"""验证「指标按需选择查询」功能的单元测试。

核心验证点：
1. 传入 selected_indicator_names 时，run_indicator_query 只把选中的指标
   传递给 assess_data_sufficiency（含 admin 合并回来的指标也会被过滤掉）。
2. 不传 selected_indicator_names 时，全部指标（含合并的 admin 指标）都到达
   assess_data_sufficiency（向后兼容）。
3. assess_data_sufficiency 直接按传入的指标子集计算覆盖率/充分性。

运行方式:
    cd D:\\code\\intelligent-assessment-system\\python\\qa-service
    python test_indicator_selection.py
"""

import asyncio
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))


# ── 测试用指标定义 ──
# 3 个原始指标：命中率/摧毁率（admin-db，带 fieldMapping）/响应时间（llm）
_INDICATOR_DEFS = [
    {
        "name": "命中率",
        "formula": "命中数/发射数",
        "type": "admin-db",
        "fieldMapping": '{"命中数": "t1.hit", "发射数": "t1.fire"}',
    },
    {"name": "摧毁率", "formula": "摧毁数/命中数", "type": "admin-db"},
    {"name": "响应时间", "formula": "avg(响应时间)", "type": "llm"},
]

# dataset_indicator_node 会从 admin 拉取并合并回来的「额外」指标（未在 indicator_defs 中）
_ADMIN_MERGED_EXTRA = [{"name": "覆盖率", "formula": "covered/total", "type": "admin-db"}]


def _build_common_patches():
    """返回 run_indicator_query 所需的全部外部依赖 mock 上下文管理器。"""
    base_mock = MagicMock()

    async def fake_llm_call(state, fn):
        state.generated_sql = "SELECT 1"
        state.sql_valid = True
        state.steps = []
        return state

    # 直接 mock analyst_node（而非 run_analyst），避免 token 队列因 bridge 永不调用而挂起
    async def fake_analyst_node(es, raw_results, stream_llm_gen):
        es.final_answer = "测试分析结论"
        if False:  # 使其成为异步生成器
            yield

    async def fake_build_field_hints(schemas, merged, llm_call_fn=None):
        # 直通：返回原指标（不附加 _field_hints），让过滤逻辑成为唯一变量
        return [dict(ind) for ind in merged]

    return [
        patch("agents.indicator_query.fetch_database_tables", return_value=[]),
        patch("agents.indicator_query.fetch_datasets_for_database", return_value=[]),
        patch("agents.indicator_query.fetch_indicators_for_datasets",
              return_value=list(_ADMIN_MERGED_EXTRA)),
        patch("agents.indicator_query.fetch_table_structure",
              return_value={"tableName": "t", "columns": [], "count": 0}),
        patch("agents.indicator_query.fetch_database_config", return_value={}),
        patch("agents.indicator_query.build_field_hints", new=fake_build_field_hints),
        patch("agents.indicator_query.run_text_to_sql", side_effect=fake_llm_call),
        patch("agents.indicator_query.analyst_node", new=fake_analyst_node),
        patch("agents.indicator_query.execute_sql_on_database",
              return_value={"success": True, "rows": [{"命中率": 0.8}]}),
    ], base_mock


# =========================================================================
# 测试 1: 选中过滤 — 只有选中指标到达 assess_data_sufficiency
# =========================================================================
def test_selection_filters_indicators():
    """传 selected_indicator_names=['命中率','响应时间']，验证：
    - 命中率、响应时间 保留
    - 未选的「摧毁率」被过滤
    - admin 合并回来的「覆盖率」也被过滤
    """
    from agents.sufficiency import assess_data_sufficiency as real_assess

    captured = {}

    def spy_assess(raw_results, enhanced_indicators, question, **kwargs):
        captured["names"] = [ind.get("name") for ind in enhanced_indicators]
        captured["count"] = len(enhanced_indicators)
        return real_assess(raw_results, enhanced_indicators, question, **kwargs)

    patches, _ = _build_common_patches()
    with patch("agents.indicator_query.assess_data_sufficiency", side_effect=spy_assess), \
            _exit_stack(patches):
        from agents.indicator_query import run_indicator_query

        async def collect():
            async for _ in run_indicator_query(
                question="test", database_id="db-1", database_name="test",
                indicator_defs=list(_INDICATOR_DEFS), analysis_plan="",
                llm_call_fn=MagicMock(),
                selected_indicator_names=["命中率", "响应时间"],
            ):
                pass

        asyncio.run(collect())

    assert captured.get("count") == 2, (
        f"选中 2 个指标，但到达 assess_data_sufficiency 的有 {captured.get('count')} 个: "
        f"{captured.get('names')}")
    assert set(captured.get("names", [])) == {"命中率", "响应时间"}, (
        f"应仅含 命中率/响应时间，实际: {captured.get('names')}")
    assert "摧毁率" not in captured.get("names", []), "未选的「摧毁率」不应到达充分性判定"
    assert "覆盖率" not in captured.get("names", []), "admin 合并回来的「覆盖率」不应到达充分性判定"
    print(f"  [PASS] 选中过滤：到达充分性判定的指标 = {captured['names']}")


