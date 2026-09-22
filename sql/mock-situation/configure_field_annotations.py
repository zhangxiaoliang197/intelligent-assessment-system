# -*- coding: utf-8 -*-
"""作战数据 mock 库：为 12 个数据集批量写入字段注解（FieldAnnotation）。

背景：admin-service 的 /export/for-llm 只导出「已配置字段注解」的数据集
（见 AdminController.exportForLlm：fields 为空则 continue）。若数据集没有
字段注解，ipage 的 LLM 看到的数据集元数据为空，无法规划取数，
导致发起提问后不产图。

本脚本职责（纯数据配置，不改系统代码）：
  1. 解析同目录 schema.sql，提取每张表的字段名/类型/注释/主键/可空信息；
  2. 自动推导 dataCategory（维度/度量/属性/时间/标识，与管理后台下拉一致）；
  3. 对地图/时序关键字段注入 businessMeaning 语义增强（航迹连线、动态火力圈、
     威胁预计算等），帮助 LLM 正确规划 geoMode=raw 取数与图表；
  4. 调用 admin-service POST /api/admin/dataset/{datasetId}/fields 批量写入。

幂等性：该接口会先删除该数据集的旧注解再写入，可重复执行。
数据集与表的匹配：按 databaseId + tableName 从 /dataset/list 动态匹配，
重新注册数据集后无需改脚本。

用法（在仓库根目录执行）：
    python sql/mock-situation/configure_field_annotations.py

环境变量（均可缺省，默认对齐本地 .env）：
    ADMIN_SERVICE_URL  默认 http://localhost:10258
    ADMIN_API_TOKEN    管理面认证令牌
"""

import os
import re
import sys
import json
import logging
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("configure_field_annotations")

# ── 配置：admin-service 地址与认证 ──
BASE_URL = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
TOKEN = os.getenv("ADMIN_API_TOKEN", "")
SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", TOKEN)  # /export/for-llm 走服务身份认证
MOCK_DATABASE_ID = "db_81653e63"  # 作战数据 mock 库（admin-service 注册的 databaseId）
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# 类型正则：列名 类型 [NOT NULL] ... COMMENT '注释'
COLUMN_RE = re.compile(
    r"^\s*(\w+)\s+(VARCHAR\(\d+\)|DECIMAL\(\d+,\d+\)|BIGINT|TINYINT|INT|DATE|DATETIME)\s*"
    r"(NOT NULL)?\s*(DEFAULT[^,]*?)?\s*COMMENT\s*'([^']*)'",
    re.IGNORECASE,
)
PK_RE = re.compile(r"PRIMARY KEY \(([^)]+)\)")

