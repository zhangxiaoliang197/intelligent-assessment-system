"""实体过滤解析（Value Linking + 外键链 ID 传播）。

通用机制，不含任何业务词汇：
1. 遍历 dimension_graph 发现的低基数维度列，把用户问题中的词与「真实采样值 +
   字段注解枚举值 + 注解同义词映射」做匹配，未命中任何值则完全不加过滤（零误伤）；
2. 命中值位于关联维度表时，沿外键链逐跳解析为事实表外键 ID 白名单；
3. 命中列就在事实本表时，直接对该列过滤。

最终产出 ``{事实表名: {列名: {允许值集合}}}``，由 researcher 在 rows 进入
数据包之前做确定性行级过滤，地图/图表/表格/文案口径天然一致。
"""
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from store import admin_client
from agent.dimension_graph import (
    DimensionGraph,
    parse_alias_map,
    parse_enum_tokens,
)

logger = logging.getLogger("ipage-service")

# 通用分析词：即使恰好等于某维度值也不触发过滤（"打击任务/最近态势"类泛指问题零误伤）
_STOP_TERMS = {
    "态势", "情况", "数据", "分析", "统计", "最近", "当前", "分布", "趋势", "整体",
    "总体", "概览", "概况", "报告", "查询", "展示", "显示", "相关", "信息", "详情",
    "明细", "记录", "活动", "任务", "事件", "时间", "区域", "位置", "范围", "能力",
    "效果", "综合", "如何", "什么", "哪些", "多少", "数量", "指标", "对比", "汇总",
    "飞机", "战机", "军机", "装备", "单位", "目标",
}
# 2 字短值后接这些泛化分析后缀时，视为泛指而非枚举引用（"打击情况""巡逻活动"）
_GENERIC_SUFFIXES = ("情况", "态势", "活动", "任务", "效果", "数据", "事件", "能力",
                     "区域", "行动", "记录", "信息", "分布", "统计", "分析", "部署",
                     "安排", "计划", "报告")
# 2 字短值后接这些元词时，说明用户在显式引用该维度，应保留（"打击阶段""巡逻状态"）
_META_SUFFIXES = ("阶段", "状态", "类型", "类别", "种类", "等级", "级别", "分类", "枚举")
# 对立指代词：仅对恰好 2 值的枚举列、且注解已给出一方映射时，推导另一方
_FIRST_SIDE_TERMS = ("我方", "己方", "本方", "我军", "我方阵营")
_OPPOSITE_TERMS = ("敌方", "敌人", "对方", "对手", "对面", "敌军")
# 单跳 IN 列表分片大小
_IN_BATCH = 400
# 值长度参与包含匹配的区间
_MIN_VALUE_LEN = 2
_MAX_VALUE_LEN = 12


def _sql_literal(value: str) -> str:
    """转义 SQL 字符串字面量。"""
    return "'" + str(value).replace("'", "''") + "'"


def _is_generic_short_value(query: str, value: str) -> bool:
    """2 字短值在问题中是否为泛指用法（后接泛化分析后缀、且非显式维度引用）。"""
    if len(value) != 2:
        return False
    idx = query.find(value)
    while idx != -1:
        tail = query[idx + len(value):]
        head2 = query[max(0, idx - 2):idx]
        if tail.startswith(_META_SUFFIXES):
            return False  # 显式引用维度，保留
        if head2.endswith(_META_SUFFIXES[:2]):  # 如"在打击阶段"
            return False
        if tail.startswith(_GENERIC_SUFFIXES):
            return True
        idx = query.find(value, idx + 1)
    return False


def _build_column_vocabulary(graph: DimensionGraph, dc) -> Tuple[Set[str], Dict[str, str]]:
    """构建单个维度列的匹配词典：标准值集合 + {别名: 标准值}。

    标准值来源：真实采样值 ∪ 注解枚举词；
    别名来源：注解中的 A=B 映射，且右侧 B 必须是标准值（防止误解析）。
    """
    standards: Set[str] = set()
    sampled = graph.sample_values(dc.table, dc.column)
    if sampled:
        standards.update(v for v in sampled if _MIN_VALUE_LEN <= len(v) <= _MAX_VALUE_LEN)
    enum_tokens = parse_enum_tokens(dc.meaning)
    standards.update(t for t in enum_tokens
                     if _MIN_VALUE_LEN <= len(t) <= _MAX_VALUE_LEN)

    aliases: Dict[str, str] = {}
    for left, right in parse_alias_map(dc.meaning).items():
        # 只有映射右侧落在标准值内才采纳（"我方=蓝方"且蓝方是该列真实值）
        matched_right = next((v for v in standards if v == right or right in v or v in right), "")
        if matched_right and len(left) >= 2 and left not in standards:
            aliases[left] = matched_right
    return standards, aliases


