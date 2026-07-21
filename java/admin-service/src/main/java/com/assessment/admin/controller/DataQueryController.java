package com.assessment.admin.controller;

import com.assessment.admin.model.DatabaseConfig;
import com.assessment.admin.model.Driver;
import com.assessment.admin.repository.DatabaseConfigRepository;
import com.assessment.admin.repository.DriverRepository;
import com.assessment.admin.service.SqlExecutionService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.File;
import java.net.URL;
import java.net.URLClassLoader;
import java.sql.Connection;
import java.util.*;

@RestController
@RequestMapping("/api/dataquery")
public class DataQueryController {

    @Autowired
    private DatabaseConfigRepository dbConfigRepo;

    @Autowired
    private DriverRepository driverRepo;

    @Autowired
    private SqlExecutionService sqlExecutionService;

    @PostMapping("/execute")
    public ResponseEntity<Map<String, Object>> executeQuery(@RequestBody Map<String, Object> body) {
        String databaseId = (String) body.get("databaseId");
        String sql = (String) body.get("sql");

        if (databaseId == null || databaseId.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("缺少 databaseId 参数"));
        }
        if (sql == null || sql.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("缺少 sql 参数"));
        }

        // All public SQL entry points share the same read-only validation,
        // query timeout and row limit enforced by SqlExecutionService.
        return ResponseEntity.ok(sqlExecutionService.executeSqlOnDatabase(databaseId, sql));
    }

    @PostMapping("/test-connection")
    public ResponseEntity<Map<String, Object>> testConnection(@RequestBody Map<String, Object> body) {
        String databaseId = (String) body.get("databaseId");
        if (databaseId == null || databaseId.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("缺少 databaseId 参数"));
        }

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(databaseId);
        if (optDb.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("数据库配置不存在"));
        }
        DatabaseConfig dbConfig = optDb.get();

        Driver driver = findDriverByType(dbConfig.getType());
        if (driver == null) {
            return ResponseEntity.ok(Map.of("success", false, "message", "未找到驱动"));
        }

        String jdbcUrl = (driver.getUrlTemplate() != null ? driver.getUrlTemplate() : "")
                .replace("{host}", dbConfig.getHost())
                .replace("{port}", String.valueOf(dbConfig.getPort()))
                .replace("{database}", dbConfig.getDbName());

        long start = System.currentTimeMillis();
        try (Connection conn = getJdbcConnection(driver, jdbcUrl, dbConfig.getUsername(), dbConfig.getPassword())) {
            long elapsed = System.currentTimeMillis() - start;
            return ResponseEntity.ok(Map.of("success", true, "message", "连接成功", "latency", elapsed + "ms"));
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("success", false, "message", "连接失败: " + e.getMessage()));
        }
    }

    private Driver findDriverByType(String type) {
        if (type == null || type.isEmpty()) return null;
        Optional<Driver> opt = driverRepo.findById(type);
        if (opt.isPresent()) return opt.get();
        List<Driver> all = driverRepo.findAll();
        for (Driver d : all) {
            if (type.equals(d.getName())) return d;
        }
        return null;
    }

    private Connection getJdbcConnection(Driver driver, String url, String username, String password) throws Exception {
        if (driver.getJarFilePath() == null || driver.getJarFilePath().isEmpty()) {
            throw new Exception("驱动 '" + driver.getName() + "' 尚未上传JAR包");
        }
        File jarFile = new File(driver.getJarFilePath());
        if (!jarFile.exists()) {
            throw new Exception("驱动JAR文件不存在: " + driver.getJarFilePath());
        }
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
        return Map.of("success", false, "message", message);
    }
}
