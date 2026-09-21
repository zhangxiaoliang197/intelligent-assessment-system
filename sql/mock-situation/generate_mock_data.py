#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""态势图 mock 数据生成脚本：手绘航迹驱动版（台海场景，全程虚构）。

数据来源：同目录 drawn_tracks.json（人工手绘航迹几何 + 每架次元数据）。

阵营设定（全库统一）：大陆方（我方）= 红方；敌方 = 蓝方。
跨日航迹、基地、阵位、威胁、目标等实体语义均按此约定组织。

设计要点：
1. 一架飞机 = 一条手绘航迹（机型/呼号/任务/日期/时间窗写在元数据里），
   不再用椭圆参数方程或样条曲线凭空生成几何；
2. 航迹时间戳按「段长 ÷ 机型巡航速度」逐段累加，段速度带 ±10% 确定性抖动，
   点距疏密天然反映速度变化，时间线非严格线性；同一时刻允许多架飞机同时在空；
3. 起点吸附到基地、闭合航迹落点回到基地、打击航迹落点吸附到目标坐标；
4. 「有去无回」即无人机：红方（大陆方/我方）一次性攻击无人机命中目标后未返航（状态战损、
   不计战损表），蓝方（敌方）无人机全部被击落（落 mock_battle_damage）；
5. 输出 mock_data.sql（UTF-8，LF），可直接导入 MySQL。