def _link_entities(query: str, graph: DimensionGraph) -> List[Dict[str, Any]]:
    """把问题文本链接到维度列真实值。

    Returns:
        命中列表 [{table, column, values:set, terms:[...]}]，按列聚合。
    """
    hits_by_col: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for dc in graph.dimension_columns():
        standards, aliases = _build_column_vocabulary(graph, dc)
        if not standards:
            continue
        matched: Set[str] = set()
        terms: List[str] = []

        # 1) 同义词映射（我方→蓝方 等）
        for alias, std in aliases.items():
            if alias in query and alias not in _STOP_TERMS:
                matched.add(std)
                terms.append(alias)

        # 2) 真实值/枚举值包含匹配
        for value in sorted(standards, key=len, reverse=True):
            if value in _STOP_TERMS or value not in query:
                continue
            if _is_generic_short_value(query, value):
                continue
            matched.add(value)
            terms.append(value)

        # 3) 二值枚举的对立推导（注解已给出一方同义词时，"敌方"→ 另一方）
        sampled = graph.sample_values(dc.table, dc.column) or list(standards)
        two_values = [v for v in dict.fromkeys(sampled) if v in standards]
        if len(two_values) == 2 and aliases and any(t in query for t in _OPPOSITE_TERMS):
            known_side = next((std for std in aliases.values() if std in two_values), "")
            if known_side:
                other = next(v for v in two_values if v != known_side)
                matched.add(other)
                terms.append("对立指代")

        if matched:
            key = (dc.table, dc.column)
            hits_by_col[key] = {
                "table": dc.table,
                "column": dc.column,
                "values": matched,
                "terms": terms,
            }
    return list(hits_by_col.values())


def _distinct_values(graph: DimensionGraph, table: str, select_col: str,
                     where_col: str, ids: Set[str]) -> Set[str]:
    """执行 SELECT DISTINCT select_col FROM table WHERE where_col IN (ids)，自动分片。"""
    spec = graph.tables.get(table)
    if spec is None or not ids:
        return set()
    result: Set[str] = set()
    ids_list = list(ids)
    for start in range(0, len(ids_list), _IN_BATCH):
        batch = ids_list[start:start + _IN_BATCH]
        in_clause = ",".join(_sql_literal(v) for v in batch)
        sql = (f"SELECT DISTINCT {select_col} AS out_value "
               f"FROM {table} WHERE {where_col} IN ({in_clause})")
        try:
            payload = admin_client.execute_dataset_sql(spec.dataset_id, sql)
        except Exception as exc:
            logger.warning("外键链解析 SQL 失败 %s: %s", table, exc)
            return set()
        if not isinstance(payload, dict) or not payload.get("success"):
            logger.warning("外键链解析失败 %s: %s", table, str(payload.get("message"))[:160])
            return set()
        for row in payload.get("rows") or []:
            if isinstance(row, dict) and row.get("out_value") not in (None, ""):
                result.add(str(row.get("out_value")))
    return result


def _propagate_hit(graph: DimensionGraph, hit_table: str, hit_column: str,
                   hit_values: Set[str], target_table: str
                   ) -> Optional[Dict[str, Set[str]]]:
    """把维度表命中值沿外键链传播为目标事实表的 {列: ID白名单}。

    同表命中：直接 {hit_column: values}；
    跨表命中：BFS 最短路径（≤3 跳），逐跳 SELECT DISTINCT 解析。
    """
    if target_table == hit_table:
        if graph.local_column(target_table, hit_column):
            return {hit_column: set(hit_values)}
        return None

    path = graph.shortest_fk_path(target_table, hit_table)
    if not path:
        return None

    # 末端维度表：取被最后一条边引用列（维度表主键）在命中值下的 ID 集合
    last_edge = path[-1]
    dim_ref_col = last_edge[3]
    ids = _distinct_values(graph, hit_table, dim_ref_col, hit_column, set(hit_values))
    if not ids:
        return None

    # 从倒数第二条边反向传播到事实表（不查事实表本身）：
    # 边 E_i=(a, fk_a, b, ref_b)：在 a 上以 fk_a 过滤，输出前一条边引用 a 的列
    for i in range(len(path) - 2, 0, -1):
        edge = path[i]
        prev_edge = path[i - 1]
        out_col = prev_edge[3]  # a 表被更前一条边引用的列
        ids = _distinct_values(graph, edge[0], out_col, edge[1], ids)
        if not ids:
            return None

    # 白名单落在事实表的第一条边外键列上
    return {path[0][1]: ids}


def resolve_scope(query: str, graph: Optional[DimensionGraph],
                  target_tables: List[str]) -> Tuple[Dict[str, Dict[str, Set[str]]],
                                                     List[Dict[str, Any]]]:
    """实体过滤主入口。

    Args:
        query: 用户原始问题
        graph: 维度关系图（None 时返回空过滤，行为同现状）
        target_tables: planner 实际选中的事实表名集合

    Returns:
        (scope, hits_desc)
        scope: {table: {column: set(允许值)}}，空 dict 表示不加任何过滤；
        hits_desc: 命中描述（用于 sql_log / warning 文案）。
    """
    if graph is None or not query or not target_tables:
        return {}, []
    try:
        hits = _link_entities(query, graph)
    except Exception as exc:
        logger.warning("实体匹配失败，本次不做实体过滤: %s", exc)
        return {}, []
    if not hits:
        return {}, []

    scope: Dict[str, Dict[str, Set[str]]] = {}
    for target in dict.fromkeys(target_tables):
        if target not in graph.tables:
            continue
        merged: Dict[str, Set[str]] = {}
        for hit in hits:
            part = _propagate_hit(graph, hit["table"], hit["column"],
                                  hit["values"], target)
            if not part:
                continue
            for col, ids in part.items():
                if col in merged:
                    # 同一事实表同一列被多个维度条件约束 → 交集（AND 语义）
                    merged[col] &= ids
                else:
                    merged[col] = set(ids)
        # 交集后为空意味着条件互相矛盾，保留空集（如实呈现空态，不回退全量）
        if merged:
            scope[target] = merged

    hits_desc = [{"table": h["table"], "column": h["column"],
                  "values": sorted(h["values"]), "terms": h["terms"]}
                  for h in hits]
    if scope:
        logger.info("实体过滤解析完成: hits=%d scope_tables=%d",
                    len(hits), len(scope))
    return scope, hits_desc
