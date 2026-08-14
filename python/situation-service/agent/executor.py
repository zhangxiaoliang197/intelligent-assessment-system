"""Executor —— 研究层（态势图 Agent 架构重构 v1.1 阶段 2）。

设计目标（参见方案文档 §4.2.2）：
- MapReduce 并行单元：每个 subQuestion 一个 Executor task，asyncio.gather 并发
- 工具集收窄（v1.1）：query_admin_dataset（整表）+ Text-to-SQL（精确过滤/聚合）
- 暂不接入 knowledge / indicator / evaluation
- 结果落地到 EvidenceStore

实现选择（工程权衡）：
- Planner 已基于 schema 给出 datasetId/filters/aggregation，Executor 在 sub_question
  携带 filters/aggregation 时走 Text-to-SQL（LLM 按表结构生成精确 SQL，复用评估分析能力），
  否则回退确定性 query_admin_dataset；任一路径失败均回退整表查询
- 时间窗放宽由 orchestrator 在所有证据为空时触发，调用本模块的 _strip_time_filter 重试
"""
import asyncio
import datetime as dt
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import config
from agent import prompts, tools
from agent.evidence_store import Evidence, EvidenceStore
from llm_client import call_llm_json

logger = logging.getLogger("situation-service")


# 时间字段识别正则：匹配以 time/date/时间/日期 等关键词结尾或包含的字段名
_TIME_FIELD_PATTERN = re.compile(
    r"(time|date|时间|日期|created_at|update_time|record_time|detect_time|warning_time|"
    r"start_time|issue_time|eval_date|discovered_time|planned_time)",
    re.IGNORECASE,
)


def _is_time_field(name: str) -> bool:
    """判断字段名是否属于时间类（用于时间窗放宽时识别可剔除的过滤项）。"""
    return bool(_TIME_FIELD_PATTERN.search(str(name or "")))


def _has_time_filter(filters: Optional[Dict[str, Any]]) -> bool:
    """sub_question.filters 中是否含时间字段过滤。"""
    if not isinstance(filters, dict) or not filters:
        return False
    return any(_is_time_field(key) for key in filters.keys())


def _strip_time_filter(sub_question: Dict[str, Any]) -> Dict[str, Any]:
    """返回剔除时间过滤后的 sub_question 副本（用于时间窗放宽重试）。"""
    filters = sub_question.get("filters")
    if not isinstance(filters, dict) or not filters:
        return dict(sub_question)
    relaxed = {k: v for k, v in filters.items() if not _is_time_field(k)}
    new_sq = dict(sub_question)
    new_sq["filters"] = relaxed
    new_sq["_relaxed_time"] = True
    return new_sq


def _any_sub_question_has_time_filter(sub_questions: List[Dict[str, Any]]) -> bool:
    """是否任一 sub_question 含时间过滤（供 orchestrator 决定是否触发放宽）。"""
    return any(_has_time_filter(sq.get("filters")) for sq in sub_questions)


