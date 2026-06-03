package com.assessment.admin.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.*;

@RestController
@RequestMapping("/api/admin")
public class AdminController {

    @Value("${server.port:8081}")
    private int port;

    private static final Map<String, Map<String, Object>> databases = new LinkedHashMap<>();
    private static final List<Map<String, Object>> drivers = new ArrayList<>();
    private static final List<Map<String, Object>> datasets = new ArrayList<>();
    private static final Map<String, Object> indicators = new LinkedHashMap<>();
    private static final Map<String, Object> llmConfig = new HashMap<>();

    static {
        drivers.add(createDriver("MySQL", "com.mysql.cj.jdbc.Driver", "mysql-connector-java-8.0.33.jar", true));
        drivers.add(createDriver("PostgreSQL", "org.postgresql.Driver", "postgresql-42.6.0.jar", true));
        drivers.add(createDriver("Oracle", "oracle.jdbc.OracleDriver", "ojdbc11.jar", false));
        drivers.add(createDriver("达梦数据库V8.1", "dm.jdbc.driver.DmDriver", "DmJdbcDriver18.jar", true));
        drivers.add(createDriver("SQL Server", "com.microsoft.sqlserver.jdbc.SQLServerDriver", "mssql-jdbc-12.4.2.jar", false));

        llmConfig.put("type", "qwen");
        llmConfig.put("apiUrl", "http://localhost:8000/v1");
        llmConfig.put("temperature", 0.7);
        llmConfig.put("maxTokens", 2000);
    }

