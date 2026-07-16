"""
评估分析 API — 多智能体协作流式端点
"""
import json
import logging
import asyncio
import os
import shutil
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, List, Literal, Optional

from agents.langgraph_workflow import run_langgraph_workflow
from agents.tools import (
    create_evaluation_skill,
    delete_evaluation_skill,
    fetch_all_databases,
    fetch_datasets_for_database,
    fetch_evaluation_skill,
    fetch_evaluation_skills,
    update_evaluation_skill,
)
from llm_transport import LlmTransportError, post_chat_json

logger = logging.getLogger("evaluation.api")
_thread_pool = ThreadPoolExecutor(max_workers=8)

evaluation_router = APIRouter(prefix="/evaluation", tags=["评估分析"])

# ─── 文件持久化 ───
# 本地仓库优先复用旧版服务的数据，容器内则落在 /app/data/evaluation，
# 以便直接复用 qa-service 已挂载的持久化卷。
_LEGACY_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "solution-evaluation-service", "data")
)
_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "evaluation")
_DATA_DIR = os.getenv("EVALUATION_DATA_DIR") or (
    _LEGACY_DATA_DIR if os.path.isdir(_LEGACY_DATA_DIR) else _DEFAULT_DATA_DIR
)
os.makedirs(_DATA_DIR, exist_ok=True)
_SESSIONS_FILE = os.path.join(_DATA_DIR, "evaluation_sessions.json")
_HISTORY_FILE = os.path.join(_DATA_DIR, "evaluation_history.json")
_SKILLS_FILE = os.path.join(_DATA_DIR, "skills.json")
_write_lock = threading.RLock()
_skill_migration_lock = threading.Lock()
_skill_migration_checked = False


def _load_json(path, default):
    for candidate in (path, path + ".bak"):
        try:
            if os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as exc:
            logger.error("Failed to load JSON state %s: %s", candidate, exc)
    return default


def _save_json(path, data):
    with _write_lock:
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(path):
                shutil.copy2(path, path + ".bak")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


_eval_sessions: dict = _load_json(_SESSIONS_FILE, {})
_eval_history: list = _load_json(_HISTORY_FILE, [])
_legacy_eval_skills: list = _load_json(_SKILLS_FILE, [])


def _bounded_execution_result(result: dict) -> dict:
    """限制历史记录体积，同时保留 Skill 执行可恢复所需的结构化信息。"""
    if not isinstance(result, dict):
        return {}
    bounded = dict(result)
    query_results = []
    for item in bounded.get("queryResults", []) or []:
        if not isinstance(item, dict):
            continue
        compact = dict(item)
        compact["rows"] = (compact.get("rows", []) or [])[:100]
        query_results.append(compact)
    if "queryResults" in bounded:
        bounded["queryResults"] = query_results[:20]
    answer = str(bounded.get("final_answer", ""))
    if answer:
        bounded["final_answer"] = answer[:50000]
    return bounded


def _save_session_to_file(
    sid: str,
    question: str,
    final_answer: str,
    execution_steps: Optional[List[dict]] = None,
    result: Optional[dict] = None,
    skill_id: str = "",
):
    """保存完整会话；刷新后仍可恢复 Skill 执行流程和结构化结果。"""
    global _eval_history
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with _write_lock:
        _eval_sessions[sid] = {
            "session_id": sid,
            "question": question,
            "final_answer": final_answer[:50000],
            "executionSteps": (execution_steps or [])[:200],
            "result": _bounded_execution_result(result or {}),
            "skillId": skill_id,
            "time": now,
        }
        _save_json(_SESSIONS_FILE, _eval_sessions)

        existing = [h for h in _eval_history if h.get("id") == sid]
        if not existing:
            _eval_history.insert(0, {
                "id": sid,
                "title": question[:30] + ("..." if len(question) > 30 else ""),
                "time": now,
                "skillId": skill_id,
            })
        else:
            for h in _eval_history:
                if h.get("id") == sid:
                    h["title"] = question[:30] + ("..." if len(question) > 30 else "")
                    h["time"] = now
                    h["skillId"] = skill_id
        _eval_history = _eval_history[:200]
        _save_json(_HISTORY_FILE, _eval_history)


class EvaluationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    session_id: Optional[str] = Field(default=None, max_length=100)
    database_id: str = Field(default="", alias="dataSourceId", max_length=64)
    database_name: str = Field(default="", max_length=200)
    skill_id: str = Field(default="", alias="skillId", max_length=64)


class SkillQueryStep(BaseModel):
    datasetId: str = Field(max_length=64)
    datasetName: str = Field(default="", max_length=300)
    instruction: str = Field(default="", max_length=2000)
    dependsOnPrevious: Optional[bool] = None
    onDependencyFailure: Literal["stop", "skip", "continue"] = "skip"
    requireNonEmpty: bool = True
    onEmpty: Literal["stop", "skip", "continue"] = "continue"


class EvaluationSkillPayload(BaseModel):
    name: str = Field(max_length=100)
    description: str = Field(default="", max_length=1000)
    databaseId: str = Field(max_length=64)
    steps: List[SkillQueryStep]


MAX_SKILL_STEPS = 20
try:
    WORKFLOW_TIMEOUT_SECONDS = max(
        60,
        min(int(os.getenv("EVALUATION_WORKFLOW_TIMEOUT", "900")), 3600),
    )
except ValueError:
    WORKFLOW_TIMEOUT_SECONDS = 900


async def _validate_skill_payload(payload: EvaluationSkillPayload) -> dict:
    """校验 Skill，并使用服务端数据集信息覆盖客户端提交的名称。"""
    name = payload.name.strip()
    description = payload.description.strip()
    database_id = payload.databaseId.strip()
    if not name:
        raise ValueError("请输入 Skill 名称")
    if len(name) > 100:
        raise ValueError("Skill 名称不能超过 100 个字符")
    if len(description) > 1000:
        raise ValueError("执行目标不能超过 1000 个字符")
    if not database_id:
        raise ValueError("请先选择数据源")
    if not payload.steps:
        raise ValueError("Skill 至少需要一个数据集查询步骤")
    if len(payload.steps) > MAX_SKILL_STEPS:
        raise ValueError(f"单个 Skill 最多支持 {MAX_SKILL_STEPS} 个查询步骤")

    datasets = await asyncio.to_thread(fetch_datasets_for_database, database_id)
    dataset_map = {item.get("id", ""): item for item in datasets}
    normalised_steps = []
    for index, configured in enumerate(payload.steps, start=1):
        dataset_id = configured.datasetId.strip()
        instruction = configured.instruction.strip()
        dataset = dataset_map.get(dataset_id)
        if not dataset:
            raise ValueError(f"第 {index} 步的数据集不存在或不属于当前数据源")
        if not dataset.get("tableName"):
            raise ValueError(f"第 {index} 步的数据集「{dataset.get('name', dataset_id)}」未关联物理表")
        if not instruction:
            raise ValueError(f"请填写第 {index} 步的查询指令")
        if len(instruction) > 2000:
            raise ValueError(f"第 {index} 步的查询指令不能超过 2000 个字符")
        normalised_steps.append({
            "datasetId": dataset_id,
            "datasetName": dataset.get("name", "") or dataset_id,
            "instruction": instruction,
            "dependsOnPrevious": configured.dependsOnPrevious if configured.dependsOnPrevious is not None else index > 1,
            "onDependencyFailure": configured.onDependencyFailure,
            "requireNonEmpty": configured.requireNonEmpty,
            "onEmpty": configured.onEmpty,
        })

    return {
        "name": name,
        "description": description,
        "databaseId": database_id,
        "steps": normalised_steps,
    }


def _ensure_legacy_skills_migrated() -> dict:
    """首次访问时把旧 JSON Skill 幂等迁移到管理数据库。"""
    global _skill_migration_checked
    if _skill_migration_checked or not _legacy_eval_skills:
        return {"success": True}
    with _skill_migration_lock:
        if _skill_migration_checked:
            return {"success": True}
        current = fetch_evaluation_skills()
        if not current.get("success"):
            return current
        existing = {
            (
                str(item.get("databaseId", "")),
                str(item.get("name", "")).strip().casefold(),
            )
            for item in current.get("skills", [])
        }
        for legacy in _legacy_eval_skills:
            if not isinstance(legacy, dict):
                continue
            key = (
                str(legacy.get("databaseId", "")),
                str(legacy.get("name", "")).strip().casefold(),
            )
            if key in existing:
                continue
            response = create_evaluation_skill(legacy)
            if not response.get("success"):
                logger.error("Legacy Skill migration failed: %s", response.get("message", ""))
                return response
            existing.add(key)
        _skill_migration_checked = True
        return {"success": True}


