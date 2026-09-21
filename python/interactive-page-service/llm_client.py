"""LLM 客户端封装（ipage-service 独立实现，不依赖 situation/qa 服务）。

- load_llm_config: 从 admin-service 内部接口获取活跃 LLM 配置（凭据不下发浏览器）
- call_llm: 同步调用，返回纯文本
- call_llm_json: 调用并解析 JSON，带容错重试
- call_llm_with_tools: 原生 function-calling（OpenAI tools 协议）
"""
import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

import config

logger = logging.getLogger("ipage-service")

ADMIN_SERVICE_URL = config.ADMIN_SERVICE_URL


class LLMTruncatedText(str):
    """被 max_tokens 截断的 LLM 响应文本。

    继承 str，所有字符串用法保持不变；上层可用
    `isinstance(raw, LLMTruncatedText)` 判定本次输出是否「内容非空但被截断」
    （finish_reason=length），从而给出可读的中文原因，而不是静默当成正常结果。
    """


def load_llm_config() -> dict:
    """从 admin-service 获取当前活跃的大模型配置。

    Returns:
        包含 type/apiUrl/apiKey/model/temperature/maxTokens 的配置字典；
        获取失败返回无密钥默认值（调用方据此走确定性降级）。
    """
    try:
        req = urllib.request.Request(
            f"{ADMIN_SERVICE_URL}/api/admin/internal/config/llm/active",
            method="GET",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Service-Token", config.INTERNAL_SERVICE_TOKEN)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("success") and data.get("data"):
                return data["data"]
    except Exception as e:
        logger.warning("从 admin-service 获取活跃 LLM 配置失败: %s", e)

    logger.warning("没有可用的服务端 LLM 配置")
    return {
        "type": "deepseek",
        "apiUrl": "https://api.deepseek.com/v1",
        "apiKey": "",
        "model": "deepseek-chat",
        "temperature": 0.3,
        "maxTokens": 4000,
        "topP": 0.9,
    }


def _validate_endpoint(api_url: str) -> None:
    """校验 LLM API 地址：协议合法、主机在白名单、非本地 HTTP 需显式授权。"""
    parsed_url = urllib.parse.urlparse(api_url)
    if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname:
        raise RuntimeError("大模型 API 地址无效")
    hostname = parsed_url.hostname.lower()
    if hostname not in config.LLM_ALLOWED_HOSTS:
        raise RuntimeError(
            f"大模型 API 主机不在允许清单中: {hostname}；"
            "请通过 IPAGE_LLM_ALLOWED_HOSTS 由部署管理员显式授权"
        )
    allow_insecure_http = os.getenv("LLM_ALLOW_INSECURE_HTTP", "false").lower() in {
        "1", "true", "yes", "on",
    }
    if parsed_url.scheme != "https" and not (
        allow_insecure_http and hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError("大模型 API 必须使用 HTTPS；本地 HTTP 需显式开启 LLM_ALLOW_INSECURE_HTTP")


def _ssl_context() -> ssl.SSLContext:
    """构造 SSL 上下文；内网自签证书通过 LLM_CA_FILE 注入专用 CA。"""
    ca_file = os.getenv("LLM_CA_FILE", "").strip() or None
    return ssl.create_default_context(cafile=ca_file)


def call_llm(messages: list, temperature: float = 0.3, max_tokens: int = 4000,
             thinking_type: str = "") -> str:
    """同步调用 LLM，返回纯文本响应。

    Args:
        messages: OpenAI 格式消息列表
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        thinking_type: 推理开关，"enabled"/"disabled"，空串保持模型默认

    Returns:
        LLM 文本内容

    Raises:
        RuntimeError: 调用失败、配置缺失或思考链耗尽 token
    """
    llm_cfg = load_llm_config()
    llm_type = llm_cfg.get("type", "deepseek")
    api_key = llm_cfg.get("apiKey", "")
    api_url = llm_cfg.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = llm_cfg.get("model", "deepseek-chat")

    _validate_endpoint(api_url)
    if not api_key and llm_type != "vllm":
        raise RuntimeError("大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置")

    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if thinking_type in ("enabled", "disabled"):
        body_dict["thinking"] = {"type": thinking_type}
    body = json.dumps(body_dict).encode("utf-8")

    req = urllib.request.Request(f"{api_url}/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=180, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            if content is None:
                content = ""
            if not content.strip() and finish_reason == "length":
                usage = data.get("usage", {}) or {}
                raise RuntimeError(
                    f"大模型思考链耗尽 max_tokens 上限"
                    f"（completion_tokens={usage.get('completion_tokens', '未知')}，"
                    f"max_tokens={max_tokens}），未输出正式内容。"
                    "请增大 IPAGE_PAGE_MAX_TOKENS 或换用非 reasoning 模型（如 deepseek-chat）。"
                )
            if finish_reason == "length":
                # 内容非空但被截断：绝不能静默当正常结果（整页 HTML 会被拦腰截断，
                # 上层表现为莫名其妙的回退且无任何日志线索）
                usage = data.get("usage", {}) or {}
                logger.warning(
                    "输出被 max_tokens 截断：model=%s completion_tokens=%s max_tokens=%s "
                    "content_chars=%s（内容不完整）",
                    model, usage.get("completion_tokens", "未知"), max_tokens, len(content),
                )
                return LLMTruncatedText(content)
            return content
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            msg = json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise RuntimeError(f"大模型调用失败 (HTTP {e.code}): {msg[:500]}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"大模型调用失败: {str(e)[:500]}")


def _extract_json_block(text: str):
    """从可能含 markdown 代码块或多余文本的响应中提取 JSON。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for pattern in [r'```json\s*\n(.*?)```', r'```\s*\n(.*?)```']:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass

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
    """调用 LLM 并解析为 JSON（最多 4 次尝试，首次失败追加纠错提示）。"""
    raw = ""
    correction_used = False
    for attempt in range(4):
        try:
            current_msgs = messages
            if correction_used:
                if raw and raw.strip():
                    current_msgs = list(messages) + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content":
                            "你上一次的回复无法被解析为 JSON。请只返回纯 JSON，"
                            "不要包含 markdown 标记、解释文字或代码块。确保 JSON 语法完全正确。"},
                    ]
                else:
                    current_msgs = list(messages) + [
                        {"role": "user", "content":
                            "你上一次没有返回任何内容。请直接返回符合要求的 JSON。"},
                    ]
            raw = call_llm(current_msgs, temperature, max_tokens, thinking_type)
        except RuntimeError as e:
            raise ValueError(str(e))

        if not raw or not raw.strip():
            logger.warning("LLM 返回空内容（第 %s 次），将追加纠错提示重试", attempt + 1)
            raw = ""
            correction_used = True
            continue

        try:
            return _extract_json_block(raw)
        except json.JSONDecodeError:
            logger.warning("LLM 返回内容无法解析为 JSON（第 %s 次），前 200 字: %s",
                           attempt + 1, raw[:200])
            correction_used = True

    raise ValueError(
        f"大模型多次调用均无法返回有效 JSON（已尝试 {attempt + 1} 次）。"
    )


def call_llm_with_tools(messages: list, tools: list, tool_choice=None,
                        temperature: float = 0.3, max_tokens: int = 4000,
                        thinking_type: str = "") -> dict:
    """调用 LLM 并返回原生 function-calling 结果（OpenAI tools 协议）。

    Returns:
        {"content": str, "tool_calls": [{"id","name","arguments":dict|None}],
         "finish_reason": str, "raw_usage": dict}
    """
    llm_cfg = load_llm_config()
    llm_type = llm_cfg.get("type", "deepseek")
    api_key = llm_cfg.get("apiKey", "")
    api_url = llm_cfg.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = llm_cfg.get("model", "deepseek-chat")

    _validate_endpoint(api_url)
    if not api_key and llm_type != "vllm":
        raise RuntimeError("大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置")

    body_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "tools": tools,
    }
    if tool_choice is not None:
        body_dict["tool_choice"] = tool_choice
    if thinking_type in ("enabled", "disabled"):
        body_dict["thinking"] = {"type": thinking_type}

    url = f"{api_url}/chat/completions"

    def _do_request(payload: dict):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", f"Bearer {api_key}")
        return urllib.request.urlopen(request, timeout=180, context=_ssl_context())

    try:
        with _do_request(body_dict) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            msg = json.loads(err_body).get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        # 部分推理模型不允许 tool_choice 指定具体 function，降级为 auto 重试一次
        if isinstance(tool_choice, dict) and (
            "tool_choice" in msg.lower() or "thinking" in msg.lower()
        ):
            logger.warning("tool_choice 指定 function 被拒，降级为 auto 重试: %s", msg[:200])
            body_dict.pop("tool_choice", None)
            try:
                with _do_request(body_dict) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as exc2:
                raise RuntimeError(f"大模型调用失败 (auto 重试): {str(exc2)[:500]}") from exc2
        else:
            raise RuntimeError(f"大模型调用失败 (HTTP {e.code}): {msg[:500]}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"大模型调用失败: {str(e)[:500]}")

    choice = data["choices"][0]
    message = choice.get("message", {}) or {}
    content = message.get("content") or ""
    raw_tool_calls = message.get("tool_calls") or []

    parsed_tool_calls = []
    for tc in raw_tool_calls:
        if not isinstance(tc, dict):
            continue
        function = tc.get("function", {}) or {}
        name = function.get("name", "")
        raw_args = function.get("arguments", "")
        try:
            if isinstance(raw_args, str):
                args = json.loads(raw_args) if raw_args.strip() else {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
        except json.JSONDecodeError:
            args = None
        parsed_tool_calls.append({
            "id": tc.get("id", ""),
            "name": name,
            "arguments": args,
        })

    if not parsed_tool_calls:
        raise RuntimeError(
            f"大模型未返回 tool_calls（finish_reason={choice.get('finish_reason')}）。"
            f"原始 content 前 200 字: {content[:200]}"
        )

    return {
        "content": content,
        "tool_calls": parsed_tool_calls,
        "finish_reason": choice.get("finish_reason"),
        "raw_usage": data.get("usage", {}) or {},
    }
