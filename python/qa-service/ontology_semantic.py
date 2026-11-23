"""动态本体支撑评估分析的四个独立能力。

四个能力各自触发、互不串联，全部以本体为语义与结构依据：

1. semantic-map  语义统一：把用户问题里的口语指标映射到本体中的指标属性/指标实例；
2. clarify       模糊确认：基于本体「评估维度」实例，确认必选维度（时间、评估类型）
                 以及指标计算可能出现的多值维度；
3. trace         结果溯源：从指标属性 → 口径公式 → 数据字段绑定 → 本体实例 → 原始记录；
4. attribution   归因分析：基于指标计算结果做公式分解、关系传播、反事实与实例下钻。

每个接口都返回图谱高亮所需的 nodeIds / edgePairs，供前端跳转动态本体页面展示。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from airpower_metrics import (
    DATA_DIR,
    PROFILES,
    _to_float,
    compute_side,
    conclusion,
    data_source_info,
    load_rows,
)
from ontology_assessment import _get, _load_ontology, _pick

ONTOLOGY_SERVICE_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://localhost:10256").rstrip("/")

router = APIRouter(prefix="/evaluation", tags=["本体语义能力"])

DEFAULT_ONTOLOGY = "ont_ede9d116"

BATTLE = "战场"
METRIC_TYPE = "评估指标"
DIMENSION_TYPE = "评估维度"
BASE = "空军基地"
RADAR = "雷达站"
AIRCRAFT = "作战飞机"
SORTIE = "出动架次"
DATA_SOURCE_TYPE = "数据源"
DATA_TABLE_TYPE = "数据表"

FOCUS_TYPES = [BATTLE, METRIC_TYPE, BASE, RADAR, AIRCRAFT, SORTIE, DATA_SOURCE_TYPE, DATA_TABLE_TYPE]

# 本体指标属性名 → 指标 key（与 airpower_metrics 指标链一致）
KEY_BY_ATTRIBUTE = {
    "制空权指数": "index",
    "出动强度": "sorties",
    "任务完成率": "mission_success",
    "战备完好率": "ready_rate",
    "交换比": "exchange_ratio",
    "雷达保障时长": "radar_hours",
    "出动架次": "sorties",
    "持续保障指数": "radar_coverage",
}

METRIC_NAMES = {
    "index": "制空权指数",
    "sorties_share": "出动强度指数",
    "mission_success": "任务完成率",
    "ready_rate": "战备完好率",
    "exchange_ratio": "战损交换比",
    "radar_hours": "雷达保障时长",
    "radar_coverage": "持续保障指数",
    "sorties": "出动架次",
}

# 指数分项 key → 指标目录 key
PART_METRIC_KEY = {"exchange_score": "exchange_ratio"}

# 指标对应的原始数据列
METRIC_COLUMN = {
    "index": "",
    "sorties_share": "sorties",
    "mission_success": "mission_success_rate",
    "ready_rate": "ready_rate",
    "exchange_ratio": "losses",
    "radar_hours": "radar_hours",
    "radar_coverage": "radar_hours",
    "sorties": "sorties",
}

# 指标计算涉及的本体实体类型
METRIC_ENTITY_TYPES = {
    "index": [BATTLE, BASE, RADAR, AIRCRAFT, SORTIE],
    "sorties_share": [BATTLE, BASE, SORTIE],
    "mission_success": [BATTLE, BASE, SORTIE],
    "ready_rate": [BATTLE, AIRCRAFT],
    "exchange_ratio": [BATTLE, BASE, SORTIE],
    "radar_hours": [RADAR, BASE],
    "radar_coverage": [RADAR, BASE],
    "sorties": [BATTLE, BASE, SORTIE],
}

# 维度口语别名（用于从问题中识别已给出的维度取值）
DIMENSION_ALIASES: dict[str, dict[str, list[str]]] = {
    "时间范围": {
        "最近7天": ["最近7天", "近7天", "7天", "7日", "一周"],
        "最近14天": ["最近14天", "近14天", "14天", "14日", "两周", "半个月"],
        "最近30天": ["最近30天", "近30天", "30天", "30日", "一个月"],
    },
    "评估类型": {
        "红蓝对比": ["红蓝对比", "红蓝双方", "对比", "比较", "谁更", "优劣"],
        "单方评估": ["单方", "仅红方", "仅蓝方", "只看红方", "只看蓝方"],
    },
    "阵营": {
        "红方": ["红方", "我方"],
        "蓝方": ["蓝方", "敌方"],
    },
    "口径版本": {
        "v1.2": ["v1.2", "1.2", "出动规模主导"],
        "v1.3": ["v1.3", "1.3", "持续保障主导"],
    },
}


# ── 请求模型 ──────────────────────────────────────────────
class SemanticRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ontology_id: str = Field(default="", alias="ontologyId")
    question: str = ""
    profile: str = "v1.2"
    metric_key: str = Field(default="", alias="metricKey")
    metric_keys: list[str] = Field(default_factory=list, alias="metricKeys")
    side: str = "red"
    dimensions: dict[str, str] = Field(default_factory=dict)


def _resolve_ontology_id(ontology_id: str) -> str:
    if ontology_id.strip():
        return ontology_id.strip()
    path = DATA_DIR / "ontology_id.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip() or DEFAULT_ONTOLOGY
    return DEFAULT_ONTOLOGY


def _ontology_name(ontology_id: str) -> str:
    try:
        payload = _get(f"/ontology/{ontology_id}")
        return (payload.get("data") or {}).get("name", "") or ""
    except Exception:
        return ""


def _profile_key(value: str) -> str:
    return value if value in PROFILES else "v1.2"


def _side_key(value: str) -> str:
    text = (value or "").strip().lower()
    if text in ("blue", "蓝方", "enemy", "敌方") or "蓝" in text:
        return "blue"
    return "red"


def _dimension_value(dimensions: dict[str, str], *names: str) -> str:
    for name in names:
        if name in dimensions and dimensions[name]:
            return str(dimensions[name])
    return ""


def _metric_value(key: str, own: dict[str, Any], enemy: dict[str, Any], profile: str) -> float:
    if key == "index":
        return own["index"]
    if key == "sorties":
        return own["base"]["sorties"]
    if key == "mission_success":
        return round(own["base"]["mission_success"] * 100, 2)
    if key == "ready_rate":
        return round(own["base"]["ready_rate"] * 100, 2)
    if key == "exchange_ratio":
        return own["exchange_ratio"]
    if key == "radar_hours":
        return own["base"]["radar_hours"]
    if key == "sorties_share":
        return round(own["parts"]["sorties_share"] * 100, 2)
    if key == "exchange_score":
        return round(own["parts"]["exchange_score"] * 100, 2)
    if key == "radar_coverage":
        return round(own["parts"]["radar_coverage"] * 100, 2)
    return 0.0


def _metric_unit(key: str) -> str:
    return {
        "index": "分",
        "sorties_share": "分",
        "mission_success": "%",
        "ready_rate": "%",
        "exchange_ratio": "倍",
        "radar_hours": "小时/日",
        "radar_coverage": "分",
        "sorties": "架次",
    }.get(key, "")


def _split_values(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[|,，、;；]", text or "") if item.strip()]


def _parse_props(entity: dict) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in entity.get("properties", []) or []:
        if isinstance(item, dict):
            result[item.get("name", "")] = item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            result[str(item[0])] = item[1]
    return result


def _entity_by_type(data: dict, type_name: str) -> list[dict]:
    return [e for e in data["entities"] if e.get("_type") == type_name]


def _entity_name_map(data: dict) -> dict[str, dict]:
    return {e.get("name", ""): e for e in data["entities"]}


def _battle_pair(data: dict) -> tuple[dict, dict | None]:
    battle = _pick(data["entities"], BATTLE, "红方")
    if not battle:
        battle = _pick(data["entities"], BATTLE)
    if not battle:
        raise HTTPException(400, "该本体中没有「战场」类型实例，无法执行本体语义映射")
    return battle, _pick(data["entities"], BATTLE, "蓝方")


# ── 指标语义目录（从本体读取，而不是写死在代码里）──────────
def _metric_catalog(data: dict) -> list[dict[str, Any]]:
    battle, _ = _battle_pair(data)
    metric_entities = {e.get("name", ""): e for e in _entity_by_type(data, METRIC_TYPE)}
    battle_type = next((t for t in data["meta"].get("entity_types", []) if t.get("name") == BATTLE), {})
    catalog: dict[str, dict[str, Any]] = {}

    for schema in battle_type.get("property_schema", []) or []:
        name = schema.get("name", "")
        key = KEY_BY_ATTRIBUTE.get(name)
        if key is None:
            continue
        metric_entity = metric_entities.get(schema.get("standard_name") or name) or metric_entities.get(name)
        synonyms = list(schema.get("synonyms") or [])
        if metric_entity:
            synonyms += _split_values(str(_parse_props(metric_entity).get("同义词", "")))
        catalog[key] = {
            "key": key,
            "name": schema.get("standard_name") or name,
            "propertyName": name,
            "attributePath": f"{BATTLE}.{name}",
            "unit": schema.get("unit") or _metric_unit(key),
            "formula": schema.get("formula", ""),
            "synonyms": list(dict.fromkeys([name] + synonyms)),
            "dimension": schema.get("dimension", ""),
            "layer": 3 if key == "index" else (2 if key in ("sorties_share", "radar_coverage") else 1),
            "metricEntityId": (metric_entity or {}).get("id", ""),
            "nodeIds": [battle["id"]] + ([metric_entity["id"]] if metric_entity else []),
            "battleId": battle["id"],
        }

    # 指标实例补充：本体里定义了、但战场属性骨架未覆盖的指标
    for name, entity in metric_entities.items():
        props = _parse_props(entity)
        standard = str(props.get("标准名") or name)
        key = next((v for k, v in KEY_BY_ATTRIBUTE.items() if k == name or METRIC_NAMES.get(v) == name), "")
        if not key or key in catalog:
            continue
        catalog[key] = {
            "key": key,
            "name": standard,
            "propertyName": name,
            "attributePath": f"{METRIC_TYPE}.{standard}",
            "unit": str(props.get("单位") or _metric_unit(key)),
            "formula": str(props.get("计算公式") or ""),
            "synonyms": list(dict.fromkeys([name] + _split_values(str(props.get("同义词", ""))))),
            "dimension": "",
            "layer": 1,
            "metricEntityId": entity.get("id", ""),
            "nodeIds": [battle["id"], entity["id"]],
            "battleId": battle["id"],
        }

    # 把物理表 / 数据源节点并入指标高亮链路，让溯源能直接落到数据库
    table_entities = {e.get("name", ""): e for e in _entity_by_type(data, DATA_TABLE_TYPE)}
    source_entity = next(iter(_entity_by_type(data, DATA_SOURCE_TYPE)), None)
    for item in catalog.values():
        entity = metric_entities.get(item["name"])
        bound_text = str(_parse_props(entity).get("数据绑定", "")) if entity else ""
        matched = re.search(r"\.([A-Za-z0-9_]+)(?:#|\s)", bound_text)
        if not matched:
            continue
        table = table_entities.get(matched.group(1))
        if table:
            item["nodeIds"] = list(dict.fromkeys(item["nodeIds"] + [table["id"]]))
            item["tableName"] = table.get("name", "")
            item["tableEntityId"] = table["id"]
        if source_entity:
            item["nodeIds"] = list(dict.fromkeys(item["nodeIds"] + [source_entity["id"]]))

    ordered = sorted(catalog.values(), key=lambda item: (0 if item["key"] == "index" else 1, item["key"]))
    return ordered


def _match_metrics(question: str, catalog: list[dict]) -> list[dict]:
    text = (question or "").strip()
    compact = re.sub(r"\s+", "", text)
    matches: list[tuple[float, dict, str]] = []
    for metric in catalog:
        best_term = ""
        for term in metric["synonyms"]:
            if not term:
                continue
            if term in compact:
                if len(term) > len(best_term):
                    best_term = term
        if best_term:
            score = 100 + len(best_term)
            matches.append((score, metric, best_term))
    matches.sort(key=lambda item: item[0], reverse=True)
    if not matches:
        default = next((m for m in catalog if m["key"] == "index"), catalog[0] if catalog else None)
        if not default:
            return []
        return [{**default, "matchedTerm": "", "confidence": 0.45, "reason": "未识别到具体指标，默认按制空权指数评估"}]
    result = []
    seen = set()
    for score, metric, term in matches[:3]:
        if metric["key"] in seen:
            continue
        seen.add(metric["key"])
        result.append({
            **metric,
            "matchedTerm": term,
            "confidence": 0.95 if len(term) >= 3 else 0.8,
            "reason": f"问题中的“{term}”与本体同义词对齐到「{metric['name']}」",
        })
    return result


def _rows_for(rows: list[dict], side: str, dimensions: dict[str, str]) -> list[dict]:
    subset = [r for r in rows if r.get("side") == side]
    base = _dimension_value(dimensions, "空军基地", "基地")
    aircraft = _dimension_value(dimensions, "机型")
    if base and not base.startswith("全部"):
        subset = [r for r in subset if r.get("airbase") == base]
    if aircraft and not aircraft.startswith("全部"):
        subset = [r for r in subset if r.get("aircraft_type") == aircraft]
    window = _dimension_value(dimensions, "时间范围", "时间")
    digits = re.findall(r"\d+", window)
    if digits:
        days = int(digits[0])
        dates = sorted({r.get("date", "") for r in rows if r.get("date")})
        if dates:
            latest = datetime.strptime(dates[-1], "%Y-%m-%d")
            start = latest - timedelta(days=max(days - 1, 0))
            subset = [r for r in subset if r.get("date", "") >= start.strftime("%Y-%m-%d")]
    return subset


def _relation_edges(data: dict, node_ids: list[str]) -> list[dict]:
    node_set = set(node_ids)
    edges = []
    seen = set()
    for relation in data["relations"]:
        source, target = relation.get("source_id"), relation.get("target_id")
        if source not in node_set or target not in node_set:
            continue
        key = (source, target, relation.get("relation_type", ""))
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "source": source,
            "target": target,
            "relation": relation.get("relation_type", ""),
            "relationId": relation.get("id", ""),
        })
    return edges


def _metric_node_ids(data: dict, key: str) -> list[str]:
    node_ids = []
    for metric in _metric_catalog(data):
        if metric["key"] == key:
            node_ids.extend(metric.get("nodeIds", []))
    return list(dict.fromkeys(node_ids))


# ── 1. 语义统一 ───────────────────────────────────────────
@router.post("/semantic-map")
async def semantic_map(request: SemanticRequest) -> dict:
    ontology_id = _resolve_ontology_id(request.ontology_id)
    data = _load_ontology(ontology_id)
    battle, _ = _battle_pair(data)
    catalog = _metric_catalog(data)
    metrics = _match_metrics(request.question, catalog)

    rows = load_rows()
    profile = _profile_key(request.profile)
    side = _side_key(request.side)
    red = compute_side(rows, "red", profile)
    blue = compute_side(rows, "blue", profile)
    own, enemy = (red, blue) if side == "red" else (blue, red)

    items = []
    for metric in metrics:
        key = metric["key"]
        items.append({
            **metric,
            "value": _metric_value(key, own, enemy, profile),
            "unit": metric.get("unit") or _metric_unit(key),
            "graphNodeIds": metric.get("nodeIds", []),
        })

    return {
        "success": True,
        "data": {
            "ontology": {"id": ontology_id, "name": _ontology_name(ontology_id)},
            "question": request.question,
            "battle": {"id": battle["id"], "name": battle.get("name")},
            "profile": {"key": profile, "name": PROFILES[profile]["name"]},
            "metrics": items,
            "defaultMetricKey": items[0]["key"] if items else "",
            "catalog": [
                {
                    "key": m["key"], "name": m["name"], "attributePath": m["attributePath"],
                    "unit": m["unit"], "synonyms": m["synonyms"],
                }
                for m in catalog
            ],
        },
    }


# ── 2. 模糊确认 ───────────────────────────────────────────
def _detect_dimension(dim_name: str, values: list[str], question: str) -> str:
    text = question or ""
    # 时间范围允许问题给出本体取值列表之外的“最近N天”，例如“最近5天”
    if dim_name == "时间范围":
        match = re.search(r"最近\s*(\d+)\s*(?:天|日)", text)
        if match:
            return f"最近{int(match.group(1))}天"
        if "今天" in text:
            return "最近1天"
    alias_map = DIMENSION_ALIASES.get(dim_name, {})
    for value in values:
        for alias in [value] + alias_map.get(value, []):
            if alias and alias in text:
                return value
    return ""


def _dimensions_from_ontology(data: dict) -> list[dict]:
    items = []
    for entity in _entity_by_type(data, DIMENSION_TYPE):
        props = _parse_props(entity)
        name = str(props.get("维度名称") or entity.get("name", ""))
        values = _split_values(str(props.get("取值列表", "")))
        items.append({
            "id": entity.get("id", ""),
            "name": name,
            "values": values,
            "required": str(props.get("是否必选") or "可选") == "必选",
            "default": str(props.get("默认值") or (values[0] if values else "")),
            "field": str(props.get("绑定字段") or ""),
            "appliesTo": _split_values(str(props.get("适用指标", ""))),
        })
    priority = {"时间范围": 0, "评估类型": 1, "阵营": 2, "口径版本": 3}
    items.sort(key=lambda item: (priority.get(item["name"], 9), item["name"]))
    return items


def _applies_to_metrics(dim: dict, metric_keys: list[str], catalog: list[dict]) -> bool:
    applies = dim.get("appliesTo") or []
    if not applies or "全部指标" in applies:
        return True
    names = {m["name"] for m in catalog if m["key"] in metric_keys}
    keys = {m["key"] for m in catalog if m["key"] in metric_keys}
    for item in applies:
        if item in names or item in keys:
            return True
    return False


@router.post("/clarify")
async def clarify(request: SemanticRequest) -> dict:
    ontology_id = _resolve_ontology_id(request.ontology_id)
    data = _load_ontology(ontology_id)
    battle, _ = _battle_pair(data)
    catalog = _metric_catalog(data)
    metric_keys = request.metric_keys or ([request.metric_key] if request.metric_key else [])
    if not metric_keys:
        metric_keys = [m["key"] for m in _match_metrics(request.question, catalog)]

    dims = _dimensions_from_ontology(data)
    required, optional, resolved = [], [], []
    for dim in dims:
        detected = _detect_dimension(dim["name"], dim["values"], request.question)
        record = {**dim, "detected": detected, "value": detected or dim["default"]}
        if detected:
            resolved.append({**record, "reason": f"问题中已给出「{dim['name']}：{detected}」"})
            continue
        if dim["required"]:
            required.append({
                **record,
                "question": f"请确认{dim['name']}（必选项）",
                "reason": "该维度为指标计算的必选项，问题中未明确给出",
            })
            continue
        if not _applies_to_metrics(dim, metric_keys, catalog):
            continue
        optional.append({
            **record,
            "question": f"「{dim['name']}」存在多个取值，是否按全部取值聚合？",
            "reason": "指标计算可能产出多维度数据，需要确认聚合口径",
            "ambiguous": len(dim["values"]) > 1,
        })

    return {
        "success": True,
        "data": {
            "ontology": {"id": ontology_id, "name": _ontology_name(ontology_id)},
            "battle": {"id": battle["id"], "name": battle.get("name")},
            "metricKeys": metric_keys,
            "required": required,
            "optional": optional,
            "resolved": resolved,
            "hasQuestions": bool(required or optional),
            "dimensionNodes": [dim["id"] for dim in dims if dim["id"]],
            "note": "必选维度需确认后才能锁定口径；可选项默认按全部取值聚合，仅本次问答生效。",
        },
    }


# ── 3. 结果溯源 ───────────────────────────────────────────
def _binding_of(metric: dict, side: str, dims: dict[str, str]) -> str:
    info = data_source_info()
    database = info.get("database") or "assessment"
    table = info.get("table") or "airpower_case_daily"
    column = METRIC_COLUMN.get(metric["key"], "")
    if not column:
        return f"{database}.{table} → 口径版本 {PROFILES.get('v1.2', {}).get('name', '')} 权重合成"
    filters = [f"side='{'红方' if side == 'red' else '蓝方'}'"]
    base = _dimension_value(dims, "空军基地", "基地")
    aircraft = _dimension_value(dims, "机型")
    if base and not base.startswith("全部"):
        filters.append(f"airbase='{base}'")
    if aircraft and not aircraft.startswith("全部"):
        filters.append(f"aircraft_type='{aircraft}'")
    agg = {
        "mission_success": "weighted",
        "ready_rate": "mean",
        "radar_hours": "mean",
        "radar_coverage": "mean",
        "exchange_ratio": "ratio",
        "sorties_share": "sum",
        "sorties": "sum",
    }.get(metric["key"], "sum")
    mode = "MySQL" if info.get("mode") == "mysql" else "CSV"
    return f"{mode}:{database}.{table}#{column}?{'&'.join(filters)} · agg={agg}"


def _records(rows: list[dict], key: str, side: str, limit: int = 12) -> list[dict]:
    column = METRIC_COLUMN.get(key, "")
    if not column:
        return []
    result = []
    for row in rows:
        result.append({
            "date": row.get("date", ""),
            "airbase": row.get("airbase", ""),
            "aircraft_type": row.get("aircraft_type", ""),
            "side": row.get("side", ""),
            "column": column,
            "value": row.get(column),
            "raw": {c: row.get(c) for c in ("sorties", "losses", "mission_success_rate", "ready_rate", "radar_hours", "fuel_days")},
        })
        if len(result) >= limit:
            break
    return result


@router.post("/trace")
async def trace(request: SemanticRequest) -> dict:
    ontology_id = _resolve_ontology_id(request.ontology_id)
    data = _load_ontology(ontology_id)
    battle, _ = _battle_pair(data)
    catalog = _metric_catalog(data)
    key = request.metric_key
    if not key:
        mapped = _match_metrics(request.question, catalog)
        key = mapped[0]["key"] if mapped else "index"
    metric = next((m for m in catalog if m["key"] == key), None)
    if not metric:
        metric = {"key": key, "name": METRIC_NAMES.get(key, key), "propertyName": key,
                  "attributePath": key, "unit": _metric_unit(key), "formula": "", "synonyms": [],
                  "nodeIds": [battle["id"]], "battleId": battle["id"]}

    profile = _profile_key(_dimension_value(request.dimensions, "口径版本") or request.profile)
    side = _side_key(_dimension_value(request.dimensions, "阵营") or request.side)
    plans = PROFILES[profile]["weights"]

    all_rows = load_rows()
    rows = _rows_for(all_rows, side, request.dimensions)
    red = compute_side(all_rows, "red", profile)
    blue = compute_side(all_rows, "blue", profile)
    own, enemy = (red, blue) if side == "red" else (blue, red)
    value = _metric_value(key, own, enemy, profile)

    name_map = _entity_name_map(data)
    base_names = {r.get("airbase") for r in rows if r.get("airbase")}
    bases = [e for e in _entity_by_type(data, BASE) if e.get("name") in base_names]
    if not bases:
        bases = _entity_by_type(data, BASE)

    node_ids = list(dict.fromkeys(metric.get("nodeIds", []) + [battle["id"]] + [b["id"] for b in bases]))
    steps: list[dict] = [{
        "level": "指标属性",
        "title": metric["attributePath"],
        "detail": f"本体指标「{metric['name']}」 · 指标层级 {metric.get('layer', '-')}",
        "nodeIds": metric.get("nodeIds", []),
    }]

    if key == "index":
        parts = PROFILES[profile]["weights"]
        total = sum(parts.values())
        detail = "；".join(f"{k}×{v:.2f}" for k, v in parts.items())
        steps.append({
            "level": "口径公式",
            "title": PROFILES[profile]["name"],
            "detail": f"权重合计 {total:.2f}；{detail}",
            "nodeIds": metric.get("nodeIds", []),
        })
        for part_key, weight in parts.items():
            catalog_key = PART_METRIC_KEY.get(part_key, part_key)
            part_metric = next((m for m in catalog if m["key"] == catalog_key), None)
            part_value = _metric_value(part_key, own, enemy, profile)
            contribution = round(part_value * weight, 2)
            steps.append({
                "level": "指标分解",
                "title": part_metric["name"] if part_metric else part_key,
                "detail": f"取值 {part_value}{part_metric['unit'] if part_metric else ''} × 权重 {weight:.2f} = 贡献 {contribution} 分",
                "nodeIds": (part_metric or {}).get("nodeIds", []),
            })
            steps.append({
                "level": "数据绑定",
                "title": _binding_of(part_metric or {"key": part_key}, side, request.dimensions),
                "detail": (part_metric or {}).get("formula", "") or "派生指标（无外部字段）",
                "nodeIds": (part_metric or {}).get("nodeIds", []),
            })
    else:
        steps.append({
            "level": "数据绑定",
            "title": _binding_of(metric, side, request.dimensions),
            "detail": f"计算公式：{metric.get('formula') or '—'}",
            "nodeIds": metric.get("nodeIds", []),
        })
        steps.append({
            "level": "实体实例",
            "title": f"{len(bases)} 个空军基地参与聚合",
            "detail": "、".join(b.get("name", "") for b in bases),
            "nodeIds": [b["id"] for b in bases],
        })

    records = _records(rows, key, side, 12)
    if records:
        for record in records[:6]:
            entity = name_map.get(record["airbase"])
            steps.append({
                "level": "原始记录",
                "title": f"{record['date']} · {record['airbase']}",
                "detail": f"{record['column']} = {record['value']}",
                "nodeIds": [entity["id"]] if entity else [],
            })
        node_ids.extend([r["id"] for r in (name_map.get(x["airbase"]) for x in records) if r])

    # 依据指标类型补充参与实体
    for type_name in METRIC_ENTITY_TYPES.get(key, [BATTLE]):
        node_ids.extend([e["id"] for e in _entity_by_type(data, type_name)])
    node_ids = list(dict.fromkeys(node_ids))

    source_info = data_source_info()
    return {
        "success": True,
        "data": {
            "ontology": {"id": ontology_id, "name": _ontology_name(ontology_id)},
            "question": request.question,
            "metric": {**metric, "value": value, "unit": metric.get("unit") or _metric_unit(key)},
            "profile": {"key": profile, "name": PROFILES[profile]["name"], "weights": plans},
            "side": side,
            "steps": steps,
            "sources": [{
                "dataset": source_info.get("dataset") or "airbase_daily.csv",
                "mode": source_info.get("mode", "csv"),
                "database": source_info.get("database", ""),
                "databaseId": source_info.get("databaseId", ""),
                "table": source_info.get("table", ""),
                "rows": len(rows),
                "columns": list(records[0]["raw"].keys()) if records else [],
                "filter": f"side={'红方' if side == 'red' else '蓝方'}" + (f" · {request.dimensions}" if request.dimensions else ""),
            }],
            "nodeIds": node_ids,
            "edgePairs": _relation_edges(data, node_ids),
            "focusTypes": FOCUS_TYPES,
        },
    }


# ── 4. 归因分析 ───────────────────────────────────────────
def _red_base_stats(rows: list[dict], side: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("side") != side:
            continue
        grouped.setdefault(row.get("airbase", ""), []).append(row)
    stats = []
    for name, items in grouped.items():
        sorties = sum(r.get("sorties") or 0 for r in items)
        success = sum((r.get("sorties") or 0) * (r.get("mission_success_rate") or 0) for r in items)
        ready = [r.get("ready_rate") for r in items if r.get("ready_rate") is not None]
        stats.append({
            "name": name,
            "sorties": round(sorties, 1),
            "mission_success": round(success / sorties * 100, 2) if sorties else 0,
            "ready_rate": round(sum(ready) / len(ready) * 100, 2) if ready else 0,
            "fuel_missing": any(r.get("fuel_days") is None for r in items),
        })
    return stats


@router.post("/attribution")
async def attribution(request: SemanticRequest) -> dict:
    ontology_id = _resolve_ontology_id(request.ontology_id)
    data = _load_ontology(ontology_id)
    battle, blue_battle = _battle_pair(data)
    catalog = _metric_catalog(data)
    profile = _profile_key(_dimension_value(request.dimensions, "口径版本") or request.profile)
    side = _side_key(_dimension_value(request.dimensions, "阵营") or request.side)
    key = request.metric_key or "index"

    all_rows = load_rows()
    rows = _rows_for(all_rows, side, request.dimensions) or all_rows
    red = compute_side(all_rows, "red", profile)
    blue = compute_side(all_rows, "blue", profile)
    own, enemy = (red, blue) if side == "red" else (blue, red)
    weights = PROFILES[profile]["weights"]
    level, meaning = conclusion(red["index"], blue["index"])

    name_map = _entity_name_map(data)
    metric_map = {m["key"]: m for m in catalog}
    causes: list[dict] = []

    # ① 公式分解：加权贡献与双方差距
    contrib = []
    for part_key, weight in weights.items():
        catalog_key = PART_METRIC_KEY.get(part_key, part_key)
        metric = metric_map.get(catalog_key, {"key": catalog_key, "name": METRIC_NAMES.get(catalog_key, catalog_key),
                                              "nodeIds": [battle["id"]], "unit": _metric_unit(catalog_key)})
        own_value = _metric_value(part_key, own, enemy, profile)
        enemy_value = _metric_value(part_key, enemy, own, profile)
        own_score = own_value * weight
        enemy_score = enemy_value * weight
        contrib.append({
            "key": part_key,
            "name": metric["name"],
            "ownValue": own_value,
            "enemyValue": enemy_value,
            "ownScore": round(own_score, 2),
            "enemyScore": round(enemy_score, 2),
            "gap": round(own_score - enemy_score, 2),
            "weight": weight,
            "unit": metric.get("unit", ""),
            "nodeIds": metric.get("nodeIds", [battle["id"]]),
        })
    contrib.sort(key=lambda item: item["gap"], reverse=True)

    # 当前指标本身：归因首先落在用户问的指标上
    focus_metric = metric_map.get(key) or metric_map.get("index")
    if focus_metric:
        own_value = _metric_value(focus_metric["key"], own, enemy, profile)
        enemy_value = _metric_value(focus_metric["key"], enemy, own, profile)
        delta = round(own_value - enemy_value, 2)
        causes.append({
            "id": "metric-focus",
            "kind": "当前指标",
            "level": "高",
            "title": f"{focus_metric['name']}：{own_value}{focus_metric.get('unit', '')}",
            "detail": (
                f"在 {PROFILES[profile]['name']}、{'红方' if side == 'red' else '蓝方'}视角下，"
                f"该指标取值为 {own_value}{focus_metric.get('unit', '')}，对方为 {enemy_value}{focus_metric.get('unit', '')}，"
                f"净差 {'+' if delta >= 0 else ''}{delta}。后续归因沿公式与本体关系展开。"
            ),
            "impact": abs(delta),
            "impactUnit": focus_metric.get("unit") or "分",
            "nodeIds": focus_metric.get("nodeIds", [battle["id"]]),
        })

    for item in contrib[:2]:
        causes.append({
            "id": f"contrib-{item['key']}",
            "kind": "公式分解",
            "level": "高",
            "title": f"主要贡献项：{item['name']}",
            "detail": (
                f"{'红方' if side == 'red' else '蓝方'}取值 {item['ownValue']}{item['unit']}，"
                f"加权贡献 {item['ownScore']} 分；对方同项贡献 {item['enemyScore']} 分，"
                f"净差 {item['gap']} 分。"
            ),
            "impact": abs(item["gap"]),
            "impactUnit": "分",
            "nodeIds": item["nodeIds"],
        })
    for item in [c for c in contrib if c["gap"] < 0][:1]:
        causes.append({
            "id": f"weak-{item['key']}",
            "kind": "公式分解",
            "level": "高",
            "title": f"主要短板：{item['name']}",
            "detail": (
                f"本项取值 {item['ownValue']}{item['unit']}，加权贡献 {item['ownScore']} 分，"
                f"低于对方 {abs(item['gap'])} 分。若追平对方，指数可提升约 {abs(item['gap'])} 分。"
            ),
            "impact": abs(item["gap"]),
            "impactUnit": "分",
            "nodeIds": item["nodeIds"],
        })

    # ② 关系传播：本体关系缺失 / 数据缺口（仅本阵营相关基地）
    relations = data["relations"]
    side_base_names = {r.get("airbase") for r in all_rows if r.get("side") == side and r.get("airbase")}
    side_base_ids = {
        e["id"] for e in _entity_by_type(data, BASE) if e.get("name") in side_base_names
    }
    side_radar_ids = {
        r.get("source_id") for r in relations
        if r.get("relation_type") == "保障" and r.get("target_id") in side_base_ids
    }
    side_aircraft_ids = {
        r.get("target_id") for r in relations
        if r.get("relation_type") == "部署" and r.get("source_id") in side_base_ids
    }
    for base in _entity_by_type(data, BASE):
        if side_base_ids and base["id"] not in side_base_ids:
            continue
        supported = any(r.get("relation_type") == "保障" and r.get("target_id") == base["id"] for r in relations)
        if not supported:
            causes.append({
                "id": f"relation-{base['id']}",
                "kind": "关系传播",
                "level": "中",
                "title": f"「{base['name']}」缺少雷达保障关系",
                "detail": "本体关系链中断，该基地的持续保障能力未被计入，对方保障能力可能被低估，比较结论需打折使用。",
                "impact": 0.0,
                "impactUnit": "分",
                "nodeIds": [base["id"]],
            })
    base_stats = _red_base_stats(rows, side)
    metric_stat_field = {"mission_success": "mission_success", "ready_rate": "ready_rate", "sorties": "sorties"}.get(key)
    if metric_stat_field and base_stats:
        weakest = min(base_stats, key=lambda item: item.get(metric_stat_field, 0))
        entity = name_map.get(weakest["name"], {})
        if metric_stat_field == "mission_success":
            impact = abs(own["base"]["mission_success"] * 100 - weakest["mission_success"])
            impact_unit = "%"
        elif metric_stat_field == "ready_rate":
            impact = abs(own["base"]["ready_rate"] * 100 - weakest["ready_rate"])
            impact_unit = "%"
        else:
            impact = abs(own["base"]["sorties"] - weakest["sorties"])
            impact_unit = "架次"
        causes.append({
            "id": "metric-drill-base",
            "kind": "实例下钻",
            "level": "高",
            "title": f"{focus_metric['name'] if focus_metric else key} 最低基地：{weakest['name']}",
            "detail": (
                f"该基地{metric_stat_field}取值为 {weakest.get(metric_stat_field)}，"
                f"是{('红方' if side == 'red' else '蓝方')}参与评估基地中最低的一项，"
                f"对整体指标形成直接拖累。"
            ),
            "impact": round(impact, 2),
            "impactUnit": impact_unit,
            "nodeIds": [entity["id"]] if entity.get("id") else [],
        })
    for stat in base_stats:
        if stat["fuel_missing"]:
            entity = name_map.get(stat["name"], {})
            causes.append({
                "id": f"gate-{stat['name']}",
                "kind": "关系传播",
                "level": "中",
                "title": f"「{stat['name']}」缺少燃油保障天数",
                "detail": "持续作战能力的关键属性缺失，导致评估置信度下降，但不直接改变指数值。",
                "impact": 0.0,
                "impactUnit": "分",
                "nodeIds": [entity["id"]] if entity.get("id") else [],
            })

    # ③ 实例下钻：基地 / 机型 / 雷达
    if base_stats:
        weakest = min(base_stats, key=lambda item: item["ready_rate"])
        entity = name_map.get(weakest["name"], {})
        causes.append({
            "id": "drill-base-ready",
            "kind": "实例下钻",
            "level": "中",
            "title": f"战备薄弱点：{weakest['name']}",
            "detail": f"战备完好率 {weakest['ready_rate']}%，为参与评估基地中最低；出动 {weakest['sorties']} 架次。",
            "impact": round(max(0.0, (own["base"]["ready_rate"] * 100) - weakest["ready_rate"]), 2),
            "impactUnit": "个百分点",
            "nodeIds": [entity["id"]] if entity.get("id") else [],
        })
        weakest_success = min(base_stats, key=lambda item: item["mission_success"])
        entity = name_map.get(weakest_success["name"], {})
        causes.append({
            "id": "drill-base-success",
            "kind": "实例下钻",
            "level": "中",
            "title": f"任务效能薄弱点：{weakest_success['name']}",
            "detail": f"加权任务完成率 {weakest_success['mission_success']}%，低于整体水平。",
            "impact": round(max(0.0, (own["base"]["mission_success"] * 100) - weakest_success["mission_success"]), 2),
            "impactUnit": "个百分点",
            "nodeIds": [entity["id"]] if entity.get("id") else [],
        })

    radars = []
    for radar in _entity_by_type(data, RADAR):
        if side_radar_ids and radar["id"] not in side_radar_ids:
            continue
        props = _parse_props(radar)
        hours = _to_float(props.get("开机时长"))
        if hours is not None:
            radars.append((hours, radar))
    if radars:
        hours, radar = min(radars, key=lambda item: item[0])
        causes.append({
            "id": "drill-radar",
            "kind": "实例下钻",
            "level": "低",
            "title": f"雷达保障薄弱点：{radar['name']}",
            "detail": f"开机时长 {hours} 小时/日，低于保障需求；直接影响持续保障指数。",
            "impact": round(max(0.0, 20.0 - hours), 2),
            "impactUnit": "小时/日",
            "nodeIds": [radar["id"]],
        })

    aircraft_list = []
    for item in _entity_by_type(data, AIRCRAFT):
        if side_aircraft_ids and item["id"] not in side_aircraft_ids:
            continue
        props = _parse_props(item)
        rate = _to_float(props.get("可用率"))
        if rate is not None:
            aircraft_list.append((rate, item, props))
    if aircraft_list:
        rate, item, props = min(aircraft_list, key=lambda x: x[0])
        causes.append({
            "id": "drill-aircraft",
            "kind": "实例下钻",
            "level": "低",
            "title": f"机型可用率薄弱点：{item['name']}",
            "detail": f"{props.get('机型', '')} 可用率 {rate}%，拉低战备完好率。",
            "impact": round(max(0.0, (own["base"]["ready_rate"] * 100) - float(rate)), 2),
            "impactUnit": "个百分点",
            "nodeIds": [item["id"]],
        })

    # ④ 反事实：雷达保障提升 / 口径切换
    target_hours = 20.0
    parts = dict(own["parts"])
    parts["radar_coverage"] = min(target_hours / 24.0, 1.0)
    counter_index = round(sum(parts[k] * weights[k] for k in weights) * 100, 1)
    delta = round(counter_index - own["index"], 1)
    radar_metric = metric_map.get("radar_coverage", {})
    causes.append({
        "id": "counterfactual-radar",
        "kind": "反事实推理",
        "level": "中" if delta > 0.5 else "低",
        "title": f"若雷达保障提升至 {target_hours:.0f} 小时/日",
        "detail": f"持续保障指数将由 {own['parts']['radar_coverage'] * 100:.1f} 升至 {parts['radar_coverage'] * 100:.1f}，"
                  f"制空权指数预计由 {own['index']} 变为 {counter_index}（{'+' if delta >= 0 else ''}{delta} 分）。",
        "impact": abs(delta),
        "impactUnit": "分",
        "nodeIds": radar_metric.get("nodeIds", [battle["id"]]),
    })

    other_profile = "v1.3" if profile == "v1.2" else "v1.2"
    alt_red = compute_side(all_rows, "red", other_profile)
    alt_blue = compute_side(all_rows, "blue", other_profile)
    alt_loss = round(red["index"] - blue["index"], 1)
    alt_gap = round(alt_red["index"] - alt_blue["index"], 1)
    causes.append({
        "id": "counterfactual-profile",
        "kind": "反事实推理",
        "level": "中",
        "title": f"若切换口径到 {other_profile}",
        "detail": f"当前口径 {profile} 下净差 {alt_loss} 分；切换后为 {alt_gap} 分，"
                  f"结论等级 {conclusion(alt_red['index'], alt_blue['index'])[0]}。口径权重会改变归因排序。",
        "impact": abs(alt_gap - alt_loss),
        "impactUnit": "分",
        "nodeIds": metric_map.get("index", {}).get("nodeIds", [battle["id"]]),
    })

    causes.sort(key=lambda item: abs(item.get("impact") or 0), reverse=True)

    side_label = "红方" if side == "red" else "蓝方"
    weakest = min(contrib, key=lambda item: item["gap"])
    summary = (
        f"在{PROFILES[profile]['name']}下，{level}（{meaning}）。"
        f"{side_label}视角下，「{contrib[0]['name']}」加权贡献 {contrib[0]['ownScore']} 分，"
        f"是贡献最大的分项；相对短板为「{weakest['name']}」（净差 {weakest['gap']} 分）。"
    )

    # 具体推理过程：带真实数值与证据，供动态本体图谱展示
    relation_causes = [c for c in causes if c.get("kind") == "关系传播"][:2]
    counter_causes = [c for c in causes if c.get("kind") == "反事实推理"][:1]
    weight_text = "、".join(f"{item['name']} {round(float(item['weight']) * 100)}%" for item in contrib)
    reasoning_steps = [
        {
            "step": 1,
            "title": "锁定评估口径",
            "detail": f"采用 {PROFILES[profile]['name']}，{side_label}视角；分项权重：{weight_text}。",
        },
        {
            "step": 2,
            "title": "计算指标与净差",
            "detail": f"红方指数 {red['index']}，蓝方指数 {blue['index']}，净差 "
                      f"{round(red['index'] - blue['index'], 1)} 分，判定为「{level}」（{meaning}）。",
        },
        {
            "step": 3,
            "title": "公式分解定位主因",
            "detail": f"「{contrib[0]['name']}」加权贡献 {contrib[0]['ownScore']} 分，是最大贡献项；"
                      f"「{weakest['name']}」净差 {weakest['gap']} 分，是相对短板。",
        },
        {
            "step": 4,
            "title": "关系传播检查",
            "detail": ("；".join(c["title"] for c in relation_causes)
                       if relation_causes
                       else "基地—雷达—机型保障关系完整，未发现关系缺口。"),
        },
        {
            "step": 5,
            "title": "反事实推理",
            "detail": (counter_causes[0]["detail"] if counter_causes
                       else f"若补齐相对短板，指数预计提升约 {abs(weakest['gap'])} 分。"),
        },
    ]

    node_ids = list(dict.fromkeys([battle["id"]] + [n for c in causes for n in (c.get("nodeIds") or [])]))
    node_ids.extend([e["id"] for e in _entity_by_type(data, BASE) if not side_base_ids or e["id"] in side_base_ids])
    node_ids.extend([e["id"] for e in _entity_by_type(data, RADAR) if not side_radar_ids or e["id"] in side_radar_ids])
    node_ids.extend([e["id"] for e in _entity_by_type(data, AIRCRAFT) if not side_aircraft_ids or e["id"] in side_aircraft_ids])
    node_ids.extend([e["id"] for e in _entity_by_type(data, SORTIE)])

    return {
        "success": True,
        "data": {
            "ontology": {"id": ontology_id, "name": _ontology_name(ontology_id)},
            "question": request.question,
            "metricKey": key,
            "profile": {"key": profile, "name": PROFILES[profile]["name"], "weights": weights},
            "side": side,
            "result": {
                "redIndex": red["index"],
                "blueIndex": blue["index"],
                "level": level,
                "meaning": meaning,
                "delta": round(red["index"] - blue["index"], 1),
                "parts": own["parts"],
            },
            "summary": summary,
            "causes": causes,
            "reasoningSteps": reasoning_steps,
            "reasoningPath": [
                f"{'①②③④⑤'[index] if index < 5 else str(index + 1)} {item['title']}：{item['detail']}"
                for index, item in enumerate(reasoning_steps)
            ],
            "nodeIds": list(dict.fromkeys(node_ids)),
            "edgePairs": _relation_edges(data, list(dict.fromkeys(node_ids))),
            "focusTypes": FOCUS_TYPES,
            "blueBattleId": (blue_battle or {}).get("id", ""),
        },
    }
