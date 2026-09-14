"""GeoProfile —— 证据级地理能力画像（地图生成链路重构 §4.1）。

设计原则（参见 .trae/documents/态势图-地图生成链路重构方案.md）：
- 地理能力在取数阶段一次性测定，全链路（Planner/Writer/Verifier/Layout）只读该画像，
  不再各自独立判断，消灭"空图层/无中生有地图"的口径漂移；
- 地图存在性由数据决定：hasGeo=False 的证据永远不进地图管线。

GeoProfile 结构（随 Evidence.meta["geoProfile"] 携带）：
    {
        "hasGeo": bool,                # 是否存在可用坐标（列配对 + 样本行抽检通过）
        "pairs": [...],                # discover_coordinate_columns 配对结果
        "capableKinds": [...],         # 可产图层要素类型（points/routes/circles）
        "hasWaypoints": bool,          # 是否存在可解析的途经点 JSON 列
        "featureEstimate": int,        # 可产要素数粗估
    }
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from agent import map_builder

logger = logging.getLogger("situation-service")

# 途经点 JSON 列名识别：waypoints_json / 途经点 等（与 map_builder 的 JSON 内容抽检双条件配合）
_WAYPOINT_COLUMN_PATTERN = re.compile(r"(waypoint|途经)", re.IGNORECASE)


def _parse_float(value: Any) -> Optional[float]:
    """宽松解析浮点数，失败返回 None（区别于 0 值）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_coord(lng: Optional[float], lat: Optional[float]) -> bool:
    """坐标值是否在合法范围。"""
    return (
        lng is not None and lat is not None
        and -180 <= lng <= 180 and -90 <= lat <= 90
    )


def _rows_have_valid_coords(rows: Sequence[Dict[str, Any]], pairs: List[Dict[str, str]], sample: int = 5) -> bool:
    """抽检前 sample 行，任一坐标对在任一行中产出合法坐标即认为可用。"""
    for row in rows[:sample]:
        for pair in pairs:
            lng = _parse_float(row.get(pair["lng"]))
            lat = _parse_float(row.get(pair["lat"]))
            if _valid_coord(lng, lat):
                return True
    return False


def _has_parseable_waypoints(rows: Sequence[Dict[str, Any]], columns: Sequence[str], sample: int = 3) -> bool:
    """是否存在列名匹配途经点、且样本行内可解析出含 lng/lat 的 JSON 数组。"""
    waypoint_cols = [c for c in columns if _WAYPOINT_COLUMN_PATTERN.search(str(c))]
    if not waypoint_cols:
        return False
    for row in rows[:sample]:
        for col in waypoint_cols:
            raw = row.get(col)
            if raw in (None, ""):
                continue
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if not isinstance(data, list) or not data:
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                lng = _parse_float(item.get("lng", item.get("lon", item.get("longitude"))))
                lat = _parse_float(item.get("lat", item.get("latitude")))
                if _valid_coord(lng, lat):
                    return True
    return False


