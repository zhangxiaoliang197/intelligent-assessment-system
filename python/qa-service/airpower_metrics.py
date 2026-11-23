"""红蓝对抗制空权演示：本体指标口径与确定性计算。

指标值不是 LLM 编出来的：本模块从演示数据（CSV，可替换为真实数据集字段）
读取原始字段，按本体属性上登记的公式聚合，再按口径版本加权合成。

口径版本（PROFILES）本身也是评估结论的一部分：改变权重重算后结论会变化，
用于演示"动态本体"中口径可演进、评估可复现。
"""
from __future__ import annotations

import csv
import math
import os
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data" / "demo_airpower"
CSV_PATH = DATA_DIR / "airbase_daily.csv"

# 数据来源：auto 优先读取本地 MySQL 案例表，失败时回退 CSV；csv 强制使用 CSV。
SOURCE_MODE = os.getenv("AIRPOWER_SOURCE", "auto").strip().lower()
DB_TABLE = os.getenv("AIRPOWER_DB_TABLE", "airpower_case_daily")
DB_BASE_TABLE = os.getenv("AIRPOWER_DB_BASE_TABLE", "airpower_base")
DB_RADAR_TABLE = os.getenv("AIRPOWER_DB_RADAR_TABLE", "airpower_radar")
_CACHE_SECONDS = 15

_DB_CACHE: dict[str, Any] = {"at": 0.0, "rows": [], "info": {}}
_LAST_SOURCE: dict[str, Any] = {
    "mode": "csv",
    "dataset": "airbase_daily.csv",
    "database": "",
    "databaseId": "",
    "table": "airbase_daily.csv",
}

SIDES = {"红方": "red", "蓝方": "blue"}

# 指标口径版本：权重之和为 1
PROFILES: dict[str, dict[str, Any]] = {
    "v1.2": {
        "name": "v1.2 · 出动规模主导口径",
        "note": "强调出动规模与任务完成率，适合作战初期夺取制空权的评估。",
        "weights": {
            "sorties_share": 0.30,
            "mission_success": 0.25,
            "ready_rate": 0.15,
            "exchange_score": 0.20,
            "radar_coverage": 0.10,
        },
    },
    "v1.3": {
        "name": "v1.3 · 持续保障主导口径",
        "note": "提高雷达保障与战备完好权重，适用于拉锯阶段的持续制空能力评估。",
        "weights": {
            "sorties_share": 0.15,
            "mission_success": 0.15,
            "ready_rate": 0.25,
            "exchange_score": 0.10,
            "radar_coverage": 0.35,
        },
    },
}

# 基础指标定义：key、名称、单位、聚合公式、绑定的数据字段
BASE_METRICS: list[dict[str, str]] = [
    {
        "key": "sorties",
        "name": "出动架次",
        "unit": "架次",
        "formula": "SUM(sorties)",
        "column": "sorties",
        "agg": "sum",
        "data_type": "number",
    },
    {
        "key": "mission_success",
        "name": "任务完成率",
        "unit": "%",
        "formula": "SUM(sorties × mission_success_rate) / SUM(sorties)",
        "column": "mission_success_rate",
        "agg": "weighted",
        "data_type": "number",
    },
    {
        "key": "ready_rate",
        "name": "战备完好率",
        "unit": "%",
        "formula": "AVG(ready_rate)",
        "column": "ready_rate",
        "agg": "mean",
        "data_type": "number",
    },
    {
        "key": "losses",
        "name": "战损架次",
        "unit": "架次",
        "formula": "SUM(losses)",
        "column": "losses",
        "agg": "sum",
        "data_type": "number",
    },
    {
        "key": "radar_hours",
        "name": "雷达保障时长",
        "unit": "小时/日",
        "formula": "AVG(radar_hours)",
        "column": "radar_hours",
        "agg": "mean",
        "data_type": "number",
    },
]


class MetricsError(RuntimeError):
    """演示数据不可用或字段缺失。"""


def _admin_tools():
    """延迟导入 admin-service 工具，避免模块加载期的循环依赖。"""
    from agents.tools import execute_sql_on_database, fetch_all_databases
    return execute_sql_on_database, fetch_all_databases


