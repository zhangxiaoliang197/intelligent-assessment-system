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


def _query_dataset_with_sql(
    ds_id: str,
    query: str,
    schema: Optional[Dict[str, Any]],
    intent: str,
    limit: int,
) -> Dict[str, Any]:
    """Phase 2 取数：优先用 LLM 生成精确 SQL 执行，失败回退整表查询。

    复用评估分析 Text-to-SQL 能力（LLM 生成 WHERE/聚合/GROUP BY），
    只有 schema 无字段元数据或 SQL 生成/执行失败时才回退原 query_admin_data，
    保证态势图整体流程（5 阶段）不因取数方式升级而中断。
    """
    from agent import tools

    # 无 schema 或字段元数据 → 直接回退原整表/预定义查询
    if not schema or not schema.get("fields"):
        return tools.query_admin_data(ds_id, limit)

    from llm_client import call_llm_json
    from agent import prompts

    try:
        sql_result = call_llm_json(
            prompts.build_sql_messages(query, schema, intent),
            0.3,
            config.LLM_MAX_TOKENS,
        )
        sql = ""
        if isinstance(sql_result, dict):
            sql = str(sql_result.get("sql") or "").strip()
        elif isinstance(sql_result, str):
            sql = sql_result.strip()
        if not sql:
            logger.warning("LLM 未生成 SQL，回退整表查询: datasetId=%s", ds_id)
            return tools.query_admin_data(ds_id, limit)
    except Exception as exc:
        logger.warning("SQL 生成失败，回退整表查询: datasetId=%s err=%s", ds_id, exc)
        return tools.query_admin_data(ds_id, limit)

    data = tools.execute_dataset_sql(ds_id, sql)
    if not data.get("success"):
        logger.warning(
            "SQL 执行失败，回退整表查询: datasetId=%s sql=%s err=%s",
            ds_id, sql[:200], data.get("message", "")[:200],
        )
        return tools.query_admin_data(ds_id, limit)

    # 统一字段：execute-sql 返回 rowCount，而 /dataset/{id}/data 返回 total，
    # 补齐 total 供下游（dataset 事件 / _format_data）统一读取。
    if "total" not in data and "rowCount" in data:
        data["total"] = data["rowCount"]
    return data


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

        # ── 阶段2：取数（LLM 生成精确 SQL 后执行，替代整表拉取）──
        stage = "data"
        data_context: Dict[str, Any] = {}
        # 建立 datasetId → schema 映射，供 SQL 生成使用（/export/for-llm 已含字段与表名）
        schemas_by_id: Dict[str, Any] = {}
        if isinstance(meta, dict):
            meta_data = meta.get("data") or {}
            for s in (meta_data.get("schemas") or []):
                if isinstance(s, dict) and s.get("datasetId"):
                    schemas_by_id[s["datasetId"]] = s

        for ds in datasets_plan:
            ds_id = ds.get("datasetId", "")
            if not ds_id:
                continue
            intent = ds.get("intent", "") or ""
            limit = int(ds.get("limit", config.DATA_QUERY_LIMIT))
            schema = schemas_by_id.get(ds_id)
            data = await asyncio.to_thread(
                _query_dataset_with_sql, ds_id, query, schema, intent, limit,
            )
            data_context[ds_id] = data
            yield "dataset", {
                "datasetId": ds_id,
                "source": intent or ds_id,
                "summary": f"数据集 {ds_id}（{data.get('total', 0)} 行）",
                "rows": data.get("total", 0),
                # 全量数据下发：前端据此用 fieldMapping 全量渲染，替代 LLM 内联样本
                "columns": data.get("columns", []),
                "data": data.get("rows", []),
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
        # 组合：优先用 map_builder 扫描全量数据自动标注（对齐评估分析 _auto_build_map_annotations），
        # 生成完整 points/routes/areas/circles 并携带业务 props；无地理列或失败时，
        # 回退到阶段3已并行取到的 LLM 地图图层（map_layer，含热力图能力）。
        try:
            from agent import map_builder
            for ds_id, data in data_context.items():
                rows = data.get("rows", []) if isinstance(data, dict) else []
                ann = map_builder.build_map_annotations(rows)
                if ann and (ann.get("points") or ann.get("routes") or ann.get("areas") or ann.get("circles")):
                    map_layer = {
                        "layerId": f"ds_{ds_id}",
                        "datasetRef": ds_id,
                        "points": ann.get("points", []),
                        "routes": ann.get("routes", []),
                        "areas": ann.get("areas", []),
                        "circles": ann.get("circles", []),
                        "layerConfig": {
                            "name": f"数据集 {ds_id}",
                            "type": "points",
                            "supportedTypes": ["points", "routes", "areas", "circles"],
                            "color": "#8b5cf6",
                            "opacity": 0.85,
                            "visible": True,
                        },
                    }
                    break
        except Exception as exc:
            logger.warning("map_builder 自动标注失败，回退 LLM 地图: %s", exc)

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
