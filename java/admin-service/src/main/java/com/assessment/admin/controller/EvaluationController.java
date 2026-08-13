package com.assessment.admin.controller;

import com.assessment.admin.service.SchemaService;
import com.assessment.admin.service.SqlExecutionService;
import com.assessment.admin.model.Dataset;
import com.assessment.admin.repository.DatasetRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;

/**
 * 评估分析控制器
 * 向 Python 多智能体系统提供数据上下文和 SQL 执行能力
 */
@RestController
@RequestMapping("/api/admin")
public class EvaluationController {

    @Autowired
    private SchemaService schemaService;

    @Autowired
    private SqlExecutionService sqlExecutionService;

    @Autowired
    private DatasetRepository datasetRepository;

    @Value("${internal.service-token:local-development-token}")
    private String internalServiceToken;

    /** Minimal, actor-filtered catalog used only by situation-service preflight/runtime. */
    @GetMapping("/dataset/authorized-list")
    public ResponseEntity<Map<String, Object>> listAuthorizedDatasets(
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIds,
            @RequestHeader(value = "X-User-Role", required = false) String role) {
        if (!Objects.equals(internalServiceToken, serviceToken)) {
            return ResponseEntity.status(401).body(Map.of("success", false, "message", "服务身份校验失败"));
        }
        List<Map<String, Object>> datasets = new ArrayList<>();
        for (Dataset dataset : datasetRepository.findAll()) {
            if (!canRead(dataset, userId, teamIds, role)) continue;
            Map<String, Object> item = new HashMap<>();
            item.put("id", dataset.getId());
            item.put("name", dataset.getName());
            item.put("tableName", dataset.getTableName());
            item.put("schemaVersion", dataset.getSchemaVersion() == null ? 1 : dataset.getSchemaVersion());
            item.put("sensitiveColumns", new ArrayList<>(csvSet(dataset.getSensitiveColumns())));
            datasets.add(item);
        }
        return ResponseEntity.ok(Map.of("success", true, "total", datasets.size(), "datasets", datasets));
    }

