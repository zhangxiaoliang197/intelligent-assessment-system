"""态势图服务（situation-service）入口。

独立于本体模型与向量库（ADR-01/05），负责态势产物的生成编排、流式推送、
产物聚合与跨功能草稿态。持久化经 admin-service，不直连 DB（ADR-11）。

路由总览（详见 docs/situation-map/04-接口契约.md）：
  GET  /situation/health                  健康检查
  POST /situation/draft                   创建草稿态（跨功能跳转入口）
  GET  /situation/draft/{draftId}         读取草稿态
  POST /situation/generate                发起生成（立即返回 reportId + streamUrl）
  GET  /situation/stream/{reportId}       SSE 流式接收（agent 中间结果）
  POST /situation/refresh/{reportId}      主动刷新一次 tick
  GET  /situation/reports                 产物列表（透传 admin-service）
  GET  /situation/reports/{reportId}      产物详情
  DELETE /situation/reports/{reportId}    删除产物
  POST /situation/reports/{reportId}/share  生成分享 token
  GET  /situation/share/{token}           公开查看（分享，无需登录）

Phase 1：生成走 mock_generate（canned 数据），验证前端管线端到端。
Phase 2：切换为 real_generate（LLM tool-calling，见 agent/orchestrator.py）。
"""

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(usecwd=True))

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from logging_config import setup_logging
setup_logging("situation-service")
logger = logging.getLogger("situation-service")

import config
from models import DraftRequest, GenerateRequest, Report
from stream.sse import format_event, sse_response
from agent.orchestrator import generate
from store import admin_client, draft as draft_store

