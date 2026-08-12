# -*- coding: utf-8 -*-
"""现存指标 → Indicator Spec 迁移脚本。

读取 admin-service 中现存指标、数据集、真实表结构，为每个指标构建可编译规格
（indicatorSpec），并调用 admin API 保存（saveAndValidate 自动回写 bind_status）。

用法:
    python scripts/migrate_indicator_specs.py [--apply] [--admin http://localhost:10258]

不带 --apply 时只做本地编译校验并输出迁移计划（不写库）。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

ADMIN = os.environ.get("ADMIN_SERVICE_URL", "http://localhost:10258")
APPLY = "--apply" in sys.argv
for i, a in enumerate(sys.argv):
    if a == "--admin" and i + 1 < len(sys.argv):
        ADMIN = sys.argv[i + 1]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python", "qa-service"))


def api_get(path):
    with urllib.request.urlopen(f"{ADMIN}{path}", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(path, body):
    req = urllib.request.Request(
        f"{ADMIN}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def live_schema(database_id, table_name):
    q = urllib.parse.urlencode({"tableName": table_name})
    r = api_get(f"/api/admin/database/{urllib.parse.quote(database_id, safe='')}/table-structure?{q}")
    cols = {}
    for c in r.get("columns", []) or []:
        cols[c["columnName"]] = c.get("dataType", "")
    return cols


def build_spec(ind, ds, db_type):
    """构建可编译规格。返回 (spec | None, reason)。"""
    table = ds["tableName"]
    fm = {}
    try:
        fm = json.loads(ind.get("fieldMapping") or "{}")
    except json.JSONDecodeError:
        fm = {}
    name = ind["name"]

    if name == "客单价":
        return {
            "formula": ind["formula"],
            "sourceTables": [{"alias": "p", "tableName": table}],
            "keyMappings": [],
            "bindings": [
                {"term": "总支付额", "kind": "agg", "agg": "SUM", "table": "p", "column": "payment_value"},
                {"term": "订单数", "kind": "agg", "agg": "COUNT_DISTINCT", "table": "p", "column": "order_id"},
                {"term": "客单价", "kind": "expr",
                 "expr": "SUM(p.payment_value) / COUNT(DISTINCT p.order_id)"},
            ],
            "dimensions": [],
            "parameters": [],
            "grain": {"groupBy": [], "distinct": False},
            "output": {"alias": "客单价", "label": name},
        }, None

    if name == "平均评分":
        return {
            "formula": ind["formula"],
            "sourceTables": [{"alias": "r", "tableName": table}],
            "keyMappings": [],
            "bindings": [
                {"term": "平均评分", "kind": "agg", "agg": "AVG", "table": "r", "column": "review_score"},
            ],
            "dimensions": [], "parameters": [],
            "grain": {"groupBy": [], "distinct": False},
        }, None

    if name == "平均配送天数":
        return {
            "formula": ind["formula"],
            "sourceTables": [{"alias": "o", "tableName": table}],
            "keyMappings": [],
            "bindings": [
                {"term": "平均配送天数", "kind": "expr",
                 "expr": "AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp))"},
            ],
            "dimensions": [], "parameters": [],
            "grain": {"groupBy": [], "distinct": False},
        }, None

    if name == "GMV":
        return {
            "formula": ind["formula"],
            "sourceTables": [{"alias": "i", "tableName": table}],
            "keyMappings": [],
            "bindings": [
                {"term": "GMV", "kind": "expr",
                 "expr": "SUM(i.price + i.freight_value)"},
            ],
            "dimensions": [], "parameters": [],
            "grain": {"groupBy": [], "distinct": False},
        }, None

    if name == "复购率":
        # 预聚合：orders JOIN customer → 每客户订单数
        return {
            "formula": "复购客户数(>=2单) / 总客户数 * 100",
            "sourceTables": [],
            "keyMappings": [],
            "preAggregations": {
                "cust_orders": {
                    "table": "orders",
                    "tableAlias": "o",
                    "aggColumn": "order_id",
                    "agg": "COUNT_DISTINCT",
                    "groupBy": "customer_id",
                    "joinTable": "customer",
                    "joinAlias": "c",
                    "joinOn": "customer_id",
                    "groupByJoin": "customer_unique_id",
                },
            },
            "bindings": [
                {"term": "复购率", "kind": "expr",
                 "expr": ("COUNT(CASE WHEN preagg(cust_orders, cnt) >= 2 "
                          "THEN preagg(cust_orders, gk) END) "
                          "/ COUNT(preagg(cust_orders, gk)) * 100")},
            ],
            "dimensions": [], "parameters": [],
            "grain": {"groupBy": [], "distinct": False},
        }, None

    # 天池财务指标（达梦：双引号标识符）
    tianchi = {
        "基本每股收益": ("i", "BASIC_EPS", "agg", "MAX"),
        "毛利率": ("i", None, "expr",
                   "SUM(i.T_REVENUE - i.T_COGS) / SUM(i.T_REVENUE) * 100"),
        "市值": ("m", "MARKET_VALUE", "agg", "MAX"),
        "净利率": ("i", None, "expr",
                   "SUM(i.N_INCOME) / SUM(i.T_REVENUE) * 100"),
        "营业利润率": ("i", None, "expr",
                      "SUM(i.OPERATE_PROFIT) / SUM(i.T_REVENUE) * 100"),
        "实际税率": ("i", None, "expr",
                    "SUM(i.INCOME_TAX) / SUM(i.T_PROFIT) * 100"),
    }
    if name in tianchi:
        alias, col, kind, expr = tianchi[name]
        bindings = []
        if kind == "agg":
            bindings.append({"term": name, "kind": "agg", "agg": expr,
                             "table": alias, "column": col})
        else:
            bindings.append({"term": name, "kind": "expr", "expr": expr})
        return {
            "formula": ind["formula"],
            "sourceTables": [{"alias": alias, "tableName": table}],
            "keyMappings": [],
            "bindings": bindings,
            "dimensions": [], "parameters": [],
            "grain": {"groupBy": [], "distinct": False},
        }, None

    return None, f"未识别的指标名称: {name}"


def main():
    inds = api_get("/api/admin/indicator/list").get("indicators", [])
    dss = {d["id"]: d for d in api_get("/api/admin/dataset/list").get("datasets", [])}
    dbs = {d["id"]: d for d in api_get("/api/admin/database/list").get("databases", [])}

    from agents.indicator_engine import (
        compile_indicator_spec, build_check_schema, _quote_style_for)

    report = []
    for ind in inds:
        ds = dss.get(ind.get("datasetId"))
        if not ds:
            report.append({"name": ind["name"], "status": "no_dataset",
                           "reason": f"数据集 {ind.get('datasetId')} 不存在"})
            continue
        db = dbs.get(ds.get("databaseId"), {})
        spec, reason = build_spec(ind, ds, db.get("type", ""))
        if spec is None:
            report.append({"name": ind["name"], "status": "skip", "reason": reason})
            continue

        # 用真实表结构构建校验 schema
        schema = {}
        for st in spec.get("sourceTables", []):
            schema[st["tableName"]] = live_schema(ds["databaseId"], st["tableName"])
        check_schema = {"t": schema}
        # compile_indicator_spec 的 check_schema 是 {表名: [列名]}
        flat = {t: list(cols.keys()) for t, cols in schema.items()}
        quote = _quote_style_for(db.get("type", ""))
        ok, plan = compile_indicator_spec(spec, check_schema=flat, quote_style=quote)

        if APPLY:
            res = api_post(f"/api/admin/indicator/{ind['id']}/spec",
                           {"indicatorSpec": json.dumps(spec, ensure_ascii=False)})
            status = res.get("bindStatus", "error")
            detail = "；".join(res.get("errors", []) or []) or "OK"
            report.append({"name": ind["name"], "status": status, "reason": detail,
                           "sql": plan.get("sql", "")})
        else:
            report.append({"name": ind["name"],
                           "status": "ready" if ok else "not_ready",
                           "reason": "；".join(plan.get("errors", [])) or "OK",
                           "sql": plan.get("sql", "")})

    for r in report:
        print(f"[{r['status']}] {r['name']} — {r.get('reason', '')[:180]}")
        if r.get("sql"):
            print(f"    SQL: {r['sql'][:220]}")
    print(f"\n合计 {len(report)} 个指标"
          f"{'（已写入 admin）' if APPLY else '（预演模式，加 --apply 写入）'}")


if __name__ == "__main__":
    main()
