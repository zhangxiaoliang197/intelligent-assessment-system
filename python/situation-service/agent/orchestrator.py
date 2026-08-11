"""态势生成编排器。

Phase 1 mock_generate：canned 数据按文档时序流式推送，验证前端管线。
Phase 2 real_generate：多阶段 JSON 协议，LLM 驱动，取真实数据产出态势图。

时序约束（ADR-08）：图表/地图先出，文本为介绍+说明，最后产出。
real_generate 阶段：plan → dataset(取真实数据) → chart(逐个) → map_layer → narrative → done
同步 LLM/HTTP 调用通过 asyncio.to_thread 包装，避免阻塞事件循环。
"""
import asyncio
import logging
from typing import AsyncIterator

from stream.sse import SSEEvent
import config

logger = logging.getLogger("situation-service")


# ──────────────────────────────────────────────────────────
# Phase 1: mock 生成器（canned 数据，验证管线用）
# ──────────────────────────────────────────────────────────
async def mock_generate(query: str, report_id: str) -> AsyncIterator[SSEEvent]:
    """Phase 1 mock 生成器。按时序 yield 事件：plan → dataset → chart → map_layer → narrative → done。"""
    interval = config.MOCK_STREAM_INTERVAL

    await asyncio.sleep(interval)
    yield "plan", {
        "datasets": ["ds_indicator", "ds_knowledge"],
        "chartsPlan": [
            {"type": "line", "title": "近30天损耗趋势"},
            {"type": "pie", "title": "装备类型分布"},
            {"type": "radar", "title": "战备维度对比"},
        ],
        "mapPlan": [{"layerId": "loss_area"}],
    }

    await asyncio.sleep(interval)
    yield "dataset", {"datasetId": "ds_indicator", "source": "indicator",
                      "summary": f"基于提问「{query}」获取的近30天指标数据", "rows": 30}
    await asyncio.sleep(interval)
    yield "dataset", {"datasetId": "ds_knowledge", "source": "knowledge",
                      "summary": "知识库检索到的态势相关条目", "rows": 12}

    await asyncio.sleep(interval)
    yield "chart", {
        "chartId": "c_1", "type": "line", "title": "近30天损耗趋势",
        "option": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [f"D{i}" for i in range(1, 31)]},
            "yAxis": {"type": "value", "name": "损耗量"},
            "series": [{"name": "损耗", "type": "line", "smooth": True,
                        "data": [12, 15, 11, 18, 22, 19, 25, 30, 28, 35, 40, 38, 33, 36, 42,
                                 48, 45, 60, 55, 50, 47, 52, 58, 63, 59, 66, 70, 68, 72, 75],
                        "areaStyle": {}}],
        },
        "datasetRef": "ds_indicator",
    }
    await asyncio.sleep(interval)
    yield "chart", {
        "chartId": "c_2", "type": "pie", "title": "装备类型分布",
        "option": {
            "tooltip": {"trigger": "item"}, "legend": {"bottom": 0},
            "series": [{"type": "pie", "radius": ["40%", "70%"],
                        "data": [{"value": 1048, "name": "装甲"}, {"value": 735, "name": "通信"},
                                 {"value": 580, "name": "后勤"}, {"value": 484, "name": "防空"},
                                 {"value": 300, "name": "其他"}]}],
        },
        "datasetRef": "ds_indicator",
    }
    await asyncio.sleep(interval)
    yield "chart", {
        "chartId": "c_3", "type": "radar", "title": "战备维度对比",
        "option": {
            "tooltip": {},
            "radar": {"indicator": [{"name": "人员", "max": 100}, {"name": "装备", "max": 100},
                                    {"name": "训练", "max": 100}, {"name": "后勤", "max": 100},
                                    {"name": "指挥", "max": 100}]},
            "series": [{"type": "radar",
                        "data": [{"value": [82, 75, 88, 70, 90], "name": "当前"},
                                 {"value": [70, 68, 75, 65, 80], "name": "基线"}]}],
        },
        "datasetRef": "ds_indicator",
    }

    await asyncio.sleep(interval)
    yield "map_layer", {
        "layerId": "loss_area",
        "points": [
            {"name": "A 区域", "lng": 116.40, "lat": 39.90, "raw": "A区域部署点"},
            {"name": "B 区域", "lng": 121.47, "lat": 31.23, "raw": "B区域部署点"},
            {"name": "C 区域", "lng": 113.27, "lat": 23.13, "raw": "C区域部署点"},
            {"name": "D 区域", "lng": 108.95, "lat": 34.27, "raw": "D区域部署点"},
        ],
        "routes": [], "areas": [],
        "circles": [{"name": "C 区域雷达覆盖", "center": {"lng": 113.27, "lat": 23.13}, "radiusKm": 120}],
        "layerConfig": {"color": "#e74c3c", "opacity": 0.85},
    }

    await asyncio.sleep(interval)
    yield "narrative", {
        "intro": f"针对「{query}」，当前态势整体呈现：近30天损耗呈上升趋势，"
                 f"装备类型以装甲与通信为主，战备各维度总体优于基线，A/B 区域点位需重点关注。",
        "explanations": [
            {"chartId": "c_1", "text": "折线展示近30天损耗量，第18天出现峰值，之后高位震荡。"},
            {"chartId": "c_2", "text": "饼图展示装备类型占比，装甲类占比最高（约 34%）。"},
            {"chartId": "c_3", "text": "雷达图对比当前与基线，指挥与人员维度提升明显，后勤略低。"},
        ],
    }

    await asyncio.sleep(interval)
    yield "done", {"reportId": report_id, "status": "ready", "partial": False}
    logger.info("mock 生成完成: reportId=%s", report_id)


