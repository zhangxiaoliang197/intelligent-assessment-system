"""Verifier —— 校验层（态势图 Agent 架构重构 v1.1 阶段 4）。

设计目标（参见方案文档 §4.2.5）：
- 规则通道（确定性，必须通过，零 LLM 成本）：
  · chart 数量 ≥ 2（v1.1 硬约束）
  · chart 类型-数据适配校验（v1.1 新增）：pie 分类数 ≤ 8、radar 维度 3-12 等
  · chart 数值证据校验（沿用 orchestrator._verification 思路，但简化为内联检查）
  · narrative 引用 chartId 必须命中
- LLM 通道（可选开启 SITUATION_VERIFIER_LLM=true）：语义一致性检查
- Reflection 决策：失败 → 回 WRITE 重写，上限 2 轮
"""
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import config
from agent.evidence_store import EvidenceStore

logger = logging.getLogger("situation-service")


# ──────────────────────────────────────────────────────────────────
# 工具函数：从 ECharts option 提取数值/分类
# ──────────────────────────────────────────────────────────────────

def _extract_numbers(value: Any) -> List[float]:
    """递归提取所有数值（用于证据校验）。"""
    numbers = []
    if isinstance(value, bool):
        return numbers
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            numbers.append(float(value))
        return numbers
    if isinstance(value, dict):
        for v in value.values():
            numbers.extend(_extract_numbers(v))
    elif isinstance(value, list):
        for item in value:
            numbers.extend(_extract_numbers(item))
    return numbers


def _count_pie_categories(option: dict) -> int:
    """统计 pie 图的分类数（series.data 长度）。"""
    for series in option.get("series", []) or []:
        if isinstance(series, dict) and str(series.get("type", "")).lower() == "pie":
            data = series.get("data")
            return len(data) if isinstance(data, list) else 0
    return 0


def _has_negative_pie_values(option: dict) -> bool:
    """检查 pie 图是否有负值分片。"""
    for series in option.get("series", []) or []:
        if not isinstance(series, dict):
            continue
        if str(series.get("type", "")).lower() != "pie":
            continue
        for item in series.get("data", []) or []:
            if isinstance(item, dict):
                value = item.get("value")
            else:
                value = item
            try:
                if float(value) < 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _count_radar_dimensions(option: dict) -> int:
    """统计 radar 图的维度数（radar.indicator 长度）。"""
    radar = option.get("radar")
    if not isinstance(radar, dict):
        return 0
    indicator = radar.get("indicator")
    return len(indicator) if isinstance(indicator, list) else 0


def _count_xaxis_samples(option: dict) -> int:
    """统计 line 图的 X 轴样本数。"""
    xAxis = option.get("xAxis")
    if isinstance(xAxis, list) and xAxis:
        data = xAxis[0].get("data") if isinstance(xAxis[0], dict) else None
        return len(data) if isinstance(data, list) else 0
    if isinstance(xAxis, dict):
        data = xAxis.get("data")
        return len(data) if isinstance(data, list) else 0
    return 0


def _find_category_axis(option: dict) -> Optional[dict]:
    """找到 type='category' 的轴配置（bar 图类目轴可能在 xAxis 或 yAxis）。

    ECharts 中纵向柱状图类目轴在 xAxis，横向条形图类目轴在 yAxis。
    仅凭 xAxis.data 判断会漏掉横向条形图，导致误报「分类为空」。
    """
    for axis_key in ("xAxis", "yAxis"):
        axis = option.get(axis_key)
        if isinstance(axis, dict):
            axis = [axis]
        if not isinstance(axis, list):
            continue
        for a in axis:
            if isinstance(a, dict) and str(a.get("type", "")).lower() == "category":
                return a
    return None


def _count_scatter_points(option: dict) -> int:
    """统计 scatter 图的点数。"""
    total = 0
    for series in option.get("series", []) or []:
        if not isinstance(series, dict):
            continue
        if str(series.get("type", "")).lower() != "scatter":
            continue
        data = series.get("data")
        if isinstance(data, list):
            total += len(data)
    return total


def _count_bar_categories(option: dict) -> int:
    """bar 图分类数：优先取 type='category' 的轴（支持横向条形图），
    未显式声明 category 时回退到 xAxis.data（兼容旧配置）。"""
    cat_axis = _find_category_axis(option)
    if cat_axis is not None:
        data = cat_axis.get("data")
        return len(data) if isinstance(data, list) else 0
    return _count_xaxis_samples(option)


# ──────────────────────────────────────────────────────────────────
# 类型-数据适配校验（v1.1 新增）
# ──────────────────────────────────────────────────────────────────

