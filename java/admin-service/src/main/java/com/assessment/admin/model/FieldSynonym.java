package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 语义目录（Semantic Catalog）：业务概念 → 物理列 的同义词/别名条目。
 * 供指标编译器确定性解析公式项，替代运行期字符串相似度猜测。
 */
@Entity
@Table(name = "ass_field_synonym")
public class FieldSynonym {

    @Id
    @Column(length = 32)
    private String id;

    /** 业务概念/公式项，如 "命中次数"、"战损率"、"物品" */
    @Column(length = 200, nullable = false)
    private String concept;

    /** 归一化概念（去空格/标点/小写），用于确定性匹配 */
    @Column(length = 200, nullable = false)
    private String conceptNorm;

    @Column(name = "database_id", length = 32)
    private String databaseId;

    @Column(name = "dataset_id", length = 32)
    private String datasetId;

    @Column(name = "table_name", length = 200)
    private String tableName;

    @Column(name = "column_name", length = 200)
    private String columnName;

    @Column(name = "column_comment", length = 500)
    private String columnComment;

    /** 映射来源：manual / annotation / llm / import */
    @Column(length = 32)
    private String source;

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

    public FieldSynonym() {}

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getConcept() { return concept; }
    public void setConcept(String concept) { this.concept = concept; }
    public String getConceptNorm() { return conceptNorm; }
    public void setConceptNorm(String conceptNorm) { this.conceptNorm = conceptNorm; }
    public String getDatabaseId() { return databaseId; }
    public void setDatabaseId(String databaseId) { this.databaseId = databaseId; }
    public String getDatasetId() { return datasetId; }
    public void setDatasetId(String datasetId) { this.datasetId = datasetId; }
    public String getTableName() { return tableName; }
    public void setTableName(String tableName) { this.tableName = tableName; }
    public String getColumnName() { return columnName; }
    public void setColumnName(String columnName) { this.columnName = columnName; }
    public String getColumnComment() { return columnComment; }
    public void setColumnComment(String columnComment) { this.columnComment = columnComment; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
