"""字段解析器 —— 注解优先、列名启发式兜底的统一判定入口。

对应方案《ipage-注解优先与零回归降级方案》的 4.1 节，四层优先级：

1. ① 结构化注解（数据集级 / 字段级 ``semantic_json``，P1 已打通通道）；
2. ② 业务含义文本（``businessMeaning``／``annotation`` 中的元结构词与单位词）；
3. ③ 列名启发式（与改造前的实现**逐字一致**，见下方 ``find_*`` 函数）；
4. ④ 常量默认（unitKind=other、shape=dot、无坐标 …）。

**零回归的构造性保证**：任何 ①② 层命中失败都等价于该层不存在；当 ``spec`` 为 ``None``
或注解为空时，本模块的每个方法都只走 ③/④，输出与改造前完全相同。

② 层设有一道闸门：仅当数据源**已声明结构化语义**（数据集级或任一字段级 ``semantic_json``
非空）时才启用。否则历史数据（只有 ``businessMeaning`` 自由文本）会因"文本里恰好含
『时间/状态』"而被隐式改变行为 —— 闸门保证存量数据集逐字节不变。

本模块零 IO、零 LLM：只读 ``dimension_graph`` 已解析进内存的表结构，可纯单测。
"""
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.dimension_graph import TableSpec

logger = logging.getLogger("ipage-service")

# ── 常量：实体大类 → 运行时 unitKind（决策 D1：ground_facility 映射为 facility）──
ENTITY_KIND_TO_UNIT: Dict[str, str] = {
    "air": "aircraft",
    "base": "base",
    "ground_facility": "facility",
    # 军事领域新增 6 类：运行时 unitKind 与注解值同名
    "unit": "unit",
    "person": "person",
    "organization": "organization",
    "task": "task",
    "area": "area",
    "resource": "resource",
    "other": "other",
}

# 能力画像（profiler）产出的军事通用实体大类；仅作为内部 unitKind 使用，不写入注解契约
PROFILE_ENTITY_KINDS: frozenset = frozenset({
    "platform", "platform_air", "platform_ground", "platform_sea",
    "unit", "facility", "person", "organization", "event", "task",
    "area", "resource", "sensor", "target", "threat", "other",
})

# 中文语义词典（与 profiler 保持一致；只在英文/注解未命中时兜底，保证存量数据零回归）
_CN_LNG_TOKENS = ("经度", "东经")
_CN_LAT_TOKENS = ("纬度", "北纬")
_CN_TIME_TOKENS = ("时间", "日期", "时刻", "上报", "发生", "记录")
_CN_FACTION_TOKENS = ("阵营", "归属", "隶属", "敌我", "所属", "编成", "派别")
_CN_STATUS_TOKENS = ("状态", "结果", "健康", "告警")
_CN_TYPE_TOKENS = ("类别", "类型", "分类", "种类")
_CN_ID_TOKENS = ("编号", "标识", "编码")
_CN_NAME_TOKENS = ("名称", "呼号", "姓名")
_CN_SEQ_TOKENS = ("序号", "顺序", "点号")
_CN_RADIUS_TOKENS = ("半径", "作用范围", "覆盖范围")

# 物理表名 → 地图单位语义（③ 层兜底；注解缺失时保持历史行为，不删除）
UNIT_KIND_BY_TABLE: Dict[str, str] = {
    "mock_enemy_threat": "threat",
    "mock_target": "target",
    "mock_aircraft": "base",
    "mock_strike_event": "event_strike",
    "mock_battle_damage": "event_damage",
    "mock_recon_event": "event_recon",
}

# 象形符号注册表键（与 page-kit.js 的 SIT_SHAPES、semantic-schema.json 的 enum 三方对齐）
SYMBOL_KEYS: frozenset = frozenset({
    "fighter", "awacs", "recon", "bomber", "base", "sam", "radar",
    "coastal", "flag", "depot", "fuel", "anchor", "runway", "tower",
    "boom", "cross", "magnifier", "ring", "dot",
})

# 阵营规范值 → 语义色（其余规范值由 PALETTE 稳定分配，见 faction_color）
FACTION_SEMANTIC_COLORS: Dict[str, str] = {
    "蓝方": "#1d4ed8", "红方": "#dc2626",
    "blue": "#1d4ed8", "red": "#dc2626",
}
# 与 page-kit.js 的 PALETTE 同序同色，保证前后端取色口径一致
FACTION_PALETTE: Tuple[str, ...] = (
    "#1d4ed8", "#dc2626", "#d97706", "#059669", "#7c3aed", "#0891b2", "#be185d", "#65a30d",
)

