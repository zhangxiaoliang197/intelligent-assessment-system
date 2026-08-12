# -*- coding: utf-8 -*-
"""indicator_engine（编译器/规划器/Preflight）单元测试。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.indicator_engine import (
    compile_indicator_spec, plan_indicators, preflight_indicators,
)


SPEC = {
    "sourceTables": [
        {"alias": "o", "tableName": "orders", "role": "fact"},
        {"alias": "i", "tableName": "order_items", "role": "detail"},
        {"alias": "p", "tableName": "products", "role": "dimension"},
    ],
    "keyMappings": [
        {"left": "o.order_id", "right": "i.order_id"},
        {"left": "i.product_id", "right": "p.product_id"},
    ],
    "dimensions": [
        {"alias": "d", "table": "o", "column": "order_date", "type": "time"},
    ],
    "parameters": [
        {"name": "物品类别", "term": "某物品", "type": "filter",
         "target": {"table": "p", "column": "item_type"}},
    ],
    "bindings": [
        {"term": "订单数", "kind": "agg", "agg": "COUNT_DISTINCT",
         "table": "o", "column": "order_id"},
        {"term": "销售额", "kind": "agg", "agg": "SUM",
         "table": "i", "column": "price"},
        {"term": "目标物品订单数", "kind": "scoped",
         "base": {"term": "订单数", "table": "o", "column": "order_id",
                  "agg": "COUNT_DISTINCT"},
         "scope": {"table": "p", "column": "item_type",
                   "operator": "=", "value": "=参数(物品类别)"}},
    ],
    "grain": {"groupBy": ["d"], "distinct": False},
    "output": {"alias": "avg_order_value", "label": "客单价"},
}


SCHEMA = {
    "orders": ["order_id", "order_date", "status"],
    "order_items": ["item_id", "order_id", "product_id", "price"],
    "products": ["product_id", "item_type", "name"],
}


def test_compile():
    ok, plan = compile_indicator_spec(SPEC, params={"物品类别": "A类"},
                                      check_schema=SCHEMA)
    assert ok, plan["errors"]
    assert plan["sql"].startswith("SELECT o.order_date AS d")
    assert "COUNT(DISTINCT o.order_id) AS 订单数" in plan["sql"]
    assert "SUM(i.price) AS 销售额" in plan["sql"]
    assert "p.item_type = 'A类'" in plan["sql"]
    assert "GROUP BY o.order_date" in plan["sql"]
    assert plan["gaps"] == []
    print("[ok] test_compile")
    print(plan["sql"])


def test_compile_missing_binding():
    bad = json.loads(json.dumps(SPEC, ensure_ascii=False))
    bad["bindings"][0]["column"] = "not_a_column"
    ok, plan = compile_indicator_spec(bad, params={}, check_schema=SCHEMA)
    assert not ok
    assert any("列" in e or "schema" in e for e in plan["errors"] + plan["gaps"])
    print("[ok] test_compile_missing_binding")


def test_plan_merges_and_flags_unready():
    inds = [
        {"name": "客单价", "indicatorSpec": json.dumps(SPEC, ensure_ascii=False),
         "_question": "某物品的客单价"},
        {"name": "未配置指标", "formula": "X/Y"},
    ]
    res = plan_indicators(inds, params={"物品类别": "A类"}, check_schema=SCHEMA)
    assert len(res["plans"]) == 1
    assert res["plans"][0]["ok"] is True
    assert res["plans"][0]["indicatorNames"] == ["客单价"]
    assert len(res["unready"]) == 1
    assert "未配置 indicatorSpec" in res["unready"][0]["reason"]
    print("[ok] test_plan_merges_and_flags_unready")


def test_preflight():
    inds = [
        {"name": "客单价", "indicatorSpec": json.dumps(SPEC, ensure_ascii=False)},
        {"name": "未配置指标", "formula": "X/Y"},
    ]
    res = preflight_indicators(inds, check_schema=SCHEMA,
                               table_row_counts={"orders": 100, "order_items": 300,
                                                 "products": 50})
    assert res["total"] == 2
    statuses = {p["name"]: p["status"] for p in res["per_indicator"]}
    assert statuses["客单价"] == "ready"
    assert statuses["未配置指标"] == "missing_binding"
    print("[ok] test_preflight")


def test_preflight_empty_source():
    inds = [{"name": "客单价", "indicatorSpec": json.dumps(SPEC, ensure_ascii=False)}]
    res = preflight_indicators(inds, check_schema=SCHEMA,
                               table_row_counts={"orders": 0, "order_items": 0,
                                                 "products": 0})
    assert res["per_indicator"][0]["status"] == "empty_source"
    print("[ok] test_preflight_empty_source")


def test_preagg_repurchase():
    spec = {
        "formula": "复购客户数(>=2单) / 总客户数 * 100",
        "sourceTables": [],
        "keyMappings": [],
        "preAggregations": {
            "cust_orders": {
                "table": "orders", "tableAlias": "o",
                "aggColumn": "order_id", "agg": "COUNT_DISTINCT",
                "groupBy": "customer_id",
                "joinTable": "customer", "joinAlias": "c",
                "joinOn": "customer_id",
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
    }
    schema = {"orders": ["order_id", "customer_id"],
              "customer": ["customer_id", "customer_unique_id"]}
    ok, plan = compile_indicator_spec(spec, check_schema=schema)
    assert ok, plan["errors"]
    assert plan["sql"].startswith("WITH cust_orders AS (")
    assert "JOIN customer AS c ON o.customer_id = c.customer_id" in plan["sql"]
    assert "COUNT(CASE WHEN cust_orders.cnt >= 2" in plan["sql"]
    print("[ok] test_preagg_repurchase")
    print(plan["sql"])


def test_expr_with_dotted_refs_and_spaced_table():
    spec = {
        "sourceTables": [{"alias": "i", "tableName": "income statement"}],
        "bindings": [
            {"term": "毛利率", "kind": "expr",
             "expr": "SUM(i.T_REVENUE - i.T_COGS) / SUM(i.T_REVENUE) * 100"},
        ],
        "dimensions": [], "parameters": [], "grain": {},
    }
    schema = {"income statement": ["TICKER_SYMBOL", "END_DATE", "T_REVENUE", "T_COGS"]}
    ok, plan = compile_indicator_spec(spec, check_schema=schema, quote_style="double")
    assert ok, plan["errors"]
    assert '"income statement"' in plan["sql"]
    assert "T_REVENUE" in plan["sql"] and "T_COGS" in plan["sql"]
    assert "SUM(" in plan["sql"]
    print("[ok] test_expr_with_dotted_refs_and_spaced_table")
    print(plan["sql"])


def test_expr_rejects_sql_and_unknown_refs():
    base = {
        "sourceTables": [{"alias": "p", "tableName": "order_payment"}],
        "bindings": [
            {"term": "客单价", "kind": "expr",
             "expr": "SUM(p.payment_value) / COUNT(DISTINCT p.order_id)"},
        ],
        "dimensions": [], "parameters": [], "grain": {},
    }
    schema = {"order_payment": ["order_id", "payment_value"]}
    for bad_expr in ("SELECT * FROM secret", "SUM(x.col)", "SUM(p.nope)"):
        spec = json.loads(json.dumps(base, ensure_ascii=False))
        spec["bindings"][0]["expr"] = bad_expr
        ok, plan = compile_indicator_spec(spec, check_schema=schema, quote_style="backtick")
        assert not ok, f"expected rejection: {bad_expr}"
    print("[ok] test_expr_rejects_sql_and_unknown_refs")


if __name__ == "__main__":
    test_compile()
    test_compile_missing_binding()
    test_plan_merges_and_flags_unready()
    test_preflight()
    test_preflight_empty_source()
    test_preagg_repurchase()
    test_expr_with_dotted_refs_and_spaced_table()
    test_expr_rejects_sql_and_unknown_refs()
    print("\nAll indicator_engine tests passed.")
