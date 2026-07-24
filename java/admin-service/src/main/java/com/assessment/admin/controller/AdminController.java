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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.io.IOException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.*;


@RestController
@RequestMapping("/api/admin")
public class AdminController {

    private static final Logger logger = LoggerFactory.getLogger(AdminController.class);

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
                "jdbc:oracle:thin:@//{host}:{port}/{database}"
        });
        DRIVER_PRESETS.put("达梦数据库V8", new String[]{
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
    public ResponseEntity<Map<String, Object>> listDatabaseTables(
            @PathVariable String dbId,
            @RequestParam(defaultValue = "false") boolean includeColumns) {
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
            try (Connection conn = getJdbcConnection(driver, jdbcUrl, dbConfig.getUsername(), dbConfig.getPassword())) {
                DatabaseMetaData metadata = conn.getMetaData();
                String catalog = safeCatalog(conn);
                String schema = safeSchema(conn);
                List<Map<String, Object>> tables = new ArrayList<>();
                Set<String> seen = new HashSet<>();
                appendMetadataTables(metadata, catalog, schema, tables, seen);
                // 某些旧 JDBC 驱动不会正确实现 Connection#getSchema。仅在首轮
                // 为空时放宽 schema，再由去重和系统 schema 过滤保证目录可用。
                if (tables.isEmpty() && schema != null) {
                    appendMetadataTables(metadata, catalog, null, tables, seen);
                }
                if (tables.isEmpty()) {
                    appendMetadataTables(metadata, null, null, tables, seen);
                }
                // 兜底：Oracle/达梦 JDBC 元数据接口兼容性问题，改用直接 SQL 查询 user_tables
                if (tables.isEmpty() && isOracleLike(driver)) {
                    logger.info("触发Oracle/达梦兜底查询: driverClass={}", driver.getDriverClass());
                    appendTablesViaSql(conn, tables, seen);
                    logger.info("Oracle/达梦兜底查询结果: {} 张表", tables.size());
                }
                tables.sort(Comparator.comparing(item -> String.valueOf(item.get("tableName")), String.CASE_INSENSITIVE_ORDER));
                if (includeColumns) {
                    for (Map<String, Object> table : tables) {
                        try {
                            String tableCatalog = String.valueOf(table.getOrDefault("catalogName", ""));
                            String tableSchema = String.valueOf(table.getOrDefault("schemaName", ""));
                            List<Map<String, Object>> columns = readMetadataColumns(
                                    metadata,
                                    tableCatalog.isBlank() ? null : tableCatalog,
                                    tableSchema.isBlank() ? null : tableSchema,
                                    String.valueOf(table.get("tableName")));
                            table.put("columns", columns);
                            table.put("columnCount", columns.size());
                        } catch (SQLException metadataError) {
                            table.put("columns", List.of());
                            table.put("columnCount", 0);
                            table.put("metadataError", metadataError.getMessage());
                        }
                    }
                }
                Map<String, Object> response = new LinkedHashMap<>();
                response.put("success", true);
                response.put("tables", tables);
                response.put("total", tables.size());
                if (tables.isEmpty()) {
                    response.put("hint", "该数据库中未发现用户表，请确认当前账号有对应 schema 的查询权限");
                }
                // ── 诊断信息 ──
                Map<String, Object> diag = new LinkedHashMap<>();
                diag.put("driverName", driver.getName());
                diag.put("driverClass", driver.getDriverClass());
                diag.put("connectionCatalog", catalog);
                diag.put("connectionSchema", schema);
                diag.put("oracleFallbackTriggered", isOracleLike(driver));
                response.put("_diag", diag);
                logger.info("表列表查询完成: db={}, driver={}, catalog={}, schema={}, 结果={}张表, oracle兜底={}",
                        dbConfig.getName(), driver.getName(), catalog, schema, tables.size(), isOracleLike(driver));
                appendDatabaseProfile(response, dbConfig, metadata);
                return ResponseEntity.ok(response);
            }
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("success", false, "message", "读取数据表失败: " + e.getMessage()));
        }
    }

    // ==================== 数据库表列查询（支持多数据库） ====================
    @GetMapping("/database/{dbId}/table/{tableName}/columns")
    public ResponseEntity<Map<String, Object>> getTableColumns(
            @PathVariable String dbId,
            @PathVariable String tableName) {
        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(dbId);
        if (optDb.isEmpty()) {
            return ResponseEntity.badRequest()
                    .body(Map.of("success", false, "message", "数据库配置不存在"));
        }
        return readTableColumns(optDb.get(), tableName);
    }

    /**
     * 直接读取所选数据源中的物理表结构，不要求事先创建 Dataset 记录。
     * Skill 运行时通过这个入口按当前数据库的真实元数据选择表。
     */
    @GetMapping("/database/{dbId}/table-structure")
    public ResponseEntity<Map<String, Object>> getDatabaseTableStructure(
            @PathVariable String dbId,
            @RequestParam String tableName) {
        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(dbId);
        if (optDb.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据库配置不存在"));
        }
        return readTableColumns(optDb.get(), tableName);
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

    /** 测试大模型 API 连接 */
    @PostMapping("/config/llm/{id}/test")
    public ResponseEntity<Map<String, Object>> testLlmConnection(@PathVariable String id) {
        Optional<LlmConfig> opt = llmConfigRepo.findById(id);
        if (opt.isEmpty()) {
            return ResponseEntity.badRequest().body(errorMap("配置不存在"));
        }

        LlmConfig config = opt.get();
        String baseUrl = config.getApiUrl();
        if (baseUrl == null || baseUrl.isBlank()) {
            return ResponseEntity.ok(Map.of("success", false, "message", "API 地址为空"));
        }

        // 标准化 API URL：去掉尾部斜杠，确保以 /chat/completions 结尾
        String url = baseUrl.replaceAll("/+$", "");
        if (!url.endsWith("/chat/completions")) {
            if (!url.endsWith("/v1")) {
                url += "/v1";
            }
            url += "/chat/completions";
        }

        long start = System.currentTimeMillis();
        try {
            // 构建最小测试请求体
            String requestBody = String.format(
                "{\"model\":\"%s\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":1}",
                config.getModel() != null ? config.getModel().replace("\"", "\\\"") : "gpt-3.5-turbo"
            );

            java.net.http.HttpRequest request = java.net.http.HttpRequest.newBuilder()
                .uri(java.net.URI.create(url))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + (config.getApiKey() != null ? config.getApiKey() : ""))
                .POST(java.net.http.HttpRequest.BodyPublishers.ofString(requestBody))
                .timeout(java.time.Duration.ofSeconds(15))
                .build();

            java.net.http.HttpClient client = java.net.http.HttpClient.newBuilder()
                .connectTimeout(java.time.Duration.ofSeconds(10))
                .build();

            java.net.http.HttpResponse<String> response = client.send(request,
                java.net.http.HttpResponse.BodyHandlers.ofString());

            long elapsed = System.currentTimeMillis() - start;
            int statusCode = response.statusCode();

            if (statusCode >= 200 && statusCode < 300) {
                return ResponseEntity.ok(Map.of(
                    "success", true,
                    "message", "连接成功，API 正常响应 (" + elapsed + "ms)",
                    "latency", elapsed + "ms",
                    "statusCode", statusCode
                ));
            } else {
                // 截断错误响应体，避免过长
                String respBody = response.body();
                if (respBody != null && respBody.length() > 300) {
                    respBody = respBody.substring(0, 300) + "...";
                }
                return ResponseEntity.ok(Map.of(
                    "success", false,
                    "message", "API 返回错误 (" + statusCode + ") — " + (respBody != null ? respBody : ""),
                    "statusCode", statusCode,
                    "latency", elapsed + "ms"
                ));
            }

        } catch (Exception e) {
            long elapsed = System.currentTimeMillis() - start;
            String errorMsg = e.getMessage();
            String errorType = e.getClass().getSimpleName();

            if (errorMsg != null && (errorMsg.toLowerCase().contains("timeout") || errorMsg.contains("timed out"))) {
                return ResponseEntity.ok(Map.of(
                    "success", false,
                    "message", "连接超时 (" + elapsed + "ms)，请检查 API 地址是否正确",
                    "error", errorType + ": " + errorMsg
                ));
            }

            return ResponseEntity.ok(Map.of(
                "success", false,
                "message", "测试失败: " + (errorMsg != null ? errorMsg : errorType),
                "error", errorType + ": " + (errorMsg != null ? errorMsg : "")
            ));
        }
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
        if (!isSafeMetadataTableName(tableName)) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "表名为空或包含不支持的字符"));
        }
        tableName = tableName.trim();

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
        if (!isSafeMetadataTableName(tableName)) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "数据集表名为空或包含不支持的字符"));
        }
        tableName = tableName.trim();
        Driver driver = findDriverByType(dbConfig.getType());
        if (driver == null) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "不支持的数据库类型: " + dbConfig.getType()));
        }

        String jdbcUrl = (driver.getUrlTemplate() != null ? driver.getUrlTemplate() : "")
                .replace("{host}", dbConfig.getHost())
                .replace("{port}", String.valueOf(dbConfig.getPort()))
                .replace("{database}", dbConfig.getDbName());

        try {
            try (Connection conn = getJdbcConnection(driver, jdbcUrl, dbConfig.getUsername(), dbConfig.getPassword())) {
                DatabaseMetaData metadata = conn.getMetaData();
                List<Map<String, Object>> columns = readMetadataColumns(
                        metadata, safeCatalog(conn), safeSchema(conn), tableName);
                if (columns.isEmpty()) {
                    columns = readMetadataColumns(metadata, null, null, tableName);
                }

                Map<String, Object> response = new LinkedHashMap<>();
                response.put("success", true);
                response.put("tableName", tableName);
                response.put("columns", columns);
                response.put("count", columns.size());
                appendDatabaseProfile(response, dbConfig, metadata);
                return ResponseEntity.ok(response);
            }
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("success", false, "message", "读取表结构失败: " + e.getMessage()));
        }
    }

    private List<Map<String, Object>> readMetadataColumns(
            DatabaseMetaData metadata, String catalog, String schema, String tableName) throws SQLException {
        Set<String> primaryKeys = new HashSet<>();
        try {
            try (ResultSet rs = metadata.getPrimaryKeys(catalog, schema, tableName)) {
                while (rs.next()) {
                    String columnName = rs.getString("COLUMN_NAME");
                    if (columnName != null) primaryKeys.add(columnName.toLowerCase(Locale.ROOT));
                }
            }
        } catch (SQLException ignored) {
            // 部分旧 JDBC 驱动不支持主键元数据；仍返回字段，主键标记默认为 false。
        }

        List<Map<String, Object>> columns = new ArrayList<>();
        try (ResultSet rs = metadata.getColumns(catalog, schema, tableName, "%")) {
            while (rs.next()) {
                String columnName = rs.getString("COLUMN_NAME");
                Map<String, Object> column = new LinkedHashMap<>();
                column.put("columnName", columnName);
                column.put("dataType", Objects.toString(rs.getString("TYPE_NAME"), ""));
                column.put("isNullable", rs.getInt("NULLABLE") != DatabaseMetaData.columnNoNulls);
                column.put("isPrimaryKey", columnName != null && primaryKeys.contains(columnName.toLowerCase(Locale.ROOT)));
                column.put("comment", Objects.toString(rs.getString("REMARKS"), ""));
                column.put("ordinalPosition", rs.getInt("ORDINAL_POSITION"));
                columns.add(column);
            }
        }
        columns.sort(Comparator.comparingInt(item -> ((Number) item.get("ordinalPosition")).intValue()));
        columns.forEach(item -> item.remove("ordinalPosition"));
        return columns;
    }

    private void appendMetadataTables(
            DatabaseMetaData metadata,
            String catalog,
            String schema,
            List<Map<String, Object>> tables,
            Set<String> seen) throws SQLException {
        Set<String> systemSchemas = Set.of(
                "information_schema", "pg_catalog", "sys", "mysql", "performance_schema",
                // Oracle 系统 schema
                "system", "ctxsys", "mdsys", "xdb", "wmsys", "outln", "dbsnmp",
                "appqossys", "oracle_ocm", "dvsys", "lbacsys", "gsmadmin_internal",
                "sysman", "aux_stats$", "dip", "oem_monitor", "remotesys",
                // 达梦 系统 schema
                "sysdba", "sysauditor", "syssso",
                // SQL Server 系统 schema
                "sysadmin"
        );
        int rawCount = 0;
        try (ResultSet rs = metadata.getTables(catalog, schema, "%", new String[]{"TABLE"})) {
            while (rs.next()) {
                rawCount++;
                String tableName = rs.getString("TABLE_NAME");
                String schemaName = Objects.toString(rs.getString("TABLE_SCHEM"), "");
                if (tableName == null
                        || tableName.isBlank()
                        || systemSchemas.contains(schemaName.toLowerCase(Locale.ROOT))
                        || !seen.add(tableName.toLowerCase(Locale.ROOT))) {
                    continue;
                }
                Map<String, Object> table = new LinkedHashMap<>();
                table.put("tableName", tableName);
                table.put("schemaName", schemaName);
                table.put("catalogName", Objects.toString(rs.getString("TABLE_CAT"), ""));
                tables.add(table);
            }
        }
        if (rawCount > 0) {
            logger.info("JDBC元数据: catalog={}, schema={}, 原始={}张, 保留={}张",
                    catalog, schema, rawCount, tables.size());
        }
    }

    private String safeCatalog(Connection connection) {
        try {
            return connection.getCatalog();
        } catch (SQLException ignored) {
            return null;
        }
    }

    private String safeSchema(Connection connection) {
        try {
            return connection.getSchema();
        } catch (SQLException | AbstractMethodError ignored) {
            return null;
        }
    }

    /**
     * Attach both the configured driver type and the JDBC driver's actual
     * database product information. SQL generation uses the actual product
     * first, so a custom driver id does not accidentally select the wrong
     * dialect.
     */
    private void appendDatabaseProfile(
            Map<String, Object> target,
            DatabaseConfig dbConfig,
            DatabaseMetaData metadata) {
        target.put("databaseType", Objects.toString(dbConfig.getType(), ""));
        try {
            target.put("databaseProductName", Objects.toString(metadata.getDatabaseProductName(), ""));
        } catch (SQLException ignored) {
            target.put("databaseProductName", "");
        }
        try {
            target.put("databaseProductVersion", Objects.toString(metadata.getDatabaseProductVersion(), ""));
        } catch (SQLException ignored) {
            target.put("databaseProductVersion", "");
        }
        try {
            target.put("identifierQuoteString", Objects.toString(metadata.getIdentifierQuoteString(), "").trim());
        } catch (SQLException ignored) {
            target.put("identifierQuoteString", "");
        }
    }

    private boolean isSafeMetadataTableName(String tableName) {
        return tableName != null
                && !tableName.trim().isEmpty()
                && tableName.length() <= 256
                && tableName.matches("[\\p{L}\\p{N}_$# .-]+");
    }

    /**
     * 判断是否为 Oracle / 达梦 类数据库（使用 user_tables 兜底查询）
     * 通过 JDBC 驱动类名判断，比 Driver.name 更可靠
     */
    private boolean isOracleLike(Driver driver) {
        if (driver == null) return false;
        String cls = driver.getDriverClass();
        return cls != null && (cls.contains("oracle") || cls.contains("dm.jdbc"));
    }

    /**
     * 通过直接 SQL 查询 user_tables 获取当前用户拥有的表（兜底方案）
     * Oracle/达梦 JDBC 驱动的 getTables() 在某些版本中可能返回空，此方法作为补充。
     */
    private void appendTablesViaSql(Connection conn, List<Map<String, Object>> tables, Set<String> seen) {
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery("SELECT table_name FROM user_tables ORDER BY table_name")) {
            while (rs.next()) {
                String tableName = rs.getString(1);
                if (tableName == null || tableName.isBlank() || !seen.add(tableName.toLowerCase(Locale.ROOT))) {
                    continue;
                }
                Map<String, Object> table = new LinkedHashMap<>();
                table.put("tableName", tableName);
                table.put("schemaName", "");
                table.put("catalogName", "");
                tables.add(table);
            }
        } catch (SQLException e) {
            logger.warn("user_tables 兜底查询失败: {}", e.getMessage());
            // 尝试 all_tables（用户可能有跨 schema 访问权限）
            try (Statement stmt2 = conn.createStatement();
                 ResultSet rs2 = stmt2.executeQuery("SELECT table_name FROM all_tables ORDER BY table_name")) {
                while (rs2.next()) {
                    String tableName = rs2.getString(1);
                    if (tableName == null || tableName.isBlank() || !seen.add(tableName.toLowerCase(Locale.ROOT))) {
                        continue;
                    }
                    Map<String, Object> table = new LinkedHashMap<>();
                    table.put("tableName", tableName);
                    table.put("schemaName", "");
                    table.put("catalogName", "");
                    tables.add(table);
                }
            } catch (SQLException e2) {
                logger.warn("all_tables 兜底查询也失败: {}", e2.getMessage());
            }
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
            case "达梦数据库V8": return "SELECT SVR_VERSION FROM V$INSTANCE";
            case "SQL Server": return "SELECT @@VERSION";
            default: return "SELECT 1";
        }
    }
}
