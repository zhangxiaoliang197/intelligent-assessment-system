package com.assessment.admin.controller;

import com.assessment.admin.model.SituationReport;
import com.assessment.admin.repository.SituationReportRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.*;

/**
 * 态势图产物 CRUD 控制器。
 *
 * 挂在 /api/admin/situation 下（与 EvaluationController 同模式，独立类不污染 AdminController）。
 * situation-service 调本接口落库/查询（ADR-11）；前端经 situation-service 透传访问，
 * 仅分享查看 /api/admin/situation/share/{token} 可被前端直连（nginx 已配置）。
 *
 * 表结构见 init-mysql.sql 的 situation_report（docs/situation-map/07 §2.1）。
 */
@RestController
@RequestMapping("/api/admin/situation")
public class SituationController {

    @Autowired
    private SituationReportRepository reportRepo;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @org.springframework.beans.factory.annotation.Value("${internal.service-token:local-development-token}")
    private String internalServiceToken;

    // ==================== 产物 CRUD ====================

    /** 创建产物（situation-service 生成中/完成时调用）。 */
    @PostMapping("/reports")
    public ResponseEntity<Map<String, Object>> createReport(
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestBody Map<String, Object> body) {
        if (!Objects.equals(internalServiceToken, serviceToken)) return unauthorizedService();
        SituationReport r = new SituationReport();
        r.setId(getStr(body, "reportId"));
        r.setTitle(getStr(body, "title"));
        r.setQuery(getStr(body, "query"));
        r.setSource(getStr(body, "source"));
        r.setUserId(getStr(body, "userId"));
        r.setTeamIds(getStr(body, "teamIds"));
        r.setStatus(getStr(body, "status"));
        r.setSnapshotJson(toJson(body.get("snapshot")));
        reportRepo.save(r);
        return ResponseEntity.ok(Map.of("success", true, "message", "产物已保存", "id", r.getId()));
    }

    /** 更新产物（生成完成/编辑另存）。不存在则新建（兼容 situation-service 先 PUT 后 POST 的兜底）。 */
    @PutMapping("/reports/{reportId}")
    public ResponseEntity<Map<String, Object>> updateReport(@PathVariable String reportId,
                                                            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
                                                            @RequestBody Map<String, Object> body) {
        if (!Objects.equals(internalServiceToken, serviceToken)) return unauthorizedService();
        Optional<SituationReport> opt = reportRepo.findById(reportId);
        SituationReport r;
        boolean created = false;
        if (opt.isEmpty()) {
            r = new SituationReport();
            r.setId(reportId);
            r.setStatus("generating");
            created = true;
        } else {
            r = opt.get();
        }
        if (body.containsKey("title")) r.setTitle(getStr(body, "title"));
        if (body.containsKey("query")) r.setQuery(getStr(body, "query"));
        if (body.containsKey("source")) r.setSource(getStr(body, "source"));
        if (body.containsKey("userId")) r.setUserId(getStr(body, "userId"));
        if (body.containsKey("teamIds")) r.setTeamIds(getStr(body, "teamIds"));
        if (body.containsKey("status")) r.setStatus(getStr(body, "status"));
        if (body.containsKey("snapshot")) r.setSnapshotJson(toJson(body.get("snapshot")));
        reportRepo.save(r);
        return ResponseEntity.ok(Map.of("success", true, "message", created ? "产物已保存" : "产物已更新"));
    }

