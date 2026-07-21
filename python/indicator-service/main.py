from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Generator
import json
import os
import tempfile
import urllib.request
import urllib.error
import ssl
import re
import uuid
import logging
from datetime import datetime

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

QA_SERVICE_URL = os.getenv("QA_SERVICE_URL", "http://localhost:10253")
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")
EVALUATION_API_URL = os.getenv("EVALUATION_API_URL", "http://localhost:10253")  # evaluation-api 注册在 qa-service
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
os.makedirs(DATA_DIR, exist_ok=True)

# 滑动窗口大小
MAX_CONTEXT = int(os.getenv("INDICATOR_CONTEXT_ROUNDS", "5"))

# ── 查询确认意图关键词 ──
_QUERY_CONFIRM_KEYWORDS = [
    "查询", "查一下", "查数据", "查查看", "查看指标", "查指标", "查结果",
    "确认查询", "我查", "想查",
]
_QUERY_DENY_KEYWORDS = [
    "不查询", "不用查询", "不查", "不用查", "不", "不用了",
    "不需要", "不需要了", "不用", "不查询了", "先不查",
    "算了", "不要", "不要了", "不必", "免了", "不执行",
]

# 新问题检测关键词
_NEW_QUESTION_KEYWORDS = [
    "什么是", "什么叫", "解释", "定义", "含义", "概念",
    "帮我分析", "帮我查", "如何", "怎样", "怎么",
]

# 概念问答分类关键词（第一层快速判断，与 LLM 分类互补）
_CONCEPT_KEYWORDS = [
    "什么是", "什么叫", "定义", "解释", "含义", "概念",
    "什么意思", "如何理解",
]


def _is_concept_query(question: str) -> bool:
    """用 _CONCEPT_KEYWORDS 匹配判断是否为概念问答。"""
    t = question.strip().lower()
    for kw in _CONCEPT_KEYWORDS:
        if kw in t:
            return True
    return False


def _is_new_question(question: str) -> bool:
    """用 _NEW_QUESTION_KEYWORDS 匹配或长度超过 8 个字判断为新问题。"""
    t = question.strip().lower()
    # 超过 8 个字也认为是新问题
    if len(t) > 8:
        return True
    for kw in _NEW_QUESTION_KEYWORDS:
        if kw in t:
            return True
    return False


