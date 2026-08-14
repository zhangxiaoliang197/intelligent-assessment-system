"""态势生成编排器。

Phase 1：mock_generate 用 canned 数据按文档时序流式推送事件，
验证前端管线（图表先出 → 地图 → 文本，非结论先行，ADR-08）。
Phase 2：替换为 real_generate，走 LLM tool-calling 循环（见 tools.py / prompts.py）。
"""
import asyncio
import datetime as dt
import hashlib
import json
import logging
import math
import re
from typing import Any, AsyncIterator, Dict, Optional

from stream.sse import SSEEvent
import config
from agent import prompts, tools
from llm_client import call_llm_json

logger = logging.getLogger("situation-service")


_DEFAULT_PROFILE = {
    "skillId": "",
    "skillName": "通用态势分析",
    "category": "综合态势",
    "dataSources": ["admin", "indicator", "knowledge"],
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
            "workflow", "parameterBindings", "revision", "version", "contentHash",
        ):
            if skill_context.get(field):
                profile[field] = skill_context[field]
    return profile


def _restrict_profile_to_database(profile: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the selected datasource as an additional server-side catalog constraint."""
    selected = str(context.get("dataSourceId") or "").strip()
    if not selected:
        return profile
    constrained = dict(profile)
    constrained["dataSourceId"] = selected
    return constrained


def _coerce_datetime(value: Any) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        return value
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _resolve_field(rows: list, requested: str) -> Optional[str]:
    if not rows:
        return None
    fields = list(dict.fromkeys(str(key) for row in rows for key in row))
    if requested in fields:
        return requested
    lowered = requested.lower()
    return next((field for field in fields if lowered and lowered in field.lower()), None)


def _resolve_temporal_field(rows: list, requested: str) -> Optional[str]:
    field = _resolve_field(rows, requested)
    if field:
        return field
    fields = list(dict.fromkeys(str(key) for row in rows for key in row))
    priorities = (
        "update_time", "record_time", "detect_time", "warning_time", "start_time",
        "issue_time", "eval_date", "discovered_time", "planned_time", "created_at",
    )
    for candidate in priorities:
        matched = next((item for item in fields if item.lower() == candidate), None)
        if matched:
            return matched
    return next(
        (item for item in fields if any(token in item.lower() for token in ("time", "date", "时间", "日期"))),
        None,
    )


def _time_window_days(value: Any) -> Optional[int]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(1, int(math.ceil(float(value))))
    text = str(value or "").strip().lower()
    matched = re.search(r"(\d+(?:\.\d+)?)", text)
    if not matched:
        return None
    amount = float(matched.group(1))
    if any(token in text for token in ("小时", "hour")):
        amount = amount / 24
    elif any(token in text for token in ("周", "week")):
        amount = amount * 7
    elif any(token in text for token in ("月", "month")):
        amount = amount * 30
    elif any(token in text for token in ("年", "year")):
        amount = amount * 365
    return max(1, int(math.ceil(amount)))


def _apply_execution_plan(bundles: list, profile: dict, context: dict) -> list[dict]:
    """Execute parameter bindings deterministically before any evidence reaches the LLM."""
    parameters = ((context.get("skill") or {}).get("parameters") or {})
    bindings = profile.get("parameterBindings") or {}
    execution = []
    handled_parameters = set()
    no_filter_values = {"全部", "红蓝双方", "所有", "不限"}
    for bundle in bundles:
        rows = _rows_from_payload(bundle.get("payload"))
        schema_rows = list(rows)
        input_count = len(rows)
        applied = []
        for key, value in parameters.items():
            binding = bindings.get(key) or {"operator": "equals", "field": key}
            operator = binding.get("operator")
            requested_field = str(binding.get("field") or key)
            field = (
                _resolve_temporal_field(schema_rows, requested_field)
                if operator == "time-window"
                else _resolve_field(schema_rows, requested_field)
            )
            if str(value).strip() in no_filter_values:
                handled_parameters.add(key)
                applied.append({"parameter": key, "operator": operator, "value": value, "skipped": "all"})
                continue
            if operator == "limit":
                rows = rows[:max(1, min(int(value), config.SITUATION_DATA_ROW_LIMIT))]
                applied.append({"parameter": key, "operator": operator, "value": value})
                handled_parameters.add(key)
            elif operator == "equals" and field:
                wanted = {str(item) for item in value} if isinstance(value, list) else {str(value)}
                rows = [row for row in rows if str(row.get(field)) in wanted]
                applied.append({"parameter": key, "operator": operator, "field": field, "value": value})
                handled_parameters.add(key)
            elif operator == "contains" and field:
                wanted = [str(item).strip() for item in value] if isinstance(value, list) else [str(value).strip()]
                rows = [row for row in rows if any(item in str(row.get(field, "")) for item in wanted)]
                applied.append({"parameter": key, "operator": operator, "field": field, "value": value})
                handled_parameters.add(key)
            elif operator == "numeric-threshold" and field:
                threshold = _as_number(value)
                if threshold is not None:
                    rows = [
                        row for row in rows
                        if (number := _as_number(row.get(field))) is not None and number >= threshold
                    ]
                    applied.append({"parameter": key, "operator": operator, "field": field, "value": threshold})
                    handled_parameters.add(key)
            elif operator == "time-window" and field:
                days = _time_window_days(value)
                if days:
                    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, days))
                    rows = [row for row in rows if (stamp := _coerce_datetime(row.get(field))) and stamp >= cutoff]
                    applied.append({"parameter": key, "operator": operator, "field": field, "days": days})
                    handled_parameters.add(key)
            elif operator == "map-radius":
                radius = _as_number(value)
                if radius is not None:
                    applied.append({"parameter": key, "operator": operator, "radiusKm": radius})
                    handled_parameters.add(key)
            elif operator == "analysis-control":
                applied.append({"parameter": key, "operator": operator, "value": value})
                handled_parameters.add(key)
        payload = dict(bundle.get("payload") or {})
        payload["rows"] = rows
        if not any(key in payload for key in ("results", "indicators", "datasets", "items", "history")):
            payload["rowCount"] = len(rows)
        transformed = {**bundle, "payload": payload, "rows": len(rows)}
        transformed["execution"] = {
            "inputRows": input_count,
            "outputRows": len(rows),
            "operators": applied,
            "steps": profile.get("workflow") or profile.get("executionPlan") or [],
        }
        execution.append(transformed)
    unbound = sorted(set(parameters) - handled_parameters)
    if unbound:
        raise ValueError(f"Skill 参数未绑定到可执行字段或控制器: {', '.join(unbound)}")
    return execution


def _workflow_events(profile: dict, bundles: list) -> list[dict]:
    """Materialize workflow stages with deterministic input/output facts."""
    input_rows = sum(int((bundle.get("execution") or {}).get("inputRows", 0)) for bundle in bundles)
    output_rows = sum(int((bundle.get("execution") or {}).get("outputRows", 0)) for bundle in bundles)
    applied_operators = [
        operator
        for bundle in bundles
        for operator in ((bundle.get("execution") or {}).get("operators") or [])
    ]
    events = []
    for step in profile.get("workflow") or []:
        operator = str(step.get("operator") or "transform")
        stage = {
            "sequence": step.get("sequence"),
            "name": step.get("name"),
            "operator": operator,
            "status": "completed",
            "datasets": [bundle.get("source") for bundle in bundles],
            "inputRows": input_rows,
            "outputRows": output_rows,
        }
        if operator == "collect":
            stage["outputRows"] = input_rows
        elif operator == "filter":
            stage["appliedOperators"] = applied_operators
        elif operator == "visualize":
            stage["plannedCharts"] = len(profile.get("chartTypes") or [])
            stage["plannedMapLayers"] = len(profile.get("mapLayerTypes") or [])
        elif operator == "transform":
            stage["focusMetrics"] = list(profile.get("focusMetrics") or [])
        else:
            raise ValueError(f"Skill workflow operator 不支持: {operator}")
        events.append(stage)
    return events


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
    if any(layer_type in {"areas", "coverage"} for layer_type in layer_types):
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


def _safe_id(value: Any) -> str:
    text = "".join(char if str(char).isalnum() else "_" for char in str(value or ""))
    return text.strip("_")[:40] or "source"


def _datasets_from_response(response: dict) -> list:
    datasets = response.get("datasets", []) if isinstance(response, dict) else []
    if not isinstance(datasets, list):
        data = response.get("data", {}) if isinstance(response, dict) else {}
        datasets = data.get("datasets", []) if isinstance(data, dict) else data
    return datasets if isinstance(datasets, list) else []


def _rows_from_payload(payload: Any) -> list:
    """从不同服务的响应结构中抽取供图表编排使用的记录。"""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "results", "indicators", "datasets", "items", "history"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row if isinstance(row, dict) else {"value": row} for row in value]
    for key in ("data", "session", "snapshot"):
        value = payload.get(key)
        rows = _rows_from_payload(value)
        if rows:
            return rows
        if isinstance(value, dict):
            return [value]
    return [payload] if payload else []


def _source_result(source: str, query: str, context: dict, datasets: list) -> dict:
    actor = context.get("_actor") or {}
    with tools.actor_context(actor):
        return _source_result_as_actor(source, query, context, datasets)


def _source_result_as_actor(source: str, query: str, context: dict, datasets: list) -> dict:
    if source.startswith("dataset:") or source.startswith("ds_") or source.startswith("t_"):
        if source.startswith("dataset:"):
            requested_id = source.split(":", 1)[1]
            matches = [item for item in datasets if str(item.get("id", "")).strip() == requested_id]
        elif source.startswith("ds_"):
            matches = [item for item in datasets if str(item.get("id", "")).strip() == source]
        else:
            # Legacy built-ins use physical names. Refuse ambiguous bindings and always persist
            # the resolved datasetId/schemaVersion in provenance.
            matches = [
                item for item in datasets
                if str(item.get("tableName", "")).strip() == source
            ]
        if len(matches) != 1:
            message = "未找到已授权数据集" if not matches else "数据源绑定不唯一，请改用 dataset:<id>"
            return {"success": False, "message": message}
        matched = matches[0]
        # 远端特性：schema 含字段元数据时优先 LLM 生成精确 SQL 取数，失败回退预定义查询/整表
        if matched.get("fields"):
            try:
                sql_result = _query_dataset_with_sql(
                    str(matched.get("id") or ""), query, matched, "",
                    config.SITUATION_DATA_ROW_LIMIT,
                )
                if isinstance(sql_result, dict) and sql_result.get("success") is not False:
                    sql_result["dataset"] = matched
                    return sql_result
                logger.warning("SQL 取数未成功，回退数据集预定义查询: dataset=%s", matched.get("id"))
            except Exception as exc:
                logger.warning("SQL 取数异常，回退数据集预定义查询: dataset=%s err=%s", matched.get("id"), exc)
        return tools.query_admin_dataset(matched, config.SITUATION_DATA_ROW_LIMIT)
    if source == "knowledge":
        return tools.query_knowledge(query, top_k=8)
    if source == "indicator":
        return tools.get_indicators(context.get("indicatorIds") or [])
    if source == "evaluation":
        evaluation_id = context.get("evaluationId") or context.get("sessionId")
        if not evaluation_id:
            return {"success": False, "message": "当前上下文未提供评估会话 ID"}
        return tools.get_evaluation(str(evaluation_id))
    if source == "admin":
        combined_rows = []
        sampled = []
        for dataset in datasets[:config.SITUATION_AUTO_DATASET_LIMIT]:
            result = tools.query_admin_dataset(dataset, config.SITUATION_DATA_ROW_LIMIT)
            if result.get("success") is not True:
                continue
            table_name = str(dataset.get("tableName") or dataset.get("name") or "dataset")
            sampled.append(table_name)
            for row in result.get("rows", []):
                if isinstance(row, dict):
                    combined_rows.append({"_dataset": table_name, **row})
        if not combined_rows:
            return {"success": False, "message": "已注册数据集未返回可用记录"}
        return {
            "success": True,
            "rows": combined_rows,
            "rowCount": len(combined_rows),
            "sampledDatasets": sampled,
        }
    return {"success": False, "message": "尚未配置该数据源的只读适配器"}


def _result_ok(source: str, result: dict) -> bool:
    if not isinstance(result, dict) or result.get("success") is False:
        return False
    if source == "indicator":
        return isinstance(result.get("indicators"), list) and bool(result["indicators"])
    if source == "knowledge":
        return isinstance(result.get("results"), list) and bool(result["results"])
    return bool(_rows_from_payload(result))


async def _collect_real_data(query: str, profile: dict, context: dict) -> tuple[list, list]:
    sources = list(dict.fromkeys(str(item).strip() for item in profile["dataSources"] if str(item).strip()))
    needs_catalog = any(
        source.startswith(("t_", "ds_", "dataset:")) or source == "admin"
        for source in sources
    )
    actor = context.get("_actor") or {}
    if needs_catalog:
        with tools.actor_context(actor):
            catalog_response = await asyncio.to_thread(tools.list_admin_datasets)
    else:
        catalog_response = {}
    datasets = _datasets_from_response(catalog_response)
    selected_database = str(context.get("dataSourceId") or profile.get("dataSourceId") or "").strip()
    if selected_database:
        datasets = [
            item for item in datasets
            if str(item.get("databaseId") or item.get("dataSourceId") or "").strip() == selected_database
        ]
    tasks = [
        asyncio.to_thread(_source_result, source, query, context, datasets)
        for source in sources
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    bundles, failures = [], []
    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            failures.append({"source": source, "message": str(result)[:200]})
            continue
        if not _result_ok(source, result):
            message = result.get("message") if isinstance(result, dict) else "数据响应格式无效"
            failures.append({"source": source, "message": str(message or "未返回可用记录")[:200]})
            continue
        rows = _rows_from_payload(result)
        row_count = int(result.get("rowCount", len(rows))) if isinstance(result, dict) else len(rows)
        if source.startswith(("t_", "ds_", "dataset:")):
            dataset_meta = result.get("dataset", {})
            label = dataset_meta.get("name") or source
        else:
            label = source
        bundles.append({
            "source": source,
            "summary": f"真实数据源「{label}」返回 {row_count} 条可用记录",
            "rows": row_count,
            "payload": result,
            "physicalDatasetId": str((result.get("dataset") or {}).get("id") or ""),
            "schemaVersion": int((result.get("dataset") or {}).get("schemaVersion") or 1),
            "truncated": bool(result.get("truncated")),
        })
    return bundles, failures


def _sensitive_column(name: Any, bundle: dict) -> bool:
    normalized = str(name or "").strip().lower().replace("-", "_")
    configured = set(config.SITUATION_SENSITIVE_COLUMNS)
    dataset_sensitive = {
        str(item).strip().lower()
        for item in ((bundle.get("payload") or {}).get("dataset") or {}).get("sensitiveColumns", [])
    }
    return normalized in dataset_sensitive or any(token in normalized for token in configured)


def _evidence_digest(rows: list) -> str:
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_scalar(value: Any, limit: int = 80) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:limit]


def _grouped_aggregates(rows: list, categorical_cols: list, numeric_cols: list, top_n: int = 10) -> list:
    """按分类列分组、对数值列做 sum/avg/count 聚合（每组 top-N 组），供 LLM 证据与验证器共用。"""
    grouped = []
    for cat_col in categorical_cols:
        for num_col in numeric_cols:
            groups: Dict[str, list] = {}
            for row in rows:
                raw_group = row.get(cat_col)
                if raw_group in (None, ""):
                    continue
                value = _as_number(row.get(num_col))
                if value is None:
                    continue
                group = str(raw_group)[:60]
                groups.setdefault(group, []).append(value)
            if not groups:
                continue
            top = sorted(groups.items(), key=lambda item: -len(item[1]))[:top_n]
            grouped.append({
                "groupBy": cat_col,
                "metric": num_col,
                "groups": [
                    {"group": group, "count": len(values), "sum": round(sum(values), 6),
                     "avg": round(sum(values) / len(values), 6)}
                    for group, values in top
                ],
            })
    return grouped


def _aggregate_evidence(bundle: dict) -> dict:
    rows = _rows_from_payload(bundle["payload"])
    columns = list(dict.fromkeys(str(key) for row in rows for key in row))[:50]
    safe_columns = [column for column in columns if not _sensitive_column(column, bundle)]
    numeric_stats, category_counts = {}, {}
    for column in safe_columns:
        values = [_as_number(row.get(column)) for row in rows]
        numbers = [value for value in values if value is not None]
        if numbers:
            numeric_stats[column] = {
                "count": len(numbers), "min": min(numbers), "max": max(numbers),
                "sum": round(sum(numbers), 6), "avg": round(sum(numbers) / len(numbers), 6),
            }
            continue
        counts: Dict[str, int] = {}
        for row in rows:
            value = row.get(column)
            if value not in (None, ""):
                label = str(value)[:60]
                counts[label] = counts.get(label, 0) + 1
        if counts and len(counts) <= 100:
            category_counts[column] = dict(
                sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            )
    grouped_stats = _grouped_aggregates(
        rows,
        categorical_cols=list(category_counts.keys()),
        numeric_cols=list(numeric_stats.keys()),
    )
    samples = []
    if config.SITUATION_LLM_EVIDENCE_ROWS:
        for row in rows[:config.SITUATION_LLM_EVIDENCE_ROWS]:
            samples.append({
                column: _safe_scalar(row.get(column))
                for column in safe_columns
                if column in row
            })
    return {
        "datasetId": bundle["datasetId"],
        "source": bundle["source"],
        "summary": bundle["summary"],
        "rowCount": len(rows),
        "columns": safe_columns,
        "numericStats": numeric_stats,
        "categoryCounts": category_counts,
        "groupedStats": grouped_stats,
        "samples": samples,
        "evidenceHash": _evidence_digest(rows),
    }


def _prompt_payload(bundles: list) -> list:
    return [_aggregate_evidence(bundle) for bundle in bundles]


def _run_llm_orchestration(query: str, profile: dict, context: dict, bundles: list) -> dict:
    """保留五阶段 LLM 协议，但所有模型阶段只接收聚合脱敏证据。"""
    aggregated = _prompt_payload(bundles)
    allowed_ids = {item["datasetId"] for item in aggregated}
    meta = {"success": True, "data": {"schemas": [{
        "datasetId": item["datasetId"], "datasetName": item["source"],
        "description": item["summary"],
        "fields": [{"column": column, "type": "aggregated", "businessMeaning": "聚合可验证字段"}
                   for column in item["columns"]],
    } for item in aggregated], "indicators": []}}

    parameters = ((context.get("skill") or {}).get("parameters") or {})
    effective_query = query
    if parameters:
        controls = "，".join(f"{key}={value}" for key, value in parameters.items())
        effective_query = f"{query}\n必须遵循的 Skill 执行参数：{controls}"

    plan = call_llm_json(
        prompts.build_plan_messages(effective_query, meta), temperature=0.2,
        max_tokens=min(config.LLM_MAX_TOKENS, 6000),
    )
    if not isinstance(plan, dict):
        plan = {}
    datasets_plan = [
        item for item in plan.get("datasets", [])[:len(allowed_ids)]
        if isinstance(item, dict) and str(item.get("datasetId")) in allowed_ids
    ] if isinstance(plan.get("datasets"), list) else []
    if not datasets_plan:
        datasets_plan = [{"datasetId": item["datasetId"], "intent": item["summary"]} for item in aggregated]
    allowed_chart_types = set(profile.get("chartTypes") or _CHART_TYPES)
    charts_plan = [
        item for item in plan.get("chartsPlan", [])[:5]
        if isinstance(item, dict) and str(item.get("type") or "bar").lower() in allowed_chart_types
    ] if isinstance(plan.get("chartsPlan"), list) else []
    if not charts_plan:
        charts_plan = [
            {"type": chart_type, "title": metric, "intent": profile.get("analysisGoal", "")}
            for chart_type, metric in zip(profile["chartTypes"][:3], profile["focusMetrics"][:3])
        ]
    safe_plan = {
        "datasets": datasets_plan, "chartsPlan": charts_plan,
        "mapPlan": plan.get("mapPlan", [])[:3] if isinstance(plan.get("mapPlan"), list) else [],
        "needKnowledge": False, "knowledgeQuery": "",
    }

    # 用单行“聚合数据集”适配原有阶段提示词；这里不包含业务原始行。
    data_context = {}
    for item in aggregated:
        aggregate_row = {
            "rowCount": item["rowCount"], "numericStats": item["numericStats"],
            "categoryCounts": item["categoryCounts"], "groupedStats": item["groupedStats"],
            "evidenceHash": item["evidenceHash"],
            **({"samples": item["samples"]} if item["samples"] else {}),
        }
        data_context[item["datasetId"]] = {
            "success": True, "columns": list(aggregate_row), "rows": [aggregate_row], "total": 1,
        }

    # 图表与地图互不依赖，并行生成以省掉一次 LLM 往返延迟。
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        charts_future = pool.submit(
            call_llm_json,
            prompts.build_chart_messages(effective_query, data_context, safe_plan),
            temperature=0.2,
            max_tokens=config.LLM_MAX_TOKENS,
        )
        map_future = pool.submit(
            call_llm_json,
            prompts.build_map_messages(effective_query, data_context),
            temperature=0.2,
            max_tokens=min(config.LLM_MAX_TOKENS, 8000),
        )
        charts = charts_future.result()
        map_layer = map_future.result()
    if isinstance(charts, dict):
        charts = charts.get("charts") or [charts]
    if not isinstance(charts, list):
        raise ValueError("LLM 产图阶段未返回数组")
    if not isinstance(map_layer, dict):
        map_layer = {}
    # 数值预校验 + 纠错重试：LLM 常估算数值而非复制证据，把拒因喂回去定向重写。
    for attempt in range(2):
        chart_failures = _chart_value_failures(charts, profile, bundles)
        if not chart_failures:
            break
        logger.warning("图表数值校验未通过，进行第 %d 次纠错重试: %s", attempt + 1, chart_failures[:1])
        charts = call_llm_json(
            prompts.build_chart_correction_messages(effective_query, data_context, safe_plan, chart_failures),
            temperature=0.2,
            max_tokens=config.LLM_MAX_TOKENS,
        )
        if isinstance(charts, dict):
            charts = charts.get("charts") or [charts]
        if not isinstance(charts, list):
            break
    narrative = call_llm_json(
        prompts.build_narrative_messages(effective_query, charts, map_layer), temperature=0.3,
        max_tokens=min(config.LLM_MAX_TOKENS, 6000),
    )
    if not isinstance(narrative, dict):
        narrative = {}
    return {"plan": safe_plan, "charts": charts, "mapLayer": map_layer, "narrative": narrative}


_CHART_TYPES = {"bar", "line", "pie", "radar", "gauge", "scatter", "heatmap", "relation", "sankey", "map"}


def _valid_coord(value: Any, minimum: float, maximum: float) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and minimum <= number <= maximum
    except (TypeError, ValueError):
        return False


def _safe_text(value: Any, limit: int = 160) -> str:
    return re.sub(r"[<>\x00-\x1f]", "", str(value or ""))[:limit]


def _safe_point(value: Any) -> Optional[dict]:
    if not isinstance(value, dict) or not (
        _valid_coord(value.get("lng"), -180, 180)
        and _valid_coord(value.get("lat"), -90, 90)
    ):
        return None
    return {
        "name": _safe_text(value.get("name") or "点位"),
        "lng": float(value["lng"]),
        "lat": float(value["lat"]),
        "raw": _safe_text(value.get("raw")),
        **({"featureId": _safe_id(value.get("featureId"))} if value.get("featureId") else {}),
        **({"datasetRef": _safe_text(value.get("datasetRef"), 80)} if value.get("datasetRef") else {}),
    }


def _coordinate_evidence(bundles: list) -> set[tuple[float, float]]:
    evidence: set[tuple[float, float]] = set()
    lng_names = {"lng", "lon", "longitude", "经度"}
    lat_names = {"lat", "latitude", "纬度"}
    for bundle in bundles:
        for row in _rows_from_payload(bundle.get("payload")):
            lowered = {str(key).strip().lower(): value for key, value in row.items()}
            lng = next((lowered[name] for name in lng_names if name in lowered), None)
            lat = next((lowered[name] for name in lat_names if name in lowered), None)
            if _valid_coord(lng, -180, 180) and _valid_coord(lat, -90, 90):
                evidence.add((round(float(lng), 6), round(float(lat), 6)))
    return evidence


def _point_is_evidenced(point: dict, evidence: set[tuple[float, float]]) -> bool:
    return (round(float(point["lng"]), 6), round(float(point["lat"]), 6)) in evidence


def _verify_map_coordinates(layer: dict, bundles: list) -> dict:
    evidence = _coordinate_evidence(bundles)
    if not evidence:
        layer.update({"points": [], "routes": [], "areas": [], "circles": []})
        layer["verification"] = {"verified": True, "method": "empty-without-coordinate-evidence", "checkedCoordinates": 0}
        return layer
    points = [point for point in layer.get("points", []) if _point_is_evidenced(point, evidence)]
    routes = [route for route in layer.get("routes", []) if all(_point_is_evidenced(point, evidence) for point in route["points"])]
    areas = [area for area in layer.get("areas", []) if all(_point_is_evidenced(point, evidence) for point in area["points"])]
    circles = [circle for circle in layer.get("circles", []) if _point_is_evidenced(circle["center"], evidence)]
    checked = len(points) + sum(len(item["points"]) for item in routes + areas) + len(circles)
    layer.update({"points": points, "routes": routes, "areas": areas, "circles": circles})
    layer["verification"] = {"verified": True, "method": "coordinate-membership", "checkedCoordinates": checked}
    return layer


def _safe_path(value: Any, minimum_points: int) -> Optional[dict]:
    if not isinstance(value, dict) or not isinstance(value.get("points"), list):
        return None
    points = [point for item in value["points"][:500] if (point := _safe_point(item))]
    if len(points) < minimum_points:
        return None
    return {
        "name": _safe_text(value.get("name") or "图形"),
        "points": points,
        **({"featureId": _safe_id(value.get("featureId"))} if value.get("featureId") else {}),
        **({"datasetRef": _safe_text(value.get("datasetRef"), 80)} if value.get("datasetRef") else {}),
    }


def _sanitize_map_layer(value: Any, profile: dict, context: Optional[dict] = None) -> dict:
    if not isinstance(value, dict):
        value = {}
    points = [
        point for item in value.get("points", [])[:300]
        if (point := _safe_point(item))
    ] if isinstance(value.get("points"), list) else []
    routes = [
        route for item in value.get("routes", [])[:100]
        if (route := _safe_path(item, 2))
    ] if isinstance(value.get("routes"), list) else []
    areas = [
        area for item in value.get("areas", [])[:100]
        if (area := _safe_path(item, 3))
    ] if isinstance(value.get("areas"), list) else []
    circles = []
    for item in value.get("circles", [])[:100] if isinstance(value.get("circles"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("center"), dict):
            continue
        center = _safe_point(item["center"])
        radius = _as_number(item.get("radiusKm"))
        if center and radius is not None and 0 < radius <= 5000:
            circles.append({
                "name": _safe_text(item.get("name") or "圆形区域"),
                "center": {"lng": center["lng"], "lat": center["lat"]},
                "radiusKm": radius,
                **({"featureId": _safe_id(item.get("featureId"))} if item.get("featureId") else {}),
                **({"datasetRef": _safe_text(item.get("datasetRef"), 80)} if item.get("datasetRef") else {}),
            })
    layer_config = value.get("layerConfig", {}) if isinstance(value.get("layerConfig"), dict) else {}
    color = str(layer_config.get("color") or "#e74c3c")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#e74c3c"
    opacity = _as_number(layer_config.get("opacity"))
    weight = _as_number(layer_config.get("weight"))
    fill_opacity = _as_number(layer_config.get("fillOpacity"))
    layer_config = {
        "name": _safe_text(layer_config.get("name") or profile["skillName"]),
        "color": color,
        "opacity": min(max(opacity if opacity is not None else 0.85, 0), 1),
        "weight": min(max(weight if weight is not None else 3, 1), 12),
        "fillOpacity": min(max(fill_opacity if fill_opacity is not None else 0.15, 0), 1),
        "visible": bool(layer_config.get("visible", True)),
    }
    layer = {
        "layerId": str(value.get("layerId") or f"skill_{profile['skillId'] or 'general'}"),
        "points": points, "routes": routes, "areas": areas, "circles": circles,
        "layerConfig": layer_config,
    }
    # 远端特性：保留 datasetRef/fieldMapping（前端据此用全量数据渲染轨迹/标点）
    if isinstance(value.get("datasetRef"), str) and value["datasetRef"]:
        layer["datasetRef"] = _safe_text(value["datasetRef"], 80)
    if isinstance(value.get("fieldMapping"), dict):
        layer["fieldMapping"] = {
            str(key)[:60]: str(item)[:60]
            for key, item in value["fieldMapping"].items()
            if isinstance(item, str)
        }
    map_radius = next((
        _as_number(value)
        for key, value in (((context or {}).get("skill") or {}).get("parameters") or {}).items()
        if "半径" in str(key)
    ), None)
    if map_radius is not None:
        layer["layerConfig"]["radiusKm"] = min(max(map_radius, 0.1), 5000)
    return layer


_FORBIDDEN_OPTION_KEYS = {"formatter", "renderItem", "graphic", "backgroundColor"}


def _safe_echarts(value: Any, depth: int = 0, budget: list = None) -> Any:
    """Limit ECharts JSON to inert data/configuration (no HTML, callbacks or external URLs)."""
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 12 or budget[0] > 5000:
        raise ValueError("图表 option 结构过大")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value[:500]
        if re.search(r"(?:https?:|data:|image:|javascript:|<[^>]+>)", text, re.I):
            raise ValueError("图表 option 包含外部资源或 HTML")
        return text
    if isinstance(value, list):
        return [_safe_echarts(item, depth + 1, budget) for item in value[:1000]]
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:200]:
            safe_key = str(key)[:80]
            if safe_key in _FORBIDDEN_OPTION_KEYS:
                continue
            result[safe_key] = _safe_echarts(item, depth + 1, budget)
        return result
    raise ValueError("图表 option 包含不可序列化值")


def _numeric_values(option: dict) -> list[float]:
    values: list[float] = []
    for series in option.get("series", []) if isinstance(option.get("series"), list) else []:
        if not isinstance(series, dict):
            continue
        data = series.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            raw = item.get("value") if isinstance(item, dict) else item
            if isinstance(raw, list):
                for value in raw:
                    number = _as_number(value)
                    if number is not None:
                        values.append(round(number, 6))
            else:
                number = _as_number(raw)
                if number is not None:
                    values.append(round(number, 6))
    return values


def _bundle_numbers(bundle: dict) -> list[float]:
    values = []
    rows = _rows_from_payload(bundle.get("payload"))
    for row in rows:
        for value in row.values():
            number = _as_number(value)
            if number is not None:
                values.append(round(number, 6))
    # LLM 收到的是这些确定性统计值，也允许它们被验证器精确匹配。
    columns = list(dict.fromkeys(str(key) for row in rows for key in row))[:50]
    numeric_cols: list = []
    categorical_cols: list = []
    for column in columns:
        numbers = [number for row in rows if (number := _as_number(row.get(column))) is not None]
        if numbers:
            numeric_cols.append(column)
            values.extend(round(number, 6) for number in (
                min(numbers), max(numbers), sum(numbers), sum(numbers) / len(numbers), len(numbers),
            ))
        else:
            counts: Dict[str, int] = {}
            for row in rows:
                raw = row.get(column)
                if raw not in (None, ""):
                    label = str(raw)[:60]
                    counts[label] = counts.get(label, 0) + 1
            values.extend(float(count) for count in counts.values())
            if len(counts) <= 100:
                categorical_cols.append(column)
    # 分组聚合值（与 _aggregate_evidence.groupedStats 同源），让验证器能精确复算分组图表。
    for gs in _grouped_aggregates(rows, categorical_cols, numeric_cols):
        for group in gs["groups"]:
            values.extend([float(group["count"]), group["sum"], group["avg"]])
    return values


def _verification(chart: dict, bundle: dict, transform: dict) -> dict:
    output_values = _numeric_values(chart["option"])
    evidence_values = _bundle_numbers(bundle)
    operation = transform.get("operation", "evidence-membership")
    # 容差放宽到 1%（相对）或 0.5（绝对）：LLM 常把统计值四舍五入到整数/整千，
    # 逐位精确比对（1e-6）会把合理舍入误判为伪造；1% 仍足以拦截编造的大数。
    mismatches = []
    for value in output_values:
        if not any(math.isclose(value, candidate, rel_tol=0.01, abs_tol=0.5) for candidate in evidence_values):
            closest = min(evidence_values, key=lambda item: abs(item - value), default=None)
            mismatches.append(f"{value}→最近证据{closest}")
    return {
        "verified": bool(output_values) and not mismatches,
        "method": operation,
        "checkedValues": len(output_values),
        "mismatches": mismatches,
        "evidenceHash": _evidence_digest(_rows_from_payload(bundle.get("payload"))),
        "verifiedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def _chart_value_failures(raw_charts: list, profile: dict, bundles: list) -> list:
    """轻量预校验：按与 _validate_llm_result 相同的口径找出无法由证据复算的图表。"""
    if not isinstance(raw_charts, list):
        return []
    dataset_ids = {bundle["datasetId"] for bundle in bundles}
    bundle_by_id = {bundle["datasetId"]: bundle for bundle in bundles}
    if not bundle_by_id:
        return []
    fallback_dataset = bundles[0]["datasetId"]
    failures = []
    for index, value in enumerate(raw_charts[:5], start=1):
        if not isinstance(value, dict) or not isinstance(value.get("option"), dict):
            continue
        chart_id = _safe_id(value.get("chartId") or f"c_{index}")
        dataset_ref = str(value.get("datasetRef") or fallback_dataset)
        if dataset_ref not in dataset_ids:
            dataset_ref = fallback_dataset
        transform = value.get("transform") if isinstance(value.get("transform"), dict) else {}
        transform = {
            "operation": str(transform.get("operation") or "evidence-membership")[:80],
            "groupBy": str(transform.get("groupBy") or "")[:80],
            "metric": str(transform.get("metric") or "")[:80],
        }
        chart = {
            "chartId": chart_id,
            "type": "bar",
            "title": "",
            "option": _safe_echarts(value["option"]),
            "datasetRef": dataset_ref,
        }
        verification = _verification(chart, bundle_by_id[dataset_ref], transform)
        if not verification["verified"]:
            failures.append({
                "chartId": chart_id,
                "datasetRef": dataset_ref,
                "mismatches": verification.get("mismatches", []),
            })
    return failures


def _validate_llm_result(result: dict, profile: dict, bundles: list) -> tuple[list, dict, dict]:
    raw_charts = result.get("charts")
    if not isinstance(raw_charts, list) or not raw_charts:
        raise ValueError("LLM 结果缺少 charts")
    dataset_ids = {bundle["datasetId"] for bundle in bundles}
    bundle_by_id = {bundle["datasetId"]: bundle for bundle in bundles}
    fallback_dataset = bundles[0]["datasetId"]
    charts, seen = [], set()
    for index, value in enumerate(raw_charts[:5], start=1):
        if not isinstance(value, dict) or not isinstance(value.get("option"), dict):
            continue
        chart_id = _safe_id(value.get("chartId") or f"c_{index}")
        if chart_id in seen:
            chart_id = f"{chart_id}_{index}"
        seen.add(chart_id)
        chart_type = str(value.get("type") or "bar").lower()
        allowed_chart_types = set(profile.get("chartTypes") or _CHART_TYPES).intersection(_CHART_TYPES)
        if chart_type not in allowed_chart_types:
            chart_type = next(
                (item for item in profile.get("chartTypes", []) if item in allowed_chart_types),
                "bar",
            )
        dataset_ref = str(value.get("datasetRef") or fallback_dataset)
        if dataset_ref not in dataset_ids:
            dataset_ref = fallback_dataset
        option = _safe_echarts(value["option"])
        transform = value.get("transform") if isinstance(value.get("transform"), dict) else {}
        transform = {
            "operation": str(transform.get("operation") or "evidence-membership")[:80],
            "groupBy": str(transform.get("groupBy") or "")[:80],
            "metric": str(transform.get("metric") or "")[:80],
        }
        chart = {
            "chartId": chart_id,
            "type": chart_type,
            "title": str(value.get("title") or profile["focusMetrics"][(index - 1) % len(profile["focusMetrics"])]),
            "option": option,
            "datasetRef": dataset_ref,
            "fieldMapping": value.get("fieldMapping") or {},
            "provenance": {
                "datasetId": dataset_ref,
                "physicalDatasetId": bundle_by_id[dataset_ref].get("physicalDatasetId", ""),
                "schemaVersion": bundle_by_id[dataset_ref].get("schemaVersion", 1),
                "transform": transform,
                "truncated": bundle_by_id[dataset_ref].get("truncated", False),
            },
        }
        chart["verification"] = _verification(chart, bundle_by_id[dataset_ref], transform)
        if not chart["verification"]["verified"]:
            details = "；".join(chart["verification"].get("mismatches", [])[:3])
            raise ValueError(f"图表 {chart_id} 的数值无法由证据重算验证" + (f"（{details}）" if details else ""))
        charts.append(chart)
    if not charts:
        raise ValueError("LLM 未生成可用图表")
    raw_map = result.get("mapLayer")
    if not raw_map and isinstance(result.get("mapLayers"), list) and result["mapLayers"]:
        raw_map = result["mapLayers"][0]
    map_layer = _verify_map_coordinates(_sanitize_map_layer(raw_map, profile, result.get("context")), bundles)
    raw_narrative = result.get("narrative") if isinstance(result.get("narrative"), dict) else {}
    chart_ids = {chart["chartId"] for chart in charts}
    explanations = []
    for item in raw_narrative.get("explanations", []) if isinstance(raw_narrative.get("explanations"), list) else []:
        if isinstance(item, dict) and str(item.get("chartId")) in chart_ids:
            explanations.append({"chartId": str(item["chartId"]), "text": str(item.get("text") or "")})
    exp_ids = {item["chartId"] for item in explanations}
    for chart in charts:
        if chart["chartId"] not in exp_ids:
            explanations.append({"chartId": chart["chartId"], "text": f"该图使用 {chart['datasetRef']} 的真实数据生成。"})
    narrative = {
        "intro": str(raw_narrative.get("intro") or f"已围绕“{profile['skillName']}”汇聚真实数据并生成当前态势。"),
        "explanations": explanations,
        "mapExplanation": str(raw_narrative.get("mapExplanation") or ""),
    }
    return charts, map_layer, narrative


def _as_number(value: Any) -> Optional[float]:
    try:
        text = str(value).strip().replace(",", "").rstrip("%")
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _fallback_option(chart_type: str, rows: list, metric: str) -> tuple[str, dict, str]:
    rows = rows[:20] or [{"数据": 0}]
    keys = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else ["数据"]
    metric_field = _resolve_field(rows, metric)
    numeric_key = (
        metric_field
        if metric_field and any(_as_number(row.get(metric_field)) is not None for row in rows)
        else next((key for key in keys if any(_as_number(row.get(key)) is not None for row in rows)), None)
    )
    label_key = next((key for key in keys if key != numeric_key), keys[0])
    labels = [str(row.get(label_key, index + 1))[:30] for index, row in enumerate(rows)]
    if numeric_key:
        values = [_as_number(row.get(numeric_key)) or 0 for row in rows]
    else:
        counts: Dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        labels, values = list(counts.keys()), list(counts.values())
    actual_metric = str(numeric_key or f"{label_key}记录数")
    if chart_type == "pie":
        return "pie", {"tooltip": {"trigger": "item"}, "legend": {"bottom": 0}, "series": [{
            "name": actual_metric, "type": "pie", "radius": ["35%", "68%"],
            "data": [{"name": label, "value": value} for label, value in zip(labels, values)],
        }]}, actual_metric
    if chart_type == "radar":
        max_value = max([float(value) for value in values] + [1.0])
        return "radar", {"tooltip": {}, "radar": {"indicator": [
            {"name": label, "max": max_value * 1.2} for label in labels[:8]
        ]}, "series": [{"name": actual_metric, "type": "radar", "data": [{"name": actual_metric, "value": values[:8]}]}]}, actual_metric
    if chart_type == "gauge":
        return "gauge", {"series": [{"name": actual_metric, "type": "gauge", "progress": {"show": True},
                                       "data": [{"name": labels[0], "value": values[0]}]}]}, actual_metric
    effective = "line" if chart_type == "line" else "bar"
    return effective, {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": actual_metric},
        "series": [{"name": actual_metric, "type": effective, "smooth": effective == "line", "data": values}],
    }, actual_metric


def _fallback_map(profile: dict, bundles: list, context: Optional[dict] = None) -> dict:
    lng_keys = {"lng", "lon", "longitude", "经度"}
    lat_keys = {"lat", "latitude", "纬度"}
    name_keys = {"name", "title", "region", "location", "名称", "区域", "地点"}
    points = []
    for bundle in bundles:
        for row in _rows_from_payload(bundle["payload"]):
            lowered = {str(key).strip().lower(): value for key, value in row.items()}
            lng = next((lowered[key] for key in lng_keys if key in lowered), None)
            lat = next((lowered[key] for key in lat_keys if key in lowered), None)
            if not (_valid_coord(lng, -180, 180) and _valid_coord(lat, -90, 90)):
                continue
            name = next((lowered[key] for key in name_keys if key in lowered), bundle["source"])
            points.append({"name": str(name), "lng": float(lng), "lat": float(lat), "raw": bundle["source"]})
    return _sanitize_map_layer({
        "layerId": f"skill_{profile['skillId'] or 'general'}",
        "points": points,
        "layerConfig": {"name": profile["skillName"], "visible": True},
    }, profile, context)


def _data_fallback(query: str, profile: dict, bundles: list, context: Optional[dict] = None) -> tuple[list, dict, dict]:
    charts = []
    metrics = profile["focusMetrics"][:3]
    requested_types = profile["chartTypes"][:3]
    for index, metric in enumerate(metrics, start=1):
        bundle = bundles[(index - 1) % len(bundles)]
        chart_type, option, effective_metric = _fallback_option(
            requested_types[(index - 1) % len(requested_types)],
            _rows_from_payload(bundle["payload"]),
            metric,
        )
        chart = {
            "chartId": f"c_{index}", "type": chart_type, "title": effective_metric,
            "option": option, "datasetRef": bundle["datasetId"],
            "provenance": {
                "datasetId": bundle["datasetId"],
                "physicalDatasetId": bundle.get("physicalDatasetId", ""),
                "schemaVersion": bundle.get("schemaVersion", 1),
                "transform": {"operation": "deterministic-first-numeric-or-count"},
                "truncated": bundle.get("truncated", False),
            },
        }
        chart["verification"] = _verification(
            chart, bundle, {"operation": "deterministic-first-numeric-or-count"},
        )
        charts.append(chart)
    narrative = {
        "intro": f"已围绕“{query}”读取 {len(bundles)} 个真实数据源。当前结果由数据降级编排生成，建议在 LLM 配置恢复后重新生成以获得更完整说明。",
        "explanations": [
            {"chartId": chart["chartId"], "text": f"该图直接使用 {chart['datasetRef']} 的真实记录生成。"}
            for chart in charts
        ],
        "mapExplanation": "",
    }
    return charts, _fallback_map(profile, bundles, context), narrative


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
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """基于注册数据源和当前 LLM 配置生成态势产物。

    数据访问由受控工具完成，LLM 只负责规划可视化和说明，不能生成 SQL 或直接
    访问数据源。这样既能使用真实记录，也保留服务端的只读查询边界。
    """
    profile = _skill_profile(skill_context)
    runtime_context = dict(context or {})
    profile = _restrict_profile_to_database(profile, runtime_context)
    yield "plan", {
        "skill": {
            "id": profile["skillId"],
            "name": profile["skillName"],
            "category": profile["category"],
        },
        "steps": profile["executionPlan"],
        "datasets": profile["dataSources"],
        "chartsPlan": [
            {"type": chart_type, "title": metric}
            for chart_type, metric in zip(profile["chartTypes"][:3], profile["focusMetrics"][:3])
        ],
        "mapPlan": [{
            "layerId": f"skill_{profile['skillId'] or 'general'}",
            "types": profile["mapLayerTypes"],
        }],
        "mode": "real",
    }

    bundles, failures = await _collect_real_data(query, profile, runtime_context)
    for failure in failures:
        yield "error", {
            "stage": "data",
            "source": failure["source"],
            "message": failure["message"],
            "fatal": False,
        }
    if not bundles:
        raise RuntimeError("没有取得可用于态势分析的真实数据，请检查 Skill 数据源和相关服务")

    bundles = _apply_execution_plan(bundles, profile, runtime_context)
    if not any(_rows_from_payload(bundle.get("payload")) for bundle in bundles):
        raise RuntimeError("Skill 参数执行后没有匹配数据，请调整过滤条件")

    for step_event in _workflow_events(profile, bundles):
        yield "step", step_event

    for index, bundle in enumerate(bundles, start=1):
        bundle["datasetId"] = f"real_{index}_{_safe_id(bundle['source'])}"
        payload = bundle.get("payload")
        rows = _rows_from_payload(payload)
        columns = payload.get("columns") if isinstance(payload, dict) else []
        if not columns and rows and isinstance(rows[0], dict):
            columns = list(rows[0].keys())
        yield "dataset", {
            "datasetId": bundle["datasetId"],
            "source": bundle["source"],
            "summary": bundle["summary"],
            "rows": bundle["rows"],
            "realData": True,
            "physicalDatasetId": bundle.get("physicalDatasetId", ""),
            "schemaVersion": bundle.get("schemaVersion", 1),
            "truncated": bundle.get("truncated", False),
            "execution": bundle.get("execution", {}),
            "evidenceHash": _evidence_digest(rows),
            # 远端特性：全量数据下发，前端用 fieldMapping 全量渲染（替代 LLM 内联样本）
            "columns": columns,
            "data": rows,
        }

    partial = False
    try:
        result = await asyncio.to_thread(_run_llm_orchestration, query, profile, runtime_context, bundles)
        result["context"] = runtime_context
        charts, map_layer, narrative = _validate_llm_result(result, profile, bundles)
    except Exception as exc:
        if not config.SITUATION_ALLOW_DATA_FALLBACK:
            raise
        partial = True
        logger.warning("LLM 编排失败，使用真实数据降级渲染: reportId=%s error=%s", report_id, exc)
        yield "error", {
            "stage": "llm",
            "message": f"LLM 编排暂不可用，已基于真实数据降级生成：{str(exc)[:160]}",
            "fatal": False,
        }
        charts, map_layer, narrative = _data_fallback(query, profile, bundles, runtime_context)

    # 远端特性：优先用 map_builder 从全量真实数据自动标注（确定性、无需 LLM 产图）；
    # 无地理列或坐标未通过证据校验时保留 LLM 地图（其坐标已通过同一证据校验）。
    builder_layer = None
    try:
        from agent import map_builder
        for bundle in bundles:
            ann = map_builder.build_map_annotations(_rows_from_payload(bundle.get("payload")))
            if ann and (ann.get("points") or ann.get("routes") or ann.get("areas") or ann.get("circles")):
                candidate = _verify_map_coordinates(_sanitize_map_layer({
                    "layerId": f"ds_{bundle.get('datasetId', '')}",
                    "datasetRef": bundle.get("datasetId", ""),
                    "points": ann.get("points", []),
                    "routes": ann.get("routes", []),
                    "areas": ann.get("areas", []),
                    "circles": ann.get("circles", []),
                    "layerConfig": {
                        "name": f"数据集 {bundle.get('source', '')}",
                        "type": "points",
                        "supportedTypes": ["points", "routes", "areas", "circles"],
                        "color": "#8b5cf6",
                        "opacity": 0.85,
                        "visible": True,
                    },
                }, profile, runtime_context), bundles)
                if candidate.get("points") or candidate.get("routes") or candidate.get("areas") or candidate.get("circles"):
                    builder_layer = candidate
                    break
    except Exception as exc:
        logger.warning("map_builder 自动标注失败，保留 LLM 地图: %s", exc)
    if builder_layer:
        map_layer = builder_layer

    for chart in charts:
        yield "chart", chart
    if map_layer:
        yield "map_layer", map_layer
    yield "narrative", narrative
    yield "done", {
        "reportId": report_id,
        "status": "partial" if partial else "ready",
        "partial": partial,
        "skillId": profile["skillId"],
        "skillName": profile["skillName"],
        "dataMode": "real",
        "orchestration": "data-fallback" if partial else "llm",
    }
    logger.info(
        "真实态势生成完成: reportId=%s datasets=%s charts=%s partial=%s",
        report_id, len(bundles), len(charts), partial,
    )


# 对外入口：Phase 1 用 mock，Phase 2 切换为 real
async def generate(
    query: str,
    report_id: str,
    skill_context: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[SSEEvent]:
    """态势生成入口；mock 只能通过环境变量显式启用。"""
    if config.SITUATION_GENERATION_MODE == "mock":
        async for evt in mock_generate(query, report_id, skill_context):
            yield evt
        return
    async for evt in real_generate(query, report_id, skill_context, context):
        yield evt