def check_chart_type_data_fit(chart: Dict[str, Any]) -> Optional[str]:
    """按 §4.2.4 适配规则表逐图校验。返回失败原因字符串（None 表示通过）。

    规则：
        pie：分类数 ≤ 8；不得有负值分片
        radar：维度 ∈ [3, 12]
        line：X 轴样本 ≥ 2
        bar：分类数 ≤ 30
        scatter：点数 ≥ 5
        所有：series.data 长度 > 0
    """
    if not isinstance(chart, dict):
        return "chart 不是对象"
    option = chart.get("option")
    if not isinstance(option, dict):
        return "option 缺失或非对象"

    series = option.get("series")
    if not isinstance(series, list) or not series:
        return "series 缺失或为空"

    chart_type = str(chart.get("type") or "").lower()

    if chart_type == "pie":
        cat_count = _count_pie_categories(option)
        if cat_count == 0:
            return "pie 图 series.data 为空"
        if cat_count > 8:
            return f"pie 图分类数 {cat_count} > 8，应合并为「其他」或改用 bar"
        if _has_negative_pie_values(option):
            return "pie 图含负值分片（饼图不允许负值）"

    elif chart_type == "radar":
        dims = _count_radar_dimensions(option)
        if dims == 0:
            return "radar 图缺少 radar.indicator 维度定义"
        if dims < 3:
            return f"radar 图维度数 {dims} < 3"
        if dims > 12:
            return f"radar 图维度数 {dims} > 12"

    elif chart_type == "line":
        samples = _count_xaxis_samples(option)
        if samples < 2:
            return f"line 图 X 轴样本数 {samples} < 2（至少两个点才成线）"

    elif chart_type == "bar":
        cat_count = _count_bar_categories(option)
        if cat_count == 0:
            return "bar 图分类轴为空（xAxis/yAxis 均无 category 数据）"
        if cat_count > 30:
            return f"bar 图分类数 {cat_count} > 30，应聚合或拆分"

    elif chart_type == "scatter":
        points = _count_scatter_points(option)
        if points < 5:
            return f"scatter 图点数 {points} < 5"

    return None


# ──────────────────────────────────────────────────────────────────
# 数值证据校验（沿用 orchestrator._verification 思路）
# ──────────────────────────────────────────────────────────────────

