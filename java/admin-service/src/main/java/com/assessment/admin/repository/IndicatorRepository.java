package com.assessment.admin.repository;

import com.assessment.admin.model.Indicator;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface IndicatorRepository extends JpaRepository<Indicator, String> {
    List<Indicator> findByCategory(String category);
}
