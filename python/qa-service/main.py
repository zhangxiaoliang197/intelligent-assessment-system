from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Generator
from datetime import datetime
import uuid
import json
import os
import tempfile
import urllib.request
import urllib.error
import ssl
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("qa-service")

app = FastAPI(
    title="智能问答服务",
    description="基于大模型的智能问答系统",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# LLM 配置现在从 Java admin-service 的 MySQL 数据库中获取
# 支持多配置管理和活跃配置切换
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SESSIONS_FILE = os.path.join(DATA_DIR, 'sessions.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
os.makedirs(DATA_DIR, exist_ok=True)

# 滑动窗口大小：保留最近N轮对话作为上下文
MAX_CONTEXT = int(os.getenv("QA_CONTEXT_ROUNDS", "5"))

def atomic_json_write(filepath, data):
    """原子写入JSON文件，防止写入中断导致文件损坏"""
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

def load_llm_config():
    """从 Java admin-service API 获取当前活跃的大模型配置"""
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm/active",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
            # 没有活跃配置，尝试从配置列表中取第一个可用配置作为兜底
            logger.warning("No active LLM config found, trying config list fallback...")
    except Exception as e:
        logger.warning(f"Failed to fetch LLM config from admin-service: {e}")

    # 兜底：从配置列表中取第一个可用配置（优先 vllm > openai > deepseek > 其他）
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            list_data = json.loads(resp.read().decode("utf-8"))
            if list_data.get("success") and list_data.get("data"):
                configs = list_data["data"]
                if isinstance(configs, list) and len(configs) > 0:
                    # 优先找 vllm/openai/deepseek 类型的配置
                    priority_order = ["vllm", "openai", "deepseek"]
                    for pt in priority_order:
                        for c in configs:
                            if c.get("type") == pt and c.get("apiUrl"):
                                logger.info(f"Using {pt} config from list: model={c.get('model')}, url={c.get('apiUrl')}")
                                return c
                    # 没匹配到优先类型，取第一个有 apiUrl 的
                    for c in configs:
                        if c.get("apiUrl"):
                            logger.info(f"Using fallback config: type={c.get('type')}, model={c.get('model')}")
                            return c
                    # 所有配置都没有 apiUrl，取第一个
                    logger.info(f"Using first config from list: type={configs[0].get('type')}")
                    return configs[0]
    except Exception:
        pass

    logger.warning("No LLM config available, using hardcoded defaults")
    return {
        "type": "deepseek",
        "apiUrl": "https://api.deepseek.com/v1",
        "apiKey": "",
        "model": "deepseek-chat",
        "temperature": 0.7,
        "maxTokens": 2000,
        "topP": 0.9
    }

KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")

def search_knowledge(query, top_k=5):
    try:
        body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            f"{KNOWLEDGE_SERVICE_URL}/knowledge/search",
            data=body, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("results", [])
    except Exception:
        return []

def call_llm_api(query, context=""):
    api_url, api_key, model, temperature, max_tokens, messages, err = get_llm_messages(query, context)
    if api_url is None:
        return err, [], []

    references, sources = err

    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }).encode("utf-8")

    url = f"{api_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
            return answer, references, sources
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err = json.loads(err_body)
            msg = err.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        return f"大模型调用失败 (HTTP {e.code}): {msg[:500]}", [], []
    except Exception as e:
        return f"大模型调用失败: {str(e)[:500]}", [], []

def get_llm_messages(query, context=""):
    """构建 LLM 请求消息（复用逻辑）"""
    config = load_llm_config()
    llm_type = config.get("type", "deepseek")
    api_key = config.get("apiKey", "")
    api_url = config.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = config.get("model", "deepseek-chat")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("maxTokens", 2000)

    # vLLM 是本地部署，无需 API Key
    if not api_key and llm_type != "vllm":
        return None, None, None, None, None, None, "大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置。"

    knowledge_chunks = search_knowledge(query, top_k=5)
    knowledge_context = ""
    references = []
    sources = []

    if knowledge_chunks:
        for i, ch in enumerate(knowledge_chunks):
            knowledge_context += f"\n\n[参考资料{i + 1} - {ch.get('title', '未知')}]\n{ch.get('content', '')}"
            references.append(f"{ch.get('title', '未知')} (相关度: {ch.get('score', 0):.0%})")
            sources.append({
                "title": ch.get("title", "未知"),
                "category": ch.get("category", "未分类"),
                "score": ch.get("score", 0)
            })

    system_prompt = "你是一个专业的智能评估系统助手，擅长作战效能评估、指标体系分析、方案评估等领域。请用中文回答，回答要专业、准确、有条理。"

    if knowledge_context:
        system_prompt += f"\n\n以下是知识库中检索到的相关参考资料，请优先基于这些资料回答问题：{knowledge_context}"

    ctx = ""
    if context:
        ctx = f"\n\n历史对话上下文（最近{MAX_CONTEXT}轮）:\n{context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query + ctx}
    ]

    return api_url, api_key, model, temperature, max_tokens, messages, (references, sources)