# 状态规范键（与 page-kit.js 的 STATUS_STYLES 注册表对齐；不新增视觉，仅归一语义）
STATUS_KEYS: frozenset = frozenset({"destroyed", "miss", "critical", "heavy", "light"})

# 消息模板：注解声明了但字段不存在 / 值域不识别时的中文提示（写入数据集 warnings）
NOTE_COLUMN_MISSING = "语义注解声明的列 {col} 在结果集中不存在，已忽略该注解"
NOTE_SYMBOL_UNKNOWN = "语义注解的符号键 {symbol} 不在运行时光符号注册表内，已忽略"
NOTE_STATUS_UNKNOWN = "状态注解的规范值 {value} 不在运行时状态键内，已忽略"


def _stable_index(value: str, size: int) -> int:
    """按内容取稳定索引（md5，避免 Python 字符串哈希随机化导致跨进程不一致）。"""
    digest = hashlib.md5(str(value).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, size)


def faction_color(canonical: str) -> str:
    """规范阵营值 → 颜色；未命中语义色时按 PALETTE 稳定分配（同值同色）。"""
    text = str(canonical or "").strip()
    if not text:
        return ""
    if text in FACTION_SEMANTIC_COLORS:
        return FACTION_SEMANTIC_COLORS[text]
    return FACTION_PALETTE[_stable_index(text, len(FACTION_PALETTE))]


# ──────────────────────────────────────────────────────────────────
# ③ 层：列名启发式（与改造前 researcher 中的实现逐字一致，函数体不变）
# ──────────────────────────────────────────────────────────────────

def find_coord_pairs(columns: List[str]) -> List[Tuple[str, str, str]]:
    """识别成对经纬度列，返回 (前缀, lng列, lat列)；前缀 '' 表示裸 lng/lat。

    英文前后缀优先（与改造前逐字一致），中文「经度/纬度」作为兜底追加在末尾。
    """
    lngs, lats = {}, {}
    cn_lng = cn_lat = None
    for c in columns:
        low = str(c).lower()
        if low in ("lng", "lon", "longitude"):
            lngs[""] = c
        elif low in ("lat", "latitude"):
            lats[""] = c
        elif low.endswith("_lng") or low.endswith("_lon"):
            lngs[low[:-4]] = c
        elif low.endswith("_lat"):
            lats[low[:-4]] = c
        elif any(tok in low for tok in _CN_LNG_TOKENS) and not cn_lng:
            cn_lng = c
        elif any(tok in low for tok in _CN_LAT_TOKENS) and not cn_lat:
            cn_lat = c
    pairs = [(prefix, lng, lats[prefix]) for prefix, lng in lngs.items() if prefix in lats]
    if cn_lng and cn_lat:
        pairs.append(("", cn_lng, cn_lat))
    return pairs


def find_field(columns: List[str], candidates: Tuple[str, ...]) -> Optional[str]:
    """在列名中按包含关系找字段（如 seq/time/name/radius）。"""
    lowered = {str(c).lower(): c for c in columns}
    for cand in candidates:
        for low, original in lowered.items():
            if cand in low:
                return original
    return None


def radius_kind(col_name: str) -> str:
    """按半径列名判圈类型：strike→打击圈，detect/recon→侦察(探测)圈，无线索返回空串。

    一张表可能有**多根半径列**（如 detect_radius_km + strike_radius_km），
    必须用列名把"半径值"与"圈类型"配对，否则会出现
    "半径取探测值、标签却写打击范围"的错配，且另一根半径被整个忽略。
    """
    low = str(col_name or "").lower()
    if "strike" in low or "打击" in low or "攻击" in low:
        return "strike"
    if ("detect" in low or "recon" in low or "scout" in low or "search" in low
            or "侦察" in low or "探测" in low or "搜索" in low):
        return "recon"
    return ""


# 档案/管理类日期关键词：服役日期、成立日期、创建时间等是静态属性，不是态势事件时间，
# 绝不能作为地图时间轴字段（否则会把时间轴拉到数年前）
NON_EVENT_TIME_KEYS = ("commission", "found", "establish", "birth", "create", "update", "valid",
                       "服役", "成立", "创建", "更新", "出生", "有效")