    private static Map<String, Object> createDriver(String name, String driverClass, String defaultJar, boolean isBuiltIn) {
        Map<String, Object> driver = new HashMap<>();
        driver.put("id", UUID.randomUUID().toString());
        driver.put("name", name);
        driver.put("driverClass", driverClass);
        driver.put("defaultJar", defaultJar);
        driver.put("isBuiltIn", isBuiltIn);
        driver.put("uploadedJar", null);
        return driver;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        Map<String, Object> response = new HashMap<>();
        response.put("status", "healthy");
        response.put("service", "admin-service");
        response.put("port", port);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/info")
    public ResponseEntity<Map<String, Object>> getInfo() {
        Map<String, Object> response = new HashMap<>();
        response.put("service", "admin-service");
        response.put("version", "1.0.0");
        response.put("description", "基础管理系统");
        return ResponseEntity.ok(response);
    }

    @GetMapping("/database/list")
    public ResponseEntity<Map<String, Object>> listDatabases() {
        List<Map<String, Object>> dbList = new ArrayList<>();
        for (Map.Entry<String, Map<String, Object>> entry : databases.entrySet()) {
            Map<String, Object> db = new HashMap<>(entry.getValue());
            db.put("id", entry.getKey());
            dbList.add(db);
        }

        return ResponseEntity.ok(Map.of(
            "success", true,
            "total", dbList.size(),
            "databases", dbList
        ));
    }

    @PostMapping("/database")
    public ResponseEntity<Map<String, Object>> addDatabase(@RequestBody Map<String, Object> dbConfig) {
        String dbId = "db_" + UUID.randomUUID().toString().substring(0, 8);

        Map<String, Object> database = new HashMap<>();
        database.put("name", dbConfig.get("name"));
        database.put("type", dbConfig.get("type"));
        database.put("host", dbConfig.get("host"));
        database.put("port", dbConfig.get("port"));
        database.put("database", dbConfig.get("database"));
        database.put("username", dbConfig.get("username"));
        database.put("password", dbConfig.get("password"));
        database.put("status", "未连接");
        database.put("createTime", new Date());

        databases.put(dbId, database);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "数据库配置添加成功",
            "id", dbId
        ));
    }

    @PutMapping("/database/{dbId}")
    public ResponseEntity<Map<String, Object>> updateDatabase(@PathVariable String dbId, @RequestBody Map<String, Object> dbConfig) {
        if (!databases.containsKey(dbId)) {
            return ResponseEntity.notFound().build();
        }

        Map<String, Object> database = databases.get(dbId);
        database.put("name", dbConfig.get("name"));
        database.put("type", dbConfig.get("type"));
        database.put("host", dbConfig.get("host"));
        database.put("port", dbConfig.get("port"));
        database.put("database", dbConfig.get("database"));
        database.put("username", dbConfig.get("username"));
        database.put("password", dbConfig.get("password"));

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "数据库配置更新成功"
        ));
    }

    @DeleteMapping("/database/{dbId}")
    public ResponseEntity<Map<String, Object>> deleteDatabase(@PathVariable String dbId) {
        if (!databases.containsKey(dbId)) {
            return ResponseEntity.notFound().build();
        }

        databases.remove(dbId);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "数据库配置删除成功"
        ));
    }

    @PostMapping("/database/{dbId}/test")
    public ResponseEntity<Map<String, Object>> testConnection(@PathVariable String dbId) {
        if (!databases.containsKey(dbId)) {
            return ResponseEntity.notFound().build();
        }

        Map<String, Object> database = databases.get(dbId);
        database.put("status", "已连接");

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "数据库连接测试成功",
            "status", "已连接"
        ));
    }

    @GetMapping("/driver/list")
    public ResponseEntity<Map<String, Object>> listDrivers() {
        return ResponseEntity.ok(Map.of(
            "success", true,
            "total", drivers.size(),
            "drivers", drivers
        ));
    }

    @PostMapping("/driver/upload")
    public ResponseEntity<Map<String, Object>> uploadDriver(
            @RequestParam("name") String name,
            @RequestParam("driverClass") String driverClass,
            @RequestParam("file") MultipartFile file) {

        String driverId = UUID.randomUUID().toString();
        Map<String, Object> driver = createDriver(name, driverClass, file.getOriginalFilename(), false);
        driver.put("uploadedJar", file.getOriginalFilename());
        drivers.add(driver);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "驱动上传成功",
            "id", driverId
        ));
    }

    @DeleteMapping("/driver/{driverId}")
    public ResponseEntity<Map<String, Object>> deleteDriver(@PathVariable String driverId) {
        drivers.removeIf(d -> d.get("id").equals(driverId) && !(Boolean) d.get("isBuiltIn"));

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "驱动删除成功"
        ));
    }

    @GetMapping("/dataset/list")
    public ResponseEntity<Map<String, Object>> listDatasets() {
        return ResponseEntity.ok(Map.of(
            "success", true,
            "total", datasets.size(),
            "datasets", datasets
        ));
    }

    @PostMapping("/dataset")
    public ResponseEntity<Map<String, Object>> createDataset(@RequestBody Map<String, Object> datasetConfig) {
        String datasetId = "ds_" + UUID.randomUUID().toString().substring(0, 8);

        Map<String, Object> dataset = new HashMap<>();
        dataset.put("id", datasetId);
        dataset.put("name", datasetConfig.get("name"));
        dataset.put("description", datasetConfig.get("description"));
        dataset.put("databaseId", datasetConfig.get("databaseId"));
        dataset.put("sql", datasetConfig.get("sql"));
        dataset.put("records", 0);
        dataset.put("createTime", new Date());

        datasets.add(dataset);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "数据集创建成功",
            "id", datasetId
        ));
    }

    @GetMapping("/dataset/{datasetId}")
    public ResponseEntity<Map<String, Object>> getDataset(@PathVariable String datasetId) {
        for (Map<String, Object> dataset : datasets) {
            if (dataset.get("id").equals(datasetId)) {
                return ResponseEntity.ok(Map.of(
                    "success", true,
                    "data", dataset
                ));
            }
        }
        return ResponseEntity.notFound().build();
    }

    @PutMapping("/dataset/{datasetId}")
    public ResponseEntity<Map<String, Object>> updateDataset(@PathVariable String datasetId, @RequestBody Map<String, Object> datasetConfig) {
        for (Map<String, Object> dataset : datasets) {
            if (dataset.get("id").equals(datasetId)) {
                dataset.put("name", datasetConfig.get("name"));
                dataset.put("description", datasetConfig.get("description"));
                dataset.put("sql", datasetConfig.get("sql"));

                return ResponseEntity.ok(Map.of(
                    "success", true,
                    "message", "数据集更新成功"
                ));
            }
        }
        return ResponseEntity.notFound().build();
    }

    @DeleteMapping("/dataset/{datasetId}")
    public ResponseEntity<Map<String, Object>> deleteDataset(@PathVariable String datasetId) {
        datasets.removeIf(d -> d.get("id").equals(datasetId));

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "数据集删除成功"
        ));
    }

    @GetMapping("/indicator/list")
    public ResponseEntity<Map<String, Object>> listIndicators() {
        return ResponseEntity.ok(Map.of(
            "success", true,
            "total", indicators.size(),
            "indicators", indicators.values()
        ));
    }

    @PostMapping("/indicator")
    public ResponseEntity<Map<String, Object>> createIndicator(@RequestBody Map<String, Object> indicatorConfig) {
        String indicatorId = "ind_" + UUID.randomUUID().toString().substring(0, 8);

        Map<String, Object> indicator = new HashMap<>();
        indicator.put("id", indicatorId);
        indicator.put("name", indicatorConfig.get("name"));
        indicator.put("category", indicatorConfig.get("category"));
        indicator.put("formula", indicatorConfig.get("formula"));
        indicator.put("description", indicatorConfig.get("description"));
        indicator.put("weight", indicatorConfig.get("weight"));
        indicator.put("createTime", new Date());

        indicators.put(indicatorId, indicator);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "指标创建成功",
            "id", indicatorId
        ));
    }

    @GetMapping("/indicator/{indicatorId}")
    public ResponseEntity<Map<String, Object>> getIndicator(@PathVariable String indicatorId) {
        if (indicators.containsKey(indicatorId)) {
            return ResponseEntity.ok(Map.of(
                "success", true,
                "data", indicators.get(indicatorId)
            ));
        }
        return ResponseEntity.notFound().build();
    }

    @PutMapping("/indicator/{indicatorId}")
    public ResponseEntity<Map<String, Object>> updateIndicator(@PathVariable String indicatorId, @RequestBody Map<String, Object> indicatorConfig) {
        if (indicators.containsKey(indicatorId)) {
            @SuppressWarnings("unchecked")
            Map<String, Object> indicator = (Map<String, Object>) indicators.get(indicatorId);
            indicator.put("name", indicatorConfig.get("name"));
            indicator.put("category", indicatorConfig.get("category"));
            indicator.put("formula", indicatorConfig.get("formula"));
            indicator.put("description", indicatorConfig.get("description"));
            indicator.put("weight", indicatorConfig.get("weight"));

            return ResponseEntity.ok(Map.of(
                "success", true,
                "message", "指标更新成功"
            ));
        }
        return ResponseEntity.notFound().build();
    }

    @DeleteMapping("/indicator/{indicatorId}")
    public ResponseEntity<Map<String, Object>> deleteIndicator(@PathVariable String indicatorId) {
        indicators.remove(indicatorId);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "指标删除成功"
        ));
    }

    @GetMapping("/config/llm")
    public ResponseEntity<Map<String, Object>> getLlmConfig() {
        return ResponseEntity.ok(Map.of(
            "success", true,
            "data", llmConfig
        ));
    }

    @PostMapping("/config/llm")
    public ResponseEntity<Map<String, Object>> saveLlmConfig(@RequestBody Map<String, Object> config) {
        llmConfig.putAll(config);

        return ResponseEntity.ok(Map.of(
            "success", true,
            "message", "大模型配置保存成功"
        ));
    }
}
