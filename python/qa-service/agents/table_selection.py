"""数据表选择与意图路由共享工具。

提取自 langgraph_workflow.py（已退役），供 react_workflow 和测试复用。
"""

from __future__ import annotations

import re
from typing import Dict

# ═══════════════════════════════════════════════════════════════════════════
# 名称处理与分词
# ═══════════════════════════════════════════════════════════════════════════


def _normalize_name(name: str) -> str:
    """名称归一化：去空格、标点、转小写，便于中文/英文混合匹配。

    与 indicator-service/main.py 中的 _normalize_name 保持一致。
    """
    if not name:
        return ""
    return re.sub(r'[\s\u3000（）()【】\[\]《》<>「」""''\-_·、，。！？：；]+', '', name).lower()


def _char_bigrams(text: str) -> set:
    """对中文友好的 2-gram 分词：返回字符串的二元字符集合。

    与 indicator-service/main.py 中的 _char_bigrams 保持一致，
    不引入 jieba 依赖。
    """
    if not text or len(text) < 2:
        return set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _jaccard(set_a: set, set_b: set) -> float:
    """计算两个集合的 Jaccard 相似度。"""
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 统一相似度计算
# ═══════════════════════════════════════════════════════════════════════════


def _text_similarity(query_bigrams: set, target_bigrams: set) -> float:
    """统一的文本相似度（0.0 ~ 1.0）。

    综合 Jaccard（结构相似）和归一化重叠率（关键词覆盖），
    各占 50% 权重。不设硬阈值，让连续分值自然拉开差距。

    Args:
        query_bigrams:   查询文本（问题+计划）的 bigram 集合
        target_bigrams:  目标文本（表名/注释/数据集名/描述）的 bigram 集合

    Returns:
        0.0 ~ 1.0 的相似度
    """
    if not query_bigrams or not target_bigrams:
        return 0.0
    # Jaccard：集合层面的结构相似度
    j = _jaccard(query_bigrams, target_bigrams)
    # 归一化重叠：查询中有多大比例的关键词出现在目标中（避免长文本天然高分）
    normalized_overlap = len(query_bigrams & target_bigrams) / len(query_bigrams)
    return j * 0.5 + normalized_overlap * 0.5


# ═══════════════════════════════════════════════════════════════════════════
# 表筛选
# ═══════════════════════════════════════════════════════════════════════════


def _extract_table_info(t):
    """从 all_tables 元素中提取 (表名, 表注释) 二元组。

    兼容 list[str] 和 list[dict] 两种输入格式：
    - str: 直接作为表名，注释为空
    - dict: 取 tableName 字段，tableComment 字段可能存在
    """
    if isinstance(t, dict):
        return t.get("tableName", ""), t.get("tableComment", "")
    return str(t), ""