def find_time_field(columns: List[str]) -> Optional[str]:
    """识别态势时间字段（记录/事件发生时间）。

    匹配优先级：
      1. 明确的事件时间列（record_time/event_time/recon_time/destroyed_time 等）
      2. 以 _time 结尾的列（排除服役、成立、创建等档案管理时间）
      3. 含 date/时间 的列兜底（同样排除档案日期，如 commission_date）
      4. 中文时间词兜底（上报时间/发生时刻等），同样排除档案词
    """
    lows = [str(c).lower() for c in columns]
    event_cands = ("record_time", "event_time", "recon_time", "destroyed_time",
                   "occur_time", "detect_time", "strike_time", "damage_time")
    for cand in event_cands:
        for low, original in zip(lows, columns):
            if cand in low:
                return original
    for low, original in zip(lows, columns):
        if (low == "time" or low.endswith("_time")) \
                and not any(k in low for k in NON_EVENT_TIME_KEYS):
            return original
    for low, original in zip(lows, columns):
        if ("date" in low or "时间" in str(original)) \
                and not any(k in low for k in NON_EVENT_TIME_KEYS):
            return original
    for low, original in zip(lows, columns):
        if any(tok in low for tok in _CN_TIME_TOKENS) \
                and not any(k in low for k in NON_EVENT_TIME_KEYS):
            return original
    return None


# ── ② 层信号：业务含义文本中的元结构词（仅在结构化语义已声明时启用）──
_TIME_MEANING_TOKENS = ("事件时间", "记录时间", "发生时间", "观测时间", "时间")
_STATUS_MEANING_TOKENS = ("状态", "结果", "受损", "毁伤")
_TYPE_MEANING_TOKENS = ("类别", "类型", "分类", "种类")
_ALTITUDE_MEANING_TOKENS = ("高度", "海拔")
_SPEED_MEANING_TOKENS = ("速度", "速率")
_HEADING_MEANING_TOKENS = ("航向", "朝向")


