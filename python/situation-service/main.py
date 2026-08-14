"""态势图服务（situation-service）入口。

独立于本体模型与向量库（ADR-01/05），负责态势产物的生成编排、流式推送、
产物聚合与跨功能草稿态。持久化经 admin-service，不直连 DB（ADR-11）。

路由总览（详见 docs/situation-map/04-接口契约.md）：
  GET  /situation/health                  健康检查
  POST /situation/draft                   创建草稿态（跨功能跳转入口）
  GET  /situation/draft/{draftId}         读取草稿态
  POST /situation/generate                发起生成（立即返回 reportId + streamUrl）
  GET  /situation/skills                  态势图 Skill 目录（搜索/分类）
  POST /situation/skills/recommend        根据问题推荐 Skill
  POST /situation/skills/{skillId}/apply  预执行并返回编排计划
  GET  /situation/stream/{reportId}       SSE 流式接收（agent 中间结果）
  POST /situation/refresh/{reportId}      主动刷新一次 tick
  GET  /situation/reports                 产物列表（透传 admin-service）
  GET  /situation/reports/{reportId}      产物详情
  DELETE /situation/reports/{reportId}    删除产物
  POST /situation/reports/{reportId}/share  生成分享 token
  GET  /situation/share/{token}           公开查看（分享，无需登录）

生成默认走真实数据 + LLM 编排；mock 仅能通过环境变量显式启用。
"""

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import asyncio
import json
import logging
import time
import uuid
import hashlib
import hmac
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from logging_config import setup_logging
setup_logging("situation-service")
logger = logging.getLogger("situation-service")

import config
from models import (
    DraftRequest,
    GenerateRequest,
    Report,
    SkillApplyRequest,
    SkillFavoriteRequest,
    SkillMarkdownUpdateRequest,
    SkillPublishRequest,
    SkillRecommendRequest,
    SkillRollbackRequest,
    SkillUpsertRequest,
)
from stream.sse import format_event, sse_response
from agent.orchestrator import generate
from skills import (
    SkillCatalogError,
    archive_skill_definition,
    build_skill_context,
    catalog_summary,
    create_skill_definition,
    get_skill,
    list_skill_versions,
    list_skills as list_situation_skills,
    preflight_skill,
    publish_skill_definition,
    recommend_skills,
    rollback_skill_definition,
    update_skill_definition,
)
from skills.store import (
    SkillStoreError,
    finish_usage,
    list_favorite_ids,
    list_usage,
    set_favorite,
    start_usage,
    usage_stats,
)
from skills.markdown import get_skill_markdown, update_skill_markdown
from store import admin_client, draft as draft_store

app = FastAPI(
    title="态势图服务",
    description="综合态势感知：LLM 编排多源数据，流式生成统计图表 + 地图 + 态势介绍",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.SITUATION_CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID",
        "X-User-Id", "X-Team-Ids", "X-User-Role", "X-Actor-Signature",
    ],
)


# ──────────────────────────────────────────────────────────
# 辅助：统一响应封装
# ──────────────────────────────────────────────────────────
def _ok(data: dict, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}


def _fail(message: str, data: dict = None) -> dict:
    return {"success": False, "message": message, "data": data or {}}


def _gen_report_id() -> str:
    """生成 reportId：r_{yyyymmdd}_{8位uuid}"""
    today = time.strftime("%Y%m%d")
    return f"r_{today}_{uuid.uuid4().hex[:8]}"


def _read_headers(request: Request) -> tuple:
    """从请求头读取用户身份（skill governance 约定）。"""
    actor = _actor(request)
    return actor["userId"], actor["teamIds"]


def _actor(request: Request) -> dict:
    user_id = request.headers.get("X-User-Id", "").strip() or "local-admin"
    team_ids_raw = request.headers.get("X-Team-Ids", "")
    team_ids = [item.strip() for item in team_ids_raw.split(",") if item.strip()]
    role = request.headers.get("X-User-Role", "admin").strip().lower() or "admin"
    signature = request.headers.get("X-Actor-Signature", "").strip()
    actor_payload = f"{user_id}|{','.join(team_ids)}|{role}".encode("utf-8")
    expected = hmac.new(
        config.INTERNAL_SERVICE_TOKEN.encode("utf-8"), actor_payload, hashlib.sha256,
    ).hexdigest()
    trusted = bool(signature) and hmac.compare_digest(signature, expected)
    if not trusted:
        # 本地开发无网关注入签名时，回退到历史本地身份 local-admin/admin，
        # 以兼容既有历史产物的归属；生产环境应由可信网关注入并 HMAC 签名。
        user_id, team_ids, role = "local-admin", [], "admin"
    return {
        "userId": user_id,
        "teamIds": team_ids,
        "role": role,
        "trusted": trusted,
    }


