"""评估分析：空间分布产物生成。

背景
----
评估分析的主查询通常是按阵营/区域聚合的统计结果（如 AVG/GROUP BY），
行数据里没有经纬度，态势页面因此无法渲染地图。本模块在不改变评估主查询
口径的前提下，额外执行一条只读坐标明细查询，生成一个独立的「空间分布」
产物，随评估 ``result.geoArtifacts`` 返回。

设计要点
--------
1. 只读、可降级：任何异常都返回 ``None``，不影响评估主流程；
2. 选表可解释：优先使用评估实际涉及的表；没有坐标时按表名/描述/字段注释
   与问题做确定性语义匹配；
3. 数据量可控：最多 200 行、15 列，避免超出 MySQL ``metadata`` TEXT 容量；
4. 图层自动识别：名称+经纬度→标点；seq+实体→航迹；半径列→范围圈。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .sql_dialect import normalize_database_dialect
from .tools import execute_sql_on_database, fetch_skill_datasets_for_database

logger = logging.getLogger("evaluation.geo_artifacts")

# 坐标产物的数据上限（与 ass_chat_message.metadata TEXT 容量对齐）
MAX_GEO_ROWS = 120
MAX_GEO_COLUMNS = 15
MAX_EXTRA_COLUMNS = 6
# 坐标明细查询的 HTTP 超时（秒），避免拖慢评估结束
GEO_QUERY_TIMEOUT = 8

# 允许附带坐标产物的结果类型
ARTIFACT_RESULT_TYPES = {
    "skill",
    "air_superiority",
    "combat_effectiveness",
    "indicator_calculation",
    "data_query",
    "general",
}

# 语义打分时需要过滤的高频词片段
_STOP_GRAMS = {
    "对比", "双方", "分析", "评估", "查询", "统计", "情况", "数据", "指标",
    "结果", "主要", "哪些", "如何", "以及", "进行", "给出", "基于", "当前",
    "相关", "所有", "各个", "分别", "一下", "一个", "可以", "是否", "什么",
}

# 表名/列名白名单：仅允许安全的标识符，避免坐标 SQL 被注入
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)?$")
_SQL_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([`\"\[\]A-Za-z0-9_$.#]+)",
    re.IGNORECASE,
)
# 大文本/二进制列不进入坐标产物，控制体积
_EXCLUDED_TYPES = re.compile(
    r"TEXT|BLOB|CLOB|BINARY|JSON|XML|IMAGE|BYTEA|LONGTEXT|MEDIUMTEXT",
    re.IGNORECASE,
)

_LNG_SUFFIXES = ("_lng", "_lon", "_longitude", "_经度")
_LAT_SUFFIXES = ("_lat", "_latitude", "_纬度")

_RADIUS_PRIORITY = ("radius_km", "radius", "coverage_km", "半径")


@dataclass
class GeoTable:
    """一张可生成地图的坐标表。"""

    table_name: str
    dataset_name: str
    description: str
    lng_column: str
    lat_column: str
    name_column: str = ""
    seq_column: str = ""
    entity_column: str = ""
    radius_columns: List[str] = field(default_factory=list)
    kind: str = "points"  # points / routes / areas
    columns: List[str] = field(default_factory=list)
    all_columns: List[str] = field(default_factory=list)
    database_type: str = ""
    database_product_name: str = ""
    text_for_score: str = ""

    @property
    def identity(self) -> str:
        """用于日志与去重的稳定标识。"""
        return f"{self.table_name}:{self.lng_column}/{self.lat_column}"


def _norm(value: Any) -> str:
    """列名/表名统一小写并去除空白。"""
    return str(value or "").strip().casefold()


def _is_safe_identifier(value: str) -> bool:
    """判断表名/列名是否可以安全拼入坐标 SQL。"""
    return bool(_IDENTIFIER_RE.match(str(value or "")))


def _find_lng_lat_pair(columns: Sequence[str]) -> Optional[Tuple[str, str]]:
    """从列名中找出配对度最高的经纬度列。

    支持 ``lng/lat``、``longitude/latitude``、``track_lng/track_lat`` 等写法，
    同前缀列对优先，避免把 ``home_lng`` 和 ``event_lat`` 错配。
    """
    lng_columns: List[Tuple[str, str]] = []
    lat_columns: List[Tuple[str, str]] = []
    for column in columns:
        key = _norm(column)
        if not key:
            continue
        if key in ("lng", "lon", "longitude", "经度"):
            lng_columns.append((column, ""))
        elif key.endswith(_LNG_SUFFIXES):
            for suffix in _LNG_SUFFIXES:
                if key.endswith(suffix):
                    lng_columns.append((column, key[: -len(suffix)]))
                    break
        elif key in ("lat", "latitude", "纬度"):
            lat_columns.append((column, ""))
        elif key.endswith(_LAT_SUFFIXES):
            for suffix in _LAT_SUFFIXES:
                if key.endswith(suffix):
                    lat_columns.append((column, key[: -len(suffix)]))
                    break

    best: Optional[Tuple[int, str, str]] = None
    for lng_name, lng_prefix in lng_columns:
        for lat_name, lat_prefix in lat_columns:
            # 同前缀加分；无前缀的通用列略微降权，避免抢占业务前缀列
            score = 10 if lng_prefix == lat_prefix else 0
            if not lng_prefix and not lat_prefix:
                score += 5
            if best is None or score > best[0]:
                best = (score, lng_name, lat_name)
    if not best:
        return None
    return best[1], best[2]


def _find_name_column(columns: Sequence[str]) -> str:
    """选择地图标注名称列。"""
    normalized = {_norm(column): column for column in columns}
    for candidate in (
        "aircraft_name",
        "enemy_aircraft_name",
        "target_name",
        "threat_name",
        "unit_name",
        "callsign",
        "name",
    ):
        if candidate in normalized:
            return normalized[candidate]
    # 通用维度名（阵营/区域/类型）不适合作为地图点位名称
    dimension_prefixes = ("side_", "region_", "type_", "category_", "faction_", "status_")
    for key, column in normalized.items():
        if key.endswith("_name") and not key.startswith(dimension_prefixes):
            return column
    return ""


def _find_seq_column(columns: Sequence[str]) -> str:
    """选择航迹点排序序号列。"""
    normalized = {_norm(column): column for column in columns}
    for candidate in ("seq", "sequence", "point_seq", "序号"):
        if candidate in normalized:
            return normalized[candidate]
    return ""


def _find_entity_column(columns: Sequence[str], name_column: str = "") -> str:
    """选择航迹分组实体列（飞机/目标/单位编号或名称）。"""
    normalized = {_norm(column): column for column in columns}
    for candidate in (
        "aircraft_id",
        "enemy_aircraft_id",
        "entity_id",
        "unit_id",
        "target_id",
        "threat_id",
        "aircraft_name",
        "enemy_aircraft_name",
        "unit_name",
        "target_name",
        "threat_name",
    ):
        if candidate in normalized:
            return normalized[candidate]
    # 名称列可作为航迹分组依据；若每组不足 2 个点，build_geo_features 会降级为标点
    return name_column


def _find_radius_columns(columns: Sequence[str]) -> List[str]:
    """选择范围圈半径列，支持一张表同时有探测/打击双半径。"""
    normalized = {_norm(column): column for column in columns}
    result: List[str] = []
    for candidate in _RADIUS_PRIORITY:
        if candidate in normalized and normalized[candidate] not in result:
            result.append(normalized[candidate])
    for key, column in normalized.items():
        if ("radius" in key or key.endswith("半径")) and column not in result:
            result.append(column)
    return result


def _is_scalar_type(column_meta: Dict[str, Any]) -> bool:
    """判断字段是否适合放入坐标明细行。"""
    data_type = str(column_meta.get("dataType") or column_meta.get("type") or "")
    if data_type and _EXCLUDED_TYPES.search(data_type):
        return False
    return True


def inspect_dataset(dataset: Dict[str, Any]) -> Optional[GeoTable]:
    """检查单个数据集/物理表能否生成坐标产物。

    Args:
        dataset: ``fetch_skill_datasets_for_database`` 返回的数据集字典

    Returns:
        GeoTable 或 None（无表名、无坐标列、字段名不安全时）
    """
    if not isinstance(dataset, dict):
        return None
    table_name = str(dataset.get("tableName") or "").strip()
    if not table_name or not _is_safe_identifier(table_name):
        return None

    raw_columns = dataset.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        return None

    column_metas: List[Dict[str, Any]] = [
        column for column in raw_columns if isinstance(column, dict)
    ]
    column_names = [
        str(column.get("columnName") or column.get("name") or "")
        for column in column_metas
    ]
    column_names = [name for name in column_names if name and _is_safe_identifier(name)]
    pair = _find_lng_lat_pair(column_names)
    if not pair:
        return None

    lng_column, lat_column = pair
    name_column = _find_name_column(column_names)
    seq_column = _find_seq_column(column_names)
    entity_column = _find_entity_column(column_names, name_column)
    radius_columns = _find_radius_columns(column_names)

    # 图层判定优先级：航迹（seq+实体）> 范围圈（半径）> 标点
    if seq_column and entity_column:
        kind = "routes"
    elif radius_columns:
        kind = "areas"
    else:
        kind = "points"

    selected: List[str] = [lng_column, lat_column]
    for column in (name_column, seq_column, entity_column, *radius_columns):
        if column and column not in selected:
            selected.append(column)

    # 附带少量业务属性列，供地图弹窗展示；主键与大文本列不进入
    extra_columns: List[str] = []
    for meta in column_metas:
        column = str(meta.get("columnName") or meta.get("name") or "")
        if not column or column in selected or not _is_safe_identifier(column):
            continue
        if meta.get("isPrimaryKey") or not _is_scalar_type(meta):
            continue
        extra_columns.append(column)
        if len(extra_columns) >= MAX_EXTRA_COLUMNS:
            break
    selected.extend(extra_columns)
    selected = selected[:MAX_GEO_COLUMNS]

    score_parts: List[str] = [
        str(dataset.get("name") or ""),
        str(dataset.get("description") or ""),
        table_name,
    ]
    for meta in column_metas:
        score_parts.append(str(meta.get("columnName") or ""))
        score_parts.append(str(meta.get("comment") or ""))
        score_parts.append(str(meta.get("businessMeaning") or ""))
        score_parts.append(str(meta.get("annotation") or ""))

    return GeoTable(
        table_name=table_name,
        dataset_name=str(dataset.get("name") or table_name),
        description=str(dataset.get("description") or ""),
        lng_column=lng_column,
        lat_column=lat_column,
        name_column=name_column,
        seq_column=seq_column,
        entity_column=entity_column,
        radius_columns=radius_columns,
        kind=kind,
        columns=selected,
        all_columns=column_names,
        database_type=str(dataset.get("databaseType") or ""),
        database_product_name=str(dataset.get("databaseProductName") or ""),
        text_for_score=" ".join(part for part in score_parts if part).casefold(),
    )


def _normalize_table_reference(value: str) -> str:
    """清洗 SQL 中的表名引用。"""
    text = str(value or "").strip().strip("`\"[]")
    return text.casefold()


def _table_last_segment(value: str) -> str:
    """取表名最后一段，兼容 schema.table 写法。"""
    return _normalize_table_reference(value).split(".")[-1]


def extract_used_tables(result: Dict[str, Any]) -> List[str]:
    """从评估结果中提取实际查询过的表名。"""
    tables: List[str] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        normalized = _normalize_table_reference(text)
        if normalized and normalized not in tables:
            tables.append(normalized)

    def add_sql(sql: Any) -> None:
        if not sql:
            return
        for match in _SQL_TABLE_RE.finditer(str(sql)):
            add(match.group(1))

    add_sql(result.get("generatedSql"))
    for item in result.get("queryResults") or []:
        if not isinstance(item, dict):
            continue
        add(item.get("tableName"))
        add_sql(item.get("sql"))
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        add(item.get("tableName"))
        add_sql(item.get("sql"))
    return tables


def _iter_result_row_groups(result: Dict[str, Any]) -> Iterable[List[Dict[str, Any]]]:
    """遍历评估结果中所有可能带坐标的行数据。"""
    groups: List[Any] = []
    groups.append(result.get("rawResults"))
    for item in result.get("queryResults") or []:
        if isinstance(item, dict):
            groups.append(item.get("rows"))
    for item in result.get("results") or []:
        if isinstance(item, dict):
            groups.append(item.get("rows"))
    query_result = result.get("queryResult")
    if isinstance(query_result, dict):
        groups.append(query_result.get("sampleData"))
    for group in groups:
        if isinstance(group, list) and group and isinstance(group[0], dict):
            yield group


def result_has_geo_rows(result: Dict[str, Any]) -> bool:
    """判断评估结果本身是否已带经纬度行（前端可直接识别，无需补充）。"""
    for rows in _iter_result_row_groups(result):
        columns = list(rows[0].keys())
        if _find_lng_lat_pair(columns):
            return True
    return False


def result_has_data_rows(result: Dict[str, Any]) -> bool:
    """判断评估结果是否包含任何可展示的数据行（纯知识问答不补地图）。"""
    for _rows in _iter_result_row_groups(result):
        return True
    return False


def _tokenize(text: str) -> set:
    """把问题切成 2~4 字片段，用于确定性语义匹配。"""
    normalized = re.sub(r"\s+", "", str(text or "").casefold())
    tokens: set = set()
    for size in (2, 3, 4):
        for index in range(max(0, len(normalized) - size + 1)):
            token = normalized[index: index + size]
            if token in _STOP_GRAMS:
                continue
            if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", token):
                tokens.add(token)
    for token in re.findall(r"[a-z][a-z0-9_]{2,}", normalized):
        tokens.add(token)
    return tokens


def _result_text(result: Dict[str, Any], question: str, skill_name: str) -> str:
    """收集用于选表的上下文文本。"""
    parts: List[str] = [question or "", skill_name or ""]
    skill = result.get("skill")
    if isinstance(skill, dict):
        parts.extend([str(skill.get("name") or ""), str(skill.get("description") or "")])
    for item in result.get("queryResults") or []:
        if isinstance(item, dict):
            parts.extend([
                str(item.get("stepName") or ""),
                str(item.get("instruction") or ""),
                str(item.get("datasetName") or ""),
            ])
    for item in result.get("results") or []:
        if isinstance(item, dict):
            parts.extend([str(item.get("group") or ""), str(item.get("label") or "")])
    return " ".join(part for part in parts if part)


def _semantic_score(context_tokens: set, geo_table: GeoTable) -> int:
    """坐标表与问题的确定性语义得分。"""
    if not context_tokens:
        return 0
    score = 0
    for token in context_tokens:
        if token in geo_table.text_for_score:
            score += len(token)
    return score


def _kind_richness(kind: str) -> int:
    """图层丰富度：航迹 > 范围圈 > 标点。"""
    return {"routes": 2, "areas": 1}.get(kind, 0)


def choose_geo_table(
    geo_tables: Sequence[GeoTable],
    used_tables: Sequence[str],
    context_text: str,
) -> Optional[GeoTable]:
    """选择一张最合适的坐标表。

    规则：
    1. 评估实际涉及的表优先（可能多张，按图层丰富度排序）；
    2. 没有涉及表时做语义匹配，得分最高者胜出；
    3. 只有一张坐标表时直接使用；多张且语义无匹配时返回 None。
    """
    if not geo_tables:
        return None

    used_exact = {_normalize_table_reference(table) for table in used_tables}
    used_last = {_table_last_segment(table) for table in used_tables}

    matched: List[GeoTable] = []
    for table in geo_tables:
        normalized = _normalize_table_reference(table.table_name)
        if normalized in used_exact or _table_last_segment(normalized) in used_last:
            matched.append(table)
    if matched:
        return sorted(matched, key=lambda item: _kind_richness(item.kind), reverse=True)[0]

    tokens = _tokenize(context_text)
    scored = [(_semantic_score(tokens, table), table) for table in geo_tables]
    scored = [item for item in scored if item[0] > 0]
    if scored:
        scored.sort(key=lambda item: (item[0], _kind_richness(item[1].kind)), reverse=True)
        return scored[0][1]

    if len(geo_tables) == 1:
        return geo_tables[0]
    return None


def build_geo_sql(geo_table: GeoTable, dialect: str, limit: int = MAX_GEO_ROWS) -> str:
    """按数据库方言生成坐标明细 SQL。"""
    columns = ", ".join(geo_table.columns)
    condition = (
        f"{geo_table.lng_column} IS NOT NULL AND {geo_table.lat_column} IS NOT NULL"
    )
    order_column = geo_table.seq_column or ""
    normalized_dialect = normalize_database_dialect(
        geo_table.database_type, geo_table.database_product_name
    )
    if dialect:
        normalized_dialect = dialect

    if normalized_dialect == "sqlserver":
        sql = f"SELECT TOP {limit} {columns} FROM {geo_table.table_name} WHERE {condition}"
        if order_column:
            sql += f" ORDER BY {order_column}"
        return sql

    sql = f"SELECT {columns} FROM {geo_table.table_name} WHERE {condition}"
    if order_column:
        sql += f" ORDER BY {order_column}"
    if normalized_dialect in ("oracle", "ansi"):
        sql += f" FETCH FIRST {limit} ROWS ONLY"
    else:
        sql += f" LIMIT {limit}"
    return sql


def _to_number(value: Any) -> Optional[float]:
    """把单元格解析为数字。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _valid_coordinate(lng: float, lat: float) -> bool:
    """校验经纬度范围，过滤明显异常的数据。"""
    return -180 <= lng <= 180 and -90 <= lat <= 90


