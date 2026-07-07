"""
方案评估 API — 多智能体协作流式端点
"""
import json
import logging
import asyncio
import os
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from agents.workflow import run_evaluation_workflow
from agents.tools import fetch_all_databases

logger = logging.getLogger("evaluation.api")
_thread_pool = ThreadPoolExecutor(max_workers=8)

evaluation_router = APIRouter(prefix="/evaluation", tags=["方案评估"])

# ─── 文件持久化 ───
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "solution-evaluation-service", "data")
os.makedirs(_DATA_DIR, exist_ok=True)
_SESSIONS_FILE = os.path.join(_DATA_DIR, "evaluation_sessions.json")
_HISTORY_FILE = os.path.join(_DATA_DIR, "evaluation_history.json")
_write_lock = threading.Lock()


def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path, data):
    with _write_lock:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


_eval_sessions: dict = _load_json(_SESSIONS_FILE, {})
_eval_history: list = _load_json(_HISTORY_FILE, [])


def _save_session_to_file(sid: str, question: str, final_answer: str):
    """保存会话到文件"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    _eval_sessions[sid] = {
        "session_id": sid,
        "question": question,
        "final_answer": final_answer[:50000],
        "time": now
    }
    _save_json(_SESSIONS_FILE, _eval_sessions)

    existing = [h for h in _eval_history if h.get("id") == sid]
    if not existing:
        _eval_history.insert(0, {
            "id": sid,
            "title": question[:30] + ("..." if len(question) > 30 else ""),
            "time": now
        })
    else:
        for h in _eval_history:
            if h.get("id") == sid:
                h["title"] = question[:30] + ("..." if len(question) > 30 else "")
                h["time"] = now
    _eval_history = _eval_history[:200]
    _save_json(_HISTORY_FILE, _eval_history)


class EvaluationRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    database_id: str = ""
    database_name: str = ""


def _get_llm_config():
    import importlib
    main_mod = importlib.import_module('main')
    return main_mod.load_llm_config()


def _sync_llm_call(system_prompt: str, user_message: str) -> str:
    import urllib.request
    import urllib.error
    import ssl

    config = _get_llm_config()
    api_key = config.get("apiKey", "")
    api_url = config.get("apiUrl", "https://api.deepseek.com/v1").rstrip("/")
    model = config.get("model", "deepseek-chat")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("maxTokens", 4096)

    if not api_key and config.get("type") != "vllm":
        raise RuntimeError("大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置。")

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
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
        with urllib.request.urlopen(req, timeout=180, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err = json.loads(err_body)
            msg = err.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise RuntimeError(f"LLM调用失败 (HTTP {e.code}): {msg[:500]}")
    except Exception as e:
        raise RuntimeError(f"LLM调用失败: {str(e)[:500]}")


async def async_llm_call(system_prompt: str, user_message: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_thread_pool, _sync_llm_call, system_prompt, user_message)


@evaluation_router.post("/analyze/stream")
async def analyze_stream(request: EvaluationRequest):
    logger.info(f"Evaluation request: {request.query[:100]}, db={request.database_id}")

    session_id = request.session_id or str(uuid.uuid4())

    async def generate():
        final_answer = ""
        try:
            async for event in run_evaluation_workflow(
                question=request.query,
                llm_call_fn=async_llm_call,
                session_id=session_id,
                database_id=request.database_id,
                database_name=request.database_name,
            ):
                if event.get("type") == "result":
                    event["session_id"] = session_id
                    final_answer = event.get("final_answer", "")
                yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

            # 保存到文件
            if final_answer:
                _save_session_to_file(session_id, request.query, final_answer)

        except Exception as e:
            logger.error(f"Evaluation stream error: {e}", exc_info=True)
            yield json.dumps({
                "type": "error",
                "message": f"系统异常: {str(e)[:500]}",
                "session_id": session_id
            }, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@evaluation_router.get("/data-sources")
async def get_data_sources():
    """获取所有数据源（数据库配置列表）"""
    try:
        databases = fetch_all_databases()
        def _map_status(db):
            raw = db.get("status", "")
            error = db.get("errorMsg")
            if error:
                return "error"
            if raw in ("已连接", "connected", "active"):
                return "available"
            return "unavailable"

        return {
            "success": True,
            "databases": databases,
            "dataSources": [
                {
                    "id": db.get("id", ""),
                    "name": db.get("name", ""),
                    "type": db.get("type", ""),
                    "host": db.get("host", ""),
                    "port": db.get("port", ""),
                    "dbName": db.get("database", db.get("dbName", "")),
                    "status": _map_status(db),
                }
                for db in databases
            ]
        }
    except Exception as e:
        logger.error(f"Failed to load data sources: {e}")
        return {"success": False, "message": str(e), "databases": [], "dataSources": []}


@evaluation_router.get("/history")
async def get_history():
    """获取历史记录列表"""
    return {"success": True, "history": _eval_history}


@evaluation_router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取指定会话"""
    session = _eval_sessions.get(session_id)
    if session:
        return {"success": True, "session": session}
    return {"success": False, "message": "会话不存在"}


@evaluation_router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    if session_id in _eval_sessions:
        del _eval_sessions[session_id]
        _save_json(_SESSIONS_FILE, _eval_sessions)
    global _eval_history
    _eval_history = [h for h in _eval_history if h.get("id") != session_id]
    _save_json(_HISTORY_FILE, _eval_history)
    return {"success": True, "message": "已删除"}