def _load_skills(database_id: str = "") -> dict:
    migrated = _ensure_legacy_skills_migrated()
    if not migrated.get("success"):
        return migrated
    return fetch_evaluation_skills(database_id)


def _load_skill(skill_id: str) -> dict:
    migrated = _ensure_legacy_skills_migrated()
    if not migrated.get("success"):
        return migrated
    return fetch_evaluation_skill(skill_id)


def _get_llm_config():
    import importlib
    main_mod = importlib.import_module('main')
    return main_mod.load_llm_config()


def _sync_llm_call(system_prompt: str, user_message: str) -> str:
    config = _get_llm_config()
    api_key = config.get("apiKey", "")
    api_url = (config.get("apiUrl") or "").rstrip("/")
    model = config.get("model", "deepseek-chat")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("maxTokens", 4096)

    if not api_url:
        raise RuntimeError("大模型 API 地址未配置，请在「基础管理 → 大模型配置」中设置。")
    if not api_key and config.get("type") != "vllm":
        raise RuntimeError("大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置。")

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }

    url = f"{api_url}/chat/completions"

    try:
        data = post_chat_json(url, api_key, body, timeout=180)
        return data["choices"][0]["message"]["content"]
    except LlmTransportError as e:
        raise RuntimeError(f"LLM调用失败: {str(e)[:500]}")
    except Exception as e:
        raise RuntimeError(f"LLM调用失败: {str(e)[:500]}")


async def async_llm_call(system_prompt: str, user_message: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_thread_pool, _sync_llm_call, system_prompt, user_message)


@evaluation_router.post("/analyze/stream")
async def analyze_stream(request: EvaluationRequest):
    question = request.query.strip()
    if not question:
        return StreamingResponse(
            iter([json.dumps({"type": "error", "message": "评估问题不能为空"}, ensure_ascii=False) + "\n"]),
            media_type="application/x-ndjson",
        )
    logger.info(
        f"Evaluation request: {question[:100]}, db={request.database_id}, "
        f"skill={request.skill_id}"
    )

    session_id = request.session_id or str(uuid.uuid4())
    skill_response = await asyncio.to_thread(_load_skill, request.skill_id) if request.skill_id else {
        "success": True,
        "skill": None,
    }
    selected_skill = skill_response.get("skill") if skill_response.get("success") else None

    async def generate():
        final_answer = ""
        execution_steps: List[dict] = []
        result_payload: dict = {}
        if request.skill_id and not skill_response.get("success"):
            yield json.dumps({
                "type": "error",
                "message": skill_response.get("message", "Skills 持久化服务不可用"),
                "session_id": session_id,
            }, ensure_ascii=False) + "\n"
            return
        if request.skill_id and not selected_skill:
            yield json.dumps({
                "type": "error",
                "message": "所选 Skill 不存在或已被删除",
                "session_id": session_id,
            }, ensure_ascii=False) + "\n"
            return
        if selected_skill and (
            selected_skill.get("valid") is False or not selected_skill.get("steps")
        ):
            yield json.dumps({
                "type": "error",
                "message": selected_skill.get(
                    "validationMessage",
                    "所选 Skill 没有有效查询步骤，请重新编辑后保存",
                ),
                "session_id": session_id,
            }, ensure_ascii=False) + "\n"
            return
        if selected_skill and selected_skill.get("databaseId") != request.database_id:
            yield json.dumps({
                "type": "error",
                "message": "所选 Skill 不属于当前数据源，请重新选择",
                "session_id": session_id,
            }, ensure_ascii=False) + "\n"
            return
        try:
            async with asyncio.timeout(WORKFLOW_TIMEOUT_SECONDS):
                async for event in run_langgraph_workflow(
                    question=question,
                    llm_call_fn=async_llm_call,
                    session_id=session_id,
                    database_id=request.database_id,
                    database_name=request.database_name,
                    skill=selected_skill,
                ):
                    if event.get("type") == "step" and isinstance(event.get("step"), dict):
                        step = event["step"]
                        existing_index = next(
                            (index for index, item in enumerate(execution_steps)
                             if item.get("step") == step.get("step")),
                            -1,
                        )
                        if existing_index >= 0:
                            execution_steps[existing_index] = step
                        else:
                            execution_steps.append(step)
                    if event.get("type") == "result":
                        event["session_id"] = session_id
                        final_answer = event.get("final_answer", "")
                        result_payload = event.get("result", {}) if isinstance(event.get("result"), dict) else {}
                    yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

            # 保存到文件
            if final_answer:
                _save_session_to_file(
                    session_id,
                    question,
                    final_answer,
                    execution_steps=execution_steps,
                    result=result_payload,
                    skill_id=request.skill_id,
                )

        except TimeoutError:
            logger.error("Evaluation workflow timed out after %s seconds", WORKFLOW_TIMEOUT_SECONDS)
            yield json.dumps({
                "type": "error",
                "message": f"执行超时：整个评估流程超过 {WORKFLOW_TIMEOUT_SECONDS} 秒",
                "session_id": session_id,
            }, ensure_ascii=False) + "\n"
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


