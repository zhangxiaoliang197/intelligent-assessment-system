package com.assessment.admin.repository;

import com.assessment.admin.model.EvaluationSkill;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface EvaluationSkillRepository extends JpaRepository<EvaluationSkill, String> {
    List<EvaluationSkill> findByDatabaseIdOrderByCreateTimeAsc(String databaseId);
}
