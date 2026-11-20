"""指标结果确定性数值校验。

本模块在「SQL 执行」之后、「数据充分性评估」之前，对查询结果做一次
不依赖大模型的数值语义校验，专门拦截"口径错误但语法/执行都成功"的结果：

  1. 比率类指标结果超出 0~100（例如命中率 150%、发现率 220%）
  2. 比率类指标结果为负值或空值（通常意味着分母为 0 或字段缺失）
  3. 比率类指标引用了不同粒度的分子/分母（通过越界值间接暴露）

同时从结果附注中提取样本量信息，对样本过少的指标给出低置信度提示
（只提示、不剔除），避免"3 条记录得出 100%"这类结论被当作稳定结论。

设计原则：
  - 纯 Python 规则，零 LLM 调用、零外部 IO，结果可解释、可测试
  - 只做确定性判断，不改写指标定义，也不猜测业务口径
  - 兼容两种结果形态：
      * 长表：一行一个指标（指标名列 + 指标值列），如 indicator / indicator_value
      * 宽表：一行多个指标（列名即指标名）
"""
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from .sufficiency import _normalize_name

# ── 比率类指标的上限（百分比口径）──
PERCENT_UPPER_LIMIT = 100.0
# ── 比率的浮点容差，避免 100.0000001 被误判 ──
_EPSILON = 1e-6
# ── 样本量下限：低于该值只给低置信度提示 ──
MIN_SAMPLE_SIZE = 3

# 长表形态的列名候选（归一化后比较，见 _normalize_name）
_LABEL_COLUMN_ALIASES = {
    "indicator", "indicatorname", "indicatortitle", "metric", "metricname",
    "指标", "指标名", "指标名称", "指标项",
}
_VALUE_COLUMN_ALIASES = {
    "indicatorvalue", "metricvalue", "value", "metricresult", "result",
    "指标值", "指标结果", "结果值", "数值",
}

# 有界比率关键词：这类指标的结果必须落在 0~100（百分比口径）
_BOUNDED_RATIO_PATTERN = re.compile(r"(率|占比|百分比|比例|完成度)")
# 英文列名/别名中的比率信号（SQL 生成常用 xxx_rate / xxx_pct 作为别名）
_EN_BOUNDED_RATIO_PATTERN = re.compile(
    r"(rate|ratio|percent|pct|share|completion)", re.IGNORECASE)

# 样本量提示：从"命中记录数:3，打击次数:2"这类附注中提取数字
_SAMPLE_HINT_PATTERN = re.compile(
    r"(样本数|样本量|记录数|数据量|条数|批次数|架次数|阵地数|目标数|单元数|任务数|次数)"
    r"\s*[:：=]?\s*(\d+)"
)

# 比率空值判定：值为空通常表示分母为 0（SQL 里常见 NULLIF(...) 写法）
_EMPTY_VALUES = (None, "", "null", "NULL", "None", "nan", "NaN")


def _strip_unit(label: str) -> str:
    """去掉指标标签中的单位/括号说明，便于与指标定义匹配。

    Args:
        label: 结果中的指标标签，如 "命中率(%)"、"首次发现距离均值(km)"

    Returns:
        去掉括号内容后的标签
    """
    return re.sub(r"[（(][^）)]*[）)]", "", label or "").strip()