@evaluation_router.get("/skills")
async def get_skills(database_id: str = ""):
    """获取 Skills；传入 database_id 时仅返回当前数据源的 Skills。"""
    response = await asyncio.to_thread(_load_skills, database_id)
    if not response.get("success"):
        return {
            "success": False,
            "message": response.get("message", "Skills 持久化服务不可用"),
            "skills": [],
        }
    return {"success": True, "skills": response.get("skills", [])}


@evaluation_router.post("/skills")
async def create_skill(payload: EvaluationSkillPayload):
    try:
        skill = await _validate_skill_payload(payload)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    migration = await asyncio.to_thread(_ensure_legacy_skills_migrated)
    if not migration.get("success"):
        return {"success": False, "message": migration.get("message", "Skills 持久化服务不可用")}
    response = await asyncio.to_thread(create_evaluation_skill, skill)
    return response


@evaluation_router.put("/skills/{skill_id}")
async def update_skill(skill_id: str, payload: EvaluationSkillPayload):
    try:
        validated = await _validate_skill_payload(payload)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    migration = await asyncio.to_thread(_ensure_legacy_skills_migrated)
    if not migration.get("success"):
        return {"success": False, "message": migration.get("message", "Skills 持久化服务不可用")}
    return await asyncio.to_thread(update_evaluation_skill, skill_id, validated)


@evaluation_router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    migration = await asyncio.to_thread(_ensure_legacy_skills_migrated)
    if not migration.get("success"):
        return {"success": False, "message": migration.get("message", "Skills 持久化服务不可用")}
    return await asyncio.to_thread(delete_evaluation_skill, skill_id)


@evaluation_router.get("/datasets")
async def get_datasets(database_id: str):
    """返回当前数据源可用于 Skills 编排的数据集。"""
    try:
        datasets = await asyncio.to_thread(fetch_datasets_for_database, database_id)
        return {"success": True, "datasets": datasets}
    except Exception as exc:
        logger.error("Failed to load skill datasets: %s", exc)
        return {"success": False, "message": str(exc), "datasets": []}


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
    with _write_lock:
        return {"success": True, "history": list(_eval_history)}


@evaluation_router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取指定会话"""
    with _write_lock:
        session = _eval_sessions.get(session_id)
    if session:
        return {"success": True, "session": session}
    return {"success": False, "message": "会话不存在"}


@evaluation_router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    global _eval_history
    with _write_lock:
        if session_id in _eval_sessions:
            del _eval_sessions[session_id]
            _save_json(_SESSIONS_FILE, _eval_sessions)
        _eval_history = [h for h in _eval_history if h.get("id") != session_id]
        _save_json(_HISTORY_FILE, _eval_history)
    return {"success": True, "message": "已删除"}
