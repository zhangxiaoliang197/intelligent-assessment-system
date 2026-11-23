"""评估分析中的数据库指标问答。

当用户问题命中动态本体中的评估指标时，直接按本体口径在 MySQL 案例表上计算，
不依赖 Text-to-SQL 的随机路由。返回值与评估流式接口的 result 事件结构一致。

触发条件很克制：必须命中本体指标的同义词/标准名，否则返回 None，交回原编排链路。
"""
from __future__ import annotations

import re
from typing import Any

from airpower_metrics import PROFILES, compute_side, data_source_info, load_rows
from ontology_assessment import _load_ontology
from ontology_semantic import (
    BASE,
    DATA_SOURCE_TYPE,
    DATA_TABLE_TYPE,
    _entity_by_type,
    _metric_catalog,
    _match_metrics,
    _resolve_ontology_id,
)

PROFILE = "v1.2"

SIDE_LABELS = {"red": "红方", "blue": "蓝方"}

METRIC_ALIASES = {
    "index": "制空权指数",
    "sorties_share": "出动强度指数",
    "mission_success": "任务完成率",
    "ready_rate": "战备完好率",
    "exchange_ratio": "战损交换比",
    "radar_hours": "雷达保障时长",
    "radar_coverage": "持续保障指数",
    "sorties": "出动架次",
}


def _detect_side(question: str, dimensions: dict[str, str] | None = None) -> str:
    dim_side = str((dimensions or {}).get("阵营") or "")
    if "蓝" in dim_side or "敌" in dim_side:
        return "blue"
    if "红" in dim_side:
        return "red"
    if any(word in question for word in ("蓝方", "敌方", "对手")):
        return "blue"
    return "red"


def _dimension_days(question: str, dimensions: dict[str, str] | None = None) -> int | None:
    text = question or ""
    dim_time = str((dimensions or {}).get("时间范围") or "")
    for source in (text, dim_time):
        match = re.search(r"最近\s*(\d+)\s*(?:天|日)", source)
        if match:
            return int(match.group(1))
    if "全部" in dim_time:
        return None
    return None


def _date_window(
    rows: list[dict[str, Any]],
    question: str,
    dimensions: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str, str, str]:
    days = _dimension_days(question, dimensions)
    dates = sorted({str(row.get("date")) for row in rows if row.get("date")})
    if not dates:
        return rows, "全部日期", "", ""
    if not days:
        return rows, f"{dates[0]} ~ {dates[-1]}", dates[0], dates[-1]
    days = max(1, min(days, len(dates)))
    cutoff = dates[-days]
    return ([row for row in rows if str(row.get("date")) >= cutoff],
            f"{cutoff} ~ {dates[-1]}", cutoff, dates[-1])


def _side_rows(rows: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("side") == side]


def _weighted_success(subset: list[dict[str, Any]]) -> float:
    sorties = sum(float(row.get("sorties") or 0) for row in subset)
    if not sorties:
        return 0.0
    weighted = sum(float(row.get("sorties") or 0) * float(row.get("mission_success_rate") or 0)
                   for row in subset)
    return round(weighted / sorties * 100, 2)


def _mean(subset: list[dict[str, Any]], key: str, scale: float = 1.0) -> float:
    values = [float(row.get(key) or 0) for row in subset]
    return round(sum(values) / len(values) * scale, 2) if values else 0.0


def _metric_value(key: str, subset: list[dict[str, Any]], total_rows: list[dict[str, Any]] | None = None) -> tuple[float, str]:
    if key == "sorties":
        return round(sum(float(row.get("sorties") or 0) for row in subset), 2), "架次"
    if key == "mission_success":
        return _weighted_success(subset), "%"
    if key == "ready_rate":
        return _mean(subset, "ready_rate", 100), "%"
    if key == "radar_hours":
        return _mean(subset, "radar_hours"), "小时/日"
    if key == "sorties_share":
        own = sum(float(row.get("sorties") or 0) for row in subset)
        total = sum(float(row.get("sorties") or 0) for row in (total_rows or subset))
        return round(own / total * 100, 2) if total else 0.0, "分"
    if key == "radar_coverage":
        return round(_mean(subset, "radar_hours") / 24 * 100, 2), "分"
    return 0.0, ""


