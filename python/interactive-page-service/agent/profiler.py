"""数据能力画像（确定性，零 LLM）。

对 ``/export/for-llm`` 元数据中的每个数据集构建「能力画像」，回答四个问题：

1. 这张表有没有坐标、时间、实体键、类别、归属、状态、度量、半径、关系；
2. 这些能力来自哪里（注解 / 注释 / 列名 / 统计值域）；
3. 值域是否可信（经纬度范围、时间格式、低基数枚举）；
4. 缺什么能力，页面生成时应该降级成什么。

画像只读元数据与采样统计，不调用 LLM，也不写任何注解。消费方：

- Planner：按能力决定可规划的区块与地理形态，并把能力标签写进数据集目录；
- FieldResolver：注解缺失时用画像作为第二优先级，替代纯列名启发式；
- Researcher：地图整形、时序分桶、实体补全的事实来源。

失败一律降级：统计 SQL 失败只用静态画像，不阻断页面生成。
"""
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import cache_registry
import config
from store import admin_client

logger = logging.getLogger("ipage-service")

PROFILE_CACHE_NAME = "profiler.profiles"

# 数据源类型 → SQL 方言（决定标识符引用与时间函数）
_DIALECT_BY_TYPE: Dict[str, str] = {
    "mysql": "mysql", "mariadb": "mysql",
    "postgresql": "postgresql", "postgres": "postgresql", "pg": "postgresql",
    "h2": "h2",
    "达梦数据库v8": "dm", "达梦": "dm", "dm": "dm", "dm8": "dm",
    "oracle": "oracle",
    "sql server": "sqlserver", "sqlserver": "sqlserver", "mssql": "sqlserver",
}
_VALID_DIALECTS = frozenset(_DIALECT_BY_TYPE.values())

# ── 中英文别名词典（军事领域通用，不针对具体数据源）──
# 只做“列名/注释 → 语义角色”的匹配，不绑定表名。
_LNG_TOKENS = ("lng", "lon", "longitude", "经度", "东经", "横坐标", "x坐标")
_LAT_TOKENS = ("lat", "latitude", "纬度", "北纬", "纵坐标", "y坐标")
_TIME_TOKENS = ("record_time", "event_time", "occur_time", "report_time",
                "detect_time", "recon_time", "strike_time", "damage_time",
                "时间", "日期", "时刻", "上报", "发生", "记录")
_SEQ_TOKENS = ("seq", "序号", "顺序", "点号", "轨迹点")
_RADIUS_TOKENS = ("radius", "半径", "作用范围", "覆盖范围")
_ID_TOKENS = ("_id", "编号", "标识", "编码", "代码")
_NAME_TOKENS = ("name", "callsign", "名称", "呼号", "标题", "姓名")
_CATEGORY_TOKENS = ("category", "type", "kind", "class", "类别", "类型", "种类", "分类")
_FACTION_TOKENS = ("faction", "camp", "side", "阵营", "归属", "隶属", "敌我", "编成", "所属", "派别")
_STATUS_TOKENS = ("status", "state", "health", "状态", "结果", "健康", "告警", "运行情况")
_AREA_TOKENS = ("wkt", "geojson", "polygon", "geometry", "边界", "区域", "范围面")

# 说明性长文本列：即使列名命中类别/状态词，也不作为语义维度
_NON_SEMANTIC_TOKENS = ("note", "remark", "desc", "comment", "summary", "content", "text",
                        "说明", "备注", "摘要", "描述", "理由", "详情")
# 实体键优先候选：优先明确的业务实体外键，避免把 mission_id/type_id 当成实体
_ENTITY_KEY_TOKENS = ("aircraft_id", "entity_id", "object_id", "unit_id", "equipment_id",
                      "platform_id", "sensor_id", "target_id", "threat_id", "damage_id",
                      "recon_id", "vehicle_id", "ship_id", "person_id", "编号")

