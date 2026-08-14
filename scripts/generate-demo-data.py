#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成大量作战评估演示数据，追加写入 demo_business 库。

用法：
    .venv/Scripts/python.exe scripts/generate-demo-data.py

数据设计（保证跨表一致，便于态势/指标/问答等能力取数）：
- 主锚：unit（部队单位）-> force / deployment / equipment / weapon / maintenance / air_capability
- 事件锚：mission（任务）-> combat_result / combat_loss / resource_consume / command_order / recon_intelligence
- 统一维度：region（A~H 区域 × 8 方位，共 64 个）、side（红方/蓝方）、force_type（7 兵种）
- 坐标：中国境内 WGS84，同一 region 的点围绕区域中心聚集
- 追加写入，不覆盖既有演示数据（本脚本生成的 ID 一律以 GEN 前缀区分）
"""
import datetime
import random

import pymysql

random.seed(20260813)

# ── 连接 ──
conn = pymysql.connect(
    host="localhost", port=3306, user="root", password="root",
    database="demo_business", charset="utf8mb4", autocommit=False,
)
cur = conn.cursor()

# ── 参考维度 ──
LETTERS = "ABCDEFGH"
DIRECTIONS = ["东部", "西部", "北部", "南部", "中心", "沿海", "前沿", "纵深"]
REGIONS = [f"{L}区域{D}" for L in LETTERS for D in DIRECTIONS]
FORCE_TYPES = ["陆军", "海军", "空军", "火箭军", "防空", "战略支援", "联勤保障"]
SIDES = ["红方", "蓝方"]
UNIT_STATUS = ["现役", "机动", "休整", "待命"]
MISSION_TYPES = ["火力打击", "侦察监视", "兵力投送", "防空拦截", "电子对抗", "抢滩登陆"]
TARGET_TYPES = ["指挥设施", "机场", "雷达设施", "弹药库", "桥梁", "港口", "装甲集群", "炮兵阵地"]
WEAPON_TYPES = ["导弹", "火炮", "坦克", "装甲车", "雷达", "无人机", "防空导弹", "火箭炮"]
EQUIPMENT_TYPES = ["主战装备", "通信装备", "工程装备", "侦察装备", "运输装备", "保障装备"]
RESOURCE_TYPES = ["弹药", "油料", "食品", "医疗物资", "备件", "被装"]
THREAT_LEVELS = ["高", "中", "低"]
WARNING_LEVELS = ["一级", "二级", "三级"]
AIR_LEVELS = ["绝对制空", "优势制空", "均势", "劣势", "失守"]
DEFENSE_TYPES = ["要地防空", "野战防空", "海岸防御", "装甲防护"]
SPARE_STATUS = ["充足", "紧张", "短缺"]
SUPPLY_STATUS = ["已完成", "配送中", "待配送", "延误"]
TRANSPORT = ["公路", "铁路", "空运", "海运", "直升机"]
MISSION_STATUS = ["已完成", "进行中", "待执行", "已取消"]
SURNAMES = ["张", "李", "王", "赵", "刘", "陈", "杨", "黄", "周", "吴"]

# ── 区域中心坐标（中国境内近似网格）──
def _region_center(idx):
    lng = 76 + (idx % 8) * 7.5
    lat = 20 + (idx // 8) * 4.5
    return round(lng, 2), round(lat, 2)

REGION_INDEX = {region: i for i, region in enumerate(REGIONS)}

def _coord(region, spread=2.5):
    clng, clat = _region_center(REGION_INDEX[region])
    return round(clng + random.uniform(-spread, spread), 4), round(clat + random.uniform(-spread, spread), 4)

def _time():
    # 以“现在”为锚点向过去铺开：演示数据在任意时间重跑都有近 24 小时内的记录，
    # 否则时间窗类 Skill（近24小时/近7天）会在数据整体过期后过滤不到任何行。
    return datetime.datetime.now() - datetime.timedelta(
        days=random.randint(0, 220), hours=random.randint(0, 23),
        minutes=random.randint(0, 59), seconds=random.randint(0, 59))

_pick = random.choice

def _int(a, b):
    return random.randint(a, b)

def _dec(a, b, nd=2):
    return round(random.uniform(a, b), nd)

# ── 目标行数（要更多改这里）──
N_UNITS = 3000
N_DEPLOY = 12000
N_EQUIP = 30000
N_WEAPON = 20000
N_MISSION = 40000
N_COMBAT_RESULT = 80000
N_COMBAT_LOSS = 40000
N_RESOURCE = 80000
N_SUPPLY = 40000
N_INVENTORY = 20000
N_THREAT = 40000
N_WARNING = 50000
N_RECON = 40000
N_ORDER = 50000
N_MAINT = 25000
N_AIR_CAP = 25000
N_AIR_OVERALL = 12000
N_DEFENSE = 18000

BATCH = 2000


def bulk_insert(table, columns, rows):
    if not rows:
        return
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO `{table}` ({', '.join(columns)}) VALUES ({placeholders})"
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, rows[i:i + BATCH])
    conn.commit()
    print(f"  {table:<20} +{len(rows):>7}")


# ============================================================
# 1. 单位主数据（主锚）
# ============================================================
print("生成单位主数据 ...")
units = []
for i in range(N_UNITS):
    force_type = _pick(FORCE_TYPES)
    region = _pick(REGIONS)
    side = _pick(SIDES)
    lng, lat = _coord(region)
    units.append({
        "id": f"GENU-{i + 1:05d}",
        "force_type": force_type, "region": region, "side": side,
        "lng": lng, "lat": lat,
    })

unit_rows = []
for i, u in enumerate(units):
    unit_rows.append((
        u["id"],
        f"{u['side'][0]}{u['force_type']}{_int(1, 99)}旅",
        _pick(["战区指挥部", f"{u['force_type']}指挥部", "集团军", "方面军"]),
        u["force_type"], u["region"],
        _pick(SURNAMES) + _pick(["指挥员", "参谋长"]),
        _int(300, 2000), _pick(UNIT_STATUS), u["side"],
        u["lng"], u["lat"], _dec(60, 100, 1),
    ))
bulk_insert("t_unit_master",
            ["unit_id", "unit_name", "parent_unit", "force_type", "region", "commander",
             "establishment", "status", "side_name", "longitude", "latitude", "command_score"],
            unit_rows)

# ============================================================
# 2. 兵力编成（每单位一行）
# ============================================================
print("生成兵力编成 ...")
force_rows = []
for i, u in enumerate(units):
    est = _int(300, 2000)
    present = _int(int(est * 0.75), est)
    deployable = _int(int(present * 0.6), present)
    force_rows.append((
        u["id"], f"{u['side'][0]}{u['force_type']}{_int(1, 99)}旅", u["force_type"],
        est, present, deployable,
        f"GENF-{i + 1:06d}", u["side"], _dec(0.6, 1.0, 3),
        u["region"], u["lng"], u["lat"], _time(),
    ))
bulk_insert("t_force",
            ["unit_id", "unit_name", "force_type", "establishment", "present_count",
             "deployable_count", "force_no", "side_name", "readiness_rate",
             "region", "longitude", "latitude", "update_time"],
            force_rows)

# ============================================================
# 3. 兵力部署（每单位多次部署）
# ============================================================
print("生成兵力部署 ...")
deploy_rows = []
for k in range(N_DEPLOY):
    u = _pick(units)
    lng, lat = _coord(u["region"])
    deploy_rows.append((
        f"GEND-{k + 1:06d}", u["side"], u["id"], u["force_type"], u["region"],
        _int(50, 1200), _int(20, 600), _pick(["满员", "基本满员", "缺编", "临时加强"]),
        _time(), lng, lat, _dec(50, 100, 1), _dec(50, 100, 1),
    ))
bulk_insert("t_deployment",
            ["deployment_no", "side_name", "unit_id", "force_type", "region",
             "personnel_count", "equipment_count", "readiness_status", "update_time",
             "longitude", "latitude", "combat_power", "mobility_score"],
            deploy_rows)

# ============================================================
# 4. 装备完好情况
# ============================================================
print("生成装备完好情况 ...")
equip_rows = []
for k in range(N_EQUIP):
    u = _pick(units)
    total = _int(10, 300)
    faulty = _int(0, int(total * 0.25))
    online = _int(int(total * 0.5), total - faulty)
    equip_rows.append((
        u["id"], _pick(EQUIPMENT_TYPES), f"{_pick(['X','Y','Z','W'])}-{_int(10, 99)}",
        total, total - faulty, faulty, online,
        f"GENEQ-{k + 1:06d}", u["side"], _dec(0.5, 1.0, 3),
        u["region"], u["lng"], u["lat"], _time(),
    ))
bulk_insert("t_equipment",
            ["unit_id", "equipment_type", "model", "total_count", "available_count",
             "faulty_count", "online_count", "equipment_no", "side_name", "readiness_rate",
             "region", "longitude", "latitude", "update_time"],
            equip_rows)

# ============================================================
# 5. 武器装备
# ============================================================
print("生成武器装备 ...")
weapon_rows = []
for k in range(N_WEAPON):
    u = _pick(units)
    total = _int(5, 120)
    avail = _int(0, total)
    weapon_rows.append((
        f"{_pick(['红旗','长剑','东风','猎鹰','天燕','红箭'])}-{_int(1, 30)}",
        _pick(WEAPON_TYPES), f"{_pick(['A','B','C','D'])}-{_int(1, 9)}",
        total, _dec(20, 4000, 1), _pick(["在库", "部署", "维护", "战备"]),
        u["id"], f"GENW-{k + 1:06d}", u["side"], avail,
        _dec(0.6, 1.0, 3), _dec(0.6, 1.0, 3), u["region"], _time(),
    ))
bulk_insert("t_weapon",
            ["weapon_name", "weapon_type", "model", "total_count", "range_km",
             "status", "unit_id", "weapon_no", "side_name", "available_count",
             "accuracy_rate", "readiness_rate", "region", "update_time"],
            weapon_rows)

# ============================================================
# 6. 任务（事件锚）+ 相关表
# ============================================================
print("生成任务 ...")
mission_nos = [f"GENM-{k + 1:06d}" for k in range(N_MISSION)]
mission_rows = []
for k, mno in enumerate(mission_nos):
    u = _pick(units)
    start = _time()
    end = start + datetime.timedelta(hours=_int(1, 96))
    mission_rows.append((
        mno, f"对{_pick(['敌','对方'])}{_pick(TARGET_TYPES)}{_pick(MISSION_TYPES)}",
        _pick(MISSION_TYPES), f"{_pick(['敌','对方'])}{_pick(['一号','二号','三号','前沿','纵深'])}{_pick(TARGET_TYPES)}",
        u["id"], _int(1, 60), _pick(MISSION_STATUS), start, end,
        u["region"], u["side"], u["lng"], u["lat"], _dec(0, 1, 3), _dec(1, 5, 1),
    ))
bulk_insert("t_mission",
            ["mission_no", "mission_name", "mission_type", "target_name", "unit_id",
             "sorties", "status", "start_time", "end_time", "region", "side_name",
             "longitude", "latitude", "completion_rate", "risk_score"],
            mission_rows)

print("生成战果 ...")
result_rows = []
for k in range(N_COMBAT_RESULT):
    mno = _pick(mission_nos)
    u = _pick(units)
    lng, lat = _coord(u["region"])
    result_rows.append((
        mno, u["id"], _pick(WEAPON_TYPES), _pick(TARGET_TYPES), f"目标-{_int(1, 999)}",
        _int(1, 50), _int(0, 20), _pick(["达成", "部分达成", "未达成"]),
        _time(), f"GENR-{k + 1:06d}", _dec(0.3, 1.0, 3),
        u["region"], lng, lat,
    ))
bulk_insert("t_combat_result",
            ["mission_no", "unit_id", "weapon_type", "target_type", "target_name",
             "hit_count", "destroyed_count", "target_achieved", "record_time", "result_no",
             "success_rate", "region", "longitude", "latitude"],
            result_rows)

print("生成战损 ...")
loss_rows = []
for k in range(N_COMBAT_LOSS):
    mno = _pick(mission_nos)
    u = _pick(units)
    lng, lat = _coord(u["region"])
    loss_rows.append((
        mno, u["id"], _pick(EQUIPMENT_TYPES), _pick(["战损", "故障", "被毁", "失踪"]),
        _int(0, 30), _int(0, 50), _time(), f"GENL-{k + 1:06d}", u["side"],
        u["region"], lng, lat, _dec(1, 5, 1),
    ))
bulk_insert("t_combat_loss",
            ["mission_no", "unit_id", "equipment_type", "loss_type", "loss_count",
             "casualty_count", "loss_time", "loss_no", "side_name",
             "region", "longitude", "latitude", "impact_score"],
            loss_rows)

print("生成资源消耗 ...")
resource_rows = []
for k in range(N_RESOURCE):
    mno = _pick(mission_nos)
    u = _pick(units)
    rtype = _pick(RESOURCE_TYPES)
    lng, lat = _coord(u["region"])
    resource_rows.append((
        mno, rtype, f"{rtype}-{_int(1, 50)}", _dec(1, 5000, 1),
        _pick(["发", "吨", "箱", "件", "升"]), _time(), f"GENC-{k + 1:06d}",
        u["id"], _pick(["发", "吨", "箱", "件", "升"]),
        u["region"], lng, lat, _dec(1, 5, 1),
    ))
bulk_insert("t_resource_consume",
            ["mission_no", "resource_type", "resource_name", "consume_count", "unit",
             "consume_time", "consume_no", "unit_id", "measure_unit",
             "region", "longitude", "latitude", "cost_score"],
            resource_rows)

print("生成指挥指令 ...")
order_rows = []
for k in range(N_ORDER):
    mno = _pick(mission_nos)
    u = _pick(units)
    issue = _time()
    resp = issue + datetime.timedelta(minutes=_int(1, 600))
    order_rows.append((
        f"GENO-{k + 1:06d}", _pick(["战区级", "军级", "旅级", "营级"]),
        f"对{u['region']}方向执行{_pick(MISSION_TYPES)}", issue,
        _pick(["已执行", "执行中", "待执行"]), resp, mno, u["id"],
        _pick(MISSION_TYPES), f"{_pick(MISSION_TYPES)}指令", _int(1, 600),
        u["region"], _dec(0.3, 1.0, 3),
    ))
bulk_insert("t_command_order",
            ["order_no", "command_level", "content", "issue_time", "execute_status",
             "response_time", "mission_no", "unit_id", "order_type", "content_summary",
             "response_minutes", "region", "completion_rate"],
            order_rows)

print("生成侦察情报 ...")
recon_rows = []
for k in range(N_RECON):
    mno = _pick(mission_nos)
    u = _pick(units)
    lng, lat = _coord(u["region"])
    recon_rows.append((
        f"GENI-{k + 1:06d}", mno, u["id"], f"情报目标-{_int(1, 999)}",
        _pick(["卫星", "无人机", "雷达", "人工", "电子侦察"]),
        _dec(0.3, 1.0, 3), _dec(0.3, 1.0, 3), _pick(["高", "中", "低"]),
        _time(), _pick(TARGET_TYPES), u["region"], lng, lat,
    ))
bulk_insert("t_recon_intelligence",
            ["recon_no", "mission_no", "unit_id", "target_name", "intelligence_source",
             "coverage_rate", "identification_accuracy", "confidence_level", "discovered_time",
             "target_type", "region", "longitude", "latitude"],
            recon_rows)

# ============================================================
# 7. 后勤 / 保障
# ============================================================
print("生成补给保障 ...")
supply_rows = []
for k in range(N_SUPPLY):
    u = _pick(units)
    planned = _dec(10, 5000, 1)
    delivered = round(planned * random.uniform(0.4, 1.0), 1)
    planned_t = _time()
    supply_rows.append((
        f"GENS-{k + 1:06d}", _pick(RESOURCE_TYPES), f"补给-{_int(1, 99)}",
        planned, delivered, round(delivered / planned, 3),
        _pick(SUPPLY_STATUS), _pick(TRANSPORT),
        u["region"], u["lng"], u["lat"], planned_t,
        planned_t + datetime.timedelta(hours=_int(2, 96)),
        _pick(["高", "中", "低"]), _dec(50, 100, 1),
    ))
bulk_insert("t_supply",
            ["plan_no", "resource_type", "resource_name", "planned_count", "delivered_count",
             "progress", "status", "transport_ability", "region", "longitude", "latitude",
             "planned_time", "delivered_time", "risk_level", "support_score"],
            supply_rows)

print("生成物资库存 ...")
inventory_rows = []
for k in range(N_INVENTORY):
    u = _pick(units)
    stock = _dec(10, 50000, 1)
    inventory_rows.append((
        _pick(RESOURCE_TYPES), f"库存-{_int(1, 999)}", stock,
        _pick(["件", "吨", "箱", "发", "升"]), _pick(["正常", "偏低", "告急", "充足"]),
        f"{u['region']}仓库{_int(1, 20)}", _time(), f"GENV-{k + 1:06d}",
        _dec(0, stock * 0.5, 1), _dec(0, stock, 1),
        _pick(["件", "吨", "箱", "发", "升"]), u["region"], u["lng"], u["lat"],
        _dec(1, 90, 1),
    ))
bulk_insert("t_inventory",
            ["resource_type", "resource_name", "stock_count", "unit", "alert_level",
             "warehouse", "update_time", "inventory_no", "reserved_count", "inbound_count",
             "measure_unit", "region", "longitude", "latitude", "support_days"],
            inventory_rows)

# ============================================================
# 8. 威胁 / 预警 / 防御 / 空中 / 维修
# ============================================================
print("生成威胁目标 ...")
threat_rows = []
for k in range(N_THREAT):
    u = _pick(units)
    lng, lat = _coord(u["region"])
    threat_rows.append((
        f"威胁-{_int(1, 9999)}", _pick(TARGET_TYPES), _pick(THREAT_LEVELS),
        f"北纬{abs(lat):.1f} 东经{lng:.1f}", _pick(["活跃", "待确认", "已处置", "潜伏"]),
        _time(), u["region"], lng, lat, _dec(0.3, 1.0, 3), _dec(1, 5, 1),
    ))
bulk_insert("t_threat",
            ["target_name", "target_type", "threat_level", "location", "status",
             "detect_time", "region", "longitude", "latitude", "confidence_score", "risk_score"],
            threat_rows)

print("生成预警告警 ...")
warning_rows = []
for k in range(N_WARNING):
    u = _pick(units)
    warn = _time()
    resp = warn + datetime.timedelta(minutes=_int(1, 300))
    warning_rows.append((
        f"GENW-{k + 1:06d}", f"预警-{_int(1, 999)}", _pick(WARNING_LEVELS),
        _int(5, 600), _pick(["雷达", "卫星", "无人机", "地面观察哨"]),
        _pick(["已处置", "处置中", "待处置"]), warn, resp,
        _pick(TARGET_TYPES), u["region"], u["lng"], u["lat"], _dec(1, 5, 1),
    ))
bulk_insert("t_warning_event",
            ["warning_no", "target_name", "warning_level", "advance_minutes", "detection_source",
             "handling_status", "warning_time", "response_time", "target_type",
             "region", "longitude", "latitude", "risk_score"],
            warning_rows)

print("生成防御防护 ...")
defense_rows = []
for k in range(N_DEFENSE):
    u = _pick(units)
    lng, lat = _coord(u["region"])
    defense_rows.append((
        f"GENE-{k + 1:06d}", u["id"], u["region"], _pick(DEFENSE_TYPES),
        _dec(5, 500, 1), _pick(["高", "中", "低"]), _int(5, 200), _int(0, 150),
        _pick(["待命", "值班", "维护"]), u["side"], lng, lat,
        _dec(50, 100, 1), _time(),
    ))
bulk_insert("t_defense",
            ["defense_no", "unit_id", "region", "defense_type", "coverage_km",
             "protection_level", "interceptor_count", "available_count", "status",
             "side_name", "longitude", "latitude", "defense_score", "update_time"],
            defense_rows)

print("生成空中能力 ...")
aircap_rows = []
for k in range(N_AIR_CAP):
    u = _pick(units)
    aircap_rows.append((
        u["id"], _pick(["制空", "对地", "预警", "电子战", "运输", "加油"]),
        _dec(40, 100, 1), _dec(0.1, 1.0, 2), _time().date(),
        f"GENA-{k + 1:06d}", u["side"], _dec(0.5, 1.0, 3),
        _int(5, 200), _dec(0.4, 1.0, 3), u["region"],
    ))
bulk_insert("t_air_capability",
            ["unit_id", "capability_type", "score", "weight", "eval_date", "capability_no",
             "side_name", "weight_value", "sorties_available", "mission_success_rate", "region"],
            aircap_rows)

print("生成总体空中评估 ...")
airoverall_rows = []
for k in range(N_AIR_OVERALL):
    u = _pick(units)
    lng, lat = _coord(u["region"])
    airoverall_rows.append((
        f"GENOA-{k + 1:06d}", u["side"], u["id"], _dec(40, 100, 1),
        _pick(AIR_LEVELS), _time().date(), f"空中态势评估摘要-{k + 1}",
        u["region"], _int(10, 500), _dec(0, 5, 1), lng, lat,
    ))
bulk_insert("t_air_overall",
            ["eval_no", "side_name", "unit_id", "overall_score", "air_control_level",
             "eval_date", "evidence_summary", "region", "available_sorties", "threat_pressure",
             "longitude", "latitude"],
            airoverall_rows)

print("生成装备维修 ...")
maint_rows = []
for k in range(N_MAINT):
    u = _pick(units)
    fault = _int(1, 80)
    repaired = _int(0, fault)
    maint_rows.append((
        f"GENM-{k + 1:06d}", u["id"], _pick(EQUIPMENT_TYPES), f"{_pick(['X','Y','Z'])}-{_int(10, 99)}",
        fault, repaired, fault - repaired, _pick(SPARE_STATUS),
        _dec(1, 168, 1), _time(), _dec(0.5, 1.0, 3), u["region"],
    ))
bulk_insert("t_maintenance",
            ["maintenance_no", "unit_id", "equipment_type", "model", "fault_count",
             "repaired_count", "pending_count", "spare_part_status", "recovery_hours",
             "record_time", "readiness_after", "region"],
            maint_rows)

cur.close()
conn.close()
print("\n完成：已向 demo_business 追加演示数据。")
