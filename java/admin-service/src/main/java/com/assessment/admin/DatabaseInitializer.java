package com.assessment.admin;

import com.assessment.admin.model.Driver;
import com.assessment.admin.model.LlmConfig;
import com.assessment.admin.model.MapServiceConfig;
import com.assessment.admin.repository.DriverRepository;
import com.assessment.admin.repository.LlmConfigRepository;
import com.assessment.admin.repository.MapServiceConfigRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.io.File;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Component
public class DatabaseInitializer implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(DatabaseInitializer.class);

    // 高德底图默认配置（baseUrl 为同源瓦片代理前缀，vite/nginx 转发到高德瓦片服务）
    private static final String AMAP_CONFIG_ID = "map_amap_001";
    private static final String AMAP_CONFIG_NAME = "高德在线底图（推荐）";
    private static final String AMAP_BASE_URL = "/amap-tiles";

    /** 首次初始化默认启用的底图类型：geowebcache（内网）或 amap（公网高德） */
    @Value("${map.default-type:geowebcache}")
    private String defaultMapType;

    private final DriverRepository driverRepo;
    private final LlmConfigRepository llmConfigRepo;
    private final MapServiceConfigRepository mapConfigRepo;
    private final com.assessment.admin.service.DriverJarResolver driverJarResolver;

    @Value("${db.type:mysql}")
    private String dbType;

    @Value("${db.mysql.host:localhost}")
    private String mysqlHost;
    @Value("${db.mysql.port:3306}")
    private int mysqlPort;
    @Value("${db.mysql.database:assessment}")
    private String mysqlDb;
    @Value("${db.mysql.user:root}")
    private String mysqlUser;
    @Value("${db.mysql.password:root}")
    private String mysqlPassword;

    @Value("${db.postgresql.host:localhost}")
    private String pgHost;
    @Value("${db.postgresql.port:5432}")
    private int pgPort;
    @Value("${db.postgresql.database:assessment}")
    private String pgDb;
    @Value("${db.postgresql.user:postgres}")
    private String pgUser;
    @Value("${db.postgresql.password:postgres}")
    private String pgPassword;

    public DatabaseInitializer(DriverRepository driverRepo, LlmConfigRepository llmConfigRepo,
                               MapServiceConfigRepository mapConfigRepo,
                               com.assessment.admin.service.DriverJarResolver driverJarResolver) {
        this.driverRepo = driverRepo;
        this.llmConfigRepo = llmConfigRepo;
        this.mapConfigRepo = mapConfigRepo;
        this.driverJarResolver = driverJarResolver;
    }

    @Override
    public void run(String... args) {
        createDatabaseIfNotExists();
        initDefaultDrivers();
        // 驱动表可能保留历史部署写入的失效路径（如旧的文件名），启动时统一巡检并自愈
        healDriverJarPaths();
        initDefaultLlmConfig();
        initDefaultMapServiceConfig();
    }

    /**
     * 巡检全部驱动记录：精确路径失效时按驱动类在驱动目录中通配匹配，
     * 命中后把可移植路径写回数据库，避免升级镜像后仍引用旧文件名导致连接失败。
     */
    private void healDriverJarPaths() {
        List<Driver> drivers = driverRepo.findAll();
        int healed = 0;
        for (Driver driver : drivers) {
            try {
                boolean recovered = driverJarResolver.resolveAndHeal(driver).recovered();
                if (recovered) {
                    healed++;
                }
            } catch (Exception e) {
                // 缺驱动属于可恢复状态：不阻断启动，由使用方在连接时报出中文提示
                log.warn("驱动 {} 暂不可用: {}", driver.getName(), e.getMessage());
            }
        }
        if (healed > 0) {
            log.info("驱动JAR路径自愈完成，共更新 {} 条", healed);
        }
    }

    private void createDatabaseIfNotExists() {
        try {
            if ("postgresql".equalsIgnoreCase(dbType)) {
                try (Connection conn = DriverManager.getConnection(
                        "jdbc:postgresql://" + pgHost + ":" + pgPort + "/",
                        pgUser, pgPassword);
                     Statement stmt = conn.createStatement()) {
                    stmt.executeUpdate("CREATE DATABASE \"" + pgDb + "\"");
                    log.info("数据库 {} 创建成功", pgDb);
                } catch (Exception e) {
                    if (!e.getMessage().contains("already exists")) {
                        log.warn("创建数据库 {} 失败(可能已存在): {}", pgDb, e.getMessage());
                    }
                }
            } else {
                try (Connection conn = DriverManager.getConnection(
                        "jdbc:mysql://" + mysqlHost + ":" + mysqlPort +
                        "?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true",
                        mysqlUser, mysqlPassword);
                     Statement stmt = conn.createStatement()) {
                    stmt.executeUpdate("CREATE DATABASE IF NOT EXISTS `" + mysqlDb +
                            "` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
                    log.info("数据库 {} 已就绪", mysqlDb);
                }
            }
        } catch (Exception e) {
            log.warn("创建数据库时异常(可能已存在): {}", e.getMessage());
        }
    }

    private void initDefaultDrivers() {
        if (driverRepo.count() > 0) {
            log.info("驱动表已有数据，跳过初始化");
            return;
        }

        Map<String, String[]> presets = new LinkedHashMap<>();
        presets.put("MySQL", new String[]{
                "com.mysql.cj.jdbc.Driver",
                "jdbc:mysql://{host}:{port}/{database}?useSSL=false&serverTimezone=Asia/Shanghai&connectionCollation=utf8mb4_unicode_ci&sessionVariables=character_set_client=utf8mb4,character_set_connection=utf8mb4,character_set_results=utf8mb4",
                "drivers/mysql-connector-j.jar"
        });
        presets.put("PostgreSQL", new String[]{
                "org.postgresql.Driver",
                "jdbc:postgresql://{host}:{port}/{database}",
                "drivers/postgresql.jar"
        });
        presets.put("SQLServer", new String[]{
                "com.microsoft.sqlserver.jdbc.SQLServerDriver",
                "jdbc:sqlserver://{host}:{port};databaseName={database}",
                "drivers/mssql-jdbc.jar"
        });
        presets.put("Oracle", new String[]{
                "oracle.jdbc.OracleDriver",
                "jdbc:oracle:thin:@//{host}:{port}/{database}",
                "drivers/ojdbc11.jar"
        });
        presets.put("达梦数据库V8", new String[]{
                "dm.jdbc.driver.DmDriver",
                "jdbc:dm://{host}:{port}/{database}",
                "drivers/DmJdbcDriver11.jar"
        });

        int i = 0;
        for (Map.Entry<String, String[]> entry : presets.entrySet()) {
            String name = entry.getKey();
            String[] vals = entry.getValue();
            Driver d = new Driver();
            d.setId("driver_" + pad(i++));
            d.setName(name);
            d.setDriverClass(vals[0]);
            d.setUrlTemplate(vals[1]);
            // 存相对路径（跨机器可移植），运行时以 user.dir 为基准解析
            String jarPath = vals[2];
            d.setJarFilePath(jarPath);
            d.setJarFileName(jarPath != null ? new File(jarPath).getName() : null);
            d.setCreateTime(LocalDateTime.now());
            d.setUpdateTime(LocalDateTime.now());
            driverRepo.save(d);
        }
        log.info("初始驱动数据已插入 ({} 条)", presets.size());
    }

    private void initDefaultLlmConfig() {
        if (llmConfigRepo.count() > 0) {
            log.info("LLM配置表已有数据，跳过初始化");
            return;
        }

        LlmConfig config = new LlmConfig();
        config.setId("llm_001");
        config.setName("DeepSeek 默认");
        config.setType("deepseek");
        config.setApiUrl("https://api.deepseek.com/v1");
        config.setApiKey("");
        config.setModel("deepseek-chat");
        config.setTemperature(0.7);
        config.setMaxTokens(2000);
        config.setTopP(0.9);
        config.setIsActive(true);
        config.setCreateTime(LocalDateTime.now());
        config.setUpdateTime(LocalDateTime.now());
        llmConfigRepo.save(config);
        log.info("默认LLM配置已插入 (DeepSeek)");
    }

    /**
     * 初始化/迁移地图服务配置。
     *
     * 首次初始化：同时写入 GeoWebCache 与高德在线底图，启用哪一项由
     * map.default-type 决定（内网默认 geowebcache，公网默认 amap）。
     * 存量环境：若从未存在 amap 配置，则补一条；仅当默认类型为 amap 且当前启用项
     * 仍是 GeoWebCache 时才自动切换，用户手动配过其他服务则保持不动。
     */
    private void initDefaultMapServiceConfig() {
        boolean preferAmap = "amap".equalsIgnoreCase(defaultMapType);
        List<MapServiceConfig> all = mapConfigRepo.findAll();
        if (all.isEmpty()) {
            // baseUrl 只到 GWC 上下文根；多写 /gwc 会拼出 /geowebcache/gwc/service/tms/... 导致 404
            saveMapConfig("map_001", "GeoWebCache 内网地图（默认）", "geowebcache", "/geowebcache", !preferAmap);
            saveMapConfig(AMAP_CONFIG_ID, AMAP_CONFIG_NAME, "amap", AMAP_BASE_URL, preferAmap);
            log.info("默认地图服务配置已插入：{}（启用），另一项作为备用",
                    preferAmap ? "高德在线底图" : "GeoWebCache 内网地图");
            return;
        }

        boolean hasAmap = all.stream().anyMatch(c -> "amap".equalsIgnoreCase(c.getType()));
        if (hasAmap) {
            log.info("地图服务配置已存在高德项，跳过迁移");
            return;
        }

        MapServiceConfig active = all.stream()
                .filter(c -> Boolean.TRUE.equals(c.getIsActive()))
                .findFirst().orElse(null);
        boolean activeIsGeoWebCache = active == null || "geowebcache".equalsIgnoreCase(active.getType());

        // 若固定 ID 已被其他配置占用，改用随机 ID，避免覆盖用户已有配置
        String amapId = mapConfigRepo.findById(AMAP_CONFIG_ID).isPresent()
                ? "map_" + java.util.UUID.randomUUID().toString().substring(0, 8)
                : AMAP_CONFIG_ID;

        // 仅在默认类型为 amap 时才把 GeoWebCache 切换成高德；内网部署保持内网底图不变
        boolean activateAmap = activeIsGeoWebCache && preferAmap;

        MapServiceConfig amap = new MapServiceConfig();
        amap.setId(amapId);
        amap.setName(AMAP_CONFIG_NAME);
        amap.setType("amap");
        amap.setBaseUrl(AMAP_BASE_URL);
        amap.setIsActive(activateAmap);
        amap.setCreateTime(LocalDateTime.now());
        amap.setUpdateTime(LocalDateTime.now());

        if (activateAmap) {
            all.forEach(c -> {
                c.setIsActive(false);
                mapConfigRepo.save(c);
            });
            log.info("存量地图配置已迁移为高德底图（如需回退，请在管理后台启用 GeoWebCache）");
        } else if (activeIsGeoWebCache) {
            log.info("当前启用 GeoWebCache，默认类型为 geowebcache，保持内网底图不变");
        } else {
            log.info("已补充高德底图配置，但当前启用的是 {}，保持用户选择不变", active.getName());
        }
        mapConfigRepo.save(amap);
    }

    /** 写入一条地图服务配置 */
    private void saveMapConfig(String id, String name, String type, String baseUrl, boolean active) {
        MapServiceConfig config = new MapServiceConfig();
        config.setId(id);
        config.setName(name);
        config.setType(type);
        config.setBaseUrl(baseUrl);
        config.setIsActive(active);
        config.setCreateTime(LocalDateTime.now());
        config.setUpdateTime(LocalDateTime.now());
        mapConfigRepo.save(config);
    }

    private static String pad(int num) {
        if (num < 10) return "0" + num;
        return String.valueOf(num);
    }
}