def _base_names(ontology: dict[str, Any]) -> list[str]:
    return [entity.get("name", "") for entity in _entity_by_type(ontology, BASE)]


def _sql_for(
    key: str,
    side: str,
    by_base: bool,
    start: str,
    end: str,
    airbase: str = "",
) -> str:
    side_label = SIDE_LABELS[side]
    enemy_label = SIDE_LABELS["blue" if side == "red" else "red"]
    where = f"side = '{side_label}'"
    if start and end:
        where += f" AND stat_date BETWEEN '{start}' AND '{end}'"
    if airbase:
        where += f" AND airbase = '{airbase}'"
    if key == "sorties":
        expr = "SUM(sorties) AS sorties"
    elif key == "mission_success":
        expr = "ROUND(SUM(sorties * mission_success_rate) / SUM(sorties) * 100, 2) AS mission_success_rate"
    elif key == "ready_rate":
        expr = "ROUND(AVG(ready_rate) * 100, 2) AS ready_rate"
    elif key == "radar_hours":
        expr = "ROUND(AVG(radar_hours), 2) AS radar_hours"
    elif key == "radar_coverage":
        expr = "ROUND(AVG(radar_hours) / 24 * 100, 2) AS radar_coverage"
    elif key == "sorties_share":
        expr = ("ROUND(SUM(sorties) / (SELECT SUM(sorties) FROM assessment.airpower_case_daily "
                f"WHERE stat_date BETWEEN '{start}' AND '{end}') * 100, 2) AS sorties_share")
    elif key == "exchange_ratio":
        expr = ("ROUND((SELECT SUM(losses) FROM assessment.airpower_case_daily "
                f"WHERE side = '{enemy_label}' AND stat_date BETWEEN '{start}' AND '{end}') "
                "/ SUM(losses), 2) AS exchange_ratio")
    elif key == "index":
        expr = "'v1.2 权重合成' AS formula"
    else:
        expr = "COUNT(*) AS rows"
    if by_base and key != "exchange_ratio":
        return (f"SELECT airbase, {expr} FROM assessment.airpower_case_daily "
                f"WHERE {where} GROUP BY airbase ORDER BY airbase")
    return (f"SELECT {expr} FROM assessment.airpower_case_daily WHERE {where}")


