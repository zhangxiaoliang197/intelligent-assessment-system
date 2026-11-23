"""把红蓝对抗制空权案例数据写入专用 MySQL 库，并在管理端配置为数据集（幂等）。

用法（在 python/qa-service 目录）：
    MYSQL_PASSWORD=****** ADMIN_API_TOKEN=****** INTERNAL_SERVICE_TOKEN=****** \
        python init_airpower_case_mysql.py

脚本完成四件事：
1. 创建专用库（默认 airpower_assessment）与案例主表、基地维度表、雷达保障表、日度事实表；
2. 从演示 CSV 读取 2026-11-18 ~ 2026-11-22 的红蓝双方日度数据，按唯一键 UPSERT；
3. 在 admin-service 注册数据源（同名已存在则复用），并把 4 张表注册为数据集；
4. 为 4 个数据集写入字段语义注解（dataCategory / businessMeaning），供 LLM 与取数链路使用。

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

# 案例专用库与数据源名称（库名可用 AIRPOWER_DB_NAME 覆盖，避免与元数据库混用）
DB_NAME = os.getenv("AIRPOWER_DB_NAME", "airpower_assessment")
DATA_SOURCE_NAME = os.getenv("AIRPOWER_DATA_SOURCE_NAME", "红蓝对抗案例库(MySQL)")

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


def _mysql_config(with_database: bool = True) -> dict[str, Any]:
    password = os.getenv("AIRPOWER_MYSQL_PASSWORD") or os.getenv("MYSQL_PASSWORD")
    if not password:
        raise SystemExit(
            "未提供 MySQL 密码：请设置 MYSQL_PASSWORD 或 AIRPOWER_MYSQL_PASSWORD 环境变量"
        )
    config = {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": password,
        "charset": "utf8mb4",
        "autocommit": False,
    }
    if with_database:
        config["database"] = DB_NAME
    return config


def _ensure_database() -> None:
    """创建案例专用库（不存在时），避免与元数据库 assessment 混用。"""
    conn = pymysql.connect(**_mysql_config(with_database=False))
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
        conn.commit()
    finally:
        conn.close()


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


# 数据集注册规格：表名、展示名、说明、允许列
DATASET_SPECS: list[tuple[str, str, str, list[str]]] = [
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

# 字段语义注解：表名 → {列名: (dataCategory, businessMeaning)}
FIELD_SEMANTICS: dict[str, dict[str, tuple[str, str]]] = {
    DAILY_TABLE: {
        "record_id": ("标识", "自增记录号，仅供排序与去重，不参与分析"),
        "case_id": ("标识", "案例编号，固定为 case_airpower_2026，用于过滤本案例数据"),
        "stat_date": ("时间", "统计日期，时间轴切片与趋势分析的时间维度"),
        "side": ("属性", "阵营枚举：红方/蓝方；WHERE 过滤只能写红方或蓝方"),
        "airbase": ("属性", "空军基地名称，按基地分组对比出动与保障能力"),
        "aircraft_type": ("属性", "驻训机型（J-20/J-16/F-35A/F-16C），机型维度对比"),
        "sorties": ("度量", "出动架次，出动强度指标；按 side 汇总"),
        "mission_success_rate": ("度量", "任务成功率 0-1，按架次加权后乘 100 得百分比"),
        "losses": ("度量", "战损架次，交换比 = 敌方战损 / 我方战损"),
        "ready_rate": ("度量", "战备完好率 0-1，可用装备占比，取均值"),
        "radar_hours": ("度量", "雷达保障时长（小时/日），取均值衡量保障强度"),
        "fuel_days": ("度量", "燃油保障天数，持续作战能力指标；为空表示数据缺失"),
        "runway_status": ("属性", "跑道状态（正常/受限/受损），影响出动能力判断"),
        "created_at": ("时间", "入库时间，仅供审计，不参与业务分析"),
    },
    BASE_TABLE: {
        "base_id": ("标识", "基地编号，主键"),
        "case_id": ("标识", "所属案例编号"),
        "side": ("属性", "阵营枚举：红方/蓝方"),
        "base_name": ("属性", "基地名称，与日度表的 airbase 对应"),
        "aircraft_type": ("属性", "驻训机型"),
        "runway_status": ("属性", "跑道状态（正常/受限/受损）"),
        "fuel_days": ("度量", "燃油保障天数"),
        "created_at": ("时间", "入库时间，仅供审计"),
    },
    RADAR_TABLE: {
        "radar_id": ("标识", "雷达编号，主键"),
        "case_id": ("标识", "所属案例编号"),
        "radar_name": ("属性", "雷达站名称"),
        "base_name": ("属性", "保障的基地名称；为空表示未关联基地（数据质量告警项）"),
        "side": ("属性", "阵营枚举：红方/蓝方"),
        "coverage_km": ("度量", "覆盖半径 km，衡量探测范围"),
        "uptime_hours": ("度量", "每日开机时长（小时），衡量保障强度"),
        "created_at": ("时间", "入库时间，仅供审计"),
    },
    CASE_TABLE: {
        "case_id": ("标识", "案例编号，主键"),
        "case_name": ("属性", "案例名称"),
        "description": ("属性", "案例说明：数据范围与口径"),
        "region": ("属性", "作战区域"),
        "start_date": ("时间", "案例起始日期"),
        "end_date": ("时间", "案例结束日期"),
        "profile_version": ("属性", "评估口径版本，例如 v1.2"),
        "source": ("属性", "数据来源说明"),
        "created_at": ("时间", "入库时间，仅供审计"),
    },
}


def _admin_client():
    """构造 admin-service 调用函数（统一注入管理面与服务间令牌）。"""
    token = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()
    admin_token = os.getenv("ADMIN_API_TOKEN", "").strip()
    admin_url = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258").rstrip("/")
    headers = {"Content-Type": "application/json", "X-User-Role": "admin", "X-User-Id": "system"}
    if token:
        headers["X-Service-Token"] = token
    if admin_token:
        headers["X-Admin-Token"] = admin_token

    def call(path: str, method: str = "GET", body=None) -> dict:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{admin_url}/api/admin/{path}", data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return call


def ensure_data_source(call) -> str:
    """确保案例库数据源存在（同名复用，否则新建并测试连接），返回 databaseId。"""
    for db in call("database/list").get("databases", []):
        if str(db.get("database", "")) == DB_NAME and str(db.get("type", "")).lower() == "mysql":
            db_id = str(db.get("id", ""))
            if db.get("status") != "已连接":
                try:
                    call(f"database/{db_id}/test", "POST")
                except Exception as exc:  # noqa: BLE001
                    print(f"[warn] 数据源连接测试失败：{exc}")
            return db_id

    config = _mysql_config(with_database=False)
    resp = call("database", "POST", {
        "name": DATA_SOURCE_NAME,
        "type": "MySQL",
        "host": config["host"],
        "port": config["port"],
        "database": DB_NAME,
        "username": config["user"],
        "password": config["password"],
    })
    db_id = str(resp.get("id", ""))
    if not db_id:
        raise SystemExit(f"创建数据源失败：{resp}")
    call(f"database/{db_id}/test", "POST")
    return db_id


def register_datasets(call, database_id: str) -> tuple[list[str], dict[str, str]]:
    """把 4 张物理表注册为数据集，返回（新建表清单，表名→数据集ID）。"""
    current = {
        str(item.get("tableName")): str(item.get("id"))
        for item in call("dataset/list").get("datasets", [])
        if str(item.get("databaseId")) == database_id
    }
    created: list[str] = []
    for table, name, description, columns in DATASET_SPECS:
        if table in current:
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

    # 重新取一次，拿到新建数据集的 ID
    datasets = {
        str(item.get("tableName")): str(item.get("id"))
        for item in call("dataset/list").get("datasets", [])
        if str(item.get("databaseId")) == database_id
    }
    return created, datasets


def configure_field_annotations(call, datasets: dict[str, str]) -> int:
    """为已注册的数据集写入字段语义注解，返回成功的数据集数量。"""
    ok = 0
    for table, dataset_id in datasets.items():
        semantics = FIELD_SEMANTICS.get(table)
        if not semantics:
            continue
        payload = [
            {
                "columnName": column,
                "columnType": "",
                "columnComment": "",
                "isPrimaryKey": column.endswith("_id") or column == "record_id",
                "isNullable": False,
                "dataCategory": category,
                "businessMeaning": meaning,
                "annotation": meaning,
            }
            for column, (category, meaning) in semantics.items()
        ]
        try:
            resp = call(f"dataset/{dataset_id}/fields", "POST", payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 写入 {table} 字段注解失败：{exc}")
            continue
        if resp.get("success"):
            ok += 1
            print(f"  字段注解已写入：{table}（{len(payload)} 列）")
        else:
            print(f"[warn] 写入 {table} 字段注解被拒绝：{resp.get('message')}")
    return ok


def main() -> None:
    _ensure_database()
    conn = _connect()
    try:
        create_tables(conn)
        rows, bases = load_case(conn)
        counts = verify(conn)
    finally:
        conn.close()

    print(f"案例 {CASE_ID} 已写入 MySQL 库 {DB_NAME}：")
    for table, count in counts.items():
        print(f"  - {table}: {count} 行")
    print(f"  日度数据 {len(rows)} 条，基地 {len(bases)} 个，雷达 {len(RADAR_SPECS)} 个")

    call = _admin_client()
    database_id = ensure_data_source(call)
    print(f"数据源已就绪：{DATA_SOURCE_NAME}（{database_id}）")

    created, datasets = register_datasets(call, database_id)
    if created:
        print("已注册数据集：" + "、".join(created))
    else:
        print("数据集均已存在，复用现有注册")
    annotated = configure_field_annotations(call, datasets)
    print(f"字段注解完成：{annotated} 个数据集")

    (DATA_DIR / "case_mysql.json").write_text(
        json.dumps({
            "caseId": CASE_ID,
            "databaseId": database_id,
            "database": DB_NAME,
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
    print(f"提示：qa 服务启动时设置 AIRPOWER_DATABASE_ID={database_id} 可固定使用本数据源")


if __name__ == "__main__":
    sys.exit(main())
