"""Writer Agents —— 合成层（态势图 Agent 架构重构 v1.1 阶段 3）。

设计目标（参见方案文档 §4.2.4）：
- chart Writer：并行 N 个，每个 chartSpec 一个 LLM 调用，读 EvidenceStore 产出 ECharts option
- map Writer（v1.1 冻结）：不改动 map_builder / build_map_messages / _verify_map_coordinates，
  仅把调用从内联拆为独立 task，与 chart 并行
- narrative Writer：最后串行，读 EvidenceStore + chart 元数据，按 ADR-08 撰写"介绍 + 逐图说明"

并发模型：
- chart 与 map 用 asyncio.gather 并行（受 SITUATION_MAX_CONCURRENT 节流）
- narrative 必须等 chart + map 完成后串行（解决 P2：文本与图表脱节）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from agent import prompts, map_builder
from agent.evidence_store import ChartMetadata, Evidence, EvidenceStore
from llm_client import call_llm_json

logger = logging.getLogger("situation-service")

# 与 orchestrator._CHART_TYPES 对齐（避免循环导入）
_CHART_TYPES = {"bar", "line", "pie", "radar", "gauge", "scatter", "heatmap", "relation", "sankey", "map"}


def _allowed_chart_types(profile: Dict[str, Any]) -> List[str]:
    skill_types = profile.get("chartTypes") or []
    allowed = [t.lower() for t in skill_types if t.lower() in _CHART_TYPES]
    return allowed or sorted(_CHART_TYPES)


def _safe_echarts_option(option: Any) -> dict:
    """简单校验：option 必须是 dict 且含 series。详细校验由 Verifier 完成。"""
    if not isinstance(option, dict):
        return {}
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return option  # 让 Verifier 拦截
    return option


async def write_single_chart(
    query: str,
    chart_spec: Dict[str, Any],
    store: EvidenceStore,
    profile: Dict[str, Any],
    semaphore: Optional[asyncio.Semaphore] = None,
) -> Optional[Dict[str, Any]]:
    """单个 chart Writer：1 chartSpec + 1 Evidence → 1 chart dict。

    Args:
        query: 用户原始问题
        chart_spec: Planner 输出的图表规格（id/type/title/subQuestionRef/intent）
        store: 共享 EvidenceStore
        profile: Skill profile
        semaphore: 并发节流信号量

    Returns:
        chart dict（含 chartId/type/title/option/datasetRef/fieldMapping/explanation）；
        失败返回 None（由调用方决定是否走 fallback）
    """
    chart_id = str(chart_spec.get("id") or "").strip()
    expected_type = str(chart_spec.get("type") or "bar").lower()
    title = str(chart_spec.get("title") or "").strip()
    intent = str(chart_spec.get("intent") or "").strip()
    sub_q_ref = str(chart_spec.get("subQuestionRef") or "").strip()

    # 取对应证据
    evidence = store.get_evidence(sub_q_ref) if sub_q_ref else None
    if not evidence:
        # 子问题未取到数据，跳过此图（保留位置但不产出）
        logger.warning("chart %s 引用的子问题 %s 无证据，跳过", chart_id, sub_q_ref)
        return None

    # 证据为空时跳过（避免 LLM 编造）
    if not evidence.rows:
        logger.warning("chart %s 引用的证据 %s 数据为空，跳过", chart_id, sub_q_ref)
        return None

    # 格式化证据文本（复用 prompts._format_data 的思路，但基于 Evidence 对象）
    evidence_payload = {
        "success": True,
        "columns": evidence.columns,
        "rows": evidence.rows,
        "total": evidence.meta.get("totalRows", len(evidence.rows)),
    }
    evidence_text = prompts._format_data(evidence_payload, max_rows=30)
    evidence_text = f"摘要：{evidence.summary}\n{evidence_text}"

    allowed = _allowed_chart_types(profile)
    messages = prompts.build_single_chart_messages(query, chart_spec, evidence_text, allowed)

    async def _call():
        return await asyncio.to_thread(
            call_llm_json,
            messages,
            0.2,
            config.LLM_MAX_TOKENS,
            # 图表产出不需要深度思考链：deepseek-v4-flash 等推理模型的
            # reasoning 会优先耗光 max_tokens，导致 content 被截断为空。
            # 显式禁用 thinking，保证 ECharts option 能完整输出在 token 内。
            "disabled",
        )

    if semaphore is not None:
        async with semaphore:
            raw = await _call()
    else:
        raw = await _call()

    if not isinstance(raw, dict):
        logger.warning("chart %s LLM 返回非对象: %s", chart_id, type(raw).__name__)
        return None

    option = _safe_echarts_option(raw.get("option"))
    if not option:
        logger.warning("chart %s option 为空或非法", chart_id)
        return None

    actual_type = str(raw.get("type") or expected_type).lower()
    if actual_type not in _CHART_TYPES:
        actual_type = expected_type

    chart = {
        "chartId": chart_id or str(raw.get("chartId") or ""),
        "type": actual_type,
        "title": str(raw.get("title") or title),
        "option": option,
        "datasetRef": str(raw.get("datasetRef") or evidence.dataset_ref or ""),
        "fieldMapping": raw.get("fieldMapping") or {},
        "explanation": str(raw.get("explanation") or intent or ""),
    }

    # 写回 chart metadata 到 EvidenceStore（供 narrative 反向引用）
    await store.add_chart_metadata(ChartMetadata(
        chart_id=chart["chartId"],
        title=chart["title"],
        chart_type=chart["type"],
        explanation=chart["explanation"],
        dataset_ref=chart["datasetRef"],
        field_mapping=chart["fieldMapping"],
        verified=False,
    ))
    return chart


async def write_charts_parallel(
    query: str,
    chart_specs: List[Dict[str, Any]],
    store: EvidenceStore,
    profile: Dict[str, Any],
    max_concurrent: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """并行扇出：所有 chartSpec 并发执行。

    策略：每个 chartSpec 一个 write_single_chart 任务，asyncio.gather 汇总。
    失败的 chart 从结果中剔除（保留成功的）。
    """
    if not chart_specs:
        return []

    concurrency = max_concurrent or config.SITUATION_MAX_CONCURRENT
    semaphore = asyncio.Semaphore(max(1, concurrency))

    tasks = [
        write_single_chart(query, spec, store, profile, semaphore)
        for spec in chart_specs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    charts = []
    for index, result in enumerate(results, start=1):
        if isinstance(result, dict) and result:
            # 补 chartId（如果 LLM 漏了）
            if not result.get("chartId"):
                result["chartId"] = f"c_{index}"
            charts.append(result)
        else:
            logger.warning("chart 编号 %s 产出为空", index)
    return charts


async def write_map(
    query: str,
    store: EvidenceStore,
    profile: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """map Writer（v1.1 冻结）：复用现有 map_builder + LLM 地图备选链路。

    不修改 map_builder.py / build_map_messages / _verify_map_coordinates，
    仅把调用从 orchestrator._run_llm_orchestration 内联拆出为独立 task。

    Returns:
        (map_layer_dict, dataset_ref) —— map_layer 为 None 表示无地理数据可绘
    """
    # 1) 优先用 map_builder 自动标注（确定性）
    for evidence in store.list_evidences():
        try:
            annotations = map_builder.build_map_annotations(evidence.rows)
        except Exception as exc:
            logger.warning("map_builder 处理证据 %s 失败: %s", evidence.id, exc)
            continue

        if not annotations:
            continue
        points = annotations.get("points") or []
        routes = annotations.get("routes") or []
        areas = annotations.get("areas") or []
        circles = annotations.get("circles") or []
        if not (points or routes or areas or circles):
            continue

        map_layer = {
            "layerId": f"layer_{evidence.id}",
            "datasetRef": evidence.dataset_ref,
            "points": points,
            "routes": routes,
            "areas": areas,
            "circles": circles,
            "layerConfig": {
                "name": f"数据集 {evidence.source}",
                "type": "points",
                "supportedTypes": ["points", "routes", "areas", "circles"],
                "color": "#8b5cf6",
                "opacity": 0.85,
                "visible": True,
            },
        }
        return map_layer, evidence.dataset_ref

    # 2) map_builder 未生成 → 走 LLM 地图备选（保留现有 prompt）
    # data_context 格式与 build_map_messages 期望一致：{datasetId: {success/columns/rows/total}}
    data_context = {}
    for ev in store.list_evidences():
        if not ev.rows:
            continue
        data_context[ev.id] = {
            "success": True,
            "columns": ev.columns,
            "rows": ev.rows,
            "total": ev.meta.get("totalRows", len(ev.rows)),
        }
    if not data_context:
        return None, ""

    try:
        raw = await asyncio.to_thread(
            call_llm_json,
            prompts.build_map_messages(query, data_context),
            0.2,
            config.LLM_MAX_TOKENS,
            # 与图表 Writer 一致：禁用 thinking 链，避免推理耗尽 token 无内容
            "disabled",
        )
    except Exception as exc:
        logger.warning("map LLM 调用失败: %s", exc)
        return None, ""

    if not isinstance(raw, dict):
        return None, ""

    map_layer = {
        "layerId": str(raw.get("layerId") or "main"),
        "datasetRef": str(raw.get("datasetRef") or ""),
        "points": raw.get("points") or [],
        "routes": raw.get("routes") or [],
        "areas": raw.get("areas") or [],
        "circles": raw.get("circles") or [],
        "fieldMapping": raw.get("fieldMapping") or {},
        "layerConfig": raw.get("layerConfig") or {"type": "points", "color": "#e74c3c", "opacity": 0.85},
    }
    return map_layer, map_layer.get("datasetRef", "")


async def write_narrative(
    query: str,
    store: EvidenceStore,
    map_layer: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """narrative Writer（最后串行）：读 EvidenceStore + chart 元数据 + map 元数据。

    与 orchestrator._run_llm_orchestration 的 narrative 阶段对齐，但数据源改为
    EvidenceStore 的 chart_metadata（解决 P2：narrative 看不到实际产出图表）。
    """
    chart_meta_list = store.list_chart_metadata()
    charts_summary = "\n".join(
        f"- {m.chart_id}: {m.title}（{m.chart_type}）—— {m.explanation}"
        for m in chart_meta_list
    ) or "（无图表）"

    points = map_layer.get("points", []) if map_layer else []
    routes = map_layer.get("routes", []) if map_layer else []
    areas = map_layer.get("areas", []) if map_layer else []
    circles = map_layer.get("circles", []) if map_layer else []
    if map_layer:
        map_summary = (
            f"图层 {map_layer.get('layerId', '')}：{len(points)} 个标点、{len(routes)} 条路线、"
            f"{len(areas)} 个区域、{len(circles)} 个圆形区域"
        )
    else:
        map_summary = "（无地图）"

    messages = prompts.build_narrative_messages(
        query,
        [{"chartId": m.chart_id, "title": m.title, "explanation": m.explanation} for m in chart_meta_list],
        map_layer,
    )

    try:
        raw = await asyncio.to_thread(
            call_llm_json,
            messages,
            0.3,
            min(config.LLM_MAX_TOKENS, 6000),
            "",
        )
    except Exception as exc:
        logger.warning("narrative LLM 调用失败: %s", exc)
        # 兜底：用 chart metadata 拼接最小 narrative
        return {
            "intro": f"已围绕用户问题汇聚真实数据，共生成了 {len(chart_meta_list)} 张图表。",
            "explanations": [
                {"chartId": m.chart_id, "text": m.explanation or f"该图使用 {m.dataset_ref} 的真实数据生成。"}
                for m in chart_meta_list
            ],
            "mapExplanation": "" if not map_layer else f"地图展示了 {len(points)} 个标点。",
        }

    if not isinstance(raw, dict):
        raw = {}

    # 强制 explanations 命中实际产出的 chartId（解决 P2）
    valid_chart_ids = {m.chart_id for m in chart_meta_list}
    raw_explanations = raw.get("explanations")
    explanations = []
    if isinstance(raw_explanations, list):
        for item in raw_explanations:
            if isinstance(item, dict) and str(item.get("chartId")) in valid_chart_ids:
                explanations.append({
                    "chartId": str(item["chartId"]),
                    "text": str(item.get("text") or ""),
                })

    # 补全缺失图表的 explanation
    covered_ids = {e["chartId"] for e in explanations}
    for m in chart_meta_list:
        if m.chart_id not in covered_ids:
            explanations.append({
                "chartId": m.chart_id,
                "text": m.explanation or f"该图使用 {m.dataset_ref} 的真实数据生成。",
            })

    return {
        "intro": str(raw.get("intro") or f"已围绕用户问题汇聚真实数据，共生成了 {len(chart_meta_list)} 张图表。"),
        "explanations": explanations,
        "mapExplanation": str(raw.get("mapExplanation") or ""),
    }


__all__ = [
    "write_single_chart",
    "write_charts_parallel",
    "write_map",
    "write_narrative",
]
