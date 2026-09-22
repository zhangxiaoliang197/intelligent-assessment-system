package com.assessment.admin.model;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * 语义注解草稿（LLM 生成 / 人工修改，审核通过后才写入正式注解）。
 *
 * 与正式注解（{@link FieldAnnotation} + {@link Dataset#getSemanticJson()}）**物理隔离**：
 * 运行期（ipage / qa）只读正式注解，草稿在通过审核前对页面生成完全不可见。
 */
@Entity
@Table(name = "ass_annotation_draft")
public class AnnotationDraft {

    @Id
    @Column(length = 32)
    private String id;

    @Column(name = "dataset_id", length = 32, nullable = false)
    private String datasetId;

    @Column(name = "table_name", length = 200)
    private String tableName;

    /** 同一数据集一次生成 = 一个批次，便于整批通过/驳回 */
    @Column(name = "batch_id", length = 32)
    private String batchId;

    /** field=字段级语义；dataset=数据集级语义（entityKind/geometry 等） */
    @Column(length = 16)
    private String scope;

    @Column(name = "column_name", length = 200)
    private String columnName;

    /** 草稿内容（与正式注解同格式的 JSON 文本） */
    @Column(name = "draft_json", columnDefinition = "text")
    private String draftJson;

    /** draft / approved / rejected / superseded（同列再次生成时旧的置 superseded） */
    @Column(length = 16)
    private String status;

    /** llm / rule / manual */
    @Column(length = 16)
    private String source;

    @Column(length = 100)
    private String model;

    @Column(name = "prompt_hash", length = 64)
    private String promptHash;

    /** 本次调用消耗的 token（模型返回 usage 时记录） */
    @Column(name = "tokens")
    private Integer tokens;

    /** 硬错误（禁批量通过）：值域编造、格式/结构校验失败 */
    @Column(name = "issues_json", columnDefinition = "text")
    private String issuesJson;

    /** 软提示（可强制通过）：AnnotationValidator 的 W 系列告警、采样缺失说明等 */
    @Column(name = "warnings_json", columnDefinition = "text")
    private String warningsJson;

    /** 生成时用到的真实采样值（供人审核对"为什么没给出某个枚举"） */
    @Column(name = "sampled_json", columnDefinition = "text")
    private String sampledJson;

    @Column(name = "created_by", length = 64)
    private String createdBy;

    @Column(name = "create_time")
    private LocalDateTime createTime;

    @Column(name = "update_time")
    private LocalDateTime updateTime;

    @Column(name = "reviewed_by", length = 64)
    private String reviewedBy;

    @Column(name = "reviewed_at")
    private LocalDateTime reviewedAt;

    @Column(name = "review_remark", length = 500)
    private String reviewRemark;

    @PrePersist
    protected void onCreate() {
        createTime = LocalDateTime.now();
        updateTime = LocalDateTime.now();
        if (status == null) status = "draft";
        if (scope == null) scope = "field";
        if (source == null) source = "llm";
    }

    @PreUpdate
    protected void onUpdate() {
        updateTime = LocalDateTime.now();
    }

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getDatasetId() { return datasetId; }
    public void setDatasetId(String datasetId) { this.datasetId = datasetId; }
    public String getTableName() { return tableName; }
    public void setTableName(String tableName) { this.tableName = tableName; }
    public String getBatchId() { return batchId; }
    public void setBatchId(String batchId) { this.batchId = batchId; }
    public String getScope() { return scope; }
    public void setScope(String scope) { this.scope = scope; }
    public String getColumnName() { return columnName; }
    public void setColumnName(String columnName) { this.columnName = columnName; }
    public String getDraftJson() { return draftJson; }
    public void setDraftJson(String draftJson) { this.draftJson = draftJson; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getPromptHash() { return promptHash; }
    public void setPromptHash(String promptHash) { this.promptHash = promptHash; }
    public Integer getTokens() { return tokens; }
    public void setTokens(Integer tokens) { this.tokens = tokens; }
    public String getIssuesJson() { return issuesJson; }
    public void setIssuesJson(String issuesJson) { this.issuesJson = issuesJson; }
    public String getWarningsJson() { return warningsJson; }
    public void setWarningsJson(String warningsJson) { this.warningsJson = warningsJson; }
    public String getSampledJson() { return sampledJson; }
    public void setSampledJson(String sampledJson) { this.sampledJson = sampledJson; }
    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
    public String getReviewedBy() { return reviewedBy; }
    public void setReviewedBy(String reviewedBy) { this.reviewedBy = reviewedBy; }
    public LocalDateTime getReviewedAt() { return reviewedAt; }
    public void setReviewedAt(LocalDateTime reviewedAt) { this.reviewedAt = reviewedAt; }
    public String getReviewRemark() { return reviewRemark; }
    public void setReviewRemark(String reviewRemark) { this.reviewRemark = reviewRemark; }
}
