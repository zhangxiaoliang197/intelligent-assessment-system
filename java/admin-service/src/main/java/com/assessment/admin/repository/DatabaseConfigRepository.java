package com.assessment.admin.repository;

import com.assessment.admin.model.DatabaseConfig;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface DatabaseConfigRepository extends JpaRepository<DatabaseConfig, String> {
    List<DatabaseConfig> findByType(String type);
}
