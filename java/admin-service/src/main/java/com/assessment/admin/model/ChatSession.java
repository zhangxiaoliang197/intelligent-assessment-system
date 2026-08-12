package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 聊天会话实体。
 * 对应表 ass_chat_session，统一管理 qa/indicator/evaluation 三类会话的元数据。
 * 由各 Python 服务调 admin-service CRUD 落库，不直连 DB。
 */
@Entity
@Table(name = "ass_chat_session")
public class ChatSession {

    @Id
    @Column(length = 50)
    private String id;

    @Column(name = "user_id", length = 64, nullable = false)
    private String userId = "";

    @Column(length = 20, nullable = false)
    private String type;                     // qa | indicator | evaluation

    @Column(length = 200, nullable = false)
    private String title = "";

    @Column(length = 30)
    private String stage;                    // indicator 专用

    @Column(name = "extra_data", columnDefinition = "TEXT")
    private String extraData;                // pending_indicators JSON 等扩展数据

    @Column(name = "message_count")
    private Integer messageCount = 0;

    @Column(name = "last_active_at")
    private LocalDateTime lastActiveAt;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @Column(name = "update_time")
    private LocalDateTime updateTime;

    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        if (createTime == null) createTime = now;
        if (updateTime == null) updateTime = now;
        if (lastActiveAt == null) lastActiveAt = now;
    }

    @PreUpdate
    protected void onUpdate() {
        updateTime = LocalDateTime.now();
    }

    public ChatSession() {}

    // ---- getters & setters ----

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getStage() { return stage; }
    public void setStage(String stage) { this.stage = stage; }

    public String getExtraData() { return extraData; }
    public void setExtraData(String extraData) { this.extraData = extraData; }

    public Integer getMessageCount() { return messageCount; }
    public void setMessageCount(Integer messageCount) { this.messageCount = messageCount; }

    public LocalDateTime getLastActiveAt() { return lastActiveAt; }
    public void setLastActiveAt(LocalDateTime lastActiveAt) { this.lastActiveAt = lastActiveAt; }

    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }

    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