def pick_relevant_tables(all_tables, analysis_plan, question, max_tables=12, table_metadata=None):
    """
    从全部表名中筛选最相关的表，用于减少后续 LLM prompt 长度。

    兼容 list[str] 和 list[dict]（含 tableComment）两种输入。
    使用统一的 2-gram 语义相似度对每个信号源打分，按来源可靠性加权累加。
    动态阈值：取得分 > 0 的表，按得分降序排列，上限 max_tables（默认 12），
    同分优先非系统表。

    打分模型：
        score = Σ (权重 × similarity(query+plan, signal))

        信号源权重（按可靠性降序）：
        - 计划中明确提及表名       → +200（LLM 已判断相关，最强信号）
        - 数据集名称（人工标注）      → ×25
        - 数据集描述（人工标注）      → ×20
        - 表 DDL 注释             → ×15
        - 物理表名（常为技术命名）    → ×10

    Args:
        all_tables:     所有表名（list[str] 或 list[dict]）
        analysis_plan:  orchestrator 生成的分析计划文本
        question:       用户原始问题文本
        max_tables:     最多返回的表数量（默认 12）
        table_metadata: 可选，{tableName: {name, description}} 数据集元数据

    Returns:
        排序后的表名列表（最多 max_tables 个元素）
    """
    if not all_tables:
        return []

    # ── 统一转换为 (name, comment) 列表 ──
    table_infos = []
    for t in all_tables:
        name, comment = _extract_table_info(t)
        if name:
            table_infos.append((name, comment, t))

    # 只有极少量表（≤3）时才跳过打分直接返回全部
    if len(table_infos) <= 3:
        return [name for name, _, _ in table_infos]

    # ── 合并查询上下文：问题 + 分析计划，一次性匹配 ──
    context_text = (question or '') + ' ' + (analysis_plan or '')
    ctx_norm = _normalize_name(context_text)
    ctx_bigrams = _char_bigrams(ctx_norm)

    scores = {name: 0 for name, _, _ in table_infos}
    plan_lower = (analysis_plan or '').lower()

    for name, comment, _ in table_infos:
        name_norm = _normalize_name(name)
        name_bigrams = _char_bigrams(name_norm)
        comment_norm = _normalize_name(comment)
        comment_bigrams = _char_bigrams(comment_norm)

        # ── 信号 1：物理表名（技术命名，语义弱，权重最低）──
        scores[name] += int(10 * _text_similarity(ctx_bigrams, name_bigrams))

        # ── 信号 2：物理表 DDL 注释（有限语义）──
        scores[name] += int(15 * _text_similarity(ctx_bigrams, comment_bigrams))

        # ── 信号 3：数据集名称（人工标注，语义准确，权重高）──
        if table_metadata and name in table_metadata:
            meta = table_metadata[name]
            ds_name = _normalize_name(meta.get("name", ""))
            ds_name_bigrams = _char_bigrams(ds_name)
            scores[name] += int(25 * _text_similarity(ctx_bigrams, ds_name_bigrams))

            ds_desc = _normalize_name(meta.get("description", ""))
            ds_desc_bigrams = _char_bigrams(ds_desc)
            scores[name] += int(20 * _text_similarity(ctx_bigrams, ds_desc_bigrams))

        # ── 信号 4：LLM 在分析计划中明确提及表名 → +200（最强信号）──
        if name_lower in plan_lower:
            scores[name] += 200

    # ── 信号 5：分析计划中的 "表 xxx" 或 "TABLE xxx" 显式引用 → +200 ──
    table_pattern = re.findall(
        r'(?:表\s*|TABLE\s+)([a-zA-Z_][a-zA-Z0-9_]*)',
        analysis_plan or '', re.IGNORECASE
    )
    for match in table_pattern:
        for name, _, _ in table_infos:
            if name.lower() == match.lower():
                scores[name] += 200

    # ── 排序：按得分降序，同分时非系统表优先 ──
    def _sort_key(item):
        name, score = item
        is_sys = name.lower().startswith(('ass_', 'sys_', 'test_', 'tbl_'))
        return (-score, 1 if is_sys else 0, name.lower())

    sorted_tables = sorted(scores.items(), key=_sort_key)
    top = [name for name, s in sorted_tables if s > 0]

    if not top:
        # 没有任何表得分 > 0（如问题与所有表无关），返回非系统表兜底
        non_sys = [name for name, _, _ in table_infos
                   if not name.lower().startswith(('ass_', 'sys_', 'test_', 'tbl_'))]
        top = non_sys[:max_tables] if non_sys else [name for name, _, _ in table_infos[:max_tables]]

    return top[:max_tables]


# ═══════════════════════════════════════════════════════════════════════════
# 意图路由
# ═══════════════════════════════════════════════════════════════════════════


def route_by_intent(state: Dict) -> str:
    """
    根据 orchestrator 识别出的 query_type 决定下一个节点。

    路由规则：
        - general_analysis → simple_analysis（通用分析，无需查库）
        - 无 database_id → simple_analysis（无数据源，走通用分析）
        - 有 database_id → data_explore（数据库查询，走 SQL 管线）

    Args:
        state: 当前状态（含 query_type / database_id）

    Returns:
        下一个节点的名称字符串
    """
    query_type = state.get("query_type", "")
    database_id = state.get("database_id", "")
    # 有数据源时，不允许 LLM 把问题路由到 general_analysis（兜底保护）
    if query_type == "general_analysis" and database_id:
        return "data_explore"
    if query_type == "general_analysis":
        return "simple_analysis"
    if not database_id:
        return "simple_analysis"
    return "data_explore"