def _normalize_query_result(result: Dict[str, Any]) -> tuple[List[str], List[Dict[str, Any]]]:
    """统一 admin execute-sql 返回的列/行结构。"""
    raw_rows = result.get("rows", result.get("data", result.get("results", []))) or []
    raw_columns = result.get("columns", []) or []
    columns = [
        str(column.get("name") or column.get("columnName") or "")
        if isinstance(column, dict)
        else str(column)
        for column in raw_columns
    ]
    if not raw_rows:
        return columns, []
    if isinstance(raw_rows[0], dict):
        rows = [row for row in raw_rows if isinstance(row, dict)]
        if not columns and rows:
            columns = list(rows[0].keys())
        return columns, rows
    if not columns:
        columns = [f"column_{index + 1}" for index in range(len(raw_rows[0]))]
    return columns, [dict(zip(columns, row)) for row in raw_rows]


def _build_props(row: Dict[str, Any], geo_table: GeoTable) -> Optional[Dict[str, Any]]:
    """提取地图弹窗属性（剔除坐标与空值）。"""
    excluded = {
        _norm(geo_table.lng_column),
        _norm(geo_table.lat_column),
        _norm(geo_table.name_column),
        _norm(geo_table.seq_column),
        _norm(geo_table.entity_column),
        *(_norm(column) for column in geo_table.radius_columns),
    }
    props: Dict[str, Any] = {}
    for key, value in row.items():
        if _norm(key) in excluded or value is None or value == "":
            continue
        props[str(key)] = value
    return props or None


