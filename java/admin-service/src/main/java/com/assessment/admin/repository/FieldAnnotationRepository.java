package com.assessment.admin.repository;

import com.assessment.admin.model.FieldAnnotation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;

public interface FieldAnnotationRepository extends JpaRepository<FieldAnnotation, String> {
    List<FieldAnnotation> findByDatasetId(String datasetId);
    List<FieldAnnotation> findByDatasetIdAndTableName(String datasetId, String tableName);
    @Transactional
    void deleteByDatasetId(String datasetId);
}
