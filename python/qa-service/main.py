from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Generator
from datetime import datetime
import uuid
import json
import os
import base64
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
IMAGES_DIR = os.path.join(DATA_DIR, 'images')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

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
            results = data.get("results", [])
            # 调试：打印知识库返回的第一个结果的字段名
            if results:
                logger.debug(f"KB result sample keys: {list(results[0].keys())}")

            # 按文档去重 + title 规范化（知识库服务已做 doc_id 去重，此处兜底）
            deduped = []
            seen_titles = set()
            for i, r in enumerate(results):
                raw_title = r.get("title", "")
                # title 为空/纯数字 → 尝试 filename 字段
                is_bare_number = isinstance(raw_title, str) and raw_title.strip().isdigit()
                if not isinstance(raw_title, str) or not raw_title.strip() or is_bare_number:
                    alt = r.get("filename") or r.get("name") or r.get("source") or r.get("file") or ""
                    if alt and str(alt).strip() and not str(alt).strip().isdigit():
                        raw_title = str(alt).strip()
                    else:
                        raw_title = "知识库文档"
                else:
                    raw_title = raw_title.strip()

                r["title"] = raw_title

                if raw_title in seen_titles:
                    continue
                seen_titles.add(raw_title)
                deduped.append(r)

            return deduped
    except Exception:
        return []


# ── 图片支持检测 ──
# 仅列出已验证支持 OpenAI image_url 格式的模型。
# deepseek-chat 实际不支持 image_url → 不列入。
_IMAGE_CAPABLE_PATTERNS = [
    "gpt-4o", "gpt-4-turbo", "gpt-4-vision", "gpt-4-turbo-preview",
    "claude-3", "claude-3.5", "claude-3-5",
    "gemini-2", "gemini-2.5", "gemini-1.5",
    "qwen-vl", "qwen2-vl", "qwen2.5-vl",
    "glm-4v", "cogvlm", "cogvlm2",
    "yi-vl", "yi-vision",
    "internvl", "internvl2",
    "llava", "llava-next", "llava-v1",
    "vision", "vl", "multimodal", "omni",
]


def _model_supports_images(config: dict = None) -> bool:
    """检测当前配置的大模型是否支持图片多模态输入"""
    if config is None:
        config = load_llm_config()
    if not config:
        return False
    model = (config.get("model") or "").lower()
    return any(pattern in model for pattern in _IMAGE_CAPABLE_PATTERNS)


def _load_image_base64(image_id: str) -> tuple:
    """
    从 data/images/{image_id} 读取图片并转为 base64 data URL。

    Returns:
        tuple[str, str]: (data_url, mime_type)，失败时返回 ("", "")
    """
    import imghdr
    image_path = os.path.join(IMAGES_DIR, image_id)
    if not os.path.exists(image_path):
        return "", ""

    mime_map = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}
    img_type = imghdr.what(image_path) or "png"
    mime = mime_map.get(img_type, "image/png")

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}", mime


def _get_attachment_text(attachment_id: Optional[str]) -> str:
    """根据 attachment_id 获取缓存的文档文本"""
    if not attachment_id:
        return ""
    try:
        from attachment_handler import get_attachment_text
        return get_attachment_text(attachment_id) or ""
    except Exception as e:
        logger.warning(f"Failed to get attachment text for {attachment_id}: {e}")
        return ""

def _get_attachment_info(attachment_id: Optional[str]) -> tuple:
    """获取附件信息，返回 (text, filename)"""
    if not attachment_id:
        return "", ""
    try:
        from attachment_handler import get_attachment_text, get_attachment_filename
        text = get_attachment_text(attachment_id) or ""
        filename = get_attachment_filename(attachment_id) or ""
        return text, filename
    except Exception as e:
        logger.warning(f"Failed to get attachment info for {attachment_id}: {e}")
        return "", ""

def call_llm_api(query, context="", attachment_text="", attachment_filename="", image_data_url=""):
    api_url, api_key, model, temperature, max_tokens, messages, err = get_llm_messages(query, context, attachment_text, attachment_filename, image_data_url)
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
        # 智能翻译：图片格式不支持
        if "image_url" in msg.lower() and "unknown variant" in msg.lower():
            msg = "当前模型不支持图片识别，请切换至 gpt-4o、qwen-vl 等支持多模态的模型"
        return f"大模型调用失败 (HTTP {e.code}): {msg[:500]}", [], []
    except Exception as e:
        return f"大模型调用失败: {str(e)[:500]}", [], []

