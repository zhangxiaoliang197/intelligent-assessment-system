"""Temporal intent parsing and strict historical evidence constraints.

Time retrospective requests must never silently fall back to current/all-time
data.  This module converts UI ranges or natural-language time expressions into
one normalized contract and applies that contract to Planner sub-questions.
"""
from __future__ import annotations

import calendar
import copy
import datetime as dt
import re
from typing import Any, Dict, Iterable, Optional, Tuple


_TEMPORAL_INTENT = re.compile(
    r"时间回溯|历史态势|历史回溯|回溯到|回到|截至|截止|当时|彼时|那时|"
    r"态势快照|历史快照|演化|变化趋势|过去\s*\d+\s*(?:小时|天|日|月|年)|"
    r"近\s*\d+\s*(?:小时|天|日|月|年)|\d+\s*(?:小时|天|日|月|年)前|"
    r"昨天|前天|上周|上月|去年",
    re.IGNORECASE,
)
_AS_OF_INTENT = re.compile(r"回溯到|回到|截至|截止|当时|彼时|那时|时点|快照")
_TIME_FIELD = re.compile(
    r"time|date|timestamp|datetime|created|updated|recorded|detected|warning|issued|"
    r"时间|日期|时刻|时点|发生|记录|发现|告警|更新时间",
    re.IGNORECASE,
)


def _local_now(now: Optional[dt.datetime] = None) -> dt.datetime:
    value = now or dt.datetime.now().astimezone()
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value


def _day_bounds(day: dt.date, tzinfo: dt.tzinfo) -> Tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time.min, tzinfo=tzinfo)
    end = dt.datetime.combine(day, dt.time.max.replace(microsecond=0), tzinfo=tzinfo)
    return start, end


def _iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_timestamp(value: Any, tzinfo: dt.tzinfo) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.time.min)
    elif isinstance(value, (int, float)):
        number = float(value)
        if abs(number) > 10_000_000_000:
            number /= 1000
        try:
            parsed = dt.datetime.fromtimestamp(number, tz=tzinfo)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if re.fullmatch(r"\d{10,13}", text):
            return _parse_timestamp(int(text), tzinfo)
        normalized = text.replace("年", "-").replace("月", "-").replace("日", "")
        try:
            parsed = dt.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tzinfo)
    return parsed.astimezone(tzinfo)


def _contract(
    mode: str,
    start: Optional[dt.datetime],
    end: dt.datetime,
    label: str,
    source: str,
) -> Dict[str, Any]:
    return {
        "active": True,
        "mode": mode,
        "start": _iso(start) if start else "",
        "end": _iso(end),
        "asOf": _iso(end) if mode == "as_of" else "",
        "label": label,
        "source": source,
        "strict": True,
        "evidenceBoundary": "仅使用所选历史时间边界内的记录，不以区间外或当前数据替代",
    }


def _from_selected_range(
    value: Any,
    tzinfo: dt.tzinfo,
) -> Optional[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    start = _parse_timestamp(value[0], tzinfo)
    end = _parse_timestamp(value[1], tzinfo)
    if not start or not end:
        return None
    if start > end:
        start, end = end, start
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end.replace(hour=23, minute=59, second=59, microsecond=0)
    label = f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}"
    return _contract("range", start, end, label, "selected-range")


