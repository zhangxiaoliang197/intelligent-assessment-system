"""
评估分析 API — 多智能体协作流式端点
"""
import json
import logging
import asyncio
import copy
import os
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from agents.langgraph_workflow import run_langgraph_workflow
from agents.tools import fetch_all_databases
from agents.skill_catalog import (
    SkillCatalogError,
    SkillConflictError,
    SkillNotFoundError,
    SkillPermissionError,
    SkillReadOnlyError,
    SkillStoreUnavailableError,
    create_custom_skill,
    delete_custom_skill,
    get_skill,
    get_custom_catalog_warning,
    list_skills,
    recommend_skills,
    skill_availability,
    update_custom_skill,
)
from agents.skill_runner import run_skill_workflow
from skill_api import skill_actor_from_request

logger = logging.getLogger("evaluation.api")
_thread_pool = ThreadPoolExecutor(max_workers=8)
_io_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evaluation-history")

evaluation_router = APIRouter(prefix="/evaluation", tags=["评估分析"])

# ─── 文件持久化 ───
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
_SESSIONS_FILE = os.path.join(_DATA_DIR, "evaluation_sessions.json")
_HISTORY_FILE = os.path.join(_DATA_DIR, "evaluation_history.json")
_write_lock = threading.RLock()


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
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)


_eval_sessions: dict = _load_json(_SESSIONS_FILE, {})
_eval_history: list = _load_json(_HISTORY_FILE, [])


def _save_session_to_file(
    sid: str,
    question: str,
    final_answer: str,
    skill_id: str = "",
    result: Optional[dict] = None,
    steps: Optional[list] = None,
    database_id: str = "",
    database_name: str = "",
):
    """保存会话到文件"""
    global _eval_history
    with _write_lock:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        previous_turns = _eval_sessions.get(sid, {}).get("turns", [])
        turn = {
            "question": question,
            "final_answer": final_answer[:50000],
            "skill_id": skill_id,
            "result": result or {},
            "steps": steps or [],
            "database_id": database_id,
            "database_name": database_name,
            "time": now,
        }
        _eval_sessions[sid] = {
            "session_id": sid,
            **turn,
            "turns": [*previous_turns, turn][-50:],
        }

        # 将会话移到历史记录最前面，并在历史记录和会话详情中保留同一有界集合
        _eval_history = [item for item in _eval_history if item.get("id") != sid]
        _eval_history.insert(0, {
            "id": sid,
            "title": question[:30] + ("..." if len(question) > 30 else ""),
            "time": now,
            "skill_id": skill_id,
        })
        _eval_history = _eval_history[:200]
        retained_ids = {item.get("id") for item in _eval_history}
        for stored_id in list(_eval_sessions.keys()):
            if stored_id not in retained_ids:
                _eval_sessions.pop(stored_id, None)

        _save_json(_SESSIONS_FILE, _eval_sessions)
        _save_json(_HISTORY_FILE, _eval_history)


def _delete_session_from_file(sid: str) -> bool:
    """原子性地从内存和两个持久化文件中移除一个会话"""
    global _eval_history
    with _write_lock:
        existed = sid in _eval_sessions or any(item.get("id") == sid for item in _eval_history)
        _eval_sessions.pop(sid, None)
        _eval_history = [item for item in _eval_history if item.get("id") != sid]
        _save_json(_SESSIONS_FILE, _eval_sessions)
        _save_json(_HISTORY_FILE, _eval_history)
        return existed


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: str
    session_id: Optional[str] = None
    database_id: str = Field(default="", alias="dataSourceId")
    database_name: str = ""
    attachment_id: Optional[str] = None
    skill_id: Optional[str] = Field(default=None, alias="skillId")
    timeout_seconds: Optional[int] = Field(default=None, ge=30, le=1800, alias="timeoutSeconds")


class SkillRecommendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    query: str
    limit: int = Field(default=3, ge=1, le=10)
    database_id: str = Field(default="", alias="dataSourceId")


class SkillStepInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    id: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    dataset_keywords: list[str] = Field(
        min_length=1,
        max_length=12,
        alias="datasetKeywords",
    )
    allow_reuse: bool = Field(default=False, alias="allowReuse")
    dataset_id: Optional[str] = Field(default=None, max_length=128, alias="datasetId")
    dataset_name: Optional[str] = Field(default=None, max_length=160, alias="datasetName")
    depends_on: list[str] = Field(default_factory=list, max_length=12, alias="dependsOn")
    run_if: str = Field(default="all_success", pattern="^(all_success|any_success|always)$", alias="runIf")
    retry_count: int = Field(default=0, ge=0, le=3, alias="retryCount")
    timeout_seconds: int = Field(default=130, ge=5, le=300, alias="timeoutSeconds")
    on_failure: str = Field(default="continue", pattern="^(continue|stop|skip_dependents)$", alias="onFailure")


class SkillOrchestrationInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    mode: str = Field(default="sequential", pattern="^(sequential|dependency)$")
    max_concurrency: int = Field(default=1, ge=1, le=6, alias="maxConcurrency")
    timeout_seconds: int = Field(default=600, ge=30, le=1800, alias="timeoutSeconds")
    failure_policy: str = Field(default="continue", pattern="^(continue|stop)$", alias="failurePolicy")


class SkillCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=40)
    triggers: list[str] = Field(default_factory=list, max_length=12)
    recommended_questions: list[str] = Field(
        default_factory=list,
        max_length=5,
        alias="recommendedQuestions",
    )
    steps: list[SkillStepInput] = Field(min_length=1, max_length=12)
    output_instruction: str = Field(
        min_length=1,
        max_length=1200,
        alias="outputInstruction",
    )
    owner_id: Optional[str] = Field(default=None, max_length=128, alias="ownerId")
    team_id: Optional[str] = Field(default=None, max_length=128, alias="teamId")
    visibility: Optional[str] = Field(default=None, pattern="^(private|team|public)$")
    status: Optional[str] = Field(default=None, pattern="^(draft|published|archived)$")
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    is_template: Optional[bool] = Field(default=None, alias="isTemplate")
    orchestration: SkillOrchestrationInput = Field(default_factory=SkillOrchestrationInput)


class SkillUpdateRequest(SkillCreateRequest):
    expected_revision: int = Field(ge=1, alias="expectedRevision")


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

    ca_cert_file = os.getenv("LLM_CA_CERT_FILE") or config.get("caCertPath") or None
    try:
        ssl_ctx = ssl.create_default_context(cafile=ca_cert_file)
    except (OSError, ssl.SSLError) as exc:
        raise RuntimeError(f"大模型 CA 证书配置无效: {exc}") from exc

    tls_setting = os.getenv("LLM_TLS_VERIFY", str(config.get("tlsVerify", True))).strip().lower()
    verify_tls = tls_setting not in {"0", "false", "no", "off"}
    if not verify_tls:
        if config.get("type") != "vllm":
            raise RuntimeError("仅内网自签名 vLLM 允许关闭 TLS 校验；公网模型必须校验证书")
        logger.warning("TLS certificate verification is disabled for the configured vLLM endpoint")
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


async def async_llm_call(system_prompt: str, user_message: str,
                         on_token=None) -> str:
    """调用 LLM，可选择通过 *on_token* 回调逐个流式传输 token。

    当提供 *on_token* 时，函数内部使用 SSE 流式传输，
    对每个接收到的 token 调用 ``on_token(chunk)``。
    不提供 *on_token* 时，将标准的阻塞调用派发到线程池。

    两种模式均返回完整的响应文本。
    """
    if on_token:
        return await _async_stream_llm_internal(
            system_prompt, user_message, on_token)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _thread_pool, _sync_llm_call, system_prompt, user_message)


