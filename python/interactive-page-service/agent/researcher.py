"""Researcher —— 取数智能体（Text-to-SQL + 脱敏 + 采样 + 地理特征整形）。

每个 subQuestion 一个取数单元，可并行执行：
1. 物理表结构 → LLM 生成只读 SELECT（aggregate 聚合 / detail 明细保真）
2. admin-service 执行；失败回退整表查询
3. 敏感列脱敏、长文本截断、行数上限
4. 经纬度字段识别，预整形为 SitMap 直接可用的 geoFeatures（tracks/points/circles），
   地图点按上限均匀抽稀
5. 确定性统计摘要，供 PageWriter 理解数据形态
"""
import datetime as dt
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import config
import cache_registry
from llm_client import call_llm_json
from agent import prompts
from agent import field_resolver
from agent.dimension_graph import DimensionGraph
from agent.field_resolver import FieldResolver, build_resolver
from store import admin_client

logger = logging.getLogger("ipage-service")

# 长文本列截断长度（防止超长 JSON/备注撑爆数据包）
_MAX_TEXT_LEN = 200
# 单条航迹抽稀后的点数上限
_MAX_POINTS_PER_TRACK = 240

# 列名启发式（③ 层）统一由 field_resolver 承载；此处保留旧名以兼容既有调用点与测试，
# 行为与改造前逐字一致（注解缺失时它就是唯一判据）。
_find_coord_pairs = field_resolver.find_coord_pairs
_find_field = field_resolver.find_field
_find_time_field = field_resolver.find_time_field
_radius_kind = field_resolver.radius_kind
_UNIT_KIND_BY_TABLE = field_resolver.UNIT_KIND_BY_TABLE

# 机型/飞机档案索引缓存（key=数据源标识）：跨子问题复用，避免重复拉取小档案表
_aircraft_index_cache: Dict[str, Dict[str, Any]] = {}


# ──────────────────────────────────────────────────────────────────
# 基础工具
# ──────────────────────────────────────────────────────────────────

def _is_sensitive(column: str, dataset_sensitive: set) -> bool:
    """判断列是否敏感：数据集标注优先，再匹配全局敏感词。"""
    normalized = str(column or "").strip().lower().replace("-", "_")
    if normalized in dataset_sensitive:
        return True
    return any(token in normalized for token in config.IPAGE_SENSITIVE_COLUMNS)


