package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 聊天消息实体。
 * 对应表 ass_chat_message，append-only 存储，前端读完整历史，LLM 不直接读。
 * metadata 按 type 存三类对话的结构化差异数据（JSON 字符串）。
 */
@Entity
@Table(name = "ass_chat_message")
public class ChatMessage {

    @Id
    @Column(length = 32)
    private String id;

    @Column(name = "session_id", length = 32, nullable = false)
    private String sessionId;

    @Column(length = 16, nullable = false)
    private String role;                     // user | assistant | system

    @Column(columnDefinition = "text")
    private String content;

    @Column(name = "sequence_num")
    private Integer sequenceNum;

    @Column(columnDefinition = "text")
    private String metadata;                 // JSON: 三类对话的差异数据

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @PrePersist
    protected void onCreate() {
        if (createTime == null) createTime = LocalDateTime.now();
    }

    public ChatMessage() {}

    // ---- getters & setters ----

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }

    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }

    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }

    public Integer getSequenceNum() { return sequenceNum; }
    public void setSequenceNum(Integer sequenceNum) { this.sequenceNum = sequenceNum; }

    public String getMetadata() { return metadata; }
    public void setMetadata(String metadata) { this.metadata = metadata; }

    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