# 实体大类词典：表名/注释命中即给出内部 unitKind（不写注解，不影响契约）
_ENTITY_KIND_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("预警机", "platform_air"), ("侦察机", "platform_air"), ("战斗机", "platform_air"),
    ("轰炸机", "platform_air"), ("无人机", "platform_air"), ("飞机", "platform_air"),
    ("aircraft", "platform_air"), ("uav", "platform_air"), ("air", "platform_air"),
    ("舰", "platform_sea"), ("艇", "platform_sea"), ("ship", "platform_sea"),
    ("vessel", "platform_sea"),
    ("车辆", "platform_ground"), ("坦克", "platform_ground"), ("装甲", "platform_ground"),
    ("vehicle", "platform_ground"),
    ("目标", "target"), ("threat", "threat"), ("威胁", "threat"),
    ("基地", "facility"), ("机场", "facility"), ("阵地", "facility"), ("仓库", "facility"),
    ("设施", "facility"), ("雷达站", "facility"), ("码头", "facility"),
    ("base", "facility"), ("facility", "facility"),
    ("部队", "unit"), ("分队", "unit"), ("编制", "unit"), ("连队", "unit"),
    ("unit", "unit"),
    ("人员", "person"), ("官兵", "person"), ("person", "person"),
    ("组织", "organization"), ("机构", "organization"), ("organization", "organization"),
    ("告警", "event"), ("故障", "event"), ("事件", "event"), ("打击", "event"),
    ("侦察", "event"), ("event", "event"),
    ("任务", "task"), ("行动", "task"), ("演训", "task"), ("计划", "task"),
    ("mission", "task"), ("task", "task"),
    ("防区", "area"), ("责任区", "area"), ("禁飞区", "area"), ("区域", "area"),
    ("zone", "area"), ("area", "area"),
    ("物资", "resource"), ("备件", "resource"), ("库存", "resource"), ("保障", "resource"),
    ("resource", "resource"), ("material", "resource"),
    ("频谱", "sensor"), ("信号", "sensor"), ("传感器", "sensor"), ("雷达", "sensor"),
    ("sensor", "sensor"), ("radar", "sensor"),
)

_NUMERIC_TYPE_RE = re.compile(r"int|decimal|numeric|float|double|real|number", re.I)
_TIME_TYPE_RE = re.compile(r"date|time|timestamp", re.I)
_BULKY_TYPE_RE = re.compile(r"text|blob|json|clob|geometry|geography|bytea|image", re.I)
_SAFE_IDENT_RE = re.compile(r"^[^\s`\"';]+$")

# 模块级缓存：key = 结构+注解+统计开关指纹，值为 {byId, byTable}
_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}


def clear_cache(database_id: Optional[str] = None,
                tables: Optional[List[str]] = None) -> int:
    """清理画像缓存（供 cache_registry 注解变更回调使用）。

    键里含 databaseId 与表名指纹，按前缀过滤即可精确失效。
    """
    wanted = {str(t) for t in (tables or []) if t}
    removed = 0
    for key in list(_PROFILE_CACHE):
        if database_id and database_id not in key:
            continue
        if wanted and not any(t in key for t in wanted):
            continue
        _PROFILE_CACHE.pop(key, None)
        removed += 1
    return removed


cache_registry.register_cache(PROFILE_CACHE_NAME, clear_cache)


# ──────────────────────────────────────────────────────────────────
# 对外入口
# ──────────────────────────────────────────────────────────────────

def ensure_profiles(meta: Dict[str, Any], force: bool = False,
                   allow_stats: bool = False) -> Dict[str, Any]:
    """确保 meta 上挂载能力画像，返回 ``{"byId": {...}, "byTable": {...}}``。

    Args:
        meta: /export/for-llm 元数据（画像会挂到 ``meta["_profiles"]``）
        force: 忽略已有画像重建（排障用）
        allow_stats: 是否允许统计 SQL。默认 False：纯静态画像，零查询；
            由生成入口显式开启，避免测试或只读场景意外查库。

    画像只构建一次，后续同一次生成流程内直接复用。
    """
    if not isinstance(meta, dict):
        return {"byId": {}, "byTable": {}}
    if not force and isinstance(meta.get("_profiles"), dict):
        return meta["_profiles"]
    profiles = build_profiles(meta, use_stats=allow_stats)
    meta["_profiles"] = profiles
    return profiles


