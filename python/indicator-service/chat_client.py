"""
聊天会话 HTTP 客户端（供 indicator-service 使用）。
通过 admin-service 的 /api/admin/chat 接口读写聊天数据，
替代原来的 sessions.json 文件持久化。
"""
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("chat-client")

ADMIN_SERVICE_URL = "http://localhost:10258"
DEFAULT_USER_ID = "default-user"

try:
    import os as _os
    ADMIN_SERVICE_URL = _os.getenv("ADMIN_SERVICE_URL", ADMIN_SERVICE_URL)
except Exception:
    pass


def _http(method: str, path: str, body: dict = None, timeout: int = 10) -> dict:
    url = f"{ADMIN_SERVICE_URL}{path}"
    data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data_bytes, method=method)
    req.add_header("Content-Type", "application/json")
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


def create_session(session_id: str, title: str = "", stage: str = "analyzing",
                   user_id: str = DEFAULT_USER_ID) -> dict:
    return _http("POST", "/api/admin/chat/sessions", {
        "id": session_id,
        "userId": user_id,
        "type": "indicator",
        "title": title,
        "stage": stage,
    })


def get_session(session_id: str) -> dict:
    return _http("GET", f"/api/admin/chat/sessions/{session_id}")


def update_session(session_id: str, **kwargs) -> dict:
    return _http("PUT", f"/api/admin/chat/sessions/{session_id}", kwargs)


def delete_session(session_id: str) -> dict:
    return _http("DELETE", f"/api/admin/chat/sessions/{session_id}")


def list_sessions(user_id: str = DEFAULT_USER_ID, page: int = 1, size: int = 50) -> dict:
    return _http("GET", f"/api/admin/chat/sessions?userId={user_id}&type=indicator&page={page}&size={size}")


def add_message(session_id: str, role: str, content: str, sequence_num: int,
                metadata: str = "", title: str = "") -> dict:
    body = {
        "role": role,
        "content": content,
        "sequenceNum": sequence_num,
        "metadata": metadata,
    }
    if title:
        body["title"] = title
    return _http("POST", f"/api/admin/chat/sessions/{session_id}/messages", body)


def get_messages(session_id: str, limit: int = None) -> dict:
    path = f"/api/admin/chat/sessions/{session_id}/messages"
    if limit is not None and limit > 0:
        path += f"?limit={limit}"
    return _http("GET", path)


def get_last_seq(session_id: str) -> int:
    resp = _http("GET", f"/api/admin/chat/sessions/{session_id}/messages/last-seq")
    if resp.get("success") and resp.get("data"):
        return resp["data"].get("sequenceNum", -1)
    return -1


def get_context(session_id: str, context_type: str = "full") -> dict:
    return _http("GET", f"/api/admin/chat/sessions/{session_id}/context?contextType={context_type}")


def update_context(session_id: str, content: str, message_range: str = "",
                   token_estimate: int = None, context_type: str = "full") -> dict:
    body = {
        "contextType": context_type,
        "content": content,
    }
    if message_range:
        body["messageRange"] = message_range
    if token_estimate is not None:
        body["tokenEstimate"] = token_estimate
    return _http("PUT", f"/api/admin/chat/sessions/{session_id}/context", body)