def _classify_query(query: str) -> str:
    """先调用 qa-service 的 LLM 分类接口，失败则用关键词兜底。

    Returns:
        "concept_qa" / "indicator_analysis" / "general_chat"
    """
    try:
        body = json.dumps({"query": query}).encode("utf-8")
        req = urllib.request.Request(
            f"{QA_SERVICE_URL}/qa/classify-query",
            data=body,
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            classification = data.get("classification", "")
            if classification in ("concept_qa", "indicator_analysis", "general_chat"):
                return classification
    except Exception as e:
        logger.warning(f"Classify query via qa-service failed: {e}")

    # 兜底：关键词匹配
    if _is_concept_query(query):
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
        body = json.dumps({"query": query, "top_k": 3}).encode("utf-8")
        req = urllib.request.Request(
            f"{KNOWLEDGE_SERVICE_URL}/knowledge/search",
            data=body,
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            kb_results = data.get("results", [])
    except Exception as e:
        logger.warning(f"Knowledge search failed: {e}")

    # ── 获取已配置指标定义 ──
    indicator_defs = []
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/indicator/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("indicators"):
                indicator_defs = data["indicators"]
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
    body = json.dumps({
        "query": query,
        "top_k": 3,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{QA_SERVICE_URL}/qa/chat/stream",
        data=body,
        method="POST"
    )
    req.add_header("Content-Type", "application/json")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    full_answer = ""
    try:
        with urllib.request.urlopen(req, timeout=180, context=ssl_ctx) as resp:
            for line in resp:
                line_str = line.decode("utf-8").strip()
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


def atomic_json_write(filepath, data):
    dirpath = os.path.dirname(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        bak_path = filepath + '.bak'
        if os.path.exists(filepath):
            try:
                import shutil
                shutil.copy2(filepath, bak_path)
            except Exception:
                pass
        if os.name == 'nt' and os.path.exists(filepath):
            os.remove(filepath)
        os.rename(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


class AnalyzeRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    depth: int = 3
    database_id: Optional[str] = None
    database_name: Optional[str] = None


# ========== 会话管理 ==========

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sessions: {e}")
            bak = SESSIONS_FILE + '.bak'
            if os.path.exists(bak):
                try:
                    with open(bak, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
    return {}


def save_sessions():
    atomic_json_write(SESSIONS_FILE, sessions)
    logger.info("Indicator sessions saved")


sessions = load_sessions()
logger.info(f"Indicator service started: {len(sessions)} sessions, context rounds={MAX_CONTEXT}")


# ========== 会话 stage / 意图检测 ==========

def _ensure_session(session_id: str) -> dict:
    """确保 session 存在并升级到新版数据结构（含 stage / pending_indicators）。"""
    if session_id not in sessions:
        sessions[session_id] = {
            "stage": "analyzing",
            "messages": [],
            "pending_indicators": None,
        }
        return sessions[session_id]

    s = sessions[session_id]
    # 兼容旧格式：纯 list → 新 dict 格式迁移
    if isinstance(s, list):
        sessions[session_id] = {
            "stage": "analyzing",
            "messages": s,
            "pending_indicators": None,
        }
    else:
        s.setdefault("stage", "analyzing")
        s.setdefault("messages", [])
        s.setdefault("pending_indicators", None)
    return sessions[session_id]


def _get_recent_messages(session_id: str) -> list:
    """获取最近对话消息（用于上下文构建）。"""
    s = _ensure_session(session_id)
    return s["messages"]

def _get_session_stage(session_id: str) -> str:
    """获取当前 session stage。"""
    s = _ensure_session(session_id)
    return s.get("stage", "analyzing")

def _set_session_stage(session_id: str, stage: str):
    """设置 session stage。"""
    s = _ensure_session(session_id)
    s["stage"] = stage
    save_sessions()

def _set_pending_indicators(session_id: str, indicators_data: dict):
    """保存待查询的指标体系数据。"""
    s = _ensure_session(session_id)
    s["pending_indicators"] = indicators_data
    save_sessions()

def _get_pending_indicators(session_id: str) -> dict:
    """获取待查询的指标体系数据。"""
    s = _ensure_session(session_id)
    return s.get("pending_indicators") or {}

def _clear_pending_indicators(session_id: str):
    """清空待查询数据并回到 analyzing。"""
    s = _ensure_session(session_id)
    s["pending_indicators"] = None
    s["stage"] = "analyzing"
    save_sessions()


def _is_query_confirm(text: str) -> bool:
    """检测用户输入是否表达了"查询"确认意图。"""
    t = text.strip().lower()
    # 去掉标点
    import re as _re
    t_clean = _re.sub(r'[，。！？、；：""''（）\s]', '', t)
    for kw in _QUERY_CONFIRM_KEYWORDS:
        if kw in t_clean:
            # 排除"不查询"类否定
            if not any(dk in t_clean for dk in _QUERY_DENY_KEYWORDS):
                return True
    return False


def _is_query_deny(text: str) -> bool:
    """检测用户输入是否表达了"不查询"意图。"""
    t = text.strip().lower()
    import re as _re
    t_clean = _re.sub(r'[，。！？、；：""''（）\s]', '', t)
    for kw in _QUERY_DENY_KEYWORDS:
        if kw in t_clean:
            return True
    return False


def _fetch_available_databases() -> list:
    """从 admin-service 获取可用数据源列表。"""
    import re as _re
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/database/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
                return data.get("databases", [])
    except Exception as e:
        logger.warning(f"Failed to fetch databases: {e}")
    return []


def _match_database(user_text: str, databases: list) -> dict:
    """根据用户输入匹配数据源（按名称或ID）。"""
    import re as _re
    t = user_text.strip()
    if not databases:
        return {}

    # 精确 ID 匹配
    for db in databases:
        if t == db.get("id", ""):
            return db

    # 精确名称匹配
    for db in databases:
        if t == db.get("name", ""):
            return db

    # 名称包含匹配
    for db in databases:
        name = db.get("name", "")
        if name and name in t:
            return db
        if t in name:
            return db

    # 模糊：取最后一个可能是名称的词尝试匹配
    words = _re.split(r'[，。！？、；：""''（）\s]+', t)
    for word in reversed(words):
        if len(word) >= 2:
            for db in databases:
                name = db.get("name", "")
                if word in name or name in word:
                    return db
    return {}


# ========== 查询管线（调用 evaluation-api） ==========

def _stream_indicator_query(session_id: str, query: str, database_id: str, database_name: str,
                            pending_indicators: dict) -> Generator[str, None, None]:
    """
    调用 qa-service 的 evaluation-api 执行指标查询管线。

    将指标分析结果作为 indicator_defs 传入，复用评估分析的
    Data Explore → Table Select → SQL Gen → SQL Exec → Analyst 管线。

    Yields:
        SSE JSON 行（每行以 \n 结尾）
    """
    body = json.dumps({
        "question": query,
        "database_id": database_id,
        "database_name": database_name,
        "indicator_defs": pending_indicators.get("indicators", []),
        "analysis_plan": pending_indicators.get("summary", ""),
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{EVALUATION_API_URL}/evaluation/indicator-query/stream",
        data=body,
        method="POST"
    )
    req.add_header("Content-Type", "application/json")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=180, context=ssl_ctx) as resp:
            for line in resp:
                yield line.decode("utf-8")
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

        body = json.dumps({
            "query": prompt,
            "top_k": 10
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{QA_SERVICE_URL}/qa/chat",
            data=body,
            method="POST"
        )
        req.add_header("Content-Type", "application/json")

        ctx_ssl = ssl.create_default_context()
        ctx_ssl.check_hostname = False
        ctx_ssl.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, timeout=120, context=ctx_ssl) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data.get("answer", "")

            result = parse_structured_response(answer)

            return result
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

        # 优先级1: 查找 ---JSON--- 或 ---正在生成指标体系--- 分隔符，取分隔符之后的部分
        sep_match = re.search(r'---\s*(?:JSON|正在生成指标体系)\s*---', answer)
        if sep_match:
            after_sep = answer[sep_match.end():].strip()
            if after_sep:
                json_str = after_sep

        # 优先级2: 如果已提取到分隔符后的内容，尝试直接解析；否则按原逻辑搜索
        if json_str is None:
            # 否则按原有逻辑搜索
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
    for sid, s_data in sessions.items():
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
    _ensure_session(new_id)
    save_sessions()
    return {"success": True, "session_id": new_id}


@app.delete("/indicator/session/{session_id}")
async def delete_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        save_sessions()
        return {"success": True}
    raise HTTPException(status_code=404, detail="会话不存在")


# ========== 分析 API ==========

@app.post("/indicator/analyze")
async def analyze_indicator(request: AnalyzeRequest):
    """分析指标请求（非流式，兼容旧版）"""
    session_id = request.session_id or str(uuid.uuid4())
    _ensure_session(session_id)

    # 滑动窗口上下文
    msgs = _get_recent_messages(session_id)
    recent = msgs[-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')[:200]}\n"

    result = call_llm_for_indicator_analysis(request.query, context)

    now_str = datetime.now().isoformat()
    s = _ensure_session(session_id)
    s["messages"].append({"role": "user", "content": request.query, "timestamp": now_str})
    s["messages"].append({
        "role": "assistant",
        "content": result.get("summary", result.get("answer", "")[:200]),
        "timestamp": now_str
    })
    if len(s["messages"]) > MAX_CONTEXT * 4:
        s["messages"] = s["messages"][-(MAX_CONTEXT * 4):]

    # 非流式接口不触发追问机制，直接返回
    _set_session_stage(session_id, "done")
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
    _ensure_session(session_id)
    stage = _get_session_stage(session_id)
    msgs = _get_recent_messages(session_id)

    logger.info(f"Indicator analyze/stream: session={session_id}, stage={stage}, query={request.query[:80]}")

    # =====================================================================
    # 分支 A：用户正处于"待确认"阶段 → 解析意图
    # =====================================================================
    if stage == "awaiting_confirmation":
        user_text = request.query.strip()

        # ── 子分支 A0：用户输入了新问题（不是确认也不是拒绝） ──
        if _is_new_question(user_text):
            logger.info(f"[{session_id}] Detected new question in awaiting_confirmation stage, resetting to analyzing")
            stage = "analyzing"
            _set_session_stage(session_id, "analyzing")
            # 不需要 yield 任何事件，继续走下面的逻辑

        # ── 子分支 A1：用户表示"不查询" ──
        elif _is_query_deny(user_text):
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

                s = _ensure_session(session_id)
                s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})
                s["messages"].append({"role": "assistant", "content": resp_text, "timestamp": now_str})
                _set_session_stage(session_id, "done")
                _clear_pending_indicators(session_id)

            return StreamingResponse(
                generate_deny(),
                media_type="application/x-ndjson",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )

        # ── 子分支 A2：用户表示"查询" ──
        elif _is_query_confirm(user_text):
            # 先看用户是否在输入中直接带了数据源
            database_id = request.database_id
            database_name = request.database_name or ""

            # 如果前端没传，尝试从用户文本中匹配
            if not database_id:
                dbs = _fetch_available_databases()
                matched = _match_database(user_text, dbs)
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
                pending = _get_pending_indicators(session_id)
                original_query = pending.get("original_query", request.query) if pending else request.query

                def generate_query():
                    now_str = datetime.now().isoformat()
                    _set_session_stage(session_id, "querying")

                    s = _ensure_session(session_id)
                    s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})

                    # 先创建助手消息，后续所有 text 事件都流入同一个 bubble
                    yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"

                    start_text = f"好的，正在使用数据源「{database_name or database_id}」查询这些指标..."
                    yield json.dumps({"type": "text", "content": start_text}, ensure_ascii=False) + "\n"

                    # 调用 evaluation-api 执行查询管线
                    final_answer = ""
                    pending = _get_pending_indicators(session_id)
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
                    _set_session_stage(session_id, "done")
                    _clear_pending_indicators(session_id)

                return StreamingResponse(
                    generate_query(),
                    media_type="application/x-ndjson",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no"
                    }
                )

            # 没有找到数据源 → 列出可用数据源，让用户选择
            else:
                dbs = _fetch_available_databases()
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

                    s = _ensure_session(session_id)
                    s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})
                    s["messages"].append({"role": "assistant", "content": resp_text, "timestamp": now_str})
                    # 仍然保持 awaiting_confirmation，等用户提供数据源
                    save_sessions()

                return StreamingResponse(
                    generate_list_dbs(),
                    media_type="application/x-ndjson",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no"
                    }
                )

        # ── 子分支 A3：既不是确认也不是否认 → 当成"在 awaiting 阶段提供数据源名"处理 ──
        dbs = _fetch_available_databases()
        matched = _match_database(user_text, dbs)
        if matched:
            database_id = matched.get("id", "")
            database_name = matched.get("name", "")
            pending = _get_pending_indicators(session_id)
            original_query = pending.get("original_query", "") if pending else ""

            def generate_query_by_name():
                now_str = datetime.now().isoformat()
                _set_session_stage(session_id, "querying")

                s = _ensure_session(session_id)
                s["messages"].append({"role": "user", "content": user_text, "timestamp": now_str})

                # 先创建助手消息，后续所有 text 事件都流入同一个 bubble
                yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"

                start_text = f"好的，使用数据源「{database_name or database_id}」开始查询指标..."
                yield json.dumps({"type": "text", "content": start_text}, ensure_ascii=False) + "\n"

                final_answer = ""
                pending = _get_pending_indicators(session_id)
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
                _set_session_stage(session_id, "done")
                _clear_pending_indicators(session_id)

            return StreamingResponse(
                generate_query_by_name(),
                media_type="application/x-ndjson",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"
                }
            )

        # 完全不匹配 → 可能是新问题，重置为 analyzing 走正常流程
        logger.info(f"User text in awaiting_confirmation not matched: {user_text[:50]}, resetting to analyzing")
        _set_session_stage(session_id, "analyzing")
        _clear_pending_indicators(session_id)
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
            return StreamingResponse(generate_greeting(), media_type="application/x-ndjson")

        if query_type == "concept_qa":
            # 概念问答 → 直接走知识库检索 + LLM 总结
            def generate_concept_qa():
                now_str = datetime.now().isoformat()
                s = _ensure_session(session_id)
                s["messages"].append({"role": "user", "content": request.query, "timestamp": now_str})

                yield json.dumps({"type": "new_message", "content": ""}, ensure_ascii=False) + "\n"

                for ev in _handle_concept_qa_stream(session_id, request.query):
                    yield ev

                _set_session_stage(session_id, "done")
            return StreamingResponse(generate_concept_qa(), media_type="application/x-ndjson")

        # 否则走原有的 Phase 1 指标体系生成流程（已有代码，不需要动）

    # 如果是 done 重置为 analyzing
    if stage == "done":
        _set_session_stage(session_id, "analyzing")

    recent = msgs[-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')[:200]}\n"

    ctx_str = ""
    if context:
        ctx_str = f"\n\n历史对话上下文:\n{context}"

    # 从 admin 获取已配置的指标作为参考
    db_indicators_text = ""
    try:
        req_db = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/indicator/list",
            method="GET"
        )
        req_db.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req_db, timeout=5) as resp_db:
            db_data = json.loads(resp_db.read().decode("utf-8"))
            if db_data.get("success") and db_data.get("indicators"):
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

