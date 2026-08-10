package com.assessment.admin.repository;

import com.assessment.admin.model.SituationReport;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

/**
 * 态势图产物 Repository。
 * 列表按 userId / teamIds 过滤（skill governance 约定）；
 * 分享查看按 token 查询（无需登录态）。
 */
public interface SituationReportRepository extends JpaRepository<SituationReport, String> {

    // 列表按创建人过滤（分页在 Controller 层用 Pageable 处理）
    List<SituationReport> findByUserIdOrderByCreatedAtDesc(String userId);

    // 分享 token 查询
    Optional<SituationReport> findByShareToken(String shareToken);
}
