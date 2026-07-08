package com.assessment.admin.controller;

import com.assessment.admin.service.SchemaService;
import com.assessment.admin.service.SqlExecutionService;
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
            @RequestBody Map<String, String> body) {

        String sql = body.get("sql");
        if (sql == null || sql.trim().isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("success", false, "message", "SQL不能为空"));
        }

        Map<String, Object> result = sqlExecutionService.executeSql(datasetId, sql);
        return ResponseEntity.ok(result);
    }

    /**
     * 在数据库配置上执行 SQL 查询
     * POST /api/admin/database/{dbId}/execute-sql
     */
    @PostMapping("/database/{dbId}/execute-sql")
    public ResponseEntity<Map<String, Object>> executeSqlOnDatabase(
            @PathVariable String dbId,
            @RequestBody Map<String, String> body) {

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
}
