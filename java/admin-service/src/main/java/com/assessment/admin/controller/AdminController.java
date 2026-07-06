package com.assessment.admin.controller;

import com.assessment.admin.model.DatabaseConfig;
import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.Driver;
import com.assessment.admin.model.FieldAnnotation;
import com.assessment.admin.model.Indicator;
import com.assessment.admin.model.LlmConfig;
import com.assessment.admin.repository.DatabaseConfigRepository;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.DriverRepository;
import com.assessment.admin.repository.FieldAnnotationRepository;
import com.assessment.admin.repository.IndicatorRepository;
import com.assessment.admin.repository.LlmConfigRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;

import java.io.File;
import java.io.IOException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.*;


@RestController
@RequestMapping("/api/admin")
public class AdminController {

    @Autowired
    private DatabaseConfigRepository dbConfigRepo;

    @Autowired
    private IndicatorRepository indicatorRepo;

    @Autowired
    private DatasetRepository datasetRepo;

    @Autowired
    private LlmConfigRepository llmConfigRepo;

    @Autowired
    private FieldAnnotationRepository fieldAnnotationRepo;

    @Autowired
    private DriverRepository driverRepo;

    @Value("${db.type:mysql}")
    private String dbType;

    @Value("${driver.storage-path:drivers}")
    private String driverStoragePath;

    // 驱动预设（驱动名称 → 驱动类 + URL模板）
    private static final Map<String, String[]> DRIVER_PRESETS = new LinkedHashMap<>();
    static {
        DRIVER_PRESETS.put("MySQL", new String[]{
                "com.mysql.cj.jdbc.Driver",
                "jdbc:mysql://{host}:{port}/{database}?useSSL=false&serverTimezone=Asia/Shanghai&connectionCollation=utf8mb4_unicode_ci&sessionVariables=character_set_client=utf8mb4,character_set_connection=utf8mb4,character_set_results=utf8mb4"
        });
        DRIVER_PRESETS.put("PostgreSQL", new String[]{
                "org.postgresql.Driver",
                "jdbc:postgresql://{host}:{port}/{database}"
        });
        DRIVER_PRESETS.put("Oracle", new String[]{
                "oracle.jdbc.OracleDriver",
                "jdbc:oracle:thin:@{host}:{port}:{database}"
        });
        DRIVER_PRESETS.put("达梦数据库V8.1", new String[]{
                "dm.jdbc.driver.DmDriver",
                "jdbc:dm://{host}:{port}/{database}"
        });
        DRIVER_PRESETS.put("SQL Server", new String[]{
                "com.microsoft.sqlserver.jdbc.SQLServerDriver",
                "jdbc:sqlserver://{host}:{port};databaseName={database}"
        });
    }