# =========================================================================
# 测试 2: 向后兼容 — 不传 selected_indicator_names 时全部指标到达
# =========================================================================
def test_no_selection_keeps_all():
    """不传 selected_indicator_names，验证 4 个指标（3 原始 + 1 合并）全部到达。"""
    from agents.sufficiency import assess_data_sufficiency as real_assess

    captured = {}

    def spy_assess(raw_results, enhanced_indicators, question, **kwargs):
        captured["names"] = [ind.get("name") for ind in enhanced_indicators]
        captured["count"] = len(enhanced_indicators)
        return real_assess(raw_results, enhanced_indicators, question, **kwargs)

    patches, _ = _build_common_patches()
    with patch("agents.indicator_query.assess_data_sufficiency", side_effect=spy_assess), \
            _exit_stack(patches):
        from agents.indicator_query import run_indicator_query

        async def collect():
            async for _ in run_indicator_query(
                question="test", database_id="db-1", database_name="test",
                indicator_defs=list(_INDICATOR_DEFS), analysis_plan="",
                llm_call_fn=MagicMock(),
                selected_indicator_names=None,
            ):
                pass

        asyncio.run(collect())

    assert captured.get("count") == 4, (
        f"未选择时应全部 4 个到达，实际 {captured.get('count')}: {captured.get('names')}")
    assert set(captured.get("names", [])) == {"命中率", "摧毁率", "响应时间", "覆盖率"}, (
        f"应含全部 4 个指标，实际: {captured.get('names')}")
    print(f"  [PASS] 向后兼容：全部 {captured['count']} 个指标到达充分性判定")


# =========================================================================
# 测试 3: 充分性按子集判定 — assess_data_sufficiency 基于传入指标计算覆盖率
# =========================================================================
def test_sufficiency_based_on_subset():
    """直接调 assess_data_sufficiency，传 2 个指标 + 仅覆盖 1 个的结果列，
    断言 indicators_total=2、coverage_ratio=0.5、scenario=insufficient。"""
    from agents.sufficiency import assess_data_sufficiency

    indicators = [
        {"name": "命中率", "formula": "命中数/发射数"},
        {"name": "摧毁率", "formula": "摧毁数/命中数"},
    ]
    raw_results = [{"命中率": 0.8}]  # 只有命中率列有数据

    report = assess_data_sufficiency(raw_results, indicators, "分析命中与摧毁情况")

    assert report["indicators_total"] == 2, (
        f"指标总数应为 2，实际 {report['indicators_total']}")
    assert report["indicators_with_data"] == 1, (
        f"有数据指标应为 1，实际 {report['indicators_with_data']}")
    assert abs(report["coverage_ratio"] - 0.5) < 1e-6, (
        f"覆盖率应为 0.5，实际 {report['coverage_ratio']}")
    assert report["scenario"] == "insufficient", (
        f"场景应为 insufficient，实际 {report['scenario']}")
    missing = [p["name"] for p in report["per_indicator"] if not p["has_data"]]
    assert "摧毁率" in missing, f"摧毁率应被判定为无数据，实际缺失列表: {missing}"
    print(f"  [PASS] 充分性按子集判定：{report['indicators_with_data']}/"
          f"{report['indicators_total']} → {report['scenario']}")


# =========================================================================
# 测试 4 & 5: _build_query_start_text — 确认消息文案
# （独立字符串格式化函数，无需 mock 任何外部依赖）
# =========================================================================