def stream_llm_api(query, context="") -> Generator[str, None, tuple]:
    """流式调用 LLM API，逐块 yield 文本，最后 return (完整文本, references, sources)"""
    api_url, api_key, model, temperature, max_tokens, messages, refs_src = get_llm_messages(query, context)
    if api_url is None:
        yield refs_src  # 这是错误信息字符串
        return refs_src, [], []

    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True
    }).encode("utf-8")

    url = f"{api_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    full_answer = ""

    try:
        with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        full_answer += content
                        yield content
                except json.JSONDecodeError:
                    continue

        return full_answer

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err = json.loads(err_body)
            msg = err.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        error_msg = f"大模型调用失败 (HTTP {e.code}): {msg[:500]}"
        yield error_msg
        return error_msg
    except Exception as e:
        error_msg = f"大模型调用失败: {str(e)[:500]}"
        yield error_msg
        return error_msg

class ChatMessage(BaseModel):
    role: str
    content: str
    references: Optional[List[str]] = []

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    top_k: int = 5

class ChatResponse(BaseModel):
    answer: str
    references: List[str]
    session_id: str
    sources: List[dict]

class HistoryItem(BaseModel):
    id: str
    query: str
    answer: str
    timestamp: datetime

class LlmConfigRequest(BaseModel):
    type: str = "deepseek"
    apiUrl: str = "https://api.deepseek.com/v1"
    apiKey: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.7
    maxTokens: int = 2000
    topP: float = 0.9

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sessions.json: {e}, trying backup")
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
    logger.info("Sessions saved")

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [HistoryItem(**item) for item in data]
        except Exception as e:
            logger.warning(f"Failed to load history.json: {e}, trying backup")
            bak = HISTORY_FILE + '.bak'
            if os.path.exists(bak):
                try:
                    with open(bak, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        return [HistoryItem(**item) for item in data]
                except Exception:
                    pass
    return []

def save_history():
    atomic_json_write(HISTORY_FILE, [h.dict() for h in chat_history])
    logger.info("History saved")

sessions = load_sessions()
chat_history = load_history()
logger.info(f"QA service started: {len(sessions)} sessions, {len(chat_history)} history items, context rounds={MAX_CONTEXT}")

@app.get("/")
async def root():
    return {"service": "qa-service", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# ========== 会话管理 API ==========

@app.get("/qa/sessions")
async def list_sessions():
    """返回所有会话列表，以最新问题为标题"""
    session_list = []
    for sid, msgs in sessions.items():
        if not msgs:
            continue
        # 找到最新一条用户消息作为标题
        latest_question = ""
        last_time = ""
        for msg in reversed(msgs):
            if msg.get("role") == "user":
                q = msg.get("content", "").strip()
                latest_question = q[:30] if len(q) > 30 else q
                break
        # 获取时间戳
        last_msg = msgs[-1] if msgs else {}
        last_time = last_msg.get("timestamp", datetime.now().isoformat())
        session_list.append({
            "id": sid,
            "title": latest_question or "(空会话)",
            "message_count": len(msgs),
            "last_active": last_time
        })
    # 按最后活跃时间倒序排列
    session_list.sort(key=lambda x: x.get("last_active", ""), reverse=True)
    return {"success": True, "sessions": session_list}

@app.post("/qa/session/new")
async def new_session():
    """创建一个新会话，返回新的 session_id"""
    new_id = str(uuid.uuid4())
    sessions[new_id] = []
    save_sessions()
    logger.info(f"New session created: {new_id}")
    return {"success": True, "session_id": new_id}

@app.delete("/qa/session/{session_id}")
async def delete_session(session_id: str):
    """删除整个会话"""
    if session_id in sessions:
        del sessions[session_id]
        save_sessions()
        logger.info(f"Session deleted: {session_id}")
        return {"success": True}
    raise HTTPException(status_code=404, detail="会话不存在")

# ========== 对话 API ==========

@app.post("/qa/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    # 滑动窗口：取最近 MAX_CONTEXT*2 条消息（user + assistant 各算一条）
    recent = sessions[session_id][-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')}\n"

    answer, references, sources = call_llm_api(request.query, context)

    now_str = datetime.now().isoformat()
    sessions[session_id].append({"role": "user", "content": request.query, "timestamp": now_str})
    sessions[session_id].append({"role": "assistant", "content": answer, "timestamp": now_str})

    # 只保留最近 MAX_CONTEXT*2 条消息（控制内存和文件大小）
    if len(sessions[session_id]) > MAX_CONTEXT * 4:
        sessions[session_id] = sessions[session_id][-(MAX_CONTEXT * 4):]

    chat_history.append(HistoryItem(
        id=str(uuid.uuid4()),
        query=request.query,
        answer=answer,
        timestamp=datetime.now()
    ))

    save_sessions()
    save_history()
    return ChatResponse(
        answer=answer,
        references=references,
        session_id=session_id,
        sources=sources
    )

# ========== 流式对话 API ==========

@app.post("/qa/chat/stream")
async def chat_stream(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    if session_id not in sessions:
        sessions[session_id] = []

    recent = sessions[session_id][-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')}\n"

    # 先发送 sources + session_id
    _, __, ___, ____, _____, ______, refs_src = get_llm_messages(request.query, context)
    if refs_src is None:
        refs_src = ([], [])

    def generate():
        full_answer = ""
        gen = stream_llm_api(request.query, context)
        try:
            for chunk in gen:
                full_answer += chunk
                yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"
            # 获取 references 和 sources
            api_url, api_key, model, temp, mt, msgs, rs = get_llm_messages(request.query, context)
            references, sources = (rs if isinstance(rs, tuple) else ([], []))
            yield json.dumps({
                "type": "done",
                "session_id": session_id,
                "references": references,
                "sources": sources
            }, ensure_ascii=False, default=str) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "content": str(e)[:500]}, ensure_ascii=False) + "\n"

        # 保存会话
        now_str = datetime.now().isoformat()
        sessions[session_id].append({"role": "user", "content": request.query, "timestamp": now_str})
        sessions[session_id].append({"role": "assistant", "content": full_answer, "timestamp": now_str})
        if len(sessions[session_id]) > MAX_CONTEXT * 4:
            sessions[session_id] = sessions[session_id][-(MAX_CONTEXT * 4):]

        chat_history.append(HistoryItem(
            id=str(uuid.uuid4()),
            query=request.query,
            answer=full_answer,
            timestamp=datetime.now()
        ))
        save_sessions()
        save_history()

    response = StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
    return response

# ========== 历史记录 API ==========

@app.get("/qa/history")
async def get_history(session_id: str):
    """获取指定会话的所有消息"""
    if session_id not in sessions:
        return {"messages": []}
    return {
        "messages": [
            {
                "role": msg["role"],
                "content": msg["content"],
                "references": []
            }
            for msg in sessions[session_id]
        ]
    }

@app.get("/qa/history/list")
async def list_history():
    """返回所有历史记录（按会话分组）"""
    items = []
    for sid, msgs in sessions.items():
        if not msgs:
            continue
        latest_question = ""
        for msg in reversed(msgs):
            if msg.get("role") == "user":
                q = msg.get("content", "").strip()
                latest_question = q[:30] if len(q) > 30 else q
                break
        last_time = msgs[-1].get("timestamp", datetime.now().isoformat())
        items.append({
            "id": sid,
            "title": latest_question or "(空会话)",
            "query": latest_question,
            "timestamp": str(last_time)
        })
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"items": items[-20:]}

@app.delete("/qa/history/{session_id}")
async def clear_history(session_id: str):
    if session_id in sessions:
        sessions[session_id] = []
        save_sessions()
        return {"message": "历史记录已清空"}
    raise HTTPException(status_code=404, detail="会话不存在")

# ========== LLM 配置 API ==========
# 现在从 Java admin-service 获取 MySQL 中持久化的配置

@app.get("/config/llm")
async def get_llm_config():
    """获取当前活跃的大模型配置"""
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm/active",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to fetch LLM config: {e}")
        return {"success": False, "message": "无法连接到管理服务", "data": load_llm_config()}

@app.get("/config/llm/list")
async def list_llm_configs():
    """列出所有大模型配置"""
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm/list",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"获取失败: {str(e)}"}

@app.post("/config/llm")
async def save_llm_config_endpoint(config: LlmConfigRequest):
    """保存新的大模型配置"""
    try:
        body = json.dumps(config.dict()).encode("utf-8")
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm",
            data=body, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"保存失败: {str(e)}"}

@app.put("/config/llm/{config_id}/activate")
async def activate_llm_config(config_id: str):
    """激活指定的大模型配置"""
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm/{config_id}/activate",
            method="PUT"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"切换失败: {str(e)}"}

@app.delete("/config/llm/{config_id}")
async def delete_llm_config(config_id: str):
    """删除大模型配置"""
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/config/llm/{config_id}",
            method="DELETE"
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"删除失败: {str(e)}"}

# ========== 方案评估 API（多智能体） ==========
try:
    from evaluation_api import evaluation_router
    app.include_router(evaluation_router)
    logger.info("Evaluation router registered")
except Exception as e:
    logger.warning(f"Failed to register evaluation router: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10253)