class FieldResolver:
    """单个数据集的字段解析器（注解优先，列名启发式兜底）。"""

    def __init__(self, spec: Optional[TableSpec], columns: List[str],
                 table_name: str = "", profile: Optional[Dict[str, Any]] = None):
        """初始化。

        Args:
            spec: 数据集结构摘要（含两级语义注解）；None 表示无元数据，
                此时所有方法只走列名启发式，与改造前行为一致。
            columns: 本次取数结果集的列名（注解声明的列必须在此存在才生效）。
            table_name: 物理表名（③ 层表名映射兜底用）。
            profile: 能力画像（profiler 产出）；注解缺失时作为第二优先级来源。
        """
        self.spec = spec
        self.columns: List[str] = [str(c) for c in (columns or [])]
        self.table_name = str(table_name or "")
        self.profile: Dict[str, Any] = profile if isinstance(profile, dict) else {}
        # 维度关系图（由 build_resolver 注入；用于注解值域采样比对，可为 None）
        self.graph: Any = None
        self._lower_map = {c.lower(): c for c in self.columns}
        # 数据集级注解
        semantic = getattr(spec, "semantic", None) or {}
        self.dataset_semantic: Dict[str, Any] = semantic if isinstance(semantic, dict) else {}
        # ② 层闸门：只有"已声明结构化语义"的数据源才启用文本兜底，保证存量数据不变
        self.textual_fallback_enabled = bool(
            self.dataset_semantic
            or any((meta or {}).get("semantic") for meta in
                   (getattr(spec, "columns", None) or {}).values())
        )
        # 注解问题提示（调用方写入数据集 warnings，失败不阻断）
        self.notes: List[str] = []

    # ── 列存在性校验（防止"注解写了结果集里没有的列"造成半生效）──

    def _existing(self, column: Any) -> Optional[str]:
        """注解声明的列名是否存在；不存在返回 None 并留提示。"""
        name = str(column or "").strip()
        if not name:
            return None
        if name in self.columns:
            return name
        low = name.lower()
        if low in self._lower_map:
            return self._lower_map[low]
        self.notes.append(NOTE_COLUMN_MISSING.format(col=name))
        return None

    def _semantic_of(self, column: str) -> Dict[str, Any]:
        """取字段级语义注解（无 spec 或无注解返回空字典）。"""
        meta = (getattr(self.spec, "columns", None) or {}).get(column) or {}
        semantic = meta.get("semantic")
        return semantic if isinstance(semantic, dict) else {}

    def _meaning_of(self, column: str) -> str:
        """取字段业务含义文本（注解优先，其次是物理列注释）。"""
        meta = (getattr(self.spec, "columns", None) or {}).get(column) or {}
        return str(meta.get("meaning") or "")

    # ── ②.5 层：能力画像（注解缺失时的第二优先级来源）──────────────
    # 画像由 profiler 确定性产出，不写入注解契约；只对结果集中真实存在的列生效。

    def _profile_cap(self) -> Dict[str, Any]:
        """取画像能力段（无画像返回空字典）。"""
        cap = self.profile.get("capabilities") if isinstance(self.profile, dict) else None
        return cap if isinstance(cap, dict) else {}

    def _existing_quiet(self, column: Any) -> Optional[str]:
        """画像列存在性检查：不存在时**不写提示**（画像不是注解，缺列不代表注解失效）。"""
        name = str(column or "").strip()
        if not name:
            return None
        if name in self.columns:
            return name
        return self._lower_map.get(name.lower())

    def _existing_pair(self, lng: Any, lat: Any) -> Optional[Tuple[str, str]]:
        """画像坐标列必须都存在于结果集，才认为有效。"""
        lng_col = self._existing_quiet(lng)
        lat_col = self._existing_quiet(lat)
        if lng_col and lat_col and lng_col != lat_col:
            return lng_col, lat_col
        return None

    def profile_geo_pair(self) -> Optional[Tuple[str, str]]:
        """画像坐标对（投影坐标不参与地图渲染）。"""
        geo = self._profile_cap().get("geo") or {}
        if str(geo.get("coordType") or "geographic") == "projected":
            return None
        return self._existing_pair(geo.get("lng"), geo.get("lat"))

    def profile_time_column(self) -> Optional[str]:
        """画像事件时间列。"""
        cap = self._profile_cap().get("time") or {}
        return self._existing_quiet(cap.get("column"))

    def profile_seq_column(self) -> Optional[str]:
        """画像轨迹点序号列。"""
        entity = self._profile_cap().get("entity") or {}
        return self._existing_quiet(entity.get("seq"))

    def profile_entity_key(self) -> Optional[str]:
        """画像实体键列（航迹拆分、实体编号）。"""
        entity = self._profile_cap().get("entity") or {}
        return self._existing_quiet(entity.get("key"))

    def profile_name_column(self) -> Optional[str]:
        """画像名称列。"""
        entity = self._profile_cap().get("entity") or {}
        return self._existing_quiet(entity.get("name"))

    def profile_category_columns(self) -> List[str]:
        """画像类别列（按画像顺序，只保留结果集中存在的列）。"""
        cols = self._profile_cap().get("category") or []
        return [c for c in (self._existing_quiet(x) for x in cols) if c]

    def profile_faction_columns(self) -> List[str]:
        """画像归属/阵营列。"""
        cols = self._profile_cap().get("affiliation") or []
        return [c for c in (self._existing_quiet(x) for x in cols) if c]

    def profile_status_columns(self) -> List[str]:
        """画像状态列。"""
        cols = self._profile_cap().get("status") or []
        return [c for c in (self._existing_quiet(x) for x in cols) if c]

    def profile_radius_columns(self) -> List[str]:
        """画像半径列。"""
        geo = self._profile_cap().get("geo") or {}
        cols = geo.get("radius") or []
        return [c for c in (self._existing_quiet(x) for x in cols) if c]

    def profile_unit_kind(self) -> str:
        """画像实体大类（仅内部 unitKind，不写入注解契约）。"""
        entity = self._profile_cap().get("entity") or {}
        kind = str(entity.get("kind") or "").strip()
        return kind if kind in PROFILE_ENTITY_KINDS else ""

    def column_by_role(self, role: str) -> Optional[str]:
        """按字段角色找列（① 层）；多个同角色时按结构顺序取第一个。"""
        if not role:
            return None
        for column in self.columns:
            if str(self._semantic_of(column).get("role") or "").strip() == role:
                return column
        # 角色声明的列可能不在结果集（如聚合 SQL 未投影）：遍历全表结构兜底提示
        for column, meta in (getattr(self.spec, "columns", None) or {}).items():
            if str((meta or {}).get("semantic", {}).get("role") or "").strip() == role:
                self.notes.append(NOTE_COLUMN_MISSING.format(col=column))
                break
        return None

    def _by_meaning(self, tokens: Tuple[str, ...],
                    exclude: Tuple[str, ...] = ()) -> Optional[str]:
        """② 层：业务含义文本命中元结构词（仅在闸门开启时生效）。"""
        if not self.textual_fallback_enabled:
            return None
        for column in self.columns:
            meaning = self._meaning_of(column)
            if not meaning:
                continue
            low = str(column).lower()
            if any(k in low for k in exclude):
                continue
            if any(token in meaning for token in tokens):
                return column
        return None

    # ── 坐标 ──────────────────────────────────────────────────────

    def annotated_coord_pair(self) -> Optional[Tuple[str, str]]:
        """① 层坐标对（仅注解 / 字段角色命中；无注解返回 None，**不回落列名**）。"""
        geometry = self.dataset_semantic.get("geometry")
        if isinstance(geometry, dict):
            lng = self._existing(geometry.get("lngColumn"))
            lat = self._existing(geometry.get("latColumn"))
            if lng and lat:
                return lng, lat
        # 字段级 role=lng/lat 兜底（注解了角色但未写 geometry）
        role_lng, role_lat = self.column_by_role("lng"), self.column_by_role("lat")
        if role_lng and role_lat and role_lng != role_lat:
            return role_lng, role_lat
        return None

    def coord_pair(self) -> Optional[Tuple[str, str]]:
        """返回 (lng列, lat列) 或 None（注解 → 画像 → 列名启发式）。"""
        annotated = self.annotated_coord_pair()
        if annotated:
            return annotated
        profiled = self.profile_geo_pair()
        if profiled:
            return profiled
        pairs = find_coord_pairs(self.columns)
        return (pairs[0][1], pairs[0][2]) if pairs else None

    # ── 时间 / 排序 ───────────────────────────────────────────────

    def event_time_column(self) -> Optional[str]:
        """事件时间列：注解 → role=time → 画像 → 含义文本 → 列名启发式。"""
        annotated = self._existing(self.dataset_semantic.get("eventTimeColumn"))
        if annotated:
            return annotated
        role_col = self.column_by_role("time")
        if role_col:
            return role_col
        profiled = self.profile_time_column()
        if profiled:
            return profiled
        meaning_col = self._by_meaning(_TIME_MEANING_TOKENS, exclude=NON_EVENT_TIME_KEYS)
        if meaning_col:
            return meaning_col
        return find_time_field(self.columns)

    def seq_column(self) -> Optional[str]:
        """航迹点排序列（不含时间回退）：role=seq → 画像 → 列名含 seq。"""
        return (self.column_by_role("seq")
                or self.profile_seq_column()
                or find_field(self.columns, ("seq",)))

    def sort_column(self) -> Optional[str]:
        """航迹点排序字段：seq 列 → 事件时间列。"""
        return self.seq_column() or self.event_time_column()

    def type_column(self, fallback: Optional[str] = None) -> Optional[str]:
        """类型/类别列：含义文本 → 画像类别列 → 传入的列名启发式结果。"""
        profiled = self.profile_category_columns()
        return self._by_meaning(_TYPE_MEANING_TOKENS) or (profiled[0] if profiled else None) \
            or fallback

    def altitude_column(self) -> Optional[str]:
        """高度列：role=altitude → 含义文本 → 列名。"""
        return (self.column_by_role("altitude")
                or self._by_meaning(_ALTITUDE_MEANING_TOKENS)
                or find_field(self.columns, ("altitude", "alt_")))

    def speed_column(self) -> Optional[str]:
        """速度列：role=speed → 含义文本 → 列名。"""
        return (self.column_by_role("speed")
                or self._by_meaning(_SPEED_MEANING_TOKENS)
                or find_field(self.columns, ("speed",)))

    def heading_column(self) -> Optional[str]:
        """航向列：role=heading → 含义文本 → 列名。"""
        return (self.column_by_role("heading")
                or self._by_meaning(_HEADING_MEANING_TOKENS)
                or find_field(self.columns, ("heading",)))

    # ── 航迹拆分 ─────────────────────────────────────────────────

    def track_group_columns(self, id_field: Optional[str] = None,
                            mission_field: Optional[str] = None,
                            name_field: Optional[str] = None) -> List[str]:
        """航迹分组列。

        注解 ``trackGroupKey`` **必须全部命中结果集**才生效（防半生效拆错航迹）；
        否则回落历史口径：实体 ID 列（或名称列）+ 任务列。
        """
        annotated = self.dataset_semantic.get("trackGroupKey")
        if isinstance(annotated, list) and annotated:
            resolved = [self._existing(col) for col in annotated]
            if all(resolved):
                return [col for col in resolved if col]
        # 画像兜底：注解未声明拆分键时，用画像识别的实体键/名称列
        id_field = id_field or self.profile_entity_key()
        name_field = name_field or self.profile_name_column()
        group = [id_field or name_field] if (id_field or name_field) else []
        if mission_field and mission_field not in group:
            group.append(mission_field)
        return group

    # ── 半径与范围圈 ──────────────────────────────────────────────

    def radius_columns(self) -> List[str]:
        """半径列：注解 → role → 画像 → 列名（含中文「半径」）；不丢任何一圈。"""
        result: List[str] = []
        annotated = None
        geometry = self.dataset_semantic.get("geometry")
        if isinstance(geometry, dict):
            annotated = self._existing(geometry.get("radiusColumn"))
        if annotated:
            result.append(annotated)
        role_col = self.column_by_role("radius")
        if role_col and role_col not in result:
            result.append(role_col)
        for column in self.profile_radius_columns():
            if column not in result:
                result.append(column)
        for column in self.columns:
            low = str(column).lower()
            if ("radius" in low or any(tok in low for tok in _CN_RADIUS_TOKENS)) \
                    and column not in result:
                result.append(column)
        return result

    def radius_kind_of(self, column: str) -> str:
        """半径列 → 圈类型：列名线索 → 含义文本线索（② 层，闸门开启时）→ 空串。"""
        kind = radius_kind(column)
        if kind:
            return kind
        if not self.textual_fallback_enabled:
            return ""
        meaning = self._meaning_of(column)
        if "打击" in meaning or "攻击" in meaning:
            return "strike"
        if "侦察" in meaning or "探测" in meaning or "搜索" in meaning:
            return "recon"
        return ""

    # ── 单位语义与符号 ───────────────────────────────────────────

    def unit_kind(self) -> str:
        """数据集单位大类：注解 entityKind → 画像实体类型 → 表名映射 → ''。"""
        entity_kind = str(self.dataset_semantic.get("entityKind") or "").strip()
        if entity_kind in ENTITY_KIND_TO_UNIT:
            return ENTITY_KIND_TO_UNIT[entity_kind]
        if entity_kind in PROFILE_ENTITY_KINDS:
            return entity_kind
        profiled = self.profile_unit_kind()
        if profiled:
            return profiled
        table = self.table_name.lower()
        return next((kind for token, kind in UNIT_KIND_BY_TABLE.items()
                     if token in table), "")

    def symbol(self, column: str = "") -> str:
        """象形符号键：字段 symbol → 数据集 symbolDefault；未命中注册表返回 ''。"""
        candidates = []
        if column:
            candidates.append(self._semantic_of(column).get("symbol"))
        candidates.append(self.dataset_semantic.get("symbolDefault"))
        for raw in candidates:
            key = str(raw or "").strip()
            if not key:
                continue
            if key in SYMBOL_KEYS:
                return key
            self.notes.append(NOTE_SYMBOL_UNKNOWN.format(symbol=key))
        return ""

    # ── 值域（过滤用原始值 / 展示用规范值）────────────────────────

    def value_term_map(self, column: str) -> Tuple[Set[str], Dict[str, str]]:
        """字段值映射解析（供实体过滤）。

        ``values`` 是"原始值 → 规范值"，``synonyms`` 是"别名 → 规范值"。
        SQL 过滤必须用**原始值**，因此返回：
            (标准值集合=原始值, {可匹配词: 原始值})
        可匹配词包含：原始值本身、规范值、同义词键。
        """
        semantic = self._semantic_of(column)
        values = semantic.get("values") if isinstance(semantic.get("values"), dict) else {}
        synonyms = semantic.get("synonyms") if isinstance(semantic.get("synonyms"), dict) else {}
        if not values and not synonyms:
            return set(), {}

        canonical_to_raw: Dict[str, str] = {}
        for raw, canonical in values.items():
            canonical_to_raw.setdefault(str(canonical), str(raw))
        standards = {str(raw) for raw in values.keys()}
        terms: Dict[str, str] = {}
        for raw in values.keys():
            terms[str(raw)] = str(raw)
        for canonical, raw in canonical_to_raw.items():
            terms.setdefault(str(canonical), raw)
        for alias, canonical in synonyms.items():
            raw = canonical_to_raw.get(str(canonical))
            if raw:
                terms.setdefault(str(alias), raw)
        return standards, terms

    def canonical_value(self, column: str, raw: Any) -> str:
        """原始值 → 规范值（无注解时原样返回，保证零回归）。"""
        if raw is None:
            return ""
        text = str(raw).strip()
        semantic = self._semantic_of(column)
        for key in ("values", "synonyms"):
            mapping = semantic.get(key)
            if isinstance(mapping, dict) and text in mapping:
                return str(mapping[text])
        return text

    def status_column(self, fallback: Optional[str] = None) -> Optional[str]:
        """状态列：role=status → 含义文本 → 画像状态列 → 传入的列名启发式结果。"""
        profiled = self.profile_status_columns()
        return (self.column_by_role("status")
                or self._by_meaning(_STATUS_MEANING_TOKENS)
                or (profiled[0] if profiled else None)
                or fallback)

    def status_key(self, column: str, raw: Any) -> str:
        """原始状态值 → 运行时状态键；未命中注册表返回 ''（回落中文词匹配）。"""
        if raw is None or not column:
            return ""
        canonical = self.canonical_value(column, raw)
        if canonical in STATUS_KEYS:
            return canonical
        semantic = self._semantic_of(column)
        if canonical and isinstance(semantic.get("values"), dict):
            self.notes.append(NOTE_STATUS_UNKNOWN.format(value=canonical))
        return ""

    # ── 阵营 ─────────────────────────────────────────────────────

    def faction_of(self, row: Dict[str, Any], column: Optional[str] = None,
                   fallback_unit: str = "", aircraft_index: Optional[Dict[str, Any]] = None,
                   track_id: str = "") -> Tuple[str, str]:
        """解析行的阵营：返回 (规范值, 颜色)。

        - ① 注解：仅当该列**配置了 values/synonyms 值映射且本次确实映射到了新值**时，
          才产出规范值 + 颜色（颜色由规范值推出）——保证 mock 等无值映射的数据源不产生颜色字段；
        - ③ 兜底（与改造前逐字一致）：原值恰为 `蓝方/红方` 则用之，否则查档案索引，
          再否则按表名含 ``enemy`` 判为蓝方；此时颜色为空，前端沿用原逻辑。
        """
        # ① 注解值映射
        if column:
            semantic = self._semantic_of(column)
            if semantic.get("values") or semantic.get("synonyms"):
                raw = row.get(column)
                raw_text = "" if raw is None else str(raw).strip()
                canonical = self.canonical_value(column, raw)
                if canonical and canonical != raw_text:
                    return canonical, faction_color(canonical)

        # ③ 列名启发式 / 画像 / 档案索引 / 表名兜底
        # 已知阵营值保持旧口径；未知归属值（如"我方/敌我/番号"）在无档案兜底时原样保留，
        # 供前端动态生成筛选条。
        raw_text = ""
        if column:
            raw = row.get(column)
            raw_text = "" if raw is None else str(raw).strip()
        val = raw_text or str(row.get("faction") or "").strip()
        if val in ("蓝方", "红方"):
            return val, ""
        index = aircraft_index or {}
        if track_id and track_id in index:
            indexed = str(index[track_id].get("faction") or "")
            if indexed in ("蓝方", "红方"):
                return indexed, ""
        if fallback_unit:
            return fallback_unit, ""
        # 只有画像确认该数据集存在归属列时，才保留红蓝之外的任意归属值；
        # 无画像的存量数据沿用旧口径（未知值返回空），保证零回归。
        if val and self.profile_faction_columns():
            return val, ""
        return "", ""

    def faction_column(self) -> Optional[str]:
        """阵营列：注解 → 画像归属列 → 列名 faction/camp/side → 中文归属词。"""
        for column in self.columns:
            semantic = self._semantic_of(column)
            if semantic.get("values") or semantic.get("synonyms"):
                if str(semantic.get("role") or "") in ("dimension", "name", ""):
                    meaning = self._meaning_of(column)
                    low = str(column).lower()
                    if "阵营" in meaning or low in ("faction", "camp", "side"):
                        return column
        profiled = self.profile_faction_columns()
        if profiled:
            return profiled[0]
        found = find_field(self.columns, ("faction", "camp", "side"))
        if found:
            return found
        return next((c for c in self.columns
                     if any(tok in str(c).lower() for tok in _CN_FACTION_TOKENS)), None)

    # ── 值域一致性提示（决策 D4）─────────────────────────────────

    def value_domain_note(self, column: str, sampled: Optional[List[str]]) -> str:
        """注解声明的原始值与真实采样值不一致时的中文提示（不阻断）。"""
        semantic = self._semantic_of(column)
        declared = set((semantic.get("values") or {}).keys()) if isinstance(
            semantic.get("values"), dict) else set()
        if not declared or not sampled:
            return ""
        missing = declared - {str(v) for v in sampled}
        if missing:
            return (f"字段 {column} 的注解值域与真实数据不一致（多出："
                    f"{'、'.join(sorted(missing)[:5])}）")
        return ""

    def value_domain_notes(self) -> List[str]:
        """对配置了值映射的列做一次采样比对，返回不一致提示。

        **默认不启用**（由 config.IPAGE_ANNOTATION_SAMPLE_CHECK 控制）：值域校验已左移到
        保存期（admin 的 AnnotationValidator），运行期改用零成本的 value_drift_notes。
        保留本方法供排障时打开开关复核。

        采样走 ``DimensionGraph.sample_values``（内部有缓存与失败降级），
        任何异常都静默跳过，绝不影响取数主流程。
        """
        if self.graph is None or self.spec is None:
            return []
        notes: List[str] = []
        for column in self.columns:
            values = self._semantic_of(column).get("values")
            if not isinstance(values, dict) or not values:
                continue
            try:
                sampled = self.graph.sample_values(self.spec.table, column)
            except Exception as exc:  # 采样仅为校验增强，失败不阻断
                logger.warning("注解值域采样失败 %s.%s: %s", self.spec.table, column, exc)
                continue
            note = self.value_domain_note(column, sampled)
            if note:
                notes.append(note)
        return notes

    def value_drift_notes(self, rows: List[Dict[str, Any]]) -> List[str]:
        """零成本值域漂移告警：用**已在内存的结果行**找出注解值域外的实际取值。

        不查库、不加延迟（决策 D4 的运行期形态）：保存时校验通过不代表业务数据不变，
        新增枚举若不提示，页面会静默少判一块，因此保留这条兜底。
        """
        if not rows:
            return []
        notes: List[str] = []
        for column in self.columns:
            values = self._semantic_of(column).get("values")
            if not isinstance(values, dict) or not values:
                continue
            declared = {str(key) for key in values.keys()}
            unknown: List[str] = []
            for row in rows:
                raw = row.get(column)
                if raw is None:
                    continue
                text = str(raw).strip()
                if not text or text in declared or text in unknown:
                    continue
                unknown.append(text)
                if len(unknown) >= 5:
                    break
            if unknown:
                notes.append(f"字段 {column} 出现注解值域外的取值：{'、'.join(unknown)}"
                             "（可能是新增枚举，建议更新注解）")
        return notes