def _discover_database() -> tuple[str, dict[str, Any]]:
    """定位案例数据所在的 MySQL 数据源。优先读取环境变量指定值。"""
    db_id = os.getenv("AIRPOWER_DATABASE_ID", "").strip()
    try:
        _, fetch_all_databases = _admin_tools()
        databases = fetch_all_databases()
    except Exception:
        return db_id, {}
    if db_id:
        return db_id, next((db for db in databases if db.get("id") == db_id), {})
    candidates = [
        db for db in databases
        if str(db.get("type", "")).lower() == "mysql" and db.get("status") == "已连接"
    ] or [db for db in databases if str(db.get("type", "")).lower() == "mysql"]
    if not candidates:
        return "", {}
    # 多个 MySQL 数据源时，优先选案例专用库（默认 airpower_assessment），
    # 避免按主键顺序随机命中其它演示库导致取不到案例表。
    preferred_name = os.getenv("AIRPOWER_DB_NAME", "airpower_assessment").strip()
    preferred = [
        db for db in candidates
        if str(db.get("database") or db.get("dbName") or "") == preferred_name
    ]
    chosen = (preferred or candidates)[0]
    return str(chosen.get("id", "")), chosen


def _rows_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in records:
        row: dict[str, Any] = dict(raw)
        row["side"] = SIDES.get(str(row.get("side", "")).strip(), str(row.get("side", "")).strip())
        for key in ("sorties", "losses"):
            row[key] = _to_float(row.get(key)) or 0.0
        for key in ("mission_success_rate", "ready_rate", "radar_hours", "fuel_days"):
            row[key] = _to_float(row.get(key))
        rows.append(row)
    return rows


def _load_rows_from_db() -> list[dict[str, Any]]:
    """从 MySQL 案例事实表读取日度数据；不可用时返回空列表。"""
    db_id, db_info = _discover_database()
    if not db_id:
        return []
    sql = (
        "SELECT stat_date AS date, side, airbase, aircraft_type, sorties, "
        "mission_success_rate, losses, ready_rate, radar_hours, fuel_days, runway_status "
        f"FROM {DB_TABLE} ORDER BY stat_date, side, airbase"
    )
    try:
        execute_sql_on_database, _ = _admin_tools()
        result = execute_sql_on_database(db_id, sql)
    except Exception:
        return []
    if not result.get("success"):
        return []
    rows = _rows_from_records(result.get("rows", []))
    if not rows:
        return []
    database = str(db_info.get("database") or db_info.get("dbName") or "")
    _DB_CACHE.update({
        "at": time.time(),
        "rows": rows,
        "info": {
            "mode": "mysql",
            "dataset": f"{database}.{DB_TABLE}",
            "database": database,
            "databaseId": db_id,
            "table": DB_TABLE,
        },
    })
    return rows


def _cached_rows() -> list[dict[str, Any]]:
    if _DB_CACHE["rows"] and time.time() - float(_DB_CACHE["at"]) <= _CACHE_SECONDS:
        return _DB_CACHE["rows"]
    return []


def data_source_info() -> dict[str, Any]:
    """返回当前指标计算实际使用的数据来源，供溯源展示。"""
    if _DB_CACHE["info"]:
        return dict(_DB_CACHE["info"])
    return dict(_LAST_SOURCE)


def load_base_dimension() -> list[dict[str, Any]]:
    """读取基地维度表；不可用时返回空列表。"""
    db_id, _ = _discover_database()
    if not db_id:
        return []
    sql = (
        "SELECT side, base_name, aircraft_type, runway_status, fuel_days "
        f"FROM {DB_BASE_TABLE} ORDER BY side, base_name"
    )
    try:
        execute_sql_on_database, _ = _admin_tools()
        result = execute_sql_on_database(db_id, sql)
    except Exception:
        return []
    if not result.get("success"):
        return []
    return result.get("rows", [])


def load_radar_dimension() -> list[dict[str, Any]]:
    """读取雷达保障表；不可用时返回空列表。"""
    db_id, _ = _discover_database()
    if not db_id:
        return []
    sql = (
        "SELECT radar_name, base_name, side, coverage_km, uptime_hours "
        f"FROM {DB_RADAR_TABLE} ORDER BY radar_name"
    )
    try:
        execute_sql_on_database, _ = _admin_tools()
        result = execute_sql_on_database(db_id, sql)
    except Exception:
        return []
    if not result.get("success"):
        return []
    return result.get("rows", [])