async def _async_stream_llm_internal(
    system_prompt: str, user_message: str,
    on_token,
) -> str:
    """通过 SSE 流式传输 LLM token，对每个 token 调用 *on_token*。

    使用 ``asyncio.Queue`` 桥接到线程池工作线程，该线程读取
    SSE 流（urllib 是同步的）。异步调用者消费队列并调用 ``on_token``。
    """
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
        raise RuntimeError(
            "大模型 API Key 未配置，请在「基础管理 → 大模型配置」中设置。"
        )

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }).encode("utf-8")

    url = f"{api_url}/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    ca_cert_file = os.getenv("LLM_CA_CERT_FILE") or config.get("caCertPath") or None
    try:
        ssl_ctx = ssl.create_default_context(cafile=ca_cert_file)
    except (OSError, ssl.SSLError) as exc:
        raise RuntimeError(f"大模型 CA 证书配置无效: {exc}") from exc

    tls_setting = (
        os.getenv("LLM_TLS_VERIFY",
                   str(config.get("tlsVerify", True))).strip().lower()
    )
    verify_tls = tls_setting not in {"0", "false", "no", "off"}
    if not verify_tls:
        if config.get("type") != "vllm":
            raise RuntimeError(
                "仅内网自签名 vLLM 允许关闭 TLS 校验；公网模型必须校验证书"
            )
        logger.warning("已为 vLLM 端点禁用 TLS 校验")
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    token_queue: asyncio.Queue = asyncio.Queue()
    full_text = ""
    error_ref = []

    def _read_sse():
        """线程池工作线程，读取 SSE 行并将 token 送入队列"""
        nonlocal full_text
        try:
            with urllib.request.urlopen(req, timeout=300,
                                        context=ssl_ctx) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                        delta = (
                            ev.get("choices", [{}])[0]
                              .get("delta", {})
                              .get("content", "")
                        )
                        if delta:
                            full_text += delta
                            # Schedule push to the queue on the event-loop
                            asyncio.run_coroutine_threadsafe(
                                token_queue.put(delta), loop
                            )
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            error_ref.append(str(exc))
        finally:
            asyncio.run_coroutine_threadsafe(
                token_queue.put(None), loop
            )

    loop = asyncio.get_event_loop()
    # Start the SSE reader in the thread pool
    fut = loop.run_in_executor(_thread_pool, _read_sse)

    # Consume tokens from the queue
    while True:
        chunk = await token_queue.get()
        if chunk is None:
            break
        if on_token:
            on_token(chunk)

    # Check for errors
    if error_ref:
        raise RuntimeError(f"Streaming LLM error: {error_ref[0]}")

    await fut  # re-raise any exception from the worker
    return full_text


async def async_gen_llm_stream(
    system_prompt: str, user_message: str,
):
    """异步生成器，通过 SSE 逐个生成 LLM 响应 token。

    生成：
        str: 从流式 API 到达的每个文本 token。
    """
    collected = []

    def _collect(chunk: str):
        collected.append(chunk)

    await _async_stream_llm_internal(system_prompt, user_message, _collect)

    for token in collected:
        yield token


