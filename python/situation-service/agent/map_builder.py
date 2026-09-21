"""基于全量数据自动构建地图标注。

复用评估分析（qa-service）_auto_build_map_annotations 的代码智能识别逻辑：
不依赖 LLM 内联样本，而是直接扫描数据列，自动识别经纬度、轨迹、圆形范围，
生成完整 routes/markers/areas + 业务属性（props），使态势图地图达到评估分析的展示效果。

输出结构对齐态势图 map_layer 契约（points/routes/areas/circles）。
"""
import json
import logging
import re

logger = logging.getLogger("situation-service")

# 被排除的列（坐标、标识、排序字段，不需要放入 props）
_EXCLUDE = {
    "name", "aircraft_name", "aircraft_id", "seq", "id",
    "lng", "lon", "longitude", "lat", "latitude", "raw",
    "_dataset",
}

# 途经点 JSON 列名识别：waypoints_json / 途经点 等（内容抽检见 _parse_waypoints）
_WAYPOINT_COLUMN_PATTERN = re.compile(r"(waypoint|途经)", re.IGNORECASE)

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
    "track_name", "route_name", "线路名称", "轨迹名称",
    "flight_no", "flightno", "航班号", "车次", "train_no", "班次",
    "route_id", "routeid", "线路号", "线路编号",
    "no", "code", "number", "编号", "编码", "序号",
    "model", "型号", "机型", "aircraft_model",
    "type", "类型", "类别",
    "id", "aircraft_id", "标识",
)


def _find_waypoint_column(columns):
    """从列名列表中定位途经点 JSON 列（列名含 waypoint/途经），无则返回 None。"""
    for col in columns:
        if _WAYPOINT_COLUMN_PATTERN.search(str(col)):
            return col
    return None


def _parse_waypoints(row, waypoint_key):
    """解析行内途经点 JSON 数组，返回 [{"seq","lng","lat","city"}]（按 seq 升序）。

    元素形态：{"seq":1, "city":"东莞", "lng":113.75, "lat":23.02}；
    无法解析或无合法坐标时返回空列表（调用方退化为起终点两点路线）。
    """
    raw = row.get(waypoint_key)
    if raw in (None, ""):
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    waypoints = []
    for item in data:
        if not isinstance(item, dict):
            continue
        lng = _to_float(item.get("lng", item.get("lon", item.get("longitude"))), None)
        lat = _to_float(item.get("lat", item.get("latitude")), None)
        if lng is None or lat is None:
            continue
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            continue
        waypoints.append({
            "seq": _to_int(item.get("seq"), len(waypoints) + 1),
            "lng": lng,
            "lat": lat,
            "city": str(item.get("city") or item.get("name") or "").strip(),
        })
    waypoints.sort(key=lambda p: p["seq"])
    return waypoints


def _city_pair_name(row, columns_lower):
    """从起终点城市列构造路线名（如「佛山→惠州」），无城市列返回 None。"""
    origin_keys = ("origin_city", "from_city", "start_city", "src_city", "起点城市")
    dest_keys = ("dest_city", "to_city", "end_city", "dst_city", "终点城市")
    origin_city = next((row.get(columns_lower[k]) for k in origin_keys if k in columns_lower), None)
    dest_city = next((row.get(columns_lower[k]) for k in dest_keys if k in columns_lower), None)
    if origin_city and dest_city:
        return f"{origin_city}→{dest_city}"
    return None


def _point_name(row, columns, index):
    """标点名称：显式名称类字段 → 含 city/城市 的字段 → 首个非坐标字符串字段 → 点位N。"""
    cols_lower = {str(k).lower(): k for k in columns}
    for key in ("name", "名称", "title", "label", "city", "城市", "station", "站点", "area", "区域"):
        col = cols_lower.get(key)
        if col is not None:
            value = row.get(col)
            if value not in (None, ""):
                return str(value)[:40]
    for col in columns:
        col_str = str(col)
        if _COORD_PATTERN.search(col_str):
            continue
        if "zip" in col_str.lower() or "邮编" in col_str:
            continue
        value = row.get(col)
        if isinstance(value, str) and value.strip():
            return value.strip()[:40]
    return f"点位{index + 1}"


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


