package com.assessment.admin.service;

import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.Statement;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 不依赖第三方测试框架的安全回归测试；Maven testCompile 会编译，CI 可直接运行 main。
 */
public final class SqlExecutionServiceSecurityTest {

    private static final List<String> ALLOWED = List.of(
            "SELECT id, name FROM public.orders WHERE note = 'DROP; -- text';",
            "SELECT \"update\", [delete], `create` FROM mixed_identifiers",
            "WITH RECURSIVE tree AS (SELECT id FROM nodes UNION ALL SELECT n.id FROM nodes n JOIN tree t ON n.parent_id=t.id) SELECT * FROM tree",
            "SELECT payload #>> '{user,name}' FROM events",
            "SELECT q'[text; DROP is not SQL here]' AS content FROM dual",
            "SELECT $$semicolon; CALL hidden()$$ AS content",
            "SELECT /*+ INDEX(orders idx_orders) */ id FROM orders"
    );

    private static final List<String> BLOCKED = List.of(
            "SELECT 1; CALL dangerous_proc()",
            "SELECT 1;;",
            "SELECT 1; -- trailing content",
            "WITH data AS (SELECT 1) VALUES (1)",
            "SELECT * FROM users INTO OUTFILE '/tmp/users.csv'",
            "SELECT * INTO copied_users FROM users",
            "SELECT LOAD_FILE('/etc/passwd')",
            "SELECT nextval('sequence_name')",
            "SELECT pg_advisory_lock(42)",
            "SELECT set_config('search_path', 'public', false)",
            "SELECT * FROM dblink('remote', 'DELETE FROM users RETURNING *') AS t(id int)",
            "SELECT get_lock('name', 30)",
            "SELECT pg_sleep(30)",
            "SELECT NEXT VALUE FOR order_sequence",
            "SELECT * FROM users FOR UPDATE",
            "SELECT * FROM users FOR SHARE",
            "SELECT @value := 1",
            "WITH removed AS (DELETE FROM users RETURNING *) SELECT * FROM removed",
            "SELECT 1 /*!50000 INTO OUTFILE '/tmp/value' */",
            "SELECT 1 /*M! INTO OUTFILE '/tmp/value' */",
            "SEL/**/ECT 1",
            "CALL dangerous_proc()",
            "SELECT 'unterminated",
            "SELECT /* unterminated"
    );

    private static final List<String> DATASET_SCOPE_ALLOWED = List.of(
            "SELECT * FROM allowed_table",
            "SELECT * FROM `allowed_table` WHERE note = 'FROM secret_table'",
            "WITH filtered AS (SELECT * FROM allowed_table) SELECT * FROM filtered",
            "SELECT * FROM (SELECT id FROM allowed_table) derived",
            "SELECT a.id FROM allowed_table a LEFT JOIN allowed_table b ON a.id=b.id"
    );

    private static final List<String> DATASET_SCOPE_BLOCKED = List.of(
            "SELECT a.* FROM allowed_table a, secret_table b",
            "SELECT a.* FROM allowed_table a JOIN secret_table b ON a.id=b.id",
            "SELECT * FROM another_schema.allowed_table",
            "SELECT * FROM another_catalog.public.allowed_table",
            "SELECT * FROM allowed_table@remote_database",
            "SELECT * FROM table_function()",
            "SELECT * FROM allowed_table UNION ALL SELECT * FROM secret_table",
            "SELECT * FROM allowed_table, (SELECT * FROM secret_table) hidden",
            "WITH hidden AS (SELECT * FROM secret_table) SELECT * FROM hidden",
            "SELECT 1"
    );

    @Test
    void allowsExpectedQueriesAndBlocksSideEffects() throws Exception {
        for (String sql : ALLOWED) {
            if (validate(sql).isPresent()) {
                throw new AssertionError("Expected allowed SQL: " + sql + " -> "
                        + validate(sql).orElse(""));
            }
        }
        for (String sql : BLOCKED) {
            if (validate(sql).isEmpty()) {
                throw new AssertionError("Expected blocked SQL: " + sql);
            }
        }
    }

    @Test
    void enforcesDatasetTableScope() throws Exception {
        for (String sql : DATASET_SCOPE_ALLOWED) {
            if (validateScope(sql, "allowed_table").isPresent()) {
                throw new AssertionError("Expected dataset-scoped SQL: " + sql + " -> "
                        + validateScope(sql, "allowed_table").orElse(""));
            }
        }
        for (String sql : DATASET_SCOPE_BLOCKED) {
            if (validateScope(sql, "allowed_table").isEmpty()) {
                throw new AssertionError("Expected out-of-scope SQL to be blocked: " + sql);
            }
        }
    }

    @Test
    void enforcesReadOnlyTimeoutAndTruncationBoundary() throws Exception {
        verifyReadOnlyExecutionBoundary();
    }

    @SuppressWarnings("unchecked")
    private static Optional<String> validate(String sql) throws Exception {
        // 反射只用于保持该零依赖测试可由任意 Maven/JDK 环境单独编译运行。
        Class<?> serviceClass = Class.forName("com.assessment.admin.service.SqlExecutionService");
        var method = serviceClass.getDeclaredMethod("validateReadOnlySql", String.class);
        method.setAccessible(true);
        return (Optional<String>) method.invoke(null, sql);
    }