def build_profiles(meta: Dict[str, Any], use_stats: bool = False) -> Dict[str, Any]:
    """遍历数据集构建画像，返回按 id / 表名双索引的字典。"""
    result: Dict[str, Any] = {"byId": {}, "byTable": {}}
    if not isinstance(meta, dict) or not meta.get("success"):
        return result
    data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
    schemas = data.get("schemas") or []
    default_dialect = _dialect_for(data.get("dbType"))
    if use_stats and config.PROFILE_STATS_ENABLED:
        dialects = _load_dialects(schemas, default_dialect)
    else:
        # 静态画像不发 SQL，无需读取数据源类型
        dialects = {str((s or {}).get("databaseId") or ""): default_dialect
                    for s in schemas if isinstance(s, dict)}
    result["dialects"] = dialects

    stats_budget = (config.PROFILE_STATS_MAX_DATASETS
                    if (use_stats and config.PROFILE_STATS_ENABLED) else 0)
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        dataset_id = str(schema.get("datasetId") or schema.get("id") or "").strip()
        table_name = str(schema.get("tableName") or "").strip()
        if not dataset_id or not table_name:
            continue
        dialect = dialects.get(str(schema.get("databaseId") or "")) or default_dialect
        try:
            profile = _profile_of(schema, dialect, use_stats=stats_budget > 0)
        except Exception as exc:  # 画像失败不阻断生成
            logger.warning("数据集画像构建失败 dataset=%s table=%s: %s",
                           dataset_id, table_name, exc)
            profile = _static_profile(schema)
        result["byId"][dataset_id] = profile
        result["byTable"][table_name] = profile
        if stats_budget > 0:
            stats_budget -= 1
    if result["byId"]:
        logger.info("能力画像构建完成：%s 个数据集（统计增强=%s）",
                    len(result["byId"]), config.PROFILE_STATS_ENABLED)
    return result


def profile_for_table(meta: Dict[str, Any], table_name: str) -> Optional[Dict[str, Any]]:
    """按物理表名取画像（不存在返回 None）。"""
    profiles = ensure_profiles(meta)
    return (profiles.get("byTable") or {}).get(str(table_name or ""))


def profile_for_dataset(meta: Dict[str, Any], dataset_id: str) -> Optional[Dict[str, Any]]:
    """按数据集 ID 取画像（不存在返回 None）。"""
    profiles = ensure_profiles(meta)
    return (profiles.get("byId") or {}).get(str(dataset_id or ""))


def dialect_for(meta: Dict[str, Any], dataset_id: str) -> str:
    """按数据集所属数据源返回 SQL 方言（mysql/postgresql/h2/dm/oracle/sqlserver）。

    画像未构建时回退全局 ``data.dbType``，再回退 mysql。
    """
    profile = profile_for_dataset(meta, dataset_id)
    if isinstance(profile, dict) and profile.get("dialect"):
        return str(profile["dialect"])
    data = meta.get("data") if isinstance(meta, dict) else {}
    return _dialect_for((data or {}).get("dbType"))


def summarize(profile: Optional[Dict[str, Any]]) -> str:
    """把画像压缩成一行中文能力标签，供数据集目录展示。

    例：``【能力：坐标(经度/纬度)｜时间(report_time)｜类别(category)｜归属(side)｜状态(health)】``
    """
    if not isinstance(profile, dict):
        return ""
    cap = profile.get("capabilities") or {}
    parts: List[str] = []
    geo = cap.get("geo") or {}
    if geo.get("lng") and geo.get("lat"):
        parts.append(f"坐标({geo['lng']}/{geo['lat']})")
    time_cap = cap.get("time") or {}
    if time_cap.get("column"):
        parts.append(f"时间({time_cap['column']})")
    entity = cap.get("entity") or {}
    if entity.get("key"):
        parts.append(f"实体({entity['key']})")
    for col in (cap.get("category") or [])[:2]:
        parts.append(f"类别({col})")
    for col in (cap.get("affiliation") or [])[:1]:
        parts.append(f"归属({col})")
    for col in (cap.get("status") or [])[:1]:
        parts.append(f"状态({col})")
    measures = cap.get("measures") or []
    if measures:
        parts.append(f"度量({len(measures)}列)")
    return ("【能力：" + "｜".join(parts) + "】") if parts else "【能力：仅明细】"


# ──────────────────────────────────────────────────────────────────
# 静态画像：只看元数据，不查库
# ──────────────────────────────────────────────────────────────────

def _profile_of(schema: Dict[str, Any], dialect: str, use_stats: bool) -> Dict[str, Any]:
    """构建单个数据集画像（静态 + 可选统计增强），带进程内缓存。"""
    fingerprint = _fingerprint(schema, use_stats)
    cached = _PROFILE_CACHE.get(fingerprint)
    if cached is not None:
        return cached

    profile = _static_profile(schema)
    profile["dialect"] = dialect
    if use_stats and config.PROFILE_STATS_ENABLED:
        try:
            _enrich_with_stats(profile, schema, dialect)
        except Exception as exc:
            profile["warnings"].append(f"统计画像失败，已使用静态画像：{str(exc)[:120]}")
            logger.warning("统计画像失败 table=%s: %s", profile.get("tableName"), exc)

    _PROFILE_CACHE[fingerprint] = profile
    return profile


