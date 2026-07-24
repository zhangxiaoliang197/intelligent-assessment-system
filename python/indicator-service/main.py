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


# ========== 查询管线（调用 evaluation-api） ==========

def _stream_indicator_query(session_id: str, query: str, database_id: str, database_name: str,
                            pending_indicators: dict) -> Generator[str, None, None]:
    """
    调用 qa-service 的 evaluation-api 执行指标查询管线。

    将指标分析结果作为 indicator_defs 传入，复用评估分析的
    数据探索 → 表选择 → SQL生成 → SQL执行 → 分析建议 管线。

    输出：
        NDJSON 行（每行以 \n 结尾），包含 step/text/result 类型事件
    """
    try:
        for line in http_post_stream(f"{EVALUATION_API_URL}/evaluation/indicator-query/stream", {
            "question": query,
            "database_id": database_id,
            "database_name": database_name,
            "indicator_defs": pending_indicators.get("indicators", []),
            "analysis_plan": pending_indicators.get("summary", ""),
        }, timeout=180):
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

        prompt = f"""请分析以下指标需求，并返回结构化的JSON数据：

需求：{query}{ctx}

请按照以下JSON格式返回分析结果（必须是可以被json.loads解析的JSON格式）：
{{
    "tree": {{
        "name": "根节点名称，如：作战效能指标体系",
        "source": "knowledge 或 llm",
        "children": [
            {{
                "name": "一级指标名称",
                "source": "knowledge 或 llm",
                "children": [
                    {{"name": "二级指标名称", "source": "knowledge 或 llm"}}
                ]
            }}
        ]
    }},
    "indicators": [
        {{
            "name": "指标名称",
            "type": "knowledge 或 llm",
            "definition": "指标定义",
            "formula": "计算公式",
            "criteria": "评估标准",
            "weight": "权重值"
        }}
    ],
    "summary": "分析总结说明"
}}

要求：
1. tree.children最多3层结构
2. indicators至少包含5个指标
3. 每个指标必须包含name, definition, formula
4. 只返回JSON数据，不要其他说明文字
"""

        data = http_post(f"{QA_SERVICE_URL}/qa/chat", {"query": prompt, "top_k": 10}, timeout=120)
        if data:
            answer = data.get("answer", "")
            result = parse_structured_response(answer)
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


def get_default_tree() -> Dict:
    return {
        "name": "作战效能指标体系",
        "source": "knowledge",
        "children": [
            {
                "name": "打击能力",
                "source": "knowledge",
                "children": [
                    {"name": "命中率", "source": "knowledge"},
                    {"name": "摧毁率", "source": "knowledge"},
                    {"name": "突防率", "source": "llm"}
                ]
            },
            {
                "name": "生存能力",
                "source": "knowledge",
                "children": [
                    {"name": "存活率", "source": "knowledge"},
                    {"name": "防护能力", "source": "llm"}
                ]
            },
            {
                "name": "保障能力",
                "source": "knowledge",
                "children": [
                    {"name": "补给效率", "source": "knowledge"},
                    {"name": "维护能力", "source": "llm"}
                ]
            }
        ]
    }