# 坐标/时序等关键字段的语义增强（tableName -> {columnName: businessMeaning}）
SEMANTIC_OVERRIDES = {
    "mock_track_point": {
        "seq": "航迹点序号，按 aircraft_id+seq 升序连线绘制航线",
        "record_time": "记录时间，时间轴切片与巡航时序分析的时间维度",
        "track_lng": "经度（WGS84），与 track_lat 配对构成航迹坐标，地图取数用 geoMode=raw",
        "track_lat": "纬度（WGS84），与 track_lng 配对构成航迹坐标，地图取数用 geoMode=raw",
        "altitude_m": "飞行高度 m，高度剖面/分布图度量",
        "speed_kmh": "飞行速度 km/h，速度趋势图度量",
        "overlap_count": "该航迹点处于敌方火力圈的数量，重叠越多越危险",
        "threat_level": "威胁等级 0-4（0无/1低/2中/3高/4极高），预计算字段，可直接聚合统计",
    },
    "mock_enemy_track_point": {
        "enemy_aircraft_id": "敌机编号，关联 mock_aircraft/mock_aircraft_type 取阵营、机型与打击半径定值",
        "seq": "航迹点序号，按 enemy_aircraft_id+seq 升序连线绘制敌机航线",
        "record_time": "记录时间，时间动画播放与日内航迹切片的时间维度",
        "track_lng": "经度（WGS84），与 track_lat 配对构成敌机航迹坐标",
        "track_lat": "纬度（WGS84），与 track_lng 配对构成敌机航迹坐标",
        "coverage_overlap_count": "与友机火力圈的重叠数（按机型定值半径预计算），热力图权重字段",
    },
    "mock_capability_range": {
        "faction": "阵营枚举（红方/蓝方），我方即红方（大陆方）；WHERE 过滤只能用红方/蓝方，禁止写'我方'",
        "lng": "圆心经度（WGS84），与 lat/radius_km 配对绘制圆形范围圈",
        "lat": "圆心纬度（WGS84），与 lng/radius_km 配对绘制圆形范围圈",
        "radius_km": "范围半径 km，范围圈大小",
        "range_type": "范围类型（侦察范围/打击范围），地图图层分组维度",
    },
    "mock_enemy_threat": {
        "threat_type": "威胁类型（远程防空阵地/中程防空阵地/预警雷达站/岸舰导弹阵地），威胁类别统计与地图符号维度",
        "lng": "阵地经度（WGS84），威胁单元地图标点",
        "lat": "阵地纬度（WGS84），威胁单元地图标点",
        "detect_radius_km": "探测半径 km，绘制探测范围圈",
        "strike_radius_km": "打击半径 km，绘制打击范围圈",
        "threat_level": "威胁等级 1-4，威胁分布统计",
        "status": "阵地状态（活跃/压制/摧毁），战果统计维度",
    },
    "mock_target": {
        "category": "目标类别（预警雷达站/指挥所/弹药库/港口设施/机场跑道/防空阵地/岸舰导弹阵地/通信中继站/燃油储备库），目标分类统计与地图符号维度",
        "lng": "目标经度（WGS84），目标地图标点",
        "lat": "目标纬度（WGS84），目标地图标点",
        "importance": "重要度 1-5 星，目标价值分析",
        "defense_level": "防御等级 1-5，目标防护强度",
        "status": "目标状态（完好/受损/摧毁），战果统计维度",
        "destroyed_time": "摧毁/受损时间，战果时序分析",
    },
    "mock_strike_event": {
        "event_time": "打击时间，打击事件时序分析",
        "event_lng": "打击点经度（WGS84），事件地图落点标注",
        "event_lat": "打击点纬度（WGS84），事件地图落点标注",
        "hit_result": "打击结果（摧毁/受损/未命中），打击效果评估维度",
        "weapon_type": "弹药类型，弹药使用构成分析",
    },
    "mock_battle_damage": {
        "event_time": "战损时间，战损时序分析",
        "event_lng": "事件地点经度（WGS84），战损地图落点标注",
        "event_lat": "事件地点纬度（WGS84），战损地图落点标注",
        "damage_type": "战损类型（击伤/击落/迫降/事故），战损构成分析",
        "severity": "损伤程度（轻损/中损/重损/坠毁），战损严重度分析",
        "faction": "阵营（红方/蓝方），敌我战损对比维度，我方即红方（大陆方）",
    },
    "mock_recon_event": {
        "event_time": "发现时间，侦察活动时序分析",
        "event_lng": "发现地点经度（WGS84），侦察发现地图落点标注",
        "event_lat": "发现地点纬度（WGS84），侦察发现地图落点标注",
        "confidence": "置信度 0-100，情报可信度分析",
        "intel_summary": "情报摘要文本",
    },
    "mock_daily_situation": {
        "stat_date": "统计日期，时间轴拖动动态变化的主时间维度",
        "campaign_phase": "当日活动类型（低烈度日/前出日/侦察日/摩擦日/对抗日/打击日，由当日主活动动态派生），阶段对比维度",
        "blue_sortie_count": "我方当日架次，架次趋势度量",
        "red_sortie_count": "敌方当日架次，敌我活动对比度量",
        "strike_event_count": "当日打击次数，打击强度趋势度量",
        "blue_loss_today": "我方当日战损，战损趋势度量",
        "red_loss_today": "敌方当日战损，敌我战损对比度量",
        "blue_loss_total": "我方累计战损，累计曲线度量",
        "red_loss_total": "敌方累计战损，累计曲线度量",
        "max_threat_level": "当日最高威胁等级 0-4，威胁等级趋势度量",
        "threat_index": "当日威胁指数 0-100，综合威胁趋势度量",
    },
    "mock_mission": {
        "faction": "阵营枚举（红方/蓝方），我方即红方（我方任务均为红方）；WHERE 过滤只能用红方/蓝方，禁止写'我方'",
        "start_time": "任务开始时间，任务时序与时长分析",
        "end_time": "任务结束时间，与 start_time 计算任务时长",
        "mission_type": "任务类型（侦察/打击/预警/巡逻），任务构成分析维度",
        "status": "任务状态（完成/中止/进行中），任务完成率统计",
    },
    "mock_aircraft": {
        "faction": "阵营（红方/蓝方），敌我机队对比维度，我方即红方（大陆方）",
        "status": "飞机状态（在役/战损/维修），机队完好率统计",
        "home_lng": "驻场经度（WGS84），基地地图标点",
        "home_lat": "驻场纬度（WGS84），基地地图标点",
    },
    "mock_aircraft_type": {
        "faction": "阵营（红方/蓝方），机型阵营对比维度，我方即红方（大陆方）",
        "category": "机型类别（侦察机/预警机/无人攻击机/无人侦察机），机队构成分析维度",
        "recon_radius_km": "侦察半径 km，能力对比度量",
        "strike_radius_km": "打击半径 km，能力对比度量",
    },
}