app = FastAPI(
    title="态势图服务",
    description="综合态势感知：LLM 编排多源数据，流式生成统计图表 + 地图 + 态势介绍",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    user_id = request.headers.get("X-User-Id", "local-admin")
    team_ids_raw = request.headers.get("X-Team-Ids", "")
    team_ids = [t for t in team_ids_raw.split(",") if t] if team_ids_raw else []
    return user_id, team_ids


# ──────────────────────────────────────────────────────────
# 1. 健康检查
# ──────────────────────────────────────────────────────────
@app.get("/situation/health")
def health():
    return _ok({"status": "healthy", "service": "situation-service", "port": 10257})


# ──────────────────────────────────────────────────────────
# 2. 草稿态（跨功能跳转入口）
# ──────────────────────────────────────────────────────────
@app.post("/situation/draft")
def create_draft(req: DraftRequest):
    draft_id = draft_store.create_draft(req)
    logger.info("草稿态已创建: draftId=%s source=%s", draft_id, req.source)
    return _ok({"draftId": draft_id, "expiresIn": config.DRAFT_TTL})


@app.get("/situation/draft/{draft_id}")
def get_draft(draft_id: str):
    item = draft_store.get_draft(draft_id)
    if not item:
        raise HTTPException(status_code=404, detail="草稿不存在或已过期")
    return _ok(item)


# ──────────────────────────────────────────────────────────
# 3. 发起生成
# ──────────────────────────────────────────────────────────
# 生成中的产物暂存（reportId → 聚合中的 Report）
# Phase 1 单机内存即可；Phase 2 多实例需换 Redis
_INFLIGHT: dict = {}


@app.post("/situation/generate")
def generate_report(req: GenerateRequest, request: Request):
    user_id, team_ids = _read_headers(request)
    # 请求体未带 userId/teamIds 时回退到请求头
    if not req.userId or req.userId == "local-admin":
        req.userId = user_id
    if not req.teamIds:
        req.teamIds = team_ids

    report_id = _gen_report_id()
    # 若带 draftId，合并草稿态上下文
    context = dict(req.context or {})
    if req.draftId:
        d = draft_store.get_draft(req.draftId)
        if d:
            context = {**d.get("context", {}), **context}
            if not req.source or req.source == "manual":
                req.source = d.get("source", "manual")

    report = Report(
        reportId=report_id,
        title=req.query[:60] if req.query else "态势图",
        query=req.query,
        source=req.source,
        userId=req.userId,
        teamIds=req.teamIds,
        status="generating",
    )
    _INFLIGHT[report_id] = report

    logger.info("发起态势生成: reportId=%s query=%s source=%s", report_id, req.query[:50], req.source)
    return _ok({
        "reportId": report_id,
        "status": "generating",
        "streamUrl": f"/situation/stream/{report_id}",
    })


# ──────────────────────────────────────────────────────────
# 4. SSE 流式接收
# ──────────────────────────────────────────────────────────
@app.get("/situation/stream/{report_id}")
def stream_report(report_id: str):
    """SSE 推送生成事件。Phase 1 走 mock_generate。"""
    report = _INFLIGHT.get(report_id)
    if not report:
        # 不在内存中：可能是已完成的历史产物，回查 admin-service
        resp = admin_client.get_report(report_id)
        if resp.get("success"):
            # 已有产物，立即推 done 事件
            async def _replay():
                yield format_event("done", {"reportId": report_id, "status": "ready", "partial": False})
            return sse_response(_replay())
        raise HTTPException(status_code=404, detail="reportId 不存在")

    async def _event_stream():
        try:
            async for event_type, data in generate(report.query, report_id):
                # 同步聚合到内存 Report（供完成后落库）
                _apply_event(report, event_type, data)
                yield format_event(event_type, data)
        except Exception as e:
            logger.exception("生成异常: reportId=%s", report_id)
            yield format_event("error", {"stage": "llm", "message": str(e)[:200], "fatal": True})
            yield format_event("done", {"reportId": report_id, "status": "failed", "partial": False})
            report.status = "failed"
            _persist(report)
            _INFLIGHT.pop(report_id, None)
            return

        # 正常完成 → 落库
        report.status = "ready"
        _persist(report)
        _INFLIGHT.pop(report_id, None)
        logger.info("SSE 流结束并已落库: reportId=%s", report_id)

    return sse_response(_event_stream())


def _apply_event(report: Report, event_type: str, data: dict) -> None:
    """将 SSE 事件聚合到内存 Report，供生成完成后落库 snapshot。"""
    if event_type == "chart":
        report.charts.append({
            "chartId": data.get("chartId", ""),
            "type": data.get("type", ""),
            "title": data.get("title", ""),
            "option": data.get("option", {}),
            "explanation": "",
            "datasetRef": data.get("datasetRef", ""),
        })
    elif event_type == "map_layer":
        layers = report.map.setdefault("layers", [])
        layers.append({
            "layerId": data.get("layerId", ""),
            "points": data.get("points", []),
            "routes": data.get("routes", []),
            "areas": data.get("areas", []),
            "layerConfig": data.get("layerConfig", {}),
        })
    elif event_type == "narrative":
        report.narrative = {
            "intro": data.get("intro", ""),
            "explanations": data.get("explanations", []),
        }
        # 回填每个图表的 explanation 字段
        exp_map = {e.get("chartId"): e.get("text", "") for e in data.get("explanations", [])}
        for c in report.charts:
            if c["chartId"] in exp_map:
                c["explanation"] = exp_map[c["chartId"]]
    elif event_type == "dataset":
        report.datasets.append({
            "datasetId": data.get("datasetId", ""),
            "source": data.get("source", ""),
            "summary": data.get("summary", ""),
            "rows": data.get("rows", 0),
        })


def _persist(report: Report) -> None:
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
        resp = admin_client.save_report(payload)
        if not resp.get("success"):
            logger.warning("落库失败（不阻断 SSE）: reportId=%s msg=%s", report.reportId, resp.get("message"))
    except Exception as e:
        logger.exception("落库异常: reportId=%s", report.reportId)


# ──────────────────────────────────────────────────────────
# 5. 主动刷新（tick）
# ──────────────────────────────────────────────────────────
@app.post("/situation/refresh/{report_id}")
def refresh_report(report_id: str):
    """手动触发一次外部数据 tick。Phase 1 无外部数据源，返回空更新。"""
    logger.info("主动刷新: reportId=%s（Phase 1 无外部数据源）", report_id)
    return _ok({"updated": [], "status": "ready"})


# ──────────────────────────────────────────────────────────
# 6. 产物列表 / 详情 / 删除（透传 admin-service）
# ──────────────────────────────────────────────────────────
@app.get("/situation/reports")
def list_reports(request: Request, page: int = 1, size: int = 20):
    user_id, team_ids = _read_headers(request)
    resp = admin_client.list_reports(user_id, team_ids, page, size)
    if not resp.get("success"):
        return _fail(resp.get("message", "列表查询失败"))
    return resp


@app.get("/situation/reports/{report_id}")
def get_report_detail(report_id: str):
    resp = admin_client.get_report(report_id)
    if not resp.get("success"):
        return _fail(resp.get("message", "产物不存在"), {"reportId": report_id})
    return resp


@app.delete("/situation/reports/{report_id}")
def delete_report(report_id: str):
    resp = admin_client.delete_report(report_id)
    if not resp.get("success"):
        return _fail(resp.get("message", "删除失败"))
    return resp


# ──────────────────────────────────────────────────────────
# 7. 分享
# ──────────────────────────────────────────────────────────
@app.post("/situation/reports/{report_id}/share")
def create_share(report_id: str):
    resp = admin_client.create_share(report_id)
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
