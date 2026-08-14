#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把演示数据的时间列整体平移到“现在”，让时间窗类 Skill 始终有匹配记录。

generate-demo-data.py 旧版本以固定锚点 2026-01-01 生成时间戳，运行一段时间后
「近24小时」「近7天」等时间窗过滤就会落空。本脚本按全库统一增量平移所有
DATE/DATETIME 列，保持行内、行间与跨表的时间先后关系不变，最新记录落在
当前时刻往前 24 小时内。重复执行安全：数据已新鲜时自动跳过。

用法：
    .venv/Scripts/python.exe scripts/refresh-demo-data-times.py
"""
import datetime

import pymysql

conn = pymysql.connect(
    host="localhost", port=3306, user="root", password="root",
    database="demo_business", charset="utf8mb4", autocommit=False,
)
cur = conn.cursor()

# ── 1. 收集所有 DATE/DATETIME 列 ──
cur.execute("""
    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'demo_business' AND DATA_TYPE IN ('date', 'datetime')
""")
columns = [(table, col, data_type) for table, col, data_type in cur.fetchall()]
if not columns:
    print("demo_business 中没有可刷新的时间列，退出。")
    raise SystemExit(0)
print(f"发现 {len(columns)} 个时间列，分布在 {len({c[0] for c in columns})} 张表")

# ── 2. 全库最新值 → 统一增量（保持跨表先后关系）──
max_values = []
for table, col, _data_type in columns:
    cur.execute(f"SELECT MAX(`{col}`) FROM `{table}`")
    value = cur.fetchone()[0]
    if value is not None:
        max_values.append(value)
global_max = max(max_values) if max_values else None
if global_max is None:
    print("所有时间列均为空，退出。")
    raise SystemExit(0)

now = datetime.datetime.now()
delta = now - global_max
if delta < datetime.timedelta(hours=1):
    print(f"数据已足够新鲜（最新 {global_max}），无需平移。")
    raise SystemExit(0)
days = max(1, delta.days)
print(f"最新时间 {global_max} → 统一平移 +{days} 天（最新记录将落在当前时刻前 24 小时内）")

# ── 3. 平移所有时间列 ──
for table, col, _data_type in columns:
    cur.execute(f"UPDATE `{table}` SET `{col}` = `{col}` + INTERVAL {days} DAY")
    print(f"  {table}.{col} +{days} 天")
conn.commit()
print("完成。")
