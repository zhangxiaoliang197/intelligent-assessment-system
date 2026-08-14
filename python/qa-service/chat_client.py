"""
聊天会话 HTTP 客户端（供 qa-service 使用）。
通过 admin-service 的 /api/admin/chat 接口读写聊天数据，
替代原来的 sessions.json / history.json 文件持久化。
"""
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("chat-client")

ADMIN_SERVICE_URL = "http://localhost:10258"
DEFAULT_USER_ID = "default-user"

# 允许模块加载后通过 qa-service 主模块的设置覆盖默认值
try:
    import os as _os
    ADMIN_SERVICE_URL = _os.getenv("ADMIN_SERVICE_URL", ADMIN_SERVICE_URL)
except Exception:
    pass

INTERNAL_SERVICE_TOKEN = ""
try:
    import os as _os
    INTERNAL_SERVICE_TOKEN = _os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
except Exception:
    pass


def _http(method: str, path: str, body: dict = None, timeout: int = 10) -> dict:
    """调用 admin-service。返回解析后的 JSON dict。"""
    url = f"{ADMIN_SERVICE_URL}{path}"
    data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method)
    req.add_header("Content-Type", "application/json")
    if INTERNAL_SERVICE_TOKEN:
        req.add_header("X-Service-Token", INTERNAL_SERVICE_TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        logger.warning("chat admin %s %s HTTP %s: %s", method, url, e.code, msg[:200])
        return {"success": False, "message": f"HTTP {e.code}: {msg[:200]}"}
    except Exception as e:
        logger.warning("chat admin %s %s 失败: %s", method, url, e)
        return {"success": False, "message": str(e)[:200]}


# ==================== 会话 ====================

def create_session(session_id: str, session_type: str, title: str = "", stage: str = "",
                   user_id: str = DEFAULT_USER_ID) -> dict:
    """创建或获取已有会话。返回 {"success": True, "data": {...}}。"""
    return _http("POST", "/api/admin/chat/sessions", {
        "id": session_id,
        "userId": user_id,
        "type": session_type,
        "title": title,
        "stage": stage,
    })


def get_session(session_id: str) -> dict:
    """获取会话详情（含消息列表）。返回 {"success": True, "data": {..., "messages": [...]}}。"""
    return _http("GET", f"/api/admin/chat/sessions/{session_id}")


def update_session(session_id: str, **kwargs) -> dict:
    """字段级更新会话。kwargs: title, stage, messageCount, summary。"""
    return _http("PUT", f"/api/admin/chat/sessions/{session_id}", kwargs)


def delete_session(session_id: str) -> dict:
    """删除会话（级联删除消息、上下文、历史索引）。"""
    return _http("DELETE", f"/api/admin/chat/sessions/{session_id}")


def list_sessions(session_type: str, user_id: str = DEFAULT_USER_ID,
                  page: int = 1, size: int = 50) -> dict:
    """列出会话列表。返回 {"success": True, "items": [...]}。"""
    return _http("GET", f"/api/admin/chat/sessions?userId={user_id}&type={session_type}&page={page}&size={size}")


# ==================== 消息 ====================

def add_message(session_id: str, role: str, content: str, sequence_num: int,
                metadata: str = "", title: str = "", summary: str = "") -> dict:
    """追加一条消息。返回 {"success": True, "data": {...}}。"""
    body = {
        "role": role,
        "content": content,
        "sequenceNum": sequence_num,
        "metadata": metadata,
    }
    if title:
        body["title"] = title
    if summary:
        body["summary"] = summary
    return _http("POST", f"/api/admin/chat/sessions/{session_id}/messages", body)


def get_messages(session_id: str, limit: int = None) -> dict:
    """获取消息列表（支持 limit 用于上下文窗口）。返回 {"success": True, "data": [...]}。"""
    path = f"/api/admin/chat/sessions/{session_id}/messages"
    if limit is not None and limit > 0:
        path += f"?limit={limit}"
    return _http("GET", path)


def get_last_seq(session_id: str) -> int:
    """获取最后一条消息的 sequence_num。新会话返回 -1。"""
    resp = _http("GET", f"/api/admin/chat/sessions/{session_id}/messages/last-seq")
    if resp.get("success") and resp.get("data"):
        return resp["data"].get("sequenceNum", -1)
    return -1


# ==================== 上下文 ====================

def get_context(session_id: str, context_type: str = "full") -> dict:
    """获取 LLM 上下文。返回 {"success": True, "data": {"content": "...", ...}}。"""
    return _http("GET", f"/api/admin/chat/sessions/{session_id}/context?contextType={context_type}")


def update_context(session_id: str, content: str, message_range: str = "",
                   token_estimate: int = None, context_type: str = "full") -> dict:
    """更新 LLM 上下文。"""
    body = {
        "contextType": context_type,
        "content": content,
    }
    if message_range:
        body["messageRange"] = message_range
    if token_estimate is not None:
        body["tokenEstimate"] = token_estimate
    return _http("PUT", f"/api/admin/chat/sessions/{session_id}/context", body)
