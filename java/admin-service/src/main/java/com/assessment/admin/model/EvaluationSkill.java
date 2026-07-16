package com.assessment.admin.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Version;

import java.time.LocalDateTime;

/**
 * 评估分析 Skill。
 *
 * 步骤使用 JSON 保存，是因为步骤结构需要保持顺序，并允许以后在不破坏
 * 既有数据的情况下增加依赖和失败策略字段。Skill 本身存放在管理数据库，
 * 避免 qa-service 多进程部署时本地 JSON 文件互相覆盖。
 */
@Entity
@Table(
        name = "ass_evaluation_skill",
        uniqueConstraints = @UniqueConstraint(
                name = "uk_eval_skill_database_name",
                columnNames = {"database_id", "name"}
        ),
        indexes = @Index(name = "idx_eval_skill_database", columnList = "database_id")
)
public class EvaluationSkill {

    @Id
    @Column(length = 32)
    private String id;

    @Column(length = 100, nullable = false)
    private String name;

    @Column(columnDefinition = "text")
    private String description;

    @Column(name = "database_id", length = 32, nullable = false)
    private String databaseId;

    // 显式大长度让 Hibernate 按数据库方言选择 MEDIUMTEXT/TEXT/CLOB，
    // 避免 @Lob String 在 MySQL 方言下被建成只能保存 255 字节的 TINYTEXT。
    @Column(name = "steps_json", nullable = false, length = 1_000_000)
    private String stepsJson;

    @Version
    private Long version;

    @Column(name = "create_time", nullable = false)
    private LocalDateTime createTime;

    @Column(name = "update_time", nullable = false)
    private LocalDateTime updateTime;

    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        if (createTime == null) createTime = now;
        updateTime = now;
    }

    @PreUpdate
    protected void onUpdate() {
        updateTime = LocalDateTime.now();
    }

    public EvaluationSkill() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getDatabaseId() { return databaseId; }
    public void setDatabaseId(String databaseId) { this.databaseId = databaseId; }
    public String getStepsJson() { return stepsJson; }
    public void setStepsJson(String stepsJson) { this.stepsJson = stepsJson; }
    public Long getVersion() { return version; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