def _to_number(value: Any) -> Optional[float]:
    """把结果值安全转换为浮点数。

    Args:
        value: 原始结果值（可能是 Decimal / int / float / 字符串）

    Returns:
        float 数值；无法解析、NaN、Inf 时返回 None
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif value in _EMPTY_VALUES:
        return None
    else:
        try:
            num = float(str(value).replace(",", "").replace("%", "").strip())
        except (TypeError, ValueError):
            return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _is_bounded_ratio(indicator: Optional[dict], label: str) -> bool:
    """判断指标是否为有界比率（结果应在 0~100）。

    仅对名称或公式明确表达"率/占比/百分比/比例/完成度"的指标生效。
    "平均毁伤数量""弹药消耗比"等不受 100 约束的指标不会被误判。

    Args:
        indicator: 指标定义（可为 None，此时仅依据标签判断）
        label:     结果中的指标标签

    Returns:
        True 表示应按 0~100 校验
    """
    name = (indicator or {}).get("name", "") or ""
    formula = (indicator or {}).get("formula", "") or ""
    text = f"{name} {label}"
    if _BOUNDED_RATIO_PATTERN.search(text):
        return True
    # 英文别名（如 hit_rate_pct、target_avg_discovery_rate_pct）同样按比率校验
    if _EN_BOUNDED_RATIO_PATTERN.search(label):
        return True
    return "100%" in formula or bool(re.search(r"[*×]\s*100", formula))


def _match_indicator(label: str, indicators: List[dict]) -> Optional[dict]:
    """把结果标签匹配到指标定义。

    匹配顺序：归一化精确匹配 → 双向包含匹配（长度 ≥ 3）。

    Args:
        label:      结果中的指标标签
        indicators: 指标定义列表

    Returns:
        匹配到的指标定义；未命中返回 None
    """
    norm = _normalize_name(_strip_unit(label))
    if not norm:
        return None
    for ind in indicators or []:
        if _normalize_name(ind.get("name", "")) == norm:
            return ind
    for ind in indicators or []:
        name_norm = _normalize_name(ind.get("name", ""))
        if len(name_norm) >= 3 and (name_norm in norm or norm in name_norm):
            return ind
    return None


def _find_long_columns(rows: List[dict]) -> Tuple[Optional[str], Optional[str]]:
    """识别长表形态的「指标名」列与「指标值」列。

    Args:
        rows: 查询结果行

    Returns:
        (标签列名, 数值列名)；无法识别时返回 (None, None)
    """
    if not rows or not isinstance(rows[0], dict):
        return None, None
    keys = list(rows[0].keys())
    label_col = value_col = None
    for key in keys:
        norm = _normalize_name(str(key))
        if label_col is None and norm in _LABEL_COLUMN_ALIASES:
            label_col = key
        if value_col is None and norm in _VALUE_COLUMN_ALIASES:
            value_col = key
    if label_col and value_col and label_col != value_col:
        return label_col, value_col
    return None, None


def _collect_sample_warnings(row: dict, indicator_name: str) -> List[dict]:
    """从结果行的附注文本中提取样本量，低于阈值时生成低置信度提示。

    Args:
        row:            结果行
        indicator_name: 当前指标名

    Returns:
        提示列表，每个元素包含 indicator / reason / sample_size
    """
    warnings = []
    seen_sizes = set()
    for value in row.values():
        if not isinstance(value, str):
            continue
        for match in _SAMPLE_HINT_PATTERN.finditer(value):
            size = int(match.group(2))
            if size in seen_sizes:
                continue
            seen_sizes.add(size)
            if size < MIN_SAMPLE_SIZE:
                warnings.append({
                    "indicator": indicator_name,
                    "kind": "sample_too_small",
                    "sample_size": size,
                    "reason": f"样本量仅 {size}（低于 {MIN_SAMPLE_SIZE}），结论只能作低置信度参考",
                })
    return warnings


def _check_ratio(indicator: Optional[dict], label: str, value: Any,
                 row_index: int, column: str) -> Optional[dict]:
    """校验单个比率结果是否落在合理区间。

    Args:
        indicator: 指标定义（可为 None）
        label:     指标标签
        value:     结果值
        row_index: 行号（便于定位）
        column:    结果列名

    Returns:
        违规描述字典；无违规返回 None
    """
    if not _is_bounded_ratio(indicator, label):
        return None

    num = _to_number(value)
    name = (indicator or {}).get("name") or _strip_unit(label) or column
    if num is None:
        return {
            "indicator": name, "kind": "ratio_missing", "value": value,
            "row_index": row_index, "column": column,
            "reason": "比率结果为空，通常表示分母为 0 或所需字段缺失，无法计算",
        }
    if num < -_EPSILON:
        return {
            "indicator": name, "kind": "ratio_negative", "value": num,
            "row_index": row_index, "column": column,
            "reason": f"比率结果为负值 {num:g}，不符合业务含义",
        }
    if num > PERCENT_UPPER_LIMIT + _EPSILON:
        return {
            "indicator": name, "kind": "ratio_over_100", "value": num,
            "row_index": row_index, "column": column,
            "reason": f"比率结果 {num:g}% 超过理论上限 {PERCENT_UPPER_LIMIT:g}%，疑似分子/分母口径不一致",
        }
    return None


def _build_retry_feedback(violations: List[dict]) -> str:
    """构造反馈给 SQL 重写的大模型提示。

    Args:
        violations: 违规列表

    Returns:
        中文反馈文本，作为 state.previous_error 注入重试 Prompt
    """
    lines = ["上一次 SQL 执行成功，但数值校验未通过，以下指标结果超出合理范围："]
    for item in violations[:10]:
        lines.append(f"- {item['indicator']} = {item['value']}（{item['reason']}）")
    lines.append(
        "请重新检查每个比率的分子与分母：两者必须来自同一统计粒度（事件级/目标级/汇总级）"
        "且指向同一实体，分子口径不得大于分母；百分比结果必须落在 0~100。"
        "禁止把汇总表的累计计数与明细表的单次事件混用。请重新生成 SQL。"
    )
    return "\n".join(lines)


def validate_result_values(raw_results: List[dict],
                           indicators: List[dict]) -> Dict[str, Any]:
    """对指标查询结果执行确定性数值校验。

    长表形态按「指标名→指标值」逐行校验；宽表形态按列名匹配指标后逐列校验。
    校验不通过的行/单元格会从 ``valid_rows`` 中剔除或置空，供下游分析模型使用；
    原始违规信息保留在返回值中，用于步骤展示与 SQL 重写反馈。

    Args:
        raw_results: SQL 执行返回的行列表
        indicators:  指标定义列表（含 name / formula）

    Returns:
        {
            "has_violations": bool,
            "violations": [...],
            "warnings": [...],
            "invalid_indicators": [指标名],
            "valid_rows": [...],
            "summary": str,
            "retry_feedback": str,
            "checked_indicators": int,
        }
    """
    rows = raw_results if isinstance(raw_results, list) else []
    violations: List[dict] = []
    warnings: List[dict] = []
    invalid_names: List[str] = []

    label_col, value_col = _find_long_columns(rows)
    checked_columns = 0
    validated_count = 0

    if label_col and value_col:
        validated_count = len(rows)
        # ── 长表形态：逐行校验，违规行直接剔除 ──
        valid_rows = []
        for idx, row in enumerate(rows):
            label = str(row.get(label_col, "") or "")
            indicator = _match_indicator(label, indicators)
            name = (indicator or {}).get("name") or _strip_unit(label)
            violation = _check_ratio(indicator, label, row.get(value_col),
                                     idx, value_col)
            if violation:
                violations.append(violation)
                if name not in invalid_names:
                    invalid_names.append(name)
                continue
            if name:
                warnings.extend(_collect_sample_warnings(row, name))
            valid_rows.append(row)
    else:
        # ── 宽表形态：按列名匹配指标，违规单元格置空 ──
        valid_rows = [dict(r) if isinstance(r, dict) else r for r in rows]
        if rows and isinstance(rows[0], dict):
            for column in list(rows[0].keys()):
                indicator = _match_indicator(str(column), indicators)
                if not _is_bounded_ratio(indicator, str(column)):
                    continue
                checked_columns += 1
                name = (indicator or {}).get("name") or _strip_unit(str(column))
                for idx, row in enumerate(rows):
                    violation = _check_ratio(indicator, str(column),
                                             row.get(column), idx, str(column))
                    if not violation:
                        continue
                    violations.append(violation)
                    if name not in invalid_names:
                        invalid_names.append(name)
                    valid_rows[idx][column] = None
                for row in rows:
                    warnings.extend(_collect_sample_warnings(row, name))
        validated_count = checked_columns

    # 提示去重（同一指标同一提示只保留一条）
    deduped_warnings, seen = [], set()
    for warn in warnings:
        key = (warn.get("indicator"), warn.get("reason"))
        if key not in seen:
            seen.add(key)
            deduped_warnings.append(warn)

    checked = len(invalid_names) + checked_columns
    checked_found = bool(label_col and value_col) or checked_columns > 0
    if violations:
        summary = f"数值校验未通过：{len(violations)} 项越界/缺失（{('、'.join(invalid_names))[:80]}）"
    elif deduped_warnings:
        summary = f"数值校验通过，但 {len(deduped_warnings)} 项指标样本量不足"
    elif checked_found:
        summary = "数值校验通过"
    else:
        summary = "未识别到比率结果列，跳过数值校验"

    return {
        "has_violations": bool(violations),
        "violations": violations,
        "warnings": deduped_warnings,
        "invalid_indicators": invalid_names,
        "valid_rows": valid_rows,
        "summary": summary,
        "retry_feedback": _build_retry_feedback(violations) if violations else "",
        "checked_indicators": checked,
        "validated_count": validated_count,
    }
