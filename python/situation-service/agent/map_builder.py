"""基于全量数据自动构建地图标注。

复用评估分析（qa-service）_auto_build_map_annotations 的代码智能识别逻辑：
不依赖 LLM 内联样本，而是直接扫描数据列，自动识别经纬度、轨迹、圆形范围，
生成完整 routes/markers/areas + 业务属性（props），使态势图地图达到评估分析的展示效果。

输出结构对齐态势图 map_layer 契约（points/routes/areas/circles）。
"""
import logging
import re

logger = logging.getLogger("situation-service")

# 被排除的列（坐标、标识、排序字段，不需要放入 props）
_EXCLUDE = {
    "name", "aircraft_name", "aircraft_id", "seq", "id",
    "lng", "lon", "longitude", "lat", "latitude", "raw",
    "_dataset",
}

# 标注配色：按分组/行索引取色，同路线同色、不同路线不同色，避免全部退化为同一种颜色
_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#2980b9", "#27ae60", "#8e44ad",
    "#d35400", "#c0392b",
]

# 坐标列正则：匹配以经度/纬度关键词结尾的列名，供 _make_props 排除坐标字段
_COORD_PATTERN = re.compile(r'(lng|lon|longitude|经度|lat|latitude|纬度)$', re.IGNORECASE)


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
        key_lower = key.lower()
        if key_lower in _EXCLUDE:
            continue
        # 排除任何以坐标关键词结尾的列（如 origin_lng, dest_lat, geolocation_lng 等）
        if _COORD_PATTERN.search(str(key)):
            continue
        value = row.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, float):
            value = round(value, 2)
        props[key] = value
    return props if props else None


def _prop_labels(props, field_labels):
    """根据数据集字段中文名生成 props 的中文标签映射（供前端弹窗直接显示中文）。

    field_labels 为 {英文字段名: 中文标签}；未提供或字段无中文名时返回 None，
    由前端回退到自身的中文映射表（FIELD_CN_MAP）。
    """
    if not props or not field_labels:
        return None
    labels = {}
    for key in props:
        label = field_labels.get(key)
        if label and str(label).strip() and str(label).strip() != key:
            labels[key] = str(label).strip()
    return labels or None


# 路线命名候选字段（按优先级排序）：名称 → 编号/航班号 → 型号/类型 → 标识
_ROUTE_NAME_KEYS = (
    "name", "title", "label", "名称", "标题",
    "flight_no", "flightno", "航班号", "车次", "train_no", "班次",
    "route_id", "routeid", "线路号", "线路编号",
    "no", "code", "number", "编号", "编码", "序号",
    "model", "型号", "机型", "aircraft_model",
    "type", "类型", "类别",
    "id", "aircraft_id", "标识",
)


def _pick_route_name(row, columns, index):
    """从行数据中智能选取路线名称。

    优先级：名称类 → 编号/航班号 → 型号/类型 → 标识；
    所有候选列均无值时兜底为「路线N」（N 从 1 开始）。
    避免数据无 name 列时全部退化为同一种兜底命名。
    """
    cols_lower = {str(k).lower(): k for k in columns}
    for key in _ROUTE_NAME_KEYS:
        col = cols_lower.get(key)
        if col is None:
            continue
        value = row.get(col)
        if value not in (None, ""):
            return str(value)
    return f"路线{index + 1}"


