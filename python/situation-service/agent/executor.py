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
from agent import geo_profile
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
    raw_mode: bool = False,
) -> Dict[str, Any]:
    """V2 取数：优先用 LLM 生成精确 SQL 执行，失败回退整表查询。

    复用评估分析 Text-to-SQL 能力（LLM 按 schema 生成 WHERE/聚合/GROUP BY），
    只有 schema 无字段元数据或 SQL 生成/执行失败时才回退原 query_admin_dataset，
    保证 V2 五阶段流程不因取数方式升级而中断。

    raw_mode=True 时为明细保真模式（geoMode=raw）：SQL 禁止聚合，必须保留
    全部列（尤其经纬度/名称/途经点列）的行级原值，供地图确定性管线使用。
    """
    # 先取数据集物理表结构，构建 Text-to-SQL 所需的 schema
    schema = tools.fetch_dataset_structure(ds_id)
    if not schema or not schema.get("fields"):
        logger.info("Text-to-SQL 无字段元数据，回退整表查询: datasetId=%s", ds_id)
        return tools.query_admin_dataset({"id": ds_id, "name": "", "tableName": ""}, limit)

    try:
        sql_result = call_llm_json(
            prompts.build_sql_messages(query, schema, intent, raw_mode=raw_mode),
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

    # 质量门控：SQL 执行成功但 0 行时不能静默返回空集——
    # 常见成因是 LLM 聚合 SQL 语义错误（错误 WHERE/JOIN），数据库不报错但结果为空。
    # 进入三级恢复：存活探针 → LLM SQL 纠错重试 → 确定性本地聚合兜底。
    if not _extract_rows(data):
        logger.info(
            "SQL 执行成功但结果 0 行，进入空结果质量门控: datasetId=%s sql=%s",
            ds_id, sql[:200],
        )
        return _recover_empty_sql_result(ds_id, query, intent, raw_mode, limit, schema, sql, data)

    # 统一字段：execute-sql 返回 rowCount，/dataset/{id}/query 返回 total，
    # 补齐 total 供下游（dataset 事件 / _format_data）统一读取。
    if "total" not in data and "rowCount" in data:
        data["total"] = data["rowCount"]
    data["_via_sql"] = True
    return data


# ── 空结果质量门控：确定性恢复链 ──────────────────────────────────────────
# 设计背景：Text-to-SQL 存在"执行成功但语义错误返回 0 行"的失败模式（如 WHERE
# 枚举值写错、时间字面量格式不符、JOIN 条件错），旧逻辑对此完全无感知，导致
# 聚合证据静默为空、最终产物 0 图表。恢复链三级：
#   1) 存活探针（整表取样）：物理表确为空 → 确认 table_empty，不再折腾；
#   2) LLM SQL 纠错重试 1 次：回喂真实列值分布，只修导致空集的子句；
#   3) 确定性兜底：raw 模式回整表明细；aggregate 模式由 LLM 声明聚合规格
#      （groupBy/measures/filters 白名单），服务端用标准库本地聚合，LLM 不再
#      接触 SQL 语法，从机制上杜绝"语义错 SQL 空集"。
_AGG_FUNCS = {"count", "sum", "avg", "max", "min"}
_FILTER_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}
_ALIAS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,30}$")