def load_rows(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None and SOURCE_MODE != "csv":
        cached = _cached_rows()
        if cached:
            return cached
        db_rows = _load_rows_from_db()
        if db_rows:
            return db_rows
    target = path or CSV_PATH
    if not target.exists():
        raise MetricsError(f"演示数据文件不存在：{target}")
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            row: dict[str, Any] = dict(raw)
            row["side"] = SIDES.get(str(row.get("side", "")).strip(), str(row.get("side", "")).strip())
            for key in ("sorties", "losses"):
                row[key] = _to_float(row.get(key)) or 0.0
            for key in ("mission_success_rate", "ready_rate", "radar_hours", "fuel_days"):
                row[key] = _to_float(row.get(key))
            rows.append(row)
    if not rows:
        raise MetricsError("演示数据为空")
    if path is None:
        _LAST_SOURCE.update({
            "mode": "csv",
            "dataset": "airbase_daily.csv",
            "database": "",
            "databaseId": "",
            "table": "airbase_daily.csv",
        })
    return rows


def _to_float(value: Any) -> float | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def aggregate(rows: list[dict[str, Any]], side: str) -> dict[str, float]:
    """按阵营聚合基础指标。缺失值不参与均值，避免空值拖低指标。"""
    subset = [r for r in rows if r.get("side") == side]
    if not subset:
        raise MetricsError(f"演示数据中不存在阵营：{side}")
    sorties = sum(r["sorties"] for r in subset)
    losses = sum(r["losses"] for r in subset)
    success_num = sum(r["sorties"] * (r["mission_success_rate"] or 0) for r in subset)
    ready_vals = [r["ready_rate"] for r in subset if r["ready_rate"] is not None]
    radar_vals = [r["radar_hours"] for r in subset if r["radar_hours"] is not None]
    return {
        "sorties": round(sorties, 1),
        "losses": round(losses, 1),
        "mission_success": round(success_num / sorties, 4) if sorties else 0.0,
        "ready_rate": round(sum(ready_vals) / len(ready_vals), 4) if ready_vals else 0.0,
        "radar_hours": round(sum(radar_vals) / len(radar_vals), 2) if radar_vals else 0.0,
    }


def compute_side(rows: list[dict[str, Any]], side: str, profile_key: str) -> dict[str, Any]:
    """计算单侧基础指标、派生指标与制空权指数（0–100）。"""
    profile = PROFILES[profile_key]
    own = aggregate(rows, side)
    enemy_side = "blue" if side == "red" else "red"
    enemy = aggregate(rows, enemy_side)

    total_sorties = own["sorties"] + enemy["sorties"]
    sorties_share = own["sorties"] / total_sorties if total_sorties else 0.0
    exchange_ratio = enemy["losses"] / max(own["losses"], 1.0)
    exchange_score = exchange_ratio / (1 + exchange_ratio)
    radar_coverage = min(own["radar_hours"] / 24.0, 1.0)

    parts = {
        "sorties_share": round(sorties_share, 4),
        "mission_success": own["mission_success"],
        "ready_rate": own["ready_rate"],
        "exchange_score": round(exchange_score, 4),
        "radar_coverage": round(radar_coverage, 4),
    }
    weights = profile["weights"]
    index = sum(parts[key] * weights[key] for key in weights) * 100
    return {
        "side": side,
        "base": own,
        "enemy_losses": enemy["losses"],
        "exchange_ratio": round(exchange_ratio, 2),
        "parts": parts,
        "index": round(index, 1),
        "profile": profile_key,
    }


def build_chain(
    red: dict[str, Any],
    blue: dict[str, Any],
    profile_key: str,
    ontology_id: str,
    base_entity_id: str,
) -> list[dict[str, Any]]:
    """构造"基础指标 → 合成指标 → 结论指标"三级指标链。

    每个节点都带：公式、数据字段绑定、所属本体类型/属性、推导路径，
    供前端与评估结论做溯源展示。
    """
    profile = PROFILES[profile_key]
    weights = profile["weights"]
    red_parts, blue_parts = red["parts"], blue["parts"]
    binding = f"csv:airbase_daily.csv#{{column}}?side={{side}}"

    def node(
        level: int,
        name: str,
        value: float,
        unit: str,
        formula: str,
        source: str,
        type_name: str,
        attr: str,
        compare: str,
    ) -> dict[str, Any]:
        return {
            "level": level,
            "name": name,
            "value": value,
            "unit": unit,
            "formula": formula,
            "source": source,
            "typeName": type_name,
            "attribute": attr,
            "compare": compare,
        }

    chain = [
        node(1, "出动架次", red["base"]["sorties"], "架次", "SUM(sorties) WHERE side='red'",
             binding.format(column="sorties", side="red"), "战场", "出动强度", f"蓝方 {blue['base']['sorties']:.0f} 架次"),
        node(1, "任务完成率", red["base"]["mission_success"] * 100, "%",
             "SUM(sorties×success)/SUM(sorties)", binding.format(column="mission_success_rate", side="red"),
             "战场", "任务完成率", f"蓝方 {blue['base']['mission_success']*100:.1f}%"),
        node(1, "战备完好率", red["base"]["ready_rate"] * 100, "%", "AVG(ready_rate)",
             binding.format(column="ready_rate", side="red"), "空军基地", "可用率",
             f"蓝方 {blue['base']['ready_rate']*100:.1f}%"),
        node(1, "战损交换比", red["exchange_ratio"], "倍", "敌损架次 / 我损架次",
             binding.format(column="losses", side="blue") + " ÷ " + binding.format(column="losses", side="red"),
             "战场", "交换比", f"蓝方 {blue['exchange_ratio']:.2f} 倍"),
        node(1, "雷达保障时长", red["base"]["radar_hours"], "小时/日", "AVG(radar_hours)",
             binding.format(column="radar_hours", side="red"), "雷达站", "开机时长",
             f"蓝方 {blue['base']['radar_hours']:.1f} 小时/日"),
        node(2, "出动强度指数", red_parts["sorties_share"] * 100, "分",
             "R.sorties / (R.sorties + B.sorties) × 100", "派生指标（无外部字段）",
             "战场", "出动强度", f"蓝方 {blue_parts['sorties_share']*100:.1f} 分"),
        node(2, "交换优势指数", red_parts["exchange_score"] * 100, "分",
             "ratio = 敌损/我损; ratio/(1+ratio)", "派生指标（无外部字段）",
             "战场", "交换比", f"蓝方 {blue_parts['exchange_score']*100:.1f} 分"),
        node(2, "持续保障指数", red_parts["radar_coverage"] * 100, "分",
             "min(AVG(radar_hours)/24, 1) × 100", "派生指标（无外部字段）",
             "雷达站", "覆盖半径", f"蓝方 {blue_parts['radar_coverage']*100:.1f} 分"),
        node(3, f"制空权指数（{profile_key}）", red["index"], "分",
             " + ".join(f"{key}×{weight:.2f}" for key, weight in weights.items()),
             f"口径版本 {profile_key}", "战场", "制空权指数",
             f"蓝方 {blue['index']:.1f} 分"),
    ]
    for item in chain:
        item["ontologyId"] = ontology_id
        item["entityId"] = base_entity_id
    return chain


def conclusion(red_index: float, blue_index: float) -> tuple[str, str]:
    """根据双方指数差给出结论等级与释义。"""
    diff = red_index - blue_index
    if diff >= 10:
        return "红方优势", f"红方领先 {diff:.1f} 分，具备较高制空权掌握度"
    if diff >= 5:
        return "红方有利", f"红方领先 {diff:.1f} 分，但优势尚不稳固"
    if diff > -5:
        return "均势", f"双方相差 {abs(diff):.1f} 分，制空权处于争夺状态"
    if diff > -10:
        return "蓝方有利", f"蓝方领先 {abs(diff):.1f} 分"
    return "蓝方优势", f"蓝方领先 {abs(diff):.1f} 分"


def data_gate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """与本体无关的数据质量检查（缺失值、值域）。"""
    findings: list[dict[str, Any]] = []
    for row in rows:
        where = f"{row['date']} {row['airbase']}"
        if row.get("fuel_days") is None:
            findings.append({
                "level": "warning",
                "rule": "必填属性缺失",
                "message": f"{where} 缺少「燃油保障天数」，持续作战能力评估置信度下降",
                "evidence": f"{row['airbase']} · fuel_days = 空",
            })
        for column, label in (
            ("mission_success_rate", "任务完成率"),
            ("ready_rate", "战备完好率"),
        ):
            value = row.get(column)
            if value is not None and not (0 <= value <= 1):
                findings.append({
                    "level": "error",
                    "rule": "属性值域越界",
                    "message": f"{where} 的「{label}」={value} 超出 0–1",
                    "evidence": f"{row['airbase']} · {column}",
                })
        radar = row.get("radar_hours")
        if radar is not None and not (0 <= radar <= 24):
            findings.append({
                "level": "error",
                "rule": "属性值域越界",
                "message": f"{where} 的「雷达保障时长」={radar} 超出 0–24 小时",
                "evidence": f"{row['airbase']} · radar_hours",
            })
    return findings


def gate_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    errors = sum(1 for f in findings if f["level"] == "error")
    warnings = sum(1 for f in findings if f["level"] == "warning")
    confidence = max(0.5, round(0.95 - 0.10 * errors - 0.03 * warnings, 2))
    if errors:
        status = "未通过"
    elif warnings:
        status = "有条件通过"
    else:
        status = "通过"
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "confidence": confidence,
        "items": findings,
    }


def round_safe(value: float, digits: int = 3) -> float:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return 0.0
    return round(value, digits)
