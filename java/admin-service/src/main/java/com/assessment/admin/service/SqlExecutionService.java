package com.assessment.admin.service;

import com.assessment.admin.model.DatabaseConfig;
import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.Driver;
import com.assessment.admin.repository.DatabaseConfigRepository;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.DriverRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.File;
import java.net.URL;
import java.net.URLClassLoader;
import java.sql.*;
import java.util.*;

/**
 * SQL 执行服务
 * 通过动态加载的 JDBC 驱动执行用户生成的 SQL
 */
@Service
public class SqlExecutionService {

    static final int QUERY_TIMEOUT_SECONDS = 60;
    static final int MAX_RETURNED_ROWS = 1000;
    static final int MAX_SQL_LENGTH = 100_000;

    private static final Set<String> FORBIDDEN_SQL_TOKENS = Set.of(
            "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "REPLACE",
            "TRUNCATE", "DROP", "ALTER", "CREATE", "RENAME", "COMMENT",
            "GRANT", "REVOKE", "DENY", "COMMIT", "ROLLBACK", "SAVEPOINT",
            "TRANSACTION", "SET", "USE", "PRAGMA",
            "CALL", "EXEC", "EXECUTE", "DO", "BEGIN", "DECLARE", "PREPARE",
            "DEALLOCATE", "HANDLER", "ANALYZE", "VACUUM", "OPTIMIZE", "REINDEX",
            "CLUSTER", "REFRESH", "ATTACH", "DETACH", "KILL", "SHUTDOWN",
            "INTO", "OUTFILE", "DUMPFILE", "INFILE", "COPY", "UNLOAD", "IMPORT",
            "EXPORT", "BACKUP", "RESTORE", "LOAD_FILE", "OPENROWSET", "OPENQUERY",
            "OPENDATASOURCE", "BULK", "XP_CMDSHELL",
            "LOCK", "UNLOCK", "SHARE", "NOWAIT", "NEXTVAL", "SETVAL",
            "GET_LOCK", "RELEASE_LOCK", "PG_SLEEP", "PG_ADVISORY_LOCK",
            "PG_TRY_ADVISORY_LOCK", "PG_ADVISORY_XACT_LOCK", "PG_TRY_ADVISORY_XACT_LOCK",
            "PG_NOTIFY", "DBLINK", "DBLINK_EXEC", "SET_CONFIG", "LO_UNLINK",
            "PG_TERMINATE_BACKEND", "PG_CANCEL_BACKEND", "PG_RELOAD_CONF",
            "PG_READ_FILE", "PG_READ_BINARY_FILE",
            "PG_LS_DIR", "LO_IMPORT", "LO_EXPORT", "SLEEP", "BENCHMARK", "WAITFOR",
            "UTL_FILE", "UTL_HTTP", "DBMS_LOCK", "DBMS_PIPE", "DBMS_SCHEDULER"
    );

    @Autowired
    private DatasetRepository datasetRepo;

    @Autowired
    private DatabaseConfigRepository dbConfigRepo;

    @Autowired
    private DriverRepository driverRepo;

    /**
     * 在指定数据集关联的数据库上执行 SQL 查询
     */
    public Map<String, Object> executeSql(String datasetId, String sql) {
        Optional<String> validationError = validateReadOnlySql(sql);
        if (validationError.isPresent()) return errorMap(validationError.get());
        sql = stripTrailingSemicolon(sql);

        // 2. 获取数据集
        Optional<Dataset> optDs = datasetRepo.findById(datasetId);
        if (optDs.isEmpty()) return errorMap("数据集不存在");

        Dataset ds = optDs.get();
        if (ds.getDatabaseId() == null) return errorMap("数据集未关联数据库");
        Optional<String> scopeError = validateDatasetScope(sql, ds.getTableName());
        if (scopeError.isPresent()) return errorMap(scopeError.get());

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(ds.getDatabaseId());
        if (optDb.isEmpty()) return errorMap("数据库配置不存在");

        DatabaseConfig dbConfig = optDb.get();

        // 3. 获取驱动
        Driver driver = findDriver(dbConfig.getType());
        if (driver == null) return errorMap("未找到驱动: " + dbConfig.getType());

        String url = buildJdbcUrl(driver, dbConfig);

        // 数据集查询保留原有的字符串化结果，避免影响现有前端显示。
        try (Connection conn = getConnection(driver, url, dbConfig.getUsername(), dbConfig.getPassword())) {
            return executeReadOnlyQuery(conn, sql, true);
        } catch (Exception e) {
            return executionError(e);
        }
    }

