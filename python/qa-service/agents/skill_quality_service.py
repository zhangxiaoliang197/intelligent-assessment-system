"""Deterministic Skill quality scoring and operational analytics."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

from .skill_execution_store import (
    get_execution,
    list_executions,
    list_quality_reports,
    upsert_quality_report,
    utc_now,
)


def _clamp(value: float, maximum: float) -> float:
    return round(max(0.0, min(float(value), maximum)), 1)


def _final_answer(execution: Dict[str, Any]) -> str:
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    return str(result.get("final_answer") or result.get("finalAnswer") or "").strip()


def evaluate_execution_quality(
    run_id: str,
    *,
    expected_keywords: Iterable[str] = (),
) -> Dict[str, Any]:
    execution = get_execution(run_id)
    if not execution:
        raise ValueError(f"Skill 执行记录不存在: {run_id}")
    if not execution.get("finishedAt"):
        raise ValueError("Skill 尚未执行完成，暂时无法评测")

    status = str(execution.get("status") or "error")
    total = max(1, int(execution.get("totalSteps") or 0))
    completed = int(execution.get("completedSteps") or 0)
    matched = int(execution.get("matchedSteps") or 0)
    errors = int(execution.get("errorSteps") or 0)
    duration_ms = int(execution.get("durationMs") or 0)
    answer = _final_answer(execution)
    answer_lower = answer.lower()
    keywords = [str(item).strip() for item in expected_keywords if str(item).strip()][:30]
    keyword_hits = sum(1 for item in keywords if item.lower() in answer_lower)
    keyword_coverage = keyword_hits / len(keywords) if keywords else None

    completion = _clamp(completed / total * 30, 30)
    reliability = {
        "completed": 25,
        "partial": 16,
        "cancelled": 8,
        "timed_out": 5,
    }.get(status, 0)
    if errors:
        reliability = max(0, reliability - min(errors * 4, 12))
    data_coverage = _clamp(matched / total * 20, 20)
    if answer:
        base_answer_score = min(10.0, 3.0 + len(answer) / 160)
        evidence_bonus = min(5.0, answer.count("\n") * 0.5 + answer.count("：") * 0.4)
        answer_quality = base_answer_score + evidence_bonus
    else:
        answer_quality = 0.0
    if keyword_coverage is not None:
        answer_quality = answer_quality * 0.65 + keyword_coverage * 15 * 0.35
    answer_quality = _clamp(answer_quality, 15)
    if duration_ms <= 0:
        performance = 5.0
    elif duration_ms <= 30_000:
        performance = 10.0
    elif duration_ms <= 120_000:
        performance = 8.0
    elif duration_ms <= 300_000:
        performance = 5.0
    else:
        performance = 2.0

    dimensions = {
        "completion": {"score": completion, "maxScore": 30},
        "reliability": {"score": _clamp(reliability, 25), "maxScore": 25},
        "dataCoverage": {"score": data_coverage, "maxScore": 20},
        "answerQuality": {"score": answer_quality, "maxScore": 15},
        "performance": {"score": performance, "maxScore": 10},
    }
    score = round(sum(float(item["score"]) for item in dimensions.values()), 1)
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    issues: List[str] = []
    suggestions: List[str] = []
    if completed < total:
        issues.append(f"仅完成 {completed}/{total} 个编排步骤")
        suggestions.append("检查数据集匹配和步骤依赖条件，减少被跳过的步骤")
    if errors:
        issues.append(f"存在 {errors} 个失败步骤")
        suggestions.append("针对失败步骤配置重试次数、单步超时或更明确的数据集关键词")
    if matched < total:
        issues.append(f"数据源覆盖 {matched}/{total} 个步骤")
        suggestions.append("补充数据源或收窄步骤所需的数据集关键词")
    if not answer:
        issues.append("未形成最终分析结论")
        suggestions.append("检查综合输出指令，并确认整体超时足以覆盖结论生成")
    if keyword_coverage is not None and keyword_coverage < 0.6:
        issues.append(f"期望关键词覆盖率仅 {round(keyword_coverage * 100)}%")
        suggestions.append("在输出指令中明确要求覆盖核心业务指标和术语")
    if duration_ms > 300_000:
        issues.append("执行耗时超过 5 分钟")
        suggestions.append("拆分高耗时步骤，缩小查询范围或优化数据集索引")
    if not suggestions:
        suggestions.append("当前运行质量稳定，可继续通过批量评估观察不同问题下的一致性")

    report = {
        "reportId": str(uuid.uuid4()),
        "runId": run_id,
        "skillId": execution.get("skillId", ""),
        "actorId": execution.get("actorId", ""),
        "score": score,
        "grade": grade,
        "dimensions": dimensions,
        "issues": issues,
        "suggestions": suggestions,
        "expectedKeywordCoverage": None
        if keyword_coverage is None
        else round(keyword_coverage * 100, 1),
        "createdAt": utc_now(),
    }
    stored = upsert_quality_report(report)
    stored["expectedKeywordCoverage"] = report["expectedKeywordCoverage"]
    return stored


def get_skill_operations_overview(
    *,
    skill_id: str = "",
    actor_id: str = "",
    days: int = 30,
) -> Dict[str, Any]:
    days = max(1, min(int(days), 365))
    catalog = list_executions(skill_id=skill_id, actor_id=actor_id, limit=200)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    executions = []
    for item in catalog.get("items", []):
        try:
            started = datetime.fromisoformat(str(item.get("startedAt") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if started >= cutoff:
            executions.append(item)

    statuses = Counter(str(item.get("status") or "unknown") for item in executions)
    triggers = Counter(str(item.get("trigger") or "interactive") for item in executions)
    durations = [int(item.get("durationMs") or 0) for item in executions if item.get("durationMs")]
    reports = list_quality_reports(skill_id=skill_id, actor_id=actor_id, limit=50)
    report_run_ids = {str(item.get("runId") or "") for item in executions}
    reports = [item for item in reports if str(item.get("runId") or "") in report_run_ids]
    average_quality = (
        round(sum(float(item.get("score") or 0) for item in reports) / len(reports), 1)
        if reports
        else 0.0
    )
    completed_like = statuses["completed"] + statuses["partial"]
    total = len(executions)
    return {
        "skillId": skill_id,
        "days": days,
        "runCount": total,
        "successRate": round(completed_like / total * 100, 1) if total else 0.0,
        "cancelRate": round(statuses["cancelled"] / total * 100, 1) if total else 0.0,
        "timeoutRate": round(statuses["timed_out"] / total * 100, 1) if total else 0.0,
        "averageDurationMs": round(sum(durations) / len(durations)) if durations else 0,
        "averageQualityScore": average_quality,
        "evaluatedRuns": len(reports),
        "statusDistribution": dict(statuses),
        "triggerDistribution": dict(triggers),
        "recentReports": reports[:10],
        "generatedAt": utc_now(),
    }