def _static_profile(schema: Dict[str, Any]) -> Dict[str, Any]:
    """纯元数据画像：注解优先，其次列名/注释词典。"""
    dataset_id = str(schema.get("datasetId") or schema.get("id") or "")
    table_name = str(schema.get("tableName") or "")
    dataset_name = str(schema.get("datasetName") or schema.get("name") or table_name)
    description = str(schema.get("description") or "")
    fields = [f for f in (schema.get("fields") or schema.get("columns") or [])
              if isinstance(f, dict)]

    columns: Dict[str, Dict[str, Any]] = {}
    for f in fields:
        col = str(f.get("column") or f.get("name") or f.get("fieldName") or "").strip()
        if not col:
            continue
        columns[col] = {
            "type": str(f.get("type") or f.get("dataType") or ""),
            "comment": str(f.get("businessMeaning") or f.get("comment") or f.get("annotation") or ""),
            "pk": bool(f.get("isPrimaryKey")),
            "semantic": _parse_json(f.get("semanticJson")),
        }

    semantic = _parse_json(schema.get("semanticJson"))
    profile: Dict[str, Any] = {
        "datasetId": dataset_id,
        "databaseId": str(schema.get("databaseId") or ""),
        "tableName": table_name,
        "datasetName": dataset_name,
        "description": description,
        "columns": columns,
        "rowCount": None,
        "stats": False,
        "capabilities": _detect_capabilities(columns, semantic, table_name, description, dataset_name),
        "warnings": [],
    }
    return profile