请严格按照以下步骤输出：

第一步：先输出一行 ---JSON--- 作为分隔符。
第二步：紧跟一个可以被 json.loads 解析的 JSON 对象，包含 tree、indicators、summary 三个字段。
第三步：输出一行 ---分析结束--- 作为分隔符。
第四步：最后输出一段简短的分析总结（1-2句话，描述你构建指标体系的核心思路）。

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
        json_buf = ""
        lead_buf = ""       # lead 阶段缓冲：发现 --- 后暂存的文本
        saw_sep = False     # 是否已发现 ---（可能正在接收 ---JSON---）
        now_str = datetime.now().isoformat()
        phase = "lead"  # lead → json → analysis → done
        result_sent = False

        # ── Phase 1 Step 1：正在解析指标体系 ──
        yield json.dumps({
            "type": "step",
            "step": {"step": 1, "description": "解析指标体系", "status": "in_progress", "detail": "正在调用大模型分析指标需求"}
        }, ensure_ascii=False) + "\n"

        try:
            body = json.dumps({"query": prompt, "top_k": 10}).encode("utf-8")
            req = urllib.request.Request(
                f"{QA_SERVICE_URL}/qa/chat/stream",
                data=body, method="POST"
            )
            req.add_header("Content-Type", "application/json")
            ctx_ssl = ssl.create_default_context()
            ctx_ssl.check_hostname = False
            ctx_ssl.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=180, context=ctx_ssl) as resp:
                for line in resp:
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    try:
                        data = json.loads(line_str)
                        if data.get("type") == "text":
                            chunk = data.get("content", "")
                            full_text += chunk

                            if phase == "lead":
                                # 查找 ---JSON--- 分隔符
                                sep_idx = full_text.find("---JSON---")
                                if sep_idx >= 0:
                                    # ---JSON--- 已找到，不重复转发 pre 文本
                                    # （pre 内容已通过逐片 chunk 转发到前端）
                                    # 直接进入 JSON 解析阶段
                                    json_start = sep_idx + len("---JSON---")
                                    json_buf = full_text[json_start:]
                                    saw_sep = False
                                    phase = "json"
                                else:
                                    # 还没到分隔符，逐片转发（同时过滤 --- 标记符残余）
                                    if "---" in chunk or saw_sep:
                                        # 发现 --- 标记 → 进入缓冲模式
                                        # 后续所有不含 --- 的 token（如 "JSON"）都不会泄漏
                                        if "---" in chunk:
                                            clean_end = chunk.find("---")
                                            if clean_end > 0:
                                                clean_chunk = chunk[:clean_end].strip()
                                                # 有中文才转发，过滤标记符碎片（如 "JSON"、"J" 等）
                                                if clean_chunk and any('\u4e00' <= c <= '\u9fff' for c in clean_chunk):
                                                    yield json.dumps({"type": "text", "content": clean_chunk}, ensure_ascii=False) + "\n"
                                        # 不管是否在 chunk 中找到 ---，都设置缓冲标记
                                        # 这样下一段 token（如 "JSON"、"已为您生成了"）不会泄漏
                                        saw_sep = True
                                    elif chunk.strip():
                                        yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"

                            elif phase == "json":
                                json_buf += chunk
                                # 查找 ---分析结束--- 分隔符
                                end_idx = json_buf.find("---分析结束---")
                                if end_idx >= 0:
                                    json_str = json_buf[:end_idx]
                                    # 解析 JSON
                                    result = parse_structured_response(json_str)
                                    tree = result.get("tree")
                                    indicators = result.get("indicators", [])
                                    summary = result.get("summary", "")

                                    # 指标生成失败
                                    if not indicators:
                                        yield json.dumps({
                                            "type": "error",
                                            "session_id": session_id,
                                            "message": "指标体系生成失败：大模型未返回有效结果，请检查大模型配置后重试。",
                                        }, ensure_ascii=False) + "\n"
                                        return

                                    # ── Step 1 完成 ──
                                    indicator_count = len(indicators)
                                    yield json.dumps({
                                        "type": "step",
                                        "step": {"step": 1, "description": "解析指标体系", "status": "completed",
                                                 "detail": f"共识别 {indicator_count} 个指标"}
                                    }, ensure_ascii=False) + "\n"

                                    # 保存待查询的指标体系
                                    indicator_names = [ind.get("name", "") for ind in indicators[:5]]
                                    names_str = "、".join(indicator_names)
                                    if indicator_count > 5:
                                        names_str += f" 等共{indicator_count}个指标"
                                    _set_pending_indicators(session_id, {
                                        "tree": tree,
                                        "indicators": indicators,
                                        "summary": summary,
                                        "original_query": request.query,
                                        "generated_at": datetime.now().isoformat(),
                                    })
                                    _set_session_stage(session_id, "awaiting_confirmation")

                                    # ── 发送 result，前端渲染指标卡片 ──
                                    yield json.dumps({
                                        "type": "result",
                                        "session_id": session_id,
                                        "tree": tree,
                                        "indicators": indicators,
                                    }, ensure_ascii=False, default=str) + "\n"

                                    result_sent = True
                                    phase = "analysis"

                                    # 发送结构化摘要（代替冗余的 raw remaining 文本）
                                    yield json.dumps({
                                        "type": "text",
                                        "content": f"已为您生成 {indicator_count} 个指标的指标体系，包含指标树状结构和各指标的计算方式。主要指标：{names_str}。"
                                    }, ensure_ascii=False) + "\n"

                            elif phase == "analysis":
                                # 分析文本自然流式输出
                                # 过滤与已有内容高度重复的文本
                                if not chunk.strip():
                                    continue
                                yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"

                        elif data.get("type") == "error":
                            yield json.dumps({"type": "text", "content": data.get("content", "")}, ensure_ascii=False) + "\n"
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            yield json.dumps({"type": "text", "content": f"分析失败: {str(e)[:200]}"}, ensure_ascii=False) + "\n"

        # ── 容错：如果 LLM 没按新格式输出，走旧逻辑 ──
        if not result_sent:
            result = parse_structured_response(full_text)
            tree = result.get("tree")
            indicators = result.get("indicators", [])
            # 清理 full_text 中的标记符，避免 ---JSON--- 等泄漏给前端
            clean_fallback = re.sub(r'---.*?(?:JSON|正在生成指标体系|分析结束).*?---', '', full_text).strip()
            summary = result.get("summary", result.get("answer", clean_fallback[:200]))
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
                         "detail": f"共识别 {indicator_count} 个指标"}
            }, ensure_ascii=False) + "\n"
            indicator_names = [ind.get("name", "") for ind in indicators[:5]]
            names_str = "、".join(indicator_names)
            if indicator_count > 5:
                names_str += f" 等共{indicator_count}个指标"
            _set_pending_indicators(session_id, {
                "tree": tree,
                "indicators": indicators,
                "summary": summary,
                "original_query": request.query,
                "generated_at": datetime.now().isoformat(),
            })
            _set_session_stage(session_id, "awaiting_confirmation")
            yield json.dumps({
                "type": "result",
                "session_id": session_id,
                "tree": tree,
                "indicators": indicators,
            }, ensure_ascii=False, default=str) + "\n"

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
        s = _ensure_session(session_id)
        s["messages"].append({"role": "user", "content": request.query, "timestamp": now_str})
        s["messages"].append({"role": "assistant", "content": summary or full_text[:200], "timestamp": now_str})
        s["messages"].append({"role": "assistant", "content": follow_up.strip(), "timestamp": now_str})
        if len(s["messages"]) > MAX_CONTEXT * 4:
            s["messages"] = s["messages"][-(MAX_CONTEXT * 4):]
        save_sessions()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/indicator/history")
async def get_history(session_id: str):
    """获取指定会话的消息"""
    if session_id not in sessions:
        return {"messages": []}
    s = sessions[session_id]
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
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/indicator/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
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
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/indicator/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
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
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/indicator/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success"):
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