def compute_geo_profile(columns: Sequence[str], rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """计算证据级地理画像（确定性，不调 LLM）。

    Args:
        columns: 证据列名列表（脱敏后）
        rows: 证据行数据

    Returns:
        GeoProfile dict（保证结构完整，hasGeo=False 时其余字段仍有意义）
    """
    pairs = map_builder.discover_coordinate_columns([str(c) for c in (columns or [])]) if columns else []
    has_geo = bool(pairs) and bool(rows) and _rows_have_valid_coords(rows, pairs)

    capable_kinds: List[str] = []
    if has_geo:
        capable_kinds.append("points")
        prefixes = {p["prefix"].lower() for p in pairs}
        if {"origin", "from", "start", "src"} & prefixes and {"dest", "destination", "to", "end", "dst"} & prefixes:
            capable_kinds.append("routes")
        cols_lower = {str(c).lower() for c in columns}
        if "radius_km" in cols_lower or "radius" in cols_lower:
            capable_kinds.append("circles")

    has_waypoints = bool(pairs) and _has_parseable_waypoints(rows, columns or [])
    if has_waypoints and "routes" not in capable_kinds and has_geo:
        # 无 origin/dest 前缀但存在途经点 JSON 的形态同样支持路线展开
        capable_kinds.append("routes")

    feature_estimate = 0
    if has_geo:
        if "routes" in capable_kinds and "points" in capable_kinds:
            # 路线形态：每行 1 条路线 + 起终点/途经点标点
            feature_estimate = len(rows) * 3
        else:
            feature_estimate = min(len(rows) * len(pairs), 5000)

    return {
        "hasGeo": has_geo,
        "pairs": pairs,
        "capableKinds": capable_kinds,
        "hasWaypoints": has_waypoints,
        "featureEstimate": feature_estimate,
    }


def dataset_geo_info(schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从数据集 schema（/export/for-llm 的 schemas 项）推断地理能力标注。

    Args:
        schema: 含 fields（[{column/type/...}, ...]）的数据集元数据

    Returns:
        {"hasGeo": True, "kinds": [...], "hasWaypoints": bool, "pairs": [...]}；
        无地理字段时返回 None。
    """
    if not isinstance(schema, dict):
        return None
    field_names = []
    for field in schema.get("fields") or []:
        if isinstance(field, dict):
            name = str(field.get("column") or field.get("name") or field.get("fieldName") or "").strip()
            if name:
                field_names.append(name)
    if not field_names:
        return None

    pairs = map_builder.discover_coordinate_columns(field_names)
    if not pairs:
        return None

    # 数据集元数据没有行数据可抽检，仅按列名判定能力（行级校验由证据级 GeoProfile 兜底）
    kinds: List[str] = ["points"]
    prefixes = {p["prefix"].lower() for p in pairs}
    if {"origin", "from", "start", "src"} & prefixes and {"dest", "destination", "to", "end", "dst"} & prefixes:
        kinds.append("routes")
    cols_lower = {n.lower() for n in field_names}
    if "radius_km" in cols_lower or "radius" in cols_lower:
        kinds.append("circles")
    has_waypoints = any(_WAYPOINT_COLUMN_PATTERN.search(name) for name in field_names)
    if has_waypoints and "routes" not in kinds:
        kinds.append("routes")

    return {
        "hasGeo": True,
        "kinds": kinds,
        "hasWaypoints": has_waypoints,
        "pairs": pairs,
    }


def annotate_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """为 meta（/export/for-llm 返回）中每个 schema 标注地理能力（schema["geo"]）。

    原地标注并返回同一 meta 引用；meta 非法时原样返回。
    Planner 的 prompt 文本与 _validate_plan 均读取该标注，保证规划与校验同源。
    """
    if not isinstance(meta, dict) or not meta.get("success"):
        return meta
    for schema in (meta.get("data", {}) or {}).get("schemas", []) or []:
        if isinstance(schema, dict) and "geo" not in schema:
            schema["geo"] = dataset_geo_info(schema) or {"hasGeo": False}
    return meta


def geo_capable_dataset_ids(meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """返回 {datasetId: geo标注}（仅含具备地理能力的数据集）。

    meta 未标注（旧调用方/mock 场景）时返回空 dict，调用方应跳过地理强校验。
    """
    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(meta, dict) or not meta.get("success"):
        return result
    for schema in (meta.get("data", {}) or {}).get("schemas", []) or []:
        if not isinstance(schema, dict):
            continue
        ds_id = str(schema.get("datasetId") or "").strip()
        geo = schema.get("geo")
        if ds_id and isinstance(geo, dict) and geo.get("hasGeo"):
            result[ds_id] = geo
    return result


__all__ = [
    "compute_geo_profile",
    "dataset_geo_info",
    "annotate_meta",
    "geo_capable_dataset_ids",
]