def _strip_time_filters(sub_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量剔除时间过滤（供 orchestrator 时间窗放宽重试使用）。"""
    return [_strip_time_filter(sq) for sq in sub_questions]


def _query_dataset_with_sql(
    ds_id: str,
    query: str,
    intent: str,
    limit: int,
) -> Dict[str, Any]:
    """V2 取数：优先用 LLM 生成精确 SQL 执行，失败回退整表查询。

    复用评估分析 Text-to-SQL 能力（LLM 按 schema 生成 WHERE/聚合/GROUP BY），
    只有 schema 无字段元数据或 SQL 生成/执行失败时才回退原 query_admin_dataset，
    保证 V2 五阶段流程不因取数方式升级而中断。
    """
    # 先取数据集物理表结构，构建 Text-to-SQL 所需的 schema
    schema = tools.fetch_dataset_structure(ds_id)
    if not schema or not schema.get("fields"):
        logger.info("Text-to-SQL 无字段元数据，回退整表查询: datasetId=%s", ds_id)
        return tools.query_admin_dataset({"id": ds_id, "name": "", "tableName": ""}, limit)

    try:
        sql_result = call_llm_json(
            prompts.build_sql_messages(query, schema, intent),
            0.3,
            config.LLM_MAX_TOKENS,
        )
        sql = ""
        if isinstance(sql_result, dict):
            sql = str(sql_result.get("sql") or "").strip()
        elif isinstance(sql_result, str):
            sql = sql_result.strip()
        if not sql:
            logger.warning("LLM 未生成 SQL，回退整表查询: datasetId=%s", ds_id)
            return tools.query_admin_dataset({"id": ds_id, "name": "", "tableName": ""}, limit)
    except Exception as exc:
        logger.warning("SQL 生成失败，回退整表查询: datasetId=%s err=%s", ds_id, exc)
        return tools.query_admin_dataset({"id": ds_id, "name": "", "tableName": ""}, limit)

    data = tools.execute_dataset_sql(ds_id, sql)
    if not data.get("success"):
        logger.warning(
            "SQL 执行失败，回退整表查询: datasetId=%s sql=%s err=%s",
            ds_id, sql[:200], data.get("message", "")[:200],
        )
        return tools.query_admin_dataset({"id": ds_id, "name": "", "tableName": ""}, limit)

    # 统一字段：execute-sql 返回 rowCount，/dataset/{id}/query 返回 total，
    # 补齐 total 供下游（dataset 事件 / _format_data）统一读取。
    if "total" not in data and "rowCount" in data:
        data["total"] = data["rowCount"]
    data["_via_sql"] = True
    return data


def _extract_columns(payload: Dict[str, Any]) -> List[str]:
    """从 query_admin_dataset 返回中提取字段名列表。"""
    if not isinstance(payload, dict):
        return []
    columns = payload.get("columns")
    if isinstance(columns, list):
        return [str(c) for c in columns]
    rows = payload.get("rows")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return list(dict.fromkeys(str(k) for row in rows for k in row.keys()))
    return []


def _extract_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 query_admin_dataset 返回中提取行列表。"""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _truncate_rows(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """按 SITUATION_LLM_EVIDENCE_ROWS 上限截断行（保护 LLM 上下文）。"""
    if limit <= 0 or not rows:
        return rows[:0] if limit == 0 else rows
    return rows[:limit]


def _sanitize_rows(rows: List[Dict[str, Any]], sensitive_columns: Tuple[str, ...]) -> List[Dict[str, Any]]:
    """脱敏：剔除配置中的敏感列（姓名/身份证/手机号等）。

    与 orchestrator._sensitive_column 同口径，但不依赖 bundle 上下文。
    """
    if not sensitive_columns:
        return rows
    sensitive_set = {col.lower() for col in sensitive_columns}
    sanitized = []
    for row in rows:
        new_row = {k: v for k, v in row.items() if str(k).lower() not in sensitive_set}
        sanitized.append(new_row)
    return sanitized


def _build_summary(rows: List[Dict[str, Any]], columns: List[str], sub_question: str) -> str:
    """生成证据摘要（确定性，不调 LLM）。

    摘要要包含：行数、字段数、数值字段的 min/max/sum、分类字段的 top-3。
    供下游 chart Writer 快速理解数据形态。
    """
    if not rows:
        return f"（证据为空：子问题「{sub_question}」未取到数据）"

    lines = [f"行数：{len(rows)}，字段数：{len(columns)}"]

    # 数值字段统计（取前 5 个）
    numeric_stats = []
    for col in columns[:20]:
        values = []
        for row in rows:
            value = row.get(col)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
            elif isinstance(value, str):
                try:
                    values.append(float(value.replace(",", "").rstrip("%")))
                except (ValueError, AttributeError):
                    pass
        if values:
            numeric_stats.append(
                f"{col}(min={min(values):.2f}, max={max(values):.2f}, sum={sum(values):.2f})"
            )
        if len(numeric_stats) >= 5:
            break
    if numeric_stats:
        lines.append("数值字段：" + "；".join(numeric_stats))

    # 分类字段 top-3（取前 3 个非数值字段）
    category_stats = []
    for col in columns[:20]:
        if any(col in s for s in numeric_stats):
            continue
        counts: Dict[str, int] = {}
        for row in rows:
            value = row.get(col)
            if value not in (None, ""):
                label = str(value)[:30]
                counts[label] = counts.get(label, 0) + 1
        if counts and 1 < len(counts) <= 50:
            top3 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            category_stats.append(
                f"{col}(" + "，".join(f"{k}:{v}" for k, v in top3) + ")"
            )
        if len(category_stats) >= 3:
            break
    if category_stats:
        lines.append("分类字段：" + "；".join(category_stats))

    return "\n".join(lines)


async def execute_sub_question(
    sub_question: Dict[str, Any],
    store: EvidenceStore,
    row_limit: Optional[int] = None,
) -> Evidence:
    """执行单个子问题的取数任务（MapReduce 单元）。

    Args:
        sub_question: Planner 输出的子问题 dict，含 id/question/datasetId/filters/aggregation
        store: 共享 EvidenceStore，结果写入其中
        row_limit: 行数上限，默认取 config.SITUATION_DATA_ROW_LIMIT

    Returns:
        Evidence 对象（已写入 store）
    """
    sq_id = str(sub_question.get("id") or "").strip()
    question = str(sub_question.get("question") or "").strip()
    dataset_id = str(sub_question.get("datasetId") or "").strip()

    if not dataset_id:
        logger.warning("Executor 子问题 %s 无 datasetId", sq_id)
        evidence = Evidence(
            id=sq_id,
            sub_question=question,
            rows=[],
            columns=[],
            summary=f"（子问题「{question}」未指定数据集）",
            source="",
            dataset_ref="",
            meta={"error": "missing_dataset_id"},
        )
        await store.add_evidence(evidence)
        return evidence

    effective_row_limit = row_limit or config.SITUATION_DATA_ROW_LIMIT
    sensitive_columns = config.SITUATION_SENSITIVE_COLUMNS

    # 取数策略：sub_question 携带 filters/aggregation 时走 Text-to-SQL（LLM 按表结构
    # 生成精确 SQL），否则回退确定性 query_admin_dataset。任一路径失败均回退整表查询。
    filters = sub_question.get("filters")
    aggregation = sub_question.get("aggregation")
    use_text_to_sql = bool(filters or aggregation)

    # 构建 Text-to-SQL 的 intent 文本（让 LLM 知道过滤与聚合意图）
    intent_parts = []
    if filters:
        try:
            intent_parts.append(f"过滤条件: {json.dumps(filters, ensure_ascii=False)}")
        except (TypeError, ValueError):
            intent_parts.append(f"过滤条件: {filters}")
    if aggregation:
        intent_parts.append(f"聚合方式: {aggregation}")
    sql_intent = "；".join(intent_parts) if intent_parts else str(sub_question.get("intent") or "")

    try:
        if use_text_to_sql:
            # Text-to-SQL：LLM 按数据集表结构生成精确 SQL（WHERE/聚合/GROUP BY）
            payload = await asyncio.to_thread(
                _query_dataset_with_sql,
                dataset_id,
                question,
                sql_intent,
                effective_row_limit,
            )
        else:
            # 无 filters/aggregation：直接整表查询（admin-service 端做 ACL + 物理表绑定）
            payload = await asyncio.to_thread(
                tools.query_admin_dataset,
                {"id": dataset_id, "name": "", "tableName": ""},
                effective_row_limit,
            )
    except Exception as exc:
        logger.warning("Executor 子问题 %s 取数异常: %s", sq_id, exc)
        evidence = Evidence(
            id=sq_id,
            sub_question=question,
            rows=[],
            columns=[],
            summary=f"（取数失败：{str(exc)[:100]}）",
            source=dataset_id,
            dataset_ref=dataset_id,
            meta={"error": str(exc)[:200]},
        )
        await store.add_evidence(evidence)
        return evidence

    success = bool(payload.get("success")) if isinstance(payload, dict) else False
    if not success:
        msg = payload.get("message", "未知错误") if isinstance(payload, dict) else "响应非对象"
        logger.warning("Executor 子问题 %s 取数失败: %s", sq_id, msg)
        evidence = Evidence(
            id=sq_id,
            sub_question=question,
            rows=[],
            columns=[],
            summary=f"（取数失败：{str(msg)[:100]}）",
            source=dataset_id,
            dataset_ref=dataset_id,
            meta={"error": str(msg)[:200]},
        )
        await store.add_evidence(evidence)
        return evidence

    columns = _extract_columns(payload)
    rows = _extract_rows(payload)

    # 截断 + 脱敏
    rows = _truncate_rows(rows, config.SITUATION_LLM_EVIDENCE_ROWS)
    rows = _sanitize_rows(rows, sensitive_columns)
    # 重新计算 columns（脱敏后可能变化）
    if rows:
        columns = list(dict.fromkeys(str(k) for row in rows for k in row.keys()))

    summary = _build_summary(rows, columns, question)
    total_rows = payload.get("total") or payload.get("rowCount") or len(rows)

    evidence = Evidence(
        id=sq_id,
        sub_question=question,
        rows=rows,
        columns=columns,
        summary=summary,
        source=dataset_id,
        dataset_ref=dataset_id,
        meta={
            "totalRows": total_rows,
            "returnedRows": len(rows),
            "truncated": total_rows > len(rows),
            "filters": sub_question.get("filters"),
            "aggregation": sub_question.get("aggregation"),
            "intent": sub_question.get("intent", ""),
            "viaSql": bool(payload.get("_via_sql")) if isinstance(payload, dict) else False,
            "relaxedTime": bool(sub_question.get("_relaxed_time")),
        },
    )
    await store.add_evidence(evidence)
    logger.info(
        "Executor 子问题 %s 取数完成: datasetId=%s rows=%s cols=%s viaSql=%s",
        sq_id, dataset_id, len(rows), len(columns),
        bool(payload.get("_via_sql")) if isinstance(payload, dict) else False,
    )
    return evidence


async def execute_all(
    sub_questions: List[Dict[str, Any]],
    store: EvidenceStore,
    max_concurrent: Optional[int] = None,
) -> List[Evidence]:
    """MapReduce 扇出：所有子问题并行执行，受 max_concurrent 节流。

    Args:
        sub_questions: Planner 输出的子问题列表
        store: 共享 EvidenceStore
        max_concurrent: 并发上限，默认取 config.SITUATION_MAX_CONCURRENT

    Returns:
        所有 Evidence 列表（顺序与 sub_questions 对齐）
    """
    if not sub_questions:
        return []

    concurrency = max_concurrent or config.SITUATION_MAX_CONCURRENT
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _bounded(sq: Dict[str, Any]) -> Evidence:
        async with semaphore:
            return await execute_sub_question(sq, store)

    tasks = [_bounded(sq) for sq in sub_questions]
    evidences = await asyncio.gather(*tasks, return_exceptions=False)
    return list(evidences)


__all__ = [
    "execute_sub_question",
    "execute_all",
    "_any_sub_question_has_time_filter",
    "_strip_time_filters",
]
