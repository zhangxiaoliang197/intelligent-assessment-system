package com.assessment.admin.service;

import com.assessment.admin.model.DatabaseConfig;
import com.assessment.admin.model.Dataset;
import com.assessment.admin.model.Driver;
import com.assessment.admin.model.FieldAnnotation;
import com.assessment.admin.model.Indicator;
import com.assessment.admin.repository.DatabaseConfigRepository;
import com.assessment.admin.repository.DatasetRepository;
import com.assessment.admin.repository.DriverRepository;
import com.assessment.admin.repository.FieldAnnotationRepository;
import com.assessment.admin.repository.IndicatorRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.io.File;
import java.net.URL;
import java.net.URLClassLoader;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.*;

/**
 * 评估上下文服务
 * 为多智能体评估系统提供表结构、指标定义等上下文数据
 */
@Service
public class SchemaService {

    @Autowired
    private DatasetRepository datasetRepo;

    @Autowired
    private DatabaseConfigRepository dbConfigRepo;

    @Autowired
    private DriverRepository driverRepo;

    @Autowired
    private FieldAnnotationRepository fieldAnnotationRepo;

    @Autowired
    private IndicatorRepository indicatorRepo;

    /**
     * 获取数据集表结构（DDL + 标注）
     */
    public Map<String, Object> getDatasetStructure(String datasetId) {
        Optional<Dataset> optDs = datasetRepo.findById(datasetId);
        if (optDs.isEmpty()) return Map.of("success", false, "message", "数据集不存在");

        Dataset ds = optDs.get();
        if (ds.getTableName() == null || ds.getDatabaseId() == null) {
            return Map.of("success", true, "tableName", "", "columns", List.of(), "datasetName", ds.getName());
        }

        Optional<DatabaseConfig> optDb = dbConfigRepo.findById(ds.getDatabaseId());
        if (optDb.isEmpty()) return Map.of("success", false, "message", "数据库配置不存在");

        DatabaseConfig dbConfig = optDb.get();
        Driver driver = findDriver(dbConfig.getType());
        if (driver == null) return Map.of("success", false, "message", "未找到驱动: " + dbConfig.getType());

        String url = buildJdbcUrl(driver, dbConfig);

        try (Connection conn = getConnection(driver, url, dbConfig.getUsername(), dbConfig.getPassword());
             Statement stmt = conn.createStatement()) {

            String sql = buildColumnQuery(driver.getName(), dbConfig.getDbName(), ds.getTableName());
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

            return Map.of("success", true, "tableName", ds.getTableName(),
                    "columns", columns, "count", columns.size());

        } catch (Exception e) {
            return Map.of("success", false, "message", "读取表结构失败: " + e.getMessage());
        }
    }

    /**
     * 获取指标详情（含关联数据集和字段）
     */
    public Map<String, Object> getIndicatorDetail(String indicatorId) {
        Optional<Indicator> opt = indicatorRepo.findById(indicatorId);
        if (opt.isEmpty()) return Map.of("success", false, "message", "指标不存在");

        Indicator ind = opt.get();
        Map<String, Object> result = new LinkedHashMap<>();
        result.putAll(toMap(ind));

        // 获取关联信息
        if (ind.getDatasetId() != null) {
            List<FieldAnnotation> fields = fieldAnnotationRepo.findByDatasetId(ind.getDatasetId());
            result.put("linkedFields", fields);
            Optional<Dataset> ds = datasetRepo.findById(ind.getDatasetId());
            ds.ifPresent(d -> result.put("linkedDatasetName", d.getName()));
        }

        return Map.of("success", true, "data", result);
    }

    /**
     * 导出所有评估上下文（供 Python 侧一次性获取）
     */
    public Map<String, Object> exportEvaluationContext(List<String> datasetIds, List<String> indicatorIds) {
        List<Map<String, Object>> schemas = new ArrayList<>();
        if (datasetIds != null) {
            for (String id : datasetIds) {
                Map<String, Object> schema = getDatasetStructure(id);
                if (Boolean.TRUE.equals(schema.get("success"))) {
                    Optional<Dataset> ds = datasetRepo.findById(id);
                    ds.ifPresent(d -> {
                        schema.put("datasetName", d.getName());
                        schema.put("description", d.getDescription());
                    });
                    schema.put("datasetId", id);
                    schemas.add(schema);
                }
            }
        }

        List<Map<String, Object>> indicators = new ArrayList<>();
        if (indicatorIds != null) {
            for (String id : indicatorIds) {
                Optional<Indicator> opt = indicatorRepo.findById(id);
                opt.ifPresent(ind -> {
                    Map<String, Object> detail = getIndicatorDetail(id);
                    if (Boolean.TRUE.equals(detail.get("success"))) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> data = (Map<String, Object>) detail.get("data");
                        if (data != null) {
                            indicators.add(data);
                        }
                    }
                });
            }
        }

        return Map.of("success", true, "schemas", schemas, "indicators", indicators);
    }

    // ====== 内部辅助方法 ======

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
        if (!jarFile.exists()) throw new Exception("驱动JAR文件不存在: " + driver.getJarFilePath());

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

    private String buildColumnQuery(String driverName, String dbName, String tableName) {
        if ("PostgreSQL".equals(driverName)) {
            return String.format(
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
        }
        return String.format(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, " +
            "IF(COLUMN_KEY='PRI','YES','NO') AS IS_PK, " +
            "COALESCE(COLUMN_COMMENT,'') AS COLUMN_COMMENT " +
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='%s' AND TABLE_NAME='%s' " +
            "ORDER BY ORDINAL_POSITION",
            dbName, tableName);
    }

    private Map<String, Object> toMap(Indicator ind) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", ind.getId());
        m.put("name", ind.getName());
        m.put("category", ind.getCategory());
        m.put("formula", ind.getFormula());
        m.put("description", ind.getDescription());
        m.put("weight", ind.getWeight());
        m.put("datasetId", ind.getDatasetId());
        m.put("fieldMapping", ind.getFieldMapping());
        m.put("calculationMethod", ind.getCalculationMethod());
        return m;
    }
}