# ────────────────────────────────────────────────────────────────
# 主体主题契约（subject_profiles）通用化层
# ────────────────────────────────────────────────────────────────
# 让 map_builder 按主题数据契约通用识别"航迹表 + 主体档案表 + 能力半径字段"，
# 在运行时按 as_of 时间动态生成能力圈（一架主体一个圈，圆心随主体当前位置移动）。
# 新增主题（船舰/车辆）只需在 subject_profiles.yaml 加 profile + mock 表，不改本文件。

_SUBJECT_PROFILES_CACHE = None


def load_subject_profiles():
    """加载 subject_profiles.yaml 缓存（首次调用读取，后续返回缓存）。"""
    global _SUBJECT_PROFILES_CACHE
    if _SUBJECT_PROFILES_CACHE is not None:
        return _SUBJECT_PROFILES_CACHE
    import os
    import yaml  # type: ignore
    yaml_path = os.path.join(os.path.dirname(__file__), "subject_profiles.yaml")
    if not os.path.exists(yaml_path):
        _SUBJECT_PROFILES_CACHE = {}
        return _SUBJECT_PROFILES_CACHE
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            profiles = yaml.safe_load(f) or {}
        _SUBJECT_PROFILES_CACHE = profiles if isinstance(profiles, dict) else {}
    except Exception as e:
        logger.warning(f"加载 subject_profiles.yaml 失败: {e}")
        _SUBJECT_PROFILES_CACHE = {}
    return _SUBJECT_PROFILES_CACHE


def resolve_profile(rows, dataset_meta=None):
    """按 dataset 元数据匹配 subject profile。

    dataset_meta 期望含 table_name 字段；与 profile 中 track_table 或
    enemy_track_table 对比。未匹配返回 None（走旧通用识别兜底）。
    """
    if not dataset_meta:
        return None
    table_name = ""
    if isinstance(dataset_meta, dict):
        table_name = (dataset_meta.get("table_name")
                      or dataset_meta.get("tableName")
                      or dataset_meta.get("name")
                      or "")
    table_name = str(table_name).lower()
    if not table_name:
        return None
    profiles = load_subject_profiles()
    for key, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        track_table = str(profile.get("track_table") or "").lower()
        enemy_table = str(profile.get("enemy_track_table") or "").lower()
        if table_name == track_table or table_name == enemy_table:
            return {**profile, "_profile_key": key}
    return None


def _interpolate_track_position(track_pts, target_time):
    """在按时间排序的航迹点中，二分定位 target_time 的位置线性插值。

    track_pts: [{time, lng, lat}, ...] 已按 time 升序排序
    target_time: datetime
    返回: (lng, lat) 或 None（target_time 早于航迹开始或晚于结束）
    """
    if not track_pts:
        return None
    import bisect
    from datetime import datetime as _dt
    if not isinstance(target_time, _dt):
        return None
    times = [p["time"] for p in track_pts]
    idx = bisect.bisect_right(times, target_time) - 1
    if idx < 0:
        return None  # 未出动
    if idx >= len(track_pts) - 1:
        return None  # 已返航/已结束
    p1 = track_pts[idx]
    p2 = track_pts[idx + 1]
    if p2["time"] == p1["time"]:
        return (p1["lng"], p1["lat"])
    frac = ((target_time - p1["time"]).total_seconds()
            / (p2["time"] - p1["time"]).total_seconds())
    frac = max(0.0, min(1.0, frac))
    return (p1["lng"] + (p2["lng"] - p1["lng"]) * frac,
            p1["lat"] + (p2["lat"] - p1["lat"]) * frac)


def _color_for_subject(faction):
    """按阵营取能力圈颜色（红/蓝差异化，通用主题也能用）。"""
    faction = (faction or "").strip()
    if faction == "蓝方":
        return "#3498db"
    if faction == "红方":
        return "#e74c3c"
    return "#9b59b6"  # 默认紫色（未知阵营）


