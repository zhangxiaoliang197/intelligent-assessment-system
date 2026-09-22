"""智能交互页面服务（interactive-page-service / ipage）入口。

独立智能体：针对用户态势问题，直接生成含图表 + 地图 + 文字说明的可交互
单文件 HTML 页面。态势生成能力由本服务独立实现；平台能力仅通过
admin-service 的数据集元数据、只读 SQL 与 LLM 配置接口获取。

路由总览：
  GET    /ipage/health                  健康检查
  POST   /ipage/internal/cache/invalidate 元数据注解变更后失效进程内缓存（admin 回调）
  POST   /ipage/generate                发起生成（返回 pageId + streamUrl）
  GET    /ipage/stream/{pageId}         SSE 流式接收生成事件
  DELETE /ipage/generate/{pageId}       取消生成
  GET    /ipage/pages                   页面历史列表
  GET    /ipage/pages/{pageId}          页面详情（HTML + 数据包）
  DELETE /ipage/pages/{pageId}          删除页面
  GET    /ipage/sessions                会话列表（对话式交互）
  POST   /ipage/sessions                新建空会话
  GET    /ipage/sessions/{sessionId}    会话详情（消息 + 关联页面摘要）
  DELETE /ipage/sessions/{sessionId}    删除会话
  GET    /ipage/skills                  技能列表（生成剧本元数据，供前端选择器）
  POST   /ipage/skills/match            按问题语义匹配技能（阈值标定 / 前端预判）
"""

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.request
import uuid
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from logging_config import setup_logging
setup_logging("ipage-service")
logger = logging.getLogger("ipage-service")

import config
import cache_registry
from models import GenerateRequest, PageRecord, SessionCreate, SkillMatchRequest
from stream.sse import format_event, sse_response
from store import admin_client, page_store
from agent import orchestrator, skill_catalog, skill_matcher

app = FastAPI(
    title="智能交互页面服务",
    description="针对态势问题直接生成图表+地图+文字说明的可交互单文件 HTML 页面",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.IPAGE_CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID",
        "X-User-Id", "X-Team-Ids", "X-User-Role", "X-Actor-Signature",
        "X-Service-Token",
    ],
)


# ──────────────────────────────────────────────────────────────────
# 统一响应 / 身份 / ID
# ──────────────────────────────────────────────────────────────────

def _ok(data: dict, message: str = "ok") -> dict:
    return {"success": True, "message": message, "data": data}


def _fail(message: str, data: dict = None) -> dict:
    return {"success": False, "message": message, "data": data or {}}


def _gen_page_id() -> str:
    """生成 pageId：p_{yyyymmdd}_{8位uuid}。"""
    return f"p_{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


def _actor(request: Request) -> dict:
    """解析网关注入的身份头；无 HMAC 签名时回退本地开发身份。"""
    user_id = request.headers.get("X-User-Id", "").strip() or "local-admin"
    team_ids = [t.strip() for t in request.headers.get("X-Team-Ids", "").split(",") if t.strip()]
    role = request.headers.get("X-User-Role", "admin").strip().lower() or "admin"
    signature = request.headers.get("X-Actor-Signature", "").strip()
    payload = f"{user_id}|{','.join(team_ids)}|{role}".encode("utf-8")
    expected = hmac.new(
        config.INTERNAL_SERVICE_TOKEN.encode("utf-8"), payload, hashlib.sha256,
    ).hexdigest()
    trusted = bool(signature) and hmac.compare_digest(signature, expected)
    if not trusted:
        # 本地开发无网关注入签名时的回退；生产环境须由可信网关注入身份
        user_id, team_ids, role = "local-admin", [], "admin"
    return {"userId": user_id, "teamIds": team_ids, "role": role, "trusted": trusted}


# ──────────────────────────────────────────────────────────────────
# SSE 会话（一个 pageId 一个唯一生产者，多客户端共享事件日志）
# ──────────────────────────────────────────────────────────────────

class _GenerationSession:
    """生成任务会话：事件日志 + Condition 唤醒 + 后台任务句柄。"""

    def __init__(self, page: PageRecord, actor: dict, database_id: str,
                 skill_id: str = "", skill_mode: str = "auto"):
        self.page = page
        self.actor = actor
        self.database_id = database_id
        self.skill_id = skill_id
        self.skill_mode = skill_mode
        self.events = []
        self.condition = asyncio.Condition()
        self.finished = False
        self.task: Optional[asyncio.Task] = None

    async def publish(self, event_type: str, data: dict) -> None:
        async with self.condition:
            self.events.append((len(self.events) + 1, event_type, data))
            self.condition.notify_all()

    async def finish(self) -> None:
        async with self.condition:
            self.finished = True
            self.condition.notify_all()