def _detect_capabilities(columns: Dict[str, Dict[str, Any]],
                         semantic: Dict[str, Any],
                         table_name: str,
                         description: str,
                         dataset_name: str) -> Dict[str, Any]:
    """从注解与列名/注释推断能力（不含统计值域）。"""
    names = list(columns.keys())
    lower_map = {c.lower(): c for c in names}

    # ── 坐标：注解 geometry / 字段 role → 列名词典 → 成对前后缀 ──
    geo_lng = geo_lat = geo_radius = ""
    geo_source = ""
    geometry = semantic.get("geometry") if isinstance(semantic, dict) else None
    if isinstance(geometry, dict):
        geo_lng = str(geometry.get("lngColumn") or "")
        geo_lat = str(geometry.get("latColumn") or "")
        geo_radius = str(geometry.get("radiusColumn") or "")
        if geo_lng and geo_lat:
            geo_source = "annotation"
    if not (geo_lng and geo_lat):
        for role in ("lng", "lat"):
            role_col = next((c for c in names
                             if str((columns[c].get("semantic") or {}).get("role") or "") == role), "")
            if role == "lng" and role_col:
                geo_lng = role_col
            elif role == "lat" and role_col:
                geo_lat = role_col
        if geo_lng and geo_lat:
            geo_source = "annotation"
    if not (geo_lng and geo_lat):
        lngs: Dict[str, str] = {}
        lats: Dict[str, str] = {}
        for col in names:
            low = col.lower()
            meaning = str(columns[col].get("comment") or "")
            # 列名与中文注释同时参与匹配：适配 JD/WD 这类拼音缩写列
            if _hit(low, _LNG_TOKENS) or _hit(meaning, _LNG_TOKENS):
                lngs[col] = col
            if _hit(low, _LAT_TOKENS) or _hit(meaning, _LAT_TOKENS):
                lats[col] = col
            if low.endswith("_lng") or low.endswith("_lon"):
                lngs[low[:-4]] = col
            elif low.endswith("_lat"):
                lats[low[:-4]] = col
        # 前后缀配对优先，其次任意一对
        paired = next(((lngs[p], lats[p]) for p in lngs if p in lats), None)
        if paired:
            geo_lng, geo_lat = paired
            geo_source = "name"
        elif lngs and lats:
            geo_lng = next(iter(lngs.values()))
            geo_lat = next(iter(lats.values()))
            geo_source = "name"
    if not geo_radius:
        geo_radius = next((c for c in names
                           if str((columns[c].get("semantic") or {}).get("role") or "") == "radius"), "")
    radius_cols = [c for c in names
                   if str((columns[c].get("semantic") or {}).get("role") or "") == "radius"
                   or _hit(c.lower(), _RADIUS_TOKENS)]

    # ── 时间：注解 eventTimeColumn → 字段 role=time → 词典 ──
    time_col = ""
    time_source = ""
    if isinstance(semantic, dict) and semantic.get("eventTimeColumn"):
        time_col = str(semantic.get("eventTimeColumn"))
        time_source = "annotation"
    if not time_col:
        time_col = next((c for c in names
                         if str((columns[c].get("semantic") or {}).get("role") or "") == "time"), "")
        if time_col:
            time_source = "annotation"
    if not time_col:
        time_col = _pick_time_column(columns)
        if time_col:
            time_source = "name"

    # ── 实体键 / 名称 / 序号 ──
    entity_key = ""
    if isinstance(semantic, dict) and isinstance(semantic.get("trackGroupKey"), list) \
            and semantic.get("trackGroupKey"):
        entity_key = str(semantic["trackGroupKey"][0])
    if not entity_key:
        # 优先"列名与表名匹配"的实体键（mock_mission→mission_id），比固定词表更通用
        entity_key = _entity_key_by_table(names, table_name)
    if not entity_key:
        # 其次明确的业务实体外键（aircraft_id/unit_id/...），避免 mission_id/type_id 被误当实体
        entity_key = _pick_by_tokens(names, _ENTITY_KEY_TOKENS,
                                     exclude=_LNG_TOKENS + _LAT_TOKENS)
    if not entity_key:
        pk = next((c for c in names if columns[c].get("pk")), "")
        # 时间类型主键（如统计日期）不是实体键
        if pk and not _TIME_TYPE_RE.search(str(columns[pk].get("type") or "")):
            entity_key = pk
    if not entity_key:
        entity_key = _pick_by_tokens(
            names, _ID_TOKENS,
            exclude=_LNG_TOKENS + _LAT_TOKENS + ("mission", "task", "type"))
    name_col = _pick_by_tokens(names, _NAME_TOKENS)
    if not name_col:
        # 拼音缩写列（如 BDMC）靠中文注释"部队名称"识别
        name_col = next((c for c, m in columns.items()
                         if _hit(str(m.get("comment") or ""), _NAME_TOKENS)), "")
    seq_col = next((c for c in names
                    if str((columns[c].get("semantic") or {}).get("role") or "") == "seq"), "")
    if not seq_col:
        seq_col = _pick_by_tokens(names, _SEQ_TOKENS)

    # ── 类别 / 归属 / 状态：注解 role 优先，其次词典（仅文本列，排除说明/ID 列）──
    category_cols: List[str] = []
    faction_cols: List[str] = []
    status_cols: List[str] = []
    for col, meta in columns.items():
        sem = meta.get("semantic") or {}
        role = str(sem.get("role") or "")
        low = col.lower()
        meaning = str(meta.get("comment") or "")
        if role == "status":
            status_cols.append(col)
            continue
        if role == "dimension" and not (sem.get("values") or sem.get("synonyms")):
            category_cols.append(col)
            continue
        if role == "dimension" and (sem.get("values") or sem.get("synonyms")):
            if _hit(low, _FACTION_TOKENS) or any(t in meaning for t in ("阵营", "归属", "隶属", "敌我")):
                faction_cols.append(col)
            else:
                category_cols.append(col)
            continue
        if not _is_textual_column(meta):
            continue
        if any(tok in low for tok in _NON_SEMANTIC_TOKENS):
            continue
        if low.endswith("_id") or any(tok in low for tok in ("编号", "标识", "编码")):
            continue
        if _hit(low, _FACTION_TOKENS) or any(t in meaning for t in ("阵营", "归属", "隶属", "敌我")):
            faction_cols.append(col)
        elif _hit(low, _STATUS_TOKENS) or any(t in meaning for t in ("状态", "结果", "健康", "告警")):
            status_cols.append(col)
        elif _hit(low, _CATEGORY_TOKENS) or any(t in meaning for t in ("类别", "类型", "分类", "种类")):
            category_cols.append(col)
    # 去重并保持列顺序
    category_cols = [c for i, c in enumerate(category_cols) if c not in category_cols[:i]]
    faction_cols = [c for i, c in enumerate(faction_cols) if c not in faction_cols[:i]]
    status_cols = [c for i, c in enumerate(status_cols) if c not in status_cols[:i]]

    # ── 度量：数值列，排除坐标/编号/时间/半径 ──
    excluded = {geo_lng, geo_lat, geo_radius, entity_key, time_col} | set(radius_cols)
    measures = [c for c, meta in columns.items()
                if _NUMERIC_TYPE_RE.search(str(meta.get("type") or ""))
                and c not in excluded and not c.lower().endswith("_id")]

    # ── 实体大类：表名/说明/列注释词典，默认 other ──
    entity_kind = str((semantic or {}).get("entityKind") or "").strip()
    if not entity_kind:
        column_meanings = " ".join(str(m.get("comment") or "") for m in columns.values())
        entity_kind = _detect_entity_kind(
            table_name + " " + dataset_name + " " + description + " " + column_meanings)

    return {
        "geo": {"lng": geo_lng, "lat": geo_lat, "radius": radius_cols,
                "source": geo_source, "coordType": "geographic"},
        "time": {"column": time_col, "source": time_source},
        "entity": {"key": entity_key, "name": name_col, "kind": entity_kind,
                   "category": category_cols, "seq": seq_col},
        "category": category_cols,
        "affiliation": faction_cols,
        "status": status_cols,
        "measures": measures,
        "relations": [],
        "area": next((c for c in names if _hit(c.lower(), _AREA_TOKENS)), ""),
    }


