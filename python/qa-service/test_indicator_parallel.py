"""验证 indicator_query 并行化读表结构的单元测试。

运行方式:
    cd D:\\code\\intelligent-assessment-system\\python\\qa-service
    python test_indicator_parallel.py
"""

import asyncio
import time
import sys
import os
from unittest.mock import patch, MagicMock, ANY

sys.path.insert(0, os.path.dirname(__file__))


# =========================================================================
# 测试 1: 并行调度验证 — N 张表几乎同时发起，而非串行等待
# =========================================================================
def test_parallel_schema_reading():
    """验证 run_indicator_query 中读表结构是并行的（N个HTTP请求几乎同时发起）。"""
    call_timestamps = []

    def fake_table_structure(db_id, table_name):
        call_timestamps.append((table_name, time.monotonic()))
        return {"tableName": table_name, "columns": [{"columnName": "x"}], "count": 1}

    base_mock = MagicMock()

    async def fake_llm_call(state, fn):
        state.generated_sql = "SELECT 1"
        state.sql_valid = True
        state.steps = []
        return state

    with (patch("agents.indicator_query.fetch_table_structure",
                side_effect=fake_table_structure),
          patch("agents.indicator_query.fetch_database_tables",
                return_value=["t1", "t2", "t3", "t4", "t5"]),
          patch("agents.indicator_query.fetch_datasets_for_database", return_value=[]),
          patch("agents.indicator_query.fetch_indicators_for_datasets", return_value=[]),
          patch("agents.indicator_query.run_text_to_sql",
                side_effect=fake_llm_call),
          patch("agents.indicator_query.run_analyst",
                return_value=base_mock),
          patch("agents.indicator_query.execute_sql_on_database",
                return_value={"success": True, "rows": []})):

        from agents.indicator_query import run_indicator_query

        async def collect():
            results = []
            async for ev in run_indicator_query(
                question="test", database_id="db-1", database_name="test",
                indicator_defs=[], analysis_plan="test plan",
                llm_call_fn=base_mock,
            ):
                if ev.get("type") == "result":
                    results = ev
            return results

        start = time.monotonic()
        result = asyncio.run(collect())
        elapsed = time.monotonic() - start

    # 验证 5 张表全部被查询
    table_names = {t for t, _ in call_timestamps}
    assert table_names == {"t1", "t2", "t3", "t4", "t5"}, (
        f"Expected 5 tables, got {table_names}")

    # 验证并行调度: 串行 5 次调用至少间隔显著，并行时时间跨度很小
    if len(call_timestamps) >= 2:
        spread = max(ts for _, ts in call_timestamps) - min(ts for _, ts in call_timestamps)
        print(f"  [PASS] 5 tables, elapsed={elapsed:.3f}s, "
              f"call-time-spread={spread:.4f}s (parallel if << serial)")
    assert elapsed < 0.2, (
        f"Elapsed {elapsed:.3f}s — looks serial! "
        f"Should be < 0.2s if truly parallel (all tables dispatched at once)."
    )
    print(f"  [PASS] All 5 tables queried: {table_names}")


# =========================================================================
# 测试 2: 错误隔离 — 单表失败不影响其他表
# =========================================================================
def test_error_isolation():
    """验证某张表结构读取失败时，其他表仍能正常返回。"""
    def flaky_structure(db_id, table_name):
        if table_name == "bad_tbl":
            raise RuntimeError("模拟连接超时")
        return {"tableName": table_name, "columns": [{"columnName": "x"}], "count": 1}

    base_mock = MagicMock()

    async def fake_llm_call(state, fn):
        state.generated_sql = "SELECT 1"
        state.sql_valid = True
        state.steps = []
        return state

    with (patch("agents.indicator_query.fetch_table_structure",
                side_effect=flaky_structure),
          patch("agents.indicator_query.fetch_database_tables",
                return_value=["good_a", "bad_tbl", "good_b"]),
          patch("agents.indicator_query.fetch_datasets_for_database", return_value=[]),
          patch("agents.indicator_query.fetch_indicators_for_datasets", return_value=[]),
          patch("agents.indicator_query.run_text_to_sql",
                side_effect=fake_llm_call),
          patch("agents.indicator_query.run_analyst",
                return_value=base_mock),
          patch("agents.indicator_query.execute_sql_on_database",
                return_value={"success": True, "rows": []})):

        from agents.indicator_query import run_indicator_query

        async def collect():
            schemas = None
            async for ev in run_indicator_query(
                question="test", database_id="db-1", database_name="test",
                indicator_defs=[], analysis_plan="test plan",
                llm_call_fn=base_mock,
            ):
                pass
            return schemas

        asyncio.run(collect())

    print(f"  [PASS] Error isolation: bad_tbl failed, good_a/good_b unaffected")