# ──────────────────────────────────────────────────────────
# 1. 健康检查
# ──────────────────────────────────────────────────────────
@app.get("/situation/health")
def health():
    try:
        usage_stats("__health__")
        skill_storage = "healthy"
    except SkillStoreError as exc:
        logger.error("Skill 持久化健康检查失败: %s", exc)
        skill_storage = "degraded"
    return _ok({
        "status": "healthy" if skill_storage == "healthy" else "degraded",
        "service": "situation-service",
        "port": 10257,
        "skills": catalog_summary()["total"],
        "skillStorage": skill_storage,
    })


# ──────────────────────────────────────────────────────────
# 2. 态势图 Skill 目录 / 推荐 / 预执行
# ──────────────────────────────────────────────────────────
@app.get("/situation/skills")
def get_skill_catalog(
    request: Request,
    query: str = "",
    category: str = "",
    featured: Optional[bool] = None,
    limit: int = 100,
    includeArchived: bool = False,
):
    user_id, _ = _read_headers(request)
    safe_limit = max(1, min(limit, 100))
    all_matches = list_situation_skills(
        query=query,
        category=category,
        featured=featured,
        limit=100,
        user_id=user_id,
        include_archived=includeArchived,
    )
    summary = catalog_summary(user_id)
    return _ok({
        "items": all_matches[:safe_limit],
        "total": len(all_matches),
        "catalogTotal": summary["total"],
        "version": summary["version"],
        "categories": summary["categories"],
    })


@app.post("/situation/skills")
def create_situation_skill(req: SkillUpsertRequest, request: Request):
    user_id, _ = _read_headers(request)
    try:
        skill = create_skill_definition(req.definition, user_id)
    except SkillCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(skill, "Skill 草稿已创建")


@app.get("/situation/skills/categories")
def get_skill_categories(request: Request):
    user_id, _ = _read_headers(request)
    return _ok(catalog_summary(user_id))


@app.get("/situation/skills/favorites")
def get_skill_favorites(request: Request):
    user_id, _ = _read_headers(request)
    try:
        skill_ids = list_favorite_ids(user_id)
    except SkillStoreError as exc:
        raise HTTPException(status_code=503, detail=f"收藏服务暂不可用: {exc}") from exc
    visible_ids = {
        skill["id"] for skill in list_situation_skills(user_id=user_id, limit=100)
    }
    return _ok({"skillIds": [skill_id for skill_id in skill_ids if skill_id in visible_ids]})


@app.get("/situation/skills/usage")
def get_skill_usage(request: Request, limit: int = 20):
    user_id, _ = _read_headers(request)
    try:
        items = list_usage(user_id, limit)
        stats = usage_stats(user_id)
    except SkillStoreError as exc:
        raise HTTPException(status_code=503, detail=f"使用记录服务暂不可用: {exc}") from exc
    return _ok({"items": items, "total": len(items), "stats": stats})


@app.post("/situation/skills/recommend")
def recommend_situation_skills(req: SkillRecommendRequest, request: Request):
    user_id, _ = _read_headers(request)
    try:
        favorite_ids = list_favorite_ids(user_id)
        recent_usage = usage_stats(user_id)
    except SkillStoreError as exc:
        logger.warning("Skill 个性化信息读取失败，回退内容匹配: %s", exc)
        favorite_ids, recent_usage = [], {}
    items = recommend_skills(
        req.query,
        req.limit,
        user_id=user_id,
        favorite_ids=favorite_ids,
        usage=recent_usage,
        context=req.context,
    )
    return _ok({"items": items, "total": len(items), "query": req.query})


@app.post("/situation/skills/{skill_id}/apply")
def apply_situation_skill(skill_id: str, req: SkillApplyRequest, request: Request):
    user_id, _ = _read_headers(request)
    if not get_skill(skill_id, user_id):
        raise HTTPException(status_code=404, detail="态势图 Skill 不存在")
    try:
        context = build_skill_context(skill_id, req.query, req.parameters, user_id=user_id)
    except SkillCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(context, "Skill 编排计划已生成")


