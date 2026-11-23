"""把红蓝对抗制空权案例数据写入本地 MySQL（幂等）。

用法（在 python/qa-service 目录，需提供 MySQL 密码环境变量）：
    MYSQL_PASSWORD=****** ../../.venv/bin/python init_airpower_case_mysql.py

脚本完成三件事：
1. 在目标库中建案例主表、基地维度表、雷达保障表、日度事实表（CREATE TABLE IF NOT EXISTS）；
2. 从演示 CSV 读取 2026-11-18 ~ 2026-11-22 的红蓝双方日度数据，按唯一键 UPSERT；
3. 可选地把这些物理表注册为 admin-service 数据集，便于评估链路按数据集取数。

MySQL 连接参数全部从环境变量读取，不在代码中硬编码密码。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any

import pymysql

from airpower_metrics import CSV_PATH, DATA_DIR, _to_float, load_rows

CASE_ID = "case_airpower_2026"
CASE_NAME = "红蓝对抗制空权评估案例（2026-11-18 ~ 2026-11-22）"
CASE_DESC = "红蓝双方 5 个空军基地连续 5 天的出动、任务完成、战损、战备与雷达保障日度数据。"
CASE_REGION = "西太平洋某空域"
PROFILE_VERSION = "v1.2"

DAILY_TABLE = "airpower_case_daily"
BASE_TABLE = "airpower_base"
RADAR_TABLE = "airpower_radar"
CASE_TABLE = "airpower_case"

# 雷达保障数据（与本体演示口径一致；海门雷达故意不关联基地，用于数据质量门禁告警）
RADAR_SPECS: list[tuple[str, str | None, str, int, float]] = [
    ("北岭警戒雷达", "北岭基地", "红方", 320, 17),
    ("东湾警戒雷达", "东湾基地", "红方", 260, 15),
    ("南岭警戒雷达", "南岭基地", "红方", 240, 14),
    ("西峡远程雷达", "西峡基地", "蓝方", 420, 22),
    ("海门警戒雷达", None, "蓝方", 300, 21),
]

# 机型 → 代次（本体实体属性）
GENERATION = {"J-20": "四代", "J-16": "三代半", "F-35A": "四代", "F-16C": "三代"}

DDL = [
    f"""
    CREATE TABLE IF NOT EXISTS {CASE_TABLE} (
        case_id VARCHAR(32) PRIMARY KEY,
        case_name VARCHAR(200) NOT NULL,
        description TEXT,
        region VARCHAR(100),
        start_date DATE,
        end_date DATE,
        profile_version VARCHAR(20),
        source VARCHAR(200),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {BASE_TABLE} (
        base_id VARCHAR(64) PRIMARY KEY,
        case_id VARCHAR(32) NOT NULL,
        side VARCHAR(10) NOT NULL,
        base_name VARCHAR(100) NOT NULL,
        aircraft_type VARCHAR(50),
        runway_status VARCHAR(20),
        fuel_days DECIMAL(6,2),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_case_base (case_id, base_name),
        KEY idx_base_case (case_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {RADAR_TABLE} (
        radar_id VARCHAR(64) PRIMARY KEY,
        case_id VARCHAR(32) NOT NULL,
        radar_name VARCHAR(100) NOT NULL,
        base_name VARCHAR(100),
        side VARCHAR(10),
        coverage_km INT,
        uptime_hours DECIMAL(6,2),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_case_radar (case_id, radar_name),
        KEY idx_radar_case (case_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {DAILY_TABLE} (
        record_id BIGINT AUTO_INCREMENT PRIMARY KEY,
        case_id VARCHAR(32) NOT NULL,
        stat_date DATE NOT NULL,
        side VARCHAR(10) NOT NULL,
        airbase VARCHAR(100) NOT NULL,
        aircraft_type VARCHAR(50),
        sorties INT DEFAULT 0,
        mission_success_rate DECIMAL(6,4),
        losses INT DEFAULT 0,
        ready_rate DECIMAL(6,4),
        radar_hours DECIMAL(6,2),
        fuel_days DECIMAL(6,2),
        runway_status VARCHAR(20),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uk_daily (case_id, stat_date, side, airbase, aircraft_type),
        KEY idx_daily_case (case_id),
        KEY idx_daily_date (stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


def _mysql_config() -> dict[str, Any]:
    password = os.getenv("AIRPOWER_MYSQL_PASSWORD") or os.getenv("MYSQL_PASSWORD")
    if not password:
        raise SystemExit(
            "未提供 MySQL 密码：请设置 MYSQL_PASSWORD 或 AIRPOWER_MYSQL_PASSWORD 环境变量"
        )
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": password,
        "database": os.getenv("MYSQL_DATABASE", "assessment"),
        "charset": "utf8mb4",
        "autocommit": False,
    }


def _connect() -> pymysql.connections.Connection:
    return pymysql.connect(**_mysql_config())


def _base_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从日度数据抽取基地维度，取每个基地最新一天的跑道与燃油状态。"""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("side")), str(row.get("airbase")))
        current = latest.get(key)
        if current is None or str(row.get("date")) >= str(current.get("date")):
            latest[key] = row
    result = []
    for (side, airbase), row in sorted(latest.items(), key=lambda item: (item[0][0], item[0][1])):
        result.append({
            "base_id": f"base_{side}_{airbase}",
            "side": side,
            "base_name": airbase,
            "aircraft_type": row.get("aircraft_type"),
            "runway_status": row.get("runway_status"),
            "fuel_days": row.get("fuel_days"),
        })
    return result


def create_tables(conn: pymysql.connections.Connection) -> None:
    with conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)
    conn.commit()


def load_case(conn: pymysql.connections.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = load_rows(CSV_PATH)
    dates = sorted({str(r.get("date")) for r in rows if r.get("date")})
    if not dates:
        raise SystemExit("演示 CSV 中没有可用日期")

    bases = _base_rows(rows)
    with conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {CASE_TABLE}
                (case_id, case_name, description, region, start_date, end_date, profile_version, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    case_name=VALUES(case_name), description=VALUES(description), region=VALUES(region),
                    start_date=VALUES(start_date), end_date=VALUES(end_date),
                    profile_version=VALUES(profile_version), source=VALUES(source)""",
            (CASE_ID, CASE_NAME, CASE_DESC, CASE_REGION, dates[0], dates[-1], PROFILE_VERSION,
             "demo CSV → MySQL"),
        )

        for base in bases:
            cur.execute(
                f"""INSERT INTO {BASE_TABLE}
                    (base_id, case_id, side, base_name, aircraft_type, runway_status, fuel_days)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        side=VALUES(side), aircraft_type=VALUES(aircraft_type),
                        runway_status=VALUES(runway_status), fuel_days=VALUES(fuel_days)""",
                (base["base_id"], CASE_ID, base["side"], base["base_name"],
                 base["aircraft_type"], base["runway_status"], base["fuel_days"]),
            )

        for name, base_name, side, radius, hours in RADAR_SPECS:
            cur.execute(
                f"""INSERT INTO {RADAR_TABLE}
                    (radar_id, case_id, radar_name, base_name, side, coverage_km, uptime_hours)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        base_name=VALUES(base_name), side=VALUES(side),
                        coverage_km=VALUES(coverage_km), uptime_hours=VALUES(uptime_hours)""",
                (f"radar_{name}", CASE_ID, name, base_name, side, radius, hours),
            )

        for row in rows:
            cur.execute(
                f"""INSERT INTO {DAILY_TABLE}
                    (case_id, stat_date, side, airbase, aircraft_type, sorties,
                     mission_success_rate, losses, ready_rate, radar_hours, fuel_days, runway_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        sorties=VALUES(sorties), mission_success_rate=VALUES(mission_success_rate),
                        losses=VALUES(losses), ready_rate=VALUES(ready_rate),
                        radar_hours=VALUES(radar_hours), fuel_days=VALUES(fuel_days),
                        runway_status=VALUES(runway_status)""",
                (CASE_ID, row.get("date"), row.get("side"), row.get("airbase"),
                 row.get("aircraft_type"), int(_to_float(row.get("sorties")) or 0),
                 _to_float(row.get("mission_success_rate")), int(_to_float(row.get("losses")) or 0),
                 _to_float(row.get("ready_rate")), _to_float(row.get("radar_hours")),
                 _to_float(row.get("fuel_days")), row.get("runway_status")),
            )

    # 清理案例中已不存在的旧日度记录，保证 MySQL 与 CSV 口径一致
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {DAILY_TABLE} WHERE case_id=%s AND stat_date < %s", (CASE_ID, dates[0]))
        cur.execute(f"DELETE FROM {DAILY_TABLE} WHERE case_id=%s AND stat_date > %s", (CASE_ID, dates[-1]))
    conn.commit()
    return rows, bases


def verify(conn: pymysql.connections.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in (CASE_TABLE, BASE_TABLE, RADAR_TABLE, DAILY_TABLE):
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE " + ("1=1" if table == CASE_TABLE else "case_id=%s"),
                        () if table == CASE_TABLE else (CASE_ID,))
            counts[table] = int(cur.fetchone()[0])
    return counts


def register_datasets() -> list[str]:
    """把物理表注册为 admin-service 数据集（失败不阻塞数据库落库）。"""
    token = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
    admin_token = os.getenv("ADMIN_API_TOKEN", "").strip()
    admin_url = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258").rstrip("/")
    headers = {"Content-Type": "application/json", "X-User-Role": "admin", "X-User-Id": "system"}
    if token:
        headers["X-Service-Token"] = token
    if admin_token:
        headers["X-Admin-Token"] = admin_token

    def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{admin_url}/api/admin/{path}", data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        existing = {
            item.get("tableName")
            for item in call("dataset/list").get("datasets", [])
        }
    except Exception as exc:  # noqa: BLE001 - 注册失败只记录，不影响主流程
        print(f"[warn] 读取数据集列表失败，跳过注册：{exc}")
        return []

    database_id = os.getenv("AIRPOWER_DATABASE_ID", "").strip()
    if not database_id:
        try:
            dbs = call("database/list").get("databases", [])
            connected = [d for d in dbs if d.get("status") == "已连接" and str(d.get("type", "")).lower() == "mysql"]
            database_id = (connected or dbs)[0].get("id", "") if (connected or dbs) else ""
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 读取数据源失败，跳过注册：{exc}")
            return []
    if not database_id:
        print("[warn] 未找到可用数据源，跳过数据集注册")
        return []

    specs = [
        (DAILY_TABLE, "红蓝对抗-日度评估事实表", "按日期/阵营/基地/机型记录出动、任务完成、战损、战备与雷达保障。",
         ["case_id", "stat_date", "side", "airbase", "aircraft_type", "sorties", "mission_success_rate",
          "losses", "ready_rate", "radar_hours", "fuel_days", "runway_status"]),
        (BASE_TABLE, "红蓝对抗-基地维度表", "案例涉及的空军基地、所属阵营、驻训机型与保障状态。",
         ["base_id", "case_id", "side", "base_name", "aircraft_type", "runway_status", "fuel_days"]),
        (RADAR_TABLE, "红蓝对抗-雷达保障表", "雷达站覆盖半径、每日开机时长及保障的基地。",
         ["radar_id", "case_id", "radar_name", "base_name", "side", "coverage_km", "uptime_hours"]),
        (CASE_TABLE, "红蓝对抗-评估案例表", "案例元信息：时间范围、区域、口径版本与数据来源。",
         ["case_id", "case_name", "description", "region", "start_date", "end_date", "profile_version", "source"]),
    ]
    created = []
    for table, name, description, columns in specs:
        if table in existing:
            continue
        try:
            call("dataset", "POST", {
                "name": name,
                "description": description,
                "databaseId": database_id,
                "tableName": table,
                "allowedColumns": ",".join(columns),
            })
            created.append(table)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 注册数据集 {table} 失败：{exc}")
    return created


def main() -> None:
    conn = _connect()
    try:
        create_tables(conn)
        rows, bases = load_case(conn)
        counts = verify(conn)
    finally:
        conn.close()

    print(f"案例 {CASE_ID} 已写入 MySQL：")
    for table, count in counts.items():
        print(f"  - {table}: {count} 行")
    print(f"  日度数据 {len(rows)} 条，基地 {len(bases)} 个，雷达 {len(RADAR_SPECS)} 个")

    created = register_datasets()
    if created:
        print("已注册数据集：" + "、".join(created))
    else:
        print("数据集无需新增（或注册被跳过）")

    (DATA_DIR / "case_mysql.json").write_text(
        json.dumps({
            "caseId": CASE_ID,
            "tables": {
                "case": CASE_TABLE,
                "base": BASE_TABLE,
                "radar": RADAR_TABLE,
                "daily": DAILY_TABLE,
            },
            "counts": counts,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