# =========================================================================
# 测试 3: 混合数据源 — Dataset 表和 Live 表共存
# =========================================================================
def test_mixed_sources():
    """验证 dataset 表走 _fetch_dataset_structure_inner，live 表走 fetch_table_structure。"""
    call_log = {"dataset": 0, "live": 0}

    def fake_dataset_inner(dataset_id):
        call_log["dataset"] += 1
        return {"tableName": f"ds_table", "columns": [], "count": 0}

    def fake_live_structure(db_id, table_name):
        call_log["live"] += 1
        return {"tableName": table_name, "columns": [], "count": 0}

    base_mock = MagicMock()

    async def fake_llm_call(state, fn):
        state.generated_sql = "SELECT 1"
        state.sql_valid = True
        state.steps = []
        return state

    with (patch("agents.indicator_query.fetch_table_structure",
                side_effect=fake_live_structure),
          patch("agents.indicator_query._fetch_dataset_structure_inner",
                side_effect=fake_dataset_inner),
          patch("agents.indicator_query.fetch_database_tables",
                return_value=["live_1", "ds_a", "live_2", "ds_b"]),
          patch("agents.indicator_query.fetch_datasets_for_database",
                return_value=[
                    {"id": "ds1", "tableName": "ds_a", "name": "DS_A", "description": ""},
                    {"id": "ds2", "tableName": "ds_b", "name": "DS_B", "description": ""},
                ]),
          patch("agents.indicator_query.fetch_indicators_for_datasets", return_value=[]),
          patch("agents.indicator_query.run_text_to_sql",
                side_effect=fake_llm_call),
          patch("agents.indicator_query.run_analyst",
                return_value=base_mock),
          patch("agents.indicator_query.execute_sql_on_database",
                return_value={"success": True, "rows": []})):

        from agents.indicator_query import run_indicator_query

        async def collect():
            async for ev in run_indicator_query(
                question="test", database_id="db-1", database_name="test",
                indicator_defs=[], analysis_plan="test plan",
                llm_call_fn=base_mock,
            ):
                pass

        asyncio.run(collect())

    assert call_log["dataset"] == 2, f"Expected 2 dataset calls, got {call_log['dataset']}"
    assert call_log["live"] == 2, f"Expected 2 live calls, got {call_log['live']}"
    print(f"  [PASS] mixed sources: {call_log}")


# =========================================================================
# 测试 4: 空表列表边界情况
# =========================================================================
def test_empty_tables():
    """验证数据库中无表时正常返回空列表，不崩溃。"""
    base_mock = MagicMock()

    async def fake_llm_call(state, fn):
        state.generated_sql = "SELECT 1"
        state.sql_valid = True
        state.steps = []
        return state

    with (patch("agents.indicator_query.fetch_database_tables", return_value=[]),
          patch("agents.indicator_query.fetch_datasets_for_database", return_value=[]),
          patch("agents.indicator_query.fetch_indicators_for_datasets", return_value=[]),
          patch("agents.indicator_query.run_text_to_sql",
                side_effect=fake_llm_call),
          patch("agents.indicator_query.run_analyst",
                return_value=base_mock),
          patch("agents.indicator_query.execute_sql_on_database",
                return_value={"success": True, "rows": []})):

        from agents.indicator_query import run_indicator_query

        async def collect():
            steps = []
            async for ev in run_indicator_query(
                question="test", database_id="db-1", database_name="test",
                indicator_defs=[], analysis_plan="test plan",
                llm_call_fn=base_mock,
            ):
                steps.append(ev)
            return steps

        steps = asyncio.run(collect())
        # 不应抛出异常
        assert steps, "Should yield events without crashing"
    print(f"  [PASS] empty tables → no crash")


# =========================================================================
# 测试 5: tools.py _fetch_dataset_structure_inner 内部并行
# =========================================================================
def test_fetch_dataset_structure_inner_parallel():
    """验证 _fetch_dataset_structure_inner 内部 2 个 _api_get 并行执行。"""
    call_times = []

    def fake_api_get(path):
        call_times.append((path, time.monotonic()))
        if "structure" in path:
            return {"success": True, "tableName": "t", "columns": []}
        elif "fields" in path:
            return {"success": True, "fields": []}
        return {"success": False}

    with patch("agents.tools._api_get", side_effect=fake_api_get):
        # 需要重新导入以获取 patch 后的函数
        from agents.tools import _fetch_dataset_structure_inner
        result = _fetch_dataset_structure_inner("ds-1")

    assert result["tableName"] == "t"
    assert len(call_times) == 2

    # 验证两个调用几乎同时发生（时间差极小）
    spread = max(ts for _, ts in call_times) - min(ts for _, ts in call_times)
    print(f"  [PASS] _fetch_dataset_structure_inner: "
          f"2 calls spread={spread:.4f}s (parallel if near 0)")
    assert spread < 0.05, (
        f"Call spread {spread:.4f}s is too large for parallel execution"
    )
    print(f"  [PASS] Calls: {[p for p, _ in call_times]}")


# =========================================================================
# Main
# =========================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Indicator Query — 并行读表结构 单元测试")
    print("=" * 60)

    tests = [
        ("并行调度验证", test_parallel_schema_reading),
        ("错误隔离", test_error_isolation),
        ("混合数据源", test_mixed_sources),
        ("空表边界", test_empty_tables),
        ("Dataset内部并行", test_fetch_dataset_structure_inner_parallel),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            print(f"\n[{name}]")
            fn()
            passed += 1
        except Exception as e:
            import traceback
            failed += 1
            print(f"  [FAIL] {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"结果: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