用法：python generate_mock_data.py
"""

import hashlib
import json
import math
from datetime import datetime, timedelta, date
from pathlib import Path

# ── 基础常量 ──
EARTH_R_KM = 6371.0                          # 地球半径 km
SQL_DIR = Path(__file__).resolve().parent
TRACKS_PATH = SQL_DIR / "drawn_tracks.json"

# ── 阵营设定：大陆方（我方）= 红方，敌方 = 蓝方 ──
OUR_FACTION = "红方"
ENEMY_FACTION = "蓝方"


def mission_id_tag(aircraft_id):
    """按机群取任务编号前缀（M-BL=大陆方机群 / M-RD=敌方机群）。

    编号前缀是沿用历史编号的稳定 ID 标签，与阵营标签解耦：
    阵营改名后实体编号保持不变，因此不能用阵营值推导前缀。
    """
    return "M-BL" if str(aircraft_id).startswith("AC-BL") else "M-RD"

# ── 基地坐标（WGS84）──
BASES = {
    "福州基地": (119.297, 26.082),
    "厦门基地": (118.104, 24.480),
    "汕头基地": (116.723, 23.362),
    "敌北部基地": (121.232, 25.062),
    "敌南部基地": (120.079, 23.140),
}

# ── 机型档案（模糊命名，不涉及真实机型，按作战常识取值）──
# (型号, 名称, 阵营, 类别, 最大速度, 巡航速度, 升限, 航程, 侦察半径, 打击半径, 载弹, 乘员)
# 半径取值按"多架次日内归一化同屏"实测定标：同屏峰值 5~6 架、两两机间距中位 187km，
# 故按机型分档收缩，使多数圈独立、临近两圈的带仅部分重叠（详见 update-radius-day-normalized.sql）
AIRCRAFT_TYPES = [
    ("BT-03", "高空长航时侦察机", OUR_FACTION,   "侦察机",   750, 650, 20000, 12000, 60,    0,     0,  0),
    ("BT-05", "空中预警指挥机",   OUR_FACTION,   "预警机",   850, 700, 11000,  5500, 90,    0,     0, 12),
    ("BT-06", "一次性攻击无人机", OUR_FACTION,   "无人攻击机", 600, 480,  9000,   900, 45,   45,   300, 0),
    ("RT-02", "突击无人机",       ENEMY_FACTION, "无人攻击机", 620, 500,  9000,   800, 30,   40,   250, 0),
    ("RT-03", "侦察无人机",       ENEMY_FACTION, "无人侦察机", 500, 400,  8000,  1200, 50,    0,     0, 0),
]

# ── 飞机档案：(编号, 呼号, 机型, 基地, 列装日期) ──
# 呼号一律用「机种类别 + 序号」，不使用海燕/鲲鹏一类代号
AIRCRAFTS = [
    ("AC-BL-R1", "侦察机01",     "BT-03", "福州基地",   date(2023, 1, 15)),
    ("AC-BL-R2", "侦察机02",     "BT-03", "汕头基地",   date(2023, 6, 20)),
    ("AC-BL-R3", "侦察机03",     "BT-03", "福州基地",   date(2024, 3, 5)),
    ("AC-BL-R4", "侦察机04",     "BT-03", "厦门基地",   date(2024, 11, 12)),
    ("AC-BL-W1", "预警机01",     "BT-05", "厦门基地",   date(2023, 2, 1)),
    ("AC-BL-W2", "预警机02",     "BT-05", "厦门基地",   date(2024, 4, 15)),
    ("AC-BL-U1", "无人攻击机01", "BT-06", "福州基地",   date(2025, 5, 20)),
    ("AC-RD-U1", "无人攻击机02", "RT-02", "敌北部基地", date(2025, 3, 8)),
    ("AC-RD-U2", "无人侦察机01", "RT-03", "敌北部基地", date(2024, 9, 2)),
    ("AC-RD-U3", "无人侦察机02", "RT-03", "敌南部基地", date(2025, 1, 16)),
]

AC_BY_ID = {a[0]: a for a in AIRCRAFTS}
TYPE_BY_ID = {t[0]: t for t in AIRCRAFT_TYPES}

# 机型巡航高度（航迹高度剖面用）
TYPE_CRUISE_ALT = {"BT-03": 17000, "BT-05": 10000, "BT-06": 9000, "RT-02": 9000, "RT-03": 8000}

# ── 打击目标：6 类各 1 个，台岛方向环岛分散布放（两两间距 ≥25km）──
# (编号, 名称, 类别, 重要度, 经度, 纬度, 防御等级)
TARGETS = [
    ("TG-01", "敌北部预警雷达站", "预警雷达站", 5, 121.620, 25.150, 4),
    ("TG-02", "敌西部作战指挥所", "指挥所",     5, 121.100, 24.900, 5),
    ("TG-03", "敌中部港口设施",   "港口设施",   4, 120.450, 24.300, 4),
    ("TG-04", "敌中部弹药库",     "弹药库",     4, 120.550, 23.900, 3),
    ("TG-05", "敌西南机场跑道",   "机场跑道",   4, 120.200, 23.550, 4),
    ("TG-06", "敌中南部防空阵地", "防空阵地",   4, 120.450, 23.300, 4),
]
TARGET_BY_ID = {t[0]: t for t in TARGETS}

# ── 敌方静态威胁单元：仅保留岸舰导弹阵地 ──
# (编号, 名称, 类型, 经度, 纬度, 探测半径, 打击半径, 威胁等级)
ENEMY_THREATS = [
    ("TH-04", "敌岸舰导弹阵地F", "岸舰导弹阵地", 119.500, 23.600,  80, 150, 2),
]

# ── 静态火力圈威胁权重（威胁预计算用）──
THREAT_LEVEL_MAP = {
    "远程防空阵地": 3, "中程防空阵地": 2, "岸舰导弹阵地": 2,
    "预警雷达站": 1, "敌机": 3,
}

# ── 按当日主活动类型动态派生 campaign_phase 标签 ──
def daily_phase_label(has_strike: bool, has_damage: bool,
                      has_recon_or_awacs: bool, enemy_active: bool) -> str:
    """根据当日活动类型动态标注当日活动类型，不依赖硬编码阶段范围。

    优先级：打击 > 敌我同时活动(摩擦) > 我方侦察/预警(侦察) > 敌机前出(前出) > 我战损(对抗)。
    08-10 既打击又有战损，仍归为「打击日」；被击落当天归入敌机前出日而非对抗日。
    """
    if has_strike:
        return "打击日"
    if enemy_active and has_recon_or_awacs:
        return "摩擦日"
    if has_recon_or_awacs:
        return "侦察日"
    if enemy_active:
        return "前出日"
    if has_damage:
        return "对抗日"
    return "低烈度日"


def strike_radius_of(ac_id):
    """按机型档案取打击半径定值（km）：半径是飞机固有属性，不随时间/阵位变化，
    随飞机位置移动形成动态覆盖。查不到时回退 110。"""
    ac = AC_BY_ID.get(ac_id)
    if ac:
        t = TYPE_BY_ID.get(ac[2])
        if t and t[9] > 0:
            return t[9]
    return 110


# ════════════════════════ 几何与时间工具 ════════════════════════

def haversine_km(lng1, lat1, lng2, lat2):
    """球面距离（km）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def bearing_deg(lng1, lat1, lng2, lat2):
    """从点1指向点2的方位角（度，正北为 0）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def speed_factor(seed_text, index):
    """确定性速度系数（0.90~1.10）：让时间线非严格线性，同时可复现。"""
    h = hashlib.md5(f"{seed_text}:{index}".encode("utf-8")).hexdigest()
    return 0.90 + (int(h[:6], 16) % 1001) / 1000.0 * 0.20


def altitude_profile(n, alt_cruise, closed):
    """高度剖面：首点地面 300m，两端各约 8% 用于爬升/下降。

    closed=True（返场航迹）：末点回到 300m；
    closed=False 且为打击航迹：末点俯冲到 150m（撞击）；
    其余单向航迹（被击落）：全程保持巡航高度。
    """
    climb_n = max(1, int(round(n * 0.08)))
    desc_n = climb_n
    if closed:
        low = 300
    else:
        low = None
    alts = []
    for i in range(n):
        if i <= climb_n:
            a = 300 + (alt_cruise - 300) * i / climb_n
        elif closed and i >= n - 1 - desc_n:
            a = low + (alt_cruise - low) * (n - 1 - i) / desc_n
        else:
            a = alt_cruise
        alts.append(int(a))
    return alts


def build_track_points(script, target=None):
    """把一条手绘航迹转成带时间戳的航迹点序列。

    时间戳按「段长 ÷ 机型巡航速度 × 确定性速度系数」逐段累加，
    因此点距越密代表速度越慢，时间线非严格线性。
    返回: [{seq, time, lng, lat, alt, speed, heading, vs}, ...]
    """
    ac = AC_BY_ID[script["aircraft_id"]]
    type_id = ac[2]
    cruise = TYPE_BY_ID[type_id][5]
    alt_cruise = TYPE_CRUISE_ALT[type_id]
    base = BASES[script["base"]]
    closed = bool(script.get("snap_end_to_base"))

    pts = [(float(p["lng"]), float(p["lat"])) for p in script["points"]]
    if script.get("snap_start_to_base"):
        pts[0] = base
    if script.get("snap_end_to_base"):
        pts[-1] = base
    if target is not None and not closed:
        pts[-1] = (target[4], target[5])          # 打击航迹落点吸附到目标坐标

    # 被击落的单向航迹保持巡航高度；俯冲撞击的打击航迹末端降到 150m
    alts = altitude_profile(len(pts), alt_cruise, closed)
    if not closed and target is not None:
        n = len(pts)
        desc_n = max(1, int(round(n * 0.08)))
        for i in range(n - 1 - desc_n, n):
            alts[i] = int(150 + (alt_cruise - 150) * (n - 1 - i) / desc_n)

    hh, mm = str(script["start_time"]).split(":")
    day = date.fromisoformat(script["mission_date"])
    cur = datetime(day.year, day.month, day.day, int(hh), int(mm))

    points = [{
        "seq": 0, "time": cur, "lng": round(pts[0][0], 6), "lat": round(pts[0][1], 6),
        "alt": alts[0], "speed": int(cruise * speed_factor(script["track_id"], 0)),
        "heading": int(bearing_deg(pts[0][0], pts[0][1], pts[1][0], pts[1][1])),
        "vs": 0.0,
    }]
    for i in range(len(pts) - 1):
        lng1, lat1 = pts[i]
        lng2, lat2 = pts[i + 1]
        dist = haversine_km(lng1, lat1, lng2, lat2)
        if dist < 0.05:                            # 重合点直接跳过，避免零时长
            continue
        seg_speed = cruise * speed_factor(script["track_id"], i + 1)
        seg_minutes = dist / seg_speed * 60.0
        cur = cur + timedelta(minutes=seg_minutes)
        prev_alt = points[-1]["alt"]
        alt = alts[i + 1]
        points.append({
            "seq": len(points), "time": cur,
            "lng": round(lng2, 6), "lat": round(lat2, 6),
            "alt": alt, "speed": int(seg_speed),
            "heading": int(bearing_deg(lng1, lat1, lng2, lat2)),
            "vs": round((alt - prev_alt) / max(seg_minutes * 60, 1), 1),
        })
    points[-1]["heading"] = points[-2]["heading"] if len(points) > 1 else points[-1]["heading"]
    return points


# ════════════════════════ SQL 写出工具 ════════════════════════

def esc(v):
    """SQL 字符串转义。"""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def sql_value(v):
    """按类型输出 SQL 字面量。"""
    if v is None:
        return "NULL"
    if isinstance(v, datetime):
        return f"'{v.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, float):
        return f"{v:.6f}"
    return esc(v)


class TableWriter:
    """单表 INSERT 缓冲写出器（每 500 行合并为一条批量 INSERT）。"""

    def __init__(self, lines, table, columns):
        self.lines = lines
        self.table = table
        self.columns = columns
        self.rows = []
        self.count = 0

    def add(self, *values):
        self.rows.append("(" + ", ".join(sql_value(v) for v in values) + ")")
        self.count += 1
        if len(self.rows) >= 500:
            self.flush()

    def flush(self):
        if not self.rows:
            return
        cols = ", ".join(self.columns)
        self.lines.append(f"INSERT INTO {self.table} ({cols}) VALUES\n" + ",\n".join(self.rows) + ";")
        self.rows = []


# ════════════════════════ 任务编排 ════════════════════════

missions = []          # 全部任务（我方+敌方）
our_tracks = []        # 我方（红方）航迹点行
enemy_tracks = []      # 敌方（蓝方）航迹点行
strike_events = []     # 打击事件
damages = []           # 战损
recon_events = []      # 侦察发现
target_final = {}      # 目标编号 → (状态, 时间)
aircraft_status = {}   # 飞机编号 → 状态
_m_seq = {"M-BL": 0, "M-RD": 0}
_e_seq = {"RE": 0, "SE": 0, "DM": 0}


def next_mission_id(prefix):
    _m_seq[prefix] += 1
    return f"{prefix}-{_m_seq[prefix]:04d}"


def next_event_id(prefix):
    _e_seq[prefix] += 1
    return f"{prefix}-{_e_seq[prefix]:04d}"


def load_scripts():
    """读取手绘航迹元数据（按任务日期升序，保证任务编号与时间线一致）。"""
    doc = json.loads(TRACKS_PATH.read_text(encoding="utf-8"))
    tracks = doc["tracks"]
    for t in tracks:
        if len(t.get("points") or []) < 2:
            raise ValueError(f"航迹 {t.get('track_id')} 点数不足 2，无法生成航线")
    return sorted(tracks, key=lambda t: (t["mission_date"], t["start_time"]))


def build_all_missions():
    """按手绘航迹逐条生成任务、航迹点，并派生侦察/打击/战损事件。"""
    for s in load_scripts():
        ac = AC_BY_ID[s["aircraft_id"]]
        type_id, callsign = ac[2], ac[1]
        faction = s["faction"]
        m_type = s["mission_type"]
        target = TARGET_BY_ID.get(s.get("target_id") or "")
        mid = next_mission_id(mission_id_tag(s["aircraft_id"]))
        pts = build_track_points(s, target)
        start_dt, end_dt = pts[0]["time"], pts[-1]["time"]

        missions.append((mid, f"{start_dt.strftime('%m%d')}·{callsign}{m_type}任务", m_type,
                         ac[0], callsign, faction, s.get("target_id"), start_dt, end_dt,
                         "完成", s["result_summary"]))

        for p in pts:
            if faction == OUR_FACTION:
                our_tracks.append((ac[0], callsign, OUR_FACTION, mid, p["seq"], p["time"],
                                   p["lng"], p["lat"], p["alt"], p["speed"],
                                   p["heading"], p["vs"]))
            else:
                enemy_tracks.append((ac[0], callsign, mid, p["seq"], p["time"],
                                     p["lng"], p["lat"], p["alt"], p["speed"], p["heading"]))

        # 「有去无回」= 未返航 = 无人机：撤离终点即被我方击落点（敌方）或战损吞机（我方）
        if not s.get("snap_end_to_base"):
            aircraft_status[ac[0]] = "战损"
            if faction == ENEMY_FACTION:
                last = pts[-1]
                damages.append((next_event_id("DM"), ac[0], callsign, faction, mid,
                                last["time"], last["lng"], last["lat"],
                                "击落", "坠毁", "敌防空火力", 1))

        # 侦察任务：取航迹上最接近目标的轨迹点作为发现点
        if m_type == "侦察" and target is not None and s.get("confidence"):
            near = min(pts, key=lambda p: haversine_km(p["lng"], p["lat"], target[4], target[5]))
            recon_events.append((next_event_id("RE"), ac[0], callsign, target[0], target[1], mid,
                                 near["time"], near["lng"], near["lat"],
                                 s["confidence"], s["summary"]))

        # 打击任务：落点即打击点（已吸附到目标坐标），实现"轨迹终点刚好摧毁目标"的闭环
        if m_type == "打击" and target is not None:
            last = pts[-1]
            weapon = ("反辐射导弹" if target[2] in ("预警雷达站", "通信中继站")
                      else "精确制导炸弹")
            strike_events.append((next_event_id("SE"), mid, ac[0], callsign, target[0], target[1],
                                  last["time"], last["lng"], last["lat"], weapon, "摧毁",
                                  "目标结构完全毁伤，丧失功能"))
            target_final[target[0]] = ("摧毁", last["time"])


# ════════════════════════ 威胁预计算 ════════════════════════

def compute_our_threats():
    """对我方（红方）每个航迹点计算 overlap_count 与 threat_level。

    火力圈来源：敌机（蓝方）按机型定值的打击圈（随位置移动，±10 分钟容差）
    + 敌静态阵地打击圈。
    threat_level = max(圈等级)，重叠 ≥2 时 +1（上限 4）。
    """
    buckets = {}
    for r in enemy_tracks:
        b = int(r[4].timestamp() // 600)
        buckets.setdefault(b, []).append(r)
    static_circles = [(t[1], THREAT_LEVEL_MAP.get(t[2], 2), t[3], t[4], t[6])
                      for t in ENEMY_THREATS if t[6] > 0]

    out = []
    for r in our_tracks:
        t, lng, lat = r[5], r[6], r[7]
        overlap = 0
        max_lvl = 0
        b = int(t.timestamp() // 600)
        for bb in (b - 1, b, b + 1):
            for er in buckets.get(bb, []):
                if abs((er[4] - t).total_seconds()) <= 600 and \
                        haversine_km(lng, lat, er[5], er[6]) <= strike_radius_of(er[0]):
                    overlap += 1
                    max_lvl = max(max_lvl, THREAT_LEVEL_MAP["敌机"])
        for _, lvl, tlng, tlat, radius in static_circles:
            if haversine_km(lng, lat, tlng, tlat) <= radius:
                overlap += 1
                max_lvl = max(max_lvl, lvl)
        lvl = 0 if overlap == 0 else min(4, max_lvl + (1 if overlap >= 2 else 0))
        out.append(r + (overlap, lvl))
    return out


def compute_enemy_overlap():
    """计算敌方每个航迹点与友机火力圈的重叠数（热力图权重）。

    行结构：...(9)=heading，重叠数追加在末尾(10)。
    """
    n = len(enemy_tracks)
    out = [list(r) + [0] for r in enemy_tracks]
    for i in range(n):
        ri = out[i]
        for j in range(n):
            if i == j or ri[0] == out[j][0]:
                continue
            rj = out[j]
            if abs((ri[4] - rj[4]).total_seconds()) <= 120 and \
                    haversine_km(ri[5], ri[6], rj[5], rj[6]) <= strike_radius_of(rj[0]):
                ri[10] += 1
    return [tuple(r) for r in out]


# ════════════════════════ 每日态势汇总 ════════════════════════

def build_daily(tracks):
    """按日聚合态势汇总（时间轴切片核心表）。tracks 为含威胁字段的我方航迹行。

    列名 blue_*/red_* 按阵营命名（蓝方=敌方、红方=我方），因此写入时
    蓝方列取敌方数据、红方列取我方数据。
    """
    our_sortie, enemy_sortie = {}, {}
    awacs_days, recon_days = set(), set()
    for m in missions:
        key = m[7].date()
        if m[5] == OUR_FACTION:
            our_sortie[key] = our_sortie.get(key, 0) + 1
            if m[2] == "侦察":
                recon_days.add(key)
            elif m[2] == "预警":
                awacs_days.add(key)
        else:
            enemy_sortie[key] = enemy_sortie.get(key, 0) + 1
    recon_cnt, strike_cnt = {}, {}
    for e in recon_events:
        recon_cnt[e[6].date()] = recon_cnt.get(e[6].date(), 0) + 1
    for e in strike_events:
        strike_cnt[e[6].date()] = strike_cnt.get(e[6].date(), 0) + 1
    our_loss_d, enemy_loss_d = {}, {}
    for dm in damages:
        key = dm[5].date()
        if dm[3] == OUR_FACTION:
            our_loss_d[key] = our_loss_d.get(key, 0) + 1
        else:
            enemy_loss_d[key] = enemy_loss_d.get(key, 0) + 1
    max_threat_d = {}
    for r in tracks:
        key = r[5].date()
        max_threat_d[key] = max(max_threat_d.get(key, 0), r[13])

    start = min(m[7].date() for m in missions)
    end = max(m[7].date() for m in missions)
    rows = []
    ot = et = 0
    d = start
    while d <= end:
        ol = our_loss_d.get(d, 0)
        el = enemy_loss_d.get(d, 0)
        ot += ol
        et += el
        mx = max_threat_d.get(d, 0)
        enemy_active = enemy_sortie.get(d, 0) > 0
        phase_name = daily_phase_label(
            strike_cnt.get(d, 0) > 0, (ol + el) > 0,
            (d in recon_days) or (d in awacs_days), enemy_active)
        base = {"低烈度日": 8, "前出日": 15, "侦察日": 20, "摩擦日": 35,
                "对抗日": 55, "打击日": 72}.get(phase_name, 8)
        idx = base + ol * 4 + el * 2 + strike_cnt.get(d, 0) * 3 + mx * 2
        rows.append((d, phase_name,
                     enemy_sortie.get(d, 0), our_sortie.get(d, 0),
                     recon_cnt.get(d, 0), strike_cnt.get(d, 0),
                     el, ol, et, ot,
                     mx, min(100, idx), 1 if enemy_active else 0))
        d += timedelta(days=1)
    return rows


# ════════════════════════ 主流程 ════════════════════════

def main():
    """生成全部 mock 数据并写出 mock_data.sql。"""
    print("开始生成态势 mock 数据（手绘航迹驱动版）...")

    for a in AIRCRAFTS:
        aircraft_status.setdefault(a[0], "在役")

    build_all_missions()
    print(f"任务编排完成：任务 {len(missions)} 个"
          f"（我方（红） {sum(1 for m in missions if m[5] == OUR_FACTION)}"
          f" / 敌方（蓝） {sum(1 for m in missions if m[5] == ENEMY_FACTION)}）")

    our_with_threat = compute_our_threats()
    enemy_final = compute_enemy_overlap()
    print(f"轨迹生成完成：我方 {len(our_with_threat)} 点，敌方 {len(enemy_final)} 点（威胁预计算完成）")

    daily = build_daily(our_with_threat)

    lines = [
        "-- ============================================================",
        "-- 态势图 mock 数据：战机侦察打击（台海，虚构，手绘航迹驱动版）",
        "-- 阵营设定：红方 = 大陆方（我方）；蓝方 = 敌方",
        "-- 红方（我方）7 架（侦察机 4 / 预警机 2 / 无人攻击机 1）+ 蓝方（敌方）3 架（无人机）",
        "-- 航迹几何来自 drawn_tracks.json 手绘轨迹，时间轴按 record_time/event_time 播放",
        "-- 由 generate_mock_data.py 自动生成，勿手工修改",
        "-- ============================================================",
        "USE mock_situation;",
        "",
    ]

    # 1 机型
    tw = TableWriter(lines, "mock_aircraft_type",
                     ["type_id", "type_name", "faction", "category", "max_speed_kmh",
                      "cruise_speed_kmh", "max_altitude_m", "max_range_km", "recon_radius_km",
                      "strike_radius_km", "combat_load_kg", "crew"])
    for t in AIRCRAFT_TYPES:
        tw.add(*t)
    tw.flush()

    # 2 飞机（按基地分配所属中队）
    tw = TableWriter(lines, "mock_aircraft",
                     ["aircraft_id", "callsign", "type_id", "faction", "squadron", "base_name",
                      "home_lng", "home_lat", "status", "commission_date"])
    squads = {
        "福州基地": "北部侦察打击联队", "厦门基地": "中部预警侦察联队", "汕头基地": "南部侦察联队",
        "敌北部基地": "北部无人机大队", "敌南部基地": "南部无人机大队",
    }
    for ac in AIRCRAFTS:
        blng, blat = BASES[ac[3]]
        # 阵营来自机型档案（单一事实来源），不再用编号前缀推导
        tw.add(ac[0], ac[1], ac[2], TYPE_BY_ID[ac[2]][2],
               squads[ac[3]], ac[3], blng, blat, aircraft_status[ac[0]], ac[4])
    tw.flush()

    # 3 我方航迹
    tw = TableWriter(lines, "mock_track_point",
                     ["aircraft_id", "aircraft_name", "faction", "mission_id", "seq", "record_time",
                      "track_lng", "track_lat", "altitude_m", "speed_kmh", "heading_deg",
                      "vertical_rate_mps", "overlap_count", "threat_level"])
    for r in our_with_threat:
        tw.add(*r)
    tw.flush()

    # 4 敌方航迹（行结构 ...heading(9), coverage_overlap_count(10)）
    tw = TableWriter(lines, "mock_enemy_track_point",
                     ["enemy_aircraft_id", "enemy_aircraft_name", "mission_id", "seq", "record_time",
                      "track_lng", "track_lat", "altitude_m", "speed_kmh", "heading_deg",
                      "coverage_overlap_count"])
    for r in enemy_final:
        tw.add(*r)
    tw.flush()

    # 5 能力范围圈（已废弃写入：能力圈改由 map_builder 按当前时间 t + 飞机当前位置 + 机型档案半径动态生成）
    # mock_capability_range 表 schema 保留作 legacy 手动覆盖路径，新数据不再写入

    # 6 敌静态威胁
    tw = TableWriter(lines, "mock_enemy_threat",
                     ["threat_id", "threat_name", "threat_type", "lng", "lat", "detect_radius_km",
                      "strike_radius_km", "threat_level", "status", "note"])
    for t in ENEMY_THREATS:
        tw.add(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], "活跃", "持续保持战备")
    tw.flush()

    # 7 打击目标（最终状态由打击事件派生）
    tw = TableWriter(lines, "mock_target",
                     ["target_id", "target_name", "category", "importance", "lng", "lat",
                      "defense_level", "status", "destroyed_time"])
    for t in TARGETS:
        status, ttime = target_final.get(t[0], ("完好", None))
        tw.add(t[0], t[1], t[2], t[3], t[4], t[5], t[6], status, ttime)
    tw.flush()

    # 8 任务
    tw = TableWriter(lines, "mock_mission",
                     ["mission_id", "mission_name", "mission_type", "aircraft_id", "aircraft_name",
                      "faction", "target_id", "start_time", "end_time", "status", "result_summary"])
    for m in missions:
        tw.add(*m)
    tw.flush()

    # 9 打击事件
    tw = TableWriter(lines, "mock_strike_event",
                     ["event_id", "mission_id", "aircraft_id", "aircraft_name", "target_id",
                      "target_name", "event_time", "event_lng", "event_lat", "weapon_type",
                      "hit_result", "collateral_note"])
    for e in strike_events:
        tw.add(*e)
    tw.flush()

    # 10 战损
    tw = TableWriter(lines, "mock_battle_damage",
                     ["damage_id", "aircraft_id", "aircraft_name", "faction", "mission_id",
                      "event_time", "event_lng", "event_lat", "damage_type", "severity",
                      "caused_by", "confirmed"])
    for dm in damages:
        tw.add(*dm)
    tw.flush()

    # 11 侦察发现
    tw = TableWriter(lines, "mock_recon_event",
                     ["event_id", "aircraft_id", "aircraft_name", "target_id", "target_name",
                      "mission_id", "event_time", "event_lng", "event_lat", "confidence",
                      "intel_summary"])
    for e in recon_events:
        tw.add(*e)
    tw.flush()

    # 12 每日态势
    tw = TableWriter(lines, "mock_daily_situation",
                     ["stat_date", "campaign_phase", "blue_sortie_count", "red_sortie_count",
                      "recon_event_count", "strike_event_count", "blue_loss_today", "red_loss_today",
                      "blue_loss_total", "red_loss_total", "max_threat_level", "threat_index",
                      "enemy_patrol_active"])
    for r in daily:
        tw.add(*r)
    tw.flush()

    out = SQL_DIR / "mock_data.sql"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    # ── 统计输出 ──
    print("=" * 60)
    print(f"机型 {len(AIRCRAFT_TYPES)} | 飞机 {len(AIRCRAFTS)} | 任务 {len(missions)}")
    print(f"我方航迹 {len(our_with_threat)} 点 | 敌方航迹 {len(enemy_final)} 点")
    print(f"敌静态威胁 {len(ENEMY_THREATS)} | 目标 {len(TARGETS)}"
          f"（摧毁 {sum(1 for v in target_final.values() if v[0] == '摧毁')}）")
    print(f"打击事件 {len(strike_events)} | 战损 {len(damages)}"
          f"（我方（红） {sum(1 for d in damages if d[3] == OUR_FACTION)}"
          f"/敌方（蓝） {sum(1 for d in damages if d[3] == ENEMY_FACTION)}） | 侦察发现 {len(recon_events)}")
    print(f"每日汇总 {len(daily)} 天（{daily[0][0]} ~ {daily[-1][0]}）")
    for m in missions:
        print(f"  {m[0]} {m[7]:%m-%d %H:%M} → {m[8]:%H:%M} "
              f"({(m[8] - m[7]).total_seconds() / 60:.0f} 分钟) {m[4]} {m[2]}")
    print(f"已写出: {out}")


if __name__ == "__main__":
    main()