def _to_number(value: Any) -> Optional[float]:
    """宽松数值解析（整表接口数值常以字符串返回）；无法解析返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "").rstrip("%"))
        except ValueError:
            return None
    return None


def _build_value_hint(rows: List[Dict[str, Any]], max_values: int = 6) -> str:
    """从整表样本构造列值分布提示，供 SQL 纠错时选取真实枚举值。

    数值列给 min/max；分类列给 top-N 取值与计数。
    """
    if not rows:
        return ""
    lines: List[str] = []
    for col in list(rows[0].keys())[:20]:
        values = [r.get(col) for r in rows]
        non_empty = [v for v in values if v not in (None, "")]
        if not non_empty:
            continue
        numbers = [n for n in (_to_number(v) for v in non_empty) if n is not None]
        if len(numbers) >= max(1, len(non_empty) * 0.8):
            lines.append(f"{col}: 数值，min={min(numbers):g}，max={max(numbers):g}")
        else:
            counts: Dict[str, int] = {}
            for value in non_empty:
                label = str(value)[:40]
                counts[label] = counts.get(label, 0) + 1
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_values]
            lines.append(f"{col}: " + "，".join(f"{k}({v}条)" for k, v in top))
        if len(lines) >= 12:
            break
    return "\n".join(lines)


def _validate_filter_spec(spec: Dict[str, Any], columns_set: set) -> bool:
    """校验单个过滤规格是否合法（列存在、操作符在白名单、in 为数组）。"""
    if str(spec.get("column") or "") not in columns_set:
        return False
    op = str(spec.get("op") or "eq").lower()
    if op not in _FILTER_OPS:
        return False
    if op == "in" and not isinstance(spec.get("value"), list):
        return False
    return True


def _row_passes_filter(row: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    """对单行应用白名单过滤；数值优先按数值比较，退化到字符串比较。"""
    col = str(spec.get("column") or "")
    op = str(spec.get("op") or "eq").lower()
    actual = row.get(col)
    expected = spec.get("value")
    if op == "in":
        return actual in (expected or [])
    actual_num = _to_number(actual)
    expected_num = _to_number(expected)
    if actual_num is not None and expected_num is not None:
        left: Any = actual_num
        right: Any = expected_num
    else:
        left = "" if actual is None else str(actual)
        right = "" if expected is None else str(expected)
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


def _local_aggregate(
    rows: List[Dict[str, Any]], spec: Dict[str, Any], row_limit: int
) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    """按 LLM 声明的聚合规格在服务端白名单内执行确定性分组聚合。

    规格不合法（引用不存在的列/非法函数/非法别名）一律返回 None，由调用方放弃兜底。
    返回 (columns, rows)；rows 中分组列为字符串、度量列为数值。
    """
    if not isinstance(spec, dict) or not rows:
        return None
    group_cols = spec.get("groupBy")
    measures = spec.get("measures")
    filters_spec = spec.get("filters") or []
    if not isinstance(group_cols, list) or not group_cols:
        return None
    if not isinstance(measures, list) or not measures:
        return None
    if not isinstance(filters_spec, list):
        return None

    columns_set: set = set()
    for row in rows:
        columns_set.update(row.keys())

    group_cols = [str(c) for c in group_cols][:2]
    if any(c not in columns_set for c in group_cols):
        return None

    norm_measures: List[Tuple[str, str, str]] = []
    seen_aliases: set = set()
    for measure in measures[:4]:
        if not isinstance(measure, dict):
            return None
        func = str(measure.get("func") or "").lower()
        col = str(measure.get("column") or "")
        alias = str(measure.get("alias") or "")
        if func not in _AGG_FUNCS:
            return None
        if col != "*" and col not in columns_set:
            return None
        if not _ALIAS_PATTERN.match(alias) or alias in seen_aliases:
            return None
        seen_aliases.add(alias)
        norm_measures.append((func, col, alias))

    if any(not _validate_filter_spec(f, columns_set) for f in filters_spec):
        return None

    filtered = [
        row for row in rows
        if all(_row_passes_filter(row, f) for f in filters_spec)
    ]
    if not filtered:
        return [], []

    # 分组（键统一字符串化，None 归为空串），保留首次出现顺序
    groups: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    group_order: List[Tuple[str, ...]] = []
    for row in filtered:
        key = tuple("" if row.get(col) is None else str(row.get(col)) for col in group_cols)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append(row)

    out_rows: List[Dict[str, Any]] = []
    for key in group_order:
        group_rows = groups[key]
        out: Dict[str, Any] = {col: key[i] for i, col in enumerate(group_cols)}
        for func, col, alias in norm_measures:
            if func == "count":
                if col == "*":
                    value: Any = len(group_rows)
                else:
                    value = sum(1 for r in group_rows if r.get(col) not in (None, ""))
            else:
                numbers = [n for n in (_to_number(r.get(col)) for r in group_rows) if n is not None]
                if not numbers:
                    value = None
                elif func == "sum":
                    value = round(sum(numbers), 4)
                elif func == "avg":
                    value = round(sum(numbers) / len(numbers), 4)
                elif func == "max":
                    value = max(numbers)
                else:  # min
                    value = min(numbers)
            out[alias] = value
        out_rows.append(out)

    # 按第一个度量降序（None 排末尾），输出稳定且利于图表展示
    first_alias = norm_measures[0][2]

    def _sort_key(row: Dict[str, Any]) -> Tuple[int, float]:
        value = row.get(first_alias)
        return (1, 0.0) if value is None else (0, -float(value))

    out_rows.sort(key=_sort_key)
    if len(out_rows) > row_limit:
        out_rows = out_rows[:row_limit]
    return group_cols + [alias for _, _, alias in norm_measures], out_rows


def _recover_empty_sql_result(
    ds_id: str,
    query: str,
    intent: str,
    raw_mode: bool,
    limit: int,
    schema: Dict[str, Any],
    original_sql: str,
    original_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """SQL 成功但 0 行的确定性恢复链，返回带诊断标记的 payload。

    诊断字段（下划线前缀，不透出前端）：
        _empty_reason: table_empty / unrecovered / probe_failed
        _sql_corrected: LLM 纠错重试后取到数据
        _aggregation_fallback: 服务端本地聚合兜底取到数据
        _fallback_sampled_rows: 本地聚合所依据的整表样本行数
    """
    # 第 1 级：存活探针（同时作为后续兜底的样本数据，整表接口硬上限 1000 行）
    try:
        sample_payload = tools.query_admin_dataset(
            {"id": ds_id, "name": "", "tableName": ""}, min(limit, 1000)
        )
    except Exception as exc:
        logger.warning("空结果恢复-存活探针异常 datasetId=%s err=%s", ds_id, exc)
        original_payload["_empty_reason"] = "probe_failed"
        return original_payload

    sample_rows = _extract_rows(sample_payload) if isinstance(sample_payload, dict) else []
    if not sample_rows:
        logger.info("空结果恢复-物理表确认无数据 datasetId=%s", ds_id)
        original_payload["_empty_reason"] = "table_empty"
        return original_payload

    # 第 2 级：LLM SQL 纠错重试 1 次（回喂真实列值分布，低温避免发散）
    try:
        value_hint = _build_value_hint(sample_rows)
        corrected_resp = call_llm_json(
            prompts.build_sql_correction_messages(
                query, schema, intent, original_sql, value_hint, raw_mode=raw_mode
            ),
            0.1,
            config.LLM_MAX_TOKENS,
        )
        corrected_sql = ""
        if isinstance(corrected_resp, dict):
            corrected_sql = str(corrected_resp.get("sql") or "").strip()
        if corrected_sql and corrected_sql != original_sql:
            fixed = tools.execute_dataset_sql(ds_id, corrected_sql)
            if isinstance(fixed, dict) and fixed.get("success") and _extract_rows(fixed):
                logger.info(
                    "空结果恢复-SQL 纠错成功 datasetId=%s rows=%s",
                    ds_id, len(_extract_rows(fixed)),
                )
                fixed["_via_sql"] = True
                fixed["_sql_corrected"] = True
                if "total" not in fixed and "rowCount" in fixed:
                    fixed["total"] = fixed["rowCount"]
                return fixed
    except Exception as exc:
        logger.warning("空结果恢复-SQL 纠错异常 datasetId=%s err=%s", ds_id, exc)

    # 第 3 级 a：明细保真模式直接回整表明细（坐标列天然保留）
    if raw_mode:
        if isinstance(sample_payload, dict) and sample_payload.get("success"):
            logger.info("空结果恢复-明细模式回退整表 datasetId=%s rows=%s", ds_id, len(sample_rows))
            sample_payload["_fallback_table"] = True
            sample_payload["_recovery"] = "raw_full_table"
            return sample_payload
        original_payload["_empty_reason"] = "unrecovered_raw"
        return original_payload

    # 第 3 级 b：聚合模式由 LLM 声明聚合规格，服务端白名单本地聚合
    try:
        spec_resp = call_llm_json(
            prompts.build_agg_spec_messages(query, schema, intent),
            0.1,
            config.LLM_MAX_TOKENS,
        )
        aggregated = _local_aggregate(sample_rows, spec_resp if isinstance(spec_resp, dict) else {}, limit)
    except Exception as exc:
        logger.warning("空结果恢复-本地聚合异常 datasetId=%s err=%s", ds_id, exc)
        aggregated = None

    if aggregated:
        out_columns, out_rows = aggregated
        if out_rows:
            logger.info(
                "空结果恢复-本地聚合兜底成功 datasetId=%s groups=%s sampleRows=%s",
                ds_id, len(out_rows), len(sample_rows),
            )
            return {
                "success": True,
                "columns": out_columns,
                "rows": out_rows,
                "rowCount": len(out_rows),
                "total": len(out_rows),
                "_via_sql": False,
                "_aggregation_fallback": True,
                "_fallback_sampled_rows": len(sample_rows),
            }

    original_payload["_empty_reason"] = "unrecovered"
    logger.warning(
        "空结果恢复-三级恢复均未取到数据 datasetId=%s sql=%s", ds_id, original_sql[:200]
    )
    return original_payload


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

    # 取数策略（地图生成链路重构 §4.3）：
    # - geoMode=raw：明细保真模式，坐标列必须行级原值保留。带 filters 时走保真 Text-to-SQL
    #   （禁止聚合），否则直接整表查询（坐标列天然保留）；
    # - geoMode=aggregate（默认）：携带 filters/aggregation 时走 Text-to-SQL（LLM 按表结构
    #   生成精确 SQL），否则回退确定性 query_admin_dataset。任一路径失败均回退整表查询。
    filters = sub_question.get("filters")
    aggregation = sub_question.get("aggregation")
    geo_mode = str(sub_question.get("geoMode") or "aggregate").strip().lower()
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
        if geo_mode == "raw":
            # 明细保真模式：带 filters 时走保真 Text-to-SQL（禁止聚合、保留全部列），
            # 否则直接整表查询（所有列行级原值保留）
            if filters:
                payload = await asyncio.to_thread(
                    _query_dataset_with_sql,
                    dataset_id,
                    question,
                    sql_intent,
                    effective_row_limit,
                    True,
                )
            else:
                payload = await asyncio.to_thread(
                    tools.query_admin_dataset,
                    {"id": dataset_id, "name": "", "tableName": ""},
                    effective_row_limit,
                )
        elif use_text_to_sql:
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

    # 存储全量行（≤ SITUATION_DATA_ROW_LIMIT），供前端图表/地图全量重建；
    # LLM 只在 prompts._format_data 内部按 SITUATION_LLM_EVIDENCE_ROWS 采样，不会 token 爆炸。
    rows = _sanitize_rows(rows, sensitive_columns)
    # 重新计算 columns（脱敏后可能变化）
    if rows:
        columns = list(dict.fromkeys(str(k) for row in rows for k in row.keys()))

    # 摘要基于全量行计算（min/max/sum/top3 更准确），仍只输出聚合统计，不外发原始行。
    summary = _build_summary(rows, columns, question)
    # 空结果质量门控：把恢复链结论写入摘要，供 verifier/writer 区分"真无数据"与"取数失败"
    empty_reason = payload.get("_empty_reason") if isinstance(payload, dict) else None
    if not rows and empty_reason:
        reason_text = {
            "table_empty": "数据集当前无匹配记录",
            "probe_failed": "存活探针执行失败，无法确认数据是否存在",
            "unrecovered": "精确取数返回空集且自动纠错、本地聚合均未恢复",
            "unrecovered_raw": "明细取数返回空集且整表兜底未恢复",
        }.get(empty_reason, empty_reason)
        summary = f"（证据为空：子问题「{question}」{reason_text}）"
    total_rows = payload.get("total") or payload.get("rowCount") or len(rows)

    # 地理能力画像：取数后立即测定（地图生成链路重构 §4.1），
    # 全链路（map Writer / verifier / layout）只读该画像，不再各自判断
    geo = geo_profile.compute_geo_profile(columns, rows)

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
            "geoMode": geo_mode,
            "intent": sub_question.get("intent", ""),
            "viaSql": bool(payload.get("_via_sql")) if isinstance(payload, dict) else False,
            "relaxedTime": bool(sub_question.get("_relaxed_time")),
            # 空结果质量门控诊断标记（供 orchestrator 子问题级重试/verifier 口径使用）
            "emptyReason": empty_reason or "",
            "sqlCorrected": bool(payload.get("_sql_corrected")) if isinstance(payload, dict) else False,
            "aggregationFallback": bool(payload.get("_aggregation_fallback")) if isinstance(payload, dict) else False,
            "fallbackSampledRows": int(payload.get("_fallback_sampled_rows") or 0) if isinstance(payload, dict) else 0,
            "geoProfile": geo,
        },
    )
    await store.add_evidence(evidence)
    logger.info(
        "Executor 子问题 %s 取数完成: datasetId=%s rows=%s cols=%s viaSql=%s geoMode=%s hasGeo=%s",
        sq_id, dataset_id, len(rows), len(columns),
        bool(payload.get("_via_sql")) if isinstance(payload, dict) else False,
        geo_mode, geo.get("hasGeo"),
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
