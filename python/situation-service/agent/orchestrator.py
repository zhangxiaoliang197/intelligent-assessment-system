"""态势生成编排器。

Phase 1：mock_generate 用 canned 数据按文档时序流式推送事件，
验证前端管线（图表先出 → 地图 → 文本，非结论先行，ADR-08）。
Phase 2：替换为 real_generate，走 LLM tool-calling 循环（见 tools.py / prompts.py）。
"""
import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

from stream.sse import SSEEvent
import config

logger = logging.getLogger("situation-service")


_DEFAULT_PROFILE = {
    "skillId": "",
    "skillName": "通用态势分析",
    "category": "综合态势",
    "dataSources": ["indicator", "knowledge"],
    "chartTypes": ["line", "pie", "radar"],
    "mapLayerTypes": ["points"],
    "focusMetrics": ["近30天损耗趋势", "装备类型分布", "战备维度对比"],
    "executionPlan": [
        {"sequence": 1, "name": "汇聚态势数据"},
        {"sequence": 2, "name": "生成图表与地图"},
        {"sequence": 3, "name": "撰写态势说明"},
    ],
}


def _skill_profile(skill_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    profile = dict(_DEFAULT_PROFILE)
    if skill_context:
        for field in (
            "skillId", "skillName", "category", "dataSources", "chartTypes",
            "mapLayerTypes", "focusMetrics", "executionPlan", "analysisGoal",
        ):
            if skill_context.get(field):
                profile[field] = skill_context[field]
    return profile


def _chart_option(chart_type: str, index: int, metric: str) -> Dict[str, Any]:
    """生成覆盖注册表类型的合法演示 option；真实阶段由 LLM 按数据替换。"""
    labels = ["A区域", "B区域", "C区域", "D区域", "E区域"]
    values = [72 + index * 2, 64 + index * 3, 81 - index, 58 + index * 4, 69 + index]
    if chart_type == "line":
        return {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [f"D{i}" for i in range(1, 15)]},
            "yAxis": {"type": "value", "name": metric},
            "series": [{
                "name": metric, "type": "line", "smooth": True, "areaStyle": {},
                "data": [48, 52, 51, 57, 61, 59, 64, 68, 66, 72, 70, 76, 79, 81],
            }],
        }
    if chart_type == "pie":
        return {
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 0},
            "series": [{
                "name": metric,
                "type": "pie",
                "radius": ["38%", "68%"],
                "data": [{"name": label, "value": value} for label, value in zip(labels, values)],
            }],
        }
    if chart_type == "radar":
        return {
            "tooltip": {},
            "radar": {"indicator": [{"name": label, "max": 100} for label in labels]},
            "series": [{
                "name": metric,
                "type": "radar",
                "data": [
                    {"value": values, "name": "当前"},
                    {"value": [65, 62, 70, 61, 66], "name": "基线"},
                ],
            }],
        }
    if chart_type == "gauge":
        return {
            "tooltip": {"formatter": "{b}: {c}%"},
            "series": [{
                "name": metric,
                "type": "gauge",
                "progress": {"show": True},
                "detail": {"valueAnimation": True, "formatter": "{value}%"},
                "data": [{"name": metric, "value": values[index % len(values)]}],
            }],
        }
    if chart_type == "scatter":
        return {
            "tooltip": {"trigger": "item"},
            "xAxis": {"name": "影响度", "type": "value"},
            "yAxis": {"name": metric, "type": "value"},
            "series": [{
                "name": metric,
                "type": "scatter",
                "symbolSize": 16,
                "data": [[20, 48], [35, 62], [46, 58], [60, 77], [75, 83], [86, 72]],
            }],
        }
    if chart_type == "heatmap":
        return {
            "tooltip": {"position": "top"},
            "xAxis": {"type": "category", "data": ["00时", "06时", "12时", "18时"]},
            "yAxis": {"type": "category", "data": labels[:4]},
            "visualMap": {"min": 0, "max": 100, "calculable": True, "orient": "horizontal", "left": "center"},
            "series": [{
                "name": metric,
                "type": "heatmap",
                "data": [[x, y, 35 + ((x * 17 + y * 13 + index * 7) % 60)] for y in range(4) for x in range(4)],
            }],
        }
    if chart_type == "relation":
        return {
            "tooltip": {},
            "series": [{
                "type": "graph",
                "layout": "force",
                "roam": True,
                "label": {"show": True},
                "data": [{"name": label, "symbolSize": 28 + value / 5} for label, value in zip(labels, values)],
                "links": [{"source": labels[i], "target": labels[i + 1], "value": values[i]} for i in range(4)],
            }],
        }
    if chart_type == "sankey":
        return {
            "tooltip": {"trigger": "item"},
            "series": [{
                "type": "sankey",
                "data": [{"name": label} for label in labels],
                "links": [{"source": labels[i], "target": labels[i + 1], "value": 12 + i * 5} for i in range(4)],
                "lineStyle": {"color": "gradient", "curveness": 0.5},
            }],
        }
    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": metric},
        "series": [{"name": metric, "type": "bar", "data": values}],
    }