def discover_coordinate_columns(columns):
    """从列名列表中自动发现所有经纬度列，按前缀配对。

    支持子串匹配：任何以 _lng / _lon / _longitude / _经度 结尾的字段识别为经度，
    任何以 _lat / _latitude / _纬度 结尾的字段识别为纬度。
    按前缀（尾部关键词之前的部分）配对，支持同一数据源中的多对经纬度。

    示例：
        ["origin_lng", "origin_lat", "dest_lng", "dest_lat"]
        -> [{"prefix": "origin_", "lng": "origin_lng", "lat": "origin_lat"},
            {"prefix": "dest_",   "lng": "dest_lng",   "lat": "dest_lat"}]

        ["geolocation_lng", "geolocation_lat"]
        -> [{"prefix": "geolocation_", "lng": "geolocation_lng", "lat": "geolocation_lat"}]

        ["lng", "lat"]
        -> [{"prefix": "", "lng": "lng", "lat": "lat"}]

        ["longitude", "latitude"]
        -> [{"prefix": "", "lng": "longitude", "lat": "latitude"}]

    Args:
        columns: 列名列表（字符串）

    Returns:
        list[dict]: 每个元素包含 prefix（前缀）、lng（经度列名）、lat（纬度列名）。
                    如果没有可用配对，返回空列表。
    """
    if not columns:
        return []

    # 正则：匹配以经度/纬度关键词结尾的列名，捕获前缀部分
    # 注意：longitude 必须排在 lon 前面，否则 lon 会先匹配 longitude 的前 3 个字符
    lng_pattern = re.compile(r'^(.+_)?(lng|longitude|lon|经度)$', re.IGNORECASE)
    lat_pattern = re.compile(r'^(.+_)?(lat|latitude|纬度)$', re.IGNORECASE)

    # 收集所有经度列和纬度列：(规范化前缀, 原始列名)
    lng_entries = []  # [(prefix, original_key), ...]
    lat_entries = []  # [(prefix, original_key), ...]

    for col in columns:
        col_str = str(col).strip()
        if not col_str:
            continue
        m = lng_pattern.match(col_str)
        if m:
            prefix = (m.group(1) or "").rstrip('_')
            lng_entries.append((prefix, col_str))
            continue
        m = lat_pattern.match(col_str)
        if m:
            prefix = (m.group(1) or "").rstrip('_')
            lat_entries.append((prefix, col_str))

    # 按前缀配对：遍历经度列，查找同前缀的纬度列
    lat_by_prefix = {prefix: key for prefix, key in lat_entries}
    pairs = []
    for prefix, lng_key in lng_entries:
        lat_key = lat_by_prefix.get(prefix)
        if lat_key:
            pairs.append({
                "prefix": prefix,
                "lng": lng_key,
                "lat": lat_key,
            })
    return pairs


