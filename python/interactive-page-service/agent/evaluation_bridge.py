"""评估分析产物 → 态势页面数据包/规划的桥接层。

评估分析的 ``result`` 已经是「取数 + 统计 + 结论」的最终事实源，本模块把它
转换成 interactive-page-service 现有的 ``dataBundle + plan`` 契约，从而跳过
Planner（规划）与 Researcher（重新查库），只复用 PageWriter 的页面写作能力。

设计要点：
1. 纯函数、无网络调用，便于单测；
2. 行数据复用 researcher 的脱敏/截断逻辑，保证与既有页面的数据治理一致；
3. 生成确定性的 sections（kpi/chart/map/table/text），不额外调用 LLM；
4. 只新增 ``plan.origin`` 溯源字段，不改动 Guard / PageWriter / 模板兜底契约。
"""
import datetime as dt
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import config
from agent import researcher
from agent import bundle_meta
from models import EvaluationArtifacts

logger = logging.getLogger("ipage-service")

# 单页最多展示的图表区块数量（避免评估步骤过多导致首屏拥挤）
# 有地图时地图占首屏，图表最多 4 张；无地图时放宽到 8 张，容纳多轮评估产物
MAX_CHART_SECTIONS_WITH_MAP = 4
MAX_CHART_SECTIONS_NO_MAP = 8

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]")
# 多轮合并产物的轮次前缀（由前端 buildMultiRoundPayload 统一添加）
_ROUND_PREFIX_RE = re.compile(r"^r(\d+)_")


def _generated_at() -> str:
    """生成时间（与既有数据包字段格式一致）。"""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_id(raw: str, fallback: str, seen: set) -> str:
    """清洗产物 id：只保留安全字符，并保证同一页面内不重复。"""
    base = _SAFE_ID_RE.sub("", str(raw or ""))[:64] or fallback
    candidate = base
    seq = 2
    while candidate in seen:
        candidate = f"{base}_{seq}"
        seq += 1
    seen.add(candidate)
    return candidate