@app.post("/situation/skills/{skill_id}/preflight")
def preflight_situation_skill(skill_id: str, req: SkillApplyRequest, request: Request):
    actor = _actor(request)
    user_id = actor["userId"]
    result = preflight_skill(
        skill_id, req.query, req.parameters, user_id=user_id,
        team_ids=actor["teamIds"], role=actor["role"], data_source_id=req.dataSourceId,
    )
    return _ok(result, "执行前检查完成")


@app.get("/situation/skills/{skill_id}/markdown")
def get_situation_skill_markdown(skill_id: str, request: Request):
    actor = _actor(request)
    user_id = actor["userId"]
    try:
        document = get_skill_markdown(skill_id, user_id, is_admin=actor["role"] == "admin")
    except SkillCatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(document)


@app.put("/situation/skills/{skill_id}/markdown")
def update_situation_skill_markdown(
    skill_id: str,
    req: SkillMarkdownUpdateRequest,
    request: Request,
):
    actor = _actor(request)
    user_id = actor["userId"]
    try:
        document = update_skill_markdown(
            skill_id,
            req.content,
            req.expectedHash,
            user_id,
            is_admin=actor["role"] == "admin",
        )
    except SkillCatalogError as exc:
        message = str(exc)
        if "权限" in message or "只有管理员" in message:
            status_code = 403
        elif "已被更新" in message or "当前修订" in message:
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return _ok(document, "SKILL.md 已保存")


@app.put("/situation/skills/{skill_id}")
def update_situation_skill(skill_id: str, req: SkillUpsertRequest, request: Request):
    user_id, _ = _read_headers(request)
    try:
        skill = update_skill_definition(
            skill_id,
            req.definition,
            user_id,
            expected_revision=req.expectedRevision,
        )
    except SkillCatalogError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _ok(skill, "Skill 草稿已更新")


@app.delete("/situation/skills/{skill_id}")
def archive_situation_skill(skill_id: str, request: Request):
    user_id, _ = _read_headers(request)
    try:
        skill = archive_skill_definition(skill_id, user_id)
    except SkillCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(skill, "Skill 已归档")


@app.post("/situation/skills/{skill_id}/publish")
def publish_situation_skill(skill_id: str, req: SkillPublishRequest, request: Request):
    user_id, _ = _read_headers(request)
    try:
        skill = publish_skill_definition(skill_id, user_id, req.changeNote)
    except SkillCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(skill, "Skill 已发布")


@app.get("/situation/skills/{skill_id}/versions")
def get_situation_skill_versions(skill_id: str, request: Request):
    user_id, _ = _read_headers(request)
    try:
        items = list_skill_versions(skill_id, user_id)
    except SkillCatalogError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok({"items": items, "total": len(items)})


@app.post("/situation/skills/{skill_id}/rollback")
def rollback_situation_skill(skill_id: str, req: SkillRollbackRequest, request: Request):
    user_id, _ = _read_headers(request)
    try:
        skill = rollback_skill_definition(skill_id, req.version, user_id)
    except SkillCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _ok(skill, f"Skill 已回滚到版本 {req.version}，请确认后重新发布")


@app.put("/situation/skills/{skill_id}/favorite")
def favorite_situation_skill(skill_id: str, req: SkillFavoriteRequest, request: Request):
    user_id, _ = _read_headers(request)
    if not get_skill(skill_id, user_id):
        raise HTTPException(status_code=404, detail="态势图 Skill 不存在")
    try:
        favorite = set_favorite(user_id, skill_id, req.favorite)
    except SkillStoreError as exc:
        raise HTTPException(status_code=503, detail=f"收藏服务暂不可用: {exc}") from exc
    return _ok({"skillId": skill_id, "favorite": favorite})


@app.get("/situation/skills/{skill_id}")
def get_situation_skill(skill_id: str, request: Request):
    user_id, _ = _read_headers(request)
    skill = get_skill(skill_id, user_id, include_archived=True)
    if not skill:
        raise HTTPException(status_code=404, detail="态势图 Skill 不存在")
    return _ok(skill)