# ──────────────────────────────────────────────────────────────────
# 统计增强：一条聚合 SQL + 少量枚举 SQL
# ──────────────────────────────────────────────────────────────────

def _enrich_with_stats(profile: Dict[str, Any], schema: Dict[str, Any], dialect: str) -> None:
    """用采样统计校正静态画像（行数、值域、基数、枚举、唯一性）。"""
    dataset_id = str(schema.get("datasetId") or schema.get("id") or "")
    table = str(profile.get("tableName") or "")
    columns = profile.get("columns") or {}
    if not dataset_id or not table or not columns:
        return

    stat_cols = _stat_columns(columns)
    if not stat_cols:
        return

    sql = _stats_sql(dialect, table, stat_cols)
    payload = admin_client.execute_dataset_sql(dataset_id, sql)
    rows = _rows_of(payload)
    if not rows:
        profile["warnings"].append("统计画像未返回结果，已使用静态画像")
        return

    row = rows[0]
    profile["rowCount"] = _to_int(row.get("r0"))
    cap = profile["capabilities"]
    for idx, col in enumerate(stat_cols):
        non_null = _to_int(row.get(f"c{idx}_n"))
        distinct = _to_int(row.get(f"c{idx}_d"))
        min_v = row.get(f"c{idx}_min")
        max_v = row.get(f"c{idx}_max")
        meta = columns.get(col) or {}
        meta["nullRate"] = 0.0
        if profile["rowCount"]:
            meta["nullRate"] = round(1 - (non_null or 0) / profile["rowCount"], 4)
        meta["distinct"] = distinct
        meta["min"] = min_v
        meta["max"] = max_v
        meta["unique"] = bool(profile["rowCount"] and distinct == profile["rowCount"])

    # 坐标：值域必须落在经纬度范围内，否则视为投影坐标（不画地图）
    geo = cap.get("geo") or {}
    if geo.get("lng") and geo.get("lat"):
        lng_meta = columns.get(geo["lng"]) or {}
        lat_meta = columns.get(geo["lat"]) or {}
        if _outside_range(lng_meta.get("min"), lng_meta.get("max"), 180) or \
                _outside_range(lat_meta.get("min"), lat_meta.get("max"), 90):
            geo["coordType"] = "projected"
            profile["warnings"].append(
                f"坐标列 {geo['lng']}/{geo['lat']} 的值域不在经纬度范围内，按投影坐标处理（不渲染地图）")

    # 时间：MIN/MAX 必须能解析成时间，否则撤销时间能力
    time_cap = cap.get("time") or {}
    if time_cap.get("column"):
        t_meta = columns.get(time_cap["column"]) or {}
        if t_meta.get("min") and not _looks_like_time(str(t_meta.get("min"))):
            if time_cap.get("source") == "name":
                time_cap["column"] = ""
                time_cap["source"] = ""

    # 实体键：静态识别为空时才用"像 ID 的唯一列"兜底。
    # 不覆盖已有判断，避免把唯一的时间戳/序号当成实体键（会把航迹拆错）。
    entity = cap.get("entity") or {}
    if not entity.get("key"):
        unique_col = next((c for c, m in columns.items()
                           if m.get("unique") and _looks_like_entity_key(c)), "")
        if unique_col:
            entity["key"] = unique_col

    # 枚举值：只对归属/状态/类别的前几列查询
    enum_targets: List[str] = []
    for group in ("affiliation", "status", "category"):
        for col in cap.get(group) or []:
            if col not in enum_targets and _enum_allowed(columns.get(col) or {}):
                enum_targets.append(col)
            if len(enum_targets) >= 2:
                break
        if len(enum_targets) >= 2:
            break
    for col in enum_targets:
        values = _enum_values(dataset_id, dialect, table, col)
        if values:
            columns[col]["values"] = values
            if col in (cap.get("affiliation") or []):
                cap.setdefault("affiliationValues", {})[col] = values

    profile["stats"] = True