    /**
     * 在指定数据库配置上执行 SQL（不关联数据集）
     */
    public Map<String, Object> executeSqlOnDatabase(String dbConfigId, String sql) {
        // 不能依赖 Python 上游校验：这个 HTTP 入口自身建立完整安全边界。
        Optional<String> validationError = validateReadOnlySql(sql);
        if (validationError.isPresent()) return errorMap(validationError.get());
        sql = stripTrailingSemicolon(sql);

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(dbConfigId);
        if (optDb.isEmpty()) return errorMap("数据库配置不存在");

        DatabaseConfig dbConfig = optDb.get();
        Driver driver = findDriver(dbConfig.getType());
        if (driver == null) return errorMap("未找到驱动: " + dbConfig.getType());

        String url = buildJdbcUrl(driver, dbConfig);

        try (Connection conn = getConnection(driver, url, dbConfig.getUsername(), dbConfig.getPassword())) {
            return executeReadOnlyQuery(conn, sql, false);
        } catch (Exception e) {
            return executionError(e);
        }
    }

    // ====== 内部辅助 ======

    /**
     * 严格校验单条、只读的 SELECT/CTE。字符串和引用标识符中的关键字会被忽略，
     * 注释会被安全跳过，但 MySQL/MariaDB 可执行注释一律拒绝。
     */
    static Optional<String> validateReadOnlySql(String sql) {
        if (sql == null || sql.trim().isEmpty()) return Optional.of("SQL不能为空");
        if (sql.length() > MAX_SQL_LENGTH) return Optional.of("SQL长度不能超过" + MAX_SQL_LENGTH + "字符");
        if (sql.indexOf('\0') >= 0) return Optional.of("SQL包含非法空字符");

        ScanResult scan = scanSql(sql);
        if (scan.error() != null) return Optional.of(scan.error());
        List<String> tokens = scan.tokens();
        if (tokens.isEmpty()) return Optional.of("SQL不能为空");

        int semicolonCount = 0;
        int semicolonIndex = -1;
        for (int i = 0; i < tokens.size(); i++) {
            if (";".equals(tokens.get(i))) {
                semicolonCount++;
                semicolonIndex = i;
            }
        }
        if (semicolonCount > 1 || (semicolonCount == 1 && semicolonIndex != tokens.size() - 1)) {
            return Optional.of("只允许执行一条SQL语句");
        }
        if (semicolonCount == 1 && !sql.stripTrailing().endsWith(";")) {
            return Optional.of("SQL结束分号后不允许附加内容");
        }

        int effectiveSize = tokens.size() - semicolonCount;
        if (effectiveSize == 0) return Optional.of("SQL不能为空");
        String first = tokens.get(0);
        if (!"SELECT".equals(first) && !"WITH".equals(first)) {
            return Optional.of("SQL必须以SELECT或WITH开头");
        }
        if ("WITH".equals(first)) {
            int depth = 0;
            boolean topLevelSelect = false;
            for (int i = 1; i < effectiveSize; i++) {
                String token = tokens.get(i);
                if ("(".equals(token)) depth++;
                else if (")".equals(token)) depth--;
                else if ("SELECT".equals(token) && depth == 0) {
                    topLevelSelect = true;
                    break;
                }
            }
            if (!topLevelSelect) return Optional.of("WITH公共表表达式最终必须执行SELECT查询");
        }

        for (int i = 0; i < effectiveSize; i++) {
            String token = tokens.get(i);
            if (FORBIDDEN_SQL_TOKENS.contains(token)) {
                return Optional.of("SQL包含禁止关键字或函数: " + token);
            }
            if ("@".equals(token) || ":=".equals(token)) {
                return Optional.of("SQL包含变量读取或赋值，禁止执行");
            }
            if (i + 1 < effectiveSize && "NEXT".equals(token) && "VALUE".equals(tokens.get(i + 1))) {
                return Optional.of("SQL包含会推进序列的NEXT VALUE操作，禁止执行");
            }
        }
        return Optional.empty();
    }

