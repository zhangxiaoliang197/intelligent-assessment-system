"""HTTP surface for governed Skill operations and runtime observability.

The original evaluation endpoints remain intentionally small and backwards
compatible.  This router contains the platform capabilities that need an actor
context or durable run id, keeping those concerns out of the generic workflow
API.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agents.skill_catalog import (
    SkillCatalogError,
    SkillConflictError,
    SkillNotFoundError,
    SkillPermissionError,
    SkillReadOnlyError,
    SkillStoreUnavailableError,
    create_skill_from_template,
    create_skill_share,
    duplicate_skill,
    export_skill,
    get_skill,
    import_skill_definitions,
    list_skill_shares,
    list_skill_versions,
    publish_custom_skill,
    resolve_skill_share,
    revoke_skill_share,
    rollback_custom_skill,
    set_skill_favorite,
)
from agents.skill_governance import SkillActor
from agents.skill_ai_service import SkillAiDraftError, generate_skill_draft
from agents.skill_quality_service import (
    evaluate_execution_quality,
    get_skill_operations_overview,
)
from agents.skill_runner import (
    cancel_skill_run,
    get_skill_execution,
    list_skill_executions,
    preflight_skill_execution,
    run_skill_step_trial,
)
from agents.skill_runtime_service import (
    cancel_skill_batch,
    compare_skill_executions,
    create_skill_schedule,
    delete_skill_schedule,
    get_skill_batch,
    get_skill_schedule,
    list_skill_batches,
    list_skill_schedules,
    poll_and_run_due_schedules,
    run_skill_batch,
    update_skill_schedule,
)


skill_api_router = APIRouter(prefix="/evaluation", tags=["评估 Skills"])
logger = logging.getLogger("evaluation.skill_api")
_background_tasks: set[asyncio.Task] = set()
_scheduler_task: asyncio.Task | None = None


def skill_actor_from_request(request: Request) -> SkillActor:
    """Build the Skill principal supplied by the trusted application gateway.

    Local deployments historically had no identity provider.  They retain the
    ``local-admin`` principal so existing Skills stay manageable; deployments
    behind SSO should replace/overwrite these headers at the gateway boundary.
    """

    user_id = (request.headers.get("x-user-id") or "local-admin").strip()
    role = (request.headers.get("x-user-role") or "admin").strip().lower()
    raw_team_ids = request.headers.get("x-team-ids") or ""
    team_ids = tuple(
        item.strip() for item in raw_team_ids.split(",") if item.strip()
    )
    return SkillActor(user_id=user_id or "local-admin", role=role or "viewer", team_ids=team_ids)


def _require_skill(skill_id: str, actor: SkillActor) -> dict[str, Any]:
    skill = get_skill(skill_id, actor)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill 不存在或当前用户无权访问: {skill_id}")
    return skill


def _raise_catalog_error(exc: SkillCatalogError) -> None:
    if isinstance(exc, SkillStoreUnavailableError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (SkillPermissionError, SkillReadOnlyError)):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, SkillNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, SkillConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _ensure_execution_access(execution: dict[str, Any], actor: SkillActor) -> None:
    owner = str(execution.get("actorId") or "")
    if owner and owner != actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前用户无权访问该 Skill 执行记录")


def _public_execution(execution: dict[str, Any]) -> dict[str, Any]:
    item = dict(execution)
    steps = []
    for stored in item.get("steps", []) or []:
        event = stored.get("event") if isinstance(stored.get("event"), dict) else {}
        step = event.get("step") if isinstance(event.get("step"), dict) else {}
        steps.append({**stored, **step})
    total = int(item.get("totalSteps") or 0)
    completed = int(item.get("completedSteps") or 0)
    status = str(item.get("status") or "")
    item.update(
        {
            "id": item.get("runId", ""),
            "skillVersion": item.get("skillRevision", 0),
            "type": item.get("trigger", "interactive"),
            "query": item.get("question", ""),
            "dataSourceId": item.get("databaseId", ""),
            "createdBy": item.get("actorId", ""),
            "createdAt": item.get("startedAt"),
            "progress": 100
            if status in {"completed", "partial", "error", "cancelled", "timed_out"}
            else round(completed / total * 100)
            if total
            else 0,
            "steps": steps,
        }
    )
    return item


def _public_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    return {
        **schedule,
        "id": schedule.get("scheduleId", ""),
        "query": schedule.get("question", ""),
        "dataSourceId": schedule.get("databaseId", ""),
    }


def _public_batch(batch: dict[str, Any]) -> dict[str, Any]:
    raw_items = batch.get("items", []) or []
    first_request = (
        raw_items[0].get("request", {})
        if raw_items and isinstance(raw_items[0].get("request"), dict)
        else {}
    )
    items = []
    for stored in raw_items:
        request = stored.get("request") if isinstance(stored.get("request"), dict) else {}
        items.append(
            {
                **stored,
                "id": f"{batch.get('batchId', '')}-{stored.get('index', 0)}",
                "query": request.get("query") or request.get("question") or "",
            }
        )
    return {
        **batch,
        "id": batch.get("batchId", ""),
        "skillId": first_request.get("skillId", ""),
        "dataSourceId": first_request.get("dataSourceId")
        or first_request.get("databaseId")
        or "",
        "total": int(batch.get("totalItems") or len(items)),
        "completed": int(batch.get("completedItems") or 0),
        "failed": int(batch.get("failedItems") or 0),
        "items": items,
    }


def _spawn(coroutine) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    _background_tasks.add(task)

    def finish(completed: asyncio.Task) -> None:
        _background_tasks.discard(completed)
        if completed.cancelled():
            return
        try:
            completed.result()
        except Exception:
            logger.exception("Background Skill task failed")

    task.add_done_callback(finish)
    return task


class SkillPreflightRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    skill_id: str = Field(default="", alias="skillId")
    database_id: str = Field(default="", alias="dataSourceId")
    database_name: str = Field(default="", alias="databaseName")
    include_schema: bool = Field(default=True, alias="includeSchema")


class SkillTrialRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    skill_id: str = Field(default="", max_length=128, alias="skillId")
    query: str = Field(min_length=1, max_length=4000)
    database_id: str = Field(min_length=1, max_length=128, alias="dataSourceId")
    database_name: str = Field(default="", max_length=160, alias="databaseName")
    step_id: str = Field(default="", max_length=64, alias="stepId")
    step_sequence: Optional[int] = Field(default=None, ge=1, le=12, alias="stepSequence")
    session_id: str = Field(default="", max_length=128, alias="sessionId")
    variables: dict[str, Any] = Field(default_factory=dict)


class RevisionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    expected_revision: Optional[int] = Field(default=None, ge=1, alias="expectedRevision")
    change_note: str = Field(default="", max_length=500, alias="changeNote")


class RollbackRequest(RevisionRequest):
    version: int = Field(ge=1)


class CloneSkillRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(default="", max_length=80)
    as_template: bool = Field(default=False, alias="asTemplate")
    visibility: Optional[str] = Field(default=None, pattern="^(private|team|public)$")
    team_id: str = Field(default="", max_length=128, alias="teamId")


class ShareSkillRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    expires_at: str = Field(default="", alias="expiresAt")
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=365, alias="expiresInDays")
    visibility: Optional[str] = Field(default=None, pattern="^(private|team|public)$")


class ImportSkillsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    document: Any
    conflict_policy: str = Field(default="copy", alias="conflictPolicy")


class SkillScheduleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    skill_id: str = Field(min_length=1, max_length=128, alias="skillId")
    name: str = Field(min_length=1, max_length=160)
    cron: str = Field(min_length=5, max_length=100)
    timezone: str = Field(default="Asia/Shanghai", max_length=80)
    enabled: bool = True
    query: str = Field(min_length=1, max_length=4000)
    database_id: str = Field(min_length=1, max_length=128, alias="dataSourceId")
    database_name: str = Field(default="", max_length=160, alias="databaseName")


class SkillScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    skill_id: Optional[str] = Field(default=None, min_length=1, max_length=128, alias="skillId")
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    cron: Optional[str] = Field(default=None, min_length=5, max_length=100)
    timezone: Optional[str] = Field(default=None, max_length=80)
    enabled: Optional[bool] = None
    query: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    database_id: Optional[str] = Field(default=None, min_length=1, max_length=128, alias="dataSourceId")
    database_name: Optional[str] = Field(default=None, max_length=160, alias="databaseName")


class SkillBatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    skill_id: str = Field(min_length=1, max_length=128, alias="skillId")
    name: str = Field(default="", max_length=160)
    database_id: str = Field(min_length=1, max_length=128, alias="dataSourceId")
    database_name: str = Field(default="", max_length=160, alias="databaseName")
    queries: list[str] = Field(min_length=1, max_length=100)
    max_concurrency: int = Field(default=2, ge=1, le=8, alias="maxConcurrency")


class CompareExecutionsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    run_ids: list[str] = Field(min_length=2, max_length=20, alias="runIds")
    baseline_run_id: Optional[str] = Field(default=None, alias="baselineRunId")


class SkillAiDraftRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    requirement: str = Field(min_length=5, max_length=4000)
    database_id: str = Field(default="", max_length=128, alias="dataSourceId")
    max_steps: int = Field(default=6, ge=1, le=12, alias="maxSteps")


class SkillQualityEvaluateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    run_id: str = Field(min_length=1, max_length=128, alias="runId")
    expected_keywords: list[str] = Field(
        default_factory=list, max_length=30, alias="expectedKeywords"
    )


@skill_api_router.post("/skills/ai-draft")
async def create_ai_skill_draft(payload: SkillAiDraftRequest, request: Request):
    """Generate an editable private draft; normal create/publish governance still applies."""
    skill_actor_from_request(request)
    datasets: list[dict[str, Any]] = []
    if payload.database_id:
        try:
            from agents.tools import fetch_skill_datasets_for_database

            datasets = await asyncio.to_thread(
                fetch_skill_datasets_for_database, payload.database_id, True, True
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"读取数据源失败: {exc}") from exc
    try:
        from evaluation_api import async_llm_call

        draft = await generate_skill_draft(
            requirement=payload.requirement,
            datasets=datasets,
            llm_call_fn=async_llm_call,
            max_steps=payload.max_steps,
        )
    except SkillAiDraftError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "success": True,
        "draft": draft,
        "dataContext": draft.get("dataContext", {}),
    }


@skill_api_router.post("/quality/evaluate")
async def evaluate_skill_quality(
    payload: SkillQualityEvaluateRequest,
    request: Request,
):
    actor = skill_actor_from_request(request)
    execution = get_skill_execution(payload.run_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Skill 执行记录不存在")
    _ensure_execution_access(execution, actor)
    try:
        report = await asyncio.to_thread(
            evaluate_execution_quality,
            payload.run_id,
            expected_keywords=payload.expected_keywords,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "report": report, **report}


@skill_api_router.get("/quality/overview")
async def get_quality_overview(
    request: Request,
    skillId: str = "",
    days: int = Query(default=30, ge=1, le=365),
):
    actor = skill_actor_from_request(request)
    if skillId:
        _require_skill(skillId, actor)
    overview = await asyncio.to_thread(
        get_skill_operations_overview,
        skill_id=skillId,
        actor_id="" if actor.is_admin else actor.user_id,
        days=days,
    )
    return {"success": True, "overview": overview, **overview}


@skill_api_router.put("/skills/{skill_id}/favorite")
async def favorite_skill(skill_id: str, request: Request):
    actor = skill_actor_from_request(request)
    try:
        result = set_skill_favorite(skill_id, True, actor)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, **result}


@skill_api_router.delete("/skills/{skill_id}/favorite")
async def unfavorite_skill(skill_id: str, request: Request):
    actor = skill_actor_from_request(request)
    try:
        result = set_skill_favorite(skill_id, False, actor)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, **result}


@skill_api_router.get("/skills/{skill_id}/versions")
async def get_skill_versions(skill_id: str, request: Request):
    actor = skill_actor_from_request(request)
    try:
        versions = list_skill_versions(skill_id, actor)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "versions": versions, "total": len(versions)}


@skill_api_router.post("/skills/{skill_id}/publish")
async def publish_skill(skill_id: str, payload: RevisionRequest, request: Request):
    actor = skill_actor_from_request(request)
    current = _require_skill(skill_id, actor)
    revision = payload.expected_revision or int(current.get("revision") or 1)
    try:
        skill = publish_custom_skill(
            skill_id,
            revision,
            actor,
            change_note=payload.change_note,
        )
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "skill": skill}


@skill_api_router.post("/skills/{skill_id}/rollback")
async def rollback_skill(skill_id: str, payload: RollbackRequest, request: Request):
    actor = skill_actor_from_request(request)
    current = _require_skill(skill_id, actor)
    revision = payload.expected_revision or int(current.get("revision") or 1)
    try:
        skill = rollback_custom_skill(
            skill_id,
            payload.version,
            revision,
            actor,
            change_note=payload.change_note,
        )
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "skill": skill}


@skill_api_router.post("/skills/{skill_id}/clone", status_code=201)
async def clone_skill(skill_id: str, payload: CloneSkillRequest, request: Request):
    actor = skill_actor_from_request(request)
    overrides: dict[str, Any] = {}
    if payload.name:
        overrides["name"] = payload.name
    if payload.visibility:
        overrides["visibility"] = payload.visibility
    if payload.team_id:
        overrides["teamId"] = payload.team_id
    try:
        source = _require_skill(skill_id, actor)
        if source.get("isTemplate") and not payload.as_template:
            skill = create_skill_from_template(skill_id, overrides, actor)
        else:
            skill = duplicate_skill(
                skill_id,
                overrides,
                actor,
                as_template=payload.as_template,
            )
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "skill": skill}


@skill_api_router.post("/skills/{skill_id}/share", status_code=201)
async def share_skill(skill_id: str, payload: ShareSkillRequest, request: Request):
    actor = skill_actor_from_request(request)
    expires_at = payload.expires_at
    if not expires_at and payload.expires_in_days:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        share = create_skill_share(skill_id, actor, expires_at=expires_at)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    token = share.get("token", "")
    share = {
        **share,
        "id": share.get("id") or token,
        "url": f"/api/evaluation/shared-skills/{token}",
        "visibility": payload.visibility or "private",
    }
    return {"success": True, "share": share, **share}


@skill_api_router.get("/skills/{skill_id}/shares")
async def get_skill_shares(skill_id: str, request: Request):
    actor = skill_actor_from_request(request)
    try:
        shares = list_skill_shares(skill_id, actor)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "shares": shares, "total": len(shares)}


@skill_api_router.delete("/skills/shares/{token}")
async def revoke_share(token: str, request: Request):
    actor = skill_actor_from_request(request)
    try:
        share = revoke_skill_share(token, actor)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "share": share}


@skill_api_router.get("/shared-skills/{token}")
async def get_shared_skill(token: str):
    try:
        share = resolve_skill_share(token)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, **share}


@skill_api_router.get("/skills/{skill_id}/export")
async def export_one_skill(skill_id: str, request: Request):
    actor = skill_actor_from_request(request)
    try:
        document = export_skill(skill_id, actor)
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    return {"success": True, "document": document, **document}


@skill_api_router.post("/skills/import", status_code=201)
async def import_skills(payload: ImportSkillsRequest, request: Request):
    actor = skill_actor_from_request(request)
    policy_map = {"copy": "rename", "rename": "rename", "skip": "skip", "error": "error"}
    policy = policy_map.get(payload.conflict_policy.strip().lower())
    if not policy:
        raise HTTPException(
            status_code=400,
            detail="conflictPolicy 仅支持 copy、rename、skip 或 error",
        )
    try:
        result = import_skill_definitions(
            payload.document,
            actor,
            conflict_policy=policy,
        )
    except SkillCatalogError as exc:
        _raise_catalog_error(exc)
    created = result.get("created", [])
    skipped = result.get("skipped", [])
    return {
        "success": True,
        "imported": len(created),
        "skipped": len(skipped),
        "skills": created,
        "warnings": [item.get("reason", "") for item in skipped if item.get("reason")],
    }


@skill_api_router.post("/skills/{skill_id}/preflight")
async def preflight_skill(
    skill_id: str,
    payload: SkillPreflightRequest,
    request: Request,
):
    actor = skill_actor_from_request(request)
    skill = _require_skill(skill_id, actor)
    result = await preflight_skill_execution(
        database_id=payload.database_id,
        database_name=payload.database_name,
        skill=skill,
        include_schema=payload.include_schema,
    )
    # Both names are returned for old clients and the richer management UI.
    result["runnable"] = bool(result.get("ready") or result.get("runtimeSelectable"))
    result["dataSourceId"] = result.get("databaseId", payload.database_id)
    return {"success": True, "preflight": result, **result}


@skill_api_router.post("/skills/{skill_id}/trial")
async def trial_skill_step(
    skill_id: str,
    payload: SkillTrialRequest,
    request: Request,
):
    actor = skill_actor_from_request(request)
    skill = _require_skill(skill_id, actor)
    if not payload.step_id and payload.step_sequence is None:
        raise HTTPException(status_code=422, detail="请提供 stepId 或 stepSequence")
    try:
        # Imported lazily to avoid a module cycle while evaluation_api registers
        # its original streaming router.
        from evaluation_api import async_llm_call

        result = await run_skill_step_trial(
            question=payload.query,
            database_id=payload.database_id,
            database_name=payload.database_name,
            skill=skill,
            llm_call_fn=async_llm_call,
            step_id=payload.step_id,
            step_sequence=payload.step_sequence,
            actor_id=actor.user_id,
            session_id=payload.session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    execution = get_skill_execution(str(result.get("runId") or "")) or {}
    public_execution = _public_execution(execution) if execution else {
        "id": result.get("runId", ""),
        "runId": result.get("runId", ""),
        "skillId": result.get("skillId", skill_id),
        "status": result.get("status", "error"),
        "type": "trial",
        "steps": [result.get("stepResult")] if result.get("stepResult") else [],
        "durationMs": result.get("durationMs", 0),
        "progress": 100,
    }
    return {
        "success": True,
        "trial": result,
        "execution": public_execution,
        **result,
    }


@skill_api_router.get("/executions")
async def get_skill_executions(
    request: Request,
    skillId: str = "",
    status: str = "",
    batchId: str = "",
    scheduleId: str = "",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=30, ge=1, le=200),
):
    actor = skill_actor_from_request(request)
    catalog = list_skill_executions(
        skill_id=skillId,
        actor_id="" if actor.is_admin else actor.user_id,
        status=status,
        batch_id=batchId,
        schedule_id=scheduleId,
        limit=pageSize,
        offset=(page - 1) * pageSize,
    )
    return {
        "success": True,
        "page": page,
        "pageSize": pageSize,
        **catalog,
        "items": [_public_execution(item) for item in catalog.get("items", [])],
    }


@skill_api_router.get("/executions/{run_id}")
async def get_skill_execution_detail(run_id: str, request: Request):
    actor = skill_actor_from_request(request)
    execution = get_skill_execution(run_id)
    if not execution:
        raise HTTPException(status_code=404, detail=f"Skill 执行记录不存在: {run_id}")
    _ensure_execution_access(execution, actor)
    return {"success": True, "execution": _public_execution(execution)}


@skill_api_router.post("/executions/{run_id}/cancel")
async def cancel_skill_execution(run_id: str, request: Request):
    actor = skill_actor_from_request(request)
    execution = get_skill_execution(run_id)
    if execution:
        _ensure_execution_access(execution, actor)
    result = cancel_skill_run(run_id, requested_by=actor.user_id)
    if result.get("status") == "not_running" and not execution:
        raise HTTPException(status_code=404, detail=result.get("message", "运行不存在"))
    return {"success": True, **result}


@skill_api_router.post("/executions/compare")
async def compare_executions(payload: CompareExecutionsRequest, request: Request):
    actor = skill_actor_from_request(request)
    for run_id in payload.run_ids:
        execution = get_skill_execution(run_id)
        if not execution:
            raise HTTPException(status_code=404, detail=f"Skill 执行记录不存在: {run_id}")
        _ensure_execution_access(execution, actor)
    try:
        comparison = compare_skill_executions(
            payload.run_ids,
            baseline_run_id=payload.baseline_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metric_names = comparison.get("metrics", [])
    rows = comparison.get("rows", [])
    items = [
        {
            **row,
            "summary": row.get("finalAnswer", ""),
            "metrics": {name: row.get(name) for name in metric_names},
        }
        for row in rows
    ]
    return {
        "success": True,
        **comparison,
        "metricNames": metric_names,
        "items": items,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


@skill_api_router.get("/schedules")
async def get_schedules(
    request: Request,
    skillId: str = "",
    enabled: Optional[bool] = None,
):
    actor = skill_actor_from_request(request)
    catalog = list_skill_schedules(
        created_by="" if actor.is_admin else actor.user_id,
        enabled=enabled,
    )
    items = [_public_schedule(item) for item in catalog.get("items", [])]
    if skillId:
        items = [item for item in items if item.get("skillId") == skillId]
    return {"success": True, **catalog, "items": items, "schedules": items, "total": len(items)}


@skill_api_router.post("/schedules", status_code=201)
async def create_schedule(payload: SkillScheduleRequest, request: Request):
    actor = skill_actor_from_request(request)
    _require_skill(payload.skill_id, actor)
    try:
        schedule = create_skill_schedule(
            {
                "skillId": payload.skill_id,
                "name": payload.name,
                "cron": payload.cron,
                "timezone": payload.timezone,
                "enabled": payload.enabled,
                "question": payload.query,
                "databaseId": payload.database_id,
                "databaseName": payload.database_name,
            },
            created_by=actor.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    public = _public_schedule(schedule)
    return {"success": True, "schedule": public, **public}


@skill_api_router.get("/schedules/{schedule_id}")
async def get_schedule_detail(schedule_id: str, request: Request):
    actor = skill_actor_from_request(request)
    schedule = get_skill_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if schedule.get("createdBy") != actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前用户无权访问该定时任务")
    public = _public_schedule(schedule)
    return {"success": True, "schedule": public, **public}


@skill_api_router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    payload: SkillScheduleUpdateRequest,
    request: Request,
):
    actor = skill_actor_from_request(request)
    current = get_skill_schedule(schedule_id)
    if not current:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if current.get("createdBy") != actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前用户无权修改该定时任务")
    raw = payload.model_dump(by_alias=True, exclude_none=True)
    changes = {
        {
            "skillId": "skillId",
            "name": "name",
            "cron": "cron",
            "timezone": "timezone",
            "enabled": "enabled",
            "query": "question",
            "dataSourceId": "databaseId",
            "databaseName": "databaseName",
        }[key]: value
        for key, value in raw.items()
    }
    if "skillId" in changes:
        _require_skill(str(changes["skillId"]), actor)
    try:
        schedule = update_skill_schedule(schedule_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    public = _public_schedule(schedule)
    return {"success": True, "schedule": public, **public}


@skill_api_router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request):
    actor = skill_actor_from_request(request)
    schedule = get_skill_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="定时任务不存在")
    if schedule.get("createdBy") != actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前用户无权删除该定时任务")
    deleted = delete_skill_schedule(schedule_id)
    return {"success": True, "deleted": deleted, "scheduleId": schedule_id}


@skill_api_router.get("/batches")
async def get_batches(request: Request, skillId: str = ""):
    actor = skill_actor_from_request(request)
    catalog = list_skill_batches(actor_id="" if actor.is_admin else actor.user_id)
    items = [_public_batch(item) for item in catalog.get("items", []) if item]
    if skillId:
        items = [item for item in items if item.get("skillId") == skillId]
    return {"success": True, **catalog, "items": items, "batches": items, "total": len(items)}


@skill_api_router.post("/batches", status_code=202)
async def create_batch_evaluation(payload: SkillBatchRequest, request: Request):
    actor = skill_actor_from_request(request)
    skill = _require_skill(payload.skill_id, actor)
    batch_id = str(uuid.uuid4())
    items = [
        {
            "skillId": payload.skill_id,
            "query": query.strip(),
            "dataSourceId": payload.database_id,
            "databaseName": payload.database_name,
        }
        for query in payload.queries
        if query.strip()
    ]
    if not items:
        raise HTTPException(status_code=422, detail="批量评估至少需要一个非空问题")
    from evaluation_api import async_llm_call

    _spawn(
        run_skill_batch(
            items=items,
            skill_resolver=lambda skill_id: skill if skill_id == skill["id"] else get_skill(skill_id, actor),
            llm_call_fn=async_llm_call,
            actor_id=actor.user_id,
            name=payload.name,
            batch_id=batch_id,
            max_concurrency=payload.max_concurrency,
        )
    )
    queued = {
        "id": batch_id,
        "batchId": batch_id,
        "skillId": payload.skill_id,
        "name": payload.name or f"批量评估-{batch_id[:8]}",
        "dataSourceId": payload.database_id,
        "status": "queued",
        "total": len(items),
        "completed": 0,
        "failed": 0,
        "items": [
            {"id": f"{batch_id}-{index}", "query": item["query"], "status": "queued"}
            for index, item in enumerate(items)
        ],
    }
    return {"success": True, "batch": queued, **queued}


@skill_api_router.get("/batches/{batch_id}")
async def get_batch_detail(batch_id: str, request: Request):
    actor = skill_actor_from_request(request)
    batch = get_skill_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批量评估不存在")
    if batch.get("actorId") != actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前用户无权访问该批量评估")
    public = _public_batch(batch)
    return {"success": True, "batch": public, **public}


@skill_api_router.post("/batches/{batch_id}/cancel")
async def cancel_batch(batch_id: str, request: Request):
    actor = skill_actor_from_request(request)
    batch = get_skill_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="批量评估不存在")
    if batch.get("actorId") != actor.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前用户无权取消该批量评估")
    result = cancel_skill_batch(batch_id, requested_by=actor.user_id)
    return {"success": True, **result}


async def _schedule_loop() -> None:
    from evaluation_api import async_llm_call

    while True:
        try:
            await poll_and_run_due_schedules(
                skill_resolver=lambda skill_id: get_skill(skill_id),
                llm_call_fn=async_llm_call,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to poll scheduled Skill executions")
        await asyncio.sleep(30)


@skill_api_router.on_event("startup")
async def start_skill_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = _spawn(_schedule_loop())


@skill_api_router.on_event("shutdown")
async def stop_skill_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        await asyncio.gather(_scheduler_task, return_exceptions=True)
    _scheduler_task = None
