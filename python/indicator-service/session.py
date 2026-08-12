"""
Indicator 会话管理（MySQL 持久化）。
通过 admin-service 的 /api/admin/chat 接口读写聊天数据，
替代原来的 sessions.json 文件持久化。
"""
import logging
from datetime import datetime

logger = logging.getLogger("indicator-service")

from config import MAX_CONTEXT_ROUNDS
from chat_client import (
    create_session as _cs_create,
    update_session as _cs_update,
    delete_session as _cs_delete,
    get_session as _cs_get,
    get_messages as _cs_get_msgs,
    add_message as _cs_add_msg,
    get_last_seq as _cs_last_seq,
    update_context as _cs_update_ctx,
    get_context as _cs_get_ctx,
)

MAX_CONTEXT = MAX_CONTEXT_ROUNDS


def ensure_session(session_id: str, auto_create: bool = True):
    """确保会话存在并返回基本信息（从 MySQL 读取）。

    Args:
        session_id: 会话 ID
        auto_create: 如果会话不存在是否自动创建。默认 True。
                     设为 False 时，不存在的会话返回 None。

    Returns:
        dict | None: 会话数据字典，auto_create=False 且会话不存在时返回 None
    """
    resp = _cs_get(session_id)
    if resp.get("success") and resp.get("data"):
        data = resp["data"]
        return {
            "stage": data.get("stage", "analyzing"),
            "messages": data.get("messages", []),
            "pending_indicators": _parse_extra_data(data.get("extraData", "")),
            "session_id": session_id,
        }
    if not auto_create:
        return None
    # 会话不存在，自动创建
    _cs_create(session_id, "indicator", stage="analyzing")
    return {"stage": "analyzing", "messages": [], "pending_indicators": None, "session_id": session_id}


def _parse_extra_data(raw: str) -> dict:
    """解析 extraData JSON 字符串中的 pending_indicators"""
    if not raw:
        return None
    import json as _json
    try:
        if isinstance(raw, str):
            parsed = _json.loads(raw)
        else:
            parsed = raw
        return parsed.get("pending_indicators") if isinstance(parsed, dict) else None
    except Exception:
        return None


def _serialize_extra_data(pending_indicators) -> str:
    """将 pending_indicators 序列化为 extraData JSON"""
    import json as _json
    return _json.dumps({"pending_indicators": pending_indicators}, ensure_ascii=False)


def get_recent_messages(session_id: str) -> list:
    """获取会话的全部消息"""
    resp = _cs_get_msgs(session_id)
    if not resp.get("success"):
        return []
    return resp.get("data", [])


def get_session_stage(session_id: str) -> str:
    """获取会话当前阶段"""
    resp = _cs_get(session_id)
    if resp.get("success") and resp.get("data"):
        return resp["data"].get("stage", "analyzing")
    return "analyzing"


def set_session_stage(session_id: str, stage: str):
    """设置会话阶段"""
    ensure_session(session_id)
    _cs_update(session_id, stage=stage)


def set_pending_indicators(session_id: str, indicators_data: dict):
    """暂存待确认的指标体系数据到 MySQL extraData"""
    ensure_session(session_id)
    extra = _serialize_extra_data(indicators_data)
    _cs_update(session_id, stage="awaiting_confirmation", extraData=extra)


def get_pending_indicators(session_id: str) -> dict:
    """获取待确认的指标体系数据"""
    resp = _cs_get(session_id)
    if resp.get("success") and resp.get("data"):
        return _parse_extra_data(resp["data"].get("extraData", "")) or {}
    return {}


def clear_pending_indicators(session_id: str):
    """清空待确认数据并重置阶段"""
    _cs_update(session_id, stage="analyzing")
    # extra_data 会被保留但 pending_indicators 已清理


def add_message(session_id: str, role: str, content: str, metadata: dict = None):
    """追加消息到 MySQL。返回 seq"""
    import re as _re
    last_seq = _cs_last_seq(session_id)
    seq = last_seq + 1
    meta_str = ""

    # 剥离 content 中的 map_annotations JSON 块，提取为 metadata
    _map_pat = _re.compile(r'```map_annotations\s*\n([\s\S]*?)```', _re.MULTILINE)
    m = _map_pat.search(content) if content else None
    if m:
        import json as _json
        try:
            map_data = _json.loads(m.group(1))
            if isinstance(map_data, dict) and metadata is None:
                metadata = {}
            if isinstance(metadata, dict):
                metadata["mapAnnotationsRaw"] = map_data
        except Exception:
            pass
        content = _map_pat.sub("", content).strip() if content else content

    if metadata:
        import json as _json
        meta_str = _json.dumps(metadata, ensure_ascii=False)

    title = ""
    if role == "user" and seq == 0:
        title = content[:30] if content and len(content) > 30 else (content or "")

    resp = _cs_add_msg(session_id, role, content, seq, metadata=meta_str, title=title)
    return seq


def get_all_sessions() -> dict:
    """获取所有会话（兼容旧接口，返回内存字典形式）。

    注意：不会为已删除的会话自动重建。如果 chat_history 中有记录
    但 chat_sessions 中没有对应记录，则该会话不会出现在返回值中。
    """
    from chat_client import list_sessions as _list_sessions
    resp = _list_sessions()
    if not resp.get("success"):
        return {}
    items = resp.get("items", [])
    result = {}
    for item in items:
        sid = item.get("sessionId", "")
        session_data = ensure_session(sid, auto_create=False)
        if session_data is not None:
            result[sid] = session_data
    return result


def delete_session(session_id: str) -> bool:
    """删除会话（MySQL 级联删除）。
    
    Returns:
        bool: True 表示删除成功，False 表示删除失败
    """
    resp = _cs_delete(session_id)
    if not resp.get("success"):
        logger.warning(f"删除会话 {session_id} 失败: {resp.get('message', '未知错误')}")
        return False
    return True


def build_context(session_id: str) -> str:
    """构建最近 MAX_CONTEXT*2 轮对话的上下文字符串"""
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
            context += f"助手: {content[:200]}\n"
    return context


logger.info(f"Indicator 会话管理已切换至 MySQL 持久化, 上下文轮数={MAX_CONTEXT}")
