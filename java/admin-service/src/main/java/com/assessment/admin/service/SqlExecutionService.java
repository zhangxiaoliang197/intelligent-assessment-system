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
        // 1. 校验并规范化为只读单语句
        try {
            sql = prepareReadOnlySql(sql);
        } catch (IllegalArgumentException e) {
            return errorMap(e.getMessage());
        }

        // 2. 获取数据集
        Optional<Dataset> optDs = datasetRepo.findById(datasetId);
        if (optDs.isEmpty()) return errorMap("数据集不存在");

        Dataset ds = optDs.get();
        if (ds.getDatabaseId() == null) return errorMap("数据集未关联数据库");

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(ds.getDatabaseId());
        if (optDb.isEmpty()) return errorMap("数据库配置不存在");

        DatabaseConfig dbConfig = optDb.get();

        // 3. 获取驱动
        Driver driver = findDriver(dbConfig.getType());
        if (driver == null) return errorMap("未找到驱动: " + dbConfig.getType());

        String url = buildJdbcUrl(driver, dbConfig);

        // 4. 执行
        try (Connection conn = getConnection(driver, url, dbConfig.getUsername(), dbConfig.getPassword());
             Statement stmt = conn.createStatement()) {

            try {
                conn.setReadOnly(true);
            } catch (SQLException ignored) {
                // 少数旧版 JDBC 驱动不支持 readOnly hint，仍由语句校验和只读账号兜底。
            }
            // 设置查询超时 60 秒
            stmt.setQueryTimeout(60);
            stmt.setMaxRows(1001);

            long start = System.currentTimeMillis();
            ResultSet rs = stmt.executeQuery(sql);
            long elapsed = System.currentTimeMillis() - start;

            // 解析结果
            ResultSetMetaData meta = rs.getMetaData();
            int colCount = meta.getColumnCount();

            // 列名
            List<String> columns = new ArrayList<>();
            for (int i = 1; i <= colCount; i++) {
                columns.add(meta.getColumnLabel(i));
            }

            // 数据行（限制最多 1000 行）
            List<Map<String, Object>> rows = new ArrayList<>();
            int rowCount = 0;
            boolean truncated = false;
            while (rs.next()) {
                if (rowCount >= 1000) {
                    truncated = true;
                    break;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= colCount; i++) {
                    Object val = rs.getObject(i);
                    row.put(columns.get(i - 1), val != null ? val.toString() : null);
                }
                rows.add(row);
                rowCount++;
            }

            return Map.of(
                    "success", true,
                    "columns", columns,
                    "rows", rows,
                    "rowCount", rows.size(),
                    "truncated", truncated,
                    "executionTime", elapsed + "ms",
                    "message", "查询成功，返回 " + rows.size() + " 行" + (truncated ? "（已截断）" : "")

            );

        } catch (Exception e) {
            return Map.of(
                    "success", false,
                    "message", "SQL执行失败: " + e.getClass().getSimpleName() + ": " + e.getMessage(),
                    "data", List.of()
            );
        }
    }

    /**
     * 在指定数据库配置上执行 SQL（不关联数据集）
     */
    public Map<String, Object> executeSqlOnDatabase(String dbConfigId, String sql) {
        try {
            sql = prepareReadOnlySql(sql);
        } catch (IllegalArgumentException e) {
            return errorMap(e.getMessage());
        }

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(dbConfigId);
        if (optDb.isEmpty()) return errorMap("数据库配置不存在");

        DatabaseConfig dbConfig = optDb.get();
        Driver driver = findDriver(dbConfig.getType());
        if (driver == null) return errorMap("未找到驱动: " + dbConfig.getType());

        String url = buildJdbcUrl(driver, dbConfig);

        try (Connection conn = getConnection(driver, url, dbConfig.getUsername(), dbConfig.getPassword());
             Statement stmt = conn.createStatement()) {

            try {
                conn.setReadOnly(true);
            } catch (SQLException ignored) {
                // 兼容不支持 readOnly hint 的 JDBC 驱动。
            }
            stmt.setQueryTimeout(60);
            stmt.setMaxRows(1001);
            long start = System.currentTimeMillis();
            ResultSet rs = stmt.executeQuery(sql);
            long elapsed = System.currentTimeMillis() - start;

            ResultSetMetaData meta = rs.getMetaData();
            int colCount = meta.getColumnCount();
            List<String> columns = new ArrayList<>();
            for (int i = 1; i <= colCount; i++) {
                columns.add(meta.getColumnLabel(i));
            }

            List<Map<String, Object>> rows = new ArrayList<>();
            int rowCount = 0;
            boolean truncated = false;
            while (rs.next()) {
                if (rowCount >= 1000) {
                    truncated = true;
                    break;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= colCount; i++) {
                    Object value = rs.getObject(i);
                    row.put(columns.get(i - 1), value != null ? value.toString() : null);
                }
                rows.add(row);
                rowCount++;
            }

            return Map.of(
                    "success", true,
                    "columns", columns,
                    "rows", rows,
                    "rowCount", rows.size(),
                    "truncated", truncated,
                    "executionTime", elapsed + "ms",
                    "message", "查询成功，返回 " + rows.size() + " 行" + (truncated ? "（已截断）" : "")
            );

        } catch (Exception e) {
            return Map.of(
                    "success", false,
                    "message", "SQL执行失败: " + e.getMessage(),
                    "data", List.of()
            );
        }
    }

    // ====== 内部辅助 ======

    /**
     * 仅接受无注释、无多语句的 SELECT/WITH 查询。
     * WITH 仍会扫描全部危险关键字，避免数据修改 CTE 绕过入口校验。
     */
    private String prepareReadOnlySql(String sql) {
        if (sql == null || sql.trim().isEmpty()) {
            throw new IllegalArgumentException("SQL不能为空");
        }

        String normalized = sql.trim();
        if (normalized.endsWith(";")) {
            normalized = normalized.substring(0, normalized.length() - 1).trim();
        }
        if (normalized.contains(";") || normalized.contains("--")
                || normalized.contains("/*") || normalized.contains("*/")) {
            throw new IllegalArgumentException("SQL只允许一条无注释的只读查询");
        }

        String sqlUpper = normalized.toUpperCase(Locale.ROOT).replaceAll("\\s+", " ");
        if (!sqlUpper.startsWith("SELECT") && !sqlUpper.startsWith("WITH")) {
            throw new IllegalArgumentException("只允许执行SELECT或WITH查询");
        }

        String[] forbidden = {
                "INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE", "TRUNCATE",
                "DROP", "ALTER", "CREATE", "RENAME", "GRANT", "REVOKE",
                "CALL", "EXEC", "EXECUTE", "INTO", "OUTFILE", "DUMPFILE",
                "LOAD_FILE", "FOR UPDATE", "LOCK IN SHARE MODE"
        };
        for (String keyword : forbidden) {
            String pattern = ".*\\b" + keyword.replace(" ", "\\s+") + "\\b.*";
            if (sqlUpper.matches(pattern)) {
                throw new IllegalArgumentException("禁止执行非只读操作: " + keyword);
            }
        }

        // SELECT 本身也可能调用阻塞、改写序列、读取文件或发起外部网络访问的函数。
        String functionScan = sqlUpper
                .replace("\"", "")
                .replace("`", "")
                .replace("[", "")
                .replace("]", "");
        String[] forbiddenFunctions = {
                "PG_SLEEP", "SLEEP", "BENCHMARK", "NEXTVAL", "SETVAL",
                "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "PG_STAT_FILE",
                "PG_TERMINATE_BACKEND", "PG_CANCEL_BACKEND",
                "PG_ROTATE_LOGFILE", "PG_LOGICAL_EMIT_MESSAGE", "PG_NOTIFY",
                "PG_ADVISORY_LOCK", "PG_ADVISORY_LOCK_SHARED",
                "PG_ADVISORY_XACT_LOCK", "PG_ADVISORY_XACT_LOCK_SHARED",
                "PG_TRY_ADVISORY_LOCK", "PG_TRY_ADVISORY_LOCK_SHARED",
                "PG_TRY_ADVISORY_XACT_LOCK", "PG_TRY_ADVISORY_XACT_LOCK_SHARED",
                "PG_ADVISORY_UNLOCK", "PG_ADVISORY_UNLOCK_SHARED", "PG_ADVISORY_UNLOCK_ALL",
                "DBLINK", "DBLINK_CONNECT", "DBLINK_EXEC", "DBLINK_SEND_QUERY",
                "QUERY_TO_XML", "QUERY_TO_XMLSCHEMA",
                "TABLE_TO_XML", "TABLE_TO_XMLSCHEMA", "TABLE_TO_XML_AND_XMLSCHEMA",
                "SCHEMA_TO_XML", "SCHEMA_TO_XMLSCHEMA", "SCHEMA_TO_XML_AND_XMLSCHEMA",
                "DATABASE_TO_XML", "DATABASE_TO_XMLSCHEMA", "DATABASE_TO_XML_AND_XMLSCHEMA",
                "CURSOR_TO_XML", "CURSOR_TO_XMLSCHEMA",
                "LO_IMPORT", "LO_EXPORT", "LOAD_FILE", "SYS_EVAL", "SYS_EXEC",
                "GET_LOCK", "RELEASE_LOCK", "IS_FREE_LOCK", "IS_USED_LOCK", "MASTER_POS_WAIT"
        };
        for (String function : forbiddenFunctions) {
            String pattern = ".*\\b" + function + "\\s*\\(.*";
            if (functionScan.matches(pattern)) {
                throw new IllegalArgumentException("禁止调用高风险数据库函数: " + function);
            }
        }
        String[] forbiddenPackages = {
                "UTL_HTTP", "UTL_INADDR", "DBMS_LDAP", "DBMS_PIPE", "DBMS_LOCK",
                "DBMS_XMLGEN", "DBMS_SQL"
        };
        for (String packageName : forbiddenPackages) {
            String pattern = ".*\\b" + packageName + "\\s*\\..*";
            if (functionScan.matches(pattern)) {
                throw new IllegalArgumentException("禁止调用高风险数据库包: " + packageName);
            }
        }
        return normalized;
    }

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
