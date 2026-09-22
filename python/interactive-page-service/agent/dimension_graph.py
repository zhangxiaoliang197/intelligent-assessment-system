"""维度关系图 —— 通用的外键发现 / 维度列识别 / 真实值采样。

设计目标（适配任意领域数据，零业务词汇）：
- 仅依据「数据集元数据（/export/for-llm）+ 数据库真实值」自动推导：
  1. 表间外键关系：列名 ``<x>_id`` + 目标表主键同名 / 表名单复数匹配；
  2. 候选维度文本列：低基数文本列、枚举注解列（类别/状态/阵营/名称等元结构）；
  3. 维度列真实值采样：GROUP BY 取分布，供实体匹配（value linking）。
- 不含任何领域词（不出现飞机/侦察机等），换库无需改代码。
- 领域语义（实体大类、字段角色、值映射、符号）来自数据源的 semantic_json 注解，
  本模块只负责**解析与缓存**，不做任何领域判断；注解变更由 admin 回调失效缓存。

注意：采样 SQL 全部走 admin-service 的只读执行端点（表名/列名来自元数据且经过
安全标识符校验），不允许任何外部输入拼接进 SQL。
"""
import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cache_registry
import semantic_validator
from store import admin_client

logger = logging.getLogger("ipage-service")

# 安全标识符（表名/列名只允许字母数字下划线$与中文，杜绝注入标点）
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_一-龥][A-Za-z0-9_$一-龥]*$")
# 外键列形态：xxx_id
_FK_COL_RE = re.compile(r"^(.+)_id$")
# 数值型物理类型（不参与文本维度采样）
_NUMERIC_TYPE_RE = re.compile(r"(int|decimal|numeric|float|double|real|number|bit|bool)", re.IGNORECASE)
_TEXT_TYPE_RE = re.compile(r"(char|text|clob|string|varchar)", re.IGNORECASE)

# 维度列的元结构信号（这些是描述"列用途"的词，不是业务词）
_STRUCT_MEANING_TOKENS = ("类别", "类型", "分类", "种类", "状态", "等级", "级别",
                          "阵营", "性质", "阶段", "枚举")
# 名称类列名信号（英文通用命名）
_NAME_COL_RE = re.compile(r"(^|_)(name|title|label|callsign|codename|alias)$", re.IGNORECASE)
# 自由文本列名排除信号（摘要/备注/描述等高基数长文本）
_EXCLUDE_COL_RE = re.compile(
    r"(summary|result|note|remark|comment|desc|description|content|text|message|"
    r"detail|reason|advice|log|sql|json|path|url|摘要|备注|描述|结论|说明|意见|原因)",
    re.IGNORECASE,
)
# businessMeaning 中的自由文本排除信号
_EXCLUDE_MEANING_TOKENS = ("摘要", "备注", "描述", "结论", "结果说明", "意见", "原因", "日志")

# 维度值采样上限：基数超过该值视为高基数列，不参与实体匹配
_MAX_DIMENSION_CARDINALITY = 50
# 外键链最大跳数（防止误连）
_MAX_FK_HOPS = 3

# 图缓存：key = (databaseId, 表名指纹, 语义注解指纹)；元数据或注解不变时复用，避免重复采样
_graph_cache: Dict[Tuple[str, Tuple[str, ...], str], "DimensionGraph"] = {}
_graph_lock = threading.Lock()


