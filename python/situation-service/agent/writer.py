"""Writer Agents —— 合成层（态势图 Agent 架构重构 v1.1 阶段 3）。

设计目标（参见方案文档 §4.2.4）：
- chart Writer：并行 N 个，每个 chartSpec 一个 LLM 调用，读 EvidenceStore 产出 ECharts option
- map Writer（地图生成链路重构）：确定性管线，地图内容 100% 来自 map_builder 对
  带地理画像（GeoProfile）证据的构建；LLM 备选分支已删除（空图层的唯一来源）。
  地图存在性由数据决定：hasGeo=False 的证据不进管线，features=0 的图层返回 None
- narrative Writer：最后串行，读 EvidenceStore + chart 元数据，按 ADR-08 撰写"介绍 + 逐图说明"

并发模型：
- chart 与 map 用 asyncio.gather 并行（受 SITUATION_MAX_CONCURRENT 节流）
- narrative 必须等 chart + map 完成后串行（解决 P2：文本与图表脱节）
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from agent import prompts, map_builder, artifact_postprocess
from agent.evidence_store import ChartMetadata, Evidence, EvidenceStore
from llm_client import call_llm_json, call_llm

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
        # 统一用 evidence.id 作为关联 key，与 dataset 事件的 datasetId 对齐，
        # 供前端全量重建时 chart.datasetRef 精确命中 dataset.datasetId。
        "datasetRef": evidence.id,
        "fieldMapping": raw.get("fieldMapping") or {},
        "explanation": str(raw.get("explanation") or intent or ""),
        # 携带证据定位信息，供 verifier 校验 fieldMapping 列名是否存在、前端关联真实数据
        "provenance": {
            "evidenceId": evidence.id,
            "datasetId": evidence.dataset_ref,
            "columns": evidence.columns,
        },
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


def map_feature_count(map_layer: Optional[Dict[str, Any]]) -> int:
    """图层要素总数（点+线+面+圆）。

    图层有效性唯一口径（地图生成链路重构 §2.3）：map_layer 有效 ⇔ features ≥ 1。
    供 writer / verifier / layout_postprocess 共用，消灭口径漂移。
    """
    if not isinstance(map_layer, dict):
        return 0
    return sum(
        len(map_layer.get(kind) or [])
        for kind in ("points", "routes", "areas", "circles")
    )


async def write_map(
    store: EvidenceStore,
    profile: Dict[str, Any],
    field_labels: Optional[Dict[str, Dict[str, str]]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """map Writer（确定性管线）：地图内容唯一来源是 map_builder。

    重构要点（地图生成链路重构 §4.4）：
    - 只处理携带有效地理画像（geoProfile.hasGeo=True）的证据，无坐标数据不进管线；
    - 不再走 LLM 地图备选分支（原空图层来源，已删除）；
    - 产出即刻判有效：features ≥ 1 才返回图层，否则返回 (None, "")。

    Args:
        store: 共享 EvidenceStore（证据 meta 已带 geoProfile）
        profile: Skill profile（保留参数以兼容调用方）
        field_labels: 可选 {datasetId: {英文字段名: 中文标签}}，供 map_builder 生成 propLabels

    Returns:
        (map_layer_dict, evidence_id) —— map_layer 为 None 表示本次无地图（数据决定）
    """
    for evidence in store.list_evidences():
        if not evidence.rows:
            continue
        # 地理画像门槛：hasGeo=False 的证据不进管线（口径同源，不再各自判断）
        geo = (evidence.meta or {}).get("geoProfile") or {}
        if not geo.get("hasGeo"):
            continue

        labels = {}
        if field_labels:
            labels = field_labels.get(evidence.dataset_ref) or field_labels.get(evidence.source) or {}
        try:
            annotations = map_builder.build_map_annotations(evidence.rows, field_labels=labels)
        except Exception as exc:
            logger.warning("map_builder 处理证据 %s 失败: %s", evidence.id, exc)
            continue

        if not annotations:
            continue
        points = annotations.get("points") or []
        routes = annotations.get("routes") or []
        areas = annotations.get("areas") or []
        circles = annotations.get("circles") or []

        map_layer = {
            "layerId": f"layer_{evidence.id}",
            "datasetRef": evidence.id,
            "points": points,
            "routes": routes,
            "areas": areas,
            "circles": circles,
            "layerConfig": {
                "name": f"数据集 {evidence.source}",
                "type": "routes" if routes else "points",
                "supportedTypes": ["points", "routes", "areas", "circles"],
                "color": "#8b5cf6",
                "opacity": 0.85,
                "visible": True,
            },
        }
        # 有效性唯一口径：features ≥ 1；空图层直接无地图（不再返回"空但非 None"的层）
        if map_feature_count(map_layer) < 1:
            logger.info("证据 %s 坐标列存在但未产出有效要素，跳过地图", evidence.id)
            continue
        logger.info(
            "map Writer 产出有效图层: evidence=%s points=%s routes=%s",
            evidence.id, len(points), len(routes),
        )
        return map_layer, evidence.id

    return None, ""


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

    # 地图说明确定性打底（地图生成链路重构 §4.5）：
    # 有图层 → 真实要素统计；无图层 → 判断是否存在带坐标的证据，明确说明而非留空
    if map_layer:
        map_base = f"地图展示 {len(routes)} 条路线、{len(points)} 个标点。" if (routes or points) else ""
    else:
        has_geo_evidence = any(
            ((ev.meta or {}).get("geoProfile") or {}).get("hasGeo") for ev in store.list_evidences()
        )
        map_base = (
            "本数据集含地理坐标但未产出有效图层。"
            if has_geo_evidence
            else "本数据集无地理坐标字段，未生成地图。"
        )

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
            "mapExplanation": map_base,
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
        # LLM 地图说明优先，缺省时回退确定性统计（杜绝空串占位）
        "mapExplanation": str(raw.get("mapExplanation") or "") or map_base,
    }


async def write_layout(
    query: str,
    store: EvidenceStore,
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """layout Writer（可选增强，NARRATIVE 之后串行）：LLM 产页面布局树。

    输入只有产物元信息（数据源无关）：图表清单 / 图层要素统计 / 数据集列名与行数。
    返回 LLM 原始布局树（未经校验）；调用方需经 layout_postprocess.sanitize_layout
    修复后方可使用。LLM 失败返回 None（前端回退固定布局）。
    """
    if not charts and not map_layer:
        return None

    # 数据集元信息：evidence id / 摘要 / 列名 / 行数（不含表名与 SQL，数据源无关）
    datasets = [
        {
            "datasetId": ev.id,
            "summary": ev.summary or ev.sub_question,
            "columns": list(ev.columns or []),
            "rowCount": int(ev.meta.get("totalRows", len(ev.rows)) or 0),
        }
        for ev in store.list_evidences()
        if ev.rows
    ]

    messages = prompts.build_layout_messages(
        query,
        [
            {
                "chartId": c.get("chartId", ""),
                "type": c.get("type", ""),
                "title": c.get("title", ""),
                "explanation": c.get("explanation", ""),
                "datasetRef": c.get("datasetRef", ""),
            }
            for c in charts
        ],
        map_layer,
        datasets,
        narrative,
    )

    try:
        # 布局是小型结构化 JSON：禁用 thinking，温度略高（0.5）增加布局多样性
        raw = await asyncio.to_thread(
            call_llm_json,
            messages,
            0.5,
            min(config.LLM_MAX_TOKENS, 4000),
            "disabled",
        )
    except Exception as exc:
        logger.warning("layout LLM 调用失败: %s", exc)
        return None

    if not isinstance(raw, dict):
        logger.warning("layout LLM 返回非对象: %s", type(raw).__name__)
        return None
    return raw


async def write_artifact(
    query: str,
    store: EvidenceStore,
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
) -> Optional[str]:
    """HTML Artifact Writer（优先于布局树，NARRATIVE 之后串行）：LLM 产整页 HTML 排版。

    返回清洗校验后的完整 HTML；LLM 失败或校验整体不通过返回 None（调用方回退布局树）。
    校验发现的引用类问题（非法 chartId 等）带错误信息 Reflection 重写一次。
    """
    if not charts and not map_layer:
        return None

    # 数据集元信息 + 列名映射（kpi 指标列白名单，与布局树 metrics 同口径）
    datasets = [
        {
            "datasetId": ev.id,
            "summary": ev.summary or ev.sub_question,
            "columns": list(ev.columns or []),
            "rowCount": int(ev.meta.get("totalRows", len(ev.rows)) or 0),
        }
        for ev in store.list_evidences()
        if ev.rows
    ]
    dataset_columns = {d["datasetId"]: set(d["columns"]) for d in datasets}

    messages = prompts.build_artifact_messages(
        query,
        [
            {
                "chartId": c.get("chartId", ""),
                "type": c.get("type", ""),
                "title": c.get("title", ""),
                "explanation": c.get("explanation", ""),
                "datasetRef": c.get("datasetRef", ""),
            }
            for c in charts
        ],
        map_layer,
        datasets,
        narrative,
    )

    # 整页 HTML 属于自由文本输出（非 JSON）：用 call_llm 原文返回，禁用 thinking
    def _generate(reflect_msgs):
        return call_llm(
            reflect_msgs,
            0.4,
            min(config.LLM_MAX_TOKENS, 12000),
            "disabled",
        )

    try:
        raw = await asyncio.to_thread(_generate, messages)
    except Exception as exc:
        logger.warning("artifact LLM 调用失败: %s", exc)
        return None

    result = artifact_postprocess.sanitize_artifact(raw, charts, map_layer, dataset_columns)
    if result is None:
        logger.warning("artifact 清洗后为空，回退布局树")
        return None

    # Reflection：校验发现引用类问题时，带错误信息重写一次
    if result.get("issues"):
        logger.info("artifact 校验发现问题，Reflection 重写: %s", "; ".join(result["issues"]))
        reflect_msgs = list(messages) + [
            {"role": "assistant", "content": result["html"][:4000]},
            {"role": "user", "content": (
                "你上一次输出的 HTML 存在以下问题：\n- "
                + "\n- ".join(result["issues"][:8])
                + "\n\n请重新输出完整 HTML，修复上述问题（chartId/datasetId 必须逐字来自清单，"
                  "有地图必须放恰好一个 map 占位符，每个图表至少一个 chart 占位符）。"
                  "仍然只返回纯 HTML。"
            )},
        ]
        try:
            raw2 = await asyncio.to_thread(_generate, reflect_msgs)
            result2 = artifact_postprocess.sanitize_artifact(
                raw2, charts, map_layer, dataset_columns)
            # 重写结果问题数更少才采纳；否则保留首次补齐结果（已可用）
            if result2 is not None and len(result2.get("issues") or []) < len(result["issues"]):
                result = result2
        except Exception as exc:
            logger.warning("artifact Reflection 重写失败（保留首次结果）: %s", exc)

    logger.info(
        "artifact 生成完成（剩余自动修复项 %s 个）", len(result.get("issues") or []))
    return result["html"]


__all__ = [
    "write_single_chart",
    "write_charts_parallel",
    "write_map",
    "write_narrative",
    "write_layout",
    "write_artifact",
]
