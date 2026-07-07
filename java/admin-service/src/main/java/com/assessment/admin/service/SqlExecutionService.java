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
        // 1. 校验
        if (sql == null || sql.trim().isEmpty()) {
            return errorMap("SQL不能为空");
        }

        sql = sql.trim();
        if (sql.endsWith(";")) sql = sql.substring(0, sql.length() - 1);

        // 安全检查
        String sqlUpper = sql.toUpperCase();
        String[] forbidden = {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE", "EXEC", "EXECUTE"};
        for (String keyword : forbidden) {
            if (sqlUpper.matches(".*\\b" + keyword + "\\b.*") && !sqlUpper.startsWith("SELECT")) {
                return errorMap("禁止执行非查询操作: " + keyword);
            }
        }
        if (!sqlUpper.startsWith("SELECT") && !sqlUpper.startsWith("WITH")) {
            return errorMap("只允许执行SELECT查询");
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

            // 设置查询超时 60 秒
            stmt.setQueryTimeout(60);

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
            while (rs.next() && rowCount < 1000) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= colCount; i++) {
                    Object val = rs.getObject(i);
                    row.put(columns.get(i - 1), val != null ? val.toString() : null);
                }
                rows.add(row);
                rowCount++;
            }

            boolean truncated = rs.next(); // 还有更多行

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
        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(dbConfigId);
        if (optDb.isEmpty()) return errorMap("数据库配置不存在");

        DatabaseConfig dbConfig = optDb.get();
        Driver driver = findDriver(dbConfig.getType());
        if (driver == null) return errorMap("未找到驱动: " + dbConfig.getType());

        String url = buildJdbcUrl(driver, dbConfig);

        try (Connection conn = getConnection(driver, url, dbConfig.getUsername(), dbConfig.getPassword());
             Statement stmt = conn.createStatement()) {

            stmt.setQueryTimeout(60);
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
            while (rs.next() && rowCount < 1000) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= colCount; i++) {
                    row.put(columns.get(i - 1), rs.getObject(i));
                }
                rows.add(row);
                rowCount++;
            }

            return Map.of(
                    "success", true,
                    "columns", columns,
                    "rows", rows,
                    "rowCount", rows.size(),
                    "executionTime", elapsed + "ms"
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