def get_llm_messages(query, context="", attachment_text="", attachment_filename="", image_data_url=""):
    """构建 LLM 请求消息（复用逻辑）。当 image_data_url 非空时使用多模态格式。"""
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

    # ── 知识库检索 ──
    knowledge_chunks = search_knowledge(query, top_k=5)
    knowledge_context = ""
    references = []
    sources = []

    has_attachment = bool(attachment_text.strip())
    doc_filename = attachment_filename or "上传文档"

    # ── 构建 references / sources ──
    # 上传文档始终排在参考来源第一位
    if has_attachment:
        references.append(f"{doc_filename}（用户上传）")
        sources.append({
            "title": doc_filename,
            "category": "用户上传文档",
            "score": 1.0
        })

    # 知识库结果
    if knowledge_chunks:
        for i, ch in enumerate(knowledge_chunks):
            knowledge_context += f"\n\n[知识库参考{i + 1} - {ch.get('title', '未知')}]\n{ch.get('content', '')}"
            references.append(f"{ch.get('title', '未知')} (相关度: {ch.get('score', 0):.0%})")
            sources.append({
                "title": ch.get("title", "未知"),
                "category": ch.get("category", "知识库"),
                "score": ch.get("score", 0)
            })

    # ── 构建 system prompt ──
    system_prompt = "你是一个专业的智能评估系统助手，擅长作战效能评估、指标体系分析、评估分析等领域。请用中文回答，回答要专业、准确、有条理。"

    if has_attachment:
        # 文档优先：文档是主要来源，知识库仅作补充
        system_prompt += f"\n\n用户上传了一份参考文档「{doc_filename}」，以下是文档全文：\n\n---\n{attachment_text}\n---"
        if knowledge_context:
            system_prompt += (
                f"\n\n此外，系统从知识库中检索到以下资料。"
                f"如果这些资料与用户的文档或问题**明确相关**，可以作为补充参考；"
                f"如果不相关，请忽略知识库资料，**仅基于用户上传的文档内容**回答问题："
                f"{knowledge_context}"
            )
        system_prompt += "\n\n请优先基于用户上传的文档内容进行回答。如果问题超出文档范围，请如实告知。"
    elif knowledge_context:
        # 仅知识库
        system_prompt += f"\n\n以下是知识库中检索到的相关参考资料，请优先基于这些资料回答问题：{knowledge_context}"

    ctx = ""
    if context:
        ctx = f"\n\n历史对话上下文（最近{MAX_CONTEXT}轮）:\n{context}"

    user_text = query + ctx
    if image_data_url:
        # 多模态格式：content 是数组，包含图片 + 文本
        user_content = [
            {"type": "image_url", "image_url": {"url": image_data_url}},
            {"type": "text", "text": user_text},
        ]
    else:
        user_content = user_text

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    return api_url, api_key, model, temperature, max_tokens, messages, (references, sources)

def stream_llm_api(query, context="", attachment_text="", attachment_filename="", image_data_url="") -> Generator[str, None, tuple]:
    """流式调用 LLM API，逐块 yield 文本，最后 return (完整文本, references, sources)"""
    api_url, api_key, model, temperature, max_tokens, messages, refs_src = get_llm_messages(query, context, attachment_text, attachment_filename, image_data_url)
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
        # 智能翻译：图片格式不支持
        if "image_url" in msg.lower() and "unknown variant" in msg.lower():
            msg = "当前模型不支持图片识别，请切换至 gpt-4o、qwen-vl 等支持多模态的模型"
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
    attachment_id: Optional[str] = None
    image_id: Optional[str] = None

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

@app.post("/attachment/upload")
async def upload_attachment(file: UploadFile = File(...)):
    """
    上传文档文件（PDF/Word/TXT），返回解析结果和 attachment_id。
    """
    from attachment_handler import parse_and_store

    import tempfile, os as _os
    suffix = _os.path.splitext(file.filename or "")[1] or ".tmp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=DATA_DIR) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = parse_and_store(tmp_path, file.filename or "unknown")
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Attachment upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"文档解析失败: {str(e)[:200]}")
    finally:
        try:
            import os as _os2
            _os2.remove(tmp_path)
        except Exception:
            pass

@app.get("/attachment/{attachment_id}/download")
async def download_attachment(attachment_id: str):
    """
    下载上传的原始文档文件。
    """
    from attachment_handler import get_attachment_original_path, get_attachment_filename
    from fastapi.responses import FileResponse
    import os as _os3

    path = get_attachment_original_path(attachment_id)
    if not path or not _os3.path.exists(path):
        raise HTTPException(status_code=404, detail="附件不存在或已过期")

    filename = get_attachment_filename(attachment_id) or "download"
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.post("/image/upload")
async def upload_image(file: UploadFile = File(...)):
    """
    上传图片文件（PNG/JPG/GIF/WebP/BMP），保存到 data/images/，返回 image_id。

    请求：multipart/form-data，字段名 "file"
    返回：{"success": true, "image_id": "uuid.png", "filename": "xxx.png"}
    """
    import shutil as _shutil
    from attachment_handler import validate_file

    filename = file.filename or "image.png"
    ext = os.path.splitext(filename)[1].lower()
    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式: {ext}，仅支持 {', '.join(sorted(allowed))}")

    image_id = f"{uuid.uuid4()}{ext}"
    dest_path = os.path.join(IMAGES_DIR, image_id)

    content = await file.read()
    max_size = 10 * 1024 * 1024  # 10MB
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

    with open(dest_path, "wb") as f:
        f.write(content)

    return {"success": True, "image_id": image_id, "filename": filename}


