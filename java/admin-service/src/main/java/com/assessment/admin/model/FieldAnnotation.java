package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "ass_field_annotation")
public class FieldAnnotation {

    @Id
    @Column(length = 32)
    private String id;

    @Column(name = "dataset_id", length = 32, nullable = false)
    private String datasetId;

    @Column(name = "table_name", length = 200, nullable = false)
    private String tableName;

    @Column(name = "column_name", length = 200, nullable = false)
    private String columnName;

    @Column(name = "column_type", length = 100)
    private String columnType;

    @Column(name = "is_primary_key")
    private Boolean isPrimaryKey;

    @Column(name = "is_nullable")
    private Boolean isNullable;

    @Column(name = "column_comment", length = 500)
    private String columnComment;

    @Column(name = "annotation", columnDefinition = "text")
    private String annotation;

    @Column(name = "business_meaning", columnDefinition = "text")
    private String businessMeaning;

    @Column(name = "data_category", length = 100)
    private String dataCategory;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @Column(name = "update_time")
    private LocalDateTime updateTime;

    @PrePersist
    protected void onCreate() {
        createTime = LocalDateTime.now();
        updateTime = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updateTime = LocalDateTime.now();
    }

    // Getters and Setters
    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getDatasetId() { return datasetId; }
    public void setDatasetId(String datasetId) { this.datasetId = datasetId; }
    public String getTableName() { return tableName; }
    public void setTableName(String tableName) { this.tableName = tableName; }
    public String getColumnName() { return columnName; }
    public void setColumnName(String columnName) { this.columnName = columnName; }
    public String getColumnType() { return columnType; }
    public void setColumnType(String columnType) { this.columnType = columnType; }
    public Boolean getIsPrimaryKey() { return isPrimaryKey; }
    public void setIsPrimaryKey(Boolean isPrimaryKey) { this.isPrimaryKey = isPrimaryKey; }
    public Boolean getIsNullable() { return isNullable; }
    public void setIsNullable(Boolean isNullable) { this.isNullable = isNullable; }
    public String getColumnComment() { return columnComment; }
    public void setColumnComment(String columnComment) { this.columnComment = columnComment; }
    public String getAnnotation() { return annotation; }
    public void setAnnotation(String annotation) { this.annotation = annotation; }
    public String getBusinessMeaning() { return businessMeaning; }
    public void setBusinessMeaning(String businessMeaning) { this.businessMeaning = businessMeaning; }
    public String getDataCategory() { return dataCategory; }
    public void setDataCategory(String dataCategory) { this.dataCategory = dataCategory; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
