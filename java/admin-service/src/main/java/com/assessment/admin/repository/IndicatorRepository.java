package com.assessment.admin.repository;

import com.assessment.admin.model.Indicator;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;

public interface IndicatorRepository extends JpaRepository<Indicator, String> {
    List<Indicator> findByCategory(String category);

    // 按数据集 ID 集合过滤指标，用于"按数据源绑定指标"的过滤场景
    List<Indicator> findByDatasetIdIn(Collection<String> datasetIds);
}
