"""态势生成编排器。

real_generate 按 5 阶段 LLM 编排（见 tools.py / prompts.py）：
plan → data → chart → map → narrative，图表/地图先出、文本最后（ADR-08）。
"""
import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

from stream.sse import SSEEvent
import config

logger = logging.getLogger("situation-service")


async def real_generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    data_source_id: str = "",
) -> AsyncIterator[SSEEvent]:
    """真实生成（5 阶段 LLM 编排，多阶段 JSON 协议）。

    时序约束（ADR-08）：图表/地图先出，文本为介绍+说明，最后产出。
    阶段：
      1. plan     LLM 据数据集元数据规划要查什么、画什么
      2. data     编排器按 plan 取真实数据行（非 LLM）
      3. chart    LLM 基于真实数据一次性生成 ECharts option 与逐图说明
      4. map      LLM 基于数据生成地图标注（WGS84）
      5. narrative LLM 撰写态势介绍 + 地图说明

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
        plan_max_tokens, plan_thinking = config.get_llm_params("plan")
        plan = await asyncio.to_thread(
            call_llm_json,
            prompts.build_plan_messages(query, meta),
            0.3,
            plan_max_tokens,
            plan_thinking,
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

        # ── 阶段3 + 阶段4：产图与地图并行 ──
        # chart 与 map 都只依赖阶段2的取数结果（data_context），彼此无依赖，
        # 并行发起可缩短总耗时；yield 顺序仍保持「图表先于地图」以符合 ADR-08。
        chart_max_tokens, chart_thinking = config.get_llm_params("chart")
        map_max_tokens, map_thinking = config.get_llm_params("map")
        stage = "chart/map"
        charts, map_layer = await asyncio.gather(
            asyncio.to_thread(
                call_llm_json,
                prompts.build_chart_messages(query, data_context, plan),
                0.3,
                chart_max_tokens,
                chart_thinking,
            ),
            asyncio.to_thread(
                call_llm_json,
                prompts.build_map_messages(query, data_context),
                0.3,
                map_max_tokens,
                map_thinking,
            ),
        )

        stage = "chart"
        if not isinstance(charts, list):
            charts = [charts] if charts else []
        for c in charts:
            if isinstance(c, dict):
                yield "chart", c

        stage = "map"
        if isinstance(map_layer, dict):
            yield "map_layer", map_layer

        # ── 阶段5：文本（态势介绍 + 地图说明，逐图说明已在产图阶段随图生成）──
        stage = "narrative"
        narrative_max_tokens, narrative_thinking = config.get_llm_params("narrative")
        narrative = await asyncio.to_thread(
            call_llm_json,
            prompts.build_narrative_messages(query, charts, map_layer if isinstance(map_layer, dict) else {}),
            0.5,
            narrative_max_tokens,
            narrative_thinking,
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


async def generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    data_source_id: str = "",
) -> AsyncIterator[SSEEvent]:
    """态势生成入口（真实数据 + LLM 编排）。

    Args:
        data_source_id: 数据源 ID，非空时仅查该数据源的数据集 schema 与指标。
    """
    async for evt in real_generate(query, report_id, skill_context, data_source_id):
        yield evt