    /**
     * 数据集执行入口的表范围防线。允许从当前物理表派生 CTE/子查询，
     * 但拒绝其他表、逗号联表、跨 schema/catalog、数据库链接和表函数。
     */
    static Optional<String> validateDatasetScope(String sql, String allowedTable) {
        ScopeTokenResult allowedResult = tokenizeScopeSql(allowedTable == null ? "" : allowedTable.strip());
        if (allowedResult.error() != null || allowedResult.tokens().isEmpty()) {
            return Optional.of("数据集未关联有效物理表");
        }
        IdentifierResult allowedIdentifier = readQualifiedIdentifier(allowedResult.tokens(), 0);
        if (allowedIdentifier.parts().isEmpty() || allowedIdentifier.nextIndex() != allowedResult.tokens().size()) {
            return Optional.of("数据集物理表配置无效");
        }

        ScopeTokenResult sqlResult = tokenizeScopeSql(sql);
        if (sqlResult.error() != null) return Optional.of("SQL数据集范围解析失败: " + sqlResult.error());
        List<ScopeToken> tokens = sqlResult.tokens();
        Set<String> cteNames = collectCteNames(tokens);
        List<List<String>> references = new ArrayList<>();
        List<String> errors = new ArrayList<>();
        Set<Integer> selectDepths = new HashSet<>();
        Set<Integer> fromDepths = new HashSet<>();
        Set<Integer> expectSource = new HashSet<>();
        Set<String> clauseTerminators = Set.of(
                "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET", "FETCH",
                "UNION", "EXCEPT", "INTERSECT", "WINDOW", "QUALIFY", "RETURNING",
                "CONNECT", "START", "MODEL", "FOR"
        );
        int depth = 0;

        for (int index = 0; index < tokens.size();) {
            ScopeToken token = tokens.get(index);
            String value = token.value();
            String upper = value.toUpperCase(Locale.ROOT);

            if ("(".equals(value)) {
                // FROM (SELECT ...) 是派生表，真实物理表由内部 SELECT 捕获。
                expectSource.remove(depth);
                depth++;
                index++;
                continue;
            }
            if (")".equals(value)) {
                selectDepths.remove(depth);
                fromDepths.remove(depth);
                expectSource.remove(depth);
                depth = Math.max(0, depth - 1);
                index++;
                continue;
            }
            if (token.identifier() && "SELECT".equals(upper)) {
                selectDepths.add(depth);
                index++;
                continue;
            }
            if (token.identifier() && clauseTerminators.contains(upper)) {
                fromDepths.remove(depth);
                expectSource.remove(depth);
                index++;
                continue;
            }
            if (token.identifier() && "FROM".equals(upper) && selectDepths.contains(depth)) {
                fromDepths.add(depth);
                expectSource.add(depth);
                index++;
                continue;
            }
            if (token.identifier()
                    && Set.of("JOIN", "APPLY", "STRAIGHT_JOIN").contains(upper)
                    && fromDepths.contains(depth)) {
                expectSource.add(depth);
                index++;
                continue;
            }
            if (",".equals(value) && fromDepths.contains(depth)) {
                expectSource.add(depth);
                index++;
                continue;
            }

            if (expectSource.contains(depth)) {
                if (token.identifier() && Set.of("LATERAL", "ONLY").contains(upper)) {
                    index++;
                    continue;
                }
                if (!token.identifier()) {
                    errors.add("无法识别的数据表来源");
                    expectSource.remove(depth);
                    index++;
                    continue;
                }

                IdentifierResult identifier = readQualifiedIdentifier(tokens, index);
                int cursor = identifier.nextIndex();
                String displayName = String.join(".", identifier.parts());
                if (cursor < tokens.size() && "@".equals(tokens.get(cursor).value())) {
                    errors.add(displayName + "@数据库链接");
                } else if (cursor < tokens.size() && "(".equals(tokens.get(cursor).value())) {
                    errors.add(displayName + "(表函数)");
                } else if (identifier.parts().size() == 1
                        && cteNames.contains(identifier.parts().get(0).toLowerCase(Locale.ROOT))) {
                    // CTE 自身不属于额外物理表，其定义内部的 FROM 会单独校验。
                } else {
                    references.add(identifier.parts());
                }
                expectSource.remove(depth);
                index = Math.max(cursor, index + 1);
                continue;
            }
            index++;
        }

        if (!expectSource.isEmpty()) errors.add("缺少数据表来源");
        List<String> allowedParts = normaliseIdentifierParts(allowedIdentifier.parts());
        for (List<String> reference : references) {
            if (!normaliseIdentifierParts(reference).equals(allowedParts)) {
                errors.add("越权数据表 " + String.join(".", reference));
            }
        }
        if (references.isEmpty()) errors.add("未识别到当前数据集物理表");
        return errors.isEmpty()
                ? Optional.empty()
                : Optional.of("SQL超出当前数据集范围: " + String.join("; ", errors));
    }