@evaluation_router.post("/analyze/stream")
async def analyze_stream(request: EvaluationRequest, http_request: Request):
    logger.info(
        f"评估请求: {request.query[:100]}, 数据库={request.database_id}, "
        f"技能={request.skill_id or 'default-workflow'}"
    )

    session_id = request.session_id or str(uuid.uuid4())
    actor = skill_actor_from_request(http_request)
    selected_skill = None
    if request.skill_id:
        selected_skill = get_skill(request.skill_id, actor)
        if not selected_skill:
            raise HTTPException(
                status_code=404,
                detail=f"Skill 不存在或当前用户无权访问: {request.skill_id}",
            )

    # 获取附件文本
    attachment_text = ""
    if request.attachment_id:
        try:
            from attachment_handler import get_attachment_text
            attachment_text = get_attachment_text(request.attachment_id) or ""
        except Exception:
            pass

    async def generate():
        final_answer = ""
        final_result = {}
        execution_steps = []
        try:
            if selected_skill:
                workflow = run_skill_workflow(
                    question=request.query,
                    llm_call_fn=async_llm_call,
                    session_id=session_id,
                    database_id=request.database_id,
                    database_name=request.database_name,
                    skill=selected_skill,
                    attachment_text=attachment_text,
                    actor_id=actor.user_id,
                    timeout_seconds=request.timeout_seconds,
                )
            else:
                workflow = run_langgraph_workflow(
                    question=request.query,
                    llm_call_fn=async_llm_call,
                    session_id=session_id,
                    database_id=request.database_id,
                    database_name=request.database_name,
                    attachment_text=attachment_text,
                )

            async for event in workflow:
                if event.get("type") == "step":
                    incoming_step = event.get("step", {})
                    existing_index = next(
                        (
                            index
                            for index, step in enumerate(execution_steps)
                            if step.get("step") == incoming_step.get("step")
                        ),
                        -1,
                    )
                    if existing_index >= 0:
                        execution_steps[existing_index] = incoming_step
                    else:
                        execution_steps.append(incoming_step)
                if event.get("type") == "result":
                    event["session_id"] = session_id
                    final_result = event.get("result", {})
                    final_answer = event.get("final_answer", "") or final_result.get("final_answer", "")
                    if final_answer:
                        try:
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(
                                _io_pool,
                                partial(
                                    _save_session_to_file,
                                    session_id,
                                    request.query,
                                    final_answer,
                                    request.skill_id or "",
                                    final_result,
                                    execution_steps,
                                    request.database_id,
                                    request.database_name,
                                ),
                            )
                        except Exception as save_error:
                            # 持久化失败不能将已成功的分析变成第二个矛盾的流错误
                            logger.error(f"持久化评估会话失败: {save_error}", exc_info=True)
                yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

        except Exception as e:
            logger.error(f"评估流错误: {e}", exc_info=True)
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


def _raise_skill_http_error(exc: SkillCatalogError) -> None:
    if isinstance(exc, SkillStoreUnavailableError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (SkillReadOnlyError, SkillPermissionError)):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, SkillNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, SkillConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@evaluation_router.get("/skills")
async def get_skills(
    request: Request,
    dataSourceId: str = "",
    status: str = "",
    visibility: str = "",
    tag: str = "",
    favorite: bool = False,
    template: Optional[bool] = None,
    includeArchived: bool = False,
):
    """返回 15 个内置 Skill 加上所有用户创建的 Skill"""
    actor = skill_actor_from_request(request)
    try:
        skills = list_skills(
            actor,
            include_archived=includeArchived,
            statuses=[status] if status else None,
            tags=[tag] if tag else None,
            template=template,
            favorites_only=favorite,
        )
    except SkillCatalogError as exc:
        raise HTTPException(status_code=500, detail=f"Skill 目录加载失败: {exc}")
    if visibility:
        skills = [skill for skill in skills if skill.get("visibility") == visibility]
    datasets = []
    availability_error = ""
    if dataSourceId:
        from agents.tools import fetch_skill_datasets_for_database

        try:
            datasets = await asyncio.to_thread(
                fetch_skill_datasets_for_database, dataSourceId, True, False
            )
        except Exception as exc:
            logger.warning(f"计算 Skill 可用性失败: {exc}")
            availability_error = str(exc)[:300]

    items = []
    for skill in skills:
        item = dict(skill)
        item["stepCount"] = len(skill.get("steps", []))
        if dataSourceId:
            item["availability"] = (
                {
                    "status": "unknown",
                    "available": False,
                    "complete": False,
                    "matchedSteps": 0,
                    "totalSteps": len(skill.get("steps", [])),
                    "datasetPlan": [],
                    "error": availability_error,
                }
                if availability_error
                else {"status": "ready", **skill_availability(skill, datasets)}
            )
        items.append(item)
    return {
        "success": True,
        "version": "1.1.0",
        "skills": items,
        "total": len(items),
        "builtInTotal": sum(1 for item in items if item.get("source") == "builtin"),
        "customTotal": sum(1 for item in items if item.get("source") == "custom"),
        "tags": sorted({tag for item in items for tag in item.get("tags", [])}),
        "customStoreStatus": "warning" if get_custom_catalog_warning() else "ready",
        "customStoreMessage": get_custom_catalog_warning(),
        "availabilityStatus": "error" if availability_error else "ready",
        "availabilityMessage": availability_error,
    }