def _as_number(value: Any) -> Optional[float]:
    """把值解析为数值（兼容字符串数字/百分比/千分位），非数值返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            number = float(value.replace(",", "").rstrip("%"))
            return number if math.isfinite(number) else None
        except (ValueError, AttributeError):
            return None
    return None


def _evidence_all_numbers(store: EvidenceStore) -> List[float]:
    """收集可用于复算图表数值的候选值集合。

    与 legacy orchestrator._bundle_numbers 同口径：除原始行值外，还纳入确定性统计值
    （数值列的 min/max/sum/avg/count、分类列的频次计数、分组聚合的 count/sum/avg）。
    chart Writer 在 prompt 中看到的正是这些统计值，图表展示的聚合指标（如平均里程）
    必须能由它们精确复算，否则会把合法聚合误报为「无法由证据复算」。
    """
    values: List[float] = []

    def _add(v: Any) -> None:
        number = _as_number(v)
        if number is not None:
            values.append(round(number, 6))

    for ev in store.list_evidences():
        rows = ev.rows
        # 1) 原始行值
        for row in rows:
            for value in row.values():
                _add(value)

        # 2) 确定性统计值（与 _build_summary 中 Writer 看到的字段统计同源）
        columns = list(dict.fromkeys(str(k) for row in rows for k in row.keys()))[:50]
        numeric_cols: List[str] = []
        categorical_cols: List[str] = []
        for column in columns:
            numbers = [_as_number(row.get(column)) for row in rows]
            numbers = [n for n in numbers if n is not None]
            if numbers:
                numeric_cols.append(column)
                _add(min(numbers))
                _add(max(numbers))
                _add(sum(numbers))
                _add(sum(numbers) / len(numbers))
                _add(len(numbers))
            else:
                counts: Dict[str, int] = {}
                for row in rows:
                    raw = row.get(column)
                    if raw not in (None, ""):
                        label = str(raw)[:60]
                        counts[label] = counts.get(label, 0) + 1
                for count in counts.values():
                    _add(float(count))
                if len(counts) <= 100:
                    categorical_cols.append(column)

        # 3) 分组聚合值（与 legacy _grouped_aggregates 同源），可复算分组图表
        for cat_col in categorical_cols:
            for num_col in numeric_cols:
                groups: Dict[str, List[float]] = {}
                for row in rows:
                    raw_group = row.get(cat_col)
                    if raw_group in (None, ""):
                        continue
                    value = _as_number(row.get(num_col))
                    if value is None:
                        continue
                    groups.setdefault(str(raw_group)[:60], []).append(value)
                for group_values in groups.values():
                    _add(float(len(group_values)))
                    _add(sum(group_values))
                    _add(sum(group_values) / len(group_values))
    return values


def check_chart_value_evidence(chart: Dict[str, Any], evidence_numbers: List[float]) -> Optional[str]:
    """检查 chart 中所有数值是否能在 evidence 集合中找到（容差 1% / 0.5）。

    Returns: 失败原因字符串（None 表示通过）
    """
    if not isinstance(chart, dict):
        return None
    option = chart.get("option")
    if not isinstance(option, dict):
        return None

    output_values = _extract_numbers(option.get("series"))
    if not output_values:
        return "series 中无数值"

    if not evidence_numbers:
        return "证据集合为空，无法验证数值"

    mismatches: List[str] = []
    for value in output_values:
        if not any(
            math.isclose(value, candidate, rel_tol=0.01, abs_tol=0.5)
            for candidate in evidence_numbers
        ):
            closest = min(evidence_numbers, key=lambda x: abs(x - value), default=None)
            mismatches.append(f"{value}→最近证据{closest}")

    if mismatches:
        return f"数值无法由证据复算（前 3 个：{';'.join(mismatches[:3])}）"
    return None


# ──────────────────────────────────────────────────────────────────
# 总体校验
# ──────────────────────────────────────────────────────────────────

def verify_charts(
    charts: List[Dict[str, Any]],
    store: EvidenceStore,
    min_charts: int = 2,
) -> Dict[str, Any]:
    """对 chart 列表做完整校验。

    Returns:
        {
          "passed": bool,
          "failures": [{"chartId": ..., "stage": "type_fit|value_evidence", "reason": ...}],
          "summary": "...",
        }
    """
    failures: List[Dict[str, Any]] = []

    if len(charts) < min_charts:
        failures.append({
            "chartId": "",
            "stage": "count",
            "reason": f"图表数量 {len(charts)} < 最少要求 {min_charts}",
        })

    evidence_numbers = _evidence_all_numbers(store)

    for chart in charts:
        chart_id = str(chart.get("chartId") or "")

        # 1) 类型-数据适配
        reason = check_chart_type_data_fit(chart)
        if reason:
            failures.append({"chartId": chart_id, "stage": "type_fit", "reason": reason})
            continue  # 类型适配失败，跳过数值校验

        # 2) 数值证据校验
        reason = check_chart_value_evidence(chart, evidence_numbers)
        if reason:
            failures.append({"chartId": chart_id, "stage": "value_evidence", "reason": reason})

    passed = not failures
    return {
        "passed": passed,
        "failures": failures,
        "summary": (
            "全部通过" if passed
            else f"{len(failures)} 项失败：" + "; ".join(
                f"{f['chartId']}/{f['stage']}:{f['reason'][:50]}" for f in failures[:3]
            )
        ),
    }


def verify_narrative(
    narrative: Optional[Dict[str, Any]],
    store: EvidenceStore,
) -> Dict[str, Any]:
    """校验 narrative 引用的 chartId 是否全部命中。

    narrative 为 None（尚未生成，如 WRITE 阶段）时跳过校验、不判失败；
    narrative 引用校验应在 NARRATIVE 阶段完成后单独执行。

    Returns:
        {"passed": bool, "missing_chart_ids": [...], "summary": "..."}
    """
    if narrative is None:
        return {
            "passed": True,
            "missing_chart_ids": [],
            "summary": "narrative 校验跳过（尚未生成）",
        }

    valid_chart_ids = {m.chart_id for m in store.list_chart_metadata()}
    explanations = narrative.get("explanations") if isinstance(narrative, dict) else None
    if not isinstance(explanations, list):
        explanations = []

    referenced_ids = set()
    invalid_refs = []
    for item in explanations:
        if not isinstance(item, dict):
            continue
        chart_id = str(item.get("chartId") or "")
        if not chart_id:
            continue
        referenced_ids.add(chart_id)
        if chart_id not in valid_chart_ids:
            invalid_refs.append(chart_id)

    # narrative 至少引用 1 个 chart
    if not referenced_ids and valid_chart_ids:
        return {
            "passed": False,
            "missing_chart_ids": [],
            "summary": "narrative 未引用任何图表（explanations 为空）",
        }

    if invalid_refs:
        return {
            "passed": False,
            "missing_chart_ids": invalid_refs,
            "summary": f"narrative 引用了不存在的 chartId: {invalid_refs[:3]}",
        }

    return {"passed": True, "missing_chart_ids": [], "summary": "narrative 引用校验通过"}


def verify_all(
    charts: List[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
    store: EvidenceStore,
    min_charts: int = 2,
) -> Dict[str, Any]:
    """全量校验入口（规则通道）。

    narrative 可为 None：WRITE 阶段尚未生成 narrative，此时只校验 charts，
    narrative 校验待 NARRATIVE 阶段后单独执行。
    """
    chart_result = verify_charts(charts, store, min_charts=min_charts)
    narrative_result = verify_narrative(narrative, store)

    passed = chart_result["passed"] and narrative_result["passed"]
    return {
        "passed": passed,
        "chart_result": chart_result,
        "narrative_result": narrative_result,
        "summary": f"charts: {chart_result['summary']} | narrative: {narrative_result['summary']}",
    }


__all__ = [
    "check_chart_type_data_fit",
    "check_chart_value_evidence",
    "verify_charts",
    "verify_narrative",
    "verify_all",
]