def build_resolver(meta: Dict[str, Any], table_name: str,
                   columns: List[str],
                   profile: Optional[Dict[str, Any]] = None) -> FieldResolver:
    """按元数据构造解析器（复用 DimensionGraph 的缓存图；失败降级为纯列名启发式）。

    失败时返回 ``FieldResolver(None, columns, table_name)`` —— 与改造前行为一致，
    绝不因注解链路异常影响取数。``profile`` 未传入时只读 ``meta["_profiles"]``，
    **不主动触发画像构建**（避免取数阶段额外查库）。
    """
    spec: Optional[TableSpec] = None
    graph: Any = None
    try:
        from agent import dimension_graph  # 延迟导入，避免模块级循环依赖
        graph = dimension_graph.DimensionGraph.build(meta)
        if graph is not None:
            spec = graph.tables.get(str(table_name or ""))
    except Exception as exc:  # 注解为增强能力，失败不阻断
        logger.warning("构造字段解析器失败，本次退回列名启发式 table=%s: %s", table_name, exc)
        spec = None
        graph = None
    if profile is None and isinstance(meta, dict):
        profiles = meta.get("_profiles")
        if isinstance(profiles, dict):
            profile = (profiles.get("byTable") or {}).get(str(table_name or ""))
    resolver = FieldResolver(spec, columns, table_name, profile=profile)
    resolver.graph = graph
    return resolver
