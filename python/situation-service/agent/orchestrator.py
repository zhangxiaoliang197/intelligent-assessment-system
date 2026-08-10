"""态势生成编排器。

Phase 1：mock_generate 用 canned 数据按文档时序流式推送事件，
验证前端管线（图表先出 → 地图 → 文本，非结论先行，ADR-08）。
Phase 2：替换为 real_generate，走 LLM tool-calling 循环（见 tools.py / prompts.py）。
"""
import asyncio
import logging
from typing import AsyncIterator

from stream.sse import SSEEvent
import config

logger = logging.getLogger("situation-service")


async def mock_generate(query: str, report_id: str) -> AsyncIterator[SSEEvent]:
    """Phase 1 mock 生成器。

    按时序 yield 事件：
      plan → dataset → chart(逐个) → map_layer → narrative → done
    图表先于文本，满足 ADR-08。
    """
    interval = config.MOCK_STREAM_INTERVAL

    # ── 1. plan ──
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

    # ── 2. dataset（可多条）──
    await asyncio.sleep(interval)
    yield "dataset", {
        "datasetId": "ds_indicator",
        "source": "indicator",
        "summary": f"基于提问「{query}」获取的近30天指标数据",
        "rows": 30,
    }
    await asyncio.sleep(interval)
    yield "dataset", {
        "datasetId": "ds_knowledge",
        "source": "knowledge",
        "summary": "知识库检索到的态势相关条目",
        "rows": 12,
    }

    # ── 3. chart（逐个产出，先于文本）──
    await asyncio.sleep(interval)
    yield "chart", {
        "chartId": "c_1",
        "type": "line",
        "title": "近30天损耗趋势",
        "option": {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [f"D{i}" for i in range(1, 31)]},
            "yAxis": {"type": "value", "name": "损耗量"},
            "series": [{
                "name": "损耗",
                "type": "line",
                "smooth": True,
                "data": [12, 15, 11, 18, 22, 19, 25, 30, 28, 35,
                         40, 38, 33, 36, 42, 48, 45, 60, 55, 50,
                         47, 52, 58, 63, 59, 66, 70, 68, 72, 75],
                "areaStyle": {},
            }],
        },
        "datasetRef": "ds_indicator",
    }

    await asyncio.sleep(interval)
    yield "chart", {
        "chartId": "c_2",
        "type": "pie",
        "title": "装备类型分布",
        "option": {
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 0},
            "series": [{
                "type": "pie",
                "radius": ["40%", "70%"],
                "data": [
                    {"value": 1048, "name": "装甲"},
                    {"value": 735, "name": "通信"},
                    {"value": 580, "name": "后勤"},
                    {"value": 484, "name": "防空"},
                    {"value": 300, "name": "其他"},
                ],
            }],
        },
        "datasetRef": "ds_indicator",
    }

    await asyncio.sleep(interval)
    yield "chart", {
        "chartId": "c_3",
        "type": "radar",
        "title": "战备维度对比",
        "option": {
            "tooltip": {},
            "radar": {
                "indicator": [
                    {"name": "人员", "max": 100},
                    {"name": "装备", "max": 100},
                    {"name": "训练", "max": 100},
                    {"name": "后勤", "max": 100},
                    {"name": "指挥", "max": 100},
                ],
            },
            "series": [{
                "type": "radar",
                "data": [
                    {"value": [82, 75, 88, 70, 90], "name": "当前"},
                    {"value": [70, 68, 75, 65, 80], "name": "基线"},
                ],
            }],
        },
        "datasetRef": "ds_indicator",
    }

    # ── 4. map_layer（WGS84 坐标，前端 gcoord 转 GCJ02）──
    await asyncio.sleep(interval)
    yield "map_layer", {
        "layerId": "loss_area",
        "points": [
            {"name": "A 区域", "lng": 116.40, "lat": 39.90, "raw": "A区域部署点"},
            {"name": "B 区域", "lng": 121.47, "lat": 31.23, "raw": "B区域部署点"},
            {"name": "C 区域", "lng": 113.27, "lat": 23.13, "raw": "C区域部署点"},
            {"name": "D 区域", "lng": 108.95, "lat": 34.27, "raw": "D区域部署点"},
        ],
        "routes": [],
        "areas": [],
        "layerConfig": {"color": "#e74c3c", "opacity": 0.85},
    }

    # ── 5. narrative（态势介绍 + 逐图说明，最后产出）──
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

    # ── 6. done ──
    await asyncio.sleep(interval)
    yield "done", {"reportId": report_id, "status": "ready", "partial": False}
    logger.info("mock 生成完成: reportId=%s", report_id)


async def real_generate(query: str, report_id: str) -> AsyncIterator[SSEEvent]:
    """Phase 2 真实生成（LLM tool-calling）。Phase 1 未启用。

    时序约束与 mock 一致：图表 → 地图 → narrative。
    待接入 llm_client.call_llm_with_tools + tools 派发。
    """
    raise NotImplementedError("Phase 2: 真实 LLM Agent 编排待实现")


# 对外入口：Phase 1 用 mock，Phase 2 切换为 real
async def generate(query: str, report_id: str) -> AsyncIterator[SSEEvent]:
    """态势生成入口。Phase 1 走 mock，Phase 2 替换为 real_generate。"""
    async for evt in mock_generate(query, report_id):
        yield evt
