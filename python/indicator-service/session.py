import json
import os
import tempfile
import logging
from datetime import datetime

logger = logging.getLogger("indicator-service")

from config import DATA_DIR, SESSIONS_FILE, MAX_CONTEXT_ROUNDS

os.makedirs(DATA_DIR, exist_ok=True)

MAX_CONTEXT = MAX_CONTEXT_ROUNDS

_sessions = {}


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
    atomic_json_write(SESSIONS_FILE, _sessions)
    logger.info("Indicator sessions saved")


def ensure_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "stage": "analyzing",
            "messages": [],
            "pending_indicators": None,
        }
        return _sessions[session_id]

    s = _sessions[session_id]
    if isinstance(s, list):
        _sessions[session_id] = {
            "stage": "analyzing",
            "messages": s,
            "pending_indicators": None,
        }
    else:
        s.setdefault("stage", "analyzing")
        s.setdefault("messages", [])
        s.setdefault("pending_indicators", None)
    return _sessions[session_id]


def get_recent_messages(session_id: str) -> list:
    s = ensure_session(session_id)
    return s["messages"]


def get_session_stage(session_id: str) -> str:
    s = ensure_session(session_id)
    return s.get("stage", "analyzing")


def set_session_stage(session_id: str, stage: str):
    s = ensure_session(session_id)
    s["stage"] = stage
    save_sessions()


def set_pending_indicators(session_id: str, indicators_data: dict):
    s = ensure_session(session_id)
    s["pending_indicators"] = indicators_data
    save_sessions()


def get_pending_indicators(session_id: str) -> dict:
    s = ensure_session(session_id)
    return s.get("pending_indicators") or {}


def clear_pending_indicators(session_id: str):
    s = ensure_session(session_id)
    s["pending_indicators"] = None
    s["stage"] = "analyzing"
    save_sessions()


def add_message(session_id: str, role: str, content: str):
    s = ensure_session(session_id)
    now_str = datetime.now().isoformat()
    s["messages"].append({"role": role, "content": content, "timestamp": now_str})
    if len(s["messages"]) > MAX_CONTEXT * 4:
        s["messages"] = s["messages"][-(MAX_CONTEXT * 4):]
    save_sessions()


def get_all_sessions():
    return _sessions


def delete_session(session_id: str):
    if session_id in _sessions:
        del _sessions[session_id]
        save_sessions()


def build_context(session_id: str) -> str:
    msgs = get_recent_messages(session_id)
    recent = msgs[-(MAX_CONTEXT * 2):]
    context = ""
    for msg in recent:
        if msg.get("role") == "user":
            context += f"用户: {msg.get('content', '')}\n"
        elif msg.get("role") == "assistant":
            context += f"助手: {msg.get('content', '')[:200]}\n"
    return context


_sessions = load_sessions()
logger.info(f"Indicator service started: {len(_sessions)} sessions, context rounds={MAX_CONTEXT}")