def _safe_scalar(value: Any) -> Any:
    """清洗单元格值：标量保留，长文本截断，复合结构转 JSON 字符串后截断。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat(sep=" ")
    text = str(value)
    return text[:_MAX_TEXT_LEN] + ("…" if len(text) > _MAX_TEXT_LEN else "")


def _sanitize_rows(rows: List[Dict[str, Any]], columns: List[str],
                   dataset_sensitive: set) -> List[Dict[str, Any]]:
    """剔除敏感列并清洗单元格。"""
    keep = [c for c in columns if not _is_sensitive(c, dataset_sensitive)]
    cleaned = []
    for row in rows:
        cleaned.append({c: _safe_scalar(row.get(c)) for c in keep})
    return cleaned


def _extract_rows_columns(payload: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """从 admin 不同端点响应中抽取 columns/rows。"""
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], []
    dict_rows = [r for r in rows if isinstance(r, dict)]
    columns = payload.get("columns")
    if isinstance(columns, list) and columns:
        cols = [str(c) for c in columns]
    else:
        cols = list(dict.fromkeys(k for r in dict_rows for k in r.keys()))
    return cols, dict_rows


def _apply_entity_scope(rows: List[Dict[str, Any]], columns: List[str],
                        scope: Dict[str, set]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """对原始数据行应用实体白名单确定性过滤（在脱敏/截断之前执行）。

    scope: {列名: 允许值集合}，多列之间为 AND 语义；scope 中不存在于本行结果集
    的列自动忽略（避免不同端点列名差异导致误清空）。

    Returns:
        (过滤后行, 实际生效的 {列: 允许值数量})。
    """
    if not scope:
        return rows, {}
    active = {col: ids for col, ids in scope.items()
              if col in columns and ids}
    if not active:
        return rows, {}
    kept = [
        r for r in rows
        if all(("" if r.get(col) is None else str(r.get(col))) in ids
               for col, ids in active.items())
    ]
    return kept, {col: len(ids) for col, ids in active.items()}


# ──────────────────────────────────────────────────────────────────
# 地理字段识别与特征整形
# ──────────────────────────────────────────────────────────────────

def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _thin_indices(total: int, limit: int) -> List[int]:
    """均匀抽稀索引：保留首末点，中间等间隔取样。"""
    if total <= limit:
        return list(range(total))
    if limit <= 2:
        return [0, total - 1][:limit]
    step = (total - 1) / (limit - 1)
    indices = sorted({int(round(i * step)) for i in range(limit)})
    return indices


def _ordered_key(value: Any) -> Tuple[int, float, str]:
    """航迹点排序键：空值排最后；数值型（如 seq=0,1,2,...,10）按数值排，
    避免字符串排序把 10 排到 2 前面导致航迹点序错乱、连线成方框；
    非数值（如 ISO 时间字符串）回退字典序（ISO 格式字典序即时间序）。"""
    if value is None:
        return (1, 0.0, "")
    num = _to_float(value)
    if num is not None:
        return (0, num, "")
    return (0, 0.0, str(value))


def _pick_coord_pair(pairs: List[Tuple[str, str, str]], prefer_prefixes: Tuple[str, ...] = ()) -> Optional[Tuple[str, str]]:
    """按偏好前缀挑选坐标对（航迹优先 track 前缀）。"""
    if not pairs:
        return None
    for prefer in prefer_prefixes:
        for prefix, lng, lat in pairs:
            if prefix == prefer:
                return lng, lat
    for prefix, lng, lat in pairs:
        if "track" in prefix:
            return lng, lat
    return pairs[0][1], pairs[0][2]


def _meta_database_key(meta: Dict[str, Any]) -> str:
    """从元数据中取数据源标识（缓存键）。"""
    if not isinstance(meta, dict):
        return "default"
    data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
    return str(data.get("databaseId") or meta.get("databaseId") or "default")


def _find_dataset_id(meta: Dict[str, Any], table_name: str) -> str:
    """按物理表名在元数据中查数据集 id。"""
    for schema in (meta.get("data", {}) or {}).get("schemas", []) if isinstance(meta, dict) else []:
        if isinstance(schema, dict) and str(schema.get("tableName") or "") == table_name:
            return str(schema.get("datasetId") or schema.get("id") or "")
    return ""


def load_aircraft_index(meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """拉取飞机档案 + 机型档案，构建 aircraftId → 阵营/机型类别/定值半径索引。

    侦察/打击半径是机型固有定值（不随时间变化），航迹位置移动牵动覆盖范围，
    因此航迹整形时通过本索引补全 faction/category/strikeRadiusKm/reconRadiusKm。
    该函数仅作为「通用维度 enrich」不可用时的兜底路径，表名不通用。
    """
    cache_key = _meta_database_key(meta)
    if cache_key in _aircraft_index_cache:
        return _aircraft_index_cache[cache_key]

    index: Dict[str, Dict[str, Any]] = {}
    try:
        ac_ds = _find_dataset_id(meta, "mock_aircraft")
        type_ds = _find_dataset_id(meta, "mock_aircraft_type")
        if not ac_ds:
            _aircraft_index_cache[cache_key] = index
            return index

        ac_payload = admin_client.query_dataset_full(ac_ds, 500)
        _, ac_rows = _extract_rows_columns(ac_payload) if ac_payload.get("success") else ([], [])
        type_map: Dict[str, Dict[str, Any]] = {}
        if type_ds:
            tp = admin_client.query_dataset_full(type_ds, 200)
            _, type_rows = _extract_rows_columns(tp) if tp.get("success") else ([], [])
            for t in type_rows:
                type_map[str(t.get("type_id") or "")] = t

        for r in ac_rows:
            acid = str(r.get("aircraft_id") or "")
            if not acid:
                continue
            t = type_map.get(str(r.get("type_id") or ""), {})
            index[acid] = {
                "faction": str(r.get("faction") or t.get("faction") or ""),
                "category": str(t.get("category") or ""),
                "typeId": str(r.get("type_id") or ""),
                "strikeRadiusKm": _to_float(t.get("strike_radius_km")),
                "reconRadiusKm": _to_float(t.get("recon_radius_km")),
                "callsign": str(r.get("callsign") or ""),
            }
    except Exception as exc:  # 档案 enrich 为增强能力，失败不阻断取数
        logger.warning("机型档案索引构建失败，航迹使用兜底语义: %s", exc)

    _aircraft_index_cache[cache_key] = index
    return index


# 通用维度 enrich 缓存：key=(数据源标识, 事实表名)
_entity_enrich_cache: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}


def clear_aircraft_index(database_id: Optional[str] = None,
                         tables: Optional[List[str]] = None) -> int:
    """清理机型/飞机档案索引。

    该索引按数据源整体缓存（键只有数据源标识），无法按表精确清理，
    因此按数据源整体失效；重建代价仅两张小档案表的查询。
    """
    removed = 0
    for key in list(_aircraft_index_cache):
        if database_id and key != database_id:
            continue
        _aircraft_index_cache.pop(key, None)
        removed += 1
    return removed


def clear_entity_enrich(database_id: Optional[str] = None,
                        tables: Optional[List[str]] = None) -> int:
    """清理通用维度 enrich 索引（键为 (数据源标识, 事实表名)，可按表精确清理）。"""
    wanted = {str(t) for t in (tables or []) if t}
    removed = 0
    for key in list(_entity_enrich_cache):
        db_key, fact_table = key
        if database_id and db_key != database_id:
            continue
        if wanted and fact_table not in wanted:
            continue
        _entity_enrich_cache.pop(key, None)
        removed += 1
    return removed


cache_registry.register_cache("researcher.aircraft_index", clear_aircraft_index)
cache_registry.register_cache("researcher.entity_enrich", clear_entity_enrich)

# 语义字段识别用的元结构词（描述列用途，不是业务词）
_ENRICH_CATEGORY_TOKENS = ("类别", "类型", "分类", "种类")
_ENRICH_FACTION_TOKENS = ("阵营",)


def _is_number_text(text: str) -> bool:
    """文本是否为纯数字/小数（数值列不得误作类别）。"""
    try:
        float(str(text).strip())
        return True
    except (TypeError, ValueError):
        return False


def _semantic_index_entry(graph: DimensionGraph, own_table: str,
                          flat_row: Dict[str, Any]) -> Dict[str, Any]:
    """从合并后的关联行中按字段语义抽取标准索引项。

    输出形状与 load_aircraft_index 单项对齐：
    {faction, category, typeId, strikeRadiusKm, reconRadiusKm, callsign}。
    二跳表字段在 flat_row 中以 "表名.列名" 存储，一跳表字段为裸列名。
    半径按字段语义分流：打击半径（strike_radius）与侦察半径（recon_radius/detect_radius）；
    注解优先：字段角色 ``role=radius`` 或业务含义含"半径"的列同样参与分流，
    类型由列名与业务含义共同判定（"打击半径"/"侦察半径"等中文列名可命中）。
    无法判定语义的裸 radius 列不参与动态能力圈，避免给通用数据源凭空造出"打击范围"。
    """
    entry: Dict[str, Any] = {
        "faction": "", "category": "", "typeId": "",
        "strikeRadiusKm": None, "reconRadiusKm": None, "callsign": "",
    }
    for key, val in flat_row.items():
        if val is None:
            continue
        src_table, col = (key.split(".", 1) + [""])[:2] if "." in key else (own_table, key)
        spec = graph.tables.get(src_table)
        meaning = ""
        role = ""
        if spec and col in spec.columns:
            meaning = str(spec.columns[col].get("meaning") or "")
            role = str((spec.columns[col].get("semantic") or {}).get("role") or "").strip()
        low = str(col).lower()
        text = str(val).strip()
        if not text:
            continue
        if not entry["category"] and len(text) <= 10 and not _is_number_text(text) and (
            any(tok in meaning for tok in _ENRICH_CATEGORY_TOKENS)
            or low in ("category", "type_name", "class", "kind")
        ):
            entry["category"] = text
        if not entry["faction"] and (
            any(tok in meaning for tok in _ENRICH_FACTION_TOKENS)
            or low in ("faction", "camp", "side")
        ):
            entry["faction"] = text
        if not entry["typeId"] and low == "type_id":
            entry["typeId"] = text
        # 半径语义：列名线索 或 注解角色/业务含义（中文"打击半径"可命中）
        radius_like = ("radius" in low or role == "radius" or "半径" in meaning)
        if radius_like:
            is_strike = ("strike" in low or "打击" in meaning or "攻击" in meaning)
            is_recon = ("recon" in low or "detect" in low or "scout" in low or "search" in low
                        or "侦察" in meaning or "探测" in meaning or "搜索" in meaning)
            if is_strike and entry["strikeRadiusKm"] is None:
                entry["strikeRadiusKm"] = _to_float(val)
            elif is_recon and entry["reconRadiusKm"] is None:
                entry["reconRadiusKm"] = _to_float(val)
            # 两类线索都没有（裸 radius_km）→ 不参与，保持历史行为
        if not entry["callsign"] and "callsign" in low:
            entry["callsign"] = text
    # callsign 回退：一跳表的通用名称列
    if not entry["callsign"]:
        for name_col in ("callsign", "name", "title", "label"):
            val = flat_row.get(name_col)
            if val:
                entry["callsign"] = str(val)
                break
    return entry


def load_entity_enrich_index(meta: Dict[str, Any], fact_table: str) -> Dict[str, Dict[str, Any]]:
    """通用维度档案 enrich（不硬编码任何业务表名）。

    沿事实表的外键边自动预加载 1-2 跳关联档案表（如 航迹→实体档案→类型档案），
    合并后按字段语义（businessMeaning/列名）抽取阵营/类别/定值半径/名称，
    产出与 load_aircraft_index 相同形状的索引供地图符号与图例使用。

    无外键关系、无元数据或加载失败时返回 {}，由调用方回退专用索引。
    """
    cache_key = (_meta_database_key(meta), str(fact_table or ""))
    if cache_key in _entity_enrich_cache:
        return _entity_enrich_cache[cache_key]

    index: Dict[str, Dict[str, Any]] = {}
    try:
        graph = DimensionGraph.build(meta)
        if graph is not None and fact_table in graph.tables:
            for fk_col, (ref_t, ref_c) in (graph.edges.get(fact_table) or {}).items():
                spec1 = graph.tables.get(ref_t)
                if spec1 is None:
                    continue
                p1 = admin_client.query_dataset_full(spec1.dataset_id, 500)
                if not p1.get("success"):
                    continue
                _, rows1 = _extract_rows_columns(p1)
                # 二跳档案：把关联行字段以 "表名.列名" 平铺进一跳行
                for fk2, (ref2, ref_c2) in (graph.edges.get(ref_t) or {}).items():
                    spec2 = graph.tables.get(ref2)
                    if spec2 is None:
                        continue
                    p2 = admin_client.query_dataset_full(spec2.dataset_id, 500)
                    if not p2.get("success"):
                        continue
                    _, rows2 = _extract_rows_columns(p2)
                    idx2 = {str(r.get(ref_c2)): r for r in rows2
                            if isinstance(r, dict) and r.get(ref_c2) is not None}
                    for r in rows1:
                        parent = idx2.get(str(r.get(fk2)))
                        if parent:
                            for k2, v2 in parent.items():
                                r[f"{ref2}.{k2}"] = v2
                for r in rows1:
                    key_val = str(r.get(ref_c) or "")
                    if key_val:
                        index[key_val] = _semantic_index_entry(graph, ref_t, r)
    except Exception as exc:  # 通用 enrich 为增强能力，失败回退专用索引
        logger.warning("通用维度 enrich 失败 fact=%s: %s", fact_table, exc)
        index = {}

    _entity_enrich_cache[cache_key] = index
    return index


def build_geo_features(rows: List[Dict[str, Any]], columns: List[str],
                       geo_kind_hint: str, table_name: str = "",
                       aircraft_index: Optional[Dict[str, Dict[str, Any]]] = None,
                       resolver: Optional[FieldResolver] = None) -> Dict[str, Any]:
    """把明细行预整形为 SitMap 直接消费的地理特征。

    resolver 为字段解析器（注解优先、业务含义文本次之、列名启发式兜底）。
    不传时按"无注解"构造 —— 输出与改造前逐字一致（零回归的构造性保证）。

    Returns:
        {"kind": "tracks|points|circles|none", "tracks": [], "points": [], "circles": []}
    """
    table = str(table_name or "").lower()
    resolver = resolver or FieldResolver(None, columns, table_name)
    table_unit_kind = resolver.unit_kind()
    aircraft_index = aircraft_index or {}
    empty = {"kind": "none", "tracks": [], "points": [], "circles": [], "units": []}
    # 坐标：注解 geometry 优先并**整体替换**候选，避免误配到同表的其它坐标前缀
    annotated_pair = resolver.annotated_coord_pair()
    pairs = ([("", annotated_pair[0], annotated_pair[1])] if annotated_pair
             else _find_coord_pairs(columns))
    if not pairs:
        return empty

    seq_field = resolver.seq_column()
    time_field = resolver.event_time_column()
    mission_field = _find_field(columns, ("mission_id", "mission"))
    alt_field = resolver.altitude_column()
    speed_field = resolver.speed_column()
    heading_field = resolver.heading_column()
    name_fields = [
        c for c in columns
        if any(tok in str(c).lower()
               for tok in ("name", "callsign", "aircraft", "目标", "名称", "呼号"))
    ]
    # 敌机编号优先于通用 aircraft_id，避免分组落到错误列
    id_field = _find_field(columns, ("enemy_aircraft_id", "aircraft_id", "target_id",
                                     "threat_id", "range_id", "id"))
    name_field = _find_field(columns, ("enemy_aircraft_name", "aircraft_name", "callsign",
                                       "threat_name", "target_name", "base_name", "name",
                                       "呼号", "名称"))
    type_field = resolver.type_column(
        _find_field(columns, ("threat_type", "category", "range_type",
                              "damage_type", "weapon_type", "type", "kind")))
    status_field = resolver.status_column(_find_field(columns, ("hit_result", "status", "severity")))
    kind_field = _find_field(columns, ("type", "category", "kind", "threat_level"))
    faction_column = resolver.faction_column()
    # 象形符号：字段注解 symbol 优先，其次数据集 symbolDefault；无注解返回空（前端走原推断）
    symbol_hint = resolver.symbol(type_field or "")

    def resolve_faction(row: Dict[str, Any], acid: str = "") -> Tuple[str, str]:
        """阵营解析：注解值映射优先，兜底行值 → 飞机档案索引 → 表名（enemy 表为敌方=蓝方）。"""
        return resolver.faction_of(row, column=faction_column,
                                   fallback_unit="蓝方" if "enemy" in table else "",
                                   aircraft_index=aircraft_index, track_id=acid)

    def attach_faction(item: Dict[str, Any], row: Dict[str, Any], acid: str = "") -> Dict[str, Any]:
        """写入阵营；颜色仅在由注解值映射推导时出现（无注解时字段不出现，保证零回归）。"""
        faction, color = resolve_faction(row, acid)
        item["faction"] = faction
        if color:
            item["factionColor"] = color
        return item

    def attach_symbol(item: Dict[str, Any]) -> Dict[str, Any]:
        """写入象形符号键（仅注解命中时出现）。"""
        if symbol_hint:
            item["symbol"] = symbol_hint
        return item

    def attach_status_key(item: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
        """写入状态规范键（仅注解值映射命中运行时段时出现）。"""
        if status_field:
            key = resolver.status_key(status_field, row.get(status_field))
            if key:
                item["statusKey"] = key
        return item

    hint = geo_kind_hint if geo_kind_hint in ("tracks", "points", "circles") else "points"

    # ── 范围圈：静态阵地/目标的固定范围圈 ──
    # 一表可含多根半径列（探测/侦察 + 打击），每根半径各自成圈、类型与半径严格配对；
    # 同时输出圆心处的单位符号，避免地图上只剩一个"孤零零的圈"。
    radius_cols = resolver.radius_columns()
    if hint == "circles" and radius_cols:
        circles = []
        circle_units = []
        for row in rows:
            pair = _pick_coord_pair(pairs)
            if not pair:
                continue
            lng, lat = _to_float(row.get(pair[0])), _to_float(row.get(pair[1]))
            if lng is None or lat is None:
                continue
            name = str(row.get(name_field) or
                       (row.get(name_fields[0]) if name_fields else "") or "")
            faction, faction_color = resolve_faction(row)
            row_range_type = str(row.get("range_type") or "")
            multi_radius = len(radius_cols) > 1
            for rc in radius_cols:
                radius = _to_float(row.get(rc))
                if radius is None or radius <= 0:
                    continue
                col_kind = resolver.radius_kind_of(rc)
                if col_kind:
                    # 列名/注解已说明半径含义 → 类型随列走，不再被别的半径列带偏
                    kind = col_kind
                    range_type = "打击范围" if kind == "strike" else "侦察范围"
                else:
                    # 无线索（如单一 radius_km）→ 沿用 range_type 列判定，兜底侦察圈
                    kind = "strike" if "打击" in row_range_type else "recon"
                    range_type = row_range_type or ("打击范围" if kind == "strike" else "侦察范围")
                circle = {
                    "lng": lng, "lat": lat, "radiusKm": radius,
                    # 多根半径时圈名加范围后缀，便于图例/弹窗区分（探测一个、打击一个）
                    "name": (name + "·" + range_type) if multi_radius else name,
                    "faction": faction,
                    "rangeType": range_type,
                    "kind": kind,
                }
                if faction_color:
                    circle["factionColor"] = faction_color
                circles.append(circle)
            if table_unit_kind:
                unit = {
                    "lng": lng, "lat": lat, "name": name, "unitKind": table_unit_kind,
                    "type": str(row.get(type_field) or "") if type_field else "",
                    "status": str(row.get(status_field) or "") if status_field else "",
                }
                attach_symbol(unit)
                attach_faction(unit, row)
                attach_status_key(unit, row)
                circle_units.append(unit)
        if circles:
            limit = config.IPAGE_MAP_POINT_LIMIT
            return {"kind": "circles", "tracks": [], "points": [],
                    "units": circle_units[:limit], "circles": circles[:limit]}

    # ── 航迹：按(实体,任务)分组 + seq/time 排序 + 每航迹抽稀 ──
    # 同一飞机多个任务必须按 mission 拆成独立航迹，否则跨任务点会交叉连线
    if hint == "tracks":
        pair = _pick_coord_pair(pairs, ("track",))
        # 拆分键：注解 trackGroupKey 优先（须全部命中），否则历史口径（实体列 + 任务列）
        group_cols = resolver.track_group_columns(
            id_field, mission_field, name_fields[0] if name_fields else None)
        if pair and group_cols:
            lng_field, lat_field = pair
            groups: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
            for row in rows:
                lng, lat = _to_float(row.get(lng_field)), _to_float(row.get(lat_field))
                if lng is None or lat is None:
                    continue
                key = tuple(str(row.get(col) or "") for col in group_cols)
                groups.setdefault(key, []).append(row)
            tracks = []
            lone_points = []
            point_budget = config.IPAGE_MAP_POINT_LIMIT
            per_track = max(20, min(_MAX_POINTS_PER_TRACK,
                                    point_budget // max(1, len(groups))))
            total_points = 0
            for key, group_rows in groups.items():
                # 首列为实体标识（无值时与历史一致记作未知目标），其余列为任务维度
                acid = key[0] or "未知目标"
                mission = "|".join(part for part in key[1:] if part)
                sort_field = seq_field or time_field
                if sort_field:
                    # 数值字段必须按数值排序：字符串排序会使 seq 10 排到 2 前，
                    # 整条航迹点序错乱、被连成分叉方框
                    group_rows = sorted(group_rows,
                                        key=lambda r: _ordered_key(r.get(sort_field)))
                # 不足 2 点不构成航迹，作为飞机位置点标注
                if len(group_rows) < 2:
                    r0 = group_rows[0]
                    lone = {
                        "lng": _to_float(r0.get(lng_field)), "lat": _to_float(r0.get(lat_field)),
                        "name": str(r0.get(name_field) or acid) if name_field else acid,
                        "kind": "aircraft", "unitKind": "aircraft",
                        "type": aircraft_index.get(acid, {}).get("category") or "",
                        "time": str(r0.get(time_field)) if time_field and r0.get(time_field) is not None else None,
                    }
                    attach_symbol(lone)
                    attach_faction(lone, r0, acid)
                    attach_status_key(lone, r0)
                    lone_points.append(lone)
                    continue
                indices = _thin_indices(len(group_rows), per_track)
                points = []
                for i in indices:
                    r = group_rows[i]
                    props = {k: v for k, v in r.items()
                             if k not in (lng_field, lat_field)}
                    points.append({
                        "lng": _to_float(r.get(lng_field)),
                        "lat": _to_float(r.get(lat_field)),
                        "seq": r.get(seq_field) if seq_field else None,
                        "time": str(r.get(time_field)) if time_field and r.get(time_field) is not None else None,
                        "alt": r.get(alt_field) if alt_field else None,
                        "speed": r.get(speed_field) if speed_field else None,
                        "heading": r.get(heading_field) if heading_field else None,
                        "props": props,
                    })
                name = acid
                if name_field:
                    for r in group_rows:
                        if r.get(name_field):
                            name = str(r.get(name_field))
                            break
                ac_meta = aircraft_index.get(acid, {})
                track = {
                    "id": acid,
                    "name": name,
                    "category": ac_meta.get("category") or "",
                    "missionId": mission,
                    "strikeRadiusKm": ac_meta.get("strikeRadiusKm"),
                    "reconRadiusKm": ac_meta.get("reconRadiusKm"),
                    "points": points,
                }
                attach_symbol(track)
                attach_faction(track, group_rows[0], acid)
                attach_status_key(track, group_rows[0])
                tracks.append(track)
                total_points += len(points)
                if total_points >= point_budget:
                    break
            if tracks:
                return {"kind": "tracks", "tracks": tracks, "points": lone_points,
                        "units": lone_points, "circles": []}

    # ── 单位点标注（tracks 条件不满足时也回落到此）──
    pair = _pick_coord_pair(pairs, ("event", "home", ""))
    if not pair:
        pair = _pick_coord_pair(pairs)
    lng_field, lat_field = pair
    points = []
    seen = set()  # 基地等档案表多行同坐标去重
    for row in rows:
        lng, lat = _to_float(row.get(lng_field)), _to_float(row.get(lat_field))
        if lng is None or lat is None:
            continue
        # 基地语义：名称必须取驻场基地名列（callsign 是飞机呼号，会破坏基地聚合）
        name = ""
        if table_unit_kind == "base":
            base_col = next((c for c in columns
                             if "base" in str(c).lower() and "name" in str(c).lower()), None)
            if base_col and row.get(base_col):
                name = str(row.get(base_col))
        if not name:
            for nf in name_fields[:2]:
                if row.get(nf):
                    name = str(row.get(nf))
                    break
        # 基地语义：飞机档案表按驻场坐标聚合，同一基地只保留一个点
        if table_unit_kind == "base":
            dedup_key = (name[:40], round(lng, 4), round(lat, 4))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
        props = {k: v for k, v in row.items() if k not in (lng_field, lat_field)}
        type_val = str(row.get(type_field)) if type_field and row.get(type_field) is not None else ""
        # 基地点的 type_field 可能误命中机型外键（aircraft_type_id），基地无类别枚举
        if table_unit_kind == "base":
            type_val = ""
        # kind 兼容旧消费方：表语义优先，其次取类型列原值
        kind = table_unit_kind or type_val or "other"
        acid = str(row.get(id_field) or "") if id_field else ""
        unit = {
            "lng": lng, "lat": lat,
            "name": name[:40],
            "kind": kind,
            "unitKind": table_unit_kind or "other",
            "id": acid,
            "type": type_val,
            "status": str(row.get(status_field)) if status_field and row.get(status_field) is not None else "",
            "time": str(row.get(time_field)) if time_field and row.get(time_field) is not None else None,
            "props": props,
        }
        attach_symbol(unit)
        attach_faction(unit, row, acid)
        attach_status_key(unit, row)
        points.append(unit)
    indices = _thin_indices(len(points), config.IPAGE_MAP_POINT_LIMIT)
    units = [points[i] for i in indices]
    return {"kind": "points", "tracks": [], "points": units, "units": units, "circles": []}


# ──────────────────────────────────────────────────────────────────
# 时间轴汇总（跨数据集，供 page-kit 日期轴/日内播放）
# ──────────────────────────────────────────────────────────────────

def _min_str(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if not a:
        return b
    if not b:
        return a
    return a if a <= b else b


def _max_str(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if not a:
        return b
    if not b:
        return a
    return a if a >= b else b


def build_map_timeline(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从各数据集 geoFeatures 汇总时间轴元数据。

    一条 track 对应一个架次任务（researcher 已按 mission 拆轨）；
    事件点时间也纳入整体日期范围。无任何带时间的地理特征时返回 None。
    """
    missions: Dict[str, Dict[str, Any]] = {}
    min_time: Optional[str] = None
    max_time: Optional[str] = None

    for entry in entries:
        geo = entry.get("geoFeatures") or {}
        for tr in geo.get("tracks") or []:
            times = [p.get("time") for p in (tr.get("points") or []) if p.get("time")]
            if not times:
                continue
            t0, t1 = min(times), max(times)
            min_time, max_time = _min_str(min_time, t0), _max_str(max_time, t1)
            mid = tr.get("missionId") or f"{tr.get('id') or tr.get('name')}@{t0[:10]}"
            if mid not in missions:
                missions[mid] = {
                    "missionId": mid,
                    "aircraftId": tr.get("id") or "",
                    "name": tr.get("name") or "",
                    "faction": tr.get("faction") or "",
                    "category": tr.get("category") or "",
                    "date": t0[:10],
                    "startTime": t0[11:16] if len(t0) >= 16 else "",
                    "endTime": t1[11:16] if len(t1) >= 16 else "",
                }
        for u in geo.get("units") or geo.get("points") or []:
            if u.get("time"):
                min_time = _min_str(min_time, str(u["time"]))
                max_time = _max_str(max_time, str(u["time"]))

    if not missions or not min_time:
        return None
    mission_list = sorted(missions.values(), key=lambda m: (m["date"], m["startTime"]))
    return {
        "startDate": min_time[:10],
        "endDate": (max_time or min_time)[:10],
        "startTime": min_time[11:16] if len(min_time) >= 16 else "",
        "endTime": (max_time or min_time)[11:16] if len(max_time or "") >= 16 else "",
        "missions": mission_list,
    }