    /** 列表（分页 + userId/teamIds 过滤）。 */
    @GetMapping("/reports")
    public ResponseEntity<Map<String, Object>> listReports(
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false, defaultValue = "local-user") String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIdsRaw,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestParam(value = "userId", required = false) String userIdParam,
            @RequestParam(value = "teamIds", required = false) String teamIdsParam,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "20") int size) {
        if (!Objects.equals(internalServiceToken, serviceToken)) return unauthorizedService();
        // Query parameters cannot widen the authenticated actor's scope.
        List<SituationReport> all = reportRepo.findAll();
        all.removeIf(report -> !canAccess(report, userId, teamIdsRaw, role));
        all.sort((a, b) -> b.getCreatedAt().compareTo(a.getCreatedAt()));

        int total = all.size();
        int from = Math.max(0, (page - 1) * size);
        int to = Math.min(total, from + size);
        List<Map<String, Object>> items = new ArrayList<>();
        for (SituationReport r : all.subList(from, to)) {
            items.add(toListItem(r));
        }
        return ResponseEntity.ok(Map.of("success", true, "total", total, "items", items));
    }

    /** 详情（含 snapshot）。 */
    @GetMapping("/reports/{reportId}")
    public ResponseEntity<Map<String, Object>> getReport(
            @PathVariable String reportId,
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIds,
            @RequestHeader(value = "X-User-Role", required = false) String role) {
        if (!Objects.equals(internalServiceToken, serviceToken)) return unauthorizedService();
        Optional<SituationReport> opt = reportRepo.findById(reportId);
        if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("success", false, "message", "产物不存在"));
        if (!canAccess(opt.get(), userId, teamIds, role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "无权访问该产物"));
        }
        return ResponseEntity.ok(Map.of("success", true, "data", toDetail(opt.get())));
    }

    /** 删除。 */
    @DeleteMapping("/reports/{reportId}")
    public ResponseEntity<Map<String, Object>> deleteReport(
            @PathVariable String reportId,
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIds,
            @RequestHeader(value = "X-User-Role", required = false) String role) {
        if (!Objects.equals(internalServiceToken, serviceToken)) return unauthorizedService();
        Optional<SituationReport> report = reportRepo.findById(reportId);
        if (report.isEmpty()) return ResponseEntity.status(404).body(Map.of("success", false, "message", "产物不存在"));
        if (!canAccess(report.get(), userId, teamIds, role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "无权删除该产物"));
        }
        reportRepo.deleteById(reportId);
        return ResponseEntity.ok(Map.of("success", true, "message", "产物已删除"));
    }

    // ==================== 分享 ====================

    /** 生成分享 token（v1 永不过期，Q-04）。 */
    @PostMapping("/reports/{reportId}/share")
    public ResponseEntity<Map<String, Object>> createShare(
            @PathVariable String reportId,
            @RequestHeader(value = "X-Service-Token", required = false) String serviceToken,
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-Team-Ids", required = false) String teamIds,
            @RequestHeader(value = "X-User-Role", required = false) String role) {
        if (!Objects.equals(internalServiceToken, serviceToken)) return unauthorizedService();
        Optional<SituationReport> opt = reportRepo.findById(reportId);
        if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("success", false, "message", "产物不存在"));
        if (!canAccess(opt.get(), userId, teamIds, role)) {
            return ResponseEntity.status(403).body(Map.of("success", false, "message", "无权分享该产物"));
        }
        SituationReport r = opt.get();
        if (r.getShareToken() == null || r.getShareToken().isEmpty()) {
            r.setShareToken(UUID.randomUUID().toString().replace("-", "").substring(0, 24));
            reportRepo.save(r);
        }
        return ResponseEntity.ok(Map.of("success", true, "data", Map.of(
                "token", r.getShareToken(),
                "expiresAt", ""
        )));
    }

    /** 公开查看（分享，无需登录态）。 */
    @GetMapping("/share/{token}")
    public ResponseEntity<Map<String, Object>> getShare(@PathVariable String token) {
        Optional<SituationReport> opt = reportRepo.findByShareToken(token);
        if (opt.isEmpty()) return ResponseEntity.status(404).body(Map.of("success", false, "message", "分享链接无效"));
        // 分享视图脱敏：不含 userId/teamIds
        SituationReport r = opt.get();
        Map<String, Object> detail = toDetail(r);
        detail.put("userId", "");
        detail.put("teamIds", "");
        return ResponseEntity.ok(Map.of("success", true, "data", detail));
    }

    // ==================== 内部工具 ====================

    private String getStr(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? "" : String.valueOf(v);
    }

    private boolean canAccess(SituationReport report, String userId, String teamIds, String role) {
        if ("admin".equalsIgnoreCase(role)) return true;
        if (userId != null && userId.equals(report.getUserId())) return true;
        Set<String> requestTeams = csvSet(teamIds);
        requestTeams.retainAll(csvSet(report.getTeamIds()));
        return !requestTeams.isEmpty();
    }

    private ResponseEntity<Map<String, Object>> unauthorizedService() {
        return ResponseEntity.status(401).body(Map.of("success", false, "message", "服务身份校验失败"));
    }

    private Set<String> csvSet(String value) {
        if (value == null || value.isBlank()) return new HashSet<>();
        Set<String> result = new HashSet<>();
        for (String item : value.split(",")) if (!item.isBlank()) result.add(item.trim());
        return result;
    }

    /** 把 snapshot 对象序列化为 JSON 字符串存储。 */
    private String toJson(Object snapshot) {
        if (snapshot == null) return null;
        if (snapshot instanceof String s) return s;
        try {
            return objectMapper.writeValueAsString(snapshot);
        } catch (Exception e) {
            return String.valueOf(snapshot);
        }
    }

    /** 列表项：精简字段，不含 snapshot。 */
    private Map<String, Object> toListItem(SituationReport r) {
        Map<String, Object> m = new HashMap<>();
        m.put("reportId", r.getId());
        m.put("title", r.getTitle());
        m.put("query", r.getQuery());
        m.put("source", r.getSource());
        m.put("status", r.getStatus());
        m.put("createdAt", r.getCreatedAt() != null ? r.getCreatedAt().toString() : "");
        m.put("updatedAt", r.getUpdatedAt() != null ? r.getUpdatedAt().toString() : "");
        return m;
    }

    /** 详情：含 snapshot（解析回 Map 便于前端消费）。 */
    private Map<String, Object> toDetail(SituationReport r) {
        Map<String, Object> m = toListItem(r);
        m.put("userId", r.getUserId());
        m.put("teamIds", r.getTeamIds());
        m.put("shareToken", r.getShareToken());
        Object snapshot = null;
        String s = r.getSnapshotJson();
        if (s != null && !s.isEmpty()) {
            try {
                snapshot = objectMapper.readValue(s, Object.class);
            } catch (Exception e) {
                snapshot = s;
            }
        }
        m.put("snapshot", snapshot);
        return m;
    }
}
