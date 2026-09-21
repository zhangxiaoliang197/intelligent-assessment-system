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
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
from agent import prompts, map_builder, artifact_postprocess, tools
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

    # LLM 调用与解析段整体隔离：单图异常记日志返回 None，不向外传播
    #（双保险，防御 gather 之外的调用路径；gather 内已由 return_exceptions=True 兜底）
    try:
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
    except Exception as exc:
        logger.warning("chart %s 产图异常: %s", chart_id, exc)
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
    # 任务级异常隔离：单图失败不应中止整批（return_exceptions=True + 逐项过滤），
    # 与 docstring 声明的「失败的 chart 从结果中剔除（保留成功的）」策略对齐
    results = await asyncio.gather(*tasks, return_exceptions=True)

    charts = []
    for index, result in enumerate(results, start=1):
        if isinstance(result, Exception):
            logger.warning("chart 编号 %s 产出异常: %s", index, result)
            continue
        if isinstance(result, dict) and result:
            # 补 chartId（如果 LLM 漏了）
            if not result.get("chartId"):
                result["chartId"] = f"c_{index}"
            charts.append(result)
        else:
            logger.warning("chart 编号 %s 产出为空", index)
    # option 规范化管线（纯规则零 LLM）：防标签重叠/图例补全/大数据采样/配色补齐，
    # 数据值不做任何修改；Reflection 重写的图同样经此管线（写图路径唯一出口）。
    if config.SITUATION_CHART_POLISH_ENABLED:
        try:
            from agent import chart_polish
            charts = chart_polish.polish_charts(charts)
        except Exception as exc:
            logger.warning("chart 规范化管线异常（使用原始 option）: %s", exc)
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


async def _fetch_table_name(dataset_id: str) -> str:
    """取数据集物理表名（用于匹配 subject_profile 的 track_table）。

    同步 HTTP 调用包成协程，避免阻塞事件循环；失败返回空字符串（调用方降级）。
    """
    if not dataset_id:
        return ""
    try:
        result = await asyncio.to_thread(tools.fetch_dataset_structure, dataset_id)
        if isinstance(result, dict):
            return str(result.get("tableName") or "")
    except Exception as exc:
        logger.warning("fetch_dataset_structure 失败 datasetId=%s err=%s", dataset_id, exc)
    return ""