# ──────────────────────────────────────────────────────────────────
# 确定性摘要
# ──────────────────────────────────────────────────────────────────

def build_summary(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    """数值字段 min/max/sum + 分类字段 top-3，供 LLM 快速理解数据。"""
    if not rows:
        return "（无数据）"
    lines = [f"行数：{len(rows)}，字段数：{len(columns)}"]
    numeric_done = 0
    for col in columns[:20]:
        values = []
        for row in rows:
            v = _to_float(row.get(col))
            if v is not None:
                values.append(v)
        if values and numeric_done < 5:
            lines.append(f"{col}: min={min(values):.2f}, max={max(values):.2f}, "
                         f"avg={sum(values)/len(values):.2f}")
            numeric_done += 1
    category_done = 0
    for col in columns[:20]:
        counts: Dict[str, int] = {}
        for row in rows:
            v = row.get(col)
            if v is not None and not isinstance(v, (int, float)):
                counts[str(v)[:30]] = counts.get(str(v)[:30], 0) + 1
        if 1 < len(counts) <= 50 and category_done < 3:
            top3 = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            lines.append(f"{col} 分布: " + "，".join(f"{k}:{v}" for k, v in top3))
            category_done += 1
    return "；".join(lines)


# ──────────────────────────────────────────────────────────────────
# 单个子问题取数
# ──────────────────────────────────────────────────────────────────

def _append_limit(sql: str, limit: int) -> str:
    """detail 查询安全追加 LIMIT（SQL 中未显式指定时）。"""
    if re_search_limit(sql):
        return sql
    return f"{sql.rstrip(';')} LIMIT {limit + 1}"


def re_search_limit(sql: str) -> bool:
    """简单判断 SQL 是否已有 LIMIT（避免重复）。"""
    import re
    return bool(re.search(r"\blimit\s+\d+", sql, re.IGNORECASE))


def _dataset_name_map(meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    schemas = (meta.get("data", {}) or {}).get("schemas", []) if isinstance(meta, dict) else []
    result = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        ds_id = str(schema.get("datasetId") or schema.get("id") or "")
        if ds_id:
            result[ds_id] = schema
    return result


def _entity_hit_terms(entity_hits: Optional[List[Dict[str, Any]]]) -> str:
    """从实体命中描述中提取标准维度值，拼接为空态提示用的中文短语。"""
    if not entity_hits:
        return ""
    terms: List[str] = []
    for hit in entity_hits:
        for val in (hit.get("values") or [])[:3]:
            text = str(val).strip()
            if text and text not in terms:
                terms.append(text)
    return "、".join(terms[:5])


# SQL 注入白名单允许的最大 IN 集合大小（超大集合仅靠行级兜底，不做文本注入）
_SCOPE_SQL_IN_LIMIT = 2000


def _mask_sql_literals(sql: str) -> str:
    """把 SQL 字符串字面量内容替换为空格，保留引号与结构，用于关键字定位。"""
    out: List[str] = []
    quote: Optional[str] = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            out.append("\n" if ch == "\n" else " ")
            if ch == quote:
                # SQL 标准转义：'' 或 "" 表示字面引号
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    out.append(" ")
                    i += 2
                    continue
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
                out.append(" ")
            else:
                out.append(ch)
        i += 1
    return "".join(out)


def _inject_scope_where(sql: str, scope: Dict[str, set]) -> str:
    """向单表 SELECT 确定性注入实体白名单 WHERE 条件。

    聚合 SQL 的结果列通常不含外键列，行级过滤无从生效，因此在 SQL 执行前
    直接注入 WHERE。列名来自维度图（标识符正则白名单）并用反引号包裹，
    值全部参数化为转义字面量；重复注入（LLM 已写同名列条件）仅冗余不改变语义。
    """
    if not sql or not scope:
        return sql
    conds: List[str] = []
    for col, ids in scope.items():
        values = sorted(ids)
        if not values or len(values) > _SCOPE_SQL_IN_LIMIT:
            continue
        literals = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
        conds.append(f"`{col.replace('`', '``')}` IN ({literals})")
    if not conds:
        return sql
    extra = " AND ".join(conds)
    masked = _mask_sql_literals(sql)
    m = re.search(r"\bWHERE\b", masked, re.IGNORECASE)
    if m:
        return sql[:m.end()] + " " + extra + " AND " + sql[m.end():]
    # 无 WHERE：插在第一个分组/排序/限流子句之前；都没有则追加到末尾
    anchor = re.search(r"\b(GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b",
                       masked, re.IGNORECASE)
    if anchor:
        return sql[:anchor.start()] + f" WHERE {extra} " + sql[anchor.start():]
    return sql.rstrip().rstrip(";") + f" WHERE {extra}"


def execute_sub_question(sq: Dict[str, Any], meta: Dict[str, Any],
                         query: str, entity_scope: Dict[str, Any] = None,
                         entity_hits: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """执行一个子问题取数（同步，供 to_thread 并行）。

    entity_scope: 本次提问的实体白名单 {tableName: {列: set(允许值)}}，
    由 orchestrator 经通用维度解析得到；本表存在对应白名单时，无论 LLM SQL
    是否遵守，都会在 rows 进入数据包前做确定性行级过滤。

    Returns:
        数据包条目 dict（含 rows/geoFeatures/summary/sqlLog）。
    """
    qid = str(sq.get("id") or "q")
    dataset_id = str(sq.get("datasetId") or "")
    mode = str(sq.get("mode") or "aggregate")
    geo_hint = str(sq.get("geo") or "none")
    ds_meta = _dataset_name_map(meta).get(dataset_id, {})
    name = str(ds_meta.get("name") or ds_meta.get("tableName") or dataset_id)
    table_name = str(ds_meta.get("tableName") or "")
    dataset_sensitive = {
        str(c).strip().lower()
        for c in (ds_meta.get("sensitiveColumns") or [])
    }

    # 本表实体白名单（可能含本表维度列或外键 ID 集合）
    scope = dict((entity_scope or {}).get(table_name) or {})
    # 注入 LLM SQL 提示的白名单（ID 数量过大时不注入，仅靠服务端兜底过滤）
    scope_hint = None
    if scope:
        total_ids = sum(len(v) for v in scope.values())
        scope_hint = {col: sorted(ids) for col, ids in scope.items()} if total_ids <= 500 else None

    sql_log: Dict[str, Any] = {"qid": qid, "datasetId": dataset_id, "mode": mode}
    warnings: List[str] = []

    structure = admin_client.fetch_dataset_structure(dataset_id)
    fields = structure.get("fields") or []
    payload: Dict[str, Any] = {}

    if fields:
        try:
            sql_result = call_llm_json(
                prompts.build_sql_messages(sq.get("question") or query, structure, mode,
                                           scope_hint=scope_hint),
                temperature=0.2,
                max_tokens=min(config.LLM_MAX_TOKENS, 4000),
                thinking_type=config.IPAGE_STRUCT_THINKING,
            )
            sql = str((sql_result or {}).get("sql") or "").strip()
        except Exception as exc:
            sql = ""
            warnings.append(f"SQL 生成失败: {str(exc)[:120]}")

        if sql:
            # 确定性兜底：无论 LLM 是否遵守 scope_hint，都强制注入白名单 WHERE
            if scope:
                sql = _inject_scope_where(sql, scope)
                sql_log["scopeInjected"] = True
            if mode == "detail":
                sql = _append_limit(sql, config.IPAGE_DETAIL_ROW_LIMIT)
            sql_log["sql"] = sql
            payload = admin_client.execute_dataset_sql(dataset_id, sql)
            sql_log["viaSql"] = bool(payload.get("success"))
            if not payload.get("success"):
                warnings.append(f"SQL 执行失败，回退整表: {str(payload.get('message'))[:120]}")
                payload = {}
        else:
            warnings.append("LLM 未生成 SQL，回退整表查询")
    else:
        warnings.append("数据集无字段元数据，回退整表查询")

    # 地理明细 SQL 成功但 0 行：回退整表查询后再统一应用实体过滤。
    # 无实体白名单时行为同现状（回退整表保地图不空白）；
    # 有实体白名单时，回退结果必须重新过滤，过滤后仍为空则如实呈现空态，
    # 严禁偷偷回退成全量（旧逻辑会把"问侦察机"放大成"所有飞机"）。
    if payload.get("success") and mode == "detail" and geo_hint != "none":
        _, _probe_rows = _extract_rows_columns(payload)
        if not _probe_rows:
            warnings.append("地理明细 SQL 返回 0 行，已回退整表查询后重新应用过滤条件")
            sql_log["fallbackFullForEmptyGeo"] = True
            payload = {}

    if not payload.get("success"):
        payload = admin_client.query_dataset_full(dataset_id, config.IPAGE_DATA_ROW_LIMIT)
        sql_log["viaSql"] = False
        if not payload.get("success"):
            raise RuntimeError(f"数据集 {dataset_id} 取数失败: {payload.get('message', '未知错误')}")

    columns, raw_rows = _extract_rows_columns(payload)
    # 实体白名单确定性过滤（脱敏/截断之前，保证图表/地图/表格口径一致）
    raw_rows, applied_scope = _apply_entity_scope(raw_rows, columns, scope)
    if applied_scope:
        sql_log["entityFilter"] = applied_scope
    rows = _sanitize_rows(raw_rows, columns, dataset_sensitive)
    columns = [c for c in columns if not _is_sensitive(c, dataset_sensitive)]

    # 实体过滤后为空：给出明确中文提示并保留空态（不再二次回退全量）
    if scope and not rows:
        terms = _entity_hit_terms(entity_hits)
        tip = f"未找到与『{terms}』匹配的记录，已按该条件过滤" if terms \
            else "按问题中的筛选条件未找到匹配记录"
        warnings.append(tip)
        sql_log["entityFilterEmpty"] = True

    total_rows = len(rows)
    truncated = False
    row_cap = config.IPAGE_CHART_ROW_LIMIT if mode == "aggregate" else config.IPAGE_DETAIL_ROW_LIMIT
    if len(rows) > row_cap:
        rows = rows[:row_cap]
        truncated = True

    geo = {"kind": "none", "tracks": [], "points": [], "circles": [], "units": []}
    if mode == "detail" and geo_hint != "none":
        # 字段解析器：注解优先（坐标/事件时间/拆分键/半径/单位大类/符号/阵营值映射），
        # 列名启发式兜底；数据源无注解时输出与改造前逐字一致
        resolver = build_resolver(meta, table_name, columns)
        # 航迹档案补全：优先通用维度 enrich（自动发现外键档案，适配任意领域），
        # 通用索引为空时回退飞机档案专用索引，保证现有地图符号不退化
        aircraft_index = {}
        if geo_hint == "tracks":
            aircraft_index = load_entity_enrich_index(meta, table_name)
            if not aircraft_index:
                aircraft_index = load_aircraft_index(meta)
        geo = build_geo_features(rows, columns, geo_hint, table_name=table_name,
                                 aircraft_index=aircraft_index, resolver=resolver)
        if geo["kind"] == "none":
            warnings.append(f"规划的地理形态 {geo_hint} 未在字段中找到可用坐标")
        # 注解问题如实上报，不阻断生成：
        # 1) 注解列在结果集中缺失（SQL 可能未投影该列）→ 回落列名启发式；
        # 2) 值域漂移：真实取值落在注解值域外（零成本，用内存行比对，不查库）；
        # 3) 值域采样比对：默认关闭（校验已左移到保存期），仅供排障打开。
        notes = list(resolver.notes) + resolver.value_drift_notes(rows)
        if config.IPAGE_ANNOTATION_SAMPLE_CHECK:
            notes += resolver.value_domain_notes()
        for note in dict.fromkeys(notes):
            warnings.append(note)

    return {
        "id": qid,
        "datasetId": dataset_id,
        "name": name,
        "tableName": table_name,
        "purpose": str(sq.get("question") or ""),
        "mode": mode,
        "columns": columns,
        "rows": rows,
        "totalRows": total_rows,
        "truncated": truncated,
        "geo": {"kind": geo["kind"]},
        "geoFeatures": {k: geo[k] for k in ("tracks", "points", "circles", "units")},
        "summary": build_summary(columns, rows),
        "warnings": warnings,
        "_sqlLog": sql_log,
    }