_STREAM_SESSIONS: Dict[str, _GenerationSession] = {}
# 后台清理任务引用集合：create_task 的返回值必须持有引用，否则可能被 GC 回收
_BACKGROUND_TASKS: set = set()
_INFLIGHT: Dict[str, PageRecord] = {}
_GENERATION_SEMAPHORE = asyncio.Semaphore(config.IPAGE_MAX_CONCURRENT)
_IDEMPOTENCY: Dict[str, tuple] = {}


@app.on_event("shutdown")
async def _shutdown_tasks() -> None:
    """关闭时取消所有在途生成任务。"""
    tasks = [s.task for s in _STREAM_SESSIONS.values() if s.task and not s.task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=10)


async def _cleanup_session(page_id: str, session: _GenerationSession) -> None:
    await asyncio.sleep(config.IPAGE_STREAM_REPLAY_TTL)
    if _STREAM_SESSIONS.get(page_id) is session:
        _STREAM_SESSIONS.pop(page_id, None)


async def _run_pipeline(page_id: str, session: _GenerationSession,
                        page: PageRecord) -> dict:
    """拉取元数据并执行四阶段编排；返回终态 done 载荷（done 不在此广播）。"""
    async with _GENERATION_SEMAPHORE:
        async with asyncio.timeout(config.IPAGE_GENERATION_TIMEOUT):
            meta = await asyncio.to_thread(orchestrator.fetch_meta, session.database_id)
            if not isinstance(meta, dict) or not meta.get("success"):
                msg = str((meta or {}).get("message") or "数据集元数据获取失败")
                page.status = "failed"
                page.error = msg
                await session.publish("error", {"pageId": page_id, "message": msg, "fatal": True})
                return {"pageId": page_id, "status": "failed"}
            done_payload = {"pageId": page_id, "status": "failed"}
            async for item in orchestrator.generate_stream(
                page, meta, page.query, session.database_id,
                session.skill_id, session.skill_mode,
            ):
                event_type, data = item["event"], item["data"]
                if event_type == "done":
                    done_payload = data
                    continue
                await session.publish(event_type, data)
            return done_payload


def _append_round_result(page_id: str, page: PageRecord, extra: dict = None) -> None:
    """生成收尾后把本轮结果写回会话消息（直答 / 页面卡片 / 错误文本）。

    会话模型见 page_store：主对话框页与态势页共享会话，前端重新加载即同步。
    修订失败（revised=false）时额外落一条文本消息说明原因：修订沿用上一版页面，
    产物本身没有变化，若只更新卡片用户无从得知本次修改为何没生效。
    """
    sid = page.sessionId
    if not sid:
        return
    extra = extra or {}
    try:
        if page.status == "ready" and page.intent == "general":
            page_store.append_message(sid, "ai", "direct",
                                      page.directAnswer or page.title or "已完成")
        elif page.status == "ready":
            content = json.dumps({
                "pageId": page_id,
                "title": page.title,
                "usedTemplate": page.error == "template_fallback",
            }, ensure_ascii=False)
            page_store.append_message(sid, "ai", "page_card", content, page_id=page_id)
            if extra.get("isRevision") and extra.get("revised") is False:
                page_store.append_message(
                    sid, "ai", "text",
                    "本次修改未生效，已保留上一版：" + _revision_failure_reason(extra),
                    page_id=page_id)
        else:
            page_store.append_message(sid, "ai", "error",
                                      page.error or "生成失败", page_id=page_id)
    except Exception as exc:
        logger.error("会话结果消息写入失败 pageId=%s: %s", page_id, exc)


def _revision_failure_reason(extra: dict) -> str:
    """从修订失败载荷中提取可读中文原因（默认给通用原因）。"""
    issues = [str(i) for i in (extra.get("guardIssues") or []) if str(i).strip()]
    if issues:
        return "；".join(issues[:3])
    return "重新设计未通过校验"


