package com.assessment.admin.model;

import jakarta.persistence.*;
import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * LLM 上下文实体。
 * 对应表 ass_chat_context，复合主键 (session_id, context_type)。
 * 与消息表分离：LLM 读此表获取压缩后的上下文，消息表保持 append-only。
 */
@Entity
@Table(name = "ass_chat_context")
@IdClass(ChatContext.ChatContextId.class)
public class ChatContext {

    @Id
    @Column(name = "session_id", length = 32)
    private String sessionId;

    @Id
    @Column(name = "context_type", length = 20)
    private String contextType = "full";     // full | summary

    @Column(columnDefinition = "text")
    private String content;

    @Column(name = "message_range", length = 50)
    private String messageRange;

    @Column(name = "token_estimate")
    private Integer tokenEstimate;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @PrePersist
    protected void onCreate() {
        if (createTime == null) createTime = LocalDateTime.now();
    }

    public ChatContext() {}

    // ---- 复合主键类 ----

    public static class ChatContextId implements Serializable {
        private String sessionId;
        private String contextType;

        public ChatContextId() {}
        public ChatContextId(String sessionId, String contextType) {
            this.sessionId = sessionId;
            this.contextType = contextType;
        }
        public String getSessionId() { return sessionId; }
        public void setSessionId(String sessionId) { this.sessionId = sessionId; }
        public String getContextType() { return contextType; }
        public void setContextType(String contextType) { this.contextType = contextType; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof ChatContextId that)) return false;
            return sessionId.equals(that.sessionId) && contextType.equals(that.contextType);
        }

        @Override
        public int hashCode() {
            return sessionId.hashCode() * 31 + contextType.hashCode();
        }
    }

    // ---- getters & setters ----

    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }

    public String getContextType() { return contextType; }
    public void setContextType(String contextType) { this.contextType = contextType; }

    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }

    public String getMessageRange() { return messageRange; }
    public void setMessageRange(String messageRange) { this.messageRange = messageRange; }

    public Integer getTokenEstimate() { return tokenEstimate; }
    public void setTokenEstimate(Integer tokenEstimate) { this.tokenEstimate = tokenEstimate; }

    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
