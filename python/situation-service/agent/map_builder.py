"""基于全量数据自动构建地图标注。

复用评估分析（qa-service）_auto_build_map_annotations 的代码智能识别逻辑：
不依赖 LLM 内联样本，而是直接扫描数据列，自动识别经纬度、轨迹、圆形范围，
生成完整 routes/markers/areas + 业务属性（props），使态势图地图达到评估分析的展示效果。

输出结构对齐态势图 map_layer 契约（points/routes/areas/circles）。
"""
import logging

logger = logging.getLogger("situation-service")

# 被排除的列（坐标、标识、排序字段，不需要放入 props）
_EXCLUDE = {
    "name", "aircraft_name", "aircraft_id", "seq", "id",
    "lng", "lon", "longitude", "lat", "latitude", "raw",
}

# 标注配色：按分组/行索引取色，同路线同色、不同路线不同色，避免全部退化为同一种颜色
_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#2980b9", "#27ae60", "#8e44ad",
    "#d35400", "#c0392b",
]


def _color_for(index: int) -> str:
    """按索引稳定取色，索引越界时回绕。"""
    return _PALETTE[index % len(_PALETTE)]


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _make_props(row, columns):
    """从行中提取非坐标、非标识的业务字段作为 props（供前端弹窗展示）。"""
    props = {}
    for key in columns:
        if key.lower() in _EXCLUDE:
            continue
        value = row.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, float):
            value = round(value, 2)
        props[key] = value
    return props if props else None


def build_map_annotations(rows):
    """扫描数据行，自动构建地图标注 dict。

    返回 {"points": [...], "routes": [...], "areas": [...], "circles": [...]}；
    无地理列时返回空 dict。
    """
    if not rows:
        return {}

    columns = list(rows[0].keys()) if isinstance(rows[0], dict) else []
    if not columns:
        return {}

    cols_lower = {k.lower(): k for k in columns}

    lng_key = next((cols_lower[c] for c in ("lng", "lon", "longitude") if c in cols_lower), None)
    lat_key = next((cols_lower[c] for c in ("lat", "latitude") if c in cols_lower), None)
    if not lng_key or not lat_key:
        return {}

    result = {"points": [], "routes": [], "areas": [], "circles": []}

    # 圆形范围（radius_km / radius）
    if "radius_km" in cols_lower or "radius" in cols_lower:
        radius_key = "radius_km" if "radius_km" in cols_lower else "radius"
        for index, row in enumerate(rows):
            name = str(row.get("name", ""))
            props = _make_props(row, columns)
            color = _color_for(index)
            circle = {
                "name": name,
                "center": {"lng": _to_float(row.get(lng_key)), "lat": _to_float(row.get(lat_key))},
                "radiusKm": _to_float(row.get(radius_key), 50),
                "color": color,
            }
            if props:
                circle["props"] = props
            result["circles"].append(circle)

            point = {
                "name": name,
                "lng": _to_float(row.get(lng_key)),
                "lat": _to_float(row.get(lat_key)),
                "routeName": name,
                "color": color,
            }
            if props:
                point["props"] = props
            result["points"].append(point)
        return result

    # 飞行路线（seq + aircraft_id / aircraft_name）
    has_seq = "seq" in cols_lower
    has_aid = "aircraft_id" in cols_lower or "aircraft_name" in cols_lower
    if has_seq and has_aid:
        id_key = "aircraft_id" if "aircraft_id" in cols_lower else "aircraft_name"
        name_key = "aircraft_name" if "aircraft_name" in cols_lower else id_key
        groups = {}
        for row in rows:
            gid = str(row.get(id_key, ""))
            if gid not in groups:
                groups[gid] = {"name": str(row.get(name_key, gid)), "points": []}
            groups[gid]["points"].append({
                "seq": _to_int(row.get("seq")),
                "lng": _to_float(row.get(lng_key)),
                "lat": _to_float(row.get(lat_key)),
                "row": row,
            })

        for gid, group in groups.items():
            points = sorted(group["points"], key=lambda p: p["seq"])
            color = _color_for(len(result["routes"]))
            result["routes"].append({
                "name": group["name"],
                "color": color,
                "points": [{"lng": p["lng"], "lat": p["lat"]} for p in points],
            })
            for index, pt in enumerate(points):
                if index == 0:
                    label = group["name"] + "-起点"
                elif index == len(points) - 1:
                    label = group["name"] + "-终点"
                else:
                    label = group["name"] + f"-途经{index}"
                point = {
                    "name": label,
                    "lng": pt["lng"],
                    "lat": pt["lat"],
                    "routeName": group["name"],
                    "color": color,
                }
                props = _make_props(pt["row"], columns)
                if props:
                    point["props"] = props
                result["points"].append(point)
        return result

    # 默认标记点（无半径、无轨迹）
    for index, row in enumerate(rows):
        name = str(row.get("name", row.get("aircraft_name", "")))
        point = {
            "name": name,
            "lng": _to_float(row.get(lng_key)),
            "lat": _to_float(row.get(lat_key)),
            "routeName": name,
            "color": _color_for(index),
        }
        props = _make_props(row, columns)
        if props:
            point["props"] = props
        result["points"].append(point)

    return result