def _test_query_text_with_selection():
    """传 selected_indicator_names=['命中率','响应时间','摧毁率']，
    验证 A2/A3 两种文案均包含指标名称 且 不含'这些指标'/'全部指标'。"""
    _build_query_start_text = _get_build_query_start_text()

    selected = ["命中率", "响应时间", "摧毁率"]

    # A2 confirm
    t = _build_query_start_text("测试库", "db-1", selected, "confirm")
    assert "指标「命中率、响应时间、摧毁率」" in t, f"A2 文案未包含选中指标名: {t!r}"
    assert "这些指标" not in t, f"A2 文案不应出现'这些指标': {t!r}"
    assert "全部指标" not in t, f"A2 文案不应出现'全部指标': {t!r}"

    # A3 by_name
    t = _build_query_start_text("测试库", "db-1", selected, "by_name")
    assert "指标「命中率、响应时间、摧毁率」" in t, f"A3 文案未包含选中指标名: {t!r}"
    assert "这些指标" not in t, f"A3 文案不应出现'这些指标': {t!r}"
    assert "全部指标" not in t, f"A3 文案不应出现'全部指标': {t!r}"

    print(f"  [PASS] 有选中：A2/A3 均包含指标名称")


def _test_query_text_without_selection():
    """不传 selected_indicator_names，验证 A2 用'全部指标'兜底、A3 保持'开始查询指标'。"""
    _build_query_start_text = _get_build_query_start_text()

    # A2 confirm — 无选中
    t = _build_query_start_text("测试库", "db-1", None, "confirm")
    assert "查询全部指标" in t, f"A2 默认文案应含'查询全部指标': {t!r}"
    assert "查询指标「" not in t, f"A2 无选中时不应列出指标名: {t!r}"

    # A3 by_name — 无选中
    t = _build_query_start_text("测试库", "db-1", None, "by_name")
    assert "开始查询指标" in t, f"A3 默认文案应含'开始查询指标': {t!r}"
    assert "查询指标「" not in t, f"A3 无选中时不应列出指标名: {t!r}"

    # 兼容：空列表等同未选中
    t = _build_query_start_text("测试库", "db-1", [], "confirm")
    assert "查询全部指标" in t, f"空列表应等同未选中: {t!r}"

    print(f"  [PASS] 无选中：A2 使用'全部指标', A3 保持'开始查询指标'")


def _get_build_query_start_text():
    """通过 importlib 从 indicator-service/main.py 加载 _build_query_start_text。

    确保 indicator-service 目录在 sys.path 中，以便 main.py 内部 from utils import ... 正确解析。
    """
    import importlib.util as _iu
    import os as _os
    _ind_dir = _os.path.join(_os.path.dirname(__file__), '..', 'indicator-service')
    _ind_dir = _os.path.abspath(_ind_dir)
    if _ind_dir not in sys.path:
        sys.path.insert(0, _ind_dir)
    _path = _os.path.join(_ind_dir, 'main.py')
    _spec = _iu.spec_from_file_location('_indicator_service_main_test', _path)
    _mod = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod._build_query_start_text


# =========================================================================
# 辅助：把一组 patch 上下文管理器组合成单个 context manager
# =========================================================================
class _exit_stack:
    def __init__(self, cms):
        self._cms = cms
        self._entered = []

    def __enter__(self):
        for cm in self._cms:
            self._entered.append(cm.__enter__())
        return self

    def __exit__(self, *exc):
        ret = False
        for cm in reversed(self._cms):
            if cm.__exit__(*exc):
                ret = True
        return ret


# =========================================================================
# Main
# =========================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("指标按需选择查询 — 单元测试")
    print("=" * 60)

    tests = [
        ("选中过滤", test_selection_filters_indicators),
        ("向后兼容", test_no_selection_keeps_all),
        ("充分性按子集判定", test_sufficiency_based_on_subset),
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

    # ── 测试 4 & 5: _build_query_start_text（在 indicator-service 中） ──
    text_tests = [
        ("确认消息文案 - 有选中指标", _test_query_text_with_selection),
        ("确认消息文案 - 无选中/默认", _test_query_text_without_selection),
    ]
    for name, fn in text_tests:
        try:
            print(f"\n[{name}]")
            fn()
            passed += 1
        except Exception as e:
            import traceback as _tb
            failed += 1
            print(f"  [FAIL] {e}")
            _tb.print_exc()

    print("\n" + "=" * 60)
    print(f"结果: {passed} passed, {failed} failed, {len(tests) + len(text_tests)} total")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