def parse_semantic(raw: Any) -> Dict[str, Any]:
    """解析 semantic_json 注解文本。

    未配置（None/空串/空白）返回 {}；格式非法返回 {} 并告警——
    此时消费侧按"未配置语义"处理，回退到 businessMeaning 的正则解析，行为与历史一致。
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning("语义注解不是合法 JSON，按未配置处理: %s", exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("语义注解必须是 JSON 对象，实际为 %s，按未配置处理", type(parsed).__name__)
        return {}
    return parsed


def annotated_geo_pair(schema: Dict[str, Any]) -> Tuple[str, str]:
    """数据集注解声明的坐标列对：geometry.lngColumn/latColumn 或字段 role=lng/lat。

    返回 (lng列, lat列)；未声明返回 ("", "")。供 Planner（地理能力判定）与
    prompts（数据集目录标注）共用，避免同一口径两处实现漂移。
    """
    semantic = parse_semantic((schema or {}).get("semanticJson"))
    geometry = semantic.get("geometry") if isinstance(semantic, dict) else None
    if isinstance(geometry, dict):
        lng = str(geometry.get("lngColumn") or "").strip()
        lat = str(geometry.get("latColumn") or "").strip()
        if lng and lat:
            return lng, lat
    role_lng = role_lat = ""
    for f in (schema or {}).get("fields") or (schema or {}).get("columns") or []:
        if not isinstance(f, dict):
            continue
        role = str(parse_semantic(f.get("semanticJson")).get("role") or "").strip()
        column = str(f.get("name") or f.get("column") or f.get("fieldName") or "")
        if not column:
            continue
        if role == "lng" and not role_lng:
            role_lng = column
        elif role == "lat" and not role_lat:
            role_lat = column
    if role_lng and role_lat:
        return role_lng, role_lat
    return "", ""


def column_name_geo_capable(schema: Dict[str, Any]) -> bool:
    """按列名启发式判断是否具备成对经纬度（历史口径，保留为兜底）。"""
    fields = (schema or {}).get("fields") or (schema or {}).get("columns") or []
    lngs, lats = [], []
    for f in fields:
        if not isinstance(f, dict):
            continue
        col = str(f.get("name") or f.get("column") or f.get("fieldName") or "").lower()
        if col.endswith("_lng") or col in ("lng", "lon", "longitude"):
            lngs.append(col)
        if col.endswith("_lat") or col in ("lat", "latitude"):
            lats.append(col)
    return bool(lngs and lats)


def _log_semantic_errors(level: str, table: str, column: str,
                         errors: List[str]) -> None:
    """记录语义注解格式问题（不阻断：admin 侧已拦截，这里兜住历史数据与脚本写入）。"""
    if not errors:
        return
    target = f"{table}.{column}" if column else table
    logger.warning("%s语义注解不合规 %s: %s", level, target, "; ".join(errors))


def _semantic_digest(specs: List["TableSpec"]) -> str:
    """按语义注解内容计算指纹；注解变更即换缓存键，行为立即生效。"""
    digest = hashlib.sha1()
    for spec in sorted(specs, key=lambda s: s.table):
        digest.update(spec.table.encode("utf-8"))
        digest.update(json.dumps(spec.semantic, sort_keys=True,
                                 ensure_ascii=False, default=str).encode("utf-8"))
        for col in sorted(spec.columns):
            digest.update(col.encode("utf-8"))
            digest.update(json.dumps(spec.columns[col].get("semantic") or {},
                                     sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8"))
    return digest.hexdigest()


def clear_caches(database_id: Optional[str] = None,
                 tables: Optional[Any] = None) -> int:
    """清理维度图缓存及其内部的维度值采样缓存，返回清理条目数。

    Args:
        database_id: 数据源标识；空表示不限数据源
        tables: 变更表名列表；空表示该数据源全量清理
    """
    wanted = {str(t) for t in (tables or []) if t}
    removed = 0
    with _graph_lock:
        for key in list(_graph_cache):
            db_id, fingerprint = key[0], key[1]
            if database_id and db_id != database_id:
                continue
            if wanted and not (set(fingerprint) & wanted):
                continue
            graph = _graph_cache.pop(key)
            graph._value_cache.clear()
            removed += 1
    return removed


cache_registry.register_cache("dimension_graph.graph", clear_caches)


def _singularize(token: str) -> str:
    """英文表名常见复数转单数（regions→region, categories→category）。"""
    t = token.lower()
    if t.endswith("ies") and len(t) > 3:
        return t[:-3] + "y"
    if t.endswith("ses") and len(t) > 3:
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss") and len(t) > 2:
        return t[:-1]
    return t


@dataclass
class TableSpec:
    """单个数据集（物理表）的结构摘要。"""
    table: str
    dataset_id: str
    # column → {type, meaning, pk, semantic}
    columns: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pk_columns: List[str] = field(default_factory=list)
    # 数据集级领域语义（semantic_json 解析结果；空 dict 表示未配置）
    semantic: Dict[str, Any] = field(default_factory=dict)

    def is_textual(self, col: str) -> bool:
        """该列是否像文本列（用于采样前粗筛）。"""
        meta = self.columns.get(col)
        if not meta:
            return False
        ctype = str(meta.get("type") or "")
        if _NUMERIC_TYPE_RE.search(ctype):
            return False
        return bool(not ctype or _TEXT_TYPE_RE.search(ctype))


@dataclass
class DimensionColumn:
    """候选维度文本列。"""
    table: str
    column: str
    meaning: str
    by_name: bool          # 是否由列名结构信号选中（名称列）
    by_meaning: bool       # 是否由 businessMeaning 结构信号选中


class DimensionGraph:
    """同库全部表的结构关系图。"""

    def __init__(self, database_id: str):
        self.database_id = database_id
        self.tables: Dict[str, TableSpec] = {}
        # table → {fk_column: (ref_table, ref_column)}
        self.edges: Dict[str, Dict[str, Tuple[str, str]]] = {}
        # 维度列缓存：(table, col) → 真实值列表（None=采样失败/非低基数）
        self._value_cache: Dict[Tuple[str, str], Optional[List[str]]] = {}
        self._dim_columns: Optional[List[DimensionColumn]] = None

    # ── 构建 ──────────────────────────────────────────────────────

    @classmethod
    def build(cls, meta: Dict[str, Any]) -> Optional["DimensionGraph"]:
        """从 /export/for-llm 元数据构建关系图（带缓存）。

        元数据异常或无表时返回 None，调用方按"无实体过滤能力"降级。
        """
        if not isinstance(meta, dict) or not meta.get("success"):
            return None
        data = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        schemas = data.get("schemas") if isinstance(data, dict) else None
        if not isinstance(schemas, list) or not schemas:
            return None
        database_id = str(data.get("databaseId") or meta.get("databaseId") or "default")

        # 语义格式规范随元数据下发，注入本地校验器（与 admin 侧同一份 schema）
        semantic_validator.set_schema(data.get("semanticSchema") if isinstance(data, dict) else None)

        specs: List[TableSpec] = []
        for schema in schemas:
            if not isinstance(schema, dict):
                continue
            table = str(schema.get("tableName") or "").strip()
            ds_id = str(schema.get("datasetId") or schema.get("id") or "").strip()
            if not table or not ds_id or not _SAFE_IDENT_RE.match(table):
                continue
            raw_fields = schema.get("fields") or schema.get("columns") or []
            spec = TableSpec(table=table, dataset_id=ds_id)
            spec.semantic = parse_semantic(schema.get("semanticJson"))
            if spec.semantic:
                _log_semantic_errors("数据集", table, "",
                                     semantic_validator.validate_dataset(spec.semantic))
            for f in raw_fields:
                if not isinstance(f, dict):
                    continue
                col = str(f.get("column") or f.get("name") or f.get("fieldName") or "").strip()
                if not col or not _SAFE_IDENT_RE.match(col):
                    continue
                meaning = str(f.get("businessMeaning") or f.get("annotation")
                              or f.get("comment") or "")
                is_pk = bool(f.get("isPrimaryKey"))
                col_semantic = parse_semantic(f.get("semanticJson"))
                if col_semantic:
                    _log_semantic_errors("字段", table, col,
                                         semantic_validator.validate_field(col_semantic))
                spec.columns[col] = {
                    "type": str(f.get("type") or f.get("dataType") or ""),
                    "meaning": meaning,
                    "pk": is_pk,
                    "semantic": col_semantic,
                }
                if is_pk:
                    spec.pk_columns.append(col)
            specs.append(spec)

        if not specs:
            return None

        fingerprint = tuple(sorted(s.table for s in specs))
        # 语义注解指纹参与缓存键：注解变更即视为另一份图，无需重启服务
        cache_key = (database_id, fingerprint, _semantic_digest(specs))
        with _graph_lock:
            cached = _graph_cache.get(cache_key)
            if cached is not None:
                return cached
            graph = cls(database_id)
            for spec in specs:
                graph.tables[spec.table] = spec
            graph._discover_edges()
            # 同一 (数据源, 表集合) 只保留最新一份，避免注解多轮修改后堆积旧图
            for stale in [k for k in _graph_cache
                          if k != cache_key and k[0] == database_id and k[1] == fingerprint]:
                _graph_cache.pop(stale, None)
            _graph_cache[cache_key] = graph
            return graph

    def _discover_edges(self) -> None:
        """纯结构规则发现外键边：A.<x>_id → B 主键同名列 / B 表名与 x 单复数匹配。"""
        table_items = list(self.tables.items())
        for table, spec in table_items:
            out: Dict[str, Tuple[str, str]] = {}
            for col in spec.columns:
                m = _FK_COL_RE.match(col)
                if not m:
                    continue
                if col in spec.pk_columns:
                    continue  # 本表主键（自引用 ID）不算外键
                token = m.group(1).lower()
                if token in {"id", "guid", "uid", "uuid"}:
                    continue
                # 规则1：目标表存在与该列同名的主键（最强信号）
                pk_hits = [
                    (t, s) for t, s in table_items
                    if col in s.pk_columns and t != table
                ]
                if len(pk_hits) == 1:
                    out[col] = (pk_hits[0][0], col)
                    continue
                if len(pk_hits) > 1:
                    # 多个表都有同名主键：歧义，放弃该列（保守）
                    continue
                # 规则2：token 与表名单数形式匹配（如 region_id→regions）
                name_hits = []
                for t, s in table_items:
                    if t == table:
                        continue
                    low = t.lower()
                    bare = low.split(".")[-1]
                    stem = bare[5:] if bare.startswith("mock_") else bare
                    candidates = {_singularize(stem), stem}
                    if token in candidates:
                        name_hits.append((t, token if token in s.columns else None))
                if len(name_hits) == 1 and name_hits[0][1]:
                    out[col] = (name_hits[0][0], name_hits[0][1])
            if out:
                self.edges[table] = out

    # ── 维度列与采样 ──────────────────────────────────────────────

    def dimension_columns(self) -> List[DimensionColumn]:
        """发现全部候选维度文本列（结构粗筛，真实基数在采样时最终确认）。"""
        if self._dim_columns is not None:
            return self._dim_columns
        result: List[DimensionColumn] = []
        for table, spec in self.tables.items():
            fk_cols = set(self.edges.get(table, {}).keys())
            for col, meta in spec.columns.items():
                if col in spec.pk_columns or col in fk_cols:
                    continue
                meaning = str(meta.get("meaning") or "")
                low = col.lower()
                if _EXCLUDE_COL_RE.search(low):
                    continue
                if any(tok in meaning for tok in _EXCLUDE_MEANING_TOKENS):
                    continue
                by_name = bool(_NAME_COL_RE.search(low))
                enum_like = _enum_like_meaning(meaning)
                by_meaning = enum_like or any(tok in meaning for tok in _STRUCT_MEANING_TOKENS)
                # 显式声明值域（字段级 values/synonyms 注解）即为维度列，不依赖列名与业务含义文本：
                # 这是"字段命名完全不一致"时仍能做实体过滤的关键；无注解时该条件恒为假。
                col_semantic = meta.get("semantic") if isinstance(meta.get("semantic"), dict) else {}
                if not (by_name or by_meaning) and not (col_semantic.get("values")
                                                        or col_semantic.get("synonyms")):
                    continue
                if not spec.is_textual(col):
                    continue
                result.append(DimensionColumn(table, col, meaning, by_name, by_meaning))
        self._dim_columns = result
        return result

    def sample_values(self, table: str, col: str) -> Optional[List[str]]:
        """采样维度列真实值（GROUP BY 分布，按频次倒序）；失败或高基数返回 None。

        无枚举/结构信号的纯名称列放宽到真实基数校验；含枚举注解的列即便采样
        失败也可由 entity_filter 直接使用注解枚举，因此这里返回 None 不阻断。
        """
        cache_key = (table, col)
        if cache_key in self._value_cache:
            return self._value_cache[cache_key]
        spec = self.tables.get(table)
        values: Optional[List[str]] = None
        if spec is not None and _SAFE_IDENT_RE.match(table) and _SAFE_IDENT_RE.match(col):
            sql = (f"SELECT {col} AS dim_value, COUNT(*) AS cnt "
                   f"FROM {table} GROUP BY {col} ORDER BY cnt DESC")
            try:
                payload = admin_client.execute_dataset_sql(spec.dataset_id, sql)
                if isinstance(payload, dict) and payload.get("success"):
                    rows = payload.get("rows") or []
                    vals = [str(r.get("dim_value")) for r in rows
                            if isinstance(r, dict) and r.get("dim_value") not in (None, "")]
                    if len(vals) <= _MAX_DIMENSION_CARDINALITY:
                        values = vals
            except Exception as exc:  # 采样仅为增强能力，失败不阻断
                logger.warning("维度列采样失败 %s.%s: %s", table, col, exc)
        self._value_cache[cache_key] = values
        return values

    # ── 外键路径 ─────────────────────────────────────────────────

    def shortest_fk_path(self, from_table: str, to_table: str,
                         max_hops: int = _MAX_FK_HOPS) -> Optional[List[Tuple[str, str, str, str]]]:
        """BFS 找 from_table → to_table 的最短外键路径。

        Returns:
            边列表 [(from_t, fk_col, to_t, ref_col), ...]；from==to 时返回 []；
            不可达返回 None。
        """
        if from_table == to_table:
            return []
        if from_table not in self.tables or to_table not in self.tables:
            return None
        queue: List[Tuple[str, List[Tuple[str, str, str, str]]]] = [(from_table, [])]
        visited = {from_table}
        while queue:
            current, path = queue.pop(0)
            for fk_col, (ref_table, ref_col) in self.edges.get(current, {}).items():
                if ref_table in visited:
                    continue
                edge = (current, fk_col, ref_table, ref_col)
                new_path = path + [edge]
                if ref_table == to_table:
                    return new_path
                if len(new_path) < max_hops:
                    visited.add(ref_table)
                    queue.append((ref_table, new_path))
        return None

    def local_column(self, table: str, column: str) -> bool:
        """列是否属于该表。"""
        spec = self.tables.get(table)
        return bool(spec and column in spec.columns)


# ── businessMeaning 枚举/同义词解析（通用，不含业务词）──────────────

_ENUM_SPLIT_RE = re.compile(r"[\/、|，,；;]")
# A=B / A:B / A即B / A 指 B 形式的同义词映射
_ALIAS_PAIR_RES = (
    re.compile(r"([一-龥A-Za-z0-9]{2,8})\s*[=＝:：]\s*([一-龥A-Za-z0-9]{1,8})"),
    re.compile(r"([一-龥A-Za-z0-9]{2,8})\s*即\s*([一-龥A-Za-z0-9]{1,8})"),
)


def _enum_like_meaning(meaning: str) -> bool:
    """businessMeaning 是否像枚举声明（分隔符切出 ≥2 个短词）。"""
    if not meaning:
        return False
    # 只在括号/冒号后的取值区切分，避免把整句注解切碎
    zone = meaning
    bracket = re.search(r"[（(]([^（）()]{2,60})[）)]", meaning)
    if bracket:
        zone = bracket.group(1)
    tokens = [t.strip() for t in _ENUM_SPLIT_RE.split(zone) if t.strip()]
    good = [t for t in tokens if 1 <= len(t) <= 10 and not t.isdigit()]
    return len(good) >= 2


def parse_enum_tokens(meaning: str) -> List[str]:
    """从注解的枚举声明区切分出候选取值（如「类别：侦察机/轰炸机」→ 两个值）。"""
    if not meaning:
        return []
    zone = meaning
    bracket = re.search(r"[（(]([^（）()]{2,60})[）)]", meaning)
    if bracket:
        zone = bracket.group(1)
    tokens = [t.strip() for t in _ENUM_SPLIT_RE.split(zone) if t.strip()]
    return [t for t in tokens if 1 <= len(t) <= 10 and not t.isdigit()]


def parse_alias_map(meaning: str) -> Dict[str, str]:
    """解析注解中的同义词映射（如「我方=蓝方」→ {"我方": "蓝方"}）。

    仅当等号右侧恰好是注解枚举中的真实值时才由调用方采纳，避免把
    「key=value 配置」之类的说明误当同义词。
    """
    aliases: Dict[str, str] = {}
    if not meaning:
        return aliases
    for pattern in _ALIAS_PAIR_RES:
        for left, right in pattern.findall(meaning):
            left, right = left.strip(), right.strip()
            if len(left) >= 2 and right and left not in aliases:
                aliases[left] = right
    return aliases
