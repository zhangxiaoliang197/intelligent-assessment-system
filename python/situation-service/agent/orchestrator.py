"""态势生成编排器（V2 Agent 架构）。

五阶段流程：PLAN → RESEARCH → WRITE(chart+map 并行) → VERIFY → NARRATIVE → EMIT
入口 `generate` 直接调用本模块的 `real_generate_v2`。

本模块包含：
- V2 编排主体（Planner/Executor/Writer/Verifier/Narrative 串联）
- V2 复用的工具函数：profile 适配、数据降级图表/地图、坐标校验、
  ECharts/Map 安全校验、聚合统计与证据摘要

V1 的 mock_generate / real_generate / _collect_real_data / _run_llm_orchestration
已移除，不再依赖 knowledge/qa/indicator 服务（ADR-01/05）。
"""
import asyncio
import datetime as dt
import hashlib
import json
import logging
import math
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from stream.sse import SSEEvent
import config
from agent import map_builder, tools, executor, writer, verifier
from agent.evidence_store import EvidenceStore
from agent.planner import Planner
from agent.state_machine import Stage, StateMachine

logger = logging.getLogger("situation-service")


_DEFAULT_PROFILE = {
    "skillId": "",
    "skillName": "通用态势分析",
    "category": "综合态势",
    # 未选 Skill 时不约束图表/地图类型与指标，由 LLM 基于用户问题与数据集 schema 自由决策。
    "chartTypes": [],
    "mapLayerTypes": [],
    "focusMetrics": [],
    "executionPlan": [],
}