    private static ScopeTokenResult tokenizeScopeSql(String sql) {
        List<ScopeToken> tokens = new ArrayList<>();
        int index = 0;
        while (index < sql.length()) {
            char ch = sql.charAt(index);
            if (Character.isWhitespace(ch) || ch == '\ufeff') {
                index++;
                continue;
            }
            if (sql.startsWith("--", index) || (ch == '#' && !sql.startsWith("#>", index))) {
                int newline = sql.indexOf('\n', index + 1);
                index = newline < 0 ? sql.length() : newline + 1;
                continue;
            }
            if (sql.startsWith("/*", index)) {
                int end = sql.indexOf("*/", index + 2);
                if (end < 0) return new ScopeTokenResult(List.of(), "块注释未闭合");
                index = end + 2;
                continue;
            }
            if (ch == '$') {
                int markerEnd = dollarQuoteMarkerEnd(sql, index);
                if (markerEnd > index) {
                    String marker = sql.substring(index, markerEnd);
                    int end = sql.indexOf(marker, markerEnd);
                    if (end < 0) return new ScopeTokenResult(List.of(), "dollar-quoted字符串未闭合");
                    tokens.add(new ScopeToken("", false));
                    index = end + marker.length();
                    continue;
                }
            }
            if ((ch == 'q' || ch == 'Q') && index + 2 < sql.length() && sql.charAt(index + 1) == '\'') {
                char opener = sql.charAt(index + 2);
                char closer = switch (opener) {
                    case '[' -> ']';
                    case '{' -> '}';
                    case '(' -> ')';
                    case '<' -> '>';
                    default -> opener;
                };
                int end = sql.indexOf(String.valueOf(closer) + "'", index + 3);
                if (end < 0) return new ScopeTokenResult(List.of(), "q-quoted字符串未闭合");
                tokens.add(new ScopeToken("", false));
                index = end + 2;
                continue;
            }
            if (ch == '\'') {
                int end = skipSingleQuoted(sql, index);
                if (end < 0) return new ScopeTokenResult(List.of(), "字符串未闭合");
                tokens.add(new ScopeToken("", false));
                index = end;
                continue;
            }
            if (ch == '"' || ch == '`' || ch == '[') {
                char closing = ch == '[' ? ']' : ch;
                StringBuilder value = new StringBuilder();
                index++;
                boolean closed = false;
                while (index < sql.length()) {
                    if (sql.charAt(index) == closing) {
                        if (index + 1 < sql.length() && sql.charAt(index + 1) == closing) {
                            value.append(closing);
                            index += 2;
                            continue;
                        }
                        index++;
                        closed = true;
                        break;
                    }
                    value.append(sql.charAt(index++));
                }
                if (!closed || value.isEmpty()) return new ScopeTokenResult(List.of(), "引用标识符无效");
                tokens.add(new ScopeToken(value.toString(), true));
                continue;
            }
            if (Character.isLetter(ch) || ch == '_' || ch == '$' || ch > 127) {
                int start = index++;
                while (index < sql.length()) {
                    char current = sql.charAt(index);
                    if (!Character.isLetterOrDigit(current)
                            && current != '_' && current != '$' && current <= 127) break;
                    index++;
                }
                tokens.add(new ScopeToken(sql.substring(start, index), true));
                continue;
            }
            if (Character.isDigit(ch)) {
                int start = index++;
                while (index < sql.length()) {
                    char current = sql.charAt(index);
                    if (!Character.isDigit(current) && ".eE+-".indexOf(current) < 0) break;
                    index++;
                }
                tokens.add(new ScopeToken(sql.substring(start, index), false));
                continue;
            }
            tokens.add(new ScopeToken(String.valueOf(ch), false));
            index++;
        }
        return new ScopeTokenResult(tokens, null);
    }

