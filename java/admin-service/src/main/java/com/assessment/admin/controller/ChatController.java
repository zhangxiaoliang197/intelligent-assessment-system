package com.assessment.admin.controller;

import com.assessment.admin.model.*;
import com.assessment.admin.repository.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.*;

/**
 * 聊天会话 CRUD 控制器。
 *
 * 挂在 /api/admin/chat 下，供各 Python 服务调用。
 * qa-service / indicator-service / evaluation_api 将原先 JSON 文件
 * 持久化替换为本控制器提供的 MySQL 持久化（通过 admin-service，不直连 DB）。
 */
@RestController
@RequestMapping("/api/admin/chat")
public class ChatController {

    @Autowired
    private ChatSessionRepository sessionRepo;

    @Autowired
    private ChatMessageRepository messageRepo;

    @Autowired
    private ChatContextRepository contextRepo;

    @Autowired
    private ChatHistoryRepository historyRepo;

    private final ObjectMapper objectMapper = new ObjectMapper();

    // ==================== 会话 CRUD ====================

    /** 新建会话（幂等：已存在则返回已有）。 */
    @PostMapping("/sessions")
    public ResponseEntity<Map<String, Object>> createSession(@RequestBody Map<String, Object> body) {
        String id = getStr(body, "id");
        if (id.isEmpty()) id = UUID.randomUUID().toString().replace("-", "").substring(0, 32);

        Optional<ChatSession> existing = sessionRepo.findById(id);
        if (existing.isPresent()) {
            return ResponseEntity.ok(Map.of("success", true, "message", "会话已存在",
                    "data", toSessionMap(existing.get())));
        }

        ChatSession s = new ChatSession();
        s.setId(id);
        s.setUserId(getStr(body, "userId"));
        s.setType(getStr(body, "type"));
        s.setTitle(getStr(body, "title"));
        s.setStage(getStr(body, "stage"));
        s.setMessageCount(0);
        s.setLastActiveAt(LocalDateTime.now());
        sessionRepo.save(s);

        // 同时写入历史索引
        upsertHistory(s, getStr(body, "summary"));

        return ResponseEntity.ok(Map.of("success", true, "message", "会话已创建",
                "data", toSessionMap(s)));
    }

    /** 更新会话（字段级 patch）。 */
    @PutMapping("/sessions/{sessionId}")
    public ResponseEntity<Map<String, Object>> updateSession(@PathVariable String sessionId,
                                                              @RequestBody Map<String, Object> body) {
        Optional<ChatSession> opt = sessionRepo.findById(sessionId);
        if (opt.isEmpty()) return notFound("会话不存在");

        ChatSession s = opt.get();
        if (body.containsKey("title")) s.setTitle(getStr(body, "title"));
        if (body.containsKey("stage")) s.setStage(getStr(body, "stage"));
        if (body.containsKey("extraData")) s.setExtraData(getStr(body, "extraData"));
        if (body.containsKey("messageCount")) s.setMessageCount(intVal(body, "messageCount"));
        if (body.containsKey("lastActiveAt")) s.setLastActiveAt(LocalDateTime.now());
        sessionRepo.save(s);

        // 同步历史索引
        upsertHistory(s, getStr(body, "summary"));

        return ResponseEntity.ok(Map.of("success", true, "message", "会话已更新",
                "data", toSessionMap(s)));
    }

    /** 获取会话详情（含消息列表）。 */
    @GetMapping("/sessions/{sessionId}")
    public ResponseEntity<Map<String, Object>> getSession(@PathVariable String sessionId) {
        Optional<ChatSession> opt = sessionRepo.findById(sessionId);
        if (opt.isEmpty()) return notFound("会话不存在");

        ChatSession s = opt.get();
        List<ChatMessage> msgs = messageRepo.findBySessionIdOrderBySequenceNumAsc(sessionId);

        Map<String, Object> data = toSessionMap(s);
        data.put("messages", msgs.stream().map(this::toMessageMap).toList());
        return ResponseEntity.ok(Map.of("success", true, "data", data));
    }

    /** 删除会话（级联删除历史索引）。消息/上下文由 DB 外键或后续清理。 */
    @DeleteMapping("/sessions/{sessionId}")
    @Transactional
    public ResponseEntity<Map<String, Object>> deleteSession(@PathVariable String sessionId) {
        sessionRepo.deleteById(sessionId);
        historyRepo.deleteBySessionId(sessionId);
        return ResponseEntity.ok(Map.of("success", true, "message", "会话已删除"));
    }