def _skill_profile(skill_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    profile = dict(_DEFAULT_PROFILE)
    if skill_context:
        for field in (
            "skillId", "skillName", "category", "chartTypes",
            "mapLayerTypes", "focusMetrics", "executionPlan", "analysisGoal",
            "workflow", "parameterBindings", "revision", "version", "contentHash",
        ):
            if skill_context.get(field):
                profile[field] = skill_context[field]
    return profile


def _restrict_profile_to_database(profile: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the selected datasource as an additional server-side catalog constraint."""
    selected = str(context.get("dataSourceId") or "").strip()
    if not selected:
        return profile
    constrained = dict(profile)
    constrained["dataSourceId"] = selected
    return constrained


def _resolve_field(rows: list, requested: str) -> Optional[str]:
    if not rows:
        return None
    fields = list(dict.fromkeys(str(key) for row in rows for key in row))
    if requested in fields:
        return requested
    lowered = requested.lower()
    return next((field for field in fields if lowered and lowered in field.lower()), None)


def _safe_id(value: Any) -> str:
    text = "".join(char if str(char).isalnum() else "_" for char in str(value or ""))
    return text.strip("_")[:40] or "source"


def _rows_from_payload(payload: Any) -> list:
    """从不同服务的响应结构中抽取供图表编排使用的记录。"""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "results", "indicators", "datasets", "items", "history"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row if isinstance(row, dict) else {"value": row} for row in value]
    for key in ("data", "session", "snapshot"):
        value = payload.get(key)
        rows = _rows_from_payload(value)
        if rows:
            return rows
        if isinstance(value, dict):
            return [value]
    return [payload] if payload else []


def _sensitive_column(name: Any, bundle: dict) -> bool:
    normalized = str(name or "").strip().lower().replace("-", "_")
    configured = set(config.SITUATION_SENSITIVE_COLUMNS)
    dataset_sensitive = {
        str(item).strip().lower()
        for item in ((bundle.get("payload") or {}).get("dataset") or {}).get("sensitiveColumns", [])
    }
    return normalized in dataset_sensitive or any(token in normalized for token in configured)


def _evidence_digest(rows: list) -> str:
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_scalar(value: Any, limit: int = 80) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:limit]


def _safe_props(value: Any) -> Optional[dict]:
    """清洗点位/圆形区域的动态业务属性（props），供前端弹窗完整展示。

    只保留可安全展示的标量字段，并对键与值做长度/控制字符约束，
    避免地图标注透传任意结构或 HTML。
    """
    if not isinstance(value, dict):
        return None
    props = {}
    for key, item in value.items():
        safe_key = _safe_text(key, 80)
        if not safe_key:
            continue
        props[safe_key] = _safe_scalar(item, 160)
    return props or None


def _grouped_aggregates(rows: list, categorical_cols: list, numeric_cols: list, top_n: int = 10) -> list:
    """按分类列分组、对数值列做 sum/avg/count 聚合（每组 top-N 组），供 LLM 证据与验证器共用。"""
    grouped = []
    for cat_col in categorical_cols:
        for num_col in numeric_cols:
            groups: Dict[str, list] = {}
            for row in rows:
                raw_group = row.get(cat_col)
                if raw_group in (None, ""):
                    continue
                value = _as_number(row.get(num_col))
                if value is None:
                    continue
                group = str(raw_group)[:60]
                groups.setdefault(group, []).append(value)
            if not groups:
                continue
            top = sorted(groups.items(), key=lambda item: -len(item[1]))[:top_n]
            grouped.append({
                "groupBy": cat_col,
                "metric": num_col,
                "groups": [
                    {"group": group, "count": len(values), "sum": round(sum(values), 6),
                     "avg": round(sum(values) / len(values), 6)}
                    for group, values in top
                ],
            })
    return grouped


def _aggregate_evidence(bundle: dict) -> dict:
    rows = _rows_from_payload(bundle["payload"])
    columns = list(dict.fromkeys(str(key) for row in rows for key in row))[:50]
    safe_columns = [column for column in columns if not _sensitive_column(column, bundle)]
    numeric_stats, category_counts = {}, {}
    for column in safe_columns:
        values = [_as_number(row.get(column)) for row in rows]
        numbers = [value for value in values if value is not None]
        if numbers:
            numeric_stats[column] = {
                "count": len(numbers), "min": min(numbers), "max": max(numbers),
                "sum": round(sum(numbers), 6), "avg": round(sum(numbers) / len(numbers), 6),
            }
            continue
        counts: Dict[str, int] = {}
        for row in rows:
            value = row.get(column)
            if value not in (None, ""):
                label = str(value)[:60]
                counts[label] = counts.get(label, 0) + 1
        if counts and len(counts) <= 100:
            category_counts[column] = dict(
                sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            )
    grouped_stats = _grouped_aggregates(
        rows,
        categorical_cols=list(category_counts.keys()),
        numeric_cols=list(numeric_stats.keys()),
    )
    samples = []
    if config.SITUATION_LLM_EVIDENCE_ROWS:
        for row in rows[:config.SITUATION_LLM_EVIDENCE_ROWS]:
            samples.append({
                column: _safe_scalar(row.get(column))
                for column in safe_columns
                if column in row
            })
    return {
        "datasetId": bundle["datasetId"],
        "source": bundle["source"],
        "summary": bundle["summary"],
        "rowCount": len(rows),
        "columns": safe_columns,
        "numericStats": numeric_stats,
        "categoryCounts": category_counts,
        "groupedStats": grouped_stats,
        "samples": samples,
        "evidenceHash": _evidence_digest(rows),
    }


def _valid_coord(value: Any, minimum: float, maximum: float) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and minimum <= number <= maximum
    except (TypeError, ValueError):
        return False


def _safe_text(value: Any, limit: int = 160) -> str:
    return re.sub(r"[<>\x00-\x1f]", "", str(value or ""))[:limit]


def _safe_point(value: Any) -> Optional[dict]:
    if not isinstance(value, dict) or not (
        _valid_coord(value.get("lng"), -180, 180)
        and _valid_coord(value.get("lat"), -90, 90)
    ):
        return None
    point = {
        "name": _safe_text(value.get("name") or "点位"),
        "lng": float(value["lng"]),
        "lat": float(value["lat"]),
        "raw": _safe_text(value.get("raw")),
    }
    # 保留后端语义配色与路线归属，前端据此做「同路线同色、不同路线不同色」
    if isinstance(value.get("routeName"), str) and value["routeName"]:
        point["routeName"] = _safe_text(value["routeName"], 80)
    color = value.get("color")
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        point["color"] = color
    if value.get("featureId"):
        point["featureId"] = _safe_id(value.get("featureId"))
    if value.get("datasetRef"):
        point["datasetRef"] = _safe_text(value.get("datasetRef"), 80)
    props = _safe_props(value.get("props"))
    if props:
        point["props"] = props
    prop_labels = _safe_props(value.get("propLabels"))
    if prop_labels:
        point["propLabels"] = prop_labels
    return point


def _coordinate_evidence(bundles: list) -> set[tuple[float, float]]:
    """从数据包中收集所有坐标证据（用于校验 LLM 产出的地图坐标是否真实存在）。"""
    evidence: set[tuple[float, float]] = set()
    for bundle in bundles:
        for row in _rows_from_payload(bundle.get("payload")):
            # 使用共享工具自动发现所有经纬度列对（支持 origin_lng/dest_lng 等前缀变体）
            pairs = map_builder.discover_coordinate_columns(list(row.keys()))
            if not pairs:
                continue
            for pair in pairs:
                lng = row.get(pair["lng"])
                lat = row.get(pair["lat"])
                if _valid_coord(lng, -180, 180) and _valid_coord(lat, -90, 90):
                    evidence.add((round(float(lng), 6), round(float(lat), 6)))
    return evidence


def _point_is_evidenced(point: dict, evidence: set[tuple[float, float]]) -> bool:
    return (round(float(point["lng"]), 6), round(float(point["lat"]), 6)) in evidence


def _verify_map_coordinates(layer: dict, bundles: list) -> dict:
    evidence = _coordinate_evidence(bundles)
    if not evidence:
        layer.update({"points": [], "routes": [], "areas": [], "circles": []})
        layer["verification"] = {"verified": True, "method": "empty-without-coordinate-evidence", "checkedCoordinates": 0}
        return layer
    points = [point for point in layer.get("points", []) if _point_is_evidenced(point, evidence)]
    routes = [route for route in layer.get("routes", []) if all(_point_is_evidenced(point, evidence) for point in route["points"])]
    areas = [area for area in layer.get("areas", []) if all(_point_is_evidenced(point, evidence) for point in area["points"])]
    circles = [circle for circle in layer.get("circles", []) if _point_is_evidenced(circle["center"], evidence)]
    checked = len(points) + sum(len(item["points"]) for item in routes + areas) + len(circles)
    layer.update({"points": points, "routes": routes, "areas": areas, "circles": circles})
    layer["verification"] = {"verified": True, "method": "coordinate-membership", "checkedCoordinates": checked}
    return layer


def _safe_path(value: Any, minimum_points: int) -> Optional[dict]:
    if not isinstance(value, dict) or not isinstance(value.get("points"), list):
        return None
    points = [point for item in value["points"][:config.SITUATION_MAP_POINT_LIMIT] if (point := _safe_point(item))]
    if len(points) < minimum_points:
        return None
    path = {
        "name": _safe_text(value.get("name") or "图形"),
        "points": points,
    }
    color = value.get("color")
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        path["color"] = color
    if value.get("featureId"):
        path["featureId"] = _safe_id(value.get("featureId"))
    if value.get("datasetRef"):
        path["datasetRef"] = _safe_text(value.get("datasetRef"), 80)
    return path


def _sanitize_map_layer(value: Any, profile: dict, context: Optional[dict] = None) -> dict:
    if not isinstance(value, dict):
        value = {}
    point_limit = config.SITUATION_MAP_POINT_LIMIT
    path_limit = config.SITUATION_MAP_PATH_LIMIT
    points = [
        point for item in value.get("points", [])[:point_limit]
        if (point := _safe_point(item))
    ] if isinstance(value.get("points"), list) else []
    routes = [
        route for item in value.get("routes", [])[:path_limit]
        if (route := _safe_path(item, 2))
    ] if isinstance(value.get("routes"), list) else []
    areas = [
        area for item in value.get("areas", [])[:path_limit]
        if (area := _safe_path(item, 3))
    ] if isinstance(value.get("areas"), list) else []
    circles = []
    for item in value.get("circles", [])[:path_limit] if isinstance(value.get("circles"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("center"), dict):
            continue
        center = _safe_point(item["center"])
        radius = _as_number(item.get("radiusKm"))
        if center and radius is not None and 0 < radius <= 5000:
            circle = {
                "name": _safe_text(item.get("name") or "圆形区域"),
                "center": {"lng": center["lng"], "lat": center["lat"]},
                "radiusKm": radius,
            }
            color = item.get("color")
            if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                circle["color"] = color
            if item.get("featureId"):
                circle["featureId"] = _safe_id(item.get("featureId"))
            if item.get("datasetRef"):
                circle["datasetRef"] = _safe_text(item.get("datasetRef"), 80)
            props = _safe_props(item.get("props"))
            if props:
                circle["props"] = props
            prop_labels = _safe_props(item.get("propLabels"))
            if prop_labels:
                circle["propLabels"] = prop_labels
            circles.append(circle)
    layer_config = value.get("layerConfig", {}) if isinstance(value.get("layerConfig"), dict) else {}
    color = str(layer_config.get("color") or "#e74c3c")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#e74c3c"
    opacity = _as_number(layer_config.get("opacity"))
    weight = _as_number(layer_config.get("weight"))
    fill_opacity = _as_number(layer_config.get("fillOpacity"))
    layer_config = {
        "name": _safe_text(layer_config.get("name") or profile["skillName"]),
        "color": color,
        "opacity": min(max(opacity if opacity is not None else 0.85, 0), 1),
        "weight": min(max(weight if weight is not None else 3, 1), 12),
        "fillOpacity": min(max(fill_opacity if fill_opacity is not None else 0.15, 0), 1),
        "visible": bool(layer_config.get("visible", True)),
    }
    layer = {
        "layerId": str(value.get("layerId") or f"skill_{profile['skillId'] or 'general'}"),
        "points": points, "routes": routes, "areas": areas, "circles": circles,
        "layerConfig": layer_config,
    }
    # 远端特性：保留 datasetRef/fieldMapping（前端据此用全量数据渲染轨迹/标点）
    if isinstance(value.get("datasetRef"), str) and value["datasetRef"]:
        layer["datasetRef"] = _safe_text(value["datasetRef"], 80)
    if isinstance(value.get("fieldMapping"), dict):
        layer["fieldMapping"] = {
            str(key)[:60]: str(item)[:60]
            for key, item in value["fieldMapping"].items()
            if isinstance(item, str)
        }
    map_radius = next((
        _as_number(value)
        for key, value in (((context or {}).get("skill") or {}).get("parameters") or {}).items()
        if "半径" in str(key)
    ), None)
    if map_radius is not None:
        layer["layerConfig"]["radiusKm"] = min(max(map_radius, 0.1), 5000)
    return layer


_FORBIDDEN_OPTION_KEYS = {"formatter", "renderItem", "graphic", "backgroundColor"}


def _safe_echarts(value: Any, depth: int = 0, budget: list = None) -> Any:
    """Limit ECharts JSON to inert data/configuration (no HTML, callbacks or external URLs)."""
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 12 or budget[0] > 5000:
        raise ValueError("图表 option 结构过大")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value[:500]
        if re.search(r"(?:https?:|data:|image:|javascript:|<[^>]+>)", text, re.I):
            raise ValueError("图表 option 包含外部资源或 HTML")
        return text
    if isinstance(value, list):
        return [_safe_echarts(item, depth + 1, budget) for item in value[:1000]]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:200]:
            safe_key = str(key)[:80]
            if safe_key in _FORBIDDEN_OPTION_KEYS:
                continue
            result[safe_key] = _safe_echarts(item, depth + 1, budget)
        return result
    raise ValueError("图表 option 包含不可序列化值")


def _numeric_values(option: dict) -> list[float]:
    values: list[float] = []
    for series in option.get("series", []) if isinstance(option.get("series"), list) else []:
        if not isinstance(series, dict):
            continue
        data = series.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            raw = item.get("value") if isinstance(item, dict) else item
            if isinstance(raw, list):
                for value in raw:
                    number = _as_number(value)
                    if number is not None:
                        values.append(round(number, 6))
            else:
                number = _as_number(raw)
                if number is not None:
                    values.append(round(number, 6))
    return values


def _bundle_numbers(bundle: dict) -> list[float]:
    values = []
    rows = _rows_from_payload(bundle.get("payload"))
    for row in rows:
        for value in row.values():
            number = _as_number(value)
            if number is not None:
                values.append(round(number, 6))
    # LLM 收到的是这些确定性统计值，也允许它们被验证器精确匹配。
    columns = list(dict.fromkeys(str(key) for row in rows for key in row))[:50]
    numeric_cols: list = []
    categorical_cols: list = []
    for column in columns:
        numbers = [number for row in rows if (number := _as_number(row.get(column))) is not None]
        if numbers:
            numeric_cols.append(column)
            values.extend(round(number, 6) for number in (
                min(numbers), max(numbers), sum(numbers), sum(numbers) / len(numbers), len(numbers),
            ))
        else:
            counts: Dict[str, int] = {}
            for row in rows:
                raw = row.get(column)
                if raw not in (None, ""):
                    label = str(raw)[:60]
                    counts[label] = counts.get(label, 0) + 1
            values.extend(float(count) for count in counts.values())
            if len(counts) <= 100:
                categorical_cols.append(column)
    # 分组聚合值（与 _aggregate_evidence.groupedStats 同源），让验证器能精确复算分组图表。
    for gs in _grouped_aggregates(rows, categorical_cols, numeric_cols):
        for group in gs["groups"]:
            values.extend([float(group["count"]), group["sum"], group["avg"]])
    return values


def _verification(chart: dict, bundle: dict, transform: dict) -> dict:
    output_values = _numeric_values(chart["option"])
    evidence_values = _bundle_numbers(bundle)
    operation = transform.get("operation", "evidence-membership")
    # 容差放宽到 1%（相对）或 0.5（绝对）：LLM 常把统计值四舍五入到整数/整千，
    # 逐位精确比对（1e-6）会把合理舍入误判为伪造；1% 仍足以拦截编造的大数。
    mismatches = []
    for value in output_values:
        if not any(math.isclose(value, candidate, rel_tol=0.01, abs_tol=0.5) for candidate in evidence_values):
            closest = min(evidence_values, key=lambda item: abs(item - value), default=None)
            mismatches.append(f"{value}→最近证据{closest}")
    return {
        "verified": bool(output_values) and not mismatches,
        "method": operation,
        "checkedValues": len(output_values),
        "mismatches": mismatches,
        "evidenceHash": _evidence_digest(_rows_from_payload(bundle.get("payload"))),
        "verifiedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _as_number(value: Any) -> Optional[float]:
    try:
        text = str(value).strip().replace(",", "").rstrip("%")
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _fallback_option(chart_type: str, rows: list, metric: str) -> tuple[str, dict, str]:
    rows = rows[:20] or [{"数据": 0}]
    keys = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else ["数据"]
    metric_field = _resolve_field(rows, metric)
    numeric_key = (
        metric_field
        if metric_field and any(_as_number(row.get(metric_field)) is not None for row in rows)
        else next((key for key in keys if any(_as_number(row.get(key)) is not None for row in rows)), None)
    )
    label_key = next((key for key in keys if key != numeric_key), keys[0])
    labels = [str(row.get(label_key, index + 1))[:30] for index, row in enumerate(rows)]
    if numeric_key:
        values = [_as_number(row.get(numeric_key)) or 0 for row in rows]
    else:
        counts: Dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        labels, values = list(counts.keys()), list(counts.values())
    actual_metric = str(numeric_key or f"{label_key}记录数")
    if chart_type == "pie":
        return "pie", {"tooltip": {"trigger": "item"}, "legend": {"bottom": 0}, "series": [{
            "name": actual_metric, "type": "pie", "radius": ["35%", "68%"],
            "data": [{"name": label, "value": value} for label, value in zip(labels, values)],
        }]}, actual_metric
    if chart_type == "radar":
        max_value = max([float(value) for value in values] + [1.0])
        return "radar", {"tooltip": {}, "radar": {"indicator": [
            {"name": label, "max": max_value * 1.2} for label in labels[:8]
        ]}, "series": [{"name": actual_metric, "type": "radar", "data": [{"name": actual_metric, "value": values[:8]}]}]}, actual_metric
    if chart_type == "gauge":
        return "gauge", {"series": [{"name": actual_metric, "type": "gauge", "progress": {"show": True},
                                       "data": [{"name": labels[0], "value": values[0]}]}]}, actual_metric
    if chart_type == "scatter":
        return "scatter", {
            "tooltip": {"trigger": "item"},
            "xAxis": {"name": "序号", "type": "value"},
            "yAxis": {"name": actual_metric, "type": "value"},
            "series": [{
                "name": actual_metric, "type": "scatter", "symbolSize": 14,
                "data": [[index, float(value)] for index, value in enumerate(values)],
            }],
        }, actual_metric
    if chart_type == "heatmap":
        heat_max = max([float(value) for value in values] + [1.0])
        return "heatmap", {
            "tooltip": {"position": "top"},
            "xAxis": {"type": "category", "data": labels},
            "yAxis": {"type": "category", "data": [actual_metric]},
            "visualMap": {"min": 0, "max": heat_max, "calculable": True,
                          "orient": "horizontal", "left": "center"},
            "series": [{
                "name": actual_metric, "type": "heatmap",
                "data": [[x, 0, float(value)] for x, value in enumerate(values)],
            }],
        }, actual_metric
    if chart_type == "relation":
        graph_max = max([float(value) for value in values] + [1.0])
        return "relation", {
            "tooltip": {},
            "series": [{
                "type": "graph", "layout": "force", "roam": True, "label": {"show": True},
                "data": [
                    {"name": label, "symbolSize": 20 + round(float(value) / graph_max * 40, 2)}
                    for label, value in zip(labels, values)
                ],
                "links": [
                    {"source": labels[index], "target": labels[index + 1]}
                    for index in range(len(labels) - 1)
                ],
            }],
        }, actual_metric
    if chart_type == "sankey":
        return "sankey", {
            "tooltip": {"trigger": "item"},
            "series": [{
                "type": "sankey",
                "data": [{"name": label} for label in labels],
                "links": [
                    {"source": labels[index], "target": labels[index + 1], "value": max(0.0, float(values[index]))}
                    for index in range(len(labels) - 1)
                ],
                "lineStyle": {"color": "gradient", "curveness": 0.5},
            }],
        }, actual_metric
    effective = "line" if chart_type == "line" else "bar"
    return effective, {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": actual_metric},
        "series": [{"name": actual_metric, "type": effective, "smooth": effective == "line", "data": values}],
    }, actual_metric


def _fallback_map(profile: dict, bundles: list, context: Optional[dict] = None) -> dict:
    """当 LLM 编排失败时，使用真实数据构建降级地图。"""
    name_keys = {"name", "title", "region", "location", "名称", "区域", "地点"}
    points = []
    for bundle in bundles:
        for row in _rows_from_payload(bundle["payload"]):
            # 使用共享工具自动发现坐标列（支持 origin_lng/dest_lng 等前缀变体）
            pairs = map_builder.discover_coordinate_columns(list(row.keys()))
            if not pairs:
                continue
            # 使用第一个坐标对（主坐标）
            primary = pairs[0]
            lng = row.get(primary["lng"])
            lat = row.get(primary["lat"])
            if not (_valid_coord(lng, -180, 180) and _valid_coord(lat, -90, 90)):
                continue
            name = next(
                (row[key] for key in name_keys if key in row and row[key] not in (None, "")),
                bundle["source"],
            )
            points.append({
                "name": str(name),
                "lng": float(lng),
                "lat": float(lat),
                "raw": bundle["source"],
            })
    return _sanitize_map_layer({
        "layerId": f"skill_{profile['skillId'] or 'general'}",
        "points": points,
        "layerConfig": {"name": profile["skillName"], "visible": True},
    }, profile, context)


def _infer_metrics_from_bundles(bundles: list, limit: int = 3) -> list:
    """未选 Skill 时，从 bundles 的数值字段推断指标名（用于数据降级图表标题）。"""
    metrics: list = []
    for bundle in bundles:
        rows = _rows_from_payload(bundle.get("payload"))
        if not rows:
            continue
        for column in dict.fromkeys(str(key) for row in rows for key in row):
            if any(_as_number(row.get(column)) is not None for row in rows):
                # 优先用 bundle 的 summary 或 dataset name 作前缀，避免与数据集字段名重复
                metrics.append(column)
                if len(metrics) >= limit:
                    return metrics
    return metrics[:limit]


def _data_fallback(query: str, profile: dict, bundles: list, context: Optional[dict] = None) -> tuple[list, dict, dict]:
    charts = []
    metrics = profile.get("focusMetrics") or []
    if not metrics:
        # 未选 Skill 时从 bundles 推断数值字段作为指标
        metrics = _infer_metrics_from_bundles(bundles, limit=3) or ["核心指标 1", "核心指标 2", "核心指标 3"]
    metrics = metrics[:3]
    requested_types = profile.get("chartTypes") or ["bar", "line", "pie"]
    requested_types = requested_types[:3]
    for index, metric in enumerate(metrics, start=1):
        bundle = bundles[(index - 1) % len(bundles)]
        chart_type, option, effective_metric = _fallback_option(
            requested_types[(index - 1) % len(requested_types)],
            _rows_from_payload(bundle["payload"]),
            metric,
        )
        chart = {
            "chartId": f"c_{index}", "type": chart_type, "title": effective_metric,
            "option": option, "datasetRef": bundle["datasetId"],
            "provenance": {
                "datasetId": bundle["datasetId"],
                "physicalDatasetId": bundle.get("physicalDatasetId", ""),
                "schemaVersion": bundle.get("schemaVersion", 1),
                "transform": {"operation": "deterministic-first-numeric-or-count"},
                "truncated": bundle.get("truncated", False),
            },
        }
        chart["verification"] = _verification(
            chart, bundle, {"operation": "deterministic-first-numeric-or-count"},
        )
        charts.append(chart)
    narrative = {
        "intro": f"已围绕“{query}”读取 {len(bundles)} 个真实数据源。当前结果由数据降级编排生成，建议在 LLM 配置恢复后重新生成以获得更完整说明。",
        "explanations": [
            {"chartId": chart["chartId"], "text": f"该图直接使用 {chart['datasetRef']} 的真实记录生成。"}
            for chart in charts
        ],
        "mapExplanation": "",
    }
    return charts, _fallback_map(profile, bundles, context), narrative


async def _fetch_meta(profile: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """获取可用数据集元数据（供 Planner 决策）。"""
    database_id = str(profile.get("dataSourceId") or context.get("dataSourceId") or "").strip()
    try:
        meta = await asyncio.to_thread(tools.query_datasets_meta, database_id)
    except Exception as exc:
        logger.warning("V2 取数据集元数据失败: %s", exc)
        meta = {"success": False, "message": str(exc)[:200]}
    return meta if isinstance(meta, dict) else {"success": False}


def _build_field_labels(meta: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """从数据集元数据提取 {datasetId: {英文字段名: 中文标签}}。

    meta 为 query_datasets_meta 的返回（{success, data:{schemas:[...]}}）；
    字段中文名优先取 businessMeaning，其次 comment；为空或与英文名相同则跳过，
    供 map_builder 生成 propLabels，前端据此直接显示中文字段名。
    """
    result: Dict[str, Dict[str, str]] = {}
    if not isinstance(meta, dict) or not meta.get("success"):
        return result
    schemas = (meta.get("data", {}) or {}).get("schemas") or []
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        ds_id = str(schema.get("datasetId") or "").strip()
        if not ds_id:
            continue
        labels: Dict[str, str] = {}
        for field in schema.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or field.get("fieldName") or "").strip()
            label = str(field.get("businessMeaning") or field.get("comment") or "").strip()
            if name and label and label != name:
                labels[name] = label
        if labels:
            result[ds_id] = labels
    return result


def _build_profile_for_v2(
    skill_context: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """构造 Skill profile（沿用 _skill_profile + 数据源约束）。"""
    profile = _skill_profile(skill_context)
    runtime_context = dict(context or {})
    return _restrict_profile_to_database(profile, runtime_context)


def _plan_to_legacy_safe_plan(plan: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """把 Planner 输出转换为兼容原 SSE plan 事件的格式。

    原 plan 事件结构：
        {"skill": {...}, "steps": [...], "datasets": [...],
         "chartsPlan": [...], "mapPlan": [...], "mode": "real"}
    """
    chart_specs = plan.get("chartSpecs") or []
    map_specs = plan.get("mapSpecs") or []
    sub_questions = plan.get("subQuestions") or []

    return {
        "skill": {
            "id": profile.get("skillId", ""),
            "name": profile.get("skillName", ""),
            "category": profile.get("category", ""),
        },
        "steps": profile.get("executionPlan") or [
            {"sequence": 1, "name": "汇聚态势数据"},
            {"sequence": 2, "name": "生成图表与地图"},
            {"sequence": 3, "name": "撰写态势说明"},
        ],
        "datasets": [
            {"datasetId": sq.get("datasetId", ""), "intent": sq.get("question", "")}
            for sq in sub_questions if sq.get("datasetId")
        ],
        "chartsPlan": [
            {"type": cs.get("type", "bar"), "title": cs.get("title", ""), "intent": cs.get("intent", "")}
            for cs in chart_specs
        ],
        "mapPlan": [
            {"layerId": ms.get("id", ""), "types": [ms.get("layerType", "points")]}
            for ms in map_specs
        ] or [{"layerId": f"skill_{profile.get('skillId') or 'general'}", "types": profile.get("mapLayerTypes", ["points"])}],
        "mode": "real",
        "_fallback": plan.get("_fallback", False),
    }


def _evidences_to_dataset_events(store: EvidenceStore) -> List[Dict[str, Any]]:
    """把 EvidenceStore 转换为 SSE dataset 事件列表（兼容原 dataset 事件结构）。"""
    events = []
    for index, ev in enumerate(store.list_evidences(), start=1):
        # 统一用 evidence.id（子问题 id）作为 datasetId，与 chart.datasetRef 对齐，
        # 使前端全量重建时 chart.datasetRef 能精确命中 dataset.datasetId。
        dataset_id = ev.id or f"real_{index}_{_safe_id(ev.source)}"
        total_rows = ev.meta.get("totalRows", len(ev.rows))
        events.append({
            "datasetId": dataset_id,
            "source": ev.source or ev.dataset_ref,
            "summary": ev.summary,
            # rows 为全量行数组（供图表/地图渲染取数）；rowCount 为实际返回行数；
            # totalRows 为真实总数（供前端步骤面板展示「共 M 行」）。
            "rows": ev.rows,
            "rowCount": len(ev.rows),
            "totalRows": total_rows,
            "realData": True,
            "physicalDatasetId": ev.dataset_ref,
            "schemaVersion": 1,
            "truncated": ev.meta.get("truncated", False) or total_rows > len(ev.rows),
            "execution": {
                "filters": ev.meta.get("filters") or {},
                "aggregation": ev.meta.get("aggregation") or "",
            },
            "evidenceHash": ev.hash or _evidence_digest(ev.rows),
            "columns": ev.columns,
            "data": ev.rows,
        })
    return events


def _post_process_map(
    map_layer: Optional[Dict[str, Any]],
    profile: Dict[str, Any],
    context: Dict[str, Any],
    store: EvidenceStore,
) -> Optional[Dict[str, Any]]:
    """对 map_layer 做坐标校验（沿用原 _verify_map_coordinates）。"""
    if not map_layer:
        return None
    sanitized = _sanitize_map_layer(map_layer, profile, context)
    # v2 用 EvidenceStore 替代 bundles：从证据数据收集坐标证据，供 _verify_map_coordinates 校验。
    # 注意不能传空 list——_coordinate_evidence([]) 返回空集合会触发"无坐标证据"分支，
    # 把 points/routes/areas/circles 全部清空，导致地图图层无内容可渲染。
    bundles = [{"payload": {"rows": ev.rows}} for ev in store.list_evidences()]
    return _verify_map_coordinates(sanitized, bundles)


async def real_generate_v2(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """V2 入口：基于 Agent 架构的态势生成。

    五阶段流程：PLAN → RESEARCH → WRITE(chart+map 并行) → VERIFY → NARRATIVE → EMIT
    """
    runtime_context = dict(context or {})
    # 绑定终端用户身份到下游调用（与 legacy 路径一致）。main.py 会把 _actor 写入
    # context；未传入时回退到本地管理员身份，保证 Executor 取数请求带上有效 ACL。
    actor = runtime_context.get("_actor") or {
        "userId": "local-admin", "teamIds": [], "role": "admin",
    }
    with tools.actor_context(actor):
        async for event_type, data in _real_generate_v2_body(
            query, report_id, skill_context, runtime_context,
        ):
            yield event_type, data


async def _real_generate_v2_body(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    runtime_context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """V2 主体：五阶段流程（PLAN → RESEARCH → WRITE → VERIFY → NARRATIVE → EMIT）。

    actor 身份由 real_generate_v2 包装器注入 tools 上下文，本函数不做身份处理。
    """
    runtime_context = dict(runtime_context or {})
    profile = _build_profile_for_v2(skill_context, runtime_context)
    store = EvidenceStore(report_id)
    sm = StateMachine(report_id)

    # ───── 阶段 1：PLAN ─────
    await sm.enter(Stage.PLAN)
    try:
        meta = await _fetch_meta(profile, runtime_context)
        # 处理用户在 context 里传的 Skill 参数（拼接到 query 中供 Planner 使用）
        parameters = ((runtime_context.get("skill") or {}).get("parameters") or {})
        effective_query = query
        if parameters:
            controls = "，".join(f"{key}={value}" for key, value in parameters.items())
            effective_query = f"{query}\n必须遵循的 Skill 执行参数：{controls}"

        planner = Planner(profile, meta)
        plan = await planner.plan(effective_query)
        await sm.exit(Stage.PLAN, success=True, meta={
            "planner_fallback": plan.get("_fallback", False),
            "planner_error": plan.get("_planner_error", ""),
            "sub_questions": len(plan.get("subQuestions") or []),
            "chart_specs": len(plan.get("chartSpecs") or []),
        })
    except Exception as exc:
        await sm.exit(Stage.PLAN, success=False, error=str(exc)[:200])
        raise

    # 推送 plan SSE 事件
    safe_plan = _plan_to_legacy_safe_plan(plan, profile)
    yield "plan", safe_plan
    if safe_plan.get("_fallback"):
        yield "error", {
            "stage": "plan",
            "message": f"Planner 降级为 Skill 模板: {plan.get('_planner_error', '')[:120]}",
            "fatal": False,
        }

    # 非态势意图（Planner 已在 directAnswer 给出回答）：跳过编排流程，
    # 直接把回答作为正文推给前端（复用 narrative 事件，前端无需改动）
    if str(plan.get("intent") or "").lower() == "general":
        yield "narrative", {
            "intro": str(plan.get("directAnswer") or ""),
            "explanations": [],
            "mapExplanation": "",
        }
        yield "done", {
            "reportId": report_id,
            "status": "ready",
            "partial": False,
            "skillId": profile.get("skillId", ""),
            "skillName": profile.get("skillName", ""),
            "dataMode": "real",
            "orchestration": "v2",
            "stateMachine": sm.snapshot(),
        }
        return

    # ───── 阶段 2：RESEARCH ─────
    await sm.enter(Stage.RESEARCH)
    try:
        sub_questions = plan.get("subQuestions") or []
        evidences = await executor.execute_all(sub_questions, store)
        await sm.exit(Stage.RESEARCH, success=True, meta={"evidences": len(evidences)})
    except Exception as exc:
        await sm.exit(Stage.RESEARCH, success=False, error=str(exc)[:200])
        raise

    # 时间窗放宽：所有证据为空且 sub_questions 含时间过滤时，剔除时间过滤重试一次。
    # 复用 V1 的「近 N 天无匹配数据 → 放宽」语义，但 V2 不依赖参数绑定，直接剔除
    # 时间字段过滤后让 Text-to-SQL 重新生成无时间约束的 SQL。
    relaxed_notice = None
    if not any(ev.rows for ev in store.list_evidences()):
        if executor._any_sub_question_has_time_filter(sub_questions):
            logger.warning(
                "V2 时间窗过滤无匹配数据，剔除时间过滤重试: reportId=%s", report_id,
            )
            await sm.enter(Stage.RESEARCH, meta={"relax": "time-window"})
            try:
                relaxed_sub_questions = executor._strip_time_filters(sub_questions)
                # EvidenceStore.add_evidence 同 id 视为更新，重试会覆盖之前的空证据
                evidences = await executor.execute_all(relaxed_sub_questions, store)
                await sm.exit(Stage.RESEARCH, success=True, meta={
                    "evidences": len(evidences),
                    "relaxed": "time-window",
                })
                if any(ev.rows for ev in store.list_evidences()):
                    relaxed_notice = "所选时间范围无匹配数据，已自动放宽时间过滤"
            except Exception as exc:
                logger.warning("V2 时间窗放宽重试失败: %s", exc)
                await sm.exit(Stage.RESEARCH, success=False, error=str(exc)[:200])

    # 证据为空则失败
    if not any(ev.rows for ev in store.list_evidences()):
        raise RuntimeError("没有取得可用于态势分析的真实数据，请检查 Skill 数据源和相关服务")

    # 推送时间窗放宽提示（非致命，前端可选展示）
    if relaxed_notice:
        yield "error", {
            "stage": "filter",
            "message": relaxed_notice,
            "fatal": False,
        }

    # 推送 dataset SSE 事件（兼容原事件结构）
    for ds_event in _evidences_to_dataset_events(store):
        yield "dataset", ds_event

    # ───── 阶段 3：WRITE (chart + map 并行) ─────
    chart_specs = plan.get("chartSpecs") or []
    map_specs = plan.get("mapSpecs") or []

    partial = False
    charts: List[Dict[str, Any]] = []
    map_layer: Optional[Dict[str, Any]] = None

    await sm.enter(Stage.WRITE)
    try:
        # chart 与 map 并行
        chart_task = writer.write_charts_parallel(
            effective_query, chart_specs, store, profile,
        )
        # 只在有 mapSpecs 或 evidences 含地理列时调 map
        field_labels = _build_field_labels(meta)
        map_task = writer.write_map(effective_query, store, profile, field_labels)

        charts_result, map_result = await asyncio.gather(chart_task, map_task, return_exceptions=True)

        if isinstance(charts_result, Exception):
            logger.warning("V2 chart 并行整体失败: %s", charts_result)
            charts = []
        else:
            charts = charts_result or []

        if isinstance(map_result, Exception):
            logger.warning("V2 map 调用失败: %s", map_result)
            map_layer = None
        else:
            map_layer_raw, _ = map_result if isinstance(map_result, tuple) else (None, "")
            map_layer = _post_process_map(map_layer_raw, profile, runtime_context, store)

        await sm.exit(Stage.WRITE, success=True, meta={
            "charts": len(charts),
            "map_present": map_layer is not None,
        })
    except Exception as exc:
        await sm.exit(Stage.WRITE, success=False, error=str(exc)[:200])
        if not config.SITUATION_ALLOW_DATA_FALLBACK:
            raise
        partial = True
        yield "error", {
            "stage": "write",
            "message": f"产图阶段失败，使用真实数据降级：{str(exc)[:160]}",
            "fatal": False,
        }

    # ───── 阶段 4：VERIFY + Reflection ─────
    await sm.enter(Stage.VERIFY)
    try:
        verify_result = verifier.verify_all(
            charts,
            None,  # narrative 还没生成，先只校验 charts
            store,
            min_charts=config.SITUATION_MIN_CHARTS,
        )
        await sm.exit(Stage.VERIFY, success=True, meta={"passed": verify_result["passed"]})
    except Exception as exc:
        await sm.exit(Stage.VERIFY, success=False, error=str(exc)[:200])
        verify_result = {"passed": False, "summary": f"校验异常: {exc}"}

    # Reflection：chart 数值/适配校验失败时重写，上限 SITUATION_REFLECTION_MAX_ROUNDS
    reflection_round = 0
    while (
        not verify_result["passed"]
        and reflection_round < config.SITUATION_REFLECTION_MAX_ROUNDS
        and any(
            f["stage"] in ("type_fit", "value_evidence", "field_mapping")
            for f in verify_result.get("chart_result", {}).get("failures", [])
        )
    ):
        reflection_round += 1
        sm.increment_reflection(Stage.WRITE)
        logger.info(
            "V2 Reflection 第 %s 轮重写失败图表: %s",
            reflection_round,
            [f["chartId"] for f in verify_result["chart_result"]["failures"]],
        )

        # 找出失败的 chartSpec（按 chartId 匹配），只重写这部分
        failed_chart_ids = {
            f["chartId"] for f in verify_result["chart_result"]["failures"]
            if f["stage"] in ("type_fit", "value_evidence")
        }
        rewrite_specs = [
            cs for cs in chart_specs
            if str(cs.get("id")) in failed_chart_ids
        ]
        if not rewrite_specs:
            break

        try:
            await sm.enter(Stage.WRITE, meta={"reflection": reflection_round})
            rewritten = await writer.write_charts_parallel(
                effective_query, rewrite_specs, store, profile,
            )
            await sm.exit(Stage.WRITE, success=True, meta={"rewritten": len(rewritten)})

            # 用重写结果替换原 charts 中对应的项
            charts_by_id = {c.get("chartId"): c for c in charts}
            for new_chart in rewritten:
                cid = new_chart.get("chartId")
                if cid:
                    charts_by_id[cid] = new_chart
            charts = list(charts_by_id.values())

            # 重新校验
            await sm.enter(Stage.VERIFY, meta={"reflection": reflection_round})
            verify_result = verifier.verify_all(
                charts,
                None,
                store,
                min_charts=config.SITUATION_MIN_CHARTS,
            )
            await sm.exit(Stage.VERIFY, success=verify_result["passed"], meta={"passed": verify_result["passed"]})
        except Exception as exc:
            logger.warning("V2 Reflection 第 %s 轮失败: %s", reflection_round, exc)
            break

    if not verify_result["passed"] and not partial:
        partial = True
        yield "error", {
            "stage": "verify",
            "message": f"部分校验未通过，输出可能不完整: {verify_result.get('summary', '')[:160]}",
            "fatal": False,
        }

    # ───── 阶段 5：NARRATIVE（最后串行） ─────
    await sm.enter(Stage.NARRATIVE)
    try:
        narrative = await writer.write_narrative(effective_query, store, map_layer)
        await sm.exit(Stage.NARRATIVE, success=True, meta={
            "explanations": len(narrative.get("explanations") or []),
        })
    except Exception as exc:
        await sm.exit(Stage.NARRATIVE, success=False, error=str(exc)[:200])
        if not config.SITUATION_ALLOW_DATA_FALLBACK:
            raise
        partial = True
        narrative = {
            "intro": f"态势生成过程中遇到问题（{str(exc)[:100]}），已基于真实数据降级输出。",
            "explanations": [],
            "mapExplanation": "",
        }

    # ───── 阶段 6：EMIT（推送产物） ─────
    await sm.enter(Stage.EMIT)

    # narrative 生成后再补一次引用校验（WRITE 阶段只校验 charts，narrative 当时尚未生成）
    narrative_check = verifier.verify_narrative(narrative, store)
    if not narrative_check["passed"] and not partial:
        partial = True
        logger.warning("V2 narrative 校验未通过: %s", narrative_check.get("summary", ""))

    # 推送 chart 事件
    for chart in charts:
        yield "chart", chart
    # 推送 map_layer 事件
    if map_layer:
        yield "map_layer", map_layer
    # 推送 narrative 事件
    yield "narrative", narrative
    # 推送 verify 事件（前端可选展示）
    yield "verify", {
        "passed": verify_result["passed"] and narrative_check["passed"],
        "summary": (
            f"{verify_result.get('summary', '')} | narrative: {narrative_check.get('summary', '')}"
        ),
        "reflectionRounds": reflection_round,
        "failures": verify_result.get("chart_result", {}).get("failures", []),
    }
    # 推送 done 事件
    yield "done", {
        "reportId": report_id,
        "status": "partial" if partial else "ready",
        "partial": partial,
        "skillId": profile.get("skillId", ""),
        "skillName": profile.get("skillName", ""),
        "dataMode": "real",
        "orchestration": "v2",
        "stateMachine": sm.snapshot(),
    }
    await sm.exit(Stage.EMIT, success=True)

    logger.info(
        "V2 态势生成完成: reportId=%s charts=%s map=%s narrative=%s partial=%s reflection=%s",
        report_id, len(charts), bool(map_layer),
        len(narrative.get("explanations") or []), partial, reflection_round,
    )


async def generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """态势生成入口；统一走 V2 Agent 架构（Planner/Executor/Writer/Verifier/Narrative）。

    V1 的 mock_generate / real_generate 路径已移除：不再依赖 knowledge/qa/indicator
    服务，所有数据均来自 admin-service 的数据集 schema + 查询接口（ADR-01/05）。
    """
    async for evt in real_generate_v2(query, report_id, skill_context, context):
        yield evt


__all__ = ["generate", "real_generate_v2"]