    // ==================== 通用 ====================
    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        return ResponseEntity.ok(Map.of("status", "healthy", "service", "admin-service", "db", dbType));
    }

    @GetMapping("/info")
    public ResponseEntity<Map<String, Object>> getInfo() {
        return ResponseEntity.ok(Map.of("service", "admin-service", "version", "3.0.0",
                "description", "基础管理系统 - MySQL持久化 + 真实JDBC连接"));
    }

    // ==================== 数据库配置管理（MySQL持久化 + 真实JDBC连接） ====================
    @GetMapping("/database/list")
    public ResponseEntity<Map<String, Object>> listDatabases() {
        List<DatabaseConfig> all = dbConfigRepo.findAll();
        List<Map<String, Object>> list = new ArrayList<>();
        for (DatabaseConfig db : all) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", db.getId());
            m.put("name", db.getName());
            m.put("type", db.getType());
            m.put("host", db.getHost());
            m.put("port", db.getPort());
            m.put("database", db.getDbName());
            m.put("username", db.getUsername());
            m.put("password", "******");
            m.put("status", db.getStatus());
            m.put("dbVersion", db.getDbVersion());
            m.put("latency", db.getLatency());
            m.put("errorMsg", db.getErrorMsg());
            m.put("createTime", db.getCreateTime() != null ? db.getCreateTime().toString() : "");
            list.add(m);
        }
        return ResponseEntity.ok(Map.of("success", true, "total", list.size(), "databases", list));
    }

    @PostMapping("/database")
    public ResponseEntity<Map<String, Object>> addDatabase(@RequestBody Map<String, Object> body) {
        DatabaseConfig db = new DatabaseConfig();
        db.setId("db_" + UUID.randomUUID().toString().substring(0, 8));
        db.setName((String) body.getOrDefault("name", ""));
        db.setType((String) body.getOrDefault("type", "MySQL"));
        db.setHost((String) body.getOrDefault("host", "localhost"));
        db.setPort(getInt(body, "port", 3306));
        db.setDbName((String) body.getOrDefault("database", ""));
        db.setUsername((String) body.getOrDefault("username", ""));
        db.setPassword((String) body.getOrDefault("password", ""));
        db.setStatus("未连接");
        dbConfigRepo.save(db);
        return ResponseEntity.ok(Map.of("success", true, "message", "数据库配置已保存", "id", db.getId()));
    }

    @PutMapping("/database/{dbId}")
    public ResponseEntity<Map<String, Object>> updateDatabase(@PathVariable String dbId,
                                                               @RequestBody Map<String, Object> body) {
        Optional<DatabaseConfig> opt = dbConfigRepo.findById(dbId);
        if (opt.isEmpty()) return ResponseEntity.notFound().build();
        DatabaseConfig db = opt.get();
        if (body.containsKey("name")) db.setName((String) body.get("name"));
        if (body.containsKey("type")) db.setType((String) body.get("type"));
        if (body.containsKey("host")) db.setHost((String) body.get("host"));
        if (body.containsKey("port")) db.setPort(getInt(body, "port", db.getPort()));
        if (body.containsKey("database")) db.setDbName((String) body.get("database"));
        if (body.containsKey("username")) db.setUsername((String) body.get("username"));
        if (body.containsKey("password")) db.setPassword((String) body.get("password"));
        db.setStatus("未连接");
        dbConfigRepo.save(db);
        return ResponseEntity.ok(Map.of("success", true, "message", "数据库配置已更新"));
    }

    @DeleteMapping("/database/{dbId}")
    public ResponseEntity<Map<String, Object>> deleteDatabase(@PathVariable String dbId) {
        dbConfigRepo.deleteById(dbId);
        return ResponseEntity.ok(Map.of("success", true, "message", "数据库配置已删除"));
    }

    @PostMapping("/database/{dbId}/test")
    public ResponseEntity<Map<String, Object>> testConnection(@PathVariable String dbId) {
        Optional<DatabaseConfig> opt = dbConfigRepo.findById(dbId);
        if (opt.isEmpty()) return ResponseEntity.notFound().build();
        DatabaseConfig db = opt.get();

        Driver driver = findDriverByType(db.getType());
        if (driver == null) {
            db.setStatus("失败");
            db.setErrorMsg("未找到匹配的数据库驱动: " + db.getType());
            dbConfigRepo.save(db);
            return ResponseEntity.ok(Map.of("success", false, "message", "未找到驱动"));
        }

        String url = (driver.getUrlTemplate() != null ? driver.getUrlTemplate() : "")
                .replace("{host}", db.getHost())
                .replace("{port}", String.valueOf(db.getPort()))
                .replace("{database}", db.getDbName());

        long start = System.currentTimeMillis();
        try {
            try (Connection conn = getJdbcConnection(driver, url, db.getUsername(), db.getPassword())) {
                long elapsed = System.currentTimeMillis() - start;
                String version = "unknown";
                try (Statement stmt = conn.createStatement();
                     ResultSet rs = stmt.executeQuery(getVersionQuery(driver.getName()))) {
                    if (rs.next()) version = rs.getString(1);
                } catch (Exception ignored) {}

                db.setStatus("已连接");
                db.setDbVersion(version);
                db.setLatency(elapsed + "ms");
                db.setErrorMsg(null);
                dbConfigRepo.save(db);
                return ResponseEntity.ok(Map.of(
                        "success", true, "message", "连接成功 (" + elapsed + "ms)",
                        "dbVersion", version, "latency", elapsed + "ms"
                ));
            }
        } catch (Exception e) {
            db.setStatus("失败");
            db.setErrorMsg(e.getClass().getSimpleName() + ": " + e.getMessage());
            dbConfigRepo.save(db);
            return ResponseEntity.ok(Map.of(
                    "success", false, "message", "连接失败: " + e.getMessage(),
                    "error", e.getClass().getSimpleName() + ": " + e.getMessage()
            ));
        }
    }

    // ==================== 驱动管理（MySQL持久化 + JAR文件上传） ====================
    @GetMapping("/driver/list")
    public ResponseEntity<Map<String, Object>> listDrivers() {
        List<Driver> all = driverRepo.findAll();
        List<Map<String, Object>> list = new ArrayList<>();
        for (Driver d : all) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", d.getId());
            m.put("name", d.getName());
            m.put("driverClass", d.getDriverClass());
            m.put("urlTemplate", d.getUrlTemplate());
            m.put("jarFileName", d.getJarFileName());
            m.put("hasJar", d.getJarFilePath() != null && !d.getJarFilePath().isEmpty());
            m.put("createTime", d.getCreateTime() != null ? d.getCreateTime().toString() : "");
            list.add(m);
        }
        return ResponseEntity.ok(Map.of("success", true, "total", list.size(), "drivers", list));
    }

    @PostMapping("/driver/upload")
    public ResponseEntity<Map<String, Object>> uploadDriver(
            @RequestParam("file") MultipartFile file,
            @RequestParam("name") String name,
            @RequestParam("type") String type) {
        if (file.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("请选择JAR文件"));
        }
        if (name == null || name.trim().isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("请输入驱动名称"));
        }
        if (type == null || type.trim().isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("请选择数据库类型"));
        }

        // 从预设获取驱动类和URL模板
        String[] preset = DRIVER_PRESETS.get(type);
        if (preset == null) {
            return ResponseEntity.badRequest().body(errorMap("不支持的数据库类型: " + type));
        }

        // 确保存储目录存在
        Path storageDir = Paths.get(driverStoragePath);
        try {
            Files.createDirectories(storageDir);
        } catch (IOException e) {
            return ResponseEntity.ok(errorMap("创建存储目录失败: " + e.getMessage()));
        }

        // 保存 JAR 文件
        String originalName = file.getOriginalFilename();
        String fileName = "driver_" + UUID.randomUUID().toString().substring(0, 8) + "_" + originalName;
        Path targetPath = storageDir.resolve(fileName);
        try {
            file.transferTo(targetPath.toFile());
        } catch (IOException e) {
            return ResponseEntity.ok(errorMap("JAR文件保存失败: " + e.getMessage()));
        }

        // 创建新驱动记录（同一种数据库可以有多个版本）
        Driver driver = new Driver();
        driver.setId("driver_" + UUID.randomUUID().toString().substring(0, 8));
        driver.setName(name.trim());
        driver.setDriverClass(preset[0]);
        driver.setUrlTemplate(preset[1]);
        driver.setJarFileName(originalName);
        driver.setJarFilePath(targetPath.toAbsolutePath().toString());
        driverRepo.save(driver);

        return ResponseEntity.ok(Map.of(
                "success", true, "message", "驱动上传成功",
                "id", driver.getId(), "jarFileName", originalName
        ));
    }

    @DeleteMapping("/driver/{driverId}")
    public ResponseEntity<Map<String, Object>> deleteDriver(@PathVariable String driverId) {
        Optional<Driver> opt = driverRepo.findById(driverId);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("驱动不存在"));
        }
        Driver driver = opt.get();

        // 删除 JAR 文件
        if (driver.getJarFilePath() != null) {
            try {
                Files.deleteIfExists(Paths.get(driver.getJarFilePath()));
            } catch (IOException ignored) {}
        }

        driverRepo.deleteById(driverId);
        return ResponseEntity.ok(Map.of("success", true, "message", "驱动已删除"));
    }

    /**
     * 根据 DatabaseConfig.type 查找 Driver（先按名称，再按ID）
     */
    private Driver findDriverByType(String type) {
        if (type == null || type.isEmpty()) return null;
        // 按ID查找
        Optional<Driver> opt = driverRepo.findById(type);
        if (opt.isPresent()) return opt.get();
        // 按名称查找（向后兼容）
        List<Driver> all = driverRepo.findAll();
        for (Driver d : all) {
            if (type.equals(d.getName())) return d;
        }
        return null;
    }

    /**
     * 通过 JDBC 连接数据库（统一使用 URLClassLoader 加载 JAR 驱动）
     */
    private Connection getJdbcConnection(Driver driver, String url, String username, String password) throws Exception {
        if (driver.getJarFilePath() == null || driver.getJarFilePath().isEmpty()) {
            throw new IOException("驱动 '" + driver.getName() + "' 尚未上传JAR包，请先在驱动管理中上传");
        }

        File jarFile = new File(driver.getJarFilePath());
        if (!jarFile.exists()) {
            throw new IOException("驱动JAR文件不存在: " + driver.getJarFilePath());
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

    // ==================== 数据库表查询 ====================
    @GetMapping("/database/{dbId}/tables")
    public ResponseEntity<Map<String, Object>> listDatabaseTables(@PathVariable String dbId) {
        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(dbId);
        if (optDb.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("数据库配置不存在"));
        }
        DatabaseConfig dbConfig = optDb.get();

        Driver driver = findDriverByType(dbConfig.getType());
        if (driver == null) {
            return ResponseEntity.badRequest().body(errorMap("不支持的数据库类型: " + dbConfig.getType()));
        }

        String jdbcUrl = (driver.getUrlTemplate() != null ? driver.getUrlTemplate() : "")
                .replace("{host}", dbConfig.getHost())
                .replace("{port}", String.valueOf(dbConfig.getPort()))
                .replace("{database}", dbConfig.getDbName());

        try {
            try (Connection conn = getJdbcConnection(driver, jdbcUrl, dbConfig.getUsername(), dbConfig.getPassword());
                 Statement stmt = conn.createStatement()) {

                String sql;
                if ("PostgreSQL".equals(driver.getName())) {
                    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name";
                } else {
                    sql = String.format(
                        "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='%s' AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
                        dbConfig.getDbName());
                }

                ResultSet rs = stmt.executeQuery(sql);
                List<Map<String, String>> tables = new ArrayList<>();
                while (rs.next()) {
                    Map<String, String> t = new HashMap<>();
                    t.put("tableName", rs.getString(1));
                    tables.add(t);
                }
                return ResponseEntity.ok(Map.of("success", true, "tables", tables, "total", tables.size()));
            }
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("success", false, "message", "读取数据表失败: " + e.getMessage()));
        }
    }

    // ==================== 数据集管理（MySQL持久化） ====================
    @GetMapping("/dataset/list")
    public ResponseEntity<Map<String, Object>> listDatasets() {
        List<Dataset> all = datasetRepo.findAll();
        List<Map<String, Object>> list = new ArrayList<>();
        for (Dataset ds : all) {
            Map<String, Object> m = new HashMap<>();
            m.put("id", ds.getId());
            m.put("name", ds.getName());
            m.put("description", ds.getDescription());
            m.put("databaseId", ds.getDatabaseId());
            m.put("tableName", ds.getTableName());
            m.put("sql", ds.getSqlText());
            m.put("records", ds.getRecords());
            m.put("lastExecuted", ds.getLastExecuted() != null ? ds.getLastExecuted().toString() : "");
            m.put("createTime", ds.getCreateTime() != null ? ds.getCreateTime().toString() : "");
            list.add(m);
        }
        return ResponseEntity.ok(Map.of("success", true, "total", list.size(), "datasets", list));
    }

    @PostMapping("/dataset")
    public ResponseEntity<Map<String, Object>> createDataset(@RequestBody Map<String, Object> body) {
        Dataset ds = new Dataset();
        ds.setId("ds_" + UUID.randomUUID().toString().substring(0, 8));
        ds.setName((String) body.getOrDefault("name", ""));
        ds.setDescription((String) body.getOrDefault("description", ""));
        ds.setDatabaseId((String) body.getOrDefault("databaseId", ""));
        ds.setTableName((String) body.getOrDefault("tableName", ""));
        ds.setSqlText((String) body.getOrDefault("sql", ""));
        datasetRepo.save(ds);
        return ResponseEntity.ok(Map.of("success", true, "message", "数据集已保存", "id", ds.getId()));
    }

    @GetMapping("/dataset/{datasetId}")
    public ResponseEntity<Map<String, Object>> getDataset(@PathVariable String datasetId) {
        Optional<Dataset> opt = datasetRepo.findById(datasetId);
        if (opt.isEmpty()) return ResponseEntity.notFound().build();
        return ResponseEntity.ok(Map.of("success", true, "data", opt.get()));
    }

    @PutMapping("/dataset/{datasetId}")
    public ResponseEntity<Map<String, Object>> updateDataset(@PathVariable String datasetId,
                                                              @RequestBody Map<String, Object> body) {
        Optional<Dataset> opt = datasetRepo.findById(datasetId);
        if (opt.isEmpty()) return ResponseEntity.notFound().build();
        Dataset ds = opt.get();
        if (body.containsKey("name")) ds.setName((String) body.get("name"));
        if (body.containsKey("description")) ds.setDescription((String) body.get("description"));
        if (body.containsKey("databaseId")) ds.setDatabaseId((String) body.get("databaseId"));
        if (body.containsKey("tableName")) ds.setTableName((String) body.get("tableName"));
        if (body.containsKey("sql")) ds.setSqlText((String) body.get("sql"));
        datasetRepo.save(ds);
        return ResponseEntity.ok(Map.of("success", true, "message", "数据集已更新"));
    }

    @DeleteMapping("/dataset/{datasetId}")
    public ResponseEntity<Map<String, Object>> deleteDataset(@PathVariable String datasetId) {
        datasetRepo.deleteById(datasetId);
        return ResponseEntity.ok(Map.of("success", true, "message", "数据集已删除"));
    }

    // ==================== 指标管理（MySQL持久化） ====================
    @GetMapping("/indicator/list")
    public ResponseEntity<Map<String, Object>> listIndicators() {
        List<Indicator> all = indicatorRepo.findAll();
        return ResponseEntity.ok(Map.of("success", true, "total", all.size(), "indicators", all));
    }

    @PostMapping("/indicator")
    public ResponseEntity<Map<String, Object>> createIndicator(@RequestBody Map<String, Object> body) {
        Indicator ind = new Indicator();
        ind.setId("ind_" + UUID.randomUUID().toString().substring(0, 8));
        ind.setName((String) body.getOrDefault("name", ""));
        ind.setCategory((String) body.getOrDefault("category", ""));
        ind.setFormula((String) body.getOrDefault("formula", ""));
        ind.setDescription((String) body.getOrDefault("description", ""));
        if (body.containsKey("weight") && body.get("weight") != null) {
            Object w = body.get("weight");
            ind.setWeight(w instanceof Double ? (Double) w : Double.valueOf(String.valueOf(w)));
        }
        indicatorRepo.save(ind);
        return ResponseEntity.ok(Map.of("success", true, "message", "指标已保存", "id", ind.getId()));
    }

    @GetMapping("/indicator/{indicatorId}")
    public ResponseEntity<Map<String, Object>> getIndicator(@PathVariable String indicatorId) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) return ResponseEntity.notFound().build();
        return ResponseEntity.ok(Map.of("success", true, "data", opt.get()));
    }

    @PutMapping("/indicator/{indicatorId}")
    public ResponseEntity<Map<String, Object>> updateIndicator(@PathVariable String indicatorId,
                                                                @RequestBody Map<String, Object> body) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) return ResponseEntity.notFound().build();
        Indicator ind = opt.get();
        if (body.containsKey("name")) ind.setName((String) body.get("name"));
        if (body.containsKey("category")) ind.setCategory((String) body.get("category"));
        if (body.containsKey("formula")) ind.setFormula((String) body.get("formula"));
        if (body.containsKey("description")) ind.setDescription((String) body.get("description"));
        if (body.containsKey("weight") && body.get("weight") != null) {
            Object w = body.get("weight");
            ind.setWeight(w instanceof Double ? (Double) w : Double.valueOf(String.valueOf(w)));
        }
        indicatorRepo.save(ind);
        return ResponseEntity.ok(Map.of("success", true, "message", "指标已更新"));
    }

    @DeleteMapping("/indicator/{indicatorId}")
    public ResponseEntity<Map<String, Object>> deleteIndicator(@PathVariable String indicatorId) {
        indicatorRepo.deleteById(indicatorId);
        return ResponseEntity.ok(Map.of("success", true, "message", "指标已删除"));
    }

    // ==================== 大模型配置 多配置管理 ====================

    /** 列出所有大模型配置 */
    @GetMapping("/config/llm/list")
    public ResponseEntity<Map<String, Object>> listLlmConfigs() {
        List<LlmConfig> configs = llmConfigRepo.findAll();
        if (configs.isEmpty()) {
            // 首次使用，返回默认配置提示
            LlmConfig defaultCfg = new LlmConfig();
            defaultCfg.setId("llm_default");
            defaultCfg.setName("DeepSeek 默认");
            defaultCfg.setType("deepseek");
            defaultCfg.setApiUrl("https://api.deepseek.com/v1");
            defaultCfg.setApiKey("");
            defaultCfg.setModel("deepseek-chat");
            defaultCfg.setTemperature(0.7);
            defaultCfg.setMaxTokens(2000);
            defaultCfg.setTopP(0.9);
            defaultCfg.setIsActive(false);
            llmConfigRepo.save(defaultCfg);
            configs = llmConfigRepo.findAll();
        }
        return ResponseEntity.ok(Map.of("success", true, "configs", configs, "total", configs.size()));
    }

    /** 保存/创建大模型配置 */
    @PostMapping("/config/llm")
    public ResponseEntity<Map<String, Object>> createLlmConfig(@RequestBody Map<String, Object> body) {
        LlmConfig config = new LlmConfig();
        config.setId("llm_" + System.currentTimeMillis());
        config.setName((String) body.getOrDefault("name", ""));
        config.setType((String) body.getOrDefault("type", "deepseek"));
        config.setApiUrl((String) body.getOrDefault("apiUrl", ""));
        config.setApiKey((String) body.getOrDefault("apiKey", ""));
        config.setModel((String) body.getOrDefault("model", ""));
        config.setTemperature(parseDouble(body.get("temperature"), 0.7));
        config.setMaxTokens(parseInt(body.get("maxTokens"), 2000));
        config.setTopP(parseDouble(body.get("topP"), 0.9));
        config.setIsActive(false);
        llmConfigRepo.save(config);
        return ResponseEntity.ok(Map.of("success", true, "id", config.getId(), "message", "大模型配置已保存"));
    }

    /** 更新大模型配置 */
    @PutMapping("/config/llm/{id}")
    public ResponseEntity<Map<String, Object>> updateLlmConfig(
            @PathVariable String id, @RequestBody Map<String, Object> body) {
        Optional<LlmConfig> opt = llmConfigRepo.findById(id);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("配置不存在"));
        }
        LlmConfig config = opt.get();
        if (body.containsKey("name")) config.setName((String) body.get("name"));
        if (body.containsKey("type")) config.setType((String) body.get("type"));
        if (body.containsKey("apiUrl")) config.setApiUrl((String) body.get("apiUrl"));
        if (body.containsKey("apiKey")) config.setApiKey((String) body.get("apiKey"));
        if (body.containsKey("model")) config.setModel((String) body.get("model"));
        if (body.containsKey("temperature")) config.setTemperature(parseDouble(body.get("temperature"), config.getTemperature()));
        if (body.containsKey("maxTokens")) config.setMaxTokens(parseInt(body.get("maxTokens"), config.getMaxTokens()));
        if (body.containsKey("topP")) config.setTopP(parseDouble(body.get("topP"), config.getTopP()));
        llmConfigRepo.save(config);
        return ResponseEntity.ok(Map.of("success", true, "message", "配置已更新"));
    }

    /** 删除大模型配置 */
    @DeleteMapping("/config/llm/{id}")
    public ResponseEntity<Map<String, Object>> deleteLlmConfig(@PathVariable String id) {
        Optional<LlmConfig> opt = llmConfigRepo.findById(id);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("配置不存在"));
        }
        llmConfigRepo.delete(opt.get());
        return ResponseEntity.ok(Map.of("success", true, "message", "配置已删除"));
    }

    /** 激活某个大模型配置（同时停用其他配置） */
    @PutMapping("/config/llm/{id}/activate")
    public ResponseEntity<Map<String, Object>> activateLlmConfig(@PathVariable String id) {
        Optional<LlmConfig> opt = llmConfigRepo.findById(id);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("配置不存在"));
        }
        LlmConfig config = opt.get();
        // 先将所有配置置为非活跃
        llmConfigRepo.findAll().forEach(c -> {
            c.setIsActive(false);
            llmConfigRepo.save(c);
        });
        // 激活目标配置
        config.setIsActive(true);
        llmConfigRepo.save(config);
        return ResponseEntity.ok(Map.of("success", true, "message", "已切换至: " + config.getName(), "activeId", id));
    }

    /** 获取当前活跃的大模型配置（供 QA 服务调用） */
    @GetMapping("/config/llm/active")
    public ResponseEntity<Map<String, Object>> getActiveLlmConfig() {
        return llmConfigRepo.findAll().stream()
                .filter(c -> c.getIsActive() != null && c.getIsActive())
                .findFirst()
                .map(config -> ResponseEntity.ok(Map.of(
                        "success", true,
                        "data", Map.of(
                                "type", config.getType(),
                                "apiUrl", config.getApiUrl(),
                                "apiKey", config.getApiKey(),
                                "model", config.getModel(),
                                "temperature", config.getTemperature() != null ? config.getTemperature() : 0.7,
                                "maxTokens", config.getMaxTokens() != null ? config.getMaxTokens() : 2000,
                                "topP", config.getTopP() != null ? config.getTopP() : 0.9
                        )
                )))
                .orElse(ResponseEntity.ok(Map.of(
                        "success", false,
                        "message", "无活跃配置",
                        "data", Map.of(
                                "type", "deepseek",
                                "apiUrl", "https://api.deepseek.com/v1",
                                "apiKey", "",
                                "model", "deepseek-chat",
                                "temperature", 0.7,
                                "maxTokens", 2000,
                                "topP", 0.9
                        )
                )));
    }

    private double parseDouble(Object val, double defaultVal) {
        if (val == null) return defaultVal;
        return val instanceof Double ? (Double) val : Double.parseDouble(String.valueOf(val));
    }
    private int parseInt(Object val, int defaultVal) {
        if (val == null) return defaultVal;
        return val instanceof Integer ? (Integer) val : Integer.parseInt(String.valueOf(val));
    }
    private Map<String, Object> errorMap(String message) {
        Map<String, Object> map = new java.util.HashMap<>();
        map.put("success", false);
        map.put("message", message);
        return map;
    }

    // ==================== 数据表结构读取 ====================
    @PostMapping("/dataset/{datasetId}/read-structure")
    public ResponseEntity<Map<String, Object>> readTableStructure(
            @PathVariable String datasetId,
            @RequestBody Map<String, String> body) {
        Optional<Dataset> optDs = datasetRepo.findById(datasetId);
        if (optDs.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据集不存在"));
        }
        Dataset ds = optDs.get();
        if (ds.getDatabaseId() == null) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据集未关联数据库"));
        }

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(ds.getDatabaseId());
        if (optDb.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "关联的数据库配置不存在"));
        }

        String tableName = body.getOrDefault("tableName", "");
        if (tableName.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "表名不能为空"));
        }

        // Save tableName to dataset
        ds.setTableName(tableName);
        datasetRepo.save(ds);

        return readTableColumns(optDb.get(), tableName);
    }

    @GetMapping("/dataset/{datasetId}/structure")
    public ResponseEntity<Map<String, Object>> getTableStructure(@PathVariable String datasetId) {
        Optional<Dataset> optDs = datasetRepo.findById(datasetId);
        if (optDs.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据集不存在"));
        }
        Dataset ds = optDs.get();
        if (ds.getTableName() == null || ds.getDatabaseId() == null) {
            return ResponseEntity.ok(Map.of("success", true, "columns", List.of(), "message", "未读取表结构"));
        }

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(ds.getDatabaseId());
        if (optDb.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据库配置不存在"));
        }

        return readTableColumns(optDb.get(), ds.getTableName());
    }

    private ResponseEntity<Map<String, Object>> readTableColumns(DatabaseConfig dbConfig, String tableName) {
        Driver driver = findDriverByType(dbConfig.getType());
        if (driver == null) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "不支持的数据库类型: " + dbConfig.getType()));
        }

        String jdbcUrl = (driver.getUrlTemplate() != null ? driver.getUrlTemplate() : "")
                .replace("{host}", dbConfig.getHost())
                .replace("{port}", String.valueOf(dbConfig.getPort()))
                .replace("{database}", dbConfig.getDbName());

        try {
            try (Connection conn = getJdbcConnection(driver, jdbcUrl, dbConfig.getUsername(), dbConfig.getPassword());
                 Statement stmt = conn.createStatement()) {

                String sql;
                if ("PostgreSQL".equals(driver.getName())) {
                    sql = String.format(
                        "SELECT column_name, data_type, is_nullable, " +
                        "CASE WHEN EXISTS (SELECT 1 FROM information_schema.table_constraints tc " +
                        "JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name " +
                        "WHERE tc.table_name = '%s' AND tc.constraint_type = 'PRIMARY KEY' " +
                        "AND kcu.column_name = c.column_name) THEN 'YES' ELSE 'NO' END AS is_pk, " +
                        "COALESCE(pgd.description, '') AS column_comment " +
                        "FROM information_schema.columns c " +
                        "LEFT JOIN pg_catalog.pg_description pgd ON pgd.objsubid = c.ordinal_position " +
                        "AND pgd.objoid = (SELECT oid FROM pg_class WHERE relname = '%s') " +
                        "WHERE c.table_name = '%s' ORDER BY c.ordinal_position",
                        tableName, tableName, tableName);
                } else {
                    sql = String.format(
                        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, " +
                        "IF(COLUMN_KEY='PRI','YES','NO') AS IS_PK, " +
                        "COALESCE(COLUMN_COMMENT,'') AS COLUMN_COMMENT " +
                        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='%s' AND TABLE_NAME='%s' " +
                        "ORDER BY ORDINAL_POSITION",
                        dbConfig.getDbName(), tableName);
                }

                ResultSet rs = stmt.executeQuery(sql);
                List<Map<String, Object>> columns = new ArrayList<>();
                while (rs.next()) {
                    Map<String, Object> col = new LinkedHashMap<>();
                    col.put("columnName", rs.getString(1));
                    col.put("dataType", rs.getString(2));
                    col.put("isNullable", "YES".equalsIgnoreCase(rs.getString(3)));
                    col.put("isPrimaryKey", "YES".equalsIgnoreCase(rs.getString(4)));
                    col.put("comment", rs.getString(5) != null ? rs.getString(5) : "");
                    columns.add(col);
                }

                return ResponseEntity.ok(Map.of("success", true, "tableName", tableName, "columns", columns, "count", columns.size()));
            }
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("success", false, "message", "读取表结构失败: " + e.getMessage()));
        }
    }

    // ==================== 字段标注 ====================
    @GetMapping("/dataset/{datasetId}/fields")
    public ResponseEntity<Map<String, Object>> getFields(@PathVariable String datasetId) {
        List<FieldAnnotation> fields = fieldAnnotationRepo.findByDatasetId(datasetId);
        return ResponseEntity.ok(Map.of("success", true, "fields", fields, "total", fields.size()));
    }

    @PostMapping("/dataset/{datasetId}/fields")
    public ResponseEntity<Map<String, Object>> saveFieldAnnotations(
            @PathVariable String datasetId,
            @RequestBody List<Map<String, Object>> body) {
        Optional<Dataset> optDs = datasetRepo.findById(datasetId);
        if (optDs.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据集不存在"));
        }
        Dataset ds = optDs.get();

        // Delete existing annotations for this dataset
        fieldAnnotationRepo.deleteByDatasetId(datasetId);

        // Save new annotations
        for (Map<String, Object> item : body) {
            FieldAnnotation fa = new FieldAnnotation();
            fa.setId("fa_" + UUID.randomUUID().toString().substring(0, 8));
            fa.setDatasetId(datasetId);
            fa.setTableName(ds.getTableName());
            fa.setColumnName((String) item.get("columnName"));
            fa.setColumnType((String) item.get("columnType"));
            fa.setIsPrimaryKey(item.get("isPrimaryKey") instanceof Boolean ? (Boolean) item.get("isPrimaryKey") : false);
            fa.setIsNullable(item.get("isNullable") instanceof Boolean ? (Boolean) item.get("isNullable") : false);
            fa.setColumnComment((String) item.get("columnComment"));
            fa.setAnnotation((String) item.get("annotation"));
            fa.setBusinessMeaning((String) item.get("businessMeaning"));
            fa.setDataCategory((String) item.get("dataCategory"));
            fieldAnnotationRepo.save(fa);
        }

        return ResponseEntity.ok(Map.of("success", true, "message", "标注已保存", "total", body.size()));
    }

    @PutMapping("/dataset/{datasetId}/fields/{fieldId}")
    public ResponseEntity<Map<String, Object>> updateFieldAnnotation(
            @PathVariable String datasetId,
            @PathVariable String fieldId,
            @RequestBody Map<String, Object> body) {
        Optional<FieldAnnotation> opt = fieldAnnotationRepo.findById(fieldId);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "标注不存在"));
        }
        FieldAnnotation fa = opt.get();
        if (body.containsKey("annotation")) fa.setAnnotation((String) body.get("annotation"));
        if (body.containsKey("businessMeaning")) fa.setBusinessMeaning((String) body.get("businessMeaning"));
        if (body.containsKey("dataCategory")) fa.setDataCategory((String) body.get("dataCategory"));
        fieldAnnotationRepo.save(fa);
        return ResponseEntity.ok(Map.of("success", true, "message", "标注已更新"));
    }

    // ==================== 指标关联 ====================
    @PostMapping("/indicator/{indicatorId}/link-dataset")
    public ResponseEntity<Map<String, Object>> linkDataset(
            @PathVariable String indicatorId,
            @RequestBody Map<String, Object> body) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "指标不存在"));
        }
        Indicator ind = opt.get();
        String datasetId = (String) body.get("datasetId");
        String fieldMapping = body.get("fieldMapping") != null ? body.get("fieldMapping").toString() : null;
        String calculationMethod = (String) body.get("calculationMethod");

        ind.setDatasetId(datasetId);
        ind.setFieldMapping(fieldMapping);
        ind.setCalculationMethod(calculationMethod);
        indicatorRepo.save(ind);

        return ResponseEntity.ok(Map.of("success", true, "message", "关联已保存"));
    }

    @GetMapping("/indicator/{indicatorId}/linkage")
    public ResponseEntity<Map<String, Object>> getLinkage(@PathVariable String indicatorId) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "指标不存在"));
        }
        Indicator ind = opt.get();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("datasetId", ind.getDatasetId());
        result.put("fieldMapping", ind.getFieldMapping());
        result.put("calculationMethod", ind.getCalculationMethod());

        if (ind.getDatasetId() != null) {
            List<FieldAnnotation> fields = fieldAnnotationRepo.findByDatasetId(ind.getDatasetId());
            result.put("linkedFields", fields);
            Optional<Dataset> ds = datasetRepo.findById(ind.getDatasetId());
            ds.ifPresent(d -> result.put("datasetName", d.getName()));
        }

        return ResponseEntity.ok(Map.of("success", true, "data", result));
    }

    // ==================== LLM 学习数据导出 ====================
    @GetMapping("/export/for-llm")
    public ResponseEntity<Map<String, Object>> exportForLlm() {
        List<Map<String, Object>> schemas = new ArrayList<>();
        List<Dataset> datasets = datasetRepo.findAll();

        for (Dataset ds : datasets) {
            if (ds.getTableName() == null) continue;
            List<FieldAnnotation> fields = fieldAnnotationRepo.findByDatasetId(ds.getId());
            if (fields.isEmpty()) continue;

            Map<String, Object> schema = new LinkedHashMap<>();
            schema.put("datasetName", ds.getName());
            schema.put("tableName", ds.getTableName());
            schema.put("description", ds.getDescription());
            List<Map<String, Object>> fieldList = new ArrayList<>();
            for (FieldAnnotation f : fields) {
                Map<String, Object> fd = new LinkedHashMap<>();
                fd.put("column", f.getColumnName());
                fd.put("type", f.getColumnType());
                fd.put("comment", f.getColumnComment());
                fd.put("annotation", f.getAnnotation());
                fd.put("businessMeaning", f.getBusinessMeaning());
                fd.put("category", f.getDataCategory());
                fd.put("isPrimaryKey", f.getIsPrimaryKey());
                fieldList.add(fd);
            }
            schema.put("fields", fieldList);
            schemas.add(schema);
        }

        List<Map<String, Object>> indicatorConfigs = new ArrayList<>();
        List<Indicator> indicators = indicatorRepo.findAll();
        for (Indicator ind : indicators) {
            Map<String, Object> ic = new LinkedHashMap<>();
            ic.put("name", ind.getName());
            ic.put("category", ind.getCategory());
            ic.put("formula", ind.getFormula());
            ic.put("description", ind.getDescription());
            ic.put("weight", ind.getWeight());
            ic.put("calculationMethod", ind.getCalculationMethod());
            ic.put("fieldMapping", ind.getFieldMapping());

            if (ind.getDatasetId() != null) {
                Optional<Dataset> ds = datasetRepo.findById(ind.getDatasetId());
                ds.ifPresent(d -> ic.put("linkedDataset", d.getName()));
                List<FieldAnnotation> fields = fieldAnnotationRepo.findByDatasetId(ind.getDatasetId());
                ic.put("linkedFieldsCount", fields.size());
            }
            indicatorConfigs.add(ic);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("schemas", schemas);
        result.put("indicators", indicatorConfigs);
        result.put("exportTime", java.time.LocalDateTime.now().toString());

        return ResponseEntity.ok(Map.of("success", true, "data", result));
    }

    // ==================== 辅助方法 ====================
    private int getInt(Map<String, Object> map, String key, int defaultVal) {
        Object v = map.get(key);
        if (v == null) return defaultVal;
        if (v instanceof Integer) return (Integer) v;
        return Integer.parseInt(String.valueOf(v));
    }

    private String getVersionQuery(String driverName) {
        if (driverName == null) return "SELECT 1";
        switch (driverName) {
            case "MySQL": return "SELECT VERSION()";
            case "PostgreSQL": return "SELECT version()";
            case "Oracle": return "SELECT * FROM v$version WHERE ROWNUM = 1";
            case "达梦数据库V8.1": return "SELECT SVR_VERSION FROM V$INSTANCE";
            case "SQL Server": return "SELECT @@VERSION";
            default: return "SELECT 1";
        }
    }
}