def build_geo_features(
    geo_table: GeoTable,
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """把坐标行转换为 markers/routes/areas。"""
    lng_key = geo_table.lng_column
    lat_key = geo_table.lat_column
    name_key = geo_table.name_column
    # 没有业务名称列时，用实体编号（如 unit_id）作为标点/区域名称
    label_key = name_key or geo_table.entity_column
    points: List[Dict[str, Any]] = []
    routes: List[Dict[str, Any]] = []
    areas: List[Dict[str, Any]] = []
    kind = geo_table.kind

    if kind == "routes":
        groups: Dict[str, List[Tuple[float, float, Dict[str, Any]]]] = {}
        for row in rows:
            lng = _to_number(row.get(lng_key))
            lat = _to_number(row.get(lat_key))
            if lng is None or lat is None or not _valid_coordinate(lng, lat):
                continue
            entity = str(
                row.get(geo_table.entity_column)
                or row.get(name_key)
                or "目标"
            )
            seq = _to_number(row.get(geo_table.seq_column)) if geo_table.seq_column else None
            groups.setdefault(entity, []).append((seq or 0.0, lng, lat, row))
        for entity, group in groups.items():
            group.sort(key=lambda item: item[0])
            if len(group) < 2:
                continue
            routes.append({
                "name": entity[:40],
                "points": [{"lng": lng, "lat": lat} for _seq, lng, lat, _row in group],
            })
        if routes:
            return {"routes": routes}
        # 航迹点不足 2 个时降级为标点
        kind = "points"

    if kind == "areas":
        for row in rows:
            lng = _to_number(row.get(lng_key))
            lat = _to_number(row.get(lat_key))
            if lng is None or lat is None or not _valid_coordinate(lng, lat):
                continue
            base_name = str(row.get(label_key) or "范围区域")[:32]
            props = _build_props(row, geo_table)
            for radius_column in geo_table.radius_columns:
                radius = _to_number(row.get(radius_column))
                if radius is None or radius <= 0:
                    continue
                label = ""
                normalized_radius = _norm(radius_column)
                if "detect" in normalized_radius or "探测" in normalized_radius:
                    label = "探测范围"
                elif "strike" in normalized_radius or "打击" in normalized_radius:
                    label = "打击范围"
                elif "coverage" in normalized_radius or "覆盖" in normalized_radius:
                    label = "覆盖范围"
                areas.append({
                    "name": f"{base_name}·{label}" if label else base_name,
                    "lng": lng,
                    "lat": lat,
                    "radiusKm": radius,
                    "props": props,
                })
        if areas:
            return {"areas": areas}

    for row in rows:
        lng = _to_number(row.get(lng_key))
        lat = _to_number(row.get(lat_key))
        if lng is None or lat is None or not _valid_coordinate(lng, lat):
            continue
        name = str(row.get(label_key) or f"坐标点 {len(points) + 1}")[:40]
        points.append({
            "name": name,
            "lng": lng,
            "lat": lat,
            "props": _build_props(row, geo_table),
        })
    return {"markers": points} if points else {}


def _build_artifact(
    database_id: str,
    geo_table: GeoTable,
    dialect: str,
) -> Optional[Dict[str, Any]]:
    """执行坐标查询并组装评估产物。"""
    sql = build_geo_sql(geo_table, dialect, MAX_GEO_ROWS)
    try:
        query_result = execute_sql_on_database(
            database_id, sql, timeout=GEO_QUERY_TIMEOUT
        )
    except Exception as exc:
        logger.warning("空间分布坐标查询失败（%s）：%s", geo_table.table_name, exc)
        return None

    if not query_result.get("success"):
        logger.warning(
            "空间分布坐标查询未成功（%s）：%s",
            geo_table.table_name,
            str(query_result.get("message") or "")[:200],
        )
        return None

    columns, rows = _normalize_query_result(query_result)
    if not rows:
        return None

    total_rows = len(rows)
    rows = rows[:MAX_GEO_ROWS]
    geo = build_geo_features(geo_table, rows)
    if not any(geo.values()):
        return None

    purpose = (
        f"基于「{geo_table.dataset_name}」的坐标明细，为态势页面提供空间分布。"
        f"字段：{', '.join(geo_table.columns)}"
    )
    return {
        "artifactId": "geo1",
        "name": f"空间分布 · {geo_table.dataset_name}"[:160],
        "purpose": purpose[:1000],
        "mode": "detail",
        "columns": columns or list(rows[0].keys()),
        "rows": rows,
        "totalRows": total_rows,
        "truncated": total_rows > len(rows),
        "geo": geo,
    }


def collect_geo_artifact(
    database_id: str,
    question: str,
    result: Dict[str, Any],
    skill_name: str = "",
) -> Optional[Dict[str, Any]]:
    """为评估结果生成一个「空间分布」产物。

    Args:
        database_id: 评估使用的数据源 id
        question: 用户评估问题
        result: 评估 result 字典
        skill_name: 评估使用的 Skill 名称

    Returns:
        坐标产物字典；无坐标表、查询失败或结果本身已带坐标时返回 None。
    """
    if not database_id or not isinstance(result, dict):
        return None
    if str(result.get("type") or "") not in ARTIFACT_RESULT_TYPES:
        return None
    if result.get("geoArtifacts"):
        return None
    if not result_has_data_rows(result):
        logger.info("评估结果没有数据行，跳过空间分布产物补充")
        return None
    if result_has_geo_rows(result):
        logger.info("评估结果已带经纬度列，跳过空间分布产物补充")
        return None

    try:
        datasets = fetch_skill_datasets_for_database(database_id, include_columns=True)
    except Exception as exc:
        logger.warning("读取数据源目录失败，跳过空间分布产物：%s", exc)
        return None

    geo_tables: List[GeoTable] = []
    seen: set = set()
    for dataset in datasets or []:
        geo_table = inspect_dataset(dataset)
        if not geo_table or geo_table.identity in seen:
            continue
        seen.add(geo_table.identity)
        geo_tables.append(geo_table)
    if not geo_tables:
        logger.info("数据源中没有可用的坐标表，跳过空间分布产物")
        return None

    used_tables = extract_used_tables(result)
    context_text = _result_text(result, question, skill_name)
    chosen = choose_geo_table(geo_tables, used_tables, context_text)
    if not chosen:
        logger.info("没有与当前评估问题匹配的坐标表，跳过空间分布产物")
        return None

    dialect = normalize_database_dialect(
        chosen.database_type, chosen.database_product_name
    )
    artifact = _build_artifact(database_id, chosen, dialect)
    if artifact:
        logger.info(
            "已生成空间分布产物：表=%s，图层=%s，行数=%s",
            chosen.table_name,
            chosen.kind,
            artifact.get("totalRows"),
        )
    return artifact