def _map_payload(profile: Dict[str, Any]) -> Dict[str, Any]:
    layer_types = profile["mapLayerTypes"]
    layer_id = f"skill_{profile['skillId'] or 'general'}"
    points = [
        {"name": "A 区域", "lng": 116.40, "lat": 39.90, "value": 82, "raw": "A区域态势点", "_layerId": layer_id},
        {"name": "B 区域", "lng": 121.47, "lat": 31.23, "value": 67, "raw": "B区域态势点", "_layerId": layer_id},
        {"name": "C 区域", "lng": 113.27, "lat": 23.13, "value": 74, "raw": "C区域态势点", "_layerId": layer_id},
        {"name": "D 区域", "lng": 108.95, "lat": 34.27, "value": 59, "raw": "D区域态势点", "_layerId": layer_id},
    ]
    routes = []
    if any(layer_type in {"routes", "flow"} for layer_type in layer_types):
        routes = [{"name": "主要态势链路", "points": [points[0], points[3], points[2]]}]
    areas = []
    if any(layer_type in {"areas", "coverage", "heatmap"} for layer_type in layer_types):
        areas = [{
            "name": "重点关注区域",
            "_regionId": "focus-area-1",
            "points": [
                {"name": "边界1", "lng": 115.6, "lat": 40.4},
                {"name": "边界2", "lng": 117.1, "lat": 40.2},
                {"name": "边界3", "lng": 117.0, "lat": 39.2},
                {"name": "边界4", "lng": 115.7, "lat": 39.3},
            ],
        }]
    circles = []
    if any(layer_type in {"circles", "coverage", "radar"} for layer_type in layer_types):
        circles = [{
            "name": "C 区域雷达覆盖",
            "center": {"lng": 113.27, "lat": 23.13},
            "radiusKm": 120,
        }]
    return {
        "layerId": layer_id,
        "points": points,
        "routes": routes,
        "areas": areas,
        "circles": circles,
        "layerConfig": {
            "name": profile["skillName"],
            "type": layer_types[0],
            "supportedTypes": layer_types,
            "color": "#e74c3c",
            "opacity": 0.85,
            "visible": True,
        },
    }


