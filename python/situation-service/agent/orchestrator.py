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
    return {
        "layerId": layer_id,
        "points": points,
        "routes": routes,
        "areas": areas,
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
    yield "map_layer", _map_payload(profile)

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
) -> AsyncIterator[SSEEvent]:
    """Phase 2 真实生成（LLM tool-calling）。Phase 1 未启用。

    时序约束与 mock 一致：图表 → 地图 → narrative。
    待接入 llm_client.call_llm_with_tools + tools 派发。
    """
    raise NotImplementedError("Phase 2: 真实 LLM Agent 编排待实现")


# 对外入口：Phase 1 用 mock，Phase 2 切换为 real
async def generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """态势生成入口。Phase 1 走 mock，Phase 2 替换为 real_generate。"""
    async for evt in mock_generate(query, report_id, skill_context):
        yield evt