@evaluation_router.post("/skills", status_code=201)
async def create_evaluation_skill(request: SkillCreateRequest, http_request: Request):
    """创建全局共享的自定义 Skill；不接受 SQL 作为输入"""
    try:
        skill = await asyncio.to_thread(
            create_custom_skill,
            request.model_dump(by_alias=True, exclude_none=True),
            skill_actor_from_request(http_request),
        )
    except SkillCatalogError as exc:
        _raise_skill_http_error(exc)
    return {"success": True, "skill": skill}


@evaluation_router.post("/skills/recommend")
async def recommend_evaluation_skills(request: SkillRecommendRequest, http_request: Request):
    actor = skill_actor_from_request(http_request)
    # 检索稍宽的词汇候选集，然后与数据源就绪状态结合。
    # 这避免了自信地推荐一个无法针对用户所选源运行的 Skill。
    recommendations = recommend_skills(request.query, min(10, max(request.limit * 3, request.limit)), actor=actor)
    datasets = []
    availability_error = ""
    if request.database_id:
        from agents.tools import fetch_skill_datasets_for_database

        try:
            datasets = await asyncio.to_thread(
                fetch_skill_datasets_for_database, request.database_id, True, False
            )
        except Exception as exc:
            logger.warning("无法用可用性信息丰富 Skill 推荐: %s", exc)
            availability_error = str(exc)[:300]

    ranked = []
    for position, skill in enumerate(recommendations):
        item = dict(skill)
        base_score = int(item.get("recommendationScore") or item.get("score") or 0)
        if request.database_id:
            availability = skill_availability(item, datasets)
            total = max(int(availability.get("totalSteps") or 0), 1)
            completeness = int(availability.get("matchedSteps") or 0) / total
            readiness_score = (
                0
                if availability_error
                else round(completeness * 80) + (30 if availability.get("complete") else 0)
            )
            item["availability"] = {
                "status": "unknown" if availability_error else "ready",
                "completeness": round(completeness, 4),
                "error": availability_error,
                **availability,
            }
            item["recommendationScore"] = base_score + readiness_score
            item["recommendationReason"] = (
                "已按场景匹配；当前数据源完整度暂不可用"
                if availability_error
                else (
                    f"命中 {len(item.get('matchedTriggers', []))} 个场景词，"
                    f"当前数据源可匹配 {availability['matchedSteps']}/{availability['totalSteps']} 步"
                )
            )
        else:
            item["recommendationReason"] = (
                f"命中场景词：{'、'.join(item.get('matchedTriggers', []))}"
                if item.get("matchedTriggers")
                else "名称或数据集关键词与当前问题匹配"
            )
        ranked.append((int(item.get("recommendationScore") or 0), position, item))
    ranked.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    recommendations = [candidate[2] for candidate in ranked[: request.limit]]
    return {"success": True, "skills": recommendations, "total": len(recommendations)}


@evaluation_router.get("/skills/{skill_id}")
async def get_skill_detail(skill_id: str, request: Request):
    skill = get_skill(skill_id, skill_actor_from_request(request), include_archived=True)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {skill_id}")
    return {"success": True, "skill": skill}


@evaluation_router.put("/skills/{skill_id}")
async def update_evaluation_skill(
    skill_id: str,
    request: SkillUpdateRequest,
    http_request: Request,
):
    """使用乐观修订检查更新自定义 Skill"""
    payload = request.model_dump(by_alias=True, exclude_none=True)
    expected_revision = int(payload.pop("expectedRevision"))
    try:
        skill = await asyncio.to_thread(
            update_custom_skill,
            skill_id,
            payload,
            expected_revision,
            skill_actor_from_request(http_request),
        )
    except SkillCatalogError as exc:
        _raise_skill_http_error(exc)
    return {"success": True, "skill": skill}


