"""生成"红蓝对抗制空权评估本体"演示数据（幂等）。

用法（在 python/qa-service 目录）：
    python seed_airpower_demo.py

脚本通过 ontology-service 的 HTTP 接口创建本体、类型、实例、关系与属性绑定，
并把本体 ID 写入 data/demo_airpower/ontology_id.txt 供评估服务默认读取。
重复执行会先删除同名演示本体再重建，不会污染其它本体。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from airpower_metrics import (
    DATA_DIR,
    PROFILES,
    aggregate,
    compute_side,
    conclusion,
    data_gate,
    data_source_info,
    gate_summary,
    load_base_dimension,
    load_radar_dimension,
    load_rows,
)

ONTOLOGY_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://localhost:10256").rstrip("/")
DEMO_NAME = "红蓝对抗制空权评估本体"
CASE_ID = "case_airpower_2026"

# 机型 → 代次（本体实体属性）
GENERATION = {"J-20": "四代", "J-16": "三代半", "F-35A": "四代", "F-16C": "三代"}

# 运行期填入，用于把本体属性绑定到真实 MySQL 字段
SOURCE: dict[str, str] = {
    "databaseId": "",
    "database": "assessment",
    "caseTable": "airpower_case",
    "baseTable": "airpower_base",
    "radarTable": "airpower_radar",
    "dailyTable": "airpower_case_daily",
}

TYPES = [
    {
        "name": "战场",
        "description": "一次制空权评估所覆盖的作战空间，承载合成指标与结论。",
        "color": "#dc2626",
        "property_schema": [
            {
                "name": "制空权指数", "category": "metric", "data_type": "number", "unit": "分", "required": True,
                "description": "0–100，按当前口径版本合成",
                "standard_name": "制空权指数", "synonyms": ["制空权", "制空能力", "空中优势", "制空优势"],
                "formula": "sorties_share×0.30 + mission_success×0.25 + ready_rate×0.15 + exchange_score×0.20 + radar_coverage×0.10",
                "dimension": "评估结论",
            },
            {
                "name": "出动强度", "category": "metric", "data_type": "number", "unit": "架次", "required": True,
                "description": "统计期内出动架次总和",
                "standard_name": "出动架次", "synonyms": ["出动架次", "出击架次", "出动量"],
                "formula": "SUM(sorties)",
                "dimension": "出动能力",
            },
            {
                "name": "任务完成率", "category": "metric", "data_type": "number", "unit": "%", "required": True,
                "description": "按架次加权的任务成功率",
                "standard_name": "任务完成率", "synonyms": ["任务完成率", "任务成功率", "成功率", "达成率"],
                "formula": "SUM(sorties × mission_success_rate) / SUM(sorties)",
                "dimension": "任务效能",
            },
            {
                "name": "战备完好率", "category": "metric", "data_type": "number", "unit": "%", "required": True,
                "description": "可用装备占比均值",
                "standard_name": "战备完好率", "synonyms": ["战备完好率", "完好率", "可用率", "妥善率"],
                "formula": "AVG(ready_rate)",
                "dimension": "装备状态",
            },
            {
                "name": "交换比", "category": "metric", "data_type": "number", "unit": "倍", "required": True,
                "description": "敌方战损 / 我方战损",
                "standard_name": "战损交换比", "synonyms": ["交换比", "战损比", "击杀比", "战损交换比"],
                "formula": "SUM(敌方 losses) / SUM(我方 losses)",
                "dimension": "作战效果",
            },
            {
                "name": "雷达保障时长", "category": "metric", "data_type": "number", "unit": "小时/日", "required": False,
                "description": "雷达平均每日开机时长",
                "standard_name": "雷达保障时长", "synonyms": ["雷达保障时长", "雷达保障", "开机时长", "雷达时长"],
                "formula": "AVG(radar_hours)",
                "dimension": "保障能力",
            },
            {
                "name": "结论等级", "category": "descriptive", "data_type": "enum", "unit": "", "required": True,
                "description": "红方优势/红方有利/均势/蓝方有利/蓝方优势",
                "standard_name": "评估结论", "synonyms": ["结论", "胜负", "态势判断"],
                "formula": "", "dimension": "评估结论",
            },
        ],
    },
    {
        "name": "空军基地",
        "description": "出动与保障的最小单元，关联飞机、雷达与架次记录。",
        "color": "#2563eb",
        "property_schema": [
            {"name": "跑道状态", "category": "descriptive", "data_type": "enum", "required": True},
            {"name": "燃油保障天数", "category": "metric", "data_type": "number", "unit": "天", "required": True},
            {"name": "出动架次", "category": "metric", "data_type": "number", "unit": "架次", "required": False},
            {"name": "任务完成率", "category": "metric", "data_type": "number", "unit": "%", "required": False},
        ],
    },
    {
        "name": "作战飞机",
        "description": "部署在基地的作战机型及可用状态。",
        "color": "#0ea5e9",
        "property_schema": [
            {"name": "机型", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "代次", "category": "descriptive", "data_type": "enum", "required": True},
            {"name": "可用率", "category": "metric", "data_type": "number", "unit": "%", "required": True},
        ],
    },
    {
        "name": "雷达站",
        "description": "为基地提供空情保障的雷达单元。",
        "color": "#7c3aed",
        "property_schema": [
            {"name": "覆盖半径", "category": "metric", "data_type": "number", "unit": "公里", "required": True},
            {"name": "开机时长", "category": "metric", "data_type": "number", "unit": "小时/日", "required": True},
        ],
    },
    {
        "name": "出动架次",
        "description": "按机型汇总的出动记录，可追溯到具体基地。",
        "color": "#f59e0b",
        "property_schema": [
            {"name": "任务类型", "category": "descriptive", "data_type": "enum", "required": True},
            {"name": "架次数", "category": "metric", "data_type": "number", "unit": "架次", "required": True},
            {"name": "成功率", "category": "metric", "data_type": "number", "unit": "%", "required": True},
        ],
    },
    {
        "name": "评估结论",
        "description": "一次评估产出的结论实例，可回溯到战场与指标口径。",
        "color": "#16a34a",
        "property_schema": [
            {"name": "结论等级", "category": "descriptive", "data_type": "enum", "required": True},
            {"name": "置信度", "category": "metric", "data_type": "number", "unit": "", "required": True},
            {"name": "评估依据", "category": "descriptive", "data_type": "string", "required": True},
        ],
    },
    {
        "name": "评估指标",
        "description": "评估口径中的指标定义，承载标准名、同义词、公式与数据绑定，用于问答语义统一与结果溯源。",
        "color": "#e11d48",
        "property_schema": [
            {"name": "标准名", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "同义词", "category": "descriptive", "data_type": "string", "required": False,
             "description": "逗号分隔，用于把用户口语指标对齐到标准指标"},
            {"name": "计算公式", "category": "descriptive", "data_type": "string", "required": False},
            {"name": "单位", "category": "descriptive", "data_type": "string", "required": False},
            {"name": "指标层级", "category": "descriptive", "data_type": "enum", "required": False,
             "description": "1=基础指标，2=合成指标，3=结论指标"},
            {"name": "数据绑定", "category": "descriptive", "data_type": "string", "required": False},
            {"name": "当前值", "category": "metric", "data_type": "number", "required": False},
        ],
    },
    {
        "name": "评估维度",
        "description": "评估问答中需要确认的筛选维度（时间、类型、阵营、基地、机型等），用于模糊确认。",
        "color": "#0d9488",
        "property_schema": [
            {"name": "维度名称", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "取值列表", "category": "descriptive", "data_type": "string", "required": True,
             "description": "竖向“|”分隔的可选值"},
            {"name": "是否必选", "category": "descriptive", "data_type": "enum", "required": True},
            {"name": "默认值", "category": "descriptive", "data_type": "string", "required": False},
            {"name": "绑定字段", "category": "descriptive", "data_type": "string", "required": False},
            {"name": "适用指标", "category": "descriptive", "data_type": "string", "required": False},
        ],
    },
    {
        "name": "数据源",
        "description": "承载案例数据的物理数据库，记录连接方式与库名，用于溯源时定位数据来源。",
        "color": "#475569",
        "property_schema": [
            {"name": "数据源类型", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "连接地址", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "数据库名", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "连接状态", "category": "descriptive", "data_type": "enum", "required": True},
            {"name": "案例编号", "category": "descriptive", "data_type": "string", "required": False},
        ],
    },
    {
        "name": "数据表",
        "description": "数据源中的物理表，记录表名、记录数与承载的指标字段，是本体属性绑定的落点。",
        "color": "#0f766e",
        "property_schema": [
            {"name": "表名", "category": "descriptive", "data_type": "string", "required": True},
            {"name": "表说明", "category": "descriptive", "data_type": "string", "required": False},
            {"name": "记录数", "category": "metric", "data_type": "number", "unit": "行", "required": False},
            {"name": "绑定字段", "category": "descriptive", "data_type": "string", "required": False},
        ],
    },
]

# 评估指标实例定义（key 与前端/指标链一致）
METRIC_SPECS = [
    ("制空权指数", "制空权指数", "制空权,制空能力,空中优势,制空优势", "sorties_share×0.30 + mission_success×0.25 + ready_rate×0.15 + exchange_score×0.20 + radar_coverage×0.10", "分", 3, "profile:v1.2", "index"),
    ("出动强度指数", "出动强度指数", "出动强度,出动规模,出击强度", "红方出动架次 / (红方+蓝方出动架次) × 100", "分", 2, "sorties", "sorties_share"),
    ("任务完成率", "任务完成率", "任务完成率,任务成功率,成功率,达成率", "SUM(sorties×mission_success_rate)/SUM(sorties)", "%", 1, "mission_success_rate", "mission_success"),
    ("战备完好率", "战备完好率", "战备完好率,完好率,可用率,妥善率", "AVG(ready_rate)", "%", 1, "ready_rate", "ready_rate"),
    ("战损交换比", "战损交换比", "交换比,战损比,击杀比,战损交换比", "敌损架次 / 我损架次", "倍", 1, "losses", "exchange_ratio"),
    ("雷达保障时长", "雷达保障时长", "雷达保障,开机时长,雷达时长", "AVG(radar_hours)", "小时/日", 1, "radar_hours", "radar_hours"),
    ("持续保障指数", "持续保障指数", "保障能力,持续保障,雷达覆盖", "min(AVG(radar_hours)/24,1)×100", "分", 2, "radar_hours", "radar_coverage"),
    ("出动架次", "出动架次", "架次,出动量,出击架次", "SUM(sorties)", "架次", 1, "sorties", "sorties"),
]

# 评估维度实例（是否必选 / 默认值 / 绑定字段 / 适用指标）
DIMENSION_SPECS = [
    ("时间范围", "最近7天|最近14天|最近30天", "必选", "最近14天", "date", "全部指标"),
    ("评估类型", "红蓝对比|单方评估", "必选", "红蓝对比", "", "制空权指数,战损交换比"),
    ("阵营", "红方|蓝方", "可选", "红方", "side", "全部指标"),
    ("空军基地", "北岭基地|东湾基地|南岭基地|西峡基地|海门基地", "可选", "全部基地", "airbase", "出动强度指数,任务完成率,战备完好率"),
    ("机型", "J-20|J-16|F-35A|F-16C", "可选", "全部机型", "aircraft_type", "任务完成率,战备完好率"),
    ("任务类型", "制空巡逻|护航|对地支援|警戒", "可选", "全部任务类型", "任务类型", "出动强度指数,任务完成率"),
    ("口径版本", "v1.2|v1.3", "可选", "v1.2", "profile", "制空权指数"),
    ("聚合粒度", "日|周|月", "可选", "日", "date", "全部指标"),
]

RELATION_TYPES = [
    {"name": "包含", "description": "战场包含空军基地"},
    {"name": "部署", "description": "基地部署作战飞机"},
    {"name": "保障", "description": "雷达站为基地提供保障"},
    {"name": "起飞于", "description": "架次由基地起飞"},
    {"name": "依据", "description": "评估结论依据战场指标"},
    {"name": "定义指标", "description": "战场定义评估指标"},
    {"name": "约束", "description": "评估维度约束评估指标"},
    {"name": "支撑", "description": "物理数据表支撑评估指标计算"},
]

TYPE_RELATIONS = [
    ("战场", "空军基地", "包含"),
    ("空军基地", "作战飞机", "部署"),
    ("雷达站", "空军基地", "保障"),
    ("出动架次", "空军基地", "起飞于"),
    ("评估结论", "战场", "依据"),
    ("战场", "评估指标", "定义指标"),
    ("评估维度", "评估指标", "约束"),
    ("数据源", "数据表", "包含"),
    ("数据表", "评估指标", "支撑"),
]


# ── HTTP 基元 ────────────────────────────────────────────────
def _request(method: str, path: str, data: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data or {}).encode("utf-8") if data is not None else None
    req = urllib.request.Request(f"{ONTOLOGY_URL}{path}", data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail[:300]}") from exc


def list_ontologies() -> list[dict]:
    return _request("GET", "/ontology/list").get("items", [])


def delete_ontology(ontology_id: str) -> None:
    _request("DELETE", f"/ontology/{ontology_id}")


def create_ontology() -> tuple[str, dict[str, str]]:
    payload = _request(
        "POST",
        "/ontology/create",
        {
            "name": DEMO_NAME,
            "description": "用于演示动态本体如何支撑评估分析：类型/属性/关系 → 数据字段绑定 → 指标链 → 质量门禁 → 结论回写。",
            "entity_types": json.dumps(TYPES, ensure_ascii=False),
            "relation_types": json.dumps(RELATION_TYPES, ensure_ascii=False),
            "status": "活跃",
        },
    )
    data = payload.get("data") or {}
    ontology_id = data.get("id") or data.get("ontology_id")
    if not ontology_id:
        raise RuntimeError(f"创建本体未返回 ID: {payload}")
    type_ids = {t["name"]: t["id"] for t in data.get("entity_types", [])}
    return ontology_id, type_ids


def add_type_relations(ontology_id: str, type_ids: dict[str, str]) -> None:
    for source, target, rel in TYPE_RELATIONS:
        if source not in type_ids or target not in type_ids:
            continue
        _request(
            "POST",
            f"/ontology/{ontology_id}/entity_type_relation",
            {
                "source_entity_type_id": type_ids[source],
                "target_entity_type_id": type_ids[target],
                "relation_type": rel,
                "description": f"{source} {rel} {target}",
            },
        )


def add_entity(ontology_id: str, name: str, type_name: str, properties: list[dict]) -> str:
    payload = _request(
        "POST",
        f"/ontology/{ontology_id}/entity",
        {
            "name": name,
            "entity_type": type_name,
            "properties": json.dumps(properties, ensure_ascii=False),
        },
    )
    entity = (payload.get("data") or {})
    entity_id = entity.get("id")
    if not entity_id:
        raise RuntimeError(f"创建实体失败: {payload}")
    return entity_id


def add_relation(ontology_id: str, source_id: str, target_id: str, relation_type: str) -> None:
    _request(
        "POST",
        f"/ontology/{ontology_id}/relation",
        {"source_id": source_id, "target_id": target_id, "relation_type": relation_type},
    )


def prop(name: str, value, *, metric: bool = False, unit: str = "", bindings: dict | None = None,
         standard_name: str = "", synonyms: list[str] | None = None,
         formula: str = "", dimension: str = "") -> dict:
    item = {
        "name": name,
        "value": value,
        "category": "metric" if metric else "descriptive",
        "data_type": "number" if metric else "string",
        "unit": unit,
        "bindings": bindings or {},
    }
    if standard_name:
        item["standard_name"] = standard_name
    if synonyms:
        item["synonyms"] = synonyms
    if formula:
        item["formula"] = formula
    if dimension:
        item["dimension"] = dimension
    return item


def _side_label(side: str) -> str:
    return {"red": "红方", "blue": "蓝方"}.get(side, side)


def _table_for_column(column: str) -> str:
    return SOURCE["radarTable"] if column in ("radar_hours", "coverage_km", "uptime_hours") else SOURCE["dailyTable"]


def binding(column: str, side: str, agg: str) -> dict:
    table = _table_for_column(column)
    return {
        "databaseId": SOURCE["databaseId"],
        "database": SOURCE["database"],
        "dataset": f"{SOURCE['database']}.{table}",
        "table": table,
        "column": column,
        "filter": f"side='{_side_label(side)}'",
        "agg": agg,
        "expression": f"{agg.upper()}({column}) WHERE side='{_side_label(side)}'",
    }


def _agg_for(column: str) -> str:
    return {
        "mission_success_rate": "weighted",
        "ready_rate": "mean",
        "radar_hours": "mean",
        "losses": "ratio",
        "sorties": "sum",
    }.get(column, "sum")


def binding_text(column: str, agg: str, side: str = "red") -> str:
    """本体指标实例上可读的数据绑定串，直接指向真实物理表字段。"""
    if column == "profile:v1.2":
        return f"{SOURCE['database']}.{SOURCE['dailyTable']} → v1.2 权重合成"
    table = _table_for_column(column)
    return f"{SOURCE['database']}.{table}#{column} ({agg.upper()}, side='{_side_label(side)}')"


def _base_metrics(rows: list[dict], base_name: str, side: str) -> tuple[int, float]:
    subset = [r for r in rows if r.get("airbase") == base_name and r.get("side") == side]
    sorties = sum(float(r.get("sorties") or 0) for r in subset)
    weighted = sum(float(r.get("sorties") or 0) * float(r.get("mission_success_rate") or 0) for r in subset)
    return int(sorties), round(weighted / sorties * 100, 2) if sorties else 0.0


def _aircraft_ready(rows: list[dict], model: str, side: str) -> float:
    subset = [r for r in rows if r.get("aircraft_type") == model and r.get("side") == side]
    values = [float(r.get("ready_rate") or 0) for r in subset]
    return round(sum(values) / len(values) * 100, 1) if values else 0.0


def main() -> None:
    rows = load_rows()
    info = data_source_info()
    if info.get("mode") == "mysql":
        SOURCE.update({
            "databaseId": info.get("databaseId", ""),
            "database": info.get("database") or "assessment",
            "dailyTable": info.get("table") or SOURCE["dailyTable"],
        })
    bases_dim = load_base_dimension()
    radars_dim = load_radar_dimension()
    red = compute_side(rows, "red", "v1.2")
    blue = compute_side(rows, "blue", "v1.2")
    level, _ = conclusion(red["index"], blue["index"])
    gate = gate_summary(data_gate(rows))

    for existing in list_ontologies():
        if existing.get("name") == DEMO_NAME:
            print(f"删除旧演示本体 {existing.get('id')}")
            delete_ontology(existing["id"])

    ontology_id, type_ids = create_ontology()
    add_type_relations(ontology_id, type_ids)
    print(f"已创建本体 {ontology_id}，类型 {len(type_ids)} 个")

    # 战场实例（指标属性绑定演示数据字段）
    weight_expr = " + ".join(f"{k}×{v}" for k, v in PROFILES["v1.2"]["weights"].items())
    battle_red = add_entity(ontology_id, "红方战场态势", "战场", [
        prop("制空权指数", red["index"], metric=True, unit="分",
             bindings={"profile": "v1.2", "expression": weight_expr},
             standard_name="制空权指数", synonyms=["制空权", "制空能力", "空中优势", "制空优势"],
             formula="sorties_share×0.30 + mission_success×0.25 + ready_rate×0.15 + exchange_score×0.20 + radar_coverage×0.10",
             dimension="评估结论"),
        prop("出动强度", red["base"]["sorties"], metric=True, unit="架次", bindings=binding("sorties", "red", "sum"),
             standard_name="出动架次", synonyms=["出动架次", "出击架次", "出动量"],
             formula="SUM(sorties)", dimension="出动能力"),
        prop("任务完成率", round(red["base"]["mission_success"] * 100, 2), metric=True, unit="%",
             bindings=binding("mission_success_rate", "red", "weighted"),
             standard_name="任务完成率", synonyms=["任务完成率", "任务成功率", "成功率", "达成率"],
             formula="SUM(sorties×mission_success_rate)/SUM(sorties)", dimension="任务效能"),
        prop("战备完好率", round(red["base"]["ready_rate"] * 100, 2), metric=True, unit="%",
             bindings=binding("ready_rate", "red", "mean"),
             standard_name="战备完好率", synonyms=["战备完好率", "完好率", "可用率", "妥善率"],
             formula="AVG(ready_rate)", dimension="装备状态"),
        prop("交换比", red["exchange_ratio"], metric=True, unit="倍",
             bindings={"dataset": "airbase_daily.csv", "column": "losses", "filter": "side=blue/red",
                       "agg": "ratio", "expression": "SUM(blue.losses) / SUM(red.losses)"},
             standard_name="战损交换比", synonyms=["交换比", "战损比", "击杀比"],
             formula="SUM(敌方 losses)/SUM(我方 losses)", dimension="作战效果"),
        prop("雷达保障时长", red["base"]["radar_hours"], metric=True, unit="小时/日",
             bindings=binding("radar_hours", "red", "mean"),
             standard_name="雷达保障时长", synonyms=["雷达保障", "开机时长", "雷达时长"],
             formula="AVG(radar_hours)", dimension="保障能力"),
        prop("结论等级", level),
    ])
    battle_blue = add_entity(ontology_id, "蓝方战场态势", "战场", [
        prop("制空权指数", blue["index"], metric=True, unit="分",
             bindings={"profile": "v1.2", "expression": weight_expr}),
        prop("出动强度", blue["base"]["sorties"], metric=True, unit="架次", bindings=binding("sorties", "blue", "sum")),
        prop("任务完成率", round(blue["base"]["mission_success"] * 100, 2), metric=True, unit="%",
             bindings=binding("mission_success_rate", "blue", "weighted")),
        prop("战备完好率", round(blue["base"]["ready_rate"] * 100, 2), metric=True, unit="%",
             bindings=binding("ready_rate", "blue", "mean")),
        prop("交换比", blue["exchange_ratio"], metric=True, unit="倍",
             bindings={"dataset": "airbase_daily.csv", "column": "losses", "filter": "side=red/blue",
                       "agg": "ratio", "expression": "SUM(red.losses) / SUM(blue.losses)"}),
        prop("雷达保障时长", blue["base"]["radar_hours"], metric=True, unit="小时/日",
             bindings=binding("radar_hours", "blue", "mean")),
        prop("结论等级", conclusion(blue["index"], red["index"])[0]),
    ])

    # 评估指标实例：把指标标准名/同义词/公式/数据绑定显式落到本体里，
    # 供评估问答做语义统一与结果溯源（图谱中可直接高亮指标节点）。
    metric_values = {
        "index": red["index"],
        "sorties_share": round(red["parts"]["sorties_share"] * 100, 2),
        "mission_success": round(red["base"]["mission_success"] * 100, 2),
        "ready_rate": round(red["base"]["ready_rate"] * 100, 2),
        "exchange_ratio": red["exchange_ratio"],
        "radar_hours": red["base"]["radar_hours"],
        "radar_coverage": round(red["parts"]["radar_coverage"] * 100, 2),
        "sorties": red["base"]["sorties"],
    }
    metric_ids: dict[str, str] = {}
    for name, standard, synonyms, formula, unit, metric_level, bind, key in METRIC_SPECS:
        if bind == "profile:v1.2":
            bind_text = binding_text(bind, "profile", "red")
            bind_meta = {
                "databaseId": SOURCE["databaseId"],
                "database": SOURCE["database"],
                "table": SOURCE["dailyTable"],
                "profile": "v1.2",
                "expression": weight_expr,
            }
        else:
            agg = _agg_for(bind)
            bind_text = binding_text(bind, agg, "red")
            bind_meta = binding(bind, "red", agg)
        metric_ids[key] = add_entity(ontology_id, name, "评估指标", [
            prop("标准名", standard),
            prop("同义词", synonyms),
            prop("计算公式", formula),
            prop("单位", unit),
            prop("指标层级", f"{metric_level} 级"),
            prop("数据绑定", bind_text, bindings=bind_meta),
            prop("当前值", metric_values.get(key, 0), metric=True, unit=unit),
        ])
        add_relation(ontology_id, battle_red, metric_ids[key], "定义指标")

    # 数据源 / 数据表实例：把“指标←物理表←数据库”的链路画进本体
    source_entity = add_entity(ontology_id, f"本地 MySQL · {SOURCE['database']}", "数据源", [
        prop("数据源类型", "MySQL"),
        prop("连接地址", "localhost:3306"),
        prop("数据库名", SOURCE["database"]),
        prop("连接状态", "已连接"),
        prop("案例编号", CASE_ID),
    ])
    table_specs = [
        (SOURCE["dailyTable"], "日度评估事实表",
         "date,side,airbase,aircraft_type,sorties,mission_success_rate,losses,ready_rate,radar_hours",
         len(rows), ["index", "sorties_share", "mission_success", "ready_rate", "exchange_ratio", "sorties"]),
        (SOURCE["baseTable"], "基地维度表",
         "side,base_name,aircraft_type,runway_status,fuel_days", len(bases_dim), ["sorties", "ready_rate"]),
        (SOURCE["radarTable"], "雷达保障表",
         "radar_name,base_name,side,coverage_km,uptime_hours", len(radars_dim), ["radar_hours", "radar_coverage"]),
        (SOURCE["caseTable"], "评估案例表",
         "case_id,start_date,end_date,profile_version,source", 1, ["index"]),
    ]
    for table_name, label, columns, count, linked_keys in table_specs:
        table_id = add_entity(ontology_id, table_name, "数据表", [
            prop("表名", table_name),
            prop("表说明", label),
            prop("记录数", count, metric=True, unit="行"),
            prop("绑定字段", columns),
        ])
        add_relation(ontology_id, source_entity, table_id, "包含")
        for key in linked_keys:
            if key in metric_ids:
                add_relation(ontology_id, table_id, metric_ids[key], "支撑")

    # 评估维度实例：问答中缺省/多值时，用这些维度向用户做模糊确认
    dimension_ids: dict[str, str] = {}
    for dim_name, values, required, default, field, applies in DIMENSION_SPECS:
        dimension_ids[dim_name] = add_entity(ontology_id, dim_name, "评估维度", [
            prop("维度名称", dim_name),
            prop("取值列表", values),
            prop("是否必选", required),
            prop("默认值", default),
            prop("绑定字段", field),
            prop("适用指标", applies),
        ])
        add_relation(ontology_id, dimension_ids[dim_name], metric_ids.get("index", battle_red), "约束")

    # 空军基地：优先使用 MySQL 基地维度表与日度事实表
    if bases_dim:
        base_specs = []
        for item in bases_dim:
            base_name = str(item.get("base_name") or "")
            side_label = str(item.get("side") or "")
            side_key = "red" if side_label == "红方" else "blue"
            sorties, success = _base_metrics(rows, base_name, side_key)
            fuel_raw = item.get("fuel_days")
            fuel = float(fuel_raw) if fuel_raw not in (None, "") else None
            base_specs.append((base_name, side_label, str(item.get("runway_status") or "正常"),
                               fuel, sorties, success))
    else:
        base_specs = [
            ("北岭基地", "红方", "正常", 6, 73, 84.0),
            ("东湾基地", "红方", "正常", 6, 64, 80.0),
            ("南岭基地", "红方", "受损", None, 54, 79.0),   # 燃油字段缺失 → 门禁告警
            ("西峡基地", "蓝方", "正常", 7, 70, 78.0),
            ("海门基地", "蓝方", "正常", 6, 65, 75.0),
        ]
    base_ids: dict[str, str] = {}
    base_sides: dict[str, str] = {}
    for name, side, runway, fuel, sorties, success in base_specs:
        side_key = "red" if side == "红方" else "blue"
        props = [prop("跑道状态", runway), prop("出动架次", sorties, metric=True, unit="架次",
                                                 bindings=binding("sorties", side_key, "sum")),
                 prop("任务完成率", success, metric=True, unit="%",
                      bindings=binding("mission_success_rate", side_key, "weighted"))]
        if fuel is not None:
            props.insert(1, prop("燃油保障天数", fuel, metric=True, unit="天",
                                 bindings=binding("fuel_days", side_key, "mean")))
        base_ids[name] = add_entity(ontology_id, name, "空军基地", props)
        base_sides[name] = side

    # 作战飞机：机型、代次来自基地维度表，可用率按日度数据均值回算
    if bases_dim:
        aircraft_specs = []
        for item in bases_dim:
            model = str(item.get("aircraft_type") or "")
            base_name = str(item.get("base_name") or "")
            side_key = "red" if str(item.get("side")) == "红方" else "blue"
            if not model:
                continue
            short = base_name.replace("基地", "")
            aircraft_specs.append((f"{model} 中队（{short}）", model,
                                   GENERATION.get(model, "三代"), _aircraft_ready(rows, model, side_key), base_name))
    else:
        aircraft_specs = [
            ("J-20 中队", "J-20", "四代", 90.0, "北岭基地"),
            ("J-16 中队（东湾）", "J-16", "三代半", 86.0, "东湾基地"),
            ("J-16 中队（南岭）", "J-16", "三代半", 82.0, "南岭基地"),
            ("F-35A 中队", "F-35A", "四代", 81.0, "西峡基地"),
            ("F-16C 中队", "F-16C", "三代", 78.0, "海门基地"),
        ]
    for name, model, generation, ready, base_name in aircraft_specs:
        aircraft_id = add_entity(ontology_id, name, "作战飞机", [
            prop("机型", model),
            prop("代次", generation),
            prop("可用率", ready, metric=True, unit="%"),
        ])
        if base_name in base_ids:
            add_relation(ontology_id, base_ids[base_name], aircraft_id, "部署")

    # 雷达站：覆盖半径与开机时长来自 MySQL 雷达保障表
    if radars_dim:
        radar_specs = [
            (str(item.get("radar_name") or ""), int(float(item.get("coverage_km") or 0)),
             float(item.get("uptime_hours") or 0),
             str(item.get("base_name")) if item.get("base_name") else None)
            for item in radars_dim
        ]
    else:
        radar_specs = [
            ("北岭警戒雷达", 320, 17, "北岭基地"),
            ("东湾警戒雷达", 260, 15, "东湾基地"),
            ("南岭警戒雷达", 240, 14, "南岭基地"),
            ("西峡远程雷达", 420, 22, "西峡基地"),
            ("海门警戒雷达", 300, 21, None),
        ]
    radar_ids: dict[str, str] = {}
    for name, radius, hours, base_name in radar_specs:
        radar_ids[name] = add_entity(ontology_id, name, "雷达站", [
            prop("覆盖半径", radius, metric=True, unit="公里",
                 bindings=binding("coverage_km", "red", "mean")),
            prop("开机时长", hours, metric=True, unit="小时/日",
                 bindings=binding("radar_hours", "red", "mean")),
        ])
        if base_name and base_name in base_ids:
            add_relation(ontology_id, radar_ids[name], base_ids[base_name], "保障")

    # 出动架次记录：按基地汇总日度事实表，架次与成功率均来自 MySQL
    sortie_specs = [
        (f"{name}出动架次", "混合", sorties, success, name)
        for name, _side, _runway, _fuel, sorties, success in base_specs
    ]
    for name, mission_type, sorties, success, base_name in sortie_specs:
        sortie_id = add_entity(ontology_id, name, "出动架次", [
            prop("任务类型", mission_type),
            prop("架次数", sorties, metric=True, unit="架次",
                 bindings=binding("sorties", "red" if base_sides.get(base_name) == "红方" else "blue", "sum")),
            prop("成功率", success, metric=True, unit="%",
                 bindings=binding("mission_success_rate", "red" if base_sides.get(base_name) == "红方" else "blue", "weighted")),
        ])
        add_relation(ontology_id, sortie_id, base_ids[base_name], "起飞于")

    # 关系：战场包含基地
    for name, base_id in base_ids.items():
        side = base_sides.get(name, "红方")
        add_relation(ontology_id, battle_red if side == "红方" else battle_blue, base_id, "包含")

    # 既存结论实例（用于演示口径变更后的结论演进）
    conclusion_entity = add_entity(ontology_id, "制空权评估结论 v1.2", "评估结论", [
        prop("结论等级", level),
        prop("置信度", gate["confidence"], metric=True),
        prop("评估依据", f"口径 v1.2；MySQL {SOURCE['database']}.{SOURCE['dailyTable']}；"
                         f"红方指数 {red['index']}，蓝方指数 {blue['index']}；数据门禁 {gate['status']}"),
    ])
    add_relation(ontology_id, conclusion_entity, battle_red, "依据")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "ontology_id.txt").write_text(ontology_id, encoding="utf-8")
    (DATA_DIR / "seed_summary.json").write_text(json.dumps({
        "ontologyId": ontology_id,
        "dataSource": info,
        "red": red,
        "blue": blue,
        "gate": gate,
        "level": level,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"演示本体已就绪：{ontology_id}")
    print(f"数据来源：{info}")
    print(f"红方指数 {red['index']} / 蓝方指数 {blue['index']} → {level}；门禁 {gate['status']}")


if __name__ == "__main__":
    main()