    /** 列出会话。 */
    @GetMapping("/sessions")
    public ResponseEntity<Map<String, Object>> listSessions(
            @RequestParam(value = "userId", required = false) String userId,
            @RequestParam(value = "type", required = false) String type,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "20") int size) {

        List<ChatHistory> all;
        if (userId != null && !userId.isEmpty()) {
            all = historyRepo.findByUserIdAndTypeOrderByCreateTimeDesc(userId,
                    type != null ? type : "qa");
        } else {
            all = historyRepo.findAll();
            all.sort((a, b) -> b.getCreateTime().compareTo(a.getCreateTime()));
        }

        int total = all.size();
        int from = Math.max(0, (page - 1) * size);
        int to = Math.min(total, from + size);
        List<Map<String, Object>> items = new ArrayList<>();
        for (ChatHistory h : all.subList(from, to)) {
            items.add(toHistoryMap(h));
        }
        return ResponseEntity.ok(Map.of("success", true, "total", total, "page", page, "items", items));
    }

    // ==================== 消息 CRUD ====================

    /** 追加消息（同时更新 session 计数 + 上下文）。 */
    @PostMapping("/sessions/{sessionId}/messages")
    @Transactional
    public ResponseEntity<Map<String, Object>> addMessage(@PathVariable String sessionId,
                                                           @RequestBody Map<String, Object> body) {
        Optional<ChatSession> opt = sessionRepo.findById(sessionId);
        if (opt.isEmpty()) return notFound("会话不存在");

        ChatSession s = opt.get();
        String id = getStr(body, "id");
        if (id.isEmpty()) id = UUID.randomUUID().toString().replace("-", "").substring(0, 32);

        ChatMessage msg = new ChatMessage();
        msg.setId(id);
        msg.setSessionId(sessionId);
        msg.setRole(getStr(body, "role"));
        msg.setContent(getStr(body, "content"));
        msg.setSequenceNum(intVal(body, "sequenceNum"));
        msg.setMetadata(toJson(getStr(body, "metadata")));
        messageRepo.save(msg);

        // 更新会话标题（仅首次消息传入）
        String title = getStr(body, "title");
        String summary = getStr(body, "summary");
        if (!title.isEmpty()) s.setTitle(title);

        // 更新会话计数
        s.setMessageCount(messageRepo.countBySessionId(sessionId));
        s.setLastActiveAt(LocalDateTime.now());
        sessionRepo.save(s);

        // 同步历史索引
        upsertHistory(s, summary.isEmpty() ? title : summary);

        return ResponseEntity.ok(Map.of("success", true, "message", "消息已追加",
                "data", toMessageMap(msg)));
    }

    /** 批量获取消息（支持 limit 用于上下文窗口）。 */
    @GetMapping("/sessions/{sessionId}/messages")
    public ResponseEntity<Map<String, Object>> getMessages(
            @PathVariable String sessionId,
            @RequestParam(value = "limit", required = false) Integer limit) {

        List<ChatMessage> all;
        if (limit != null && limit > 0) {
            // 取最近 N 条（倒序取再反转）
            List<ChatMessage> desc = messageRepo.findBySessionIdOrderBySequenceNumDesc(sessionId);
            int cnt = Math.min(limit, desc.size());
            all = new ArrayList<>();
            for (int i = cnt - 1; i >= 0; i--) {
                all.add(desc.get(i));
            }
        } else {
            all = messageRepo.findBySessionIdOrderBySequenceNumAsc(sessionId);
        }

        return ResponseEntity.ok(Map.of("success", true, "data",
                all.stream().map(this::toMessageMap).toList()));
    }

    /** 获取最后一条消息的 sequence_num（用于新消息递增）。 */
    @GetMapping("/sessions/{sessionId}/messages/last-seq")
    public ResponseEntity<Map<String, Object>> getLastSeq(@PathVariable String sessionId) {
        List<ChatMessage> desc = messageRepo.findBySessionIdOrderBySequenceNumDesc(sessionId);
        int lastSeq = desc.isEmpty() ? -1 : desc.get(0).getSequenceNum();
        return ResponseEntity.ok(Map.of("success", true, "data", Map.of("sequenceNum", lastSeq)));
    }

    // ==================== 上下文 CRUD ====================

    /** 获取 LLM 上下文。 */
    @GetMapping("/sessions/{sessionId}/context")
    public ResponseEntity<Map<String, Object>> getContext(@PathVariable String sessionId,
                                                           @RequestParam(value = "contextType", defaultValue = "full") String contextType) {
        Optional<ChatContext> opt = contextRepo.findBySessionIdAndContextType(sessionId, contextType);
        if (opt.isEmpty()) return ResponseEntity.ok(Map.of("success", true, "data",
                Map.of("content", "", "messageRange", "", "tokenEstimate", 0)));

        ChatContext ctx = opt.get();
        Map<String, Object> data = new HashMap<>();
        data.put("content", ctx.getContent());
        data.put("messageRange", ctx.getMessageRange());
        data.put("tokenEstimate", ctx.getTokenEstimate());
        return ResponseEntity.ok(Map.of("success", true, "data", data));
    }

    /** 更新 LLM 上下文。 */
    @PutMapping("/sessions/{sessionId}/context")
    public ResponseEntity<Map<String, Object>> updateContext(@PathVariable String sessionId,
                                                              @RequestBody Map<String, Object> body) {
        String contextType = getStr(body, "contextType");
        if (contextType.isEmpty()) contextType = "full";

        ChatContext ctx = contextRepo.findBySessionIdAndContextType(sessionId, contextType)
                .orElse(new ChatContext());
        ctx.setSessionId(sessionId);
        ctx.setContextType(contextType);
        ctx.setContent(getStr(body, "content"));
        if (body.containsKey("messageRange")) ctx.setMessageRange(getStr(body, "messageRange"));
        if (body.containsKey("tokenEstimate")) ctx.setTokenEstimate(intVal(body, "tokenEstimate"));
        contextRepo.save(ctx);

        return ResponseEntity.ok(Map.of("success", true, "message", "上下文已更新"));
    }

    // ==================== 内部工具 ====================

    private String getStr(Map<String, Object> body, String key) {
        Object v = body.get(key);
        return v == null ? "" : String.valueOf(v);
    }

    private int intVal(Map<String, Object> body, String key) {
        Object v = body.get(key);
        if (v instanceof Number n) return n.intValue();
        if (v instanceof String s) {
            try { return Integer.parseInt(s); } catch (Exception e) { return 0; }
        }
        return 0;
    }

    private String toJson(Object val) {
        if (val == null) return null;
        if (val instanceof String s) return s;
        try {
            return objectMapper.writeValueAsString(val);
        } catch (Exception e) {
            return String.valueOf(val);
        }
    }

    private ResponseEntity<Map<String, Object>> notFound(String msg) {
        return ResponseEntity.status(404).body(Map.of("success", false, "message", msg));
    }

    private Map<String, Object> toSessionMap(ChatSession s) {
        Map<String, Object> m = new HashMap<>();
        m.put("id", s.getId());
        m.put("userId", s.getUserId());
        m.put("type", s.getType());
        m.put("title", s.getTitle());
        m.put("stage", s.getStage());
        m.put("extraData", s.getExtraData() != null ? s.getExtraData() : "");
        m.put("messageCount", s.getMessageCount());
        m.put("lastActiveAt", s.getLastActiveAt() != null ? s.getLastActiveAt().toString() : "");
        m.put("createTime", s.getCreateTime() != null ? s.getCreateTime().toString() : "");
        m.put("updateTime", s.getUpdateTime() != null ? s.getUpdateTime().toString() : "");
        return m;
    }

    private Map<String, Object> toMessageMap(ChatMessage m) {
        Map<String, Object> map = new HashMap<>();
        map.put("id", m.getId());
        map.put("sessionId", m.getSessionId());
        map.put("role", m.getRole());
        map.put("content", m.getContent());
        map.put("sequenceNum", m.getSequenceNum());
        map.put("metadata", m.getMetadata());
        map.put("createTime", m.getCreateTime() != null ? m.getCreateTime().toString() : "");
        return map;
    }

    private Map<String, Object> toHistoryMap(ChatHistory h) {
        Map<String, Object> map = new HashMap<>();
        map.put("id", h.getId());
        map.put("sessionId", h.getSessionId());
        map.put("userId", h.getUserId());
        map.put("type", h.getType());
        map.put("title", h.getTitle());
        map.put("summary", h.getSummary());
        map.put("skillId", h.getSkillId() != null ? h.getSkillId() : "");
        map.put("createTime", h.getCreateTime() != null ? h.getCreateTime().toString() : "");
        return map;
    }

    /** 同步历史索引（upsert）。 */
    private void upsertHistory(ChatSession s, String summary) {
        Optional<ChatHistory> existing = historyRepo.findBySessionId(s.getId());
        ChatHistory h = existing.orElse(new ChatHistory());
        if (existing.isEmpty()) h.setId(UUID.randomUUID().toString().replace("-", "").substring(0, 32));
        h.setSessionId(s.getId());
        h.setUserId(s.getUserId());
        h.setType(s.getType());
        h.setTitle(s.getTitle());
        if (summary != null && !summary.isEmpty()) h.setSummary(summary);
        historyRepo.save(h);
    }
}