def try_answer_metric_question(
    question: str,
    ontology_id: str = "",
    profile: str = PROFILE,
    metric_keys: list[str] | None = None,
    dimensions: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """命中本体指标时返回可直接下发的问答结果；否则返回 None。

    metric_keys / dimensions 来自用户在前端确认过的口径。确认口径优先于
    从问题文本中猜测的结果，避免“确认了却没按确认值计算”。
    """
    if not question or len(question.strip()) < 2:
        return None
    dimensions = dimensions or {}
    resolved_id = _resolve_ontology_id(ontology_id)
    try:
        ontology = _load_ontology(resolved_id)
        catalog = _metric_catalog(ontology)
    except Exception:
        return None
    if not catalog:
        return None
    profile = str(dimensions.get("口径版本") or profile)
    if profile not in PROFILES:
        profile = PROFILE
    catalog_by_key = {item.get("key", ""): item for item in catalog}
    selected: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item_key in (metric_keys or []):
        item = catalog_by_key.get(item_key)
        if not item or item_key not in METRIC_ALIASES or item_key in seen_keys:
            continue
        seen_keys.add(item_key)
        selected.append({
            **item,
            "matchedTerm": item.get("name", item_key),
            "confidence": 1,
            "reason": "用户已确认指标口径",
        })
        if len(selected) >= 3:
            break
    if not selected:
        matches = _match_metrics(question, catalog)
        if not matches:
            return None
        for item in matches:
            item_key = item.get("key", "")
            if not item.get("matchedTerm") or item_key not in METRIC_ALIASES or item_key in seen_keys:
                continue
            seen_keys.add(item_key)
            selected.append(item)
            if len(selected) >= 3:
                break
    if not selected:
        return None
    matched_term = "、".join(str(item.get("matchedTerm")) for item in selected)
    metric = selected[0]
    key = metric.get("key", "")

    all_rows = load_rows()
    side = _detect_side(question, dimensions)
    windowed, date_text, start, end = _date_window(all_rows, question, dimensions)
    own_rows = _side_rows(windowed, side)
    base_filter = str(dimensions.get("空军基地") or "").strip()
    if base_filter in ("全部", "全部基地", "不限", "任意"):
        base_filter = ""
    if base_filter:
        own_rows = [row for row in own_rows if str(row.get("airbase")) == base_filter]
    if not own_rows:
        return None
    source_info = data_source_info()
    side_label = SIDE_LABELS[side]
    by_base = any(word in question for word in ("各基地", "按基地", "基地分别", "每个基地"))
    if key == "exchange_ratio" or base_filter:
        by_base = False
    rows: list[dict[str, Any]] = []
    sql_parts: list[str] = []

    if key == "index":
        base_scope = windowed
        if base_filter:
            base_scope = [row for row in windowed if str(row.get("airbase")) == base_filter]
        own = compute_side(base_scope, side, profile)
        enemy = compute_side(base_scope, "blue" if side == "red" else "red", profile)
        scope_text = f"{base_filter}，" if base_filter else ""
        rows.append({"指标": METRIC_ALIASES[key], "阵营": side_label, "数值": own["index"], "单位": "分"})
        for part_key, part_name in (
            ("sorties_share", "出动强度指数"),
            ("mission_success", "任务完成率"),
            ("ready_rate", "战备完好率"),
            ("exchange_score", "战损交换比"),
            ("radar_coverage", "持续保障指数"),
        ):
            rows.append({"指标": f"分项·{part_name}", "阵营": side_label,
                         "数值": round(float(own["parts"][part_key]) * 100, 2), "单位": "分"})
        answer = (
            f"基于动态本体指标「制空权指数」的口径，在 MySQL {source_info.get('dataset')} 上计算"
            f"（{date_text}，{scope_text}{side_label}）：制空权指数 {own['index']} 分，对方 {enemy['index']} 分。"
        )
        sql_parts.append(_sql_for("index", side, False, start, end, base_filter))
    elif by_base:
        base_metrics = [item for item in selected if item.get("key") != "exchange_ratio"]
        names = _base_names(ontology)
        if not names:
            names = sorted({str(row.get("airbase")) for row in own_rows if row.get("airbase")})
        for base_name in names:
            subset = [row for row in own_rows if row.get("airbase") == base_name]
            if not subset:
                continue
            record: dict[str, Any] = {"基地": base_name, "阵营": side_label}
            for item in base_metrics:
                value, metric_unit = _metric_value(item["key"], subset, windowed)
                column = f"{METRIC_ALIASES[item['key']]}({metric_unit})"
                record[column] = value
            rows.append(record)
        if not rows:
            return None
        highlights = []
        for item in base_metrics:
            column = next((col for col in rows[0] if col.startswith(METRIC_ALIASES[item["key"]])), "")
            if not column:
                continue
            best = max(rows, key=lambda row: float(row[column]))
            worst = min(rows, key=lambda row: float(row[column]))
            highlights.append(f"{METRIC_ALIASES[item['key']]}最高 {best['基地']}（{best[column]}），"
                              f"最低 {worst['基地']}（{worst[column]}）")
        answer = (f"基于动态本体指标「{'、'.join(METRIC_ALIASES[item['key']] for item in base_metrics)}」的口径，"
                  f"在 MySQL {source_info.get('dataset')} 上按基地汇总（{date_text}，{side_label}）："
                  + "；".join(highlights) + "。")
        for item in base_metrics:
            sql_parts.append(_sql_for(item["key"], side, True, start, end))
    else:
        enemy_rows = _side_rows(windowed, "blue" if side == "red" else "red")
        if base_filter:
            enemy_rows = [row for row in enemy_rows if str(row.get("airbase")) == base_filter]
        values: list[str] = []
        for item in selected:
            item_key = item["key"]
            item_name = METRIC_ALIASES[item_key]
            value, metric_unit = _metric_value(item_key, own_rows, windowed)
            if item_key == "exchange_ratio":
                own_loss = sum(float(row.get("losses") or 0) for row in own_rows)
                enemy_loss = sum(float(row.get("losses") or 0) for row in enemy_rows)
                value = round(enemy_loss / own_loss, 2) if own_loss else 0.0
                metric_unit = "倍"
            rows.append({"指标": item_name, "阵营": side_label, "数值": value, "单位": metric_unit})
            values.append(f"{item_name} = {value} {metric_unit}")
            sql_parts.append(_sql_for(item_key, side, False, start, end, base_filter))
        scope_text = f"{base_filter}，" if base_filter else ""
        answer = (f"基于动态本体指标「{'、'.join(METRIC_ALIASES[item['key']] for item in selected)}」的口径，"
                  f"在 MySQL {source_info.get('dataset')} 上计算（{date_text}，{scope_text}{side_label}）："
                  + "；".join(values) + "。")

    sql = ";\n".join(sql_parts)
    columns = list(rows[0].keys())
    table_nodes = _entity_by_type(ontology, DATA_TABLE_TYPE)
    source_nodes = _entity_by_type(ontology, DATA_SOURCE_TYPE)
    source_info = data_source_info()
    metric_names = [METRIC_ALIASES[item["key"]] for item in selected]
    name_text = "、".join(metric_names)
    chart_columns = [col for col in columns if col not in ("基地", "阵营")]
    chart = {
        "vizType": "bar" if by_base else "table",
        "xAxis": "基地" if by_base else "指标",
        "yAxis": chart_columns if by_base else ["数值"],
        "chartTitle": f"{base_filter + '·' if base_filter else ''}{side_label}{name_text}（{date_text}）",
    }
    return {
        "steps": [
            {"step": 1, "description": "本体语义映射", "status": "completed",
             "detail": f"问题命中本体指标「{name_text}」（{metric.get('attributePath') or name_text}）",
             "thinking": "", "progress": 100},
            {"step": 2, "description": "数据库指标计算", "status": "completed",
             "detail": f"读取 {source_info.get('dataset')}，按本体口径计算 {side_label} {name_text}",
             "thinking": sql, "progress": 100},
            {"step": 3, "description": "结论生成", "status": "completed", "detail": answer, "thinking": "", "progress": 100},
        ],
        "result": {
            "type": "general",
            "final_answer": answer,
            "analysis": answer,
            "generatedSql": sql,
            "sqlExplanation": f"基于动态本体指标口径，在 {source_info.get('dataset')} 上计算；{date_text}",
            "rawResults": rows,
            "totalRows": len(rows),
            "columns": columns,
            "intent": "数据查询",
            "query_type": "metric_query",
            "need_conclusion": True,
            "need_chart": by_base,
            "database_used": source_info.get("databaseId", ""),
            "database_name": source_info.get("database", ""),
            "chartConfig": chart,
            "map_annotations": "",
            "ontology": {
                "id": resolved_id,
                "metricKey": key,
                "metricKeys": [item["key"] for item in selected],
                "metricName": name_text,
                "matchedTerm": matched_term,
                "profile": profile,
                "side": side,
                "dimensions": dimensions,
                "dataSource": source_info,
                "tableNodes": [node.get("name") for node in table_nodes],
                "sourceNode": (source_nodes[0].get("name") if source_nodes else ""),
            },
        },
    }
