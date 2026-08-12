package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 聊天历史索引实体。
 * 对应表 ass_chat_history，冗余表，避免历史列表查询 JOIN 消息表。
 * 每次会话更新时 upsert，保持与 ass_chat_session 的最终一致性。
 */
@Entity
@Table(name = "ass_chat_history")
public class ChatHistory {

    @Id
    @Column(length = 32)
    private String id;

    @Column(name = "session_id", length = 32, nullable = false)
    private String sessionId;

    @Column(name = "user_id", length = 64, nullable = false)
    private String userId;

    @Column(length = 20, nullable = false)
    private String type;

    @Column(length = 200, nullable = false)
    private String title;

    @Column(length = 500, nullable = false)
    private String summary = "";

    @Column(name = "skill_id", length = 32)
    private String skillId;                  // evaluation 专用

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @PrePersist
    protected void onCreate() {
        if (createTime == null) createTime = LocalDateTime.now();
    }

    public ChatHistory() {}

    // ---- getters & setters ----

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }

    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }

    public String getType() { return type; }
    public void setType(String type) { this.type = type; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getSummary() { return summary; }
    public void setSummary(String summary) { this.summary = summary; }

    public String getSkillId() { return skillId; }
    public void setSkillId(String skillId) { this.skillId = skillId; }

    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
