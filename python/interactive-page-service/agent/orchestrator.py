"""Orchestrator —— 四阶段智能体编排。

Planner（规划/意图）→ Researcher（并行取数）→ PageWriter（生成/校验/兜底）
→ 持久化。以异步事件流形式向 main 层产出 SSE 事件。
"""
import asyncio
import datetime as dt
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Tuple

import config
from agent.planner import Planner
from agent.researcher import execute_sub_question, build_map_timeline
from agent.page_writer import PageWriter
from agent import dimension_graph, entity_filter
from models import PageRecord
from store import admin_client, page_store

logger = logging.getLogger("ipage-service")


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _elapsed_ms(started: float) -> int:
    """自 started（time.monotonic 取值）以来的毫秒耗时，用于阶段性能打点。"""
    return int((time.monotonic() - started) * 1000)


def _save(page: PageRecord) -> None:
    """落库（SQLite 本地写，异常不阻断主流程）。"""
    page.updatedAt = _now()
    try:
        page_store.upsert_page(page.to_store())
    except Exception as exc:
        logger.error("页面落库失败 pageId=%s: %s", page.pageId, exc)


async def _research_all(plan: Dict[str, Any], meta: Dict[str, Any],
                        query: str,
                        entity_scope: Dict[str, Any] = None,
                        entity_hits: list = None) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    """并行取数，逐数据集产出 dataset 事件；最终 yield ("__datasets__", entries)。"""
    sub_questions = plan.get("subQuestions") or []
    semaphore = asyncio.Semaphore(config.IPAGE_MAX_CONCURRENT)
    entity_scope = entity_scope or {}
    entity_hits = entity_hits or []

    async def run_one(sq: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            # 只统计真正执行的时间（不含信号量排队），排队总时长看整体取数打点
            started = time.monotonic()
            entry = await asyncio.to_thread(execute_sub_question, sq, meta, query,
                                            entity_scope, entity_hits)
            logger.info("子问题取数完成 qid=%s mode=%s 耗时=%d ms",
                        sq.get("id"), sq.get("mode"), _elapsed_ms(started))
            return entry

    # as_completed 完成顺序不固定，通过结果内 id 关联子问题
    futures = [asyncio.create_task(run_one(sq)) for sq in sub_questions]
    entries = []
    sql_log = []
    for coro in asyncio.as_completed(futures):
        try:
            entry = await coro
        except Exception as exc:
            logger.error("子问题取数失败: %s", exc)
            yield ("error-item", {"message": str(exc)[:200]})
            continue
        entries.append(entry)
        sql_log.append(entry.pop("_sqlLog", {}))
        yield ("dataset", {
            "qid": entry.get("id"),
            "datasetId": entry.get("datasetId"),
            "name": entry.get("name"),
            "mode": entry.get("mode"),
            "totalRows": entry.get("totalRows"),
            "truncated": entry.get("truncated"),
            "geoKind": (entry.get("geo") or {}).get("kind"),
            "warnings": entry.get("warnings", []),
        })

    # 恢复规划顺序（页面代码按 q1/q2 顺序更易理解）
    order = {str(sq.get("id")): i for i, sq in enumerate(sub_questions)}
    entries.sort(key=lambda e: order.get(e.get("id"), 99))
    sql_log.sort(key=lambda s: order.get(s.get("qid"), 99))
    yield ("__datasets__", {"entries": entries, "sqlLog": sql_log})


# ──────────────────────────────────────────────────────────────────
# 修订：延续式重规划 + 增量取数
# ──────────────────────────────────────────────────────────────────

def _sub_question_signature(sq: Dict[str, Any]) -> tuple:
    """子问题取数口径签名：datasetId/mode/geo/question/filters 任一变化即视为定义变化。"""
    return (
        str(sq.get("datasetId") or ""),
        str(sq.get("mode") or ""),
        str(sq.get("geo") or "none"),
        str(sq.get("question") or "").strip(),
        json.dumps(sq.get("filters") or {}, ensure_ascii=False, sort_keys=True),
    )


def _diff_sub_questions(parent_plan: Dict[str, Any],
                        new_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """找出需要（重新）取数的子问题：新 id 或取数口径发生变化。"""
    existing = {
        str(sq.get("id") or ""): _sub_question_signature(sq)
        for sq in (parent_plan.get("subQuestions") or []) if isinstance(sq, dict)
    }
    added: List[Dict[str, Any]] = []
    for sq in (new_plan.get("subQuestions") or []):
        if not isinstance(sq, dict):
            continue
        qid = str(sq.get("id") or "")
        if qid and existing.get(qid) == _sub_question_signature(sq):
            continue
        added.append(sq)
    return added


def _merge_incremental(new_plan: Dict[str, Any], parent_entries: List[Dict[str, Any]],
                       parent_logs: List[Dict[str, Any]],
                       new_entries: List[Dict[str, Any]],
                       new_logs: List[Dict[str, Any]]) -> Tuple[List, List, set]:
    """按新规划合并父页面数据与新增取数结果。

    未变化的子问题直接沿用父条目（不重复取数）；取数失败、最终没有任何数据的
    子问题从规划中剔除，并同步移除引用它的区块，保证页面不会引用数据包里不存在的 id。

    Returns:
        (entries, sqlLog, available_ids)
    """
    reuse_e = {str(e.get("id")): e for e in parent_entries
               if isinstance(e, dict) and e.get("id")}
    fresh_e = {str(e.get("id")): e for e in new_entries
               if isinstance(e, dict) and e.get("id")}
    reuse_l = {str(l.get("qid")): l for l in parent_logs
               if isinstance(l, dict) and l.get("qid")}
    fresh_l = {str(l.get("qid")): l for l in new_logs
               if isinstance(l, dict) and l.get("qid")}

    entries, logs, available = [], [], set()
    kept_questions = []
    for sq in (new_plan.get("subQuestions") or []):
        if not isinstance(sq, dict):
            continue
        qid = str(sq.get("id") or "")
        entry = fresh_e.get(qid) or reuse_e.get(qid)
        if entry is None:
            logger.warning("修订子问题 %s 无可用数据，已从规划中剔除", qid)
            continue
        entries.append(entry)
        log = fresh_l.get(qid) or reuse_l.get(qid)
        if log is not None:
            logs.append(log)
        available.add(qid)
        kept_questions.append(sq)

    new_plan["subQuestions"] = kept_questions
    new_plan["sections"] = [
        sec for sec in (new_plan.get("sections") or [])
        if isinstance(sec, dict)
        and (not str(sec.get("ref") or "").strip() or str(sec.get("ref")) in available)
    ]
    return entries, logs, available


async def _replan_incremental(plan: Dict[str, Any], entries: List[Dict[str, Any]],
                              sql_log: List[Dict[str, Any]], meta: Dict[str, Any],
                              query: str) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    """修订延续式重规划 + 只补取新增子问题。

    产出 ("progress"/"dataset", payload) 事件，最终产出
    ("__result__", {plan, entries, sqlLog})。任何一步失败都退化为
    「纯呈现重设计」（沿用父 plan 与父数据包），绝不阻断修订。
    """
    def fallback() -> Tuple[str, Dict[str, Any]]:
        return ("__result__", {"plan": plan, "entries": entries, "sqlLog": sql_log})

    replan_started = time.monotonic()
    try:
        planner = Planner(meta)
        new_plan = await asyncio.to_thread(planner.plan, query, "", plan)
        logger.info("阶段耗时 修订延续规划=%d ms", _elapsed_ms(replan_started))
    except Exception as exc:
        logger.warning("修订延续规划失败，退化为纯呈现重设计: %s", exc)
        yield fallback()
        return

    if (not isinstance(new_plan, dict) or new_plan.get("intent") != "data_page"
            or new_plan.get("_fallback") or new_plan.get("_planner_error")):
        logger.warning("修订延续规划未产出有效计划，退化为纯呈现重设计")
        yield fallback()
        return

    added = _diff_sub_questions(plan, new_plan)
    new_entries: List[Dict[str, Any]] = []
    new_logs: List[Dict[str, Any]] = []
    if added:
        logger.info("修订检出新增/变更子问题 %s，开始增量取数",
                    [str(sq.get("id")) for sq in added])
        yield ("progress", {"stage": "research",
                            "message": f"检测到新增数据需求，正在补充取数（{len(added)} 项）…"})
        entity_scope, entity_hits = _resolve_entity_scope(query, new_plan, meta)
        async for kind, payload in _research_all({"subQuestions": added}, meta, query,
                                                 entity_scope, entity_hits):
            if kind == "dataset":
                yield ("dataset", payload)
            elif kind == "error-item":
                yield ("progress", {"stage": "research",
                                    "message": f"部分数据查询失败：{payload.get('message')}"})
            elif kind == "__datasets__":
                new_entries, new_logs = payload["entries"], payload["sqlLog"]
    else:
        logger.info("修订未检出新增数据需求，仅重排呈现")

    merged_entries, merged_logs, available = _merge_incremental(
        new_plan, entries, sql_log, new_entries, new_logs)
    if not merged_entries:
        logger.warning("增量取数后无任何可用数据，退化为纯呈现重设计")
        yield fallback()
        return
    yield ("__result__", {"plan": new_plan, "entries": merged_entries,
                          "sqlLog": merged_logs, "availableIds": available})


async def generate_stream(page: PageRecord, meta: Dict[str, Any],
                          query: str, database_id: str = "") -> AsyncIterator[Dict[str, Any]]:
    """生成流程主循环。

    Args:
        page: 已初始化的页面记录（pageId/user/team 就绪，status=generating）
        meta: /export/for-llm 元数据
        query: 用户问题（修订场景即反馈意见）
        database_id: 可选数据源限定
    Yields:
        SSE 事件 dict：{"event": ..., "data": ...}
    """
    def ev(event: str, **data) -> Dict[str, Any]:
        return {"event": event, "data": {"pageId": page.pageId, **data}}

    # ── 修订场景：复用父页面规划与数据包 ──
    parent = None
    if page.parentId:
        parent_item = page_store.get_page(page.parentId)
        if parent_item:
            parent = PageRecord.from_store(parent_item)
        if not parent or not parent.dataBundle:
            page.status = "failed"
            page.error = "找不到可修订的历史页面或其数据包"
            _save(page)
            yield ev("error", message=page.error)
            return

    if parent:
        # 修订继承父页面的取数上下文与页面元数据：新页面记录必须自带 plan/dataBundle/intent，
        # 否则离开当前会话后（重新加载、卡片切换）前端拿不到 intent 与数据包 ——
        # 表现为 intent='' 走占位符、dataBundle={} 无数据，即"修改后的页面打不开、不显示"。
        plan = dict(parent.plan or {})
        bundle = dict(parent.dataBundle or {})
        entries = [e for e in (bundle.get("datasets") or []) if isinstance(e, dict)]
        sql_log = [s for s in (parent.sqlLog or []) if isinstance(s, dict)]
        page.plan = plan
        page.intent = parent.intent or "data_page"
        page.title = parent.title or str(plan.get("title") or query[:25])
        page.dataBundle = bundle
        page.sqlLog = sql_log
        _save(page)
        yield ev("plan", plan=_public_plan(plan), title=page.title, reused=True)

        # ── 修订增量取数：延续式重规划，只为修改意见带来的新数据需求补取数据 ──
        # 「加入飞行轨迹」这类意见本质是取数需求；只换呈现的修订链路永远无法生效。
        # 已有子问题原样沿用（直接继承父条目，不重复查询），仅新增/变更的口径重新取数。
        yield ev("progress", stage="plan", message="正在按修改意见延续规划…")
        original_plan = plan
        result: Dict[str, Any] = {}
        async for kind, payload in _replan_incremental(plan, entries, sql_log, meta, query):
            if kind == "progress":
                yield ev("progress", **payload)
            elif kind == "dataset":
                yield ev("dataset", **payload)
            elif kind == "__result__":
                result = payload
        plan = result.get("plan") or original_plan
        entries = result.get("entries") or entries
        sql_log = result.get("sqlLog") or sql_log
        # 数据包按原始页面问题重建：航迹带时间时重算时间轴，动态演示才有据可依
        bundle = {
            "question": str((parent.dataBundle or {}).get("question") or query),
            "generatedAt": _now(),
            "dataSourceId": str((parent.dataBundle or {}).get("dataSourceId") or database_id),
            "datasets": entries,
        }
        map_timeline = build_map_timeline(entries)
        if map_timeline:
            bundle["mapTimeline"] = map_timeline
        page.plan = plan
        page.dataBundle = bundle
        page.sqlLog = sql_log
        _save(page)
        if plan is not original_plan:
            yield ev("plan", plan=_public_plan(plan), title=page.title)
    else:
        # ── 阶段一：Planner ──
        yield ev("progress", stage="plan", message="正在分析问题并规划页面结构…")
        plan_started = time.monotonic()
        try:
            planner = Planner(meta)
            parent_query = ""
            plan = await asyncio.to_thread(planner.plan, query, parent_query)
            logger.info("阶段耗时 规划(Planner)=%d ms", _elapsed_ms(plan_started))
        except Exception as exc:
            logger.error("Planner 异常: %s", exc)
            page.status = "failed"
            page.error = f"规划失败: {exc}"
            _save(page)
            yield ev("error", message=page.error)
            return

        page.plan = plan
        if plan.get("intent") == "general":
            page.intent = "general"
            page.directAnswer = str(plan.get("directAnswer") or "")
            page.title = plan.get("title") or query[:25]
            page.status = "ready"
            _save(page)
            yield ev("direct", directAnswer=page.directAnswer, title=page.title)
            yield ev("done", status="ready", intent="general")
            return

        page.title = str(plan.get("title") or query[:25])
        page.intent = "data_page"
        _save(page)
        yield ev("plan", plan=_public_plan(plan), title=page.title)

        # ── 阶段二：Researcher 并行取数 ──
        # 实体过滤解析（通用 value linking）：把问题中的分类/名称等实体词解析为
        # 事实表外键 ID 白名单；未命中任何维度值时返回空，取数行为与现状完全一致。
        filter_started = time.monotonic()
        entity_scope, entity_hits = _resolve_entity_scope(query, plan, meta)
        logger.info("阶段耗时 实体过滤=%d ms", _elapsed_ms(filter_started))
        if entity_scope:
            logger.info("本次提问命中实体过滤: %s", entity_hits)
        yield ev("progress", stage="research", message="正在查询数据集…")
        entries, sql_log = [], []
        research_started = time.monotonic()
        async for kind, payload in _research_all(plan, meta, query, entity_scope, entity_hits):
            if kind == "dataset":
                yield ev("dataset", **payload)
            elif kind == "error-item":
                yield ev("progress", stage="research",
                         message=f"部分数据查询失败：{payload.get('message')}")
            elif kind == "__datasets__":
                entries, sql_log = payload["entries"], payload["sqlLog"]
        logger.info("阶段耗时 取数(全部 %d 个子问题)=%d ms",
                    len(plan.get("subQuestions") or []), _elapsed_ms(research_started))

        if not entries:
            page.status = "failed"
            page.error = "所有数据集取数均失败，无法生成页面"
            _save(page)
            yield ev("error", message=page.error)
            return

        bundle = {
            "question": query,
            "generatedAt": _now(),
            "dataSourceId": database_id,
            "datasets": entries,
        }
        # 跨数据集时间轴（有带时间航迹时才存在；page-kit 据此自动渲染时间轴控件）
        map_timeline = build_map_timeline(entries)
        if map_timeline:
            bundle["mapTimeline"] = map_timeline
        page.dataBundle = bundle
        page.sqlLog = sql_log
        _save(page)

    # ── 阶段三：PageWriter（生成 + Guard + 兜底 / 修订）──
    yield ev("progress", stage="write", message="数据就绪，正在生成交互页面…")
    writer = PageWriter()
    write_started = time.monotonic()
    try:
        if parent:
            # 修订 = 带修改意见的重新设计：复用（增量补齐后的）数据包，旧 HTML 不回灌模型；
            # 页面「用户问题」用原始问题，修改意见单独作为反馈传入
            html, write_meta = await asyncio.to_thread(
                writer.redesign, str(bundle.get("question") or query),
                plan, bundle, parent.html, query)
        else:
            html, write_meta = await asyncio.to_thread(
                writer.generate, query, plan, bundle)
    except Exception as exc:
        logger.error("PageWriter 异常: %s", exc)
        page.status = "failed"
        page.error = f"页面生成失败: {exc}"
        _save(page)
        yield ev("error", message=page.error)
        return

    logger.info("阶段耗时 页面写作=%d ms usedTemplate=%s revised=%s 页面长度=%d",
                _elapsed_ms(write_started), bool(write_meta.get("usedTemplate")),
                bool(write_meta.get("revised")), len(html or ""))
    page.html = html
    page.status = "ready"
    if write_meta.get("usedTemplate"):
        page.error = "template_fallback"
    else:
        page.error = ""
    _save(page)

    yield ev("page", title=page.title, html=html, bundle=bundle, plan=_public_plan(plan),
             usedTemplate=bool(write_meta.get("usedTemplate")),
             revised=bool(write_meta.get("revised")),
             guardIssues=write_meta.get("issues", []))
    yield ev("done", status="ready", intent=page.intent or "data_page",
             usedTemplate=bool(write_meta.get("usedTemplate")),
             isRevision=bool(parent),
             revised=bool(write_meta.get("revised")),
             guardIssues=write_meta.get("issues", []))


def _public_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """剥离规划内部标记后下发前端。"""
    return {k: v for k, v in (plan or {}).items()
            if k not in ("_fallback", "_planner_error")}


def fetch_meta(database_id: str = "") -> Dict[str, Any]:
    """拉取数据集元数据（同步，供 main 层在线程中调用）。"""
    return admin_client.query_datasets_meta(database_id)


def _resolve_entity_scope(query: str, plan: Dict[str, Any],
                          meta: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
    """构建本次提问的实体过滤白名单（失败一律降级为不过滤，不阻断主流程）。

    Returns:
        (scope, hits_desc)：scope={tableName: {column: set(允许值)}}，
        hits_desc 供日志/提示使用。
    """
    try:
        schemas = (meta.get("data", {}) or {}).get("schemas", []) \
            if isinstance(meta, dict) else []
        ds_table = {
            str((s or {}).get("datasetId") or (s or {}).get("id") or ""):
                str((s or {}).get("tableName") or "")
            for s in schemas if isinstance(s, dict)
        }
        target_tables = []
        for sq in plan.get("subQuestions") or []:
            table = ds_table.get(str((sq or {}).get("datasetId") or ""))
            if table and table not in target_tables:
                target_tables.append(table)
        graph = dimension_graph.DimensionGraph.build(meta)
        return entity_filter.resolve_scope(query, graph, target_tables)
    except Exception as exc:
        logger.warning("实体过滤解析异常，本次不做实体过滤: %s", exc)
        return {}, []
