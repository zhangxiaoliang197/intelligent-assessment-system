package com.assessment.admin.repository;

import com.assessment.admin.model.Dataset;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface DatasetRepository extends JpaRepository<Dataset, String> {
    List<Dataset> findByDatabaseId(String databaseId);
}