# ──────────────────────────────────────────────────────────
# Phase 2: 真实生成器（LLM 多阶段 JSON 协议）
# ──────────────────────────────────────────────────────────
async def real_generate(query: str, report_id: str) -> AsyncIterator[SSEEvent]:
    """Phase 2 真实生成（LLM 驱动，取真实数据）。

    阶段：
      1. plan      取数据集元数据 → LLM 规划要查什么、画什么
      2. dataset   按 plan 调 admin-service 取真实数据行
      3. chart     LLM 基于真实数据生成 ECharts option（逐个 yield，先于文本）
      4. map_layer LLM 生成地图标注（WGS84）
      5. narrative LLM 撰写态势介绍 + 逐图说明（最后）
      6. done

    同步 LLM/HTTP 调用用 asyncio.to_thread 包装，避免阻塞事件循环。
    数据源无关：通过 /export/for-llm 发现数据集，不硬编码任何表名/字段。
    """
    # 延迟导入避免循环依赖
    from agent import tools, prompts
    from llm_client import call_llm_json

    max_tokens = config.LLM_MAX_TOKENS

    # ── 阶段1：规划 ──
    logger.info("[real] 阶段1 规划: reportId=%s query=%s", report_id, query[:50])
    meta = await asyncio.to_thread(tools.query_datasets_meta)
    plan = await asyncio.to_thread(
        call_llm_json, prompts.build_plan_messages(query, meta), 0.3, max_tokens
    )
    # 容错：plan 可能缺字段
    plan = plan if isinstance(plan, dict) else {}
    plan.setdefault("datasets", [])
    plan.setdefault("chartsPlan", [])
    plan.setdefault("mapPlan", [])
    yield "plan", plan

    # ── 阶段2：取真实数据 ──
    data_context: dict = {}
    for req in plan["datasets"]:
        ds_id = req.get("datasetId", "") if isinstance(req, dict) else str(req)
        if not ds_id:
            continue
        limit = config.DATA_QUERY_LIMIT
        if isinstance(req, dict) and req.get("limit"):
            try:
                limit = min(int(req["limit"]), 1000)
            except (ValueError, TypeError):
                pass
        logger.info("[real] 阶段2 取数: datasetId=%s limit=%s", ds_id, limit)
        data = await asyncio.to_thread(tools.query_admin_data, ds_id, limit)
        data_context[ds_id] = data
        yield "dataset", {
            "datasetId": ds_id,
            "source": "admin_dataset",
            "summary": req.get("intent", "") if isinstance(req, dict) else "",
            "rows": data.get("total", 0) if data.get("success") else 0,
            "columns": data.get("columns", []) if data.get("success") else [],
            "error": data.get("message") if not data.get("success") else None,
        }

    # 知识库检索（规划要求时）
    if plan.get("needKnowledge"):
        kq = plan.get("knowledgeQuery") or query
        logger.info("[real] 阶段2 知识检索: %s", kq[:50])
        knowledge = await asyncio.to_thread(tools.query_knowledge, kq, 5)
        data_context["__knowledge__"] = knowledge
        yield "dataset", {
            "datasetId": "__knowledge__",
            "source": "knowledge",
            "summary": f"知识库检索：{kq[:60]}",
            "rows": len(knowledge.get("results", [])) if knowledge.get("success") else 0,
        }

    # ── 阶段3：产图（先于文本，ADR-08）──
    logger.info("[real] 阶段3 产图: reportId=%s", report_id)
    charts = await asyncio.to_thread(
        call_llm_json, prompts.build_chart_messages(query, data_context, plan), 0.3, max_tokens
    )
    # 容错：LLM 可能返回单对象而非数组
    if isinstance(charts, dict):
        charts = [charts]
    if not isinstance(charts, list):
        charts = []
    for c in charts:
        if isinstance(c, dict):
            yield "chart", c

    # ── 阶段4：地图 ──
    logger.info("[real] 阶段4 地图: reportId=%s", report_id)
    map_layer = await asyncio.to_thread(
        call_llm_json, prompts.build_map_messages(query, data_context), 0.3, max_tokens
    )
    if isinstance(map_layer, dict):
        map_layer.setdefault("layerId", "main")
        map_layer.setdefault("points", [])
        map_layer.setdefault("routes", [])
        map_layer.setdefault("areas", [])
        map_layer.setdefault("circles", [])
        map_layer.setdefault("layerConfig", {})
        yield "map_layer", map_layer

    # ── 阶段5：文本（最后产出）──
    logger.info("[real] 阶段5 文本: reportId=%s", report_id)
    narrative = await asyncio.to_thread(
        call_llm_json, prompts.build_narrative_messages(query, charts, map_layer if isinstance(map_layer, dict) else {}),
        0.4, max_tokens
    )
    if isinstance(narrative, dict):
        narrative.setdefault("intro", "")
        narrative.setdefault("explanations", [])
        yield "narrative", narrative

    # ── 阶段6：完成 ──
    yield "done", {"reportId": report_id, "status": "ready", "partial": False}
    logger.info("[real] 生成完成: reportId=%s charts=%d", report_id, len(charts))


# ──────────────────────────────────────────────────────────
# 对外入口：按配置切换 mock / real
# ──────────────────────────────────────────────────────────
async def generate(query: str, report_id: str) -> AsyncIterator[SSEEvent]:
    """态势生成入口。默认 Phase 2 真实生成；SITUATION_USE_MOCK=true 回退 mock。"""
    if config.USE_MOCK.lower() == "true":
        logger.info("使用 mock 生成模式 (SITUATION_USE_MOCK=true)")
        async for evt in mock_generate(query, report_id):
            yield evt
        return
    async for evt in real_generate(query, report_id):
        yield evt