@evaluation_router.delete("/skills/{skill_id}")
async def delete_evaluation_skill(
    skill_id: str,
    request: Request,
    expectedRevision: int = Query(ge=1),
):
    """删除自定义 Skill；内置 Skill 为永久只读"""
    try:
        skill = await asyncio.to_thread(
            delete_custom_skill,
            skill_id,
            expectedRevision,
            skill_actor_from_request(request),
        )
    except SkillCatalogError as exc:
        _raise_skill_http_error(exc)
    return {"success": True, "skill": skill}


# ========== 指标查询端点（由 indicator-service 确认查询后调用） ==========

class IndicatorQueryRequest(BaseModel):
    question: str
    database_id: str
    database_name: str = ""
    indicator_defs: list = Field(default_factory=list)
    analysis_plan: str = ""


@evaluation_router.post("/indicator-query/stream")
async def indicator_query_stream(request: IndicatorQueryRequest):
    """
    指标查询流式端点 — 由 indicator-service 在用户确认查询后调用。

    复用评估分析的数据探索 → 表选择 → SQL 生成 → SQL 执行 → 分析管线，
    但不经过编排器意图识别。
    """
    from agents.indicator_query import run_indicator_query

    logger.info(f"指标查询流: 问题={request.question[:80]}, 数据库={request.database_id}, "
                f"指标数={len(request.indicator_defs)}")

    async def generate():
        try:
            async for event in run_indicator_query(
                question=request.question,
                database_id=request.database_id,
                database_name=request.database_name,
                indicator_defs=request.indicator_defs,
                analysis_plan=request.analysis_plan,
                llm_call_fn=async_llm_call,
                stream_llm_gen=async_gen_llm_stream,
            ):
                yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
        except Exception as e:
            logger.error(f"指标查询流错误: {e}", exc_info=True)
            yield json.dumps({
                "type": "error",
                "message": f"查询异常: {str(e)[:500]}",
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
        databases = await asyncio.to_thread(fetch_all_databases)
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
        logger.error(f"加载数据源失败: {e}")
        return {"success": False, "message": str(e), "databases": [], "dataSources": []}


@evaluation_router.get("/data-sources/{database_id}/datasets")
async def get_data_source_datasets(database_id: str):
    """返回经服务端验证的数据集选项，供自定义 Skill 编辑器使用。"""
    from agents.tools import fetch_skill_datasets_for_database

    try:
        datasets = await asyncio.to_thread(
            fetch_skill_datasets_for_database, database_id, True, False
        )
    except Exception as exc:
        logger.error("加载自定义 Skill 编辑器的数据集失败: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    return {
        "success": True,
        "datasets": [
            {
                "id": str(dataset.get("id", "")),
                "name": str(dataset.get("name", "")),
                "tableName": str(dataset.get("tableName", "")),
                "description": str(dataset.get("description", "")),
            }
            for dataset in datasets
            if dataset.get("id") and dataset.get("tableName")
        ],
    }


@evaluation_router.get("/history")
async def get_history():
    """获取历史记录列表"""
    with _write_lock:
        history = copy.deepcopy(_eval_history)
    return {"success": True, "history": history}


@evaluation_router.get("/session/{session_id}")
async def get_session(session_id: str):
    """获取指定会话"""
    with _write_lock:
        session = copy.deepcopy(_eval_sessions.get(session_id))
    if session:
        return {"success": True, "session": session}
    return {"success": False, "message": "会话不存在"}


@evaluation_router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    loop = asyncio.get_running_loop()
    existed = await loop.run_in_executor(_io_pool, _delete_session_from_file, session_id)
    return {"success": True, "message": "已删除" if existed else "会话不存在"}