# ──────────────────────────────────────────────────────────
# 3. 草稿态（跨功能跳转入口）
# ──────────────────────────────────────────────────────────
@app.post("/situation/draft")
def create_draft(req: DraftRequest, request: Request):
    actor = _actor(request)
    req.userId, req.teamIds = actor["userId"], actor["teamIds"]
    draft_id = draft_store.create_draft(req)
    logger.info("草稿态已创建: draftId=%s source=%s", draft_id, req.source)
    return _ok({"draftId": draft_id, "expiresIn": config.DRAFT_TTL})


@app.get("/situation/draft/{draft_id}")
def get_draft(draft_id: str, request: Request):
    actor = _actor(request)
    item = draft_store.get_draft(
        draft_id, user_id=actor["userId"], team_ids=actor["teamIds"], role=actor["role"],
    )
    if not item:
        raise HTTPException(status_code=404, detail="草稿不存在或已过期")
    return _ok(item)


# ──────────────────────────────────────────────────────────
# 4. 发起生成
# ──────────────────────────────────────────────────────────
# 生成中的产物暂存（reportId → 聚合中的 Report）
# 单机使用内存；多实例部署时应将会话事件替换为 Redis Stream。
_INFLIGHT: dict = {}
# reportId → Skill 执行上下文。与生成态生命周期一致，完成后释放。
_INFLIGHT_SKILLS: dict = {}


class _GenerationSession:
    """一个 reportId 对应唯一生产任务，所有 SSE 客户端共享事件日志。"""

    def __init__(self, report: Report, skill_context: Optional[dict], context: dict):
        self.report = report
        self.skill_context = skill_context
        self.context = context
        self.events: list[tuple[int, str, dict]] = []
        self.condition = asyncio.Condition()
        self.finished = False
        self.task: Optional[asyncio.Task] = None

    async def publish(self, event_type: str, data: dict) -> None:
        async with self.condition:
            sequence = len(self.events) + 1
            self.events.append((sequence, event_type, data))
            self.condition.notify_all()

    async def finish(self) -> None:
        async with self.condition:
            self.finished = True
            self.condition.notify_all()


_STREAM_SESSIONS: dict[str, _GenerationSession] = {}
_GENERATION_SEMAPHORE = asyncio.Semaphore(config.SITUATION_MAX_CONCURRENT)
_IDEMPOTENCY: dict[str, tuple[float, str, str]] = {}


