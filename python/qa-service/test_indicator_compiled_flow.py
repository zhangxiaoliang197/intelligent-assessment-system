# -*- coding: utf-8 -*-
"""端到端验证：run_indicator_query 的确定性编译路径（全部 DB/LLM 打桩）。"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents import indicator_query as iq


SPEC = {
    "sourceTables": [
        {"alias": "o", "tableName": "orders"},
        {"alias": "i", "tableName": "order_items"},
    ],
    "keyMappings": [{"left": "o.order_id", "right": "i.order_id"}],
    "dimensions": [{"alias": "d", "table": "o", "column": "order_date"}],
    "bindings": [
        {"term": "订单数", "kind": "agg", "agg": "COUNT_DISTINCT",
         "table": "o", "column": "order_id"},
        {"term": "销售额", "kind": "agg", "agg": "SUM",
         "table": "i", "column": "price"},
    ],
    "grain": {"groupBy": ["d"], "distinct": False},
}


SCHEMAS = [
    {"tableName": "orders", "columns": [
        {"columnName": "order_id", "dataType": "VARCHAR"},
        {"columnName": "order_date", "dataType": "DATE"}]},
    {"tableName": "order_items", "columns": [
        {"columnName": "item_id", "dataType": "VARCHAR"},
        {"columnName": "order_id", "dataType": "VARCHAR"},
        {"columnName": "price", "dataType": "DECIMAL"}]},
]


async def fake_llm(system, user):
    return "mock"


async def fake_stream(system, user):
    for ch in ["已", "完", "成"]:
        yield ch


def install_mocks():
    calls = {"exec": 0}
    def fake_execute(db_id, sql):
        calls["exec"] += 1
        assert "orders" in sql and "order_items" in sql
        assert "COUNT(DISTINCT o.order_id)" in sql
        return {"success": True, "rows": [
            {"d": "2026-08-01", "订单数": "5", "销售额": "100.5"},
        ]}

    iq.fetch_database_config = lambda db_id: {"type": "MySQL", "id": db_id}
    iq.fetch_database_tables = lambda *a, **k: [
        {"tableName": "orders", "tableComment": "订单表"},
        {"tableName": "order_items", "tableComment": "订单明细"},
        {"tableName": "customers", "tableComment": "客户表"},
    ]
    iq.fetch_datasets_for_database = lambda db_id: [
        {"id": "ds1", "name": "订单数据集", "tableName": "orders",
         "description": "订单主表"},
        {"id": "ds2", "name": "订单明细数据集", "tableName": "order_items",
         "description": "订单商品明细"},
    ]
    iq.fetch_indicators_for_datasets = lambda ids: [
        {"name": "客单价", "formula": "销售额 / 订单数",
         "indicatorSpec": json.dumps(SPEC, ensure_ascii=False)},
    ]
    iq._fetch_dataset_structure_inner = lambda ds_id: {
        "tableName": "orders" if ds_id == "ds1" else "order_items",
        "columns": SCHEMAS[0]["columns"] if ds_id == "ds1" else SCHEMAS[1]["columns"],
    }
    iq.fetch_table_structure = lambda db_id, table_name: {
        "tableName": table_name,
        "columns": [{"columnName": "id", "dataType": "VARCHAR"}],
    }
    iq.execute_sql_on_database = fake_execute
    return calls


def run():
    calls = install_mocks()
    events = []

    async def main():
        async for ev in iq.run_indicator_query(
                question="客单价",
                database_id="db1",
                database_name="测试库",
                indicator_defs=[{"name": "客单价", "formula": "销售额 / 订单数"}],
                analysis_plan="查询客单价",
                llm_call_fn=fake_llm,
                stream_llm_gen=fake_stream,
        ):
            events.append(ev)

    asyncio.run(main())
    result = [e for e in events if e.get("type") == "result"][0]
    assert result["totalRows"] == 1
    assert "preflight" in result and result["preflight"]["ready"] == 1
    assert "queryPlan" in result and result["queryPlan"]["plans"]
    assert calls["exec"] == 1

    steps = [e["step"]["description"] for e in events if e.get("type") == "step"]
    assert "Preflight Readiness" in steps
    assert "Compile Query Plan" in steps
    print("compiled flow events:", steps)
    print("[ok] compiled flow executed deterministically, exec calls =", calls["exec"])


if __name__ == "__main__":
    run()