    /**
     * Situation-service only: execute the server-owned dataset template after service and
     * actor authorization. No caller supplied SQL is accepted by this endpoint.
     */
    @PostMapping("/dataset/{datasetId}/query")
    public ResponseEntity<Map<String, Object>> queryDataset(
            @PathVariable String datasetId,
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIds,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestBody(required = false) Map<String, Object> body) {
        if (!Objects.equals(internalServiceToken, serviceToken)) {
            return ResponseEntity.status(401).body(Map.of("success", false, "message", "服务身份校验失败"));
        }
        Optional<Dataset> dataset = datasetRepository.findById(datasetId);
        if (dataset.isEmpty()) {
            return ResponseEntity.status(404).body(Map.of("success", false, "message", "数据集不存在"));
        }
        if (!canRead(dataset.get(), userId, teamIds, role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "无权读取该数据集"));
        }
        int limit = 200;
        Object limitValue = body == null ? null : body.get("limit");
        if (limitValue instanceof Number number) limit = number.intValue();
        return ResponseEntity.ok(sqlExecutionService.queryDataset(datasetId, limit));
    }

    /**
     * 获取评估所需的完整上下文（表结构 + 指标定义）
     * POST /api/admin/evaluation/context
     */
    @PostMapping("/evaluation/context")
    public ResponseEntity<Map<String, Object>> getEvaluationContext(
            @RequestBody Map<String, Object> body) {

        @SuppressWarnings("unchecked")
        List<String> datasetIds = (List<String>) body.getOrDefault("datasetIds", List.of());
        @SuppressWarnings("unchecked")
        List<String> indicatorIds = (List<String>) body.getOrDefault("indicatorIds", List.of());

        Map<String, Object> context = schemaService.exportEvaluationContext(datasetIds, indicatorIds);
        return ResponseEntity.ok(context);
    }

    /**
     * 在数据集上执行 SQL 查询
     * POST /api/admin/dataset/{datasetId}/execute-sql
     */
    @PostMapping("/dataset/{datasetId}/execute-sql")
    public ResponseEntity<Map<String, Object>> executeSqlOnDataset(
            @PathVariable String datasetId,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestBody Map<String, String> body) {

        if (!"admin".equalsIgnoreCase(role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "仅管理员可执行临时 SQL"));
        }

        String sql = body.get("sql");
        if (sql == null || sql.trim().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "SQL不能为空"));
        }

        Map<String, Object> result = sqlExecutionService.executeSql(datasetId, sql);
        return ResponseEntity.ok(result);
    }

    /**
     * 态势图专用：在数据集关联的数据库上执行 LLM 生成的只读 SQL。
     * POST /api/admin/dataset/{datasetId}/execute-query
     * 与 execute-sql（仅管理员临时 SQL）不同，本端点走服务身份 + 数据集授权，
     * 供 situation-service 在取数阶段复用评估分析的 Text-to-SQL 能力，
     * 用 LLM 生成的精确 SQL（WHERE/聚合/GROUP BY）替代整表拉取。
     */
    @PostMapping("/dataset/{datasetId}/execute-query")
    public ResponseEntity<Map<String, Object>> executeQueryForSituation(
            @PathVariable String datasetId,
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIds,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestBody(required = false) Map<String, String> body) {
        if (!Objects.equals(internalServiceToken, serviceToken)) {
            return ResponseEntity.status(401).body(Map.of("success", false, "message", "服务身份校验失败"));
        }
        Optional<Dataset> dataset = datasetRepository.findById(datasetId);
        if (dataset.isEmpty()) {
            return ResponseEntity.status(404).body(Map.of("success", false, "message", "数据集不存在"));
        }
        if (!canRead(dataset.get(), userId, teamIds, role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "无权读取该数据集"));
        }
        String sql = body == null ? null : body.get("sql");
        if (sql == null || sql.trim().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "SQL不能为空"));
        }
        return ResponseEntity.ok(sqlExecutionService.executeSql(datasetId, sql));
    }

    /**
     * 在数据库配置上执行 SQL 查询
     * POST /api/admin/database/{dbId}/execute-sql
     */
    @PostMapping("/database/{dbId}/execute-sql")
    public ResponseEntity<Map<String, Object>> executeSqlOnDatabase(
            @PathVariable String dbId,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestBody Map<String, String> body) {

        if (!"admin".equalsIgnoreCase(role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "仅管理员可执行临时 SQL"));
        }

        String sql = body.get("sql");
        if (sql == null || sql.trim().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "SQL不能为空"));
        }

        Map<String, Object> result = sqlExecutionService.executeSqlOnDatabase(dbId, sql);
        return ResponseEntity.ok(result);
    }

    /**
     * 获取数据集的完整结构（DDL + 标注）
     * GET /api/admin/dataset/{datasetId}/full-structure
     */
    @GetMapping("/dataset/{datasetId}/full-structure")
    public ResponseEntity<Map<String, Object>> getFullStructure(@PathVariable String datasetId) {
        Map<String, Object> result = schemaService.getDatasetStructure(datasetId);
        return ResponseEntity.ok(result);
    }

    private boolean canRead(Dataset dataset, String userId, String teamIds, String role) {
        if ("admin".equalsIgnoreCase(role)) return true;
        Set<String> users = csvSet(dataset.getAllowedUserIds());
        if (userId != null && users.contains(userId.trim())) return true;
        Set<String> allowedTeams = csvSet(dataset.getAllowedTeamIds());
        for (String team : csvSet(teamIds)) {
            if (allowedTeams.contains(team)) return true;
        }
        return false;
    }

    private Set<String> csvSet(String csv) {
        if (csv == null || csv.isBlank()) return Set.of();
        Set<String> result = new HashSet<>();
        for (String item : csv.split(",")) {
            if (!item.isBlank()) result.add(item.trim());
        }
        return result;
    }
}