def resolve_temporal_context(
    query: str,
    context: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Resolve UI selection or Chinese time expression into a strict contract."""
    runtime = dict(context or {})
    current = _local_now(now)
    tzinfo = current.tzinfo or dt.timezone.utc

    selected = _from_selected_range(runtime.get("selectedTimeRange"), tzinfo)
    if selected:
        return selected

    text = re.sub(r"\s+", " ", str(query or "")).strip()
    has_explicit_boundary = bool(re.search(r"20\d{2}[年\-/\.]\d{1,2}", text))
    if not _TEMPORAL_INTENT.search(text) and not has_explicit_boundary:
        return {"active": False, "mode": "current", "strict": False, "label": "当前态势"}

    # Precise timestamps: YYYY-MM-DD HH:mm[:ss]. A single timestamp is an as-of snapshot.
    timestamp_matches = re.findall(
        r"(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})日?[ T]\s*"
        r"(\d{1,2})[:：](\d{2})(?:[:：](\d{2}))?",
        text,
    )
    parsed_timestamps = []
    for year, month, day, hour, minute, second in timestamp_matches[:2]:
        try:
            parsed_timestamps.append(dt.datetime(
                int(year), int(month), int(day), int(hour), int(minute), int(second or 0),
                tzinfo=tzinfo,
            ))
        except ValueError:
            continue
    if len(parsed_timestamps) >= 2:
        start, end = min(parsed_timestamps), max(parsed_timestamps)
        return _contract("range", start, end, f"{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}", "query")
    if len(parsed_timestamps) == 1:
        point = parsed_timestamps[0]
        return _contract("as_of", None, point, f"截至 {point:%Y-%m-%d %H:%M} 的历史快照", "query")

    # Full date expressions: YYYY-MM-DD / YYYY年M月D日.
    date_matches = re.findall(r"(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})日?", text)
    parsed_dates = []
    for year, month, day in date_matches[:2]:
        try:
            parsed_dates.append(dt.date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if len(parsed_dates) >= 2:
        start, _ = _day_bounds(min(parsed_dates), tzinfo)
        _, end = _day_bounds(max(parsed_dates), tzinfo)
        return _contract("range", start, end, f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}", "query")
    if len(parsed_dates) == 1:
        start, end = _day_bounds(parsed_dates[0], tzinfo)
        if _AS_OF_INTENT.search(text):
            return _contract("as_of", None, end, f"截至 {end:%Y-%m-%d} 的历史快照", "query")
        return _contract("range", start, end, f"{start:%Y-%m-%d} 当日", "query")

    # Whole month: 2026年8月 / 2026-08月.
    month_match = re.search(r"(20\d{2})[年\-/\.](\d{1,2})月?(?!\d)", text)
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if 1 <= month <= 12:
            start, _ = _day_bounds(dt.date(year, month, 1), tzinfo)
            last_day = calendar.monthrange(year, month)[1]
            _, end = _day_bounds(dt.date(year, month, last_day), tzinfo)
            if _AS_OF_INTENT.search(text):
                return _contract("as_of", None, end, f"截至 {year:04d}-{month:02d} 月末的历史快照", "query")
            return _contract("range", start, end, f"{year:04d}-{month:02d} 全月", "query")

    today = current.date()
    if "前天" in text:
        target = today - dt.timedelta(days=2)
        start, end = _day_bounds(target, tzinfo)
        return _contract("range", start, end, f"{target:%Y-%m-%d}（前天）", "query")
    if "昨天" in text:
        target = today - dt.timedelta(days=1)
        start, end = _day_bounds(target, tzinfo)
        return _contract("range", start, end, f"{target:%Y-%m-%d}（昨天）", "query")
    if "上周" in text:
        this_monday = today - dt.timedelta(days=today.weekday())
        start_day = this_monday - dt.timedelta(days=7)
        end_day = this_monday - dt.timedelta(days=1)
        start, _ = _day_bounds(start_day, tzinfo)
        _, end = _day_bounds(end_day, tzinfo)
        return _contract("range", start, end, f"上周（{start_day:%Y-%m-%d} 至 {end_day:%Y-%m-%d}）", "query")
    if "上月" in text:
        first_this_month = today.replace(day=1)
        last_previous = first_this_month - dt.timedelta(days=1)
        first_previous = last_previous.replace(day=1)
        start, _ = _day_bounds(first_previous, tzinfo)
        _, end = _day_bounds(last_previous, tzinfo)
        return _contract("range", start, end, f"上月（{first_previous:%Y-%m-%d} 至 {last_previous:%Y-%m-%d}）", "query")
    if "去年" in text:
        year = today.year - 1
        start, _ = _day_bounds(dt.date(year, 1, 1), tzinfo)
        _, end = _day_bounds(dt.date(year, 12, 31), tzinfo)
        return _contract("range", start, end, f"{year} 年", "query")

    days_ago = re.search(r"(\d{1,4})\s*天前", text)
    if days_ago:
        target = today - dt.timedelta(days=min(int(days_ago.group(1)), 3650))
        start, end = _day_bounds(target, tzinfo)
        if _AS_OF_INTENT.search(text):
            return _contract("as_of", None, end, f"截至 {target:%Y-%m-%d} 的历史快照", "query")
        return _contract("range", start, end, f"{target:%Y-%m-%d} 当日", "query")

    hours_ago = re.search(r"(\d{1,5})\s*小时前", text)
    if hours_ago:
        point = current - dt.timedelta(hours=min(int(hours_ago.group(1)), 24 * 365))
        return _contract("as_of", None, point, f"截至 {point:%Y-%m-%d %H:%M} 的历史快照", "query")

    recent_hours = re.search(r"(?:近|过去)\s*(\d{1,5})\s*小时", text)
    if recent_hours:
        hours = max(1, min(int(recent_hours.group(1)), 24 * 365))
        start = current - dt.timedelta(hours=hours)
        return _contract("range", start, current, f"近 {hours} 小时", "query")

    recent_days = re.search(r"(?:近|过去)\s*(\d{1,4})\s*天", text)
    if recent_days:
        days = max(1, min(int(recent_days.group(1)), 3650))
        start_day = today - dt.timedelta(days=days - 1)
        start, _ = _day_bounds(start_day, tzinfo)
        _, end = _day_bounds(today, tzinfo)
        return _contract("range", start, end, f"近 {days} 天（{start_day:%Y-%m-%d} 至 {today:%Y-%m-%d}）", "query")

    # Temporal intent without a parseable boundary: make it explicit instead of
    # pretending to know a date. The caller can request a concrete range.
    return {
        "active": True,
        "mode": "unspecified",
        "start": "",
        "end": "",
        "asOf": "",
        "label": "待明确的历史时间范围",
        "source": "query",
        "strict": True,
        "requiresClarification": True,
        "evidenceBoundary": "尚未获得明确历史时间边界，不执行跨时段取数",
    }


def build_temporal_instruction(temporal: Dict[str, Any]) -> str:
    if not temporal.get("active"):
        return ""
    if temporal.get("requiresClarification"):
        return "时间回溯要求：用户尚未提供可解析的历史时点或区间，必须明确说明无法确定回溯边界。"
    if temporal.get("mode") == "as_of":
        return (
            f"时间回溯要求：还原 {temporal.get('label')}；所有查询只能使用时间 <= {temporal.get('end')} 的记录。"
            "存在同一实体多条记录时，应取截至该时点的最近一条作为历史快照，禁止使用该时点之后的数据。"
        )
    return (
        f"时间回溯要求：分析 {temporal.get('label')}；所有查询必须限定在"
        f" {temporal.get('start')} 至 {temporal.get('end')}。"
        "优先输出时间序列、阶段变化和关键拐点，禁止使用区间外或当前数据替代。"
    )


def _schemas(meta: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if not isinstance(meta, dict) or not meta.get("success"):
        return []
    return (meta.get("data", {}) or {}).get("schemas") or []


def _field_name(field: Dict[str, Any]) -> str:
    return str(field.get("column") or field.get("name") or field.get("fieldName") or "").strip()


def _find_time_field(dataset_id: str, meta: Dict[str, Any]) -> str:
    for schema in _schemas(meta):
        if str(schema.get("datasetId") or "").strip() != dataset_id:
            continue
        ranked = []
        for field in schema.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = _field_name(field)
            if not name:
                continue
            label = str(
                field.get("businessMeaning") or field.get("annotation")
                or field.get("comment") or ""
            )
            field_type = str(field.get("type") or field.get("dataType") or "")
            score = 0
            if re.search(r"date|time|timestamp|datetime", field_type, re.IGNORECASE):
                score += 5
            if _TIME_FIELD.search(name):
                score += 4
            if _TIME_FIELD.search(label):
                score += 3
            if score:
                ranked.append((score, name))
        if ranked:
            return sorted(ranked, key=lambda item: (-item[0], item[1]))[0][1]
    return ""


def apply_temporal_constraints(
    plan: Dict[str, Any],
    temporal: Dict[str, Any],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach exact time filters and remove datasets without temporal evidence."""
    result = copy.deepcopy(plan)
    if not temporal.get("active") or temporal.get("requiresClarification"):
        return result

    supported_refs = set()
    unsupported = []
    for sub_question in result.get("subQuestions") or []:
        dataset_id = str(sub_question.get("datasetId") or "").strip()
        field_name = _find_time_field(dataset_id, meta)
        if not field_name:
            sub_question["_temporalUnsupported"] = True
            unsupported.append(str(sub_question.get("id") or ""))
            continue
        if temporal.get("mode") == "as_of":
            boundary = {"lte": temporal.get("end")}
        else:
            boundary = {"gte": temporal.get("start"), "lte": temporal.get("end")}
        filters = dict(sub_question.get("filters") or {})
        filters[field_name] = boundary
        sub_question["filters"] = filters
        sub_question["question"] = (
            f"{str(sub_question.get('question') or '').strip()}；{build_temporal_instruction(temporal)}"
        )[:2000]
        sub_question["_temporalField"] = field_name
        supported_refs.add(str(sub_question.get("id") or ""))

    if unsupported:
        result["subQuestions"] = [
            sq for sq in result.get("subQuestions") or []
            if not sq.get("_temporalUnsupported")
        ]
        result["chartSpecs"] = [
            spec for spec in result.get("chartSpecs") or []
            if str(spec.get("subQuestionRef") or "") in supported_refs
        ]
        result["mapSpecs"] = [
            spec for spec in result.get("mapSpecs") or []
            if str(spec.get("subQuestionRef") or "") in supported_refs
        ]
    result["_temporal"] = {
        **temporal,
        "supportedSubQuestions": len(supported_refs),
        "unsupportedSubQuestionIds": unsupported,
    }
    return result


__all__ = [
    "apply_temporal_constraints",
    "build_temporal_instruction",
    "resolve_temporal_context",
]