async def mock_generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """Phase 1 mock 生成器。

    按时序 yield 事件：
      plan → dataset → chart(逐个) → map_layer → narrative → done
    图表先于文本，满足 ADR-08。
    """
    interval = config.MOCK_STREAM_INTERVAL
    profile = _skill_profile(skill_context)
    data_sources = profile["dataSources"][:4]
    chart_types = profile["chartTypes"][:3]
    focus_metrics = profile["focusMetrics"][:3]

    # ── 1. plan ──
    await asyncio.sleep(interval)
    yield "plan", {
        "skill": {
            "id": profile["skillId"],
            "name": profile["skillName"],
            "category": profile["category"],
        },
        "steps": profile["executionPlan"],
        "datasets": data_sources,
        "chartsPlan": [
            {"type": chart_type, "title": metric}
            for chart_type, metric in zip(chart_types, focus_metrics)
        ],
        "mapPlan": [{"layerId": f"skill_{profile['skillId'] or 'general'}", "types": profile["mapLayerTypes"]}],
    }

    # ── 2. dataset（可多条）──
    for index, source in enumerate(data_sources[:2], start=1):
        await asyncio.sleep(interval)
        yield "dataset", {
            "datasetId": f"ds_{index}",
            "source": source,
            "summary": f"「{profile['skillName']}」基于 {source} 获取的态势数据",
            "rows": 30 if index == 1 else 12,
        }

    # ── 3. chart（逐个产出，先于文本）──
    for index, (chart_type, metric) in enumerate(zip(chart_types, focus_metrics), start=1):
        await asyncio.sleep(interval)
        yield "chart", {
            "chartId": f"c_{index}",
            "type": chart_type,
            "title": metric,
            "option": _chart_option(chart_type, index - 1, metric),
            "datasetRef": f"ds_{1 + ((index - 1) % min(2, len(data_sources)))}",
        }

    # ── 4. map_layer（WGS84 坐标，前端 gcoord 转 GCJ02）──
    await asyncio.sleep(interval)
    map_payload = _map_payload(profile)
    yield "map_layer", map_payload

    # ── 5. narrative（态势介绍 + 逐图说明，最后产出）──
    await asyncio.sleep(interval)
    yield "narrative", {
        "intro": (
            f"已使用「{profile['skillName']}」围绕「{query}」组织当前态势。"
            f"分析从 {', '.join(focus_metrics)} 三个重点维度展开，并将关键对象映射到地图；"
            f"当前为演示数据管线，正式环境应结合数据时间和来源置信度解读。"
        ),
        "explanations": [
            {
                "chartId": f"c_{index}",
                "text": f"该图用于展示「{metric}」，请结合时间范围、数据来源和地图位置进行联动分析。",
            }
            for index, metric in enumerate(focus_metrics, start=1)
        ],
        "mapExplanation": (
            f"该地图用于展示「{query}」相关关键对象的空间分布（"
            f"{len(map_payload.get('points', []))} 个标点、{len(map_payload.get('routes', []))} 条路线、"
            f"{len(map_payload.get('areas', []))} 个区域、{len(map_payload.get('circles', []))} 个圆形区域），"
            f"请结合各图表与地图位置进行联动分析。"
        ),
    }

    # ── 6. done ──
    await asyncio.sleep(interval)
    yield "done", {
        "reportId": report_id,
        "status": "ready",
        "partial": False,
        "skillId": profile["skillId"],
        "skillName": profile["skillName"],
    }
    logger.info("mock 生成完成: reportId=%s skillId=%s", report_id, profile["skillId"] or "general")


