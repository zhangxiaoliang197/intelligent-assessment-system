package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "ass_dataset")
public class Dataset {

    @Id
    @Column(length = 32)
    private String id;

    @Column(length = 200, nullable = false)
    private String name;

    @Column(columnDefinition = "text")
    private String description;

    @Column(name = "database_id", length = 32)
    private String databaseId;

    @Column(name = "table_name", length = 200)
    private String tableName;

    @Column(name = "sql_text", columnDefinition = "text")
    private String sqlText;

    /** Comma separated users/teams allowed to query this dataset. Empty means admin-only. */
    @Column(name = "allowed_user_ids", columnDefinition = "text")
    private String allowedUserIds;

    @Column(name = "allowed_team_ids", columnDefinition = "text")
    private String allowedTeamIds;

    /** Optional comma separated projection. Sensitive columns must never be exposed by templates. */
    @Column(name = "allowed_columns", columnDefinition = "text")
    private String allowedColumns;

    @Column(name = "sensitive_columns", columnDefinition = "text")
    private String sensitiveColumns;

    @Column(name = "schema_version")
    private Integer schemaVersion;
    /** Table join JSON: [{"left":"orders.order_id","right":"order_items.order_id"}] */
    @Column(name = "key_mappings", columnDefinition = "json")
    private String keyMappings;

    private Integer records;

    @Column(name = "last_executed")
    private LocalDateTime lastExecuted;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @Column(name = "update_time")
    private LocalDateTime updateTime;

    @PrePersist
    protected void onCreate() {
        createTime = LocalDateTime.now();
        updateTime = LocalDateTime.now();
        if (records == null) records = 0;
        if (schemaVersion == null) schemaVersion = 1;
    }

    @PreUpdate
    protected void onUpdate() {
        updateTime = LocalDateTime.now();
    }

    public Dataset() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getDatabaseId() { return databaseId; }
    public void setDatabaseId(String databaseId) { this.databaseId = databaseId; }
    public String getTableName() { return tableName; }
    public void setTableName(String tableName) { this.tableName = tableName; }
    public String getSqlText() { return sqlText; }
    public void setSqlText(String sqlText) { this.sqlText = sqlText; }
    public String getAllowedUserIds() { return allowedUserIds; }
    public void setAllowedUserIds(String allowedUserIds) { this.allowedUserIds = allowedUserIds; }
    public String getAllowedTeamIds() { return allowedTeamIds; }
    public void setAllowedTeamIds(String allowedTeamIds) { this.allowedTeamIds = allowedTeamIds; }
    public String getAllowedColumns() { return allowedColumns; }
    public void setAllowedColumns(String allowedColumns) { this.allowedColumns = allowedColumns; }
    public String getSensitiveColumns() { return sensitiveColumns; }
    public void setSensitiveColumns(String sensitiveColumns) { this.sensitiveColumns = sensitiveColumns; }
    public Integer getSchemaVersion() { return schemaVersion; }
    public void setSchemaVersion(Integer schemaVersion) { this.schemaVersion = schemaVersion; }
    public String getKeyMappings() { return keyMappings; }
    public void setKeyMappings(String keyMappings) { this.keyMappings = keyMappings; }
    public Integer getRecords() { return records; }
    public void setRecords(Integer records) { this.records = records; }
    public LocalDateTime getLastExecuted() { return lastExecuted; }
    public void setLastExecuted(LocalDateTime lastExecuted) { this.lastExecuted = lastExecuted; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