def _parse_as_of(temporal_context: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """从 temporal_context 解析 as_of 时间（用于能力圈航迹位置插值）。

    优先取 asOf（as_of 模式下的点时间），否则取 end（区间的右边界）。
    返回 datetime 或 None（无活跃时间上下文时不画动态圈）。
    """
    if not isinstance(temporal_context, dict) or not temporal_context.get("active"):
        return None
    raw = temporal_context.get("asOf") or temporal_context.get("end") or ""
    raw = str(raw or "").strip()
    if not raw:
        return None
    # temporal.py 已用 _iso() 输出 ISO8601 字符串，含时区后缀（如 +08:00）
    # Python datetime.fromisoformat 支持带偏移的 ISO 串
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        # 兜底：兼容不带时区的纯日期串
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        logger.warning("as_of 时间解析失败: %s", raw)
        return None


async def _fetch_full_table(dataset_id: str, table_name: str) -> List[Dict[str, Any]]:
    """取物理表全量数据（用于 Python 内存 JOIN 档案字段）。

    通过 dataset 关联的数据库执行 SELECT * —— 因航迹表 + 主体档案表 + 机型档案表
    通常位于同一业务数据库，可复用航迹表的 dataset 连接执行查询。
    返回 rows 列表；失败返回空列表（调用方降级跳过 enrich）。
    """
    if not dataset_id or not table_name:
        return []
    # 表名白名单校验：仅允许字母/数字/下划线，杜绝 SQL 注入
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$", table_name):
        logger.warning("表名 %s 不符白名单，拒绝 SELECT *", table_name)
        return []
    sql = f"SELECT * FROM {table_name}"
    try:
        result = await asyncio.to_thread(tools.execute_dataset_sql, dataset_id, sql)
    except Exception as exc:
        logger.warning("取档案表 %s 失败 datasetId=%s err=%s", table_name, dataset_id, exc)
        return []
    if not isinstance(result, dict) or not result.get("success"):
        logger.warning("取档案表 %s 失败: %s", table_name,
                       result.get("message", "") if isinstance(result, dict) else "")
        return []
    rows = result.get("rows") or []
    return rows if isinstance(rows, list) else []


async def _enrich_rows_with_profile(
    evidence: Evidence,
    profile: Dict[str, Any],
    table_name: str = "",
) -> List[Dict[str, Any]]:
    """按 profile 在 Python 内存中合并主体档案表 + 机型档案表数据。

    背景：evidence.rows 是单表查询结果（含 LLM SQL 的过滤/聚合），不含档案表的
    radius 字段。这里负责按 profile 配置主动取 subject_table + radius_source.table
    全量数据，按 join_key 做字典 join，把档案字段（callsign/faction/radius 等）
    附加到每行 evidence.rows 的副本上。

    设计权衡：
    - 内存 join 而非数据库 JOIN SQL：保留 LLM 过滤结果，不重取航迹数据；
    - 失败降级：取档案表失败 → 返回原 evidence.rows（map_builder 走原通用识别）；
    - 不修改原 row：构造新 row 副本，避免污染 EvidenceStore 中的原始证据。

    Args:
        evidence: 证据对象（rows 为航迹表过滤后数据）
        profile: resolve_profile 命中的 subject_profile
        table_name: evidence 对应的物理表名（用于判断用 join_key 还是 enemy_join_key）

    Returns:
        enriched_rows: 含档案字段的行列表；失败时返回 evidence.rows 原值
    """
    if not evidence.rows or not profile:
        return evidence.rows

    # 根据 evidence 的物理表名选择外键字段（我方 vs 敌方航迹表）
    join_key = str(profile.get("join_key") or "aircraft_id")
    if table_name and str(table_name).lower() == str(profile.get("enemy_track_table") or "").lower():
        join_key = str(profile.get("enemy_join_key") or join_key)

    subject_table = str(profile.get("subject_table") or "")
    radius_source = profile.get("radius_source") or {}
    radius_table = str(radius_source.get("table") or "")
    radius_join = str(radius_source.get("join") or "")
    radius_fields = radius_source.get("fields") or []
    subject_name_field = str(profile.get("subject_name") or "")
    faction_field = str(profile.get("faction_field") or "faction")

    # 1) 并行取主体档案表 + 机型档案表
    dataset_id = evidence.dataset_ref or evidence.source
    coros = []
    if subject_table:
        coros.append(_fetch_full_table(dataset_id, subject_table))
    if radius_table and radius_table != subject_table:
        coros.append(_fetch_full_table(dataset_id, radius_table))
    if not coros:
        return evidence.rows
    try:
        results = await asyncio.gather(*coros, return_exceptions=True)
    except Exception as exc:
        logger.warning("enrich 取档案表异常 evidence=%s err=%s", evidence.id, exc)
        return evidence.rows

    # 拆解 gather 结果（按 coros 顺序）
    subject_rows: List[Dict[str, Any]] = []
    type_rows: List[Dict[str, Any]] = []
    cursor = 0
    if subject_table:
        r = results[cursor]
        cursor += 1
        if isinstance(r, list):
            subject_rows = r
        else:
            logger.warning("enrich subject_rows 取回非列表 evidence=%s", evidence.id)
    if radius_table and radius_table != subject_table:
        r = results[cursor]
        if isinstance(r, list):
            type_rows = r
        else:
            logger.warning("enrich type_rows 取回非列表 evidence=%s", evidence.id)

    if not subject_rows and not type_rows:
        logger.info("enrich 无可用档案数据 evidence=%s，走原通用识别", evidence.id)
        return evidence.rows

    # 2) 索引档案表：subject_by_id / type_by_id
    subject_by_id: Dict[str, Dict[str, Any]] = {}
    if subject_rows and isinstance(subject_rows[0], dict):
        # join_key 在 subject_table 中即 aircraft_id（主键），按其建索引
        for row in subject_rows:
            sid = str(row.get(join_key) or row.get("aircraft_id") or "")
            if sid:
                subject_by_id[sid] = row

    type_by_id: Dict[str, Dict[str, Any]] = {}
    if type_rows and isinstance(type_rows[0], dict):
        for row in type_rows:
            tid = str(row.get(radius_join) or "")
            if tid:
                type_by_id[tid] = row

    # 3) 遍历 evidence.rows，附加档案字段
    enriched: List[Dict[str, Any]] = []
    match_count = 0
    for row in evidence.rows:
        if not isinstance(row, dict):
            enriched.append(row)
            continue
        new_row = dict(row)  # 不修改原 row
        sid = str(row.get(join_key) or "")
        if not sid:
            enriched.append(new_row)
            continue
        subject = subject_by_id.get(sid)
        if subject:
            match_count += 1
            # 附加 subject_name（如 callsign）—— 若 row 已有则不覆盖
            if subject_name_field and subject_name_field not in new_row:
                v = subject.get(subject_name_field)
                if v is not None:
                    new_row[subject_name_field] = v
            # 附加 faction —— 若 row 已有则不覆盖
            if faction_field and faction_field not in new_row:
                v = subject.get(faction_field)
                if v is not None:
                    new_row[faction_field] = v
            # 通过 subject 的 radius_join（如 type_id）取机型档案表
            tid = str(subject.get(radius_join) or "")
            type_record = type_by_id.get(tid) if tid else None
            if type_record:
                # 附加所有 radius 字段（recon_radius_km / strike_radius_km 等）
                for rf in radius_fields:
                    field_name = str(rf.get("field") or "")
                    if field_name and field_name not in new_row:
                        v = type_record.get(field_name)
                        if v is not None:
                            new_row[field_name] = v
        enriched.append(new_row)

    logger.info(
        "enrich 完成 evidence=%s subject_id 命中 %s/%s 行（subject_rows=%s type_rows=%s）",
        evidence.id, match_count, len(evidence.rows),
        len(subject_by_id), len(type_by_id),
    )
    return enriched


async def write_map(
    store: EvidenceStore,
    profile: Dict[str, Any],
    field_labels: Optional[Dict[str, Dict[str, str]]] = None,
    temporal_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """map Writer（确定性管线）：地图内容唯一来源是 map_builder。

    重构要点（地图生成链路重构 §4.4）：
    - 只处理携带有效地理画像（geoProfile.hasGeo=True）的证据，无坐标数据不进管线；
    - 不再走 LLM 地图备选分支（原空图层来源，已删除）；
    - 产出即刻判有效：features ≥ 1 才返回图层，否则返回 (None, "")。

    动态能力圈接入（v1.2 新增，参见方案文档 §3）：
    - 若 evidence 对应物理表命中 subject_profiles.yaml 中的主题 profile，
      则按 profile 主动 JOIN 主体档案表 + 机型档案表，把 radius 字段补到 rows；
    - 配合 temporal_context.as_of 在 map_builder 内部按时间切片生成动态能力圈
      （一架主体一个圈，圆心随主体在 as_of 时点的位置移动）；
    - 主题未命中或档案取数失败 → 走原通用识别逻辑（无动态圈），保证向后兼容。

    Args:
        store: 共享 EvidenceStore（证据 meta 已带 geoProfile）
        profile: Skill profile（保留参数以兼容调用方）
        field_labels: 可选 {datasetId: {英文字段名: 中文标签}}，供 map_builder 生成 propLabels
        temporal_context: 可选时间上下文（含 asOf/end/active），命中主题时用于 as_of 切片

    Returns:
        (map_layer_dict, evidence_id) —— map_layer 为 None 表示本次无地图（数据决定）
    """
    # 解析时间上下文为 as_of datetime（无活跃时间则 None，不画动态圈）
    as_of = _parse_as_of(temporal_context)

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

        # ── 主题 profile 命中 + 档案数据 enrich（动态能力圈前置条件） ──
        # 取 evidence 对应物理表名，匹配 subject_profiles.yaml 中的主题 profile。
        # 命中时按 profile 主动 JOIN 主体档案表 + 机型档案表，把 radius 字段
        # 补到 rows，map_builder 才能按 as_of 时间切片生成动态能力圈
        # （一架主体一个圈，圆心随主体位置移动）。
        subject_profile: Optional[Dict[str, Any]] = None
        enriched_rows = evidence.rows
        table_name = await _fetch_table_name(evidence.dataset_ref)
        if table_name:
            subject_profile = map_builder.resolve_profile(
                evidence.rows, {"table_name": table_name}
            )
        if subject_profile:
            enriched_rows = await _enrich_rows_with_profile(
                evidence, subject_profile, table_name,
            )
            logger.info(
                "evidence %s 命中主题 profile=%s，已 enrich rows（%s → %s 行）",
                evidence.id, subject_profile.get("_profile_key"),
                len(evidence.rows), len(enriched_rows),
            )

        try:
            annotations = map_builder.build_map_annotations(
                enriched_rows,
                field_labels=labels,
                profile=subject_profile,
                as_of=as_of,
            )
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
    tokens: Optional[Dict[str, Any]] = None,
    semantic: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """HTML Artifact Writer（优先于布局树，NARRATIVE 之后串行）：LLM 产整页 HTML 排版。

    返回清洗校验后的完整 HTML；LLM 失败或校验整体不通过返回 None（调用方回退布局树）。
    校验发现的引用类问题（非法 chartId 等）带错误信息 Reflection 重写一次。

    Args:
        tokens: 主题令牌 dict（style_tokens 产物，注入排版 prompt；None=不注入）
        semantic: ABT 叙事标签 {"polarity", "focus"}（注入叙事指导；None=不注入）
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
        tokens=tokens,
        semantic=semantic,
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


# 占位符标签正则：提取 (data-sit 类型, data-ref) 契约签名，防止增量修订破坏占位符
_SIT_TAG_RE = re.compile(r'<[^>]*\bdata-sit="([a-z_]+)"[^>]*>')


def _sit_signature(html: str) -> List[Tuple[str, str]]:
    """提取占位符契约签名：(data-sit 类型, data-ref) 序列（保持出现顺序）。

    增量修订前后签名必须完全一致——修订只许调样式布局，不许增删改占位符。
    """
    sig: List[Tuple[str, str]] = []
    for m in _SIT_TAG_RE.finditer(html or ""):
        tag = m.group(0)
        ref_m = re.search(r'\bdata-ref="([^"]*)"', tag)
        sig.append((m.group(1), ref_m.group(1) if ref_m else ""))
    return sig


async def revise_artifact(
    html: str,
    issues: List[Dict[str, Any]],
    query: str,
    store: EvidenceStore,
    charts: List[Dict[str, Any]],
    map_layer: Optional[Dict[str, Any]],
    narrative: Optional[Dict[str, Any]],
) -> Optional[str]:
    """HTML Artifact 增量修订（视觉反馈循环 §四）：按视觉诊断项做定向小步修订。

    与 write_artifact 内的 Reflection 重写不同：输入是已有完整 HTML + 最多 3 项
    定向诊断（位置/元素/改法），只允许调 CSS 与布局结构。修订前后的占位符契约
    签名必须逐字一致，否则拒绝采纳（返回 None，调用方保留当前最佳）。

    Args:
        html: 当前最佳的完整 HTML（骨架渲染或 LLM 自定义产物）
        issues: VLM 诊断项 [{"location", "element", "fix"}]
        query: 用户原始问题（保持排版 prompt 上下文完整）
        store: 共享 EvidenceStore（构建 kpi 白名单与 dataset_columns）
        charts: 已产出图表列表
        map_layer: 地图图层 dict（可为 None）
        narrative: 文本产物

    Returns:
        清洗校验后的完整 HTML；LLM 失败、清洗为空或契约被破坏时返回 None
    """
    clean_issues = [
        {"location": str(i.get("location") or ""), "element": str(i.get("element") or ""),
         "fix": str(i.get("fix") or "")}
        for i in (issues or []) if isinstance(i, dict) and str(i.get("fix") or "").strip()
    ]
    if not html or not clean_issues:
        return None
    before_sig = _sit_signature(html)

    # 数据集元信息与 write_artifact 同源同口径，保证清洗校验白名单一致
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
    issue_lines = "\n".join(
        f'- 位置「{i["location"]}」 元素「{i["element"]}」 建议改法：{i["fix"]}'
        for i in clean_issues
    )
    messages = messages + [
        {"role": "assistant", "content": html},
        {"role": "user", "content": (
            "以上是你此前输出的整页排版。视觉评审员对页面截图给出了以下定向诊断：\n"
            f"{issue_lines}\n\n"
            "请针对这些诊断做最小化修订（Tenten 小步补丁原则）：\n"
            "1. 只调整 CSS 样式与布局结构（间距/栅格/尺寸/层次/配色），不改动数据内容语义；\n"
            "2. 所有 data-sit 占位符（chart/map/kpi/narrative 等）必须原样保留："
            "不增、不删、不改 data-ref 与 data-metrics 属性值；\n"
            "3. 保持单文件自包含（内联 <style>、禁止 <script>），DOCTYPE 完整；\n"
            "4. 直接输出修订后的完整 HTML，不要任何解释文字或 markdown 标记。"
        )},
    ]

    try:
        raw = await asyncio.to_thread(
            call_llm, messages, 0.25, min(config.LLM_MAX_TOKENS, 12000), "disabled",
        )
    except Exception as exc:
        logger.warning("artifact 增量修订 LLM 调用失败: %s", exc)
        return None

    result = artifact_postprocess.sanitize_artifact(raw, charts, map_layer, dataset_columns)
    if result is None:
        logger.warning("artifact 增量修订清洗后为空，保留当前最佳")
        return None
    # 契约 gate：占位符签名逐字一致才采纳（vanja.io 契约先行）
    after_sig = _sit_signature(result["html"])
    if after_sig != before_sig:
        logger.warning(
            "artifact 增量修订破坏占位符契约（前 %s 处 → 后 %s 处），拒绝采纳",
            len(before_sig), len(after_sig),
        )
        return None
    logger.info(
        "artifact 增量修订完成（剩余自动修复项 %s 个）", len(result.get("issues") or []))
    return result["html"]


__all__ = [
    "write_single_chart",
    "write_charts_parallel",
    "write_map",
    "write_narrative",
    "write_layout",
    "write_artifact",
    "revise_artifact",
]
