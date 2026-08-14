package com.assessment.admin.repository;

import com.assessment.admin.model.FieldSynonym;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;

public interface FieldSynonymRepository extends JpaRepository<FieldSynonym, String> {
    List<FieldSynonym> findByConceptNorm(String conceptNorm);
    List<FieldSynonym> findByDatabaseId(String databaseId);
    List<FieldSynonym> findByDatasetIdIn(Collection<String> datasetIds);
    List<FieldSynonym> findByConceptNormIn(Collection<String> conceptNorms);
}
