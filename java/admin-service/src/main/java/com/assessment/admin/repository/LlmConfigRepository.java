package com.assessment.admin.repository;

import com.assessment.admin.model.LlmConfig;
import org.springframework.data.jpa.repository.JpaRepository;

public interface LlmConfigRepository extends JpaRepository<LlmConfig, String> {
}
