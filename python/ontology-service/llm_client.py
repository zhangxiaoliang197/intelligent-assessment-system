"""LLM 客户端封装。

复用 qa-service 的 LLM 配置加载模式（从 admin-service 获取活跃配置）和调用模式
（urllib + OpenAI 兼容协议），但不耦合 qa-service 的知识库检索、附件处理等业务逻辑。

核心能力：
- load_llm_config: 从 admin-service 获取 LLM 配置
- call_llm: 同步调用 LLM，返回纯文本
- call_llm_json: 调用 LLM 并解析为 JSON，带容错和重试
"""
import json
import os
import re
import ssl
import urllib.request
import urllib.error
import logging
import os
import urllib.parse

logger = logging.getLogger("ontology-service")

# admin-service 地址（与 qa-service 共用同一配置源）
ADMIN_SERVICE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()

# LLM 请求超时（秒）。reasoning 模型思考链长、输出大时读取耗时长，
# 120s 不足容易触发 SSL 连接中断（UNEXPECTED_EOF_WHILE_READING），默认 300s。
# 可通过环境变量 LLM_TIMEOUT 覆盖。
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))


def load_llm_config() -> dict:
    """从 Java admin-service 获取当前活跃的大模型配置。

    通过仅服务间可访问的活跃配置端点读取；失败返回无密钥默认值，
    由调用方明确报错，避免从公开列表接口暴露凭据。

    Returns:
        包含 type/apiUrl/apiKey/model/temperature/maxTokens 的配置字典
    """
    # 优先取活跃配置
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/internal/config/llm/active",
            method="GET"
        )
        req.add_header("Content-Type", "application/json")
        if INTERNAL_SERVICE_TOKEN:
            req.add_header("X-Service-Token", INTERNAL_SERVICE_TOKEN)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        logger.warning(f"从 admin-service 获取活跃 LLM 配置失败: {e}")

    logger.warning("没有可用的服务端 LLM 配置")
    return {
        "type": "deepseek",
        "apiUrl": "https://api.deepseek.com/v1",
        "apiKey": "",
        "model": "deepseek-chat",
        "temperature": 0.3,
        "maxTokens": 4000,
        "topP": 0.9
    }


def call_llm(messages: list, temperature: float = 0.3, max_tokens: int = 4000,
             thinking_type: str = "") -> str:
    """同步调用 LLM，返回纯文本响应。

    Args:
        messages: OpenAI 格式的消息列表 [{"role":"system","content":"..."},{"role":"user","content":"..."}]
        temperature: 温度参数，结构化输出建议 0.3
        max_tokens: 最大输出 token 数
        thinking_type: 推理开关，"enabled"/"disabled"；空字符串表示不注入、保持模型默认

    Returns:
        LLM 返回的文本内容

    Raises:
        RuntimeError: LLM 调用失败或配置缺失
    """
    config = load_llm_config()
    llm_type = config.get("type", "deepseek")
    api_key = config.get("apiKey", "")
    api_url = config.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = config.get("model", "deepseek-chat")

    parsed_url = urllib.parse.urlparse(api_url)
    if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname:
        raise RuntimeError("大模型 API 地址无效")
    allow_insecure_http = os.getenv("LLM_ALLOW_INSECURE_HTTP", "false").lower() in {
        "1", "true", "yes", "on",
    }
    if parsed_url.scheme != "https" and not (
        allow_insecure_http and parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError("大模型 API 必须使用 HTTPS；本地 HTTP 需显式开启 LLM_ALLOW_INSECURE_HTTP")

    # vLLM 本地部署无需 API Key
    if not api_key and llm_type != "vllm":
        raise RuntimeError("大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置")

    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    # 仅当显式指定 enabled/disabled 时注入 thinking 字段，否则保持模型默认行为
    if thinking_type in ("enabled", "disabled"):
        body_dict["thinking"] = {"type": thinking_type}
    body = json.dumps(body_dict).encode("utf-8")

    url = f"{api_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ca_file = os.getenv("LLM_CA_FILE", "").strip() or None
    ssl_ctx = ssl.create_default_context(cafile=ca_file)

    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            # DeepSeek 偶发返回 content 为 null，统一转为空字符串处理
            if content is None:
                content = ""

            # reasoning 模型（deepseek-v4-flash / deepseek-reasoner）会优先消耗 token 做思考链
            # （reasoning_content），当 max_tokens 不足时 reasoning 耗尽上限，content 被截断为空
            # 且 finish_reason=length。此种情况下重试必然失败（配置不变），直接抛错避免
            # call_llm_json 无意义重试 4 次，并记录 reasoning_tokens 便于诊断。
            if not content.strip() and finish_reason == "length":
                usage = data.get("usage", {}) or {}
                comp_detail = usage.get("completion_tokens_details", {}) or {}
                reasoning_tokens = comp_detail.get("reasoning_tokens", "未知")
                comp_tokens = usage.get("completion_tokens", "未知")
                raise RuntimeError(
                    f"大模型思考链耗尽 max_tokens 上限（reasoning_tokens={reasoning_tokens}, "
                    f"completion_tokens={comp_tokens}, max_tokens={max_tokens}），未输出正式内容。"
                    f"请增大 LLM_MAX_TOKENS 或换用非 reasoning 模型（如 deepseek-chat）。"
                )
            return content
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err = json.loads(err_body)
            msg = err.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise RuntimeError(f"大模型调用失败 (HTTP {e.code}): {msg[:500]}")
    except Exception as e:
        # 本函数内主动抛出的 RuntimeError（如 reasoning 耗尽 max_tokens）原样向上抛，
        # 不被重新包装或截断，保证 call_llm_json 能拿到原始错误信息并跳过无意义重试
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"大模型调用失败: {str(e)[:500]}")


