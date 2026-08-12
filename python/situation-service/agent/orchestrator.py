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
from agent import tools
from agent.prompts import get_system_prompt
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


def _apply_execution_plan(bundles: list, profile: dict, context: dict) -> list[dict]:
    """Execute parameter bindings deterministically before any evidence reaches the LLM."""
    parameters = ((context.get("skill") or {}).get("parameters") or {})
    bindings = profile.get("parameterBindings") or {}
    execution = []
    for bundle in bundles:
        rows = _rows_from_payload(bundle.get("payload"))
        input_count = len(rows)
        applied = []
        for key, value in parameters.items():
            binding = bindings.get(key) or {"operator": "equals", "field": key}
            operator = binding.get("operator")
            field = _resolve_field(rows, str(binding.get("field") or key))
            if operator == "limit":
                rows = rows[:max(1, min(int(value), config.SITUATION_DATA_ROW_LIMIT))]
                applied.append({"parameter": key, "operator": operator, "value": value})
            elif operator == "equals" and field:
                wanted = {str(item) for item in value} if isinstance(value, list) else {str(value)}
                rows = [row for row in rows if str(row.get(field)) in wanted]
                applied.append({"parameter": key, "operator": operator, "field": field, "value": value})
            elif operator == "numeric-threshold" and field:
                threshold = _as_number(value)
                if threshold is not None:
                    rows = [
                        row for row in rows
                        if (number := _as_number(row.get(field))) is not None and number >= threshold
                    ]
                    applied.append({"parameter": key, "operator": operator, "field": field, "value": threshold})
            elif operator == "time-window" and field:
                days = int(value) if isinstance(value, (int, float)) else None
                if days:
                    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, days))
                    rows = [row for row in rows if (stamp := _coerce_datetime(row.get(field))) and stamp >= cutoff]
                    applied.append({"parameter": key, "operator": operator, "field": field, "days": days})
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
    return execution


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
        return tools.query_admin_dataset(matches[0], config.SITUATION_DATA_ROW_LIMIT)
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
        "samples": samples,
        "evidenceHash": _evidence_digest(rows),
    }


def _prompt_payload(bundles: list) -> list:
    return [_aggregate_evidence(bundle) for bundle in bundles]


def _run_llm_orchestration(query: str, profile: dict, context: dict, bundles: list) -> dict:
    evidence = json.dumps(_prompt_payload(bundles), ensure_ascii=False, default=str)
    if len(evidence) > config.SITUATION_LLM_EVIDENCE_CHARS:
        evidence = evidence[:config.SITUATION_LLM_EVIDENCE_CHARS] + "…(聚合证据已截断)"
    schema = {
        "charts": [{
            "chartId": "c_1", "type": "bar|line|pie|radar|gauge|scatter|heatmap|relation|sankey",
            "title": "标题", "datasetRef": "真实 datasetId", "option": {"series": []},
        }],
        "mapLayer": {
            "layerId": "real_map", "points": [], "routes": [], "areas": [], "circles": [],
            "layerConfig": {"name": "图层名", "color": "#e74c3c", "opacity": 0.85, "visible": True},
        },
        "narrative": {"intro": "态势介绍", "explanations": [{"chartId": "c_1", "text": "说明"}]},
    }
    messages = [
        {
            "role": "system",
            "content": get_system_prompt() + """
数据工具已经由系统执行完毕。你现在只需根据所给真实证据返回一个 JSON 对象。
输入仅包含脱敏聚合证据，不含原始业务行。不得补造记录、数值、地点或经纬度；无坐标证据时地图数组保持为空。
图表的 datasetRef 必须使用输入中的 datasetId，option 必须是可直接渲染的 ECharts JSON。
先规划 charts/mapLayer，再写 narrative；最终回复只能包含 JSON。""",
        },
        {
            "role": "user",
            "content": (
                f"用户问题：{query}\n"
                f"Skill：{profile['skillName']}\n"
                f"分析目标：{profile.get('analysisGoal', '')}\n"
                f"关注指标：{json.dumps(profile['focusMetrics'], ensure_ascii=False)}\n"
                f"建议图表：{json.dumps(profile['chartTypes'], ensure_ascii=False)}\n"
                f"运行参数：{json.dumps((context.get('skill') or {}).get('parameters', {}), ensure_ascii=False, default=str)}\n"
                f"返回结构示例：{json.dumps(schema, ensure_ascii=False)}\n"
                f"真实证据：{evidence}"
            ),
        },
    ]
    result = call_llm_json(messages, temperature=0.2, max_tokens=config.LLM_MAX_TOKENS)
    if not isinstance(result, dict):
        raise ValueError("LLM 未返回对象结构")
    return result


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


def _sanitize_map_layer(value: Any, profile: dict) -> dict:
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
    return {
        "layerId": str(value.get("layerId") or f"skill_{profile['skillId'] or 'general'}"),
        "points": points, "routes": routes, "areas": areas, "circles": circles,
        "layerConfig": layer_config,
    }


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
    for row in _rows_from_payload(bundle.get("payload")):
        for value in row.values():
            number = _as_number(value)
            if number is not None:
                values.append(round(number, 6))
    return values