async def _run_generation(page_id: str, session: _GenerationSession) -> None:
    """唯一生产者：拉取元数据 → 四阶段编排 → 事件广播。"""
    page = session.page
    started = time.monotonic()
    done_payload = {"pageId": page_id, "status": "failed"}
    try:
        # 身份写入 ContextVar（to_thread 会复制上下文），供 admin HTTP 调用透传
        with admin_client.actor_context(session.actor):
            done_payload = await _run_pipeline(page_id, session, page)
    except TimeoutError:
        logger.warning("交互页面生成超时: pageId=%s", page_id)
        page.status = "failed"
        page.error = "生成超过服务端时限"
        await session.publish("error", {"pageId": page_id, "message": "生成超过服务端时限", "fatal": True})
    except asyncio.CancelledError:
        logger.info("交互页面生成已取消: pageId=%s", page_id)
        page.status = "failed"
        page.error = "生成已取消"
        await session.publish("error", {"pageId": page_id, "message": "生成已取消", "fatal": True})
    except Exception as exc:
        logger.exception("交互页面生成异常: pageId=%s", page_id)
        page.status = "failed"
        page.error = str(exc)[:200]
        await session.publish("error", {"pageId": page_id, "message": str(exc)[:200], "fatal": True})
    finally:
        # 兜底落库终态（编排器内已落库的情况为覆盖写）
        try:
            page_store.upsert_page(page.to_store())
        except Exception as exc:
            logger.error("终态落库失败 pageId=%s: %s", page_id, exc)
        # 把本轮结果写回会话消息（直答/页面卡片/错误/修订失败说明），供对话页与态势页同步展示
        _append_round_result(page_id, page, done_payload)
        done_payload.setdefault("pageId", page_id)
        done_payload.setdefault("status", page.status or "failed")
        done_payload.setdefault("intent", page.intent)
        await session.publish("done", done_payload)
        _INFLIGHT.pop(page_id, None)
        await session.finish()
        # 延迟清理必须是「发射即忘」：await create_task 会等满 IPAGE_STREAM_REPLAY_TTL，
        # 导致本函数与「生成结束」日志被拖后 5 分钟（耗时统计随之虚高）
        cleanup_task = asyncio.create_task(_cleanup_session(page_id, session))
        _BACKGROUND_TASKS.add(cleanup_task)
        cleanup_task.add_done_callback(_BACKGROUND_TASKS.discard)
        logger.info("交互页面生成结束: pageId=%s status=%s 总耗时=%d ms",
                    page_id, page.status, int((time.monotonic() - started) * 1000))