def _extract_json_block(text: str):
    """从可能包含 markdown 代码块或多余文本的响应中提取 JSON。

    尝试顺序：
    1. 直接 json.loads（理想情况）
    2. 提取 ```json ... ``` 代码块
    3. 提取 ``` ... ``` 代码块
    4. 用正则找最外层的 { } 或 [ ]

    Returns:
        解析后的 dict 或 list

    Raises:
        json.JSONDecodeError: 无法解析
    """
    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 ```json 代码块
    m = re.search(r'```json\s*\n(.*?)```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. 提取任意 ``` 代码块
    m = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 4. 正则找最外层 { } 或 [ ]
    for pattern in [r'\{.*\}', r'\[.*\]']:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("无法从 LLM 响应中提取 JSON", text, 0)


def call_llm_json(messages: list, temperature: float = 0.3, max_tokens: int = 4000,
                  thinking_type: str = ""):
    """调用 LLM 并解析为 JSON 结构。

    带容错和重试机制（最多 4 次尝试）：
    - 空响应：第一次追加"请返回 JSON"纠错提示重试，避免重复发相同 prompt 仍为空
    - 非空但解析失败，第一次追加"请只返回 JSON"提示重试，后续直接重试原请求
    - 仍失败抛 ValueError

    Args:
        messages: OpenAI 格式的消息列表
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        thinking_type: 推理开关，"enabled"/"disabled"；空字符串表示不注入、保持模型默认

    Returns:
        解析后的 dict 或 list

    Raises:
        ValueError: 多次尝试仍无法解析为 JSON
    """
    raw = ""
    correction_used = False
    # 统一重试循环：空响应与解析失败都追加一次纠错提示，避免反复发相同 prompt
    for attempt in range(4):
        try:
            current_msgs = messages
            if correction_used:
                if raw and raw.strip():
                    # 非空但解析失败：附上上一次回复，要求修正格式
                    current_msgs = list(messages) + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": "你上一次的回复无法被解析为 JSON。请仔细检查格式，只返回纯 JSON，不要包含任何 markdown 标记、解释文字或代码块标记。确保 JSON 语法完全正确。"}
                    ]
                else:
                    # 空响应：不附带空 assistant 消息，直接追加提示
                    current_msgs = list(messages) + [
                        {"role": "user", "content": "你上一次没有返回任何内容。请直接返回符合要求的 JSON，不要输出空白或空内容。"}
                    ]
            raw = call_llm(current_msgs, temperature, max_tokens, thinking_type)
        except RuntimeError as e:
            raise ValueError(str(e))

        # 空响应：追加一次纠错提示后重试
        if not raw or not raw.strip():
            logger.warning(f"LLM 返回空内容（第 {attempt + 1} 次），将追加纠错提示重试")
            raw = ""
            if not correction_used:
                correction_used = True  # 空响应也追加纠错，避免重复发相同 prompt
            continue

        try:
            return _extract_json_block(raw)
        except json.JSONDecodeError:
            logger.warning(f"LLM 返回内容无法直接解析为 JSON（第 {attempt + 1} 次）。原始内容前 200 字: {raw[:200]}")
            if not correction_used:
                correction_used = True  # 仅第一次追加纠错提示

    raise ValueError(
        f"大模型多次调用均无法返回有效 JSON（已尝试 {attempt + 1} 次）。"
        f"最后响应前 200 字: {raw[:200] if raw else '(空响应)'}"
    )