    private static int skipSingleQuoted(String sql, int start) {
        int index = start + 1;
        while (index < sql.length()) {
            if (sql.charAt(index) == '\\' && index + 1 < sql.length()) {
                index += 2;
            } else if (sql.charAt(index) == '\'' && index + 1 < sql.length()
                    && sql.charAt(index + 1) == '\'') {
                index += 2;
            } else if (sql.charAt(index) == '\'') {
                return index + 1;
            } else {
                index++;
            }
        }
        return -1;
    }

    private static Set<String> collectCteNames(List<ScopeToken> tokens) {
        Set<String> names = new HashSet<>();
        for (int index = 0; index < tokens.size(); index++) {
            ScopeToken token = tokens.get(index);
            if (!token.identifier()) continue;
            int cursor = index + 1;
            if (cursor < tokens.size() && "(".equals(tokens.get(cursor).value())) {
                int depth = 1;
                cursor++;
                while (cursor < tokens.size() && depth > 0) {
                    if ("(".equals(tokens.get(cursor).value())) depth++;
                    else if (")".equals(tokens.get(cursor).value())) depth--;
                    cursor++;
                }
            }
            if (cursor + 1 < tokens.size()
                    && "AS".equalsIgnoreCase(tokens.get(cursor).value())
                    && "(".equals(tokens.get(cursor + 1).value())) {
                boolean hasPriorWith = tokens.subList(0, index).stream()
                        .anyMatch(item -> item.identifier() && "WITH".equalsIgnoreCase(item.value()));
                if (hasPriorWith) names.add(token.value().toLowerCase(Locale.ROOT));
            }
        }
        return names;
    }

    private static IdentifierResult readQualifiedIdentifier(List<ScopeToken> tokens, int start) {
        if (start >= tokens.size() || !tokens.get(start).identifier()) {
            return new IdentifierResult(List.of(), start);
        }
        List<String> parts = new ArrayList<>();
        parts.add(tokens.get(start).value());
        int cursor = start + 1;
        while (cursor + 1 < tokens.size()
                && ".".equals(tokens.get(cursor).value())
                && tokens.get(cursor + 1).identifier()) {
            parts.add(tokens.get(cursor + 1).value());
            cursor += 2;
        }
        return new IdentifierResult(parts, cursor);
    }

    private static List<String> normaliseIdentifierParts(List<String> parts) {
        return parts.stream().map(value -> value.toLowerCase(Locale.ROOT)).toList();
    }

