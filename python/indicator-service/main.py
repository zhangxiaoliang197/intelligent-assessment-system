from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Generator
import json
import os
import tempfile
import re
import uuid
import logging
from datetime import datetime

from utils import http_get, http_post, http_post_stream, fetch_available_databases, create_stream_response
from session import (
    ensure_session, get_recent_messages, get_session_stage, set_session_stage,
    set_pending_indicators, get_pending_indicators, clear_pending_indicators,
    add_message, get_all_sessions, delete_session, build_context, save_sessions,
    MAX_CONTEXT
)
from intent import (
    is_concept_query, is_new_question, is_query_confirm, is_query_deny,
    match_database
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("indicator-service")

app = FastAPI(
    title="指标分析服务",
    description="智能分析评估指标体系",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from config import (
    QA_SERVICE_URL, ADMIN_SERVICE_URL, KNOWLEDGE_SERVICE_URL, EVALUATION_API_URL,
    MAX_CONTEXT_ROUNDS
)


def _build_query_start_text(database_name: str, database_id: str,
                            selected_indicator_names: Optional[List[str]] = None,
                            variant: str = "confirm") -> str:
    """构建指标查询开始的确认消息文案。

    Args:
        database_name: 数据源名称
        database_id: 数据源 ID（名称缺省时用）
        selected_indicator_names: 用户勾选的指标名称列表；非空时文案列出具体指标名
        variant: "confirm" → A2 分支（用户说"查询"）；"by_name" → A3 分支（用户提供数据源名）

    Returns:
        确认消息文本（含换行）
    """
    db_label = database_name or database_id
    if selected_indicator_names:
        names_str = "、".join(selected_indicator_names)
        if variant == "by_name":
            return f"好的，使用数据源「{db_label}」查询指标「{names_str}」...\n\n"
        return f"好的，正在使用数据源「{db_label}」查询指标「{names_str}」...\n\n"
    if variant == "by_name":
        return f"好的，使用数据源「{db_label}」开始查询指标...\n\n"
    return f"好的，正在使用数据源「{db_label}」查询全部指标...\n\n"

def _classify_query(query: str) -> str:
    """先调用 qa-service 的 LLM 分类接口，失败则用关键词兜底。

    Returns:
        "concept_qa" / "indicator_analysis" / "general_chat"
    """
    try:
        data = http_post(f"{QA_SERVICE_URL}/qa/classify-query", {"query": query}, timeout=10)
        if data:
            classification = data.get("classification", "")
            if classification in ("concept_qa", "indicator_analysis", "general_chat"):
                return classification
    except Exception as e:
        logger.warning(f"Classify query via qa-service failed: {e}")

    # 兜底：关键词匹配
    if is_concept_query(query):
        return "concept_qa"
    return "indicator_analysis"


def _handle_concept_qa_stream(session_id: str, query: str) -> Generator[str, None, None]:
    """概念问答核心处理逻辑。

    1. 不发送任何 step 事件
    2. 调用 knowledge-service 检索知识库
    3. 调用 admin-service 获取已配置指标定义
    4. 构建概念问答 prompt
    5. 调用 qa-service 的 /qa/chat/stream 流式接口
    6. 累积完整 LLM 回答，最后一次性输出 text + result 事件
    """
    # ── 检索知识库 ──
    kb_results = []
    try:
        data = http_post(f"{KNOWLEDGE_SERVICE_URL}/knowledge/search", {"query": query, "top_k": 3}, timeout=30)
        if data:
            kb_results = data.get("results", [])
    except Exception as e:
        logger.warning(f"Knowledge search failed: {e}")

    # ── 获取已配置指标定义 ──
    indicator_defs = []
    try:
        data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if data and data.get("success"):
            indicator_defs = data.get("indicators", [])
    except Exception as e:
        logger.warning(f"Failed to fetch indicators from admin: {e}")

    # ── 构建概念问答 prompt ──
    kb_text = ""
    if kb_results:
        kb_text = "\n\n## 知识库参考信息：\n"
        for i, r in enumerate(kb_results):
            kb_text += f"\n[{i + 1}] {r.get('title', '未知')}\n{r.get('content', '')}\n"

    ind_text = ""
    if indicator_defs:
        ind_text = "\n\n## 系统中已配置的指标定义：\n"
        for ind in indicator_defs:
            name = ind.get("name", "")
            desc = ind.get("description", "")
            formula = ind.get("formula", "")
            category = ind.get("category", "")
            parts = [f"- **{name}**"]
            if category:
                parts.append(f"分类: {category}")
            if desc:
                parts.append(f"定义: {desc}")
            if formula:
                parts.append(f"公式: {formula}")
            ind_text += "  " + ", ".join(parts) + "\n"

    system_prompt = "你是一个专业的智能评估系统助手，擅长解释评估指标的概念、定义和计算方法。请用中文回答，回答要准确、清晰、有条理。"
    if kb_text:
        system_prompt += kb_text
    if ind_text:
        system_prompt += ind_text
    system_prompt += "\n\n请基于以上参考信息回答用户的问题。如果参考信息不足以回答，请结合你的知识进行补充说明。"

    # ── 调用 qa-service 流式接口 ──
    full_answer = ""
    try:
        for line in http_post_stream(f"{QA_SERVICE_URL}/qa/chat/stream", {"query": query, "top_k": 3}, timeout=180):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                ev = json.loads(line_str)
                if ev.get("type") == "text":
                    full_answer += ev.get("content", "")
                elif ev.get("type") == "error":
                    yield json.dumps({"type": "text", "content": ev.get("content", "")}, ensure_ascii=False) + "\n"
                    yield json.dumps({"type": "result", "session_id": session_id, "summary": "", "tree": None, "indicators": []}, ensure_ascii=False, default=str) + "\n"
                    return
            except json.JSONDecodeError:
                continue
    except Exception as e:
        logger.error(f"Concept QA stream failed: {e}")
        yield json.dumps({"type": "text", "content": f"概念问答处理失败: {str(e)[:300]}"}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "result", "session_id": session_id, "summary": "", "tree": None, "indicators": []}, ensure_ascii=False, default=str) + "\n"
        return

    # 累积完成后一次性输出
    if full_answer:
        yield json.dumps({"type": "text", "content": full_answer}, ensure_ascii=False) + "\n"
    else:
        full_answer = "抱歉，未能找到相关概念的解释信息。"
        yield json.dumps({"type": "text", "content": full_answer}, ensure_ascii=False) + "\n"

    yield json.dumps({
        "type": "result",
        "session_id": session_id,
        "summary": full_answer,
        "tree": None,
        "indicators": [],
    }, ensure_ascii=False, default=str) + "\n"


class AnalyzeRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    depth: int = 3
    database_id: Optional[str] = None
    database_name: Optional[str] = None
    # 用户在前端勾选的要查询的指标名称列表；非空时仅查询这些指标。
    # 透传给 qa-service，由其在 admin 指标合并之后做权威过滤。
    selected_indicator_names: Optional[List[str]] = None
    # B 阶段数据联动：指定参考的本体模型ID，空则用默认本体
    ontology_id: Optional[str] = None


# ========== 查询管线（调用 evaluation-api） ==========

def _stream_indicator_query(session_id: str, query: str, database_id: str, database_name: str,
                            pending_indicators: dict,
                            selected_indicator_names: Optional[List[str]] = None) -> Generator[str, None, None]:
    """
    调用 qa-service 的 evaluation-api 执行指标查询管线。

    将指标分析结果作为 indicator_defs 传入，复用评估分析的
    数据探索 → 表选择 → SQL生成 → SQL执行 → 分析建议 管线。

    Args:
        selected_indicator_names: 用户勾选的指标名称列表；非空时透传给 qa-service，
            由其在合并 admin 指标后过滤，仅查询这些指标。

    输出：
        NDJSON 行（每行以 \n 结尾），包含 step/text/result 类型事件
    """
    payload = {
        "question": query,
        "database_id": database_id,
        "database_name": database_name,
        "indicator_defs": pending_indicators.get("indicators", []),
        "analysis_plan": pending_indicators.get("summary", ""),
    }
    if selected_indicator_names:
        payload["selected_indicator_names"] = selected_indicator_names
    try:
        for line in http_post_stream(f"{EVALUATION_API_URL}/evaluation/indicator-query/stream", payload, timeout=180):
            yield line
    except Exception as e:
        logger.error(f"Indicator query stream failed: {e}")
        yield json.dumps({
            "type": "error",
            "message": f"查询执行失败: {str(e)[:300]}",
            "session_id": session_id,
        }, ensure_ascii=False) + "\n"


# ========== LLM 调用 ==========

def call_llm_for_indicator_analysis(query: str, context: str = "") -> dict:
    try:
        ctx = ""
        if context:
            ctx = f"\n\n历史对话上下文:\n{context}"

        # 拉取实际证据，来源标签由代码层标注（与流式主流程一致）
        admin_indicators = _fetch_admin_indicators()
        kb_results = _fetch_kb_results(query, top_k=5)
        db_indicators_text = _build_admin_indicators_text(admin_indicators)
        kb_text = _build_kb_text(kb_results)

        prompt = f"""请分析以下指标需求，并返回结构化的 JSON 数据：

需求：{query}{ctx}
{db_indicators_text}
{kb_text}

请按照以下 JSON 格式返回分析结果（必须是可以被 json.loads 解析的 JSON 格式）：
{{
    "tree": {{
        "name": "根节点名称",
        "children": [
            {{"name": "子节点名称", "children": [...]}}
        ]
    }},
    "indicators": [
        {{"name": "指标名称", "definition": "指标定义", "formula": "计算公式", "criteria": "评估标准", "weight": "权重值"}}
    ],
    "summary": "分析总结说明"
}}

要求：
1. tree.children 最多 3 层结构
2. indicators 至少包含 5 个指标
3. 每个指标必须包含 name, definition, formula
4. 不要在 JSON 中输出 type 或 source 字段，来源标签由系统根据实际数据来源自动标注
5. 如能复用上述已配置指标，请直接使用其原始名称（保持名称完全一致以便系统识别）
6. 只返回 JSON 数据，不要其他说明文字
"""

        data = http_post(f"{QA_SERVICE_URL}/qa/chat", {"query": prompt, "top_k": 10}, timeout=120)
        if data:
            answer = data.get("answer", "")
            result = parse_structured_response(answer)
            # 代码层标注来源（不让 LLM 自主打标）
            result["indicators"] = _annotate_indicators(
                result.get("indicators", []), admin_indicators, kb_results
            )
            result["tree"] = _annotate_tree_source(result.get("tree"), result["indicators"])
            return result
        else:
            raise Exception("LLM 返回空数据")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {
            "answer": f"调用大模型分析失败: {str(e)}",
            "tree": None,
            "indicators": [],
            "references": [],
            "summary": ""
        }


def parse_structured_response(answer: str) -> dict:
    try:
        json_str = None

        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', answer)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{[\s\S]*\}', answer)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = answer

        json_str = json_str.strip()
        data = json.loads(json_str)

        result = {
            "answer": answer,
            "tree": data.get("tree"),
            "indicators": data.get("indicators", []),
            "summary": data.get("summary", ""),
            "references": []
        }

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed: {e}")
        logger.debug(f"Failed JSON (first 500 chars): {json_str[:500] if json_str else 'N/A'}")
        return {
            "answer": answer,
            "tree": None,
            "indicators": [],
            "summary": "",
            "references": []
        }