def build_map_annotations(rows, field_labels=None):
    """扫描数据行，自动构建地图标注 dict。

    field_labels: 可选 {英文字段名: 中文标签}，来自数据集元数据（businessMeaning/comment）。
                 提供后每个 point/circle 会附带 propLabels，前端据此直接显示中文字段名。

    返回 {"points": [...], "routes": [...], "areas": [...], "circles": [...]}；
    无地理列时返回空 dict。
    """
    if not rows:
        return {}

    columns = list(rows[0].keys()) if isinstance(rows[0], dict) else []
    if not columns:
        return {}

    # 自动发现所有经纬度列对（支持 origin_lng/dest_lng/geolocation_lng 等前缀变体）
    pairs = discover_coordinate_columns(columns)
    if not pairs:
        return {}

    # 选择主坐标对：优先空前缀（裸 lng/lat），否则用第一个
    primary = next((p for p in pairs if p["prefix"] == ""), pairs[0])
    lng_key = primary["lng"]
    lat_key = primary["lat"]

    # 保留 cols_lower 用于后续精确匹配（radius_km / seq 等非坐标字段）
    cols_lower = {k.lower(): k for k in columns}

    result = {"points": [], "routes": [], "areas": [], "circles": []}

    # 圆形范围（radius_km / radius）
    if "radius_km" in cols_lower or "radius" in cols_lower:
        radius_key = "radius_km" if "radius_km" in cols_lower else "radius"
        for index, row in enumerate(rows):
            name = str(row.get("name", ""))
            props = _make_props(row, columns)
            labels = _prop_labels(props, field_labels)
            color = _color_for(index)
            circle = {
                "name": name,
                "center": {"lng": _to_float(row.get(lng_key)), "lat": _to_float(row.get(lat_key))},
                "radiusKm": _to_float(row.get(radius_key), 50),
                "color": color,
            }
            if props:
                circle["props"] = props
            if labels:
                circle["propLabels"] = labels
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
            if labels:
                point["propLabels"] = labels
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
                labels = _prop_labels(props, field_labels)
                if labels:
                    point["propLabels"] = labels
                result["points"].append(point)
        return result

    # 检查是否存在 origin+dest 配对（常用于物流/运输数据）
    origin_prefixes = {"origin", "起点", "from", "start", "src"}
    dest_prefixes = {"dest", "destination", "终点", "to", "end", "dst"}

    origin_pair = next((p for p in pairs if p["prefix"].lower() in origin_prefixes), None)
    dest_pair = next((p for p in pairs if p["prefix"].lower() in dest_prefixes), None)

    if origin_pair and dest_pair:
        # 为每行数据生成从 origin 到 dest 的路线，以及起/终点标记
        for index, row in enumerate(rows):
            origin_lng = _to_float(row.get(origin_pair["lng"]))
            origin_lat = _to_float(row.get(origin_pair["lat"]))
            dest_lng = _to_float(row.get(dest_pair["lng"]))
            dest_lat = _to_float(row.get(dest_pair["lat"]))

            # 跳过坐标无效的行
            if not (-180 <= origin_lng <= 180 and -90 <= origin_lat <= 90):
                continue
            if not (-180 <= dest_lng <= 180 and -90 <= dest_lat <= 90):
                continue

            name = _pick_route_name(row, columns, index)
            color = _color_for(len(result["routes"]))
            props = _make_props(row, columns)
            labels = _prop_labels(props, field_labels)

            # 生成路线（origin -> dest）
            result["routes"].append({
                "name": name,
                "color": color,
                "points": [
                    {"lng": origin_lng, "lat": origin_lat},
                    {"lng": dest_lng, "lat": dest_lat},
                ],
            })

            # 起点标记
            origin_point = {
                "name": f"{name}-起点",
                "lng": origin_lng,
                "lat": origin_lat,
                "routeName": name,
                "color": color,
            }
            if props:
                origin_point["props"] = props
            if labels:
                origin_point["propLabels"] = labels
            result["points"].append(origin_point)

            # 终点标记
            dest_point = {
                "name": f"{name}-终点",
                "lng": dest_lng,
                "lat": dest_lat,
                "routeName": name,
                "color": color,
            }
            if props:
                dest_point["props"] = props
            if labels:
                dest_point["propLabels"] = labels
            result["points"].append(dest_point)

        # 如果有额外的非 origin/dest 坐标对（如 geolocation_lng/lat），也生成标点
        extra_pairs = [p for p in pairs if p["prefix"].lower() not in origin_prefixes
                       and p["prefix"].lower() not in dest_prefixes
                       and p["prefix"] != primary["prefix"]]
        for extra in extra_pairs:
            for index, row in enumerate(rows):
                elng = _to_float(row.get(extra["lng"]))
                elat = _to_float(row.get(extra["lat"]))
                if not (-180 <= elng <= 180 and -90 <= elat <= 90):
                    continue
                extra_name = str(row.get("name", row.get("aircraft_name", f"点位{index+1}")))
                extra_point = {
                    "name": extra_name,
                    "lng": elng,
                    "lat": elat,
                    "routeName": extra_name,
                    "color": _color_for(index),
                }
                extra_props = _make_props(row, columns)
                if extra_props:
                    extra_point["props"] = extra_props
                extra_labels = _prop_labels(extra_props, field_labels)
                if extra_labels:
                    extra_point["propLabels"] = extra_labels
                result["points"].append(extra_point)
        return result

    # 默认标记点（无半径、无轨迹、无 origin+dest）
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
        labels = _prop_labels(props, field_labels)
        if labels:
            point["propLabels"] = labels
        result["points"].append(point)

    return result