def _stat_columns(columns: Dict[str, Dict[str, Any]]) -> List[str]:
    """挑选适合统计的列：排除敏感列与大字段列。"""
    result: List[str] = []
    for col, meta in columns.items():
        if _is_sensitive(col):
            continue
        if _BULKY_TYPE_RE.search(str(meta.get("type") or "")):
            continue
        if not _SAFE_IDENT_RE.match(col):
            continue
        result.append(col)
        if len(result) >= 40:
            break
    return result


def _stats_sql(dialect: str, table: str, columns: List[str]) -> str:
    """一条聚合 SQL 取全部列的 COUNT/DISTINCT/MIN/MAX。"""
    parts = ["COUNT(*) AS r0"]
    for idx, col in enumerate(columns):
        q = _quote_ident(dialect, col)
        parts.append(f"COUNT({q}) AS c{idx}_n")
        parts.append(f"COUNT(DISTINCT {q}) AS c{idx}_d")
        parts.append(f"MIN({q}) AS c{idx}_min")
        parts.append(f"MAX({q}) AS c{idx}_max")
    return f"SELECT {', '.join(parts)} FROM {_quote_ident(dialect, table)}"


def _enum_values(dataset_id: str, dialect: str, table: str, column: str) -> List[str]:
    """取低基数列的枚举值（最多 50 个，按出现次数降序）。"""
    q = _quote_ident(dialect, column)
    sql = (f"SELECT {q} AS v, COUNT(*) AS n FROM {_quote_ident(dialect, table)} "
           f"GROUP BY {q} ORDER BY n DESC LIMIT 50")
    rows = _rows_of(admin_client.execute_dataset_sql(dataset_id, sql))
    return [str(r.get("v")) for r in rows
            if r.get("v") is not None and str(r.get("v")).strip()]


def _enum_allowed(meta: Dict[str, Any]) -> bool:
    """枚举查询只允许低基数文本列。"""
    ctype = str(meta.get("type") or "")
    if _NUMERIC_TYPE_RE.search(ctype) or _TIME_TYPE_RE.search(ctype):
        return False
    if _BULKY_TYPE_RE.search(ctype):
        return False
    distinct = meta.get("distinct")
    return distinct is not None and 0 < distinct <= 50


# ──────────────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────────────

def _hit(text: str, tokens: Tuple[str, ...]) -> bool:
    """列名是否命中词典（英文小写包含 / 中文包含）。"""
    low = str(text or "").lower()
    return any(tok in low for tok in tokens)


def _is_textual_column(meta: Dict[str, Any]) -> bool:
    """列是否适合作为语义维度（排除数值、时间与大字段）。"""
    ctype = str(meta.get("type") or "")
    if not ctype:
        return True
    if _NUMERIC_TYPE_RE.search(ctype) or _TIME_TYPE_RE.search(ctype):
        return False
    if _BULKY_TYPE_RE.search(ctype):
        return False
    return True


def _looks_like_entity_key(column: str) -> bool:
    """列名是否像实体键（ID/编号），用于统计后兜底选择唯一列。"""
    low = str(column or "").lower()
    return (low.endswith("_id") or _hit(low, _ENTITY_KEY_TOKENS)
            or any(tok in low for tok in ("编号", "标识", "编码")))