def build_dynamic_capability_circles(rows, profile, as_of=None):
    """按 profile 识别航迹表 + 档案字段，按 as_of 时间动态生成能力圈。

    一架主体一个圈（每种 radius 字段一圈），圆心 = 主体在 as_of 时间的位置
    （航迹线性插值）；半径来自档案表的 radius 字段值。
    主体在 as_of 时点未出动或已返航则不画圈。
    输出严格等于"当时在空主体数 × radius 字段数"。

    前置条件：上游负责按 profile 把航迹表 JOIN 主体档案表 JOIN 机型档案表
    的合并数据传给本函数；如果 rows 没含档案字段则返回 []（兜底跳过）。
    """
    if not rows or not profile or not as_of:
        return []

    join_key = profile.get("join_key", "aircraft_id")
    time_field = profile.get("time_field", "record_time")
    lng_field = profile.get("track_lng", "track_lng")
    lat_field = profile.get("track_lat", "track_lat")
    subject_name_field = profile.get("subject_name", "callsign")
    faction_field = profile.get("faction_field", "faction")
    radius_source = profile.get("radius_source") or {}
    radius_fields = radius_source.get("fields") or []

    if not rows or not isinstance(rows[0], dict):
        return []
    if join_key not in rows[0]:
        return []
    # 仅当 rows 同时含档案表的 radius 字段时启用（上游负责 JOIN）
    available_radius_fields = [rf for rf in radius_fields if rf["field"] in rows[0]]
    if not available_radius_fields:
        return []

    from collections import defaultdict
    from datetime import datetime as _dt

    groups = defaultdict(list)
    subject_meta = {}
    for row in rows:
        sid = str(row.get(join_key, ""))
        if not sid:
            continue
        t_raw = row.get(time_field)
        if isinstance(t_raw, _dt):
            t_val = t_raw
        elif t_raw:
            try:
                t_val = _dt.strptime(str(t_raw), "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
        else:
            continue
        lng = _to_float(row.get(lng_field))
        lat = _to_float(row.get(lat_field))
        if lng is None or lat is None:
            continue
        groups[sid].append({"time": t_val, "lng": lng, "lat": lat})
        if sid not in subject_meta:
            radii = {}
            for rf in available_radius_fields:
                v = _to_float(row.get(rf["field"]))
                if v and v > 0:
                    radii[rf["field"]] = v
            subject_meta[sid] = {
                "name": str(row.get(subject_name_field, sid)),
                "faction": str(row.get(faction_field, "")),
                "radii": radii,
            }

    circles = []
    for sid, track_pts in groups.items():
        track_pts.sort(key=lambda p: p["time"])
        pos = _interpolate_track_position(track_pts, as_of)
        if pos is None:
            continue
        meta = subject_meta.get(sid, {})
        for rf in available_radius_fields:
            r = meta["radii"].get(rf["field"])
            if not r or r <= 0:
                continue
            circles.append({
                "name": f"{meta.get('name', sid)}·{rf.get('range_type', '能力范围')}",
                "center": {"lng": pos[0], "lat": pos[1]},
                "radiusKm": r,
                "subjectId": sid,
                "timestamp": as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
                "color": _color_for_subject(meta.get("faction", "")),
                "props": {
                    "faction": meta.get("faction", ""),
                    "range_type": rf.get("range_type", ""),
                    "subject_id": sid,
                    "subject_name": meta.get("name", sid),
                },
            })
    return circles


def build_map_annotations(rows, field_labels=None, profile=None, as_of=None):
    """扫描数据行，自动构建地图标注 dict。

    field_labels: 可选 {英文字段名: 中文标签}，来自数据集元数据（businessMeaning/comment）。
                 提供后每个 point/circle 会附带 propLabels，前端据此直接显示中文字段名。

    profile: 可选 subject_profile（来自 subject_profiles.yaml，由 resolve_profile 匹配）。
             命中且 rows 含档案 radius 字段时，按 as_of 时间动态生成能力圈
             （一架主体一个圈，圆心随主体当前位置移动）。
    as_of: datetime，时间轴切片点。profile 命中时用于航迹位置插值。

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
        # 按 (飞机, 架次) 分组：同一架飞机多个架次必须拆成独立航迹，否则跨架次的
        # 航迹点会按 seq 交错连线，两条几乎重合的航线被连成一条"辫子"
        has_mid = "mission_id" in cols_lower
        time_key = cols_lower.get("record_time")
        groups = {}
        for row in rows:
            gid = str(row.get(id_key, ""))
            sortie = str(row.get("mission_id") or "") if has_mid else ""
            key = (gid, sortie)
            if key not in groups:
                groups[key] = {
                    "aircraft": gid,
                    "name": str(row.get(name_key, gid)),
                    "sortie": str(row.get(time_key) or sortie or "") if time_key else sortie,
                    "points": [],
                }
            groups[key]["points"].append({
                "seq": _to_int(row.get("seq")),
                "lng": _to_float(row.get(lng_key)),
                "lat": _to_float(row.get(lat_key)),
                "row": row,
            })

        # 同一架飞机存在多个架次时，航迹名后缀架次时间，便于地图上区分
        sortie_count = {}
        for (gid, _sortie) in groups:
            sortie_count[gid] = sortie_count.get(gid, 0) + 1

        for (gid, _sortie), group in groups.items():
            points = sorted(group["points"], key=lambda p: p["seq"])
            color = _color_for(len(result["routes"]))
            route_name = group["name"]
            if sortie_count[gid] > 1:
                route_name = f"{group['name']}·{group['sortie'][:16] or '架次'}"
            result["routes"].append({
                "name": route_name,
                "color": color,
                "points": [{"lng": p["lng"], "lat": p["lat"]} for p in points],
            })
            for index, pt in enumerate(points):
                if index == 0:
                    label = route_name + "-起点"
                elif index == len(points) - 1:
                    label = route_name + "-终点"
                else:
                    label = route_name + f"-途经{index}"
                point = {
                    "name": label,
                    "lng": pt["lng"],
                    "lat": pt["lat"],
                    "routeName": route_name,
                    "color": color,
                }
                props = _make_props(pt["row"], columns)
                if props:
                    point["props"] = props
                labels = _prop_labels(props, field_labels)
        if labels:
            point["propLabels"] = labels
        result["points"].append(point)

    # 检查是否存在 origin+dest 配对（常用于物流/运输数据）
    origin_prefixes = {"origin", "起点", "from", "start", "src"}
    dest_prefixes = {"dest", "destination", "终点", "to", "end", "dst"}

    origin_pair = next((p for p in pairs if p["prefix"].lower() in origin_prefixes), None)
    dest_pair = next((p for p in pairs if p["prefix"].lower() in dest_prefixes), None)

    if origin_pair and dest_pair:
        # 途经点 JSON 列（如 waypoints_json）：存在时展开为 起点→途经→终点 的多点折线
        waypoint_key = _find_waypoint_column(columns)
        cols_lower = {str(k).lower(): k for k in columns}

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
            # 兜底命名：起终点城市对（如「佛山→惠州」）优于「路线N」
            if name == f"路线{index + 1}":
                name = _city_pair_name(row, cols_lower) or name
            color = _color_for(len(result["routes"]))
            props = _make_props(row, columns)
            labels = _prop_labels(props, field_labels)

            # 途经点展开：起点 → 途经点（seq 升序）→ 终点，相邻重复坐标去重
            waypoints = _parse_waypoints(row, waypoint_key) if waypoint_key else []
            route_points = [{"lng": origin_lng, "lat": origin_lat}]
            for wp in waypoints:
                pt = {"lng": wp["lng"], "lat": wp["lat"]}
                if pt != route_points[-1]:
                    route_points.append(pt)
            dest_pt = {"lng": dest_lng, "lat": dest_lat}
            if dest_pt != route_points[-1]:
                route_points.append(dest_pt)

            # 生成路线
            result["routes"].append({
                "name": name,
                "color": color,
                "points": route_points,
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

            # 途经点标记（城市名可用时直接作为标点名）
            for wp in waypoints:
                waypoint_point = {
                    "name": wp["city"] or f"{name}-途经",
                    "lng": wp["lng"],
                    "lat": wp["lat"],
                    "routeName": name,
                    "color": color,
                }
                if wp["city"]:
                    waypoint_point["props"] = {"city": wp["city"]}
                result["points"].append(waypoint_point)

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
                extra_name = _point_name(row, columns, index)
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
        name = _point_name(row, columns, index)
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

    # 主体主题契约命中时，按 as_of 时间动态生成能力圈
    # （一架主体一个圈，圆心随主体当前位置移动；上游需 JOIN 档案表数据）
    if profile and as_of:
        dynamic_circles = build_dynamic_capability_circles(rows, profile, as_of)
        if dynamic_circles:
            result["circles"].extend(dynamic_circles)

    return result