async def _stream_events(session: _GenerationSession, cursor: int = 0):
    """从共享事件日志订阅，15 秒无事件发 keep-alive。"""
    cursor = max(0, cursor)
    while True:
        timed_out = False
        async with session.condition:
            if cursor >= len(session.events) and not session.finished:
                try:
                    await asyncio.wait_for(
                        session.condition.wait_for(
                            lambda: cursor < len(session.events) or session.finished),
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


# ──────────────────────────────────────────────────────────────────
# 健康检查
# ──────────────────────────────────────────────────────────────────

@app.get("/ipage/health")
def health():
    db_ok = True
    try:
        page_store.init_db()
    except Exception as exc:
        logger.error("健康检查-数据库初始化失败: %s", exc)
        db_ok = False
    skill_count = 0
    try:
        skill_count = len(skill_catalog.load_skills())
    except Exception as exc:
        logger.warning("健康检查-技能目录加载失败: %s", exc)
    return _ok({
        "status": "healthy" if db_ok else "degraded",
        "service": "interactive-page-service",
        "port": config.SERVICE_PORT,
        "storage": "sqlite" if db_ok else "unavailable",
        "registeredCaches": cache_registry.registered_caches(),
        "skills": skill_count,
        "skillMatchEnabled": config.IPAGE_SKILL_MATCH_ENABLED,
        "knowledgeService": _knowledge_reachable(),
    })


def _knowledge_reachable() -> str:
    """探测向量服务可达性。

    只探 /health，不调用 /knowledge/embed —— 健康检查不该触发模型推理。
    技能匹配本身可降级，因此这里的结果不影响本服务自身的 healthy 判定。
    """
    if not config.KNOWLEDGE_SERVICE_URL:
        return "unconfigured"
    url = config.KNOWLEDGE_SERVICE_URL.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            return "ok" if resp.status == 200 else "unreachable"
    except Exception:
        return "unreachable"


# ──────────────────────────────────────────────────────────────────
# 内部接口：元数据注解变更后失效进程内缓存
# ──────────────────────────────────────────────────────────────────

def _verify_service_token(request: Request) -> bool:
    """校验服务间令牌；未配置令牌时视为本地开发，放行。"""
    expected = config.INTERNAL_SERVICE_TOKEN
    if not expected:
        return True
    return hmac.compare_digest(request.headers.get("X-Service-Token", ""), expected)


@app.post("/ipage/internal/cache/invalidate")
async def invalidate_metadata_cache(request: Request):
    """清空元数据相关缓存（维度图、维度值采样、档案索引、enrich 索引）。

    由 admin-service 在字段注解/数据集语义保存成功后回调；未配置 ipage 地址时
    admin 侧会跳过该调用并在保存响应里给出告警。

    请求体：``{"databaseId": "db_xxx", "tables": ["mock_aircraft"]}``；
    字段为空表示不限范围（全量清理）。
    """
    if not _verify_service_token(request):
        raise HTTPException(status_code=401, detail="服务间令牌校验失败")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    database_id = str(payload.get("databaseId") or "").strip() or None
    raw_tables = payload.get("tables")
    tables = None
    if isinstance(raw_tables, list):
        tables = [str(t).strip() for t in raw_tables if str(t).strip()] or None

    cleared = cache_registry.invalidate(database_id, tables)
    return _ok({"cleared": cleared, "databaseId": database_id or "", "tables": tables or []},
               "元数据缓存已失效")


# ──────────────────────────────────────────────────────────────────
# 技能（生成剧本）：列表与语义匹配
# ──────────────────────────────────────────────────────────────────

@app.get("/ipage/skills")
def list_skills():
    """技能列表（仅元数据，不含正文），供前端技能选择器。

    技能是「生成剧本」（取数口径 / 区块编排 / 呈现偏好 / 叙事要点），
    不承载领域语义 —— 后者走数据源注解。

    ``defaultMode`` 是前端"是否需要用户选择"的单一来源：默认 off（不套用技能），
    由用户显式选择是否自动匹配或指定技能；``enabled=false`` 表示服务端彻底禁用了
    自动匹配（此时即使前端选"自动匹配"也不会生效）。
    """
    try:
        skills = skill_catalog.load_skills()
    except Exception as exc:
        logger.error("技能目录加载失败: %s", exc)
        return _fail("技能目录加载失败，请检查服务日志")
    return _ok({
        "enabled": config.IPAGE_SKILL_MATCH_ENABLED,
        "defaultMode": config.IPAGE_SKILL_DEFAULT_MODE,
        "matchHigh": config.IPAGE_SKILL_MATCH_HIGH,
        "matchLow": config.IPAGE_SKILL_MATCH_LOW,
        "items": [skill.to_meta() for skill in skills],
    })


@app.post("/ipage/skills/match")
def match_skill(req: SkillMatchRequest):
    """按问题语义匹配技能：返回候选与分数，以及是否达到自动套用阈值。

    用于阈值标定（用「应命中 / 不应命中」两组真实问法回放）与前端预判。
    向量服务不可用时返回空候选与中文原因，不报错。
    """
    query = (req.query or "").strip()
    if not query:
        return _fail("query 不能为空")
    try:
        top_n = max(1, min(int(req.topK or 3), 10))
        result = skill_matcher.match(query, top_n=top_n)
    except Exception as exc:
        logger.error("技能匹配失败: %s", exc)
        return _fail("技能匹配失败，请检查服务日志")
    return _ok(result.to_dict())


# ──────────────────────────────────────────────────────────────────
# 发起生成
# ──────────────────────────────────────────────────────────────────

@app.post("/ipage/generate")
async def generate(req: GenerateRequest, request: Request):
    actor = _actor(request)
    user_id, team_ids = actor["userId"], actor["teamIds"]
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if len(_INFLIGHT) >= config.IPAGE_MAX_INFLIGHT:
        raise HTTPException(status_code=429, detail="生成队列已满，请稍后重试")
    if sum(1 for p in _INFLIGHT.values() if p.userId == user_id) >= config.IPAGE_MAX_PER_USER:
        raise HTTPException(status_code=429, detail="当前用户在途生成任务已达上限")

    # 幂等键：同一键 + 同一指纹在 TTL 内直接复用
    idem_key = request.headers.get("Idempotency-Key", "").strip()[:128]
    fingerprint = ""
    if idem_key:
        fingerprint = hashlib.sha256(json.dumps({
            "userId": user_id, "query": query, "source": req.source,
            "dataSourceId": req.dataSourceId, "parentPageId": req.parentPageId,
            "context": req.context, "skillId": req.skillId, "skillMode": req.skillMode,
        }, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        previous = _IDEMPOTENCY.get(idem_key)
        if previous and previous[0] > time.time():
            if previous[1] != fingerprint:
                raise HTTPException(status_code=409, detail="幂等键已用于不同的生成请求")
            return _ok({"pageId": previous[2], "status": "generating",
                        "streamUrl": f"/ipage/stream/{previous[2]}", "reused": True})
        now = time.time()
        for key in [k for k, v in _IDEMPOTENCY.items() if v[0] <= now]:
            _IDEMPOTENCY.pop(key, None)

    # 修订必须能找到父页面
    parent: Optional[dict] = None
    if req.parentPageId:
        parent = page_store.get_page(req.parentPageId)
        if not parent:
            raise HTTPException(status_code=404, detail="要修订的历史页面不存在")

    # ── 会话解析：显式 sessionId > 父页面所属会话 > 自动新建 ──
    session_id = (req.sessionId or "").strip()
    if session_id and not page_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="所属会话不存在")
    if not session_id and parent:
        session_id = parent.get("sessionId") or ""
    if not session_id:
        session_id = page_store.create_session(user_id, team_ids, query[:25])["sessionId"]

    page_id = _gen_page_id()
    page = PageRecord(
        pageId=page_id,
        title=query[:25],
        query=query,
        source=req.source or "manual",
        parentId=req.parentPageId or "",
        sessionId=session_id,
        userId=user_id,
        teamIds=team_ids,
        status="generating",
    )
    try:
        page_store.init_db()
        page_store.upsert_page(page.to_store())
        # 入口即落库用户消息：页面刷新/换端后对话可完整回放
        page_store.append_message(session_id, "user", "text", query)
    except Exception as exc:
        logger.error("创建页面记录失败: %s", exc)
        raise HTTPException(status_code=503, detail="无法创建生成任务，请稍后重试") from exc

    _INFLIGHT[page_id] = page
    if idem_key:
        _IDEMPOTENCY[idem_key] = (time.time() + config.IPAGE_IDEMPOTENCY_TTL,
                                  fingerprint, page_id)

    session = _GenerationSession(page, actor, req.dataSourceId or "",
                                 (req.skillId or "").strip(),
                                 (req.skillMode or "auto").strip().lower() or "auto")
    _STREAM_SESSIONS[page_id] = session
    session.task = asyncio.create_task(_run_generation(page_id, session))

    logger.info("发起交互页面生成: pageId=%s parent=%s session=%s query=%s",
                page_id, req.parentPageId or "-", session_id, query[:50])
    return _ok({
        "pageId": page_id,
        "status": "generating",
        "streamUrl": f"/ipage/stream/{page_id}",
        "parentPageId": req.parentPageId or "",
        "sessionId": session_id,
    })


# ──────────────────────────────────────────────────────────────────
# SSE 订阅 / 取消
# ──────────────────────────────────────────────────────────────────

@app.get("/ipage/stream/{page_id}")
async def stream_page(page_id: str, request: Request):
    """订阅生成事件；断线按 Last-Event-ID 回放，绝不重新执行生成。"""
    session = _STREAM_SESSIONS.get(page_id)
    actor = _actor(request)
    if not session:
        item = page_store.get_page(page_id)
        if not item:
            raise HTTPException(status_code=404, detail="页面不存在")
        status = item.get("status") or "failed"

        async def _replay():
            yield format_event("done", {"pageId": page_id, "status": status,
                                        "persisted": True}, 1)
        return sse_response(_replay())

    page = session.page
    if page.userId != actor["userId"] and actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权订阅该页面")
    try:
        cursor = max(0, int(request.headers.get("Last-Event-ID", "0") or "0"))
    except ValueError:
        cursor = 0
    return sse_response(_stream_events(session, cursor))


@app.delete("/ipage/generate/{page_id}")
async def cancel_generation(page_id: str, request: Request):
    session = _STREAM_SESSIONS.get(page_id)
    if not session or session.finished:
        raise HTTPException(status_code=404, detail="生成任务不存在或已结束")
    actor = _actor(request)
    if session.page.userId != actor["userId"] and actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权取消该任务")
    if session.task:
        session.task.cancel()
    return _ok({"pageId": page_id, "status": "cancelling"})


# ──────────────────────────────────────────────────────────────────
# 页面历史 CRUD
# ──────────────────────────────────────────────────────────────────

@app.get("/ipage/pages")
def list_pages(pageNo: int = 1, size: int = 20, request: Request = None):
    actor = _actor(request)
    try:
        page_no = max(1, pageNo)
        size = min(50, max(1, size))
        result = page_store.list_pages(actor["userId"], actor["teamIds"], page_no, size)
        return _ok(result)
    except Exception as exc:
        logger.error("页面列表查询失败: %s", exc)
        return _fail(f"页面列表查询失败: {str(exc)[:120]}")


@app.get("/ipage/pages/{page_id}")
def get_page(page_id: str, request: Request):
    actor = _actor(request)
    item = page_store.get_page(page_id)
    if not item:
        raise HTTPException(status_code=404, detail="页面不存在")
    if item.get("userId") != actor["userId"] and actor["role"] != "admin":
        teams = set(item.get("teamIds") or [])
        if not teams.intersection(actor["teamIds"]):
            raise HTTPException(status_code=403, detail="无权查看该页面")
    return _ok(item)


@app.delete("/ipage/pages/{page_id}")
def remove_page(page_id: str, request: Request):
    actor = _actor(request)
    item = page_store.get_page(page_id)
    if not item:
        raise HTTPException(status_code=404, detail="页面不存在")
    if item.get("userId") != actor["userId"] and actor["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权删除该页面")
    ok = page_store.delete_page(page_id)
    if not ok:
        return _fail("删除失败")
    # 同步移除会话内的页面卡片消息，保持对话与产物一致
    page_store.delete_messages_by_page(page_id)
    return _ok({"pageId": page_id}, "删除成功")


# ──────────────────────────────────────────────────────────────────
# 会话（对话式交互：主对话框页与态势页共享同一会话）
# ──────────────────────────────────────────────────────────────────

@app.get("/ipage/sessions")
def list_sessions(pageNo: int = 1, size: int = 20, request: Request = None):
    """分页列出当前用户可见的会话（按最近更新排序）。"""
    actor = _actor(request)
    try:
        result = page_store.list_sessions(actor["userId"], actor["teamIds"],
                                          max(1, pageNo), min(50, max(1, size)))
        return _ok(result)
    except Exception as exc:
        logger.error("会话列表查询失败: %s", exc)
        return _fail(f"会话列表查询失败: {str(exc)[:120]}")


@app.post("/ipage/sessions")
def create_session(req: SessionCreate, request: Request):
    """新建空会话。"""
    actor = _actor(request)
    try:
        session = page_store.create_session(actor["userId"], actor["teamIds"], req.title or "")
        return _ok(session, "会话已创建")
    except Exception as exc:
        logger.error("会话创建失败: %s", exc)
        return _fail(f"会话创建失败: {str(exc)[:120]}")


@app.get("/ipage/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    """会话详情：全部消息 + 关联页面摘要。"""
    actor = _actor(request)
    item = page_store.get_session(session_id)
    if not item:
        raise HTTPException(status_code=404, detail="会话不存在")
    if item.get("userId") != actor["userId"] and actor["role"] != "admin":
        teams = set(item.get("teamIds") or [])
        if not teams.intersection(actor["teamIds"]):
            raise HTTPException(status_code=403, detail="无权查看该会话")
    return _ok(item)


@app.delete("/ipage/sessions/{session_id}")
def remove_session(session_id: str, request: Request):
    """删除会话及其全部消息（页面产物保留在历史列表中）。"""
    actor = _actor(request)
    item = page_store.get_session(session_id)
    if not item:
        raise HTTPException(status_code=404, detail="会话不存在")
    if item.get("userId") != actor["userId"] and actor["role"] != "admin":
        teams = set(item.get("teamIds") or [])
        if not teams.intersection(actor["teamIds"]):
            raise HTTPException(status_code=403, detail="无权删除该会话")
    ok = page_store.delete_session(session_id)
    if not ok:
        return _fail("删除失败")
    return _ok({"sessionId": session_id}, "删除成功")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=config.SERVICE_PORT, log_level="info")