def _to_number(value: Any) -> Optional[float]:
    """把单元格值解析为数字；失败返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _normalize_columns(columns: List[str], rows: List[Dict[str, Any]]) -> List[str]:
    """列名缺失时从首行键推导，并统一为字符串。"""
    if columns:
        return [str(c) for c in columns if str(c)]
    if rows and isinstance(rows[0], dict):
        return [str(k) for k in rows[0].keys()]
    return []


def _numeric_columns(columns: List[str], rows: List[Dict[str, Any]]) -> List[str]:
    """找出至少有一个数值取值的列。"""
    result = []
    for column in columns:
        if any(_to_number(row.get(column)) is not None for row in rows[:50]):
            result.append(column)
    return result


def _convert_geo(item) -> Tuple[str, Dict[str, Any], List[str]]:
    """把前端归一化的地图标注转换为 page-kit 消费的 geoFeatures。

    返回 (kind, geoFeatures, warnings)：
    kind 取值 tracks/circles/points/none，与 researcher 的 geo.kind 语义一致。
    """
    raw = item.geo or {}
    warnings: List[str] = []

    points: List[Dict[str, Any]] = []
    for marker in raw.get("markers") or []:
        lng, lat = _to_number(marker.get("lng")), _to_number(marker.get("lat"))
        if lng is None or lat is None:
            continue
        points.append({
            "lng": lng,
            "lat": lat,
            "name": str(marker.get("name") or "")[:40],
            "kind": "other",
            "unitKind": "other",
            "props": marker.get("props") or {},
        })

    tracks: List[Dict[str, Any]] = []
    for route in raw.get("routes") or []:
        route_points = []
        for point in route.get("points") or []:
            lng, lat = _to_number(point.get("lng")), _to_number(point.get("lat"))
            if lng is None or lat is None:
                continue
            route_points.append({"lng": lng, "lat": lat})
        if len(route_points) >= 2:
            tracks.append({
                "id": str(route.get("name") or ""),
                "name": str(route.get("name") or "")[:40],
                "points": route_points,
            })

    circles: List[Dict[str, Any]] = []
    for area in raw.get("areas") or []:
        lng, lat = _to_number(area.get("lng")), _to_number(area.get("lat"))
        radius = _to_number(area.get("radiusKm"))
        if lng is None or lat is None or radius is None:
            continue
        circles.append({
            "lng": lng,
            "lat": lat,
            "radiusKm": radius,
            "name": str(area.get("name") or "")[:40],
            "props": area.get("props") or {},
        })

    if not points and not tracks and not circles:
        return "none", {"tracks": [], "points": [], "circles": [], "units": []}, warnings

    if tracks:
        kind = "tracks"
    elif circles:
        kind = "circles"
    else:
        kind = "points"
    features = {"tracks": tracks, "points": points, "circles": circles, "units": points}
    return kind, features, warnings


def _build_entry(item, safe_id: str) -> Tuple[Dict[str, Any], List[str]]:
    """单条产物 → 数据包条目（含脱敏、截断、地理整形）。"""
    warnings: List[str] = []
    mode = "aggregate" if str(item.mode or "") == "aggregate" else "detail"
    raw_rows = [row for row in (item.rows or []) if isinstance(row, dict)]
    columns = _normalize_columns(list(item.columns or []), raw_rows)
    row_cap = (
        config.IPAGE_CHART_ROW_LIMIT if mode == "aggregate"
        else config.IPAGE_DETAIL_ROW_LIMIT
    )
    truncated = bool(item.truncated)
    if len(raw_rows) > row_cap:
        raw_rows = raw_rows[:row_cap]
        truncated = True
        warnings.append(f"结果超过 {row_cap} 行，已截断")

    # 复用 researcher 的敏感列剔除与单元格清洗（全局敏感词由 config 控制）
    keep_columns = [c for c in columns if not researcher._is_sensitive(c, set())]
    rows = researcher._sanitize_rows(raw_rows, keep_columns, set()) if keep_columns else []
    if len(keep_columns) < len(columns):
        warnings.append("已按敏感列规则剔除部分字段")

    geo_kind, geo_features, geo_warnings = _convert_geo(item)
    warnings.extend(geo_warnings)

    entry = {
        "id": safe_id,
        "datasetId": "",
        "name": str(item.name or safe_id)[:160],
        "tableName": "",
        "purpose": str(item.purpose or "")[:1000],
        "mode": mode,
        "columns": keep_columns,
        "rows": rows,
        "totalRows": max(int(item.totalRows or 0), len(raw_rows)),
        "truncated": truncated,
        "geo": {"kind": geo_kind},
        "geoFeatures": geo_features,
        "summary": researcher.build_summary(keep_columns, rows) if rows else "（无数据）",
        "warnings": warnings,
    }
    return entry, warnings


def _is_chartable(entry: Dict[str, Any],
                  chart_hint: Optional[Dict[str, Any]] = None) -> bool:
    """判断数据条目能否出图表：有图表建议或同时存在数值列与类目列。"""
    if chart_hint and chart_hint.get("xAxis") and chart_hint.get("yAxis"):
        return True
    columns = entry.get("columns") or []
    rows = entry.get("rows") or []
    numeric = _numeric_columns(columns, rows)
    return bool(numeric) and len(columns) >= 2


def _has_geo(entry: Dict[str, Any]) -> bool:
    """条目是否包含可渲染的地理特征。"""
    return str((entry.get("geo") or {}).get("kind") or "none") != "none"


def _append_section(sections: List[Dict[str, Any]], kind: str, title: str, ref: str = "") -> None:
    """追加区块（id 自增，保证唯一）。"""
    sections.append({
        "id": f"s{len(sections) + 1}",
        "kind": kind,
        "title": title[:60],
        "ref": ref,
    })


def _round_key(entry: Dict[str, Any]) -> int:
    """产物所属轮次：多轮合并时前端会给 id 加 r{N}_ 前缀；单轮产物统一归为第 0 组。"""
    matched = _ROUND_PREFIX_RE.match(str(entry.get("id") or ""))
    return int(matched.group(1)) if matched else 0


def _pick_chart_entries(candidates: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    """在图表配额内按轮次轮流选取，保证多轮产物都能出现在首屏图表区。

    同一轮内保持原始顺序；只有一轮时结果与「按顺序取前 cap 条」完全一致。
    """
    if cap <= 0:
        return []
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    round_order: List[int] = []
    for entry in candidates:
        key = _round_key(entry)
        if key not in buckets:
            buckets[key] = []
            round_order.append(key)
        buckets[key].append(entry)

    picked: List[Dict[str, Any]] = []
    while len(picked) < cap:
        progressed = False
        for key in round_order:
            bucket = buckets[key]
            if not bucket:
                continue
            picked.append(bucket.pop(0))
            progressed = True
            if len(picked) >= cap:
                break
        if not progressed:
            break
    return picked


def _build_plan(
    artifacts: EvaluationArtifacts,
    entries: List[Dict[str, Any]],
    chart_hints: Dict[str, Dict[str, Any]],
    fallback_query: str,
) -> Dict[str, Any]:
    """确定性页面规划：kpi → chart → map → table → 结论。"""
    presentation = artifacts.presentation or {}
    want_kpi = bool(presentation.get("kpi", True))
    want_chart = bool(presentation.get("chart", True))
    want_map = bool(presentation.get("map", True))
    want_table = bool(presentation.get("table", False))

    title = (artifacts.title or "").strip()[:60]
    if not title:
        skill_name = (artifacts.skillName or "").strip()
        title = f"{skill_name} · 态势分析" if skill_name else ""
    if not title:
        title = (artifacts.question or fallback_query or "评估态势页面").strip()[:25]

    sections: List[Dict[str, Any]] = []
    aggregate_entries = [e for e in entries if e.get("mode") == "aggregate" and e.get("rows")]
    detail_entries = [e for e in entries if e.get("mode") == "detail" and e.get("rows")]
    geo_entry = next((e for e in entries if _has_geo(e)), None)
    # 有地图时地图占首屏，图表上限收紧；无地图时放宽上限
    chart_cap = (
        MAX_CHART_SECTIONS_WITH_MAP if (want_map and geo_entry)
        else MAX_CHART_SECTIONS_NO_MAP
    )
    # 图表配额按轮次轮流分配：若直接截断，多轮场景下靠后的轮次会被整轮挤掉，
    # 表现为「生成态势页面只显示第一轮」。轮次信息来自前端加在产物 id 上的 r{N}_ 前缀。
    chart_candidates = [
        e for e in aggregate_entries if _is_chartable(e, chart_hints.get(e["id"]))
    ]
    chart_entries = _pick_chart_entries(chart_candidates, chart_cap)

    # KPI：优先引用有数值列的数据条目
    if want_kpi:
        kpi_entry = next(
            (e for e in entries if e.get("rows") and _numeric_columns(e["columns"], e["rows"])),
            None,
        )
        if kpi_entry:
            _append_section(sections, "kpi", "核心指标", kpi_entry["id"])

    if want_chart:
        for entry in chart_entries:
            hint = chart_hints.get(entry["id"]) or {}
            _append_section(
                sections, "chart",
                str(hint.get("chartTitle") or entry.get("name") or "数据图表"),
                entry["id"],
            )

    if want_map and geo_entry:
        _append_section(sections, "map", "空间分布", geo_entry["id"])

    if want_table:
        table_entry = detail_entries[0] if detail_entries else (entries[0] if entries else None)
        if table_entry:
            _append_section(sections, "table", "评估数据明细", table_entry["id"])

    # 未被任何区块引用的产物：补一张数据表，避免用户勾选的数据被静默丢弃。
    # 除明细产物外，超出图表配额的聚合产物同样要补表：多轮合并时若只按顺序截断，
    # 靠后轮次的聚合结果会既不上图也不上表，页面上看起来「只有第一轮」。
    referenced = {s.get("ref") for s in sections if s.get("ref")}
    for entry in entries:
        if entry["id"] in referenced:
            continue
        suffix = "（明细）" if entry.get("mode") == "detail" else "（数据表）"
        _append_section(sections, "table",
                        f"{entry.get('name') or '评估数据'}{suffix}", entry["id"])
        referenced.add(entry["id"])

    if (artifacts.conclusion or "").strip():
        _append_section(sections, "text", "评估结论")

    # 兜底：至少保留一个数据可视化区块（Guard 要求页面调用 SitChart/SitMap/SitTable）。
    # 明细数据没有图表时自动补一张明细表，避免页面只剩 KPI 与结论。
    if not any(s.get("kind") in ("chart", "map", "table") for s in sections):
        if chart_entries:
            _append_section(sections, "chart", "评估数据", chart_entries[0]["id"])
        elif detail_entries:
            _append_section(sections, "table", "评估数据明细", detail_entries[0]["id"])
        elif entries:
            _append_section(sections, "chart", "评估数据", entries[0]["id"])

    return {
        "title": title,
        "intent": "data_page",
        "subQuestions": [],
        "sections": sections,
        "interactions": [],
        "origin": {
            "type": "evaluation",
            "sessionId": artifacts.sourceSessionId or "",
            "skillId": artifacts.skillId or "",
            "skillName": artifacts.skillName or "",
            "artifactIds": [e["id"] for e in entries],
        },
    }


def build_bundle_and_plan(
    artifacts: EvaluationArtifacts,
    fallback_query: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """评估产物 → (bundle, plan, warnings)。

    Args:
        artifacts: 前端归一化后的评估产物（只含用户勾选项）
        fallback_query: 请求中的问题，作为 bundle.question 的兜底

    Returns:
        (数据包, 页面规划, 全局告警列表)

    Raises:
        ValueError: 没有任何可展示的数据行时抛出中文原因
    """
    seen_ids: set = set()
    entries: List[Dict[str, Any]] = []
    chart_hints: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    for index, item in enumerate(artifacts.items or [], start=1):
        if not item.rows:
            warnings.append(f"产物「{item.name or item.artifactId}」无数据行，已跳过")
            continue
        safe_id = _safe_id(item.artifactId, f"q{index}", seen_ids)
        entry, item_warnings = _build_entry(item, safe_id)
        if not entry["rows"]:
            warnings.append(f"产物「{entry['name']}」清洗后无可用数据，已跳过")
            continue
        entries.append(entry)
        warnings.extend(item_warnings)
        if isinstance(item.chartHint, dict):
            chart_hints[safe_id] = item.chartHint

    if not entries:
        raise ValueError("所选评估产物没有可展示的数据")

    question = ((artifacts.question or "").strip() or (fallback_query or "").strip()
                or "评估分析结果")
    bundle = {
        "question": question,
        "generatedAt": _generated_at(),
        "dataSourceId": artifacts.dataSourceId or "",
        "datasets": entries,
    }
    # 结论随数据包下发，供 PageWriter 写作与模板兜底使用；
    # 普通页面没有该字段，_bundle_view 仅在非空时附加，避免影响既有路径。
    conclusion = (artifacts.conclusion or "").strip()
    if conclusion:
        bundle["conclusion"] = conclusion
    # 补齐 mapAvailable：页面写作契约要求运行时数据包带该字段，缺省会让地图区块静默不渲染
    bundle_meta.apply_bundle_meta(bundle)
    plan = _build_plan(artifacts, entries, chart_hints, fallback_query)
    return bundle, plan, warnings