    private static ScanResult scanSql(String sql) {
        List<String> tokens = new ArrayList<>();
        int depth = 0;
        int i = 0;

        while (i < sql.length()) {
            char ch = sql.charAt(i);
            if (Character.isWhitespace(ch) || ch == '\ufeff') {
                i++;
                continue;
            }

            if (sql.startsWith("--", i) || (ch == '#' && !sql.startsWith("#>", i))) {
                int end = sql.indexOf('\n', i);
                if (end < 0) break;
                i = end + 1;
                continue;
            }
            if (sql.startsWith("/*", i)) {
                if (sql.startsWith("/*!", i) || sql.regionMatches(true, i, "/*M!", 0, 4)) {
                    return new ScanResult(List.of(), "不允许 MySQL/MariaDB 可执行注释");
                }
                int end = sql.indexOf("*/", i + 2);
                if (end < 0) return new ScanResult(List.of(), "SQL块注释未闭合");
                i = end + 2;
                continue;
            }

            if (ch == '$') {
                int markerEnd = dollarQuoteMarkerEnd(sql, i);
                if (markerEnd > i) {
                    String marker = sql.substring(i, markerEnd);
                    int end = sql.indexOf(marker, markerEnd);
                    if (end < 0) return new ScanResult(List.of(), "PostgreSQL dollar-quoted字符串未闭合");
                    i = end + marker.length();
                    continue;
                }
            }

            if ((ch == 'q' || ch == 'Q') && i + 2 < sql.length() && sql.charAt(i + 1) == '\'') {
                char opener = sql.charAt(i + 2);
                char closer = switch (opener) {
                    case '[' -> ']';
                    case '{' -> '}';
                    case '(' -> ')';
                    case '<' -> '>';
                    default -> opener;
                };
                int end = sql.indexOf(String.valueOf(closer) + "'", i + 3);
                if (end < 0) return new ScanResult(List.of(), "Oracle q-quoted字符串未闭合");
                i = end + 2;
                continue;
            }

            if (ch == '\'') {
                i++;
                boolean closed = false;
                while (i < sql.length()) {
                    if (sql.charAt(i) == '\\' && i + 1 < sql.length()) {
                        i += 2;
                    } else if (sql.charAt(i) == '\'' && i + 1 < sql.length() && sql.charAt(i + 1) == '\'') {
                        i += 2;
                    } else if (sql.charAt(i) == '\'') {
                        i++;
                        closed = true;
                        break;
                    } else {
                        i++;
                    }
                }
                if (!closed) return new ScanResult(List.of(), "SQL字符串未闭合");
                continue;
            }

            if (ch == '"' || ch == '`') {
                char quote = ch;
                i++;
                boolean closed = false;
                while (i < sql.length()) {
                    if (sql.charAt(i) == quote && i + 1 < sql.length() && sql.charAt(i + 1) == quote) {
                        i += 2;
                    } else if (sql.charAt(i) == quote) {
                        i++;
                        closed = true;
                        break;
                    } else {
                        i++;
                    }
                }
                if (!closed) return new ScanResult(List.of(), "SQL引用标识符未闭合");
                continue;
            }
            if (ch == '[') {
                i++;
                boolean closed = false;
                while (i < sql.length()) {
                    if (sql.charAt(i) == ']' && i + 1 < sql.length() && sql.charAt(i + 1) == ']') {
                        i += 2;
                    } else if (sql.charAt(i) == ']') {
                        i++;
                        closed = true;
                        break;
                    } else {
                        i++;
                    }
                }
                if (!closed) return new ScanResult(List.of(), "SQL Server引用标识符未闭合");
                continue;
            }

            if (Character.isLetter(ch) || ch == '_') {
                int start = i++;
                while (i < sql.length()) {
                    char current = sql.charAt(i);
                    if (!Character.isLetterOrDigit(current) && current != '_' && current != '$' && current != '#') break;
                    i++;
                }
                tokens.add(sql.substring(start, i).toUpperCase(Locale.ROOT));
                continue;
            }

            if (ch == '(') {
                depth++;
                tokens.add("(");
            } else if (ch == ')') {
                depth--;
                if (depth < 0) return new ScanResult(List.of(), "SQL括号不匹配");
                tokens.add(")");
            } else if (ch == ';') {
                tokens.add(";");
            } else if (ch == ':' && i + 1 < sql.length() && sql.charAt(i + 1) == '=') {
                tokens.add(":=");
                i += 2;
                continue;
            } else if (ch == '@') {
                tokens.add("@");
            }
            i++;
        }
        if (depth != 0) return new ScanResult(List.of(), "SQL括号不匹配");
        return new ScanResult(tokens, null);
    }

    private static int dollarQuoteMarkerEnd(String sql, int start) {
        int i = start + 1;
        if (i < sql.length() && sql.charAt(i) == '$') return i + 1;
        if (i >= sql.length() || !(Character.isLetter(sql.charAt(i)) || sql.charAt(i) == '_')) return -1;
        i++;
        while (i < sql.length() && (Character.isLetterOrDigit(sql.charAt(i)) || sql.charAt(i) == '_')) i++;
        return i < sql.length() && sql.charAt(i) == '$' ? i + 1 : -1;
    }

    private static String stripTrailingSemicolon(String sql) {
        String cleaned = sql.strip();
        return cleaned.endsWith(";") ? cleaned.substring(0, cleaned.length() - 1).stripTrailing() : cleaned;
    }