    @SuppressWarnings("unchecked")
    private static Optional<String> validateScope(String sql, String allowedTable) throws Exception {
        Class<?> serviceClass = Class.forName("com.assessment.admin.service.SqlExecutionService");
        var method = serviceClass.getDeclaredMethod("validateDatasetScope", String.class, String.class);
        method.setAccessible(true);
        return (Optional<String>) method.invoke(null, sql, allowedTable);
    }

    @SuppressWarnings("unchecked")
    private static void verifyReadOnlyExecutionBoundary() throws Exception {
        boolean[] readOnly = {false};
        boolean[] autoCommitDisabled = {false};
        boolean[] rolledBack = {false};
        int[] queryTimeout = {0};
        int[] maxRows = {0};
        int[] cursor = {0};
        int[] availableRows = {1001};

        ResultSetMetaData metadata = (ResultSetMetaData) Proxy.newProxyInstance(
                SqlExecutionServiceSecurityTest.class.getClassLoader(),
                new Class<?>[]{ResultSetMetaData.class},
                (proxy, method, args) -> switch (method.getName()) {
                    case "getColumnCount" -> 1;
                    case "getColumnLabel" -> "value";
                    default -> defaultValue(method.getReturnType());
                });

        ResultSet resultSet = (ResultSet) Proxy.newProxyInstance(
                SqlExecutionServiceSecurityTest.class.getClassLoader(),
                new Class<?>[]{ResultSet.class},
                (proxy, method, args) -> switch (method.getName()) {
                    case "next" -> ++cursor[0] <= availableRows[0];
                    case "getMetaData" -> metadata;
                    case "getObject" -> cursor[0];
                    default -> defaultValue(method.getReturnType());
                });

        Statement statement = (Statement) Proxy.newProxyInstance(
                SqlExecutionServiceSecurityTest.class.getClassLoader(),
                new Class<?>[]{Statement.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "setQueryTimeout" -> queryTimeout[0] = (int) args[0];
                        case "setMaxRows" -> maxRows[0] = (int) args[0];
                        case "executeQuery" -> { return resultSet; }
                        default -> { return defaultValue(method.getReturnType()); }
                    }
                    return null;
                });

        Connection connection = (Connection) Proxy.newProxyInstance(
                SqlExecutionServiceSecurityTest.class.getClassLoader(),
                new Class<?>[]{Connection.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "setReadOnly" -> readOnly[0] = Boolean.TRUE.equals(args[0]);
                        case "setAutoCommit" -> autoCommitDisabled[0] = Boolean.FALSE.equals(args[0]);
                        case "createStatement" -> { return statement; }
                        case "rollback" -> rolledBack[0] = true;
                        default -> { return defaultValue(method.getReturnType()); }
                    }
                    return null;
                });

        Class<?> serviceClass = Class.forName("com.assessment.admin.service.SqlExecutionService");
        Object service = serviceClass.getDeclaredConstructor().newInstance();
        Method execute = serviceClass.getDeclaredMethod(
                "executeReadOnlyQuery", Connection.class, String.class, boolean.class);
        execute.setAccessible(true);
        Map<String, Object> result = (Map<String, Object>) execute.invoke(
                service, connection, "SELECT value FROM data", false);

        require(readOnly[0], "Connection must be read-only");
        require(autoCommitDisabled[0], "Auto-commit must be disabled");
        require(rolledBack[0], "Transaction must be rolled back");
        require(queryTimeout[0] == 60, "Query timeout must be 60 seconds");
        require(maxRows[0] == 1001, "JDBC maxRows must include one truncation probe row");
        require(Integer.valueOf(1000).equals(result.get("returnedRows")), "Only 1000 rows may be returned");
        require(Boolean.TRUE.equals(result.get("truncated")), "Result must report truncation");
        require(Integer.valueOf(1001).equals(result.get("minimumTotalRows")),
                "Truncated response must expose only a lower bound");
        require(!result.containsKey("totalRows"), "Truncated response must not claim an exact total");
        require(Integer.valueOf(1000).equals(result.get("maxRows")), "Response must expose the row limit");

        cursor[0] = 0;
        availableRows[0] = 12;
        Map<String, Object> completeResult = (Map<String, Object>) execute.invoke(
                service, connection, "SELECT value FROM data", false);
        require(Boolean.FALSE.equals(completeResult.get("truncated")), "Short result must not be truncated");
        require(Integer.valueOf(12).equals(completeResult.get("returnedRows")), "Short result row count mismatch");
        require(Integer.valueOf(12).equals(completeResult.get("totalRows")),
                "Only complete results may expose an exact total");
        require(!completeResult.containsKey("minimumTotalRows"),
                "Complete result must not expose a truncation lower bound");
    }

    private static Object defaultValue(Class<?> type) {
        if (!type.isPrimitive()) return null;
        if (type == boolean.class) return false;
        if (type == byte.class) return (byte) 0;
        if (type == short.class) return (short) 0;
        if (type == int.class) return 0;
        if (type == long.class) return 0L;
        if (type == float.class) return 0F;
        if (type == double.class) return 0D;
        if (type == char.class) return '\0';
        return null;
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private SqlExecutionServiceSecurityTest() { }
}