@app.on_event("shutdown")
async def shutdown_generation_tasks() -> None:
    """Drain active producers on graceful shutdown and persist interrupted terminal state."""
    tasks = [session.task for session in _STREAM_SESSIONS.values() if session.task and not session.task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        try:
            await asyncio.wait(tasks, timeout=10)
        except Exception:
            logger.exception("关闭态势生成任务时发生异常")


async def _cleanup_stream_session(report_id: str, session: _GenerationSession) -> None:
    await asyncio.sleep(config.SITUATION_STREAM_REPLAY_TTL)
    if _STREAM_SESSIONS.get(report_id) is session:
        _STREAM_SESSIONS.pop(report_id, None)


async def _run_generation(report_id: str, session: _GenerationSession) -> None:
    """唯一生产者：聚合、持久化和使用记录均只执行一次。"""
    report = session.report
    terminal_data: Optional[dict] = None
    try:
        async with _GENERATION_SEMAPHORE:
            async with asyncio.timeout(config.SITUATION_GENERATION_TIMEOUT):
                async for event_type, data in generate(
                    report.query, report_id, session.skill_context, session.context,
                ):
                    if event_type == "done":
                        report.status = str(data.get("status") or "ready")
                        terminal_data = data
                        continue
                    _apply_event(report, event_type, data)
                    await session.publish(event_type, data)
    except TimeoutError:
        logger.warning("态势生成超时: reportId=%s", report_id)
        report.status = "failed"
        await session.publish("error", {"stage": "timeout", "message": "生成超过服务端时限", "fatal": True})
        terminal_data = {"reportId": report_id, "status": "failed", "partial": False}
    except asyncio.CancelledError:
        logger.info("态势生成任务已取消: reportId=%s", report_id)
        report.status = "failed"
        await session.publish("error", {"stage": "cancelled", "message": "生成已取消", "fatal": True})
        terminal_data = {"reportId": report_id, "status": "failed", "partial": False, "cancelled": True}
    except Exception as exc:
        logger.exception("生成异常: reportId=%s", report_id)
        report.status = "failed"
        await session.publish("error", {"stage": "llm", "message": str(exc)[:200], "fatal": True})
        terminal_data = {"reportId": report_id, "status": "failed", "partial": False}
    finally:
        if terminal_data is None:
            report.status = "failed"
            terminal_data = {"reportId": report_id, "status": "failed", "partial": False}
        persisted = await asyncio.to_thread(_persist, report)
        if not persisted:
            report.status = "failed"
            terminal_data = {"reportId": report_id, "status": "failed", "partial": False, "persisted": False}
            await session.publish("error", {"stage": "persist", "message": "产物持久化失败", "fatal": True})
        else:
            terminal_data["persisted"] = True
        await session.publish("done", terminal_data)
        await asyncio.to_thread(_finish_skill_usage, report_id, report.status)
        _INFLIGHT.pop(report_id, None)
        _INFLIGHT_SKILLS.pop(report_id, None)
        await session.finish()
        asyncio.create_task(_cleanup_stream_session(report_id, session))
        logger.info("态势生成任务结束并已落库: reportId=%s status=%s", report_id, report.status)


async def _stream_session(session: _GenerationSession, cursor: int = 0):
    """从共享事件日志订阅；供 HTTP SSE 与单元测试复用。"""
    cursor = max(0, cursor)
    while True:
        timed_out = False
        async with session.condition:
            if cursor >= len(session.events) and not session.finished:
                try:
                    await asyncio.wait_for(
                        session.condition.wait_for(
                            lambda: cursor < len(session.events) or session.finished
                        ),
                        timeout=15,
                    )
                except asyncio.TimeoutError:
                    timed_out = True
            batch = session.events[cursor:]
            finished = session.finished
        if timed_out and not batch:
            yield ": keep-alive\n\n"
            continue
        for sequence, event_type, data in batch:
            cursor = sequence
            yield format_event(event_type, data, sequence)
        if finished and cursor >= len(session.events):
            break


@app.post("/situation/generate")
async def generate_report(req: GenerateRequest, request: Request):
    actor = _actor(request)
    user_id, team_ids = actor["userId"], actor["teamIds"]
    # 身份只能来自受信网关注入的请求头，请求体字段仅为旧客户端兼容输入。
    req.userId, req.teamIds = user_id, team_ids
    if len(_INFLIGHT) >= config.SITUATION_MAX_INFLIGHT:
        raise HTTPException(status_code=429, detail="生成队列已满，请稍后重试")
    if sum(1 for report in _INFLIGHT.values() if report.userId == user_id) >= config.SITUATION_MAX_PER_USER:
        raise HTTPException(status_code=429, detail="当前用户在途生成任务已达上限")

    skill_context = None
    skill_preflight = None
    if req.skillId:
        if not get_skill(req.skillId, user_id):
            raise HTTPException(status_code=404, detail="态势图 Skill 不存在")
        skill_preflight = await asyncio.to_thread(
            preflight_skill, req.skillId, req.query, req.skillParameters,
            user_id=user_id, team_ids=team_ids, role=actor["role"], data_source_id=req.dataSourceId,
        )
        if not skill_preflight["ready"]:
            message = "；".join(skill_preflight["errors"]) or "Skill 执行前检查未通过"
            raise HTTPException(status_code=400, detail=message)
        try:
            skill_context = build_skill_context(
                req.skillId,
                req.query,
                skill_preflight["parameters"],
                user_id=user_id,
            )
        except SkillCatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_query = skill_context["query"] if skill_context else req.query.strip()
    idem_key = request.headers.get("Idempotency-Key", "").strip()[:128]
    if idem_key:
        fingerprint = hashlib.sha256(json.dumps({
            "userId": user_id, "query": normalized_query, "source": req.source,
            "skillId": req.skillId, "parameters": req.skillParameters, "context": req.context,
        }, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        previous = _IDEMPOTENCY.get(idem_key)
        if previous and previous[0] > time.time():
            if previous[1] != fingerprint:
                raise HTTPException(status_code=409, detail="幂等键已用于不同生成请求")
            return _ok({"reportId": previous[2], "status": "generating", "streamUrl": f"/situation/stream/{previous[2]}", "reused": True})
        # Bound the in-memory index even when clients continuously create unique keys.
        now = time.time()
        expired = [key for key, value in _IDEMPOTENCY.items() if value[0] <= now]
        for key in expired:
            _IDEMPOTENCY.pop(key, None)
        if len(_IDEMPOTENCY) > 5000:
            for key, _value in sorted(_IDEMPOTENCY.items(), key=lambda item: item[1][0])[:1000]:
                _IDEMPOTENCY.pop(key, None)
    report_id = _gen_report_id()
    # 若带 draftId，合并草稿态上下文
    context = dict(req.context or {})
    if req.draftId:
        d = draft_store.get_draft(
            req.draftId, user_id=user_id, team_ids=team_ids, role=actor["role"], consume=True,
        )
        if not d:
            raise HTTPException(status_code=404, detail="草稿不存在、已过期或无权访问")
        context = {**d.get("context", {}), **context}
        if not req.source or req.source == "manual":
            req.source = d.get("source", "manual")
    if skill_context:
        context["skill"] = skill_context
    context["_actor"] = actor
    context["dataSourceId"] = req.dataSourceId

    report = Report(
        reportId=report_id,
        title=normalized_query[:60] if normalized_query else "态势图",
        query=normalized_query,
        source=req.source,
        skillId=skill_context["skillId"] if skill_context else "",
        skillName=skill_context["skillName"] if skill_context else "",
        skillCategory=skill_context["category"] if skill_context else "",
        skillParameters=skill_context["parameters"] if skill_context else {},
        skillRevision=skill_context.get("revision", 1) if skill_context else 1,
        skillVersion=skill_context.get("version", 1) if skill_context else 1,
        skillContentHash=skill_context.get("contentHash", "") if skill_context else "",
        userId=req.userId,
        teamIds=req.teamIds,
        status="generating",
        dataSourceId=req.dataSourceId,
    )
    # 先持久化 generating 状态再启动后台任务。进程异常退出时仍能审计和恢复，
    # 而不是给客户端一个只存在于当前进程内存中的 reportId。
    if not await asyncio.to_thread(_persist, report):
        raise HTTPException(status_code=503, detail="无法创建持久化生成任务，请稍后重试")
    _INFLIGHT[report_id] = report
    if idem_key:
        _IDEMPOTENCY[idem_key] = (time.time() + config.SITUATION_IDEMPOTENCY_TTL, fingerprint, report_id)
    if skill_context:
        _INFLIGHT_SKILLS[report_id] = skill_context
        try:
            start_usage(report_id, req.userId, skill_context["skillId"], req.query)
        except SkillStoreError as exc:
            logger.warning("Skill 使用记录创建失败: reportId=%s error=%s", report_id, exc)

    session = _GenerationSession(report, skill_context, context)
    _STREAM_SESSIONS[report_id] = session
    session.task = asyncio.create_task(_run_generation(report_id, session))

    logger.info(
        "发起态势生成: reportId=%s query=%s source=%s skillId=%s",
        report_id,
        req.query[:50],
        req.source,
        req.skillId or "auto",
    )
    response = {
        "reportId": report_id,
        "status": "generating",
        "streamUrl": f"/situation/stream/{report_id}",
    }
    if skill_context:
        response["skill"] = {
            "id": skill_context["skillId"],
            "name": skill_context["skillName"],
            "category": skill_context["category"],
            "executionPlan": skill_context["executionPlan"],
            "parameters": skill_context["parameters"],
            "preflight": {
                "complete": skill_preflight["complete"],
                "warnings": skill_preflight["warnings"],
            },
        }
    return _ok(response)


# ──────────────────────────────────────────────────────────
# 5. SSE 流式接收
# ──────────────────────────────────────────────────────────
@app.get("/situation/stream/{report_id}")
async def stream_report(report_id: str, request: Request):
    """订阅单一生成任务；断线按 Last-Event-ID 回放，绝不重新执行生成。"""
    session = _STREAM_SESSIONS.get(report_id)
    actor = _actor(request)
    if not session:
        # 不在内存中：可能是已完成的历史产物，回查 admin-service
        resp = await asyncio.to_thread(admin_client.get_report, report_id, actor)
        if resp.get("success"):
            detail = resp.get("data") or resp
            saved_status = str(detail.get("status") or (detail.get("snapshot") or {}).get("status") or "failed")
            # 已有产物，立即推 done 事件
            async def _replay():
                yield format_event("done", {"reportId": report_id, "status": saved_status, "partial": saved_status == "partial", "persisted": True}, 1)
            return sse_response(_replay())
        raise HTTPException(status_code=404, detail="reportId 不存在")

    if session.report.userId != actor["userId"] and not set(session.report.teamIds).intersection(actor["teamIds"]) and actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权订阅该产物")
    try:
        cursor = max(0, int(request.headers.get("Last-Event-ID", "0") or "0"))
    except ValueError:
        cursor = 0

    return sse_response(_stream_session(session, cursor))


@app.delete("/situation/generate/{report_id}")
async def cancel_generation(report_id: str, request: Request):
    session = _STREAM_SESSIONS.get(report_id)
    if not session or session.finished:
        raise HTTPException(status_code=404, detail="生成任务不存在或已结束")
    actor = _actor(request)
    if session.report.userId != actor["userId"] and actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权取消该任务")
    if session.task:
        session.task.cancel()
    return _ok({"reportId": report_id, "status": "cancelling"})


@app.post("/situation/cancel/{report_id}")
async def cancel_generation_compat(report_id: str, request: Request):
    """前端兼容端点；与 DELETE /situation/generate/{reportId} 使用同一取消逻辑。"""
    return await cancel_generation(report_id, request)


def _finish_skill_usage(report_id: str, status: str) -> None:
    """使用记录故障不应影响 SSE 主流程。"""
    try:
        finish_usage(report_id, status)
    except SkillStoreError as exc:
        logger.warning("Skill 使用记录更新失败: reportId=%s error=%s", report_id, exc)


def _apply_event(report: Report, event_type: str, data: dict) -> None:
    """将 SSE 事件聚合到内存 Report，供生成完成后落库 snapshot。"""
    if event_type == "chart":
        item = {
            "chartId": data.get("chartId", ""),
            "type": data.get("type", ""),
            "title": data.get("title", ""),
            "option": data.get("option", {}),
            "explanation": "",
            "datasetRef": data.get("datasetRef", ""),
            "fieldMapping": data.get("fieldMapping") or {},
            "provenance": data.get("provenance", {}),
            "verification": data.get("verification", {}),
        }
        report.charts = [
            chart for chart in report.charts
            if (chart.get("chartId") if isinstance(chart, dict) else chart.chartId) != item["chartId"]
        ]
        report.charts.append(item)
    elif event_type == "map_layer":
        layers = report.map.setdefault("layers", [])
        item = {
            "layerId": data.get("layerId", ""),
            "points": data.get("points", []),
            "routes": data.get("routes", []),
            "areas": data.get("areas", []),
            "circles": data.get("circles", []),
            "layerConfig": data.get("layerConfig", {}),
            "datasetRef": data.get("datasetRef", ""),
            "fieldMapping": data.get("fieldMapping") or {},
            "verification": data.get("verification", {}),
        }
        report.map["layers"] = [layer for layer in layers if layer.get("layerId") != item["layerId"]]
        report.map["layers"].append(item)
    elif event_type == "narrative":
        report.narrative = {
            "intro": data.get("intro", ""),
            "explanations": data.get("explanations", []),
            "mapExplanation": data.get("mapExplanation", ""),
        }
        # 回填每个图表的 explanation 字段
        exp_map = {e.get("chartId"): e.get("text", "") for e in data.get("explanations", [])}
        for c in report.charts:
            if c["chartId"] in exp_map:
                c["explanation"] = exp_map[c["chartId"]]
        # 回填地图说明
        if data.get("mapExplanation"):
            report.map["explanation"] = data.get("mapExplanation", "")
    elif event_type == "dataset":
        item = {
            "datasetId": data.get("datasetId", ""),
            "source": data.get("source", ""),
            "summary": data.get("summary", ""),
            "rows": data.get("rows", 0),
            "physicalDatasetId": data.get("physicalDatasetId", ""),
            "schemaVersion": data.get("schemaVersion", 1),
            "truncated": data.get("truncated", False),
            "evidenceHash": data.get("evidenceHash", ""),
            "execution": data.get("execution", {}),
            "columns": data.get("columns", []),
            "data": data.get("data", []),
        }
        report.datasets = [
            dataset for dataset in report.datasets
            if (dataset.get("datasetId") if isinstance(dataset, dict) else dataset.datasetId) != item["datasetId"]
        ]
        report.datasets.append(item)
    elif event_type == "step":
        item = {
            "sequence": data.get("sequence"),
            "name": data.get("name", ""),
            "operator": data.get("operator", ""),
            "status": data.get("status", "completed"),
            "datasets": data.get("datasets", []),
            "inputRows": data.get("inputRows", 0),
            "outputRows": data.get("outputRows", 0),
            "appliedOperators": data.get("appliedOperators", []),
            "focusMetrics": data.get("focusMetrics", []),
            "plannedCharts": data.get("plannedCharts", 0),
            "plannedMapLayers": data.get("plannedMapLayers", 0),
        }
        report.execution = [step for step in report.execution if step.get("sequence") != item["sequence"]]
        report.execution.append(item)
        report.execution.sort(key=lambda step: int(step.get("sequence") or 0))


def _persist(report: Report) -> bool:
    """生成完成后调 admin-service 落库（snapshot_json）。失败仅记日志，不影响 SSE。"""
    try:
        snapshot = report.dict()
        # 落库字段对齐 admin-service SituationReport（reportId → id 之外保留原字段）
        payload = {
            "reportId": report.reportId,
            "title": report.title,
            "query": report.query,
            "source": report.source,
            "userId": report.userId,
            "teamIds": ",".join(report.teamIds) if report.teamIds else "",
            "status": report.status,
            "snapshot": snapshot,
        }
        resp = admin_client.save_report(payload, actor={"userId": report.userId, "teamIds": report.teamIds, "role": "service"})
        if not resp.get("success"):
            logger.warning("落库失败: reportId=%s msg=%s", report.reportId, resp.get("message"))
            return False
        return True
    except Exception as e:
        logger.exception("落库异常: reportId=%s", report.reportId)
        return False


# ──────────────────────────────────────────────────────────
# 6. 主动刷新（tick）
# ──────────────────────────────────────────────────────────
@app.post("/situation/refresh/{report_id}")
def refresh_report(report_id: str):
    """手动触发一次外部数据 tick。Phase 1 无外部数据源，返回空更新。"""
    logger.info("主动刷新: reportId=%s（Phase 1 无外部数据源）", report_id)
    return _ok({"updated": [], "status": "ready"})


# ──────────────────────────────────────────────────────────
# 7. 产物列表 / 详情 / 删除（透传 admin-service）
# ──────────────────────────────────────────────────────────
@app.get("/situation/reports")
def list_reports(request: Request, page: int = 1, size: int = 20):
    actor = _actor(request)
    user_id, team_ids = actor["userId"], actor["teamIds"]
    resp = admin_client.list_reports(user_id, team_ids, page, size, actor)
    if not resp.get("success"):
        return _fail(resp.get("message", "列表查询失败"))
    return resp


@app.get("/situation/reports/{report_id}")
def get_report_detail(report_id: str, request: Request):
    resp = admin_client.get_report(report_id, _actor(request))
    if not resp.get("success"):
        return _fail(resp.get("message", "产物不存在"), {"reportId": report_id})
    return resp


@app.delete("/situation/reports/{report_id}")
def delete_report(report_id: str, request: Request):
    resp = admin_client.delete_report(report_id, _actor(request))
    if not resp.get("success"):
        return _fail(resp.get("message", "删除失败"))
    return resp


# ──────────────────────────────────────────────────────────
# 8. 分享
# ──────────────────────────────────────────────────────────
@app.post("/situation/reports/{report_id}/share")
def create_share(report_id: str, request: Request):
    resp = admin_client.create_share(report_id, _actor(request))
    if not resp.get("success"):
        return _fail(resp.get("message", "生成分享链接失败"))
    data = resp.get("data", {}) or {}
    token = data.get("token", "")
    return _ok({
        "shareUrl": f"/situation/share/{token}",
        "token": token,
        "expiresAt": data.get("expiresAt"),
    })


@app.get("/situation/share/{token}")
def get_share(token: str):
    """公开查看（分享，无需登录态）。"""
    resp = admin_client.get_share(token)
    if not resp.get("success"):
        return _fail(resp.get("message", "分享链接无效或已失效"))
    return resp


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10257)
