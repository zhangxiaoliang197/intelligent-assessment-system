from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Generator
from datetime import datetime
import re
import uuid
import json
import os
import base64
import tempfile
import urllib.request
import urllib.error
import ssl
import logging

from logging_config import setup_logging
setup_logging("qa-service")
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


@app.on_event("startup")
async def validate_required_skill_catalog():
    """Fail fast instead of running a partially broken QA service."""
    from agents.skill_catalog import get_catalog_diagnostics

    diagnostics = get_catalog_diagnostics()
    if not diagnostics["ready"]:
        logger.critical("Skill 目录启动校验失败: %s", diagnostics["error"])
        raise RuntimeError(diagnostics["error"])
    logger.info(
        "Skill 目录启动校验通过: path=%s, skills=%s",
        diagnostics["path"],
        diagnostics["skillCount"],
    )


# LLM 配置现在从 Java admin-service 的 MySQL 数据库中获取
# 支持多配置管理和活跃配置切换
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()


def _admin_request(path: str, *, data: bytes = None, method: str = "GET") -> urllib.request.Request:
    """Build authenticated service-to-service requests for protected admin APIs."""
    req = urllib.request.Request(f"{ADMIN_SERVICE_URL}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if INTERNAL_SERVICE_TOKEN:
        req.add_header("X-Service-Token", INTERNAL_SERVICE_TOKEN)
    return req

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
IMAGES_DIR = os.path.join(DATA_DIR, 'images')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

# 滑动窗口大小：保留最近N轮对话作为上下文
MAX_CONTEXT = int(os.getenv("QA_CONTEXT_ROUNDS", "5"))

# ── 聊天数据持久化已迁至 MySQL（通过 admin-service 的 /api/admin/chat）──
# 不再使用 sessions.json / history.json 文件存储
from chat_client import (
    create_session as _cs_create,
    update_session as _cs_update,
    delete_session as _cs_delete,
    list_sessions as _cs_list,
    get_session as _cs_get,
    add_message as _cs_add_msg,
    get_messages as _cs_get_msgs,
    get_last_seq as _cs_last_seq,
    update_context as _cs_update_ctx,
    get_context as _cs_get_ctx,
    DEFAULT_USER_ID,
)

def _smart_truncate(text: str, max_len: int = 200) -> str:
    """按句子边界截取文本，避免半句话截断，末尾加省略号。"""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    # 从后往前找句子结束标点（。！？!?）
    for i in range(len(truncated) - 1, max_len // 2, -1):
        if truncated[i] in '。！？!?\n':
            return truncated[:i+1] + '…'
    # 没找到，退而求其次找逗号/分号
    for i in range(len(truncated) - 1, max_len // 2, -1):
        if truncated[i] in '，,；;':
            return truncated[:i+1] + '…'
    return truncated + '…'


def load_llm_config():
    """从 Java admin-service API 获取当前活跃的大模型配置"""
    try:
        req = _admin_request("/api/admin/internal/config/llm/active")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
            logger.warning("没有找到活跃的 LLM 配置")
    except Exception as e:
        logger.warning(f"从 admin-service 获取 LLM 配置失败: {e}")

    logger.warning("没有可用的服务端 LLM 配置")
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

def search_knowledge(query, top_k=5, category=None):
    try:
        body = {"query": query, "top_k": top_k}
        if category:
            body["category"] = category
        body_bytes = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{KNOWLEDGE_SERVICE_URL}/knowledge/search",
            data=body_bytes, method="POST"
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


# ── 地图标注 Skill 定义 ──
# Skill 文件放在 skill/ 目录下，以 .md 扩展名命名
# 加载策略：先从 .md 提取轻量摘要给 LLM，LLM 选择的 skill 再按需加载全文
_SKILL_DIR = os.path.join(os.path.dirname(__file__), "skill")

# 缓存：{filepath: (mtime, content)}，mtime 变化时自动重读
_skill_cache: dict = {}

def _load_skill_text(path: str) -> str:
    """加载单个 skill 定义文件，返回压缩后的纯文本。
    基于文件 mtime 缓存，仅在文件变化时重新读取。
    """
    if not os.path.exists(path):
        _skill_cache.pop(path, None)
        return ""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0

    cached = _skill_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # 去除 markdown 格式标记，保留核心内容
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped in ("", "---", "|------|------|------|------|") or stripped.startswith("```"):
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            stripped = stripped[level:].strip()
        lines.append(stripped)

    content = "\n".join(lines)
    _skill_cache[path] = (mtime, content)
    return content

def _parse_skill_summary(path: str) -> dict | None:
    """从 .md 文件中提取技能摘要：名称、描述、触发条件、输出格式模板。
    只提取必要的结构信息，不加载完整示例。
    """
    if not os.path.exists(path):
        return None

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None

    cached = _skill_cache.get(path)
    if cached and cached[0] == mtime and len(cached) > 2:
        return cached[2]  # 已缓存的摘要

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    summary = {"formats": [], "triggers": []}
    current_section = ""
    in_code_block = False
    code_lines = []

    for line in text.split("\n"):
        stripped = line.strip()

        # 跟踪代码块
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                # 收集所有 JSON 代码块（支持多种格式变体，如 polygon + circle）
                if code_lines:
                    code_str = "\n".join(code_lines)
                    if code_str not in summary["formats"]:
                        summary["formats"].append(code_str)
                code_lines = []
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # 提取技能名称（第一个 # 标题）
        if stripped.startswith("# ") and "name" not in summary:
            summary["name"] = stripped[2:].strip()

        # 提取描述（## 技能描述 下的第一段非空文本）
        if stripped == "## 技能描述":
            current_section = "description"
            continue
        if stripped.startswith("## ") and stripped != "## 技能描述":
            current_section = ""

        if current_section == "description" and stripped and not summary.get("description"):
            summary["description"] = stripped

        # 提取触发条件
        if stripped == "## 触发条件":
            current_section = "triggers"
            continue
        if current_section == "triggers" and stripped.startswith("- "):
            summary["triggers"].append(stripped[2:].strip())

    # 合并缓存（在原缓存的元组中追加 summary）
    old_cached = _skill_cache.get(path)
    if old_cached:
        _skill_cache[path] = (old_cached[0], old_cached[1], summary)

    return summary

# 地图相关关键词
_MAP_RELATED_KEYWORDS = [
    "地图", "坐标", "经纬度", "北纬", "东经", "标注", "在地图上",
    "地理", "位置", "绘制", "画出", "路线", "范围", "区域", "边界",
    "轮廓", "航线", "路径", "连线", "标点",
]

def _is_map_related(query: str) -> bool:
    """判断用户问题是否涉及地图。"""
    return any(kw in query for kw in _MAP_RELATED_KEYWORDS)

def _get_skill_catalog() -> str:
    """扫描 skill/ 目录，为每个 .md 提取摘要，生成轻量技能目录。

    只包含：技能名 + 一句话描述 + 触发条件 + JSON 格式模板。
    不含完整示例和渲染规则等冗余内容。
    """
    if not os.path.isdir(_SKILL_DIR):
        return ""

    entries = []
    try:
        for filename in sorted(os.listdir(_SKILL_DIR)):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(_SKILL_DIR, filename)
            s = _parse_skill_summary(path)
            if not s or not s.get("formats"):
                continue

            name = s.get("name", filename[:-3])
            desc = s.get("description", "")
            triggers = "、".join(s["triggers"][:3]) if s["triggers"] else ""

            entry = f"### {name}\n"
            if desc:
                entry += f"描述：{desc}\n"
            if triggers:
                entry += f"适用场景：{triggers}\n"

            # 输出所有格式变体（如 polygon + circle）
            for fmt in s["formats"]:
                entry += f"输出格式：\n```map_annotations\n{fmt}\n```\n"

            entries.append(entry)
    except OSError:
        return ""

    return "\n".join(entries)

def _build_base_prompt(query: str = "") -> str:
    """构建 system prompt。

    地图 skill 采用轻量目录模式：
    1. 只将技能摘要（名称+描述+JSON格式模板）注入 prompt
    2. 不加载完整 .md 示例和渲染规则
    3. 摘要足以让 LLM 生成正确的 map_annotations JSON
    """
    prompt = (
        "你是一个专业的智能评估系统助手，擅长作战效能评估、指标体系分析、评估分析等领域。\n"
        "请用中文回答，语言专业、准确、有条理。\n"
        "禁止使用 ###、** 等 Markdown 格式标记，标题用【】，列表用数字。\n"
        "重要：当你引用某条参考资料的内容时，必须在相关句末标注其编号，格式为 [N]（如 [1]、[2]）。"
        "一个句子可以引用多个来源，用逗号分隔，如 [1,3]。"
        "不要凭空编造编号，只引用确实使用了其内容的参考资料。\n"
    )

    # 按需注入地图 Skill 轻量目录
    if query and _is_map_related(query):
        catalog = _get_skill_catalog()
        if catalog:
            prompt += (
                "\n## 可用地图标注技能\n"
                "根据用户需求选择合适的技能，在正文末尾输出 map_annotations JSON 代码块。\n"
                "三种技能可组合使用（同一个 map_annotations 块中可同时包含 markers、routes、areas）。\n"
                "正文中正常描述地理信息，不要提到「标注代码块」或「JSON」。\n\n"
                + catalog + "\n\n"
                "通用约束：不编造坐标，不确定时在正文中说明；坐标精度到小数点后4位。"
            )

    return prompt

# ── 知识库检索跳过判断 ──
# 某些问题类型不需要知识库上下文（如地理坐标、地图可视化、纯分析等）
_SKIP_KNOWLEDGE_KEYWORDS = [
    "地图", "坐标", "经纬度", "北纬", "东经", "标注", "在地图上",
    "地理", "位置", "所在位置", "定位",
]

def _should_skip_knowledge(query: str) -> bool:
    """判断是否需要跳过知识库检索。"""
    q = query.lower()
    return any(kw in q for kw in _SKIP_KNOWLEDGE_KEYWORDS)


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

    返回：
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
        logger.warning(f"获取附件文本失败 {attachment_id}: {e}")
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
        logger.warning(f"获取附件信息失败 {attachment_id}: {e}")
        return "", ""

def call_llm_api(query, context="", attachment_text="", attachment_filename="", image_data_url="", category=None):
    api_url, api_key, model, temperature, max_tokens, messages, err = get_llm_messages(query, context, attachment_text, attachment_filename, image_data_url, category)
    if api_url is None:
        return err, [], []

    references, sources, knowledge_chunks = err

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

def get_llm_messages(query, context="", attachment_text="", attachment_filename="", image_data_url="", category=None):
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

    # ── 知识库检索（地理/坐标类问题无需检索） ──
    if _should_skip_knowledge(query):
        logger.info(f"跳过知识库检索（地理/坐标相关）: {query[:50]}")
        knowledge_chunks = []
    else:
        knowledge_chunks = search_knowledge(query, top_k=5, category=category)
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
            ref_num = i + 1
            knowledge_context += f"\n\n[参考{ref_num}] 标题: {ch.get('title', '未知')}\n内容: {ch.get('content', '')}"
            references.append(f"[{ref_num}] {ch.get('title', '未知')} (相关度: {ch.get('score', 0):.0%})")
            sources.append({
                "num": ref_num,
                "title": ch.get("title", "未知"),
                "category": ch.get("category", "知识库"),
                "score": ch.get("score", 0),
                "snippet": _smart_truncate(ch.get("content", "") or "", 200)
            })

    # ── 构建 system prompt（按需注入地图 Skill）──
    system_prompt = _build_base_prompt(query)

    if has_attachment:
        # 文档优先：文档是主要来源，知识库仅作补充
        system_prompt += f"\n\n用户上传了一份参考文档「{doc_filename}」，以下是文档全文：\n\n---\n{attachment_text}\n---"
        if knowledge_context:
            system_prompt += (
                f"\n\n此外，系统从知识库中检索到以下资料。"
                f"如果这些资料与用户的文档或问题明确相关，可以作为补充参考；"
                f"如果不相关，请忽略知识库资料，仅基于用户上传的文档内容回答问题："
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

    return api_url, api_key, model, temperature, max_tokens, messages, (references, sources, knowledge_chunks)


def stream_llm_api(query, context="", attachment_text="", attachment_filename="", image_data_url="", category=None) -> Generator[str, None, tuple]:
    """流式调用 LLM API，逐块 yield 文本，最后 return (完整文本, references, sources)"""
    api_url, api_key, model, temperature, max_tokens, messages, refs_src = get_llm_messages(query, context, attachment_text, attachment_filename, image_data_url, category)
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
    category: Optional[str] = None  # 知识库分类筛选，不传则全库搜索
    attachment_id: Optional[str] = None
    image_id: Optional[str] = None
    # B 阶段数据联动：指定参考的本体模型ID，空则合并全部归档本体
    ontology_id: Optional[str] = None
    # 临时会话：不持久化，不创建 session/message/history（供 indicator 等内部服务调用）
    no_persist: bool = False

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

logger.info(f"问答服务已启动: 聊天数据通过 admin-service MySQL 持久化, 上下文轮数={MAX_CONTEXT}")

@app.get("/")
async def root():
    return {"service": "qa-service", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health_check():
    from agents.skill_catalog import get_catalog_diagnostics

    diagnostics = get_catalog_diagnostics()
    if not diagnostics["ready"]:
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "skillCatalog": diagnostics},
        )
    return {"status": "healthy", "skillCatalog": diagnostics}

# ========== 会话管理 API（MySQL 持久化）==========

@app.get("/qa/sessions")
async def list_sessions():
    """返回所有会话列表（从 MySQL 读取）"""
    resp = _cs_list("qa")
    if not resp.get("success"):
        return {"success": True, "sessions": []}
    items = resp.get("items", [])
    result = []
    for item in items:
        # 过滤掉没有标题的空会话（点击新建但未发消息）
        title = item.get("title", "") or ""
        if not title.strip():
            continue
        # 截断长标题
        if len(title) > 20:
            title = title[:20] + '...'
        ct = item.get("createTime", "") or item.get("updateTime", "")
        if "T" in ct:
            ct = ct.replace("T", " ")[:19]
        result.append({
            "id": item.get("sessionId", ""),
            "title": title,
            "time": ct,
            "last_active": ct
        })
    return {"success": True, "sessions": result}

@app.post("/qa/session/new")
async def new_session():
    """返回一个新会话 ID，不创建数据库记录；真正发消息时由 chat/stream 创建"""
    new_id = str(uuid.uuid4()).replace("-", "")[:32]
    return {"success": True, "session_id": new_id}

@app.delete("/qa/session/{session_id}")
async def delete_session(session_id: str):
    """删除整个会话"""
    resp = _cs_delete(session_id)
    if resp.get("success"):
        logger.info(f"会话已删除: {session_id}")
        return {"success": True}
    raise HTTPException(status_code=404, detail="会话不存在")

# ========== 对话 API（MySQL 持久化）==========

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
        logger.exception(f"附件上传失败: {e}")
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
    session_id = request.session_id or str(uuid.uuid4()).replace("-", "")[:32]
    ephemeral = request.no_persist

    # 临时会话（no_persist=True）：不创建 session、不构建上下文、不保存消息
    if not ephemeral:
        _cs_create(session_id, "qa")
        context = _build_qa_context(session_id)
    else:
        context = ""

    attachment_text, attachment_filename = _get_attachment_info(request.attachment_id)

    # ── 图片处理 ──
    image_data_url = ""
    if request.image_id:
        if not _model_supports_images():
            raise HTTPException(status_code=400, detail="当前模型不支持图片识别，请切换至支持多模态的大模型（如 deepseek-chat、gpt-4o 等）")
        image_data_url, _ = _load_image_base64(request.image_id)
        if not image_data_url:
            raise HTTPException(status_code=400, detail="图片不存在或已过期")

    answer, references, sources = call_llm_api(request.query, context, attachment_text, attachment_filename, image_data_url, request.category)

    # 保存消息到 MySQL（临时会话跳过）
    if not ephemeral:
        _save_qa_messages(session_id, request.query, answer, references, sources)

    return ChatResponse(
        answer=answer,
        references=references,
        session_id=session_id,
        sources=sources
    )


def _build_qa_context(session_id: str) -> str:
    """从 MySQL 获取最近消息并构建上下文字符串"""
    resp = _cs_get_msgs(session_id, MAX_CONTEXT * 2)
    if not resp.get("success"):
        return ""
    msgs = resp.get("data", [])
    context = ""
    for msg in msgs:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            context += f"用户: {content}\n"
        elif role == "assistant":
            context += f"助手: {content}\n"
    return context


def _save_qa_messages(session_id: str, query: str, answer: str,
                      references: list, sources: list) -> None:
    """保存用户问题和助手回答到 MySQL"""
    last_seq = _cs_last_seq(session_id)
    title = ""
    if last_seq == -1:
        title = query[:30] if len(query) > 30 else query
    seq_user = last_seq + 1
    seq_asst = last_seq + 2

    import json as _json
    meta_user = _json.dumps({"attachment": ""}, ensure_ascii=False)
    meta_asst = _json.dumps({
        "references": references,
        "sources": sources,
    }, ensure_ascii=False)

    _cs_add_msg(session_id, "user", query, seq_user, meta_user)
    _cs_add_msg(session_id, "assistant", answer, seq_asst, meta_asst)

    # 通过 update_session 显式设置标题（不依赖 addMessage 的 title 参数）
    if title:
        _cs_update(session_id, title=title, summary=title[:200])

    # 更新 LLM 上下文到 MySQL
    context_text = f"用户: {query}\n助手: {answer[:300]}\n"
    msg_range = f"seq:{seq_user}-{seq_asst}"
    _cs_update_ctx(session_id, context_text, msg_range)

# ========== 流式对话 API ==========

@app.post("/qa/chat/stream")
async def chat_stream(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4()).replace("-", "")[:32]
    ephemeral = request.no_persist

    # 临时会话（no_persist=True）：不创建 session、不构建上下文、不保存消息
    if not ephemeral:
        _cs_create(session_id, "qa")
        context = _build_qa_context(session_id)
    else:
        context = ""

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

    _, __, ___, ____, _____, ______, refs_src = get_llm_messages(request.query, context, attachment_text, attachment_filename, image_data_url, request.category)
    if refs_src is None:
        refs_src = ([], [], [])
    references_pre, sources_pre, knowledge_chunks = refs_src

    def generate():
        full_answer = ""
        gen = stream_llm_api(request.query, context, attachment_text, attachment_filename, image_data_url, request.category)
        try:
            for chunk in gen:
                full_answer += chunk
                yield json.dumps({"type": "text", "content": chunk}, ensure_ascii=False) + "\n"
            # 引用信息
            knowledge_used = len(sources_pre) > 0
            cited_answer = full_answer
            yield json.dumps({
                "type": "done",
                "session_id": session_id,
                "references": references_pre,
                "sources": sources_pre,
                "knowledge_used": knowledge_used,
                "cited_answer": cited_answer
            }, ensure_ascii=False, default=str) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "content": str(e)[:500]}, ensure_ascii=False) + "\n"

        # 保存消息到 MySQL（临时会话跳过）
        if not ephemeral:
            _save_qa_messages(session_id, request.query, full_answer, references_pre, sources_pre)

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

# ========== 历史记录 API（MySQL 持久化）==========

_MAP_ANNOTATIONS_PATTERN = re.compile(r'```map_annotations\s*\n([\s\S]*?)```', re.MULTILINE)

def _parse_map_annotations_from_text(text: str) -> dict:
    """从文本中提取 map_annotations JSON 并转换为前端期望的 geoData 格式"""
    m = _MAP_ANNOTATIONS_PATTERN.search(text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except Exception:
        return {}
    geo = {}
    # markers → geoPoints
    if data.get("markers"):
        geo["geoPoints"] = [{"name": p.get("name",""), "lng": p["lng"], "lat": p["lat"]} for p in data["markers"] if "lng" in p and "lat" in p]
    # routes
    if data.get("routes"):
        geo["routes"] = []
        for r in data["routes"]:
            points = [{"name": f"{r['name']}·节点{i+1}", "lng": p["lng"], "lat": p["lat"]} for i, p in enumerate(r.get("points", [])) if "lng" in p and "lat" in p]
            if len(points) >= 2:
                geo["routes"].append({"name": r.get("name",""), "points": points})
    # areas
    if data.get("areas"):
        polys = []
        circles = []
        for a in data["areas"]:
            if a.get("shape") == "circle" and a.get("center"):
                circles.append({"name": a.get("name",""), "center": a["center"], "radiusKm": a.get("radiusKm", 10)})
            elif a.get("points"):
                pts = [{"name": "", "lng": p["lng"], "lat": p["lat"]} for p in a["points"] if "lng" in p and "lat" in p]
                if len(pts) >= 3:
                    polys.append({"name": a.get("name",""), "points": pts})
        if polys:
            geo["areas"] = polys
        if circles:
            geo["circles"] = circles
    if geo:
        geo["showMap"] = True
    return geo

def _enrich_message(msg: dict) -> dict:
    """从 MySQL 消息中提取 metadata JSON 并合并到返回结果中"""
    result = {
        "role": msg.get("role", ""),
        "content": msg.get("content", ""),
        "timestamp": msg.get("createTime", ""),
    }
    meta = msg.get("metadata")
    if meta and isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
            if isinstance(parsed, dict):
                result.update(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
    # 确保必填字段存在
    result.setdefault("references", [])
    result.setdefault("sources", [])
    result.setdefault("showMap", False)
    # 从 content 中剥离 map_annotations JSON 块并提取地图数据
    if _MAP_ANNOTATIONS_PATTERN.search(result["content"]):
        geo_data = _parse_map_annotations_from_text(result["content"])
        result["content"] = _MAP_ANNOTATIONS_PATTERN.sub("", result["content"]).strip()
        if geo_data:
            result.update(geo_data)
    return result

@app.get("/qa/history")
async def get_history(session_id: str):
    """获取指定会话的所有消息（从 MySQL 读取）"""
    resp = _cs_get_msgs(session_id)
    if not resp.get("success"):
        return {"messages": []}
    msgs = resp.get("data", [])
    return {"messages": [_enrich_message(msg) for msg in msgs]}

@app.get("/qa/history/list")
async def list_history():
    """返回所有历史记录（从 MySQL 读取）"""
    resp = _cs_list("qa")
    if not resp.get("success"):
        return {"items": []}
    items = resp.get("items", [])
    result = []
    for item in items[-20:]:
        # 过滤掉没有标题的空会话
        title = item.get("title", "") or ""
        if not title.strip():
            continue
        if len(title) > 20:
            title = title[:20] + '...'
        ct = item.get("createTime", "") or item.get("updateTime", "")
        if "T" in ct:
            ct = ct.replace("T", " ")[:19]
        result.append({
            "id": item.get("sessionId", ""),
            "title": title,
            "time": ct
        })
    return {"items": result}

@app.delete("/qa/history/{session_id}")
async def clear_history(session_id: str):
    """删除整个会话（级联删除消息）"""
    resp = _cs_delete(session_id)
    if resp.get("success"):
        return {"message": "已删除"}
    raise HTTPException(status_code=404, detail="会话不存在")

# ========== LLM 配置 API ==========
# 现在从 Java admin-service 获取 MySQL 中持久化的配置

@app.get("/config/llm")
async def get_llm_config():
    """获取当前活跃的大模型配置"""
    try:
        req = _admin_request("/api/admin/config/llm/active")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"获取 LLM 配置失败: {e}")
        return {"success": False, "message": "无法连接到管理服务", "data": load_llm_config()}

@app.get("/config/llm/list")
async def list_llm_configs():
    """列出所有大模型配置"""
    try:
        req = _admin_request("/api/admin/config/llm/list")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"获取失败: {str(e)}"}

@app.post("/config/llm")
async def save_llm_config_endpoint(config: LlmConfigRequest):
    """保存新的大模型配置"""
    try:
        body = json.dumps(config.dict()).encode("utf-8")
        req = _admin_request("/api/admin/config/llm", data=body, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"保存失败: {str(e)}"}

@app.put("/config/llm/{config_id}/activate")
async def activate_llm_config(config_id: str):
    """激活指定的大模型配置"""
    try:
        req = _admin_request(f"/api/admin/config/llm/{config_id}/activate", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"切换失败: {str(e)}"}

@app.delete("/config/llm/{config_id}")
async def delete_llm_config(config_id: str):
    """删除大模型配置"""
    try:
        req = _admin_request(f"/api/admin/config/llm/{config_id}", method="DELETE")
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
    logger.info("评估分析和托管 Skill 路由已注册")
except Exception as e:
    logger.warning(f"注册评估分析路由失败: {e}")

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
        logger.warning(f"LLM 查询分类失败: {e}")

    # ── 第三层：LLM 失败 → 关键词兜底 ──
    if kw_concept:
        return {"classification": "concept_qa"}
    if kw_analysis:
        return {"classification": "indicator_analysis"}
    return {"classification": "indicator_analysis"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10253, log_config=None)