# ========== 指标来源标注（代码层根据实际证据标注，不让 LLM 自主打标） ==========

# 来源优先级权重：admin-db 最高（已配置数据最权威），knowledge 次之，llm 最低
_SOURCE_PRIORITY = {"admin-db": 3, "knowledge": 2, "llm": 1}


def _normalize_name(name: str) -> str:
    """名称归一化：去空格、标点、转小写，便于中文/英文混合匹配。

    消除全半角括号、引号、连接符等差异，例如 "作战 效能（综合）" → "作战效能综合"。
    """
    if not name:
        return ""
    return re.sub(r'[\s\u3000（）()【】\[\]《》<>「」“”‘’\-_·、，。！？：；]+', '', name).lower()


def _char_bigrams(text: str) -> set:
    """对中文友好的 2-gram 分词：返回字符串的二元字符集合。

    与 knowledge-service 的 TF-IDF char_wb 风格一致，不引入 jieba 依赖。
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
    return inter / union if union else 0.0


def _fetch_admin_indicators() -> List[Dict]:
    """统一从 admin-service 获取已配置指标列表，失败返回空列表。

    供指标分析主流程与非流式辅助函数复用，避免重复代码。
    """
    try:
        data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if data and data.get("success"):
            return data.get("indicators", [])
    except Exception as e:
        logger.warning(f"Failed to fetch indicators from admin: {e}")
    return []


def _fetch_kb_results(query: str, top_k: int = 5) -> List[Dict]:
    """统一调用 knowledge-service 检索知识库，失败返回空列表。

    与 concept_qa 路径（main.py 概念问答分支）一致，修复指标分析路径不查知识库的缺陷。
    """
    try:
        data = http_post(
            f"{KNOWLEDGE_SERVICE_URL}/knowledge/search",
            {"query": query, "top_k": top_k},
            timeout=30,
        )
        if data:
            return data.get("results", [])
    except Exception as e:
        logger.warning(f"Knowledge search failed: {e}")
    return []


def _build_admin_indicators_text(admin_indicators: List[Dict]) -> str:
    """构建已配置指标的 prompt 注入文本。

    提示 LLM 如能复用已配置指标请保持名称完全一致，以便代码层按名称匹配标 admin-db 来源。
    """
    if not admin_indicators:
        return ""
    text = "\n## 系统中已配置的指标（来自数据库，可直接复用其名称、定义、公式）:\n"
    for ind in admin_indicators:
        parts = [f"- {ind.get('name', '')}"]
        if ind.get("category"):
            parts.append(f"分类: {ind['category']}")
        if ind.get("formula"):
            parts.append(f"公式: {ind['formula']}")
        if ind.get("description"):
            parts.append(f"描述: {ind['description']}")
        if ind.get("weight") is not None:
            parts.append(f"权重: {ind['weight']}")
        text += ", ".join(parts) + "\n"
    text += "\n如能复用上述已配置指标，请直接使用其原始名称（保持名称完全一致以便系统识别）。\n"
    return text


def _build_kb_text(kb_results: List[Dict]) -> str:
    """构建知识库检索结果的 prompt 注入文本。"""
    if not kb_results:
        return ""
    text = "\n## 知识库检索到的相关参考资料:\n"
    for i, r in enumerate(kb_results):
        text += f"\n[{i + 1}] {r.get('title', '未知')}\n{r.get('content', '')}\n"
    return text


def _match_admin_indicator(ind_name: str, admin_indicators: List[Dict]) -> Optional[Dict]:
    """判断 LLM 生成的指标名是否对应 admin-service 中已配置指标。

    匹配规则（按优先级）：
    1. 归一化后名称完全相等
    2. 归一化后名称包含关系（短串长度 ≥ 2，避免单字误判）
    3. 2-gram Jaccard 重叠率 ≥ 0.6

    Returns:
        匹配到的 admin 指标 dict，未匹配返回 None。
    """
    if not ind_name or not admin_indicators:
        return None
    norm_target = _normalize_name(ind_name)
    if not norm_target:
        return None

    # 规则 1：归一化后完全相等
    for ind in admin_indicators:
        if norm_target == _normalize_name(ind.get("name", "")):
            return ind

    # 规则 2：包含关系（短串长度 ≥ 2）
    for ind in admin_indicators:
        norm_ind = _normalize_name(ind.get("name", ""))
        if len(norm_ind) >= 2 and len(norm_target) >= 2:
            if norm_ind in norm_target or norm_target in norm_ind:
                return ind

    # 规则 3：2-gram Jaccard ≥ 0.6
    target_grams = _char_bigrams(norm_target)
    if target_grams:
        for ind in admin_indicators:
            norm_ind = _normalize_name(ind.get("name", ""))
            ind_grams = _char_bigrams(norm_ind)
            if _jaccard(target_grams, ind_grams) >= 0.6:
                return ind

    return None


def _match_kb_result(ind_name: str, ind_definition: str,
                     kb_results: List[Dict]) -> Optional[Dict]:
    """判断 LLM 生成的指标是否对应到知识库检索结果。

    匹配规则：
    1. 指标名（归一化后长度 ≥ 2）出现在某条知识库 chunk 的 title+content 中
    2. definition 的 2-gram 与 chunk content 的 2-gram Jaccard ≥ 0.5

    Returns:
        匹配到的知识库 dict，未匹配返回 None。
    """
    if not ind_name or not kb_results:
        return None
    norm_name = _normalize_name(ind_name)
    if len(norm_name) < 2:
        return None

    # 规则 1：指标名出现在知识库 chunk 文本中
    for r in kb_results:
        combined = _normalize_name(
            (r.get("title", "") or "") + (r.get("content", "") or "")
        )
        if norm_name in combined:
            return r

    # 规则 2：definition 的 2-gram 与 content 的 2-gram Jaccard ≥ 0.5
    def_text = (ind_definition or "").strip()
    if def_text:
        def_grams = _char_bigrams(_normalize_name(def_text))
        if def_grams:
            for r in kb_results:
                content_grams = _char_bigrams(
                    _normalize_name(r.get("content", "") or "")
                )
                if _jaccard(def_grams, content_grams) >= 0.5:
                    return r

    return None


def _annotate_indicators(indicators: List[Dict],
                         admin_indicators: List[Dict],
                         kb_results: List[Dict]) -> List[Dict]:
    """给每个 LLM 生成的指标打上正确的 type 字段。

    来源判定（匹配优先级 admin-db > knowledge > llm）：
    - admin-db: 名称匹配 admin-service 已配置指标
    - knowledge: 内容能对应到知识库检索结果
    - llm: 其他（LLM 自身知识推断补充）

    匹配到 admin-db 时，同时合并 admin 指标的 fieldMapping / calculationMethod /
    datasetId 字段，使下游 SQL 生成管线能直接利用已配置的字段映射和计算方法，
    无需 LLM 自行猜测公式计算项与表字段的对应关系。
    """
    for ind in indicators:
        name = ind.get("name", "")
        definition = ind.get("definition", "")

        # 优先级 1：匹配 admin-db 已配置指标
        matched = _match_admin_indicator(name, admin_indicators)
        if matched:
            ind["type"] = "admin-db"
            # 合并 admin 已配置的字段映射和计算方法（加法式扩展，向后兼容）
            if matched.get("fieldMapping"):
                ind["fieldMapping"] = matched["fieldMapping"]
            if matched.get("calculationMethod"):
                ind["calculationMethod"] = matched["calculationMethod"]
            if matched.get("datasetId"):
                ind["datasetId"] = matched["datasetId"]
            continue
        # 优先级 2：匹配知识库检索结果
        if _match_kb_result(name, definition, kb_results):
            ind["type"] = "knowledge"
            continue
        # 优先级 3：兜底为 LLM 自身知识
        ind["type"] = "llm"

    admin_cnt = sum(1 for i in indicators if i.get("type") == "admin-db")
    kb_cnt = sum(1 for i in indicators if i.get("type") == "knowledge")
    llm_cnt = sum(1 for i in indicators if i.get("type") == "llm")
    logger.info(
        f"指标来源标注完成: 共 {len(indicators)} 个, "
        f"admin-db={admin_cnt}, knowledge={kb_cnt}, llm={llm_cnt}"
    )
    return indicators


def _annotate_tree_source(tree: Optional[Dict], indicators: List[Dict]) -> Optional[Dict]:
    """根据 indicators 的 type 反推 tree 节点的 source 字段。

    叶子节点查 name->type 映射；中间/根节点取所有子节点中最高优先级来源
    （admin-db=3 > knowledge=2 > llm=1）。若 tree 为 None 直接返回。
    """
    if not tree:
        return tree

    # 构建 归一化名称 -> type 映射（优先取高优先级来源）
    name_to_type: Dict[str, str] = {}
    for ind in indicators:
        norm = _normalize_name(ind.get("name", ""))
        if not norm:
            continue
        existing = name_to_type.get(norm)
        new_type = ind.get("type", "llm")
        if not existing or _SOURCE_PRIORITY.get(new_type, 0) > _SOURCE_PRIORITY.get(existing, 0):
            name_to_type[norm] = new_type

    def _annotate_node(node: Dict) -> str:
        """递归标注节点 source，返回当前节点的来源（用于父节点聚合）。"""
        if not isinstance(node, dict):
            return "llm"
        children = node.get("children")
        # 叶子节点：查名称映射
        if not children:
            norm = _normalize_name(node.get("name", ""))
            src = name_to_type.get(norm, "llm")
            node["source"] = src
            return src
        # 中间/根节点：取子节点中最高优先级来源
        child_sources = [_annotate_node(c) for c in children if isinstance(c, dict)]
        if not child_sources:
            # children 非空但解析后为空，按叶子处理
            norm = _normalize_name(node.get("name", ""))
            src = name_to_type.get(norm, "llm")
            node["source"] = src
            return src
        best = max(child_sources, key=lambda s: _SOURCE_PRIORITY.get(s, 0))
        node["source"] = best
        return best

    _annotate_node(tree)
    return tree


def _compute_source_distribution(indicators: List[Dict]) -> Dict[str, int]:
    """统计来源分布，返回 {'admin-db': N, 'knowledge': M, 'llm': K}。"""
    dist = {"admin-db": 0, "knowledge": 0, "llm": 0}
    for ind in indicators:
        t = ind.get("type", "llm")
        if t in dist:
            dist[t] += 1
        else:
            dist["llm"] += 1
    return dist


def get_default_tree() -> Dict:
    """从 admin-service 动态获取已配置指标，按 category 分组构建指标树。

    admin-service 不可达或返回空时返回空树（不抛异常、不返回伪造数据），
    与 /indicator/list、/indicator/detail、/indicator/algorithm 的取数模式一致。
    """
    empty_tree = {"name": "已配置指标体系", "source": "admin-db", "children": []}
    try:
        data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if not (data and data.get("success")):
            return empty_tree

        indicators = data.get("indicators", [])
        if not indicators:
            return empty_tree

        # 按 category 分组构建二级树
        groups: Dict[str, List[Dict]] = {}
        for ind in indicators:
            category = ind.get("category", "未分类") or "未分类"
            groups.setdefault(category, []).append({
                "name": ind.get("name", ""),
                "source": "admin-db"
            })

        children = [
            {"name": category, "source": "admin-db", "children": leaves}
            for category, leaves in groups.items()
        ]
        return {"name": "已配置指标体系", "source": "admin-db", "children": children}
    except Exception as e:
        logger.warning(f"Failed to fetch indicator tree from admin: {e}")
        return empty_tree


# ========== API 端点 ==========

@app.get("/")
async def root():
    return {
        "service": "indicator-service",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ========== 会话管理 API ==========

@app.get("/indicator/sessions")
async def list_sessions():
    """返回所有会话列表"""
    session_list = []
    sessions_data = get_all_sessions()
    for sid, s_data in sessions_data.items():
        msgs = s_data.get("messages", []) if isinstance(s_data, dict) else s_data
        if not msgs:
            continue
        latest_question = ""
        for msg in reversed(msgs):
            if msg.get("role") == "user":
                q = msg.get("content", "").strip()
                latest_question = q[:30] if len(q) > 30 else q
                break
        last_time = msgs[-1].get("timestamp", datetime.now().isoformat())
        session_list.append({
            "id": sid,
            "title": latest_question or "(空会话)",
            "message_count": len(msgs),
            "last_active": last_time
        })
    session_list.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    return {"success": True, "sessions": session_list}


@app.post("/indicator/session/new")
async def new_session():
    new_id = str(uuid.uuid4())
    ensure_session(new_id)
    return {"success": True, "session_id": new_id}


@app.delete("/indicator/session/{session_id}")
async def delete_session_endpoint(session_id: str):
    try:
        delete_session(session_id)
        return {"success": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="会话不存在")


# ========== 分析 API ==========

@app.post("/indicator/analyze")
async def analyze_indicator(request: AnalyzeRequest):
    """分析指标请求（非流式，兼容旧版）"""
    session_id = request.session_id or str(uuid.uuid4())
    ensure_session(session_id)

    context = build_context(session_id)
    result = call_llm_for_indicator_analysis(request.query, context)

    now_str = datetime.now().isoformat()
    s = ensure_session(session_id)
    s["messages"].append({"role": "user", "content": request.query, "timestamp": now_str})
    s["messages"].append({
        "role": "assistant",
        "content": result.get("summary", result.get("answer", "")[:200]),
        "timestamp": now_str
    })
    if len(s["messages"]) > MAX_CONTEXT * 4:
        s["messages"] = s["messages"][-(MAX_CONTEXT * 4):]

    # 非流式接口不触发追问机制，直接返回
    set_session_stage(session_id, "done")
    save_sessions()

    return {
        "success": True,
        "query": request.query,
        "session_id": session_id,
        "answer": result.get("answer", ""),
        "summary": result.get("summary", ""),
        "tree": result.get("tree"),
        "indicators": result.get("indicators", []),
        "references": result.get("references", []),
        "message": "指标分析完成"
    }

@app.post("/indicator/analyze/stream")
async def analyze_indicator_stream(request: AnalyzeRequest):
    """
    流式指标分析（含"纯对话追问"状态机）。

    stage 路由：
      - "analyzing" / 无 stage → LLM 生成指标体系 → 追问 → stage=awaiting_confirmation
      - "awaiting_confirmation" → 检测用户意图：
          - 确认查询 + 有 database_id → 执行查询 → stage=done
          - 确认查询 + 无 database_id → 列出数据源 → stage 不变
          - 表示不查询 → 结束 → stage=done
      - "done" → 新问题 → 重置为 analyzing
    """
    session_id = request.session_id or str(uuid.uuid4())
    ensure_session(session_id)
    stage = get_session_stage(session_id)
    msgs = get_recent_messages(session_id)

    logger.info(f"Indicator analyze/stream: session={session_id}, stage={stage}, query={request.query[:80]}")

    # =====================================================================
    # 分支 A：用户正处于"待确认"阶段 → 解析意图
    # =====================================================================
    if stage == "awaiting_confirmation":
        user_text = request.query.strip()

        # ── 子分支 A0：用户输入了新问题（既非确认查询，也非拒绝查询） ──
        # 注意：is_new_question() 对长度>8的输入一律返回 True，会误伤「好的请帮我查询」
        # 这类长确认语。此处先排除确认/拒绝，确保真正的确认/拒绝走 A1/A2 分支。
        if is_new_question(user_text) and not is_query_confirm(user_text) and not is_query_deny(user_text):
            logger.info(f"[{session_id}] Detected new question in awaiting_confirmation stage, resetting to analyzing")
            stage = "analyzing"
            set_session_stage(session_id, "analyzing")
            # 不清除 pending_indicators：新分析成功后会自然覆盖；保留旧值以备用户回溯
            # 不需要 yield 任何事件，继续走下面的逻辑

        # ── 子分支 A1：用户表示"不查询" ──
        elif is_query_deny(user_text):
            def generate_deny():
                now_str = datetime.now().isoformat()
                resp_text = "好的，已了解。如果后续需要查询这些指标，随时告诉我。"
                yield json.dumps({"type": "text", "content": resp_text}, ensure_ascii=False) + "\n"
                yield json.dumps({
                    "type": "result",
                    "session_id": session_id,
                    "tree": None,
                    "indicators": [],
                }, ensure_ascii=False) + "\n"

                s = ensure_session(session_id)
                s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})
                s["messages"].append({"role": "assistant", "content": resp_text, "timestamp": now_str})
                set_session_stage(session_id, "done")
                clear_pending_indicators(session_id)

            return create_stream_response(generate_deny())

        # ── 子分支 A2：用户表示"查询" ──
        elif is_query_confirm(user_text):
            # 先看用户是否在输入中直接带了数据源
            database_id = request.database_id
            database_name = request.database_name or ""

            # 如果前端没传，尝试从用户文本中匹配
            if not database_id:
                dbs = fetch_available_databases(ADMIN_SERVICE_URL)
                matched = match_database(user_text, dbs)
                if matched:
                    database_id = matched.get("id", "")
                    database_name = matched.get("name", "")

            # 只有一个数据源 → 自动选中，不追问
            if not database_id and len(dbs) == 1:
                database_id = dbs[0].get("id", "")
                database_name = dbs[0].get("name", "")
                logger.info(f"Auto-selected sole datasource: {database_name} ({database_id})")

            # 如果找到了数据源 → 执行查询
            if database_id:
                pending = get_pending_indicators(session_id)
                original_query = pending.get("original_query", request.query) if pending else request.query

                def generate_query():
                    now_str = datetime.now().isoformat()
                    set_session_stage(session_id, "querying")

                    s = ensure_session(session_id)
                    s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})

                    # 先创建助手消息，后续所有 text 事件都流入同一消息气泡
                    yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"

                    start_text = _build_query_start_text(
                        database_name, database_id,
                        request.selected_indicator_names, "confirm")
                    yield json.dumps({"type": "text", "content": start_text}, ensure_ascii=False) + "\n"

                    # 调用 evaluation-api 执行查询管线
                    final_answer = ""
                    pending = get_pending_indicators(session_id)
                    try:
                        for line in _stream_indicator_query(
                            session_id, original_query,
                            database_id, database_name, pending,
                            request.selected_indicator_names
                        ):
                            line_str = line if isinstance(line, str) else line
                            yield line_str

                            # 提取 final_answer
                            try:
                                ev = json.loads(line_str.strip())
                                if ev.get("type") == "result":
                                    final_answer = ev.get("final_answer", "") or ev.get("result", {}).get("final_answer", "")
                            except Exception:
                                pass
                    except Exception as e:
                        yield json.dumps({
                            "type": "error", "message": f"查询失败: {str(e)[:200]}",
                            "session_id": session_id
                        }, ensure_ascii=False) + "\n"

                    s["messages"].append({
                        "role": "assistant",
                        "content": final_answer or "查询完成",
                        "timestamp": now_str
                    })
                    set_session_stage(session_id, "done")
                    clear_pending_indicators(session_id)

                return create_stream_response(generate_query())

            # 没有找到数据源 → 列出可用数据源，让用户选择
            else:
                dbs = fetch_available_databases(ADMIN_SERVICE_URL)
                def generate_list_dbs():
                    now_str = datetime.now().isoformat()
                    if dbs:
                        db_list = "\n".join(
                            f"  · {db.get('name', '')} ({db.get('type', '')} - {db.get('host', '')}:{db.get('port', '')})"
                            for db in dbs[:10]
                        )
                        resp_text = f"好的。请先选择一个数据源，当前可用的数据源有：\n{db_list}\n\n请直接回复数据源名称即可。"
                    else:
                        resp_text = "好的。但当前系统中没有可用的数据源，请先在管理后台配置数据源。"
                    yield json.dumps({"type": "text", "content": resp_text}, ensure_ascii=False) + "\n"
                    yield json.dumps({
                        "type": "result",
                        "session_id": session_id,
                        "tree": None, "indicators": [],
                    }, ensure_ascii=False) + "\n"

                    s = ensure_session(session_id)
                    s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})
                    s["messages"].append({"role": "assistant", "content": resp_text, "timestamp": now_str})
                    # 仍然保持 awaiting_confirmation，等用户提供数据源
                    save_sessions()

                return create_stream_response(generate_list_dbs())

        # ── 子分支 A3：既不是确认也不是否认 → 当成"在 awaiting 阶段提供数据源名"处理 ──
        dbs = fetch_available_databases(ADMIN_SERVICE_URL)
        matched = match_database(user_text, dbs)
        if matched:
            database_id = matched.get("id", "")
            database_name = matched.get("name", "")
            pending = get_pending_indicators(session_id)
            original_query = pending.get("original_query", "") if pending else ""

            def generate_query_by_name():
                now_str = datetime.now().isoformat()
                set_session_stage(session_id, "querying")

                s = ensure_session(session_id)
                s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})

                # 先创建助手消息，后续所有 text 事件都流入同一消息气泡
                yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"

                start_text = _build_query_start_text(
                    database_name, database_id,
                    request.selected_indicator_names, "by_name")
                yield json.dumps({"type": "text", "content": start_text}, ensure_ascii=False) + "\n"

                final_answer = ""
                pending = get_pending_indicators(session_id)
                try:
                    for line in _stream_indicator_query(
                        session_id, original_query,
                        database_id, database_name, pending,
                        request.selected_indicator_names
                    ):
                        line_str = line if isinstance(line, str) else line
                        yield line_str
                        try:
                            ev = json.loads(line_str.strip())
                            if ev.get("type") == "result":
                                final_answer = ev.get("final_answer", "") or ev.get("result", {}).get("final_answer", "")
                        except Exception:
                            pass
                except Exception as e:
                    yield json.dumps({
                        "type": "error", "message": f"查询失败: {str(e)[:200]}",
                        "session_id": session_id
                    }, ensure_ascii=False) + "\n"

                s["messages"].append({
                    "role": "assistant",
                    "content": final_answer or "查询完成",
                    "timestamp": now_str
                })
                set_session_stage(session_id, "done")
                clear_pending_indicators(session_id)

            return create_stream_response(generate_query_by_name())

        # ── 子分支 A4：完全不匹配 → 询问用户意图，保留已生成的指标体系 ──
        # 旧逻辑会静默重置为 analyzing 并 clear_pending_indicators()，导致用户困惑：
        # 刚生成的指标体系凭空消失、无任何提示。新逻辑明确告知"无法理解"，
        # 列出可选项，并保留 pending_indicators 与 awaiting_confirmation 状态等待用户明确意图。
        def generate_clarification():
            now_str = datetime.now().isoformat()
            pending = get_pending_indicators(session_id)
            ind_count = len(pending.get("indicators", [])) if pending else 0
            if ind_count:
                resp_text = (
                    f"抱歉，我没有理解您的回复。您刚才已生成 {ind_count} 个指标，请问您希望：\n\n"
                    "1. **查询这些指标** — 回复「查询」并告知数据源名称（如：查询 MySQL）\n"
                    "2. **暂不查询** — 回复「不查询」结束本轮\n"
                    "3. **分析新的问题** — 直接描述新的指标分析需求"
                )
            else:
                resp_text = (
                    "抱歉，我没有理解您的输入。请问您希望：\n\n"
                    "1. 查询指标 — 回复「查询」并告知数据源名称\n"
                    "2. 暂不查询 — 回复「不查询」\n"
                    "3. 分析新问题 — 直接描述需求"
                )
            yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "text", "content": resp_text}, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "result",
                "session_id": session_id,
                "tree": None, "indicators": [],
            }, ensure_ascii=False) + "\n"

            s = ensure_session(session_id)
            s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})
            s["messages"].append({"role": "assistant", "content": resp_text, "timestamp": now_str})
            # 保持 awaiting_confirmation 状态，保留 pending_indicators，等待用户明确意图
            save_sessions()

        logger.info(f"User text in awaiting_confirmation not matched: {user_text[:50]}, asking for clarification (preserving pending indicators)")
        return create_stream_response(generate_clarification())

    # =====================================================================
    # 分支 B：正常指标分析流程（analyzing / 或 done 状态的新问题）
    # =====================================================================
    if stage == "analyzing" or stage == "done":
        query_type = _classify_query(request.query)

        if query_type == "general_chat":
            # 一般对话 → 直接友好回复
            def generate_greeting():
                # 新消息
                yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"
                resp_text = "你好！我是智能评估指标体系分析助手，可以帮你：\n\n1. **指标分析** — 分析评估侦察、打击、防护等领域的指标体系\n2. **概念问答** — 解释各种评估指标的定义和计算方法\n3. **数据查询** — 从数据库中查询指标的具体数值\n\n请问有什么可以帮你的？"
                yield json.dumps({"type": "text", "content": resp_text}, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "result", "session_id": session_id, "summary": resp_text, "tree": None, "indicators": []}, ensure_ascii=False, default=str) + "\n"
            return create_stream_response(generate_greeting())

        if query_type == "concept_qa":
            # 概念问答 → 直接走知识库检索 + LLM 总结
            def generate_concept_qa():
                now_str = datetime.now().isoformat()
                s = ensure_session(session_id)
                s["messages"].append({"role": "user", "content": request.query, "timestamp": now_str})

                yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"

                for ev in _handle_concept_qa_stream(session_id, request.query):
                    yield ev

                set_session_stage(session_id, "done")
            return create_stream_response(generate_concept_qa())

        # 否则走原有的 Phase 1 指标体系生成流程（已有代码，不需要动）

    # 如果是 done 重置为 analyzing
    if stage == "done":
        set_session_stage(session_id, "analyzing")

    context = build_context(session_id)
    ctx_str = f"\n\n历史对话上下文:\n{context}" if context else ""

    # ── 拉取实际证据：admin-service 已配置指标 + knowledge-service 知识库检索 ──
    # 来源标签由代码层根据这些实际证据标注，不让 LLM 自主打标
    admin_indicators = _fetch_admin_indicators()
    kb_results = _fetch_kb_results(request.query, top_k=5)
    db_indicators_text = _build_admin_indicators_text(admin_indicators)
    kb_text = _build_kb_text(kb_results)

    prompt = f"""请分析以下指标需求，并返回结构化的 JSON 数据。