def _entity_key_by_table(names: List[str], table_name: str) -> str:
    """按表名匹配实体键：表去掉常见前后缀后，取与表名同名的 ``*_id`` 列。

    例：``mock_mission`` → ``mission_id``；``t_equipment`` → ``equipment_id``。
    比固定词表更通用，避免所有表都优先命中 ``aircraft_id``。
    """
    stem = str(table_name or "").lower().strip()
    for prefix in ("mock_", "dim_", "fact_", "t_", "tb_", "ods_", "dwd_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    parts = [p for p in stem.split("_") if p]
    for part in reversed(parts):
        for suffix in ("_id", "id"):
            candidate = part + suffix
            for col in names:
                if col.lower() == candidate:
                    return col
    return ""


def _pick_by_tokens(names: List[str], tokens: Tuple[str, ...],
                    exclude: Tuple[str, ...] = ()) -> str:
    """按词典顺序挑第一个命中的列（exclude 用于排除坐标等误命中）。"""
    for tok in tokens:
        for col in names:
            low = col.lower()
            if any(e in low for e in exclude):
                continue
            if tok in low:
                return col
    return ""


def _pick_time_column(columns: Dict[str, Dict[str, Any]]) -> str:
    """时间列：优先事件时间，排除档案/管理类日期（列名或中文注释命中都生效）。"""
    non_event = ("commission", "found", "establish", "birth", "create", "update", "valid",
                 "服役", "成立", "创建", "更新", "出生", "有效")
    for col, meta in columns.items():
        ctype = str(meta.get("type") or "")
        low = col.lower()
        meaning = str(meta.get("comment") or "")
        if not (_TIME_TYPE_RE.search(ctype) or _hit(low, _TIME_TOKENS)
                or _hit(meaning, _TIME_TOKENS)):
            continue
        if any(k in low or k in meaning for k in non_event):
            continue
        return col
    return ""


def _detect_entity_kind(text: str) -> str:
    """表名/说明 → 内部实体大类。"""
    low = str(text or "").lower()
    for token, kind in _ENTITY_KIND_TOKENS:
        if token in low:
            return kind
    return "other"


def _fingerprint(schema: Dict[str, Any], use_stats: bool) -> str:
    """结构 + 注解 + 统计开关指纹。"""
    parts = [str(schema.get("datasetId") or ""), str(schema.get("tableName") or ""),
             str(schema.get("semanticJson") or ""), "stats" if use_stats else "static"]
    for f in schema.get("fields") or schema.get("columns") or []:
        if not isinstance(f, dict):
            continue
        parts.append("|".join(str(f.get(k) or "") for k in
                              ("column", "name", "type", "comment", "businessMeaning",
                               "isPrimaryKey", "semanticJson")))
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _parse_json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _rows_of(payload: Any) -> List[Dict[str, Any]]:
    """兼容 admin 的多种返回形态，取出结果行。"""
    if not isinstance(payload, dict) or not payload.get("success"):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        rows = data.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    rows = payload.get("rows")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    return []


def _quote_ident(dialect: str, name: str) -> str:
    """按方言引用标识符（列名可能是中文）。

    MySQL 用反引号；PostgreSQL/H2/达梦/Oracle/SQL Server 用双引号。
    """
    n = str(name or "").replace('"', '""').replace("`", "``")
    if dialect in ("postgresql", "h2", "dm", "oracle", "sqlserver"):
        return f'"{n}"'
    return f"`{n}`"


def _dialect_for(db_type: Any, fallback: str = "mysql") -> str:
    """数据源类型 → SQL 方言；未知类型回退 fallback（仍未知则 mysql）。"""
    key = str(db_type or "").strip().lower()
    if key in _DIALECT_BY_TYPE:
        return _DIALECT_BY_TYPE[key]
    base = str(fallback or "").strip().lower()
    return base if base in _VALID_DIALECTS else "mysql"


def _load_dialects(schemas: List[Any], default: str) -> Dict[str, str]:
    """读取数据源类型，建立 databaseId → SQL 方言映射（失败回退全局）。"""
    type_map: Dict[str, str] = {}
    try:
        payload = admin_client.query_databases()
        items = payload.get("databases") or payload.get("data") or []
        if isinstance(items, list):
            type_map = {
                str(item.get("id")): str(item.get("type") or "")
                for item in items if isinstance(item, dict)
            }
    except Exception as exc:  # 方言探测失败不阻断
        logger.warning("读取数据源类型失败，SQL 方言回退全局: %s", exc)
    result: Dict[str, str] = {}
    for schema in schemas:
        db_id = str((schema or {}).get("databaseId") or "")
        result[db_id] = _dialect_for(type_map.get(db_id), default)
    return result


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _outside_range(min_v: Any, max_v: Any, limit: float) -> bool:
    lo, hi = _to_float(min_v), _to_float(max_v)
    if lo is None or hi is None:
        return False
    return lo < -limit or hi > limit


def _looks_like_time(text: str) -> bool:
    """宽松识别时间字符串（日期/时间/时间戳）。"""
    s = str(text or "").strip()
    if not s:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return True
    if re.match(r"^\d{13}$", s) or re.match(r"^\d{10}$", s):
        return True  # 毫秒/秒时间戳
    return bool(re.search(r"\d{1,2}:\d{2}", s))


def _is_sensitive(column: str) -> bool:
    """列名命中敏感词表时跳过统计与枚举。"""
    low = str(column or "").lower()
    return any(token in low for token in config.IPAGE_SENSITIVE_COLUMNS)