@app.get("/model/supports-image")
async def check_model_image_support():
    """检查当前配置的大模型是否支持图片识别"""
    supported = _model_supports_images()
    config = load_llm_config()
    model = config.get("model", "unknown") if config else "unknown"
    return {"supports_image": supported, "model": model}


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

    attachment_text, attachment_filename = _get_attachment_info(request.attachment_id)

    # ── 图片处理 ──
    image_data_url = ""
    if request.image_id:
        if not _model_supports_images():
            raise HTTPException(status_code=400, detail="当前模型不支持图片识别，请切换至支持多模态的大模型（如 deepseek-chat、gpt-4o 等）")
        image_data_url, _ = _load_image_base64(request.image_id)
        if not image_data_url:
            raise HTTPException(status_code=400, detail="图片不存在或已过期")

    answer, references, sources = call_llm_api(request.query, context, attachment_text, attachment_filename, image_data_url)

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
    attachment_text, attachment_filename = _get_attachment_info(request.attachment_id)

    # ── 图片处理 ──
    image_data_url = ""
    if request.image_id:
        if not _model_supports_images():
            raise HTTPException(status_code=400, detail="当前模型不支持图片识别，请切换至支持多模态的大模型（如 deepseek-chat、gpt-4o 等）")
        image_data_url, _ = _load_image_base64(request.image_id)
        if not image_data_url:
            raise HTTPException(status_code=400, detail="图片不存在或已过期")

    _, __, ___, ____, _____, ______, refs_src = get_llm_messages(request.query, context, attachment_text, attachment_filename, image_data_url)
    if refs_src is None:
        refs_src = ([], [])

    def generate():
        full_answer = ""
        gen = stream_llm_api(request.query, context, attachment_text, attachment_filename, image_data_url)
        try:
            for chunk in gen:
                full_answer += chunk
                yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"
            # 获取 references 和 sources
            api_url, api_key, model, temp, mt, msgs, rs = get_llm_messages(request.query, context, attachment_text, attachment_filename, image_data_url)
            references, sources = (rs if isinstance(rs, tuple) else ([], []))
            knowledge_used = len(sources) > 0 if isinstance(sources, list) else False
            yield json.dumps({
                "type": "done",
                "session_id": session_id,
                "references": references,
                "sources": sources,
                "knowledge_used": knowledge_used
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

# ========== 评估分析 API（多智能体） ==========
try:
    from evaluation_api import evaluation_router
    from skill_api import skill_api_router
    app.include_router(evaluation_router)
    app.include_router(skill_api_router)
    logger.info("Evaluation and governed Skill routers registered")
except Exception as e:
    logger.warning(f"Failed to register evaluation router: {e}")

@app.post("/qa/classify-query")
async def classify_query(request: ChatRequest):
    """
    对用户提问做三分类：concept_qa / indicator_analysis / general_chat。

    策略：关键词快速匹配 → LLM 分类 → 关键词兜底
    """
    query = request.query

    # ── 第一层：关键词快速判断 ──
    concept_keywords = ["什么是", "什么叫", "解释", "定义", "含义", "概念", "什么意思", "如何理解", "怎么算", "是什么"]
    analysis_keywords = ["分析", "评估", "查询", "构建", "帮我查", "指标体系", "数据", "指标"]
    general_keywords = ["你好", "谢谢", "在吗", "再见", "帮个忙"]

    kw_concept = any(kw in query for kw in concept_keywords)
    kw_analysis = any(kw in query for kw in analysis_keywords)
    kw_general = any(kw in query for kw in general_keywords)

    # 关键词明确且无冲突 → 直接返回
    if kw_general and not kw_concept and not kw_analysis:
        return {"classification": "general_chat"}
    if kw_concept and not kw_analysis:
        return {"classification": "concept_qa"}
    if kw_analysis and not kw_concept:
        return {"classification": "indicator_analysis"}

    # ── 第二层：关键词冲突或不确定 → 调用 LLM ──
    config = load_llm_config()
    api_key = config.get("apiKey", "")
    api_url = config.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = config.get("model", "deepseek-chat")

    user_prompt = f"""分类以下问题：general_chat / concept_qa / indicator_analysis

{query}"""

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.1,
        "max_tokens": 20,
        "stream": False
    }).encode("utf-8")

    url = f"{api_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data["choices"][0]["message"]["content"].strip().lower()
            if "concept" in raw:
                return {"classification": "concept_qa"}
            if "indicator_analysis" in raw or "analysis" in raw:
                return {"classification": "indicator_analysis"}
            if "general" in raw:
                return {"classification": "general_chat"}
    except Exception as e:
        logger.warning(f"Classify query LLM failed: {e}")

    # ── 第三层：LLM 失败 → 关键词兜底 ──
    if kw_concept:
        return {"classification": "concept_qa"}
    if kw_analysis:
        return {"classification": "indicator_analysis"}
    return {"classification": "indicator_analysis"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10253)
