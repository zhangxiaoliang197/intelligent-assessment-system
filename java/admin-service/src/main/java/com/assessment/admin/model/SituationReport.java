package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 态势图产物实体。
 * 对应表 situation_report，v1 采用 snapshot_json 存完整快照（见 docs/situation-map/07 §2.1）。
 * 由 situation-service 调 admin-service CRUD 落库，不直连 DB（ADR-11）。
 */
@Entity
@Table(name = "situation_report")
public class SituationReport {

    @Id
    @Column(length = 40)
    private String id;                    // reportId，如 r_20260810_xxxx

    @Column(length = 200, nullable = false)
    private String title;

    @Column(columnDefinition = "text")
    private String query;

    @Column(length = 20)
    private String source;                // manual | qa | indicator | evaluation

    @Column(name = "user_id", length = 64)
    private String userId;

    @Column(name = "team_ids", length = 255)
    private String teamIds;               // 团队 id 逗号分隔

    @Column(length = 20, nullable = false)
    private String status;                // generating | ready | partial | failed

    @Column(name = "snapshot_json", columnDefinition = "longtext")
    private String snapshotJson;          // 完整产物快照 JSON（charts/map/narrative/datasets）

    @Column(name = "share_token", length = 64)
    private String shareToken;            // 分享 token，null 表示未分享

    @Column(name = "share_expires_at")
    private LocalDateTime shareExpiresAt;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }

    public SituationReport() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getQuery() { return query; }
    public void setQuery(String query) { this.query = query; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public String getUserId() { return userId; }
    public void setUserId(String userId) { this.userId = userId; }
    public String getTeamIds() { return teamIds; }
    public void setTeamIds(String teamIds) { this.teamIds = teamIds; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getSnapshotJson() { return snapshotJson; }
    public void setSnapshotJson(String snapshotJson) { this.snapshotJson = snapshotJson; }
    public String getShareToken() { return shareToken; }
    public void setShareToken(String shareToken) { this.shareToken = shareToken; }
    public LocalDateTime getShareExpiresAt() { return shareExpiresAt; }
    public void setShareExpiresAt(LocalDateTime shareExpiresAt) { this.shareExpiresAt = shareExpiresAt; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
