package com.assessment.admin.repository;

import com.assessment.admin.model.AnnotationDraft;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/** 语义注解草稿仓储。 */
@Repository
public interface AnnotationDraftRepository extends JpaRepository<AnnotationDraft, String> {

    List<AnnotationDraft> findByDatasetIdOrderByCreateTimeDesc(String datasetId);

    List<AnnotationDraft> findByDatasetIdAndStatusOrderByCreateTimeDesc(String datasetId, String status);

    List<AnnotationDraft> findByBatchId(String batchId);

    List<AnnotationDraft> findByDatasetIdAndStatus(String datasetId, String status);

    Optional<AnnotationDraft> findFirstByDatasetIdAndColumnNameAndStatus(
            String datasetId, String columnName, String status);

    long countByDatasetIdAndStatus(String datasetId, String status);
}