    private Map<String, Object> executeReadOnlyQuery(Connection conn, String sql, boolean stringifyValues)
            throws SQLException {
        // JDBC readOnly 是驱动级保护；显式事务 + rollback 确保即使驱动只把它视为 hint 也不提交副作用。
        conn.setReadOnly(true);
        conn.setAutoCommit(false);

        try {
            try (Statement stmt = conn.createStatement()) {
                stmt.setQueryTimeout(QUERY_TIMEOUT_SECONDS);
                // 多取一行只用于准确判断是否截断，不把第 1001 行返回给调用方。
                stmt.setMaxRows(MAX_RETURNED_ROWS + 1);
                long start = System.currentTimeMillis();

                List<String> columns = new ArrayList<>();
                List<Map<String, Object>> rows = new ArrayList<>();
                boolean truncated = false;
                try (ResultSet rs = stmt.executeQuery(sql)) {
                    ResultSetMetaData meta = rs.getMetaData();
                    int colCount = meta.getColumnCount();
                    for (int i = 1; i <= colCount; i++) columns.add(meta.getColumnLabel(i));

                    while (rs.next()) {
                        if (rows.size() >= MAX_RETURNED_ROWS) {
                            truncated = true;
                            break;
                        }
                        Map<String, Object> row = new LinkedHashMap<>();
                        for (int i = 1; i <= colCount; i++) {
                            Object value = rs.getObject(i);
                            row.put(columns.get(i - 1), stringifyValues && value != null ? value.toString() : value);
                        }
                        rows.add(row);
                    }
                }

                long elapsed = System.currentTimeMillis() - start;
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("success", true);
                result.put("columns", columns);
                result.put("rows", rows);
                // rowCount 保留向后兼容；returnedRows 是语义明确的新字段。
                result.put("rowCount", rows.size());
                result.put("returnedRows", rows.size());
                result.put("truncated", truncated);
                if (truncated) {
                    // 无 COUNT(*) 无法知道精确总数，避免把1000误报成总行数。
                    result.put("minimumTotalRows", rows.size() + 1);
                } else {
                    result.put("totalRows", rows.size());
                }
                result.put("maxRows", MAX_RETURNED_ROWS);
                result.put("executionTime", elapsed + "ms");
                result.put("message", "查询成功，返回 " + rows.size() + " 行" + (truncated ? "（已截断）" : ""));
                return result;
            }
        } finally {
            // 只读查询同样结束事务，避免连接关闭行为因驱动不同而不一致。
            conn.rollback();
        }
    }

    private Map<String, Object> executionError(Exception e) {
        return Map.of(
                "success", false,
                "message", "SQL执行失败: " + e.getClass().getSimpleName() + ": " + String.valueOf(e.getMessage()),
                "data", List.of()
        );
    }

    private record ScanResult(List<String> tokens, String error) { }
    private record ScopeToken(String value, boolean identifier) { }
    private record ScopeTokenResult(List<ScopeToken> tokens, String error) { }
    private record IdentifierResult(List<String> parts, int nextIndex) { }

    private Driver findDriver(String type) {
        if (type == null || type.isEmpty()) return null;
        Optional<Driver> opt = driverRepo.findById(type);
        if (opt.isPresent()) return opt.get();
        for (Driver d : driverRepo.findAll()) {
            if (type.equals(d.getName())) return d;
        }
        return null;
    }

    private String buildJdbcUrl(Driver driver, DatabaseConfig db) {
        return (driver.getUrlTemplate() != null ? driver.getUrlTemplate() : "")
                .replace("{host}", db.getHost())
                .replace("{port}", String.valueOf(db.getPort()))
                .replace("{database}", db.getDbName());
    }

    private Connection getConnection(Driver driver, String url, String username, String password) throws Exception {
        File jarFile = new File(driver.getJarFilePath());
        if (!jarFile.exists()) throw new Exception("驱动JAR文件不存在");

        URLClassLoader classLoader = new URLClassLoader(
                new URL[]{jarFile.toURI().toURL()},
                Thread.currentThread().getContextClassLoader()
        );
        Class<?> driverCls = Class.forName(driver.getDriverClass(), true, classLoader);
        java.sql.Driver jdbcDriver = (java.sql.Driver) driverCls.getDeclaredConstructor().newInstance();
        Properties props = new Properties();
        props.setProperty("user", username);
        props.setProperty("password", password);
        return jdbcDriver.connect(url, props);
    }

    private Map<String, Object> errorMap(String message) {
        Map<String, Object> map = new HashMap<>();
        map.put("success", false);
        map.put("message", message);
        return map;
    }
}