def get_default_indicators() -> List[Dict]:
    return [
        {
            "name": "命中率",
            "type": "knowledge",
            "definition": "武器系统命中目标的概率，反映精确打击能力。",
            "formula": "命中率 = 命中次数 / 射击次数 × 100%",
            "criteria": "优秀: ≥85%, 良好: ≥75%, 合格: ≥65%",
            "weight": "0.35"
        },
        {
            "name": "摧毁率",
            "type": "knowledge",
            "definition": "被命中目标中被摧毁的比例，反映毁伤效果。",
            "formula": "摧毁率 = 摧毁数量 / 命中数量 × 100%",
            "criteria": "优秀: ≥80%, 良好: ≥70%, 合格: ≥60%",
            "weight": "0.30"
        },
        {
            "name": "突防率",
            "type": "llm",
            "definition": "成功突破敌方防御系统的概率，反映突防能力。",
            "formula": "突防率 = 成功突防次数 / 总突防次数 × 100%",
            "criteria": "根据具体作战场景确定",
            "weight": "0.25"
        },
        {
            "name": "存活率",
            "type": "knowledge",
            "definition": "作战单元在作战环境中保持功能的概率，反映生存能力。",
            "formula": "存活率 = 存活数量 / 初始数量 × 100%",
            "criteria": "优秀: ≥90%, 良好: ≥80%, 合格: ≥70%",
            "weight": "0.20"
        },
        {
            "name": "防护能力",
            "type": "llm",
            "definition": "系统抵御外部威胁的能力，包括装甲防护、电子对抗等。",
            "formula": "防护能力评分 = Σ(防护分项得分 × 分项权重)",
            "criteria": "根据防护等级确定",
            "weight": "0.15"
        }
    ]


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

        # ── 子分支 A0：用户输入了新问题（不是确认也不是拒绝） ──
        if is_new_question(user_text):
            logger.info(f"[{session_id}] Detected new question in awaiting_confirmation stage, resetting to analyzing")
            stage = "analyzing"
            set_session_stage(session_id, "analyzing")
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

                    start_text = f"好的，正在使用数据源「{database_name or database_id}」查询这些指标...\n\n"
                    yield json.dumps({"type": "text", "content": start_text}, ensure_ascii=False) + "\n"

                    # 调用 evaluation-api 执行查询管线
                    final_answer = ""
                    pending = get_pending_indicators(session_id)
                    try:
                        for line in _stream_indicator_query(
                            session_id, original_query,
                            database_id, database_name, pending
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

                start_text = f"好的，使用数据源「{database_name or database_id}」开始查询指标...\n\n"
                yield json.dumps({"type": "text", "content": start_text}, ensure_ascii=False) + "\n"

                final_answer = ""
                pending = get_pending_indicators(session_id)
                try:
                    for line in _stream_indicator_query(
                        session_id, original_query,
                        database_id, database_name, pending
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

        # 完全不匹配 → 可能是新问题，重置为 analyzing 走正常流程
        logger.info(f"User text in awaiting_confirmation not matched: {user_text[:50]}, resetting to analyzing")
        set_session_stage(session_id, "analyzing")
        clear_pending_indicators(session_id)
        # fall through to normal flow below

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

    # 从 admin 获取已配置的指标作为参考
    db_indicators_text = ""
    try:
        db_data = http_get(f"{ADMIN_SERVICE_URL}/api/admin/indicator/list", timeout=5)
        if db_data and db_data.get("success") and db_data.get("indicators"):
            db_indicators_text = "\n## 系统中已配置的指标（来自数据库，可直接引用）:\n"
            for ind in db_data["indicators"]:
                parts = [f"- {ind['name']}"]
                if ind.get("category"): parts.append(f"分类: {ind['category']}")
                if ind.get("formula"): parts.append(f"公式: {ind['formula']}")
                if ind.get("description"): parts.append(f"描述: {ind['description']}")
                if ind.get("weight") is not None: parts.append(f"权重: {ind['weight']}")
                db_indicators_text += ", ".join(parts) + "\n"
            db_indicators_text += "\n上述已配置指标的数据来源标记为 \"admin-db\"。\n"
    except Exception as e:
        logger.warning(f"Failed to fetch indicators from admin: {e}")

    prompt = f"""请分析以下指标需求，基于：1)系统已配置的指标数据库 2)知识库中的专业知识 3)你自身的领域知识，综合给出分析结果。

需求：{request.query}{ctx_str}
{db_indicators_text}

请严格按照以下格式输出：

仅输出一个可以被 json.loads 解析的 JSON 对象，包含 tree、indicators、summary 三个字段。


JSON格式要求：
{{
    "tree": {{
        "name": "根节点名称",
        "source": "admin-db 或 knowledge 或 llm",
        "children": [{{
            "name": "子节点名称",
            "source": "admin-db 或 knowledge 或 llm",
            "children": [...]
        }}]
    }},
    "indicators": [
        {{"name": "指标名称", "type": "admin-db 或 knowledge 或 llm", "definition": "定义", "formula": "公式", "criteria": "标准", "weight": "权重"}}
    ],
    "summary": "分析总结说明"
}}

来源标注规则：
- \"admin-db\" = 来自系统已配置的指标数据库
- \"knowledge\" = 来自知识库检索的参考资料
- \"llm\" = 来自大模型自身知识推断补充

要求：tree.children最多3层，indicators至少3个指标，每个指标须包含name/type/definition/formula，优先使用admin-db已有配置"""

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
                        chunk = data.get("content", "")
                        full_text += chunk
                        yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"
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
            # 构建指标简要描述文本
            ind_brief_parts = []
            for ind in indicators:
                parts = [f"- {ind.get('name', '')}"]
                if ind.get('type'):
                    parts.append(f"[{ind['type']}]")
                if ind.get('formula'):
                    parts.append(f"公式: {ind['formula']}")
                ind_brief_parts.append(" ".join(parts))
            ind_brief_text = "\n".join(ind_brief_parts)

            summary_system_prompt = (
                "你是一个专业的指标体系分析助手。请根据以下指标体系信息，用1-2句话生成一段简洁的结构化分析摘要。"
                "要求包含：指标总数、主要维度构成、来源分布（admin-db/knowledge/llm各多少）、核心指标。"
                "语言简洁、信息完整、不重复。"
                f"\n\n指标总数：{len(indicators)}\n\n指标详情：\n{ind_brief_text}"
            )

            yield json.dumps({
                "type": "step",
                "step": {"step": 2, "description": "生成分析摘要", "status": "in_progress",
                         "detail": "正在调用大模型生成指标体系分析摘要...", "phase": "indicator_gen"}
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
                    "step": {"step": 2, "description": "生成分析摘要", "status": "completed",
                             "detail": f"分析摘要已生成 (共 {len(summary_text_buf)} 字符)", "phase": "indicator_gen"}
                }, ensure_ascii=False) + "\n"

                summary = summary_text_buf

            except Exception as e:
                logger.warning(f"Second LLM summary call failed: {e}")
                yield json.dumps({
                    "type": "step",
                    "step": {"step": 2, "description": "生成分析摘要", "status": "error",
                             "detail": f"生成摘要失败: {str(e)[:80]}", "phase": "indicator_gen"}
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
    return get_default_tree()


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