async def real_generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    data_source_id: str = "",
) -> AsyncIterator[SSEEvent]:
    """Phase 2 真实生成（5 阶段 LLM 编排，多阶段 JSON 协议）。

    时序约束（ADR-08）：图表/地图先出，文本为介绍+说明，最后产出。
    阶段：
      1. plan     LLM 据数据集元数据规划要查什么、画什么
      2. data     编排器按 plan 取真实数据行（非 LLM）
      3. chart    LLM 基于真实数据生成 ECharts option 数组
      4. map      LLM 基于数据生成地图标注（WGS84）
      5. narrative LLM 撰写态势介绍 + 逐图说明

    Args:
        data_source_id: 数据源 ID。非空时仅查该数据源的数据集 schema 与指标。
    """
    # lazy import：避免模块加载期触发 prompts 的 map_skill_loader
    from llm_client import call_llm_json
    from agent import tools, prompts

    skill_id = (skill_context or {}).get("skillId", "")
    skill_name = (skill_context or {}).get("skillName", "通用态势分析")
    skill_category = (skill_context or {}).get("category", "综合态势")
    execution_plan = (skill_context or {}).get("executionPlan", [])
    stage = "plan"  # 当前阶段标识，用于错误定位

    try:
        # ── 阶段1：规划 ──
        meta = await asyncio.to_thread(tools.query_datasets_meta, data_source_id)
        plan = await asyncio.to_thread(
            call_llm_json,
            prompts.build_plan_messages(query, meta),
            0.3,
            config.LLM_MAX_TOKENS,
        )
        # 兼容 LLM 返回 dict 或含 plan 字段的结构
        if not isinstance(plan, dict):
            plan = {"datasets": [], "chartsPlan": [], "mapPlan": []}
        charts_plan = plan.get("chartsPlan", []) or []
        map_plan = plan.get("mapPlan", []) or []
        datasets_plan = plan.get("datasets", []) or []
        yield "plan", {
            "skill": {"id": skill_id, "name": skill_name, "category": skill_category},
            "steps": execution_plan,
            "datasets": [d.get("datasetId", "") for d in datasets_plan],
            "chartsPlan": charts_plan,
            "mapPlan": map_plan,
            # 对齐 store.applyEvent 的 plan 解析（data.plan.charts / data.plan.mapLayers）
            "plan": {"charts": charts_plan, "mapLayers": map_plan},
        }

        # ── 阶段2：取数（按 plan 查数据集，非 LLM）──
        stage = "data"
        data_context: Dict[str, Any] = {}
        for ds in datasets_plan:
            ds_id = ds.get("datasetId", "")
            if not ds_id:
                continue
            limit = int(ds.get("limit", config.DATA_QUERY_LIMIT))
            data = await asyncio.to_thread(tools.query_admin_data, ds_id, limit)
            data_context[ds_id] = data
            yield "dataset", {
                "datasetId": ds_id,
                "source": ds.get("intent", "") or ds_id,
                "summary": f"数据集 {ds_id}（{data.get('total', 0)} 行）",
                "rows": data.get("total", 0),
            }

        # 可选：知识库检索（结果暂不注入 chart/map prompt，预留扩展点）
        if plan.get("needKnowledge") and plan.get("knowledgeQuery"):
            stage = "knowledge"
            try:
                await asyncio.to_thread(tools.query_knowledge, plan["knowledgeQuery"], 5)
            except Exception as exc:
                logger.warning("知识库检索失败（不阻断主流程）: %s", exc)

        # ── 阶段3：产图 ──
        stage = "chart"
        charts = await asyncio.to_thread(
            call_llm_json,
            prompts.build_chart_messages(query, data_context, plan),
            0.3,
            config.LLM_MAX_TOKENS,
        )
        if not isinstance(charts, list):
            charts = [charts] if charts else []
        for c in charts:
            if isinstance(c, dict):
                yield "chart", c

        # ── 阶段4：地图 ──
        stage = "map"
        map_layer = await asyncio.to_thread(
            call_llm_json,
            prompts.build_map_messages(query, data_context),
            0.3,
            config.LLM_MAX_TOKENS,
        )
        if isinstance(map_layer, dict):
            yield "map_layer", map_layer

        # ── 阶段5：文本（态势介绍 + 逐图说明，最后产出）──
        stage = "narrative"
        narrative = await asyncio.to_thread(
            call_llm_json,
            prompts.build_narrative_messages(query, charts, map_layer if isinstance(map_layer, dict) else {}),
            0.5,
            config.LLM_MAX_TOKENS,
        )
        if isinstance(narrative, dict):
            yield "narrative", narrative

        yield "done", {
            "reportId": report_id,
            "status": "ready",
            "partial": False,
            "skillId": skill_id,
            "skillName": skill_name,
        }
        logger.info("real 生成完成: reportId=%s skillId=%s", report_id, skill_id or "auto")
    except Exception as e:
        logger.exception("real_generate 异常: reportId=%s stage=%s", report_id, stage)
        yield "error", {
            "stage": stage,
            "message": str(e)[:300],
            "fatal": True,
        }
        yield "done", {"reportId": report_id, "status": "failed", "partial": False}


# 对外入口：USE_MOCK=true 走 mock（canned 数据），否则走 real_generate（LLM 编排）
async def generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    data_source_id: str = "",
) -> AsyncIterator[SSEEvent]:
    """态势生成入口。

    Args:
        data_source_id: 数据源 ID，仅 real_generate 使用（过滤数据集 schema）。
    """
    if config.USE_MOCK:
        async for evt in mock_generate(query, report_id, skill_context):
            yield evt
    else:
        async for evt in real_generate(query, report_id, skill_context, data_source_id):
            yield evt