def parse_schema() -> dict:
    """解析 schema.sql，返回 {tableName: [字段dict, ...]}。

    字段 dict 含 columnName/columnType/columnComment/isPrimaryKey/isNullable。
    """
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()

    tables = {}
    # 逐个提取 CREATE TABLE ... ; 块
    for m in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\)\s*ENGINE", sql, re.DOTALL | re.IGNORECASE):
        table_name, body = m.group(1), m.group(2)
        pk_cols = []
        pk = PK_RE.search(body)
        if pk:
            pk_cols = [c.strip() for c in pk.group(1).split(",")]

        fields = []
        for line in body.splitlines():
            line = line.strip()
            cm = COLUMN_RE.match(line)
            if not cm:
                continue
            col, ctype, not_null, _default, comment = cm.groups()
            fields.append({
                "columnName": col.lower(),
                "columnType": ctype.upper(),
                "columnComment": comment,
                "isPrimaryKey": col.lower() in pk_cols,
                "isNullable": not (not_null or "").strip() == "NOT NULL",
            })
        tables[table_name] = fields
    return tables


def derive_category(field: dict) -> str:
    """自动推导 dataCategory（与管理后台下拉枚举一致）。"""
    col = field["columnName"]
    ctype = field["columnType"].upper()
    if field["isPrimaryKey"] or col.endswith("_id"):
        return "标识"
    if ctype in ("DATE", "DATETIME", "TIME") or col.endswith(("_time", "_date")):
        return "时间"
    if col in ("lng", "lat") or col.endswith(("_lng", "_lat")):
        return "属性"  # 坐标不聚合，归属性
    if col in ("seq",):
        return "属性"  # 排序序号，不参与聚合
    if ctype in ("INT", "BIGINT", "TINYINT", "DECIMAL"):
        return "度量"
    return "属性"


def build_payload(table_name: str, fields: list) -> list:
    """组装字段注解请求体：原始注释 + 语义增强 + 自动分类。"""
    overrides = SEMANTIC_OVERRIDES.get(table_name, {})
    payload = []
    for f in fields:
        item = dict(f)
        item["dataCategory"] = derive_category(f)
        biz = overrides.get(f["columnName"], "")
        item["businessMeaning"] = biz or f["columnComment"]
        item["annotation"] = biz or ""
        payload.append(item)
    return payload


def _http_json(method: str, path: str, body=None) -> dict:
    """调用 admin-service，返回解析后的 JSON。"""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Admin-Token", TOKEN)        # 管理面接口认证
    req.add_header("X-Service-Token", SERVICE_TOKEN)  # 服务间接口认证（/export/for-llm）
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        logger.error("调用 %s %s 失败 HTTP %s: %s", method, url, e.code, detail)
        sys.exit(1)


def main() -> None:
    if not TOKEN:
        logger.error("未配置 ADMIN_API_TOKEN 环境变量，无法认证")
        sys.exit(1)

    # 1. 取数据集列表，按 databaseId + tableName 匹配 datasetId
    ds_resp = _http_json("GET", "/api/admin/dataset/list")
    datasets = {
        d["tableName"]: d["id"]
        for d in ds_resp.get("datasets", [])
        if d.get("databaseId") == MOCK_DATABASE_ID
    }
    if not datasets:
        logger.error("databaseId=%s 下未找到任何数据集，请先在 admin-service 注册", MOCK_DATABASE_ID)
        sys.exit(1)
    logger.info("mock 库共注册 %d 个数据集", len(datasets))

    # 2. 解析 schema 并逐表写入字段注解
    tables = parse_schema()
    ok, fail = 0, 0
    for table_name, dataset_id in datasets.items():
        fields = tables.get(table_name)
        if not fields:
            logger.warning("schema.sql 中未找到表 %s，跳过", table_name)
            fail += 1
            continue
        payload = build_payload(table_name, fields)
        resp = _http_json("POST", f"/api/admin/dataset/{dataset_id}/fields", payload)
        if resp.get("success"):
            ok += 1
            logger.info("✓ %s（%s）：写入 %d 个字段注解", table_name, dataset_id, len(payload))
        else:
            fail += 1
            logger.error("✗ %s（%s）写入失败：%s", table_name, dataset_id, resp.get("message"))

    # 3. 校验：重新拉取 /export/for-llm，确认元数据非空
    export = _http_json("GET", "/api/admin/export/for-llm")
    schemas = export.get("data", {}).get("schemas", [])
    mock_schemas = [s for s in schemas if s.get("databaseId") == MOCK_DATABASE_ID]
    logger.info("校验：/export/for-llm 返回 mock 库数据集 %d 个（期望 %d）", len(mock_schemas), len(datasets))
    for s in mock_schemas:
        logger.info("  - %s（%s）字段数=%d", s.get("datasetName"), s.get("datasetId"), len(s.get("fields", [])))

    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