def _verification(chart: dict, bundle: dict, transform: dict) -> dict:
    output_values = _numeric_values(chart["option"])
    evidence_values = _bundle_numbers(bundle)
    operation = transform.get("operation", "evidence-membership")
    verified = bool(output_values) and all(
        any(math.isclose(value, candidate, rel_tol=1e-6, abs_tol=1e-6) for candidate in evidence_values)
        for value in output_values
    )
    return {
        "verified": verified,
        "method": operation,
        "checkedValues": len(output_values),
        "evidenceHash": _evidence_digest(_rows_from_payload(bundle.get("payload"))),
        "verifiedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


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
        if chart_type not in _CHART_TYPES:
            chart_type = "bar"
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
            raise ValueError(f"图表 {chart_id} 的数值无法由证据重算验证")
        charts.append(chart)
    if not charts:
        raise ValueError("LLM 未生成可用图表")
    raw_map = result.get("mapLayer")
    if not raw_map and isinstance(result.get("mapLayers"), list) and result["mapLayers"]:
        raw_map = result["mapLayers"][0]
    map_layer = _sanitize_map_layer(raw_map, profile)
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
    }
    return charts, map_layer, narrative


def _as_number(value: Any) -> Optional[float]:
    try:
        text = str(value).strip().replace(",", "").rstrip("%")
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _fallback_option(chart_type: str, rows: list, metric: str) -> tuple[str, dict]:
    rows = rows[:20] or [{"数据": 0}]
    keys = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else ["数据"]
    numeric_key = next((key for key in keys if any(_as_number(row.get(key)) is not None for row in rows)), None)
    label_key = next((key for key in keys if key != numeric_key), keys[0])
    labels = [str(row.get(label_key, index + 1))[:30] for index, row in enumerate(rows)]
    if numeric_key:
        values = [_as_number(row.get(numeric_key)) or 0 for row in rows]
    else:
        counts: Dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        labels, values = list(counts.keys()), list(counts.values())
    if chart_type == "pie":
        return "pie", {"tooltip": {"trigger": "item"}, "legend": {"bottom": 0}, "series": [{
            "name": metric, "type": "pie", "radius": ["35%", "68%"],
            "data": [{"name": label, "value": value} for label, value in zip(labels, values)],
        }]}
    if chart_type == "radar":
        max_value = max([float(value) for value in values] + [1.0])
        return "radar", {"tooltip": {}, "radar": {"indicator": [
            {"name": label, "max": max_value * 1.2} for label in labels[:8]
        ]}, "series": [{"name": metric, "type": "radar", "data": [{"name": metric, "value": values[:8]}]}]}
    if chart_type == "gauge":
        return "gauge", {"series": [{"name": metric, "type": "gauge", "progress": {"show": True},
                                       "data": [{"name": labels[0], "value": values[0]}]}]}
    effective = "line" if chart_type == "line" else "bar"
    return effective, {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": str(numeric_key or metric)},
        "series": [{"name": metric, "type": effective, "smooth": effective == "line", "data": values}],
    }


def _fallback_map(profile: dict, bundles: list) -> dict:
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
    }, profile)


def _data_fallback(query: str, profile: dict, bundles: list) -> tuple[list, dict, dict]:
    charts = []
    metrics = profile["focusMetrics"][:3]
    requested_types = profile["chartTypes"][:3]
    for index, metric in enumerate(metrics, start=1):
        bundle = bundles[(index - 1) % len(bundles)]
        chart_type, option = _fallback_option(
            requested_types[(index - 1) % len(requested_types)],
            _rows_from_payload(bundle["payload"]),
            metric,
        )
        chart = {
            "chartId": f"c_{index}", "type": chart_type, "title": metric,
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
    }
    return charts, _fallback_map(profile, bundles), narrative


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

    for step in profile.get("workflow") or []:
        yield "step", {
            "sequence": step.get("sequence"),
            "name": step.get("name"),
            "operator": step.get("operator"),
            "status": "completed",
            "datasets": [bundle.get("source") for bundle in bundles],
            "inputRows": sum(int((bundle.get("execution") or {}).get("inputRows", 0)) for bundle in bundles),
            "outputRows": sum(int((bundle.get("execution") or {}).get("outputRows", 0)) for bundle in bundles),
        }

    for index, bundle in enumerate(bundles, start=1):
        bundle["datasetId"] = f"real_{index}_{_safe_id(bundle['source'])}"
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
            "evidenceHash": _evidence_digest(_rows_from_payload(bundle.get("payload"))),
        }

    partial = False
    try:
        result = await asyncio.to_thread(_run_llm_orchestration, query, profile, runtime_context, bundles)
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
        charts, map_layer, narrative = _data_fallback(query, profile, bundles)

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