需求：{request.query}{ctx_str}
{db_indicators_text}
{kb_text}

请严格按照以下格式输出：

仅输出一个可以被 json.loads 解析的 JSON 对象，包含 tree、indicators、summary 三个字段。

JSON 格式要求：
{{
    "tree": {{
        "name": "根节点名称",
        "children": [{{
            "name": "子节点名称",
            "children": [...]
        }}]
    }},
    "indicators": [
        {{"name": "指标名称", "definition": "定义", "formula": "公式", "criteria": "标准", "weight": "权重"}}
    ],
    "summary": "分析总结说明"
}}

要求：
1. tree.children 最多 3 层结构
2. indicators 至少包含 3 个指标，每个指标必须包含 name、definition、formula
3. 不要在 JSON 中输出 type 或 source 字段，来源标签由系统根据实际数据来源自动标注
4. 如能复用上述已配置指标，请直接使用其原始名称（保持名称完全一致以便系统识别）
5. 只返回 JSON 数据，不要其他说明文字"""

    def generate():
        full_text = ""
        now_str = datetime.now().isoformat()

        # ── Phase 1 Step 1：正在解析指标体系 ──
        yield json.dumps({
            "type": "step",
            "step": {"step": 1, "description": "解析指标体系", "status": "in_progress", "detail": "正在调用大模型分析指标需求", "phase": "indicator_gen"}
        }, ensure_ascii=False) + "\n"

        try:
            for line in http_post_stream(f"{QA_SERVICE_URL}/qa/chat/stream", {"query": prompt, "top_k": 10}, timeout=180):
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    if data.get("type") == "text":
                        # 方案B：JSON 指标体系仅后台累积，不推送给前端
                        full_text += data.get("content", "")
                    elif data.get("type") == "error":
                        yield json.dumps({"type": "text", "content": data.get("content", "")}, ensure_ascii=False) + "\n"
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            yield json.dumps({"type": "text", "content": f"分析失败: {str(e)[:200]}"}, ensure_ascii=False) + "\n"

        # ── 从 LLM 响应中提取并解析 JSON 指标体系 ──
        result = parse_structured_response(full_text)
        tree = result.get("tree")
        indicators = result.get("indicators", [])
        summary = result.get("summary", result.get("answer", full_text[:200]))

        # ── 代码层根据实际证据标注来源（不让 LLM 自主打标）──
        # admin-db: 名称匹配 admin-service 已配置指标
        # knowledge: 内容对应 knowledge-service 检索结果
        # llm: 其他
        indicators = _annotate_indicators(indicators, admin_indicators, kb_results)
        tree = _annotate_tree_source(tree, indicators)
        source_dist = _compute_source_distribution(indicators)

        if not indicators:
            yield json.dumps({
                "type": "error",
                "session_id": session_id,
                "message": "指标体系生成失败：大模型未返回有效结果，请检查大模型配置后重试。",
            }, ensure_ascii=False) + "\n"
            return
        
        indicator_count = len(indicators)
        yield json.dumps({
            "type": "step",
            "step": {"step": 1, "description": "解析指标体系", "status": "completed",
                     "detail": f"共识别 {indicator_count} 个指标", "phase": "indicator_gen"}
        }, ensure_ascii=False) + "\n"
        
        indicator_names = [ind.get("name", "") for ind in indicators[:5]]
        names_str = "、".join(indicator_names)
        if indicator_count > 5:
            names_str += f" 等共{indicator_count}个指标"
        set_pending_indicators(session_id, {
            "tree": tree,
            "indicators": indicators,
            "summary": summary,
            "original_query": request.query,
            "generated_at": datetime.now().isoformat(),
        })
        set_session_stage(session_id, "awaiting_confirmation")
        
        # ── 发送 result，前端渲染指标卡片 ──
        yield json.dumps({
            "type": "result",
            "session_id": session_id,
            "tree": tree,
            "indicators": indicators,
        }, ensure_ascii=False, default=str) + "\n"

        # ── 第二次调用 LLM：生成结构化分析摘要并流式输出 ──
        if indicators:
            # 构建指标简要描述文本（不再拼接 type 标签，避免污染 LLM 复述）
            ind_brief_parts = []
            for ind in indicators:
                parts = [f"- {ind.get('name', '')}"]
                if ind.get('formula'):
                    parts.append(f"公式: {ind['formula']}")
                ind_brief_parts.append(" ".join(parts))
            ind_brief_text = "\n".join(ind_brief_parts)

            # 由代码精确统计的来源分布（不让 LLM 自行估算）
            dist_text = (
                f"admin-db(已配置){source_dist['admin-db']} 个，"
                f"knowledge(知识库){source_dist['knowledge']} 个，"
                f"llm(AI生成){source_dist['llm']} 个"
            )

            summary_system_prompt = (
                "你是一个专业的指标体系分析助手。请根据以下指标体系信息，用自然语言向用户简洁汇报分析结论。\n"
                "要求：\n"
                "1. 分段简要说明分析结果，语言专业但易懂\n"
                "2. 包含：指标总数、主要维度构成\n"
                f"3. 以下是由系统精确统计的来源分布数据，请直接引用，不要自行估算：{dist_text}\n"
                "4. 简要列举核心指标的名称和主要评估方向，无需展开公式细节\n"
                "5. 给出1条整体评估建议\n"
                "6. 不要输出JSON或任何结构化格式，只输出自然语言\n"
                "7. 总输出字数严格控制在500字以内，超出部分将被截断\n"
                f"\n\n指标总数：{len(indicators)}\n\n指标详情：\n{ind_brief_text}"
            )

            yield json.dumps({
                "type": "step",
                "step": {"step": 2, "description": "生成分析结论", "status": "in_progress",
                         "detail": "正在调用大模型生成分析结论...", "phase": "indicator_gen"}
            }, ensure_ascii=False) + "\n"

            try:
                summary_text_buf = ""
                for line in http_post_stream(f"{QA_SERVICE_URL}/qa/chat/stream", {"query": summary_system_prompt, "top_k": 3}, timeout=180):
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        summary_data = json.loads(line_str)
                        if summary_data.get("type") == "text":
                                chunk = summary_data.get("content", "")
                                if chunk:
                                    summary_text_buf += chunk
                                    yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"
                    except json.JSONDecodeError:
                        continue

                yield json.dumps({
                    "type": "step",
                    "step": {"step": 2, "description": "生成分析结论", "status": "completed",
                             "detail": f"分析结论已生成 (共 {len(summary_text_buf)} 字符)", "phase": "indicator_gen"}
                }, ensure_ascii=False) + "\n"

                summary = summary_text_buf

            except Exception as e:
                logger.warning(f"Second LLM summary call failed: {e}")
                yield json.dumps({
                    "type": "step",
                    "step": {"step": 2, "description": "生成分析结论", "status": "error",
                             "detail": f"生成结论失败: {str(e)[:80]}", "phase": "indicator_gen"}
                }, ensure_ascii=False) + "\n"

        # ── 追加追问文本（独立消息）──
        indicator_names = [ind.get("name", "") for ind in indicators[:5]]
        names_str = "、".join(indicator_names)
        if indicator_count > 5:
            names_str += f" 等共{indicator_count}个指标"
        follow_up = (
            f"已为您生成指标体系：{names_str}。\n\n"
            "**是否需要查询这些指标？** 如果查询，请回复「查询」并告知数据源名称；"
            "如果暂时不需要，请回复「不查询」。"
        )
        yield json.dumps({
            "type": "new_message",
            "content": follow_up.strip()
        }, ensure_ascii=False) + "\n"

        # 保存会话
        s = ensure_session(session_id)
        s["messages"].append({"role": "user", "content": request.query, "timestamp": now_str})
        s["messages"].append({"role": "assistant", "content": summary or f"已生成 {len(indicators)} 个指标", "timestamp": now_str})
        s["messages"].append({"role": "assistant", "content": follow_up.strip(), "timestamp": now_str})
        if len(s["messages"]) > MAX_CONTEXT * 4:
            s["messages"] = s["messages"][-(MAX_CONTEXT * 4):]
        save_sessions()

    return create_stream_response(generate())


@app.get("/indicator/history")
async def get_history(session_id: str):
    """获取指定会话的消息"""
    sessions_data = get_all_sessions()
    if session_id not in sessions_data:
        return {"messages": []}
    s = sessions_data[session_id]
    msgs = s.get("messages", []) if isinstance(s, dict) else s
    return {
        "messages": [
            {"role": msg["role"], "content": msg["content"]}
            for msg in msgs
        ]
    }


@app.get("/indicator/tree")
async def get_indicator_tree():
    return {"success": True, "tree": get_default_tree()}


@app.get("/indicator/detail/{indicator_name}")
async def get_indicator_detail(indicator_name: str):
    try:
        data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if data and data.get("success"):
            for ind in data.get("indicators", []):
                if ind.get("name", "").strip() == indicator_name.strip():
                    return {
                        "name": ind["name"],
                        "source": "admin-db",
                        "definition": ind.get("description", ""),
                        "formula": ind.get("formula", ""),
                        "criteria": "",
                        "weight": ind.get("weight", 0)
                    }
    except Exception as e:
        logger.warning(f"Failed to fetch indicator detail from admin: {e}")
    return {"message": f"未找到指标「{indicator_name}」"}


@app.get("/indicator/algorithm/{indicator_name}")
async def get_indicator_algorithm(indicator_name: str):
    try:
        data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if data and data.get("success"):
            for ind in data.get("indicators", []):
                if ind.get("name", "").strip() == indicator_name.strip():
                    method = ind.get("calculationMethod") or ind.get("formula", "")
                    return {
                        "name": ind["name"],
                        "formula": ind.get("formula", ""),
                        "steps": method.split("\n") if method else [],
                        "example": ind.get("description", "")
                    }
    except Exception as e:
        logger.warning(f"Failed to fetch indicator algorithm from admin: {e}")
    return {"message": "该指标暂无详细算法说明"}


@app.get("/indicator/list")
async def list_indicators():
    try:
        data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if data and data.get("success"):
            indicators = []
            for ind in data.get("indicators", []):
                indicators.append({
                    "name": ind["name"],
                    "category": ind.get("category", "未分类"),
                    "source": "admin-db",
                    "id": ind.get("id", "")
                })
            return {"indicators": indicators}
    except Exception as e:
        logger.warning(f"Failed to fetch indicator list from admin: {e}")
    return {"indicators": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10254)
