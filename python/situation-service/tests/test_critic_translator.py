"""Critic 翻译器单元测试（VERIFY 阶段 review_artifact 方案 §7.1）。

覆盖 apply_actions 的五类编辑指令与边界场景：
- replace_type：成功改 type / 目标不存在 / newType 非法
- drop_chart：成功移除 / 目标不存在 / 移除后跌破下限
- add_chart：成功新增 / subQuestionRef 未命中 / newType 非法 / 新增后超上限
- replace_map_layer：成功改 layerType / 目标不存在时静默跳过
- accept：占位指令，不修订
- 数量硬约束：修订后不在 [2,4] 触发 errors
- 校验复用：validate_plan_against_meta 失败触发 errors
"""
from __future__ import annotations

import unittest

from agent.critic_translator import apply_actions


# ── 测试夹具 ──
_DEFAULT_PROFILE = {
    "skillId": "",
    "skillName": "通用态势分析",
    "chartTypes": ["bar", "line", "pie", "radar", "scatter"],
}

# meta 为空 dict → _validate_plan 跳过白名单校验（兼容 mock 场景）
_EMPTY_META: dict = {}

_BASE_SUB_QUESTIONS = [
    {"id": "q1", "question": "问题 1", "datasetId": "ds1"},
    {"id": "q2", "question": "问题 2", "datasetId": "ds2"},
]

_BASE_CHART_SPECS = [
    {"id": "c1", "type": "bar", "title": "图 1", "subQuestionRef": "q1"},
    {"id": "c2", "type": "line", "title": "图 2", "subQuestionRef": "q2"},
]

_BASE_MAP_SPECS: list = []


class ReplaceTypeTests(unittest.TestCase):
    """replace_type 指令。"""

    def test_replace_type_success(self):
        actions = [{"type": "replace_type", "targetChartId": "c1", "newType": "pie",
                     "reason": "pie 更直观"}]
        nc, nm, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(nc[0]["type"], "pie")
        # 原 chart_specs 不被修改（深拷贝）
        self.assertEqual(_BASE_CHART_SPECS[0]["type"], "bar")

    def test_replace_type_target_missing(self):
        actions = [{"type": "replace_type", "targetChartId": "cX", "newType": "pie",
                     "reason": "无目标"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("不存在" in e for e in errs))

    def test_replace_type_invalid_new_type(self):
        actions = [{"type": "replace_type", "targetChartId": "c1", "newType": "bubble",
                     "reason": "非法类型"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("newType" in e and "非法" in e for e in errs))


class DropChartTests(unittest.TestCase):
    """drop_chart 指令。"""

    def test_drop_chart_success(self):
        # 配合 add_chart 补位，避免跌破下限
        actions = [
            {"type": "drop_chart", "targetChartId": "c1", "reason": "冗余"},
            {"type": "add_chart", "newType": "radar",
             "newSubQuestionRef": "q1", "reason": "补位"},
        ]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertNotIn("c1", [c.get("id") for c in nc])
        self.assertEqual(len(nc), 2)  # 删 1 加 1 = 2

    def test_drop_chart_target_missing(self):
        actions = [{"type": "drop_chart", "targetChartId": "cX", "reason": "无目标"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("不存在" in e for e in errs))

    def test_drop_chart_below_min(self):
        # 直接 drop 一张，剩 1 张 → 校验失败
        actions = [{"type": "drop_chart", "targetChartId": "c1", "reason": "跌破下限"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("不在 [2, 4]" in e for e in errs))


class AddChartTests(unittest.TestCase):
    """add_chart 指令。"""

    def test_add_chart_success(self):
        actions = [{"type": "add_chart", "newType": "radar",
                    "newSubQuestionRef": "q1", "reason": "补充雷达图"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(len(nc), 3)
        self.assertEqual(nc[-1]["type"], "radar")
        self.assertEqual(nc[-1]["subQuestionRef"], "q1")

    def test_add_chart_sub_ref_missing(self):
        actions = [{"type": "add_chart", "newType": "radar",
                    "newSubQuestionRef": "qX", "reason": "子问题不存在"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("未命中子问题" in e for e in errs))

    def test_add_chart_invalid_type(self):
        actions = [{"type": "add_chart", "newType": "bubble",
                    "newSubQuestionRef": "q1", "reason": "非法类型"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("newType" in e and "非法" in e for e in errs))

    def test_add_chart_exceed_max(self):
        # 已有 4 张时再加 → 触发数量上限
        chart_specs = [
            {"id": "c1", "type": "bar", "title": "t1", "subQuestionRef": "q1"},
            {"id": "c2", "type": "line", "title": "t2", "subQuestionRef": "q2"},
            {"id": "c3", "type": "pie", "title": "t3", "subQuestionRef": "q1"},
            {"id": "c4", "type": "radar", "title": "t4", "subQuestionRef": "q2"},
        ]
        actions = [{"type": "add_chart", "newType": "scatter",
                    "newSubQuestionRef": "q1", "reason": "超上限"}]
        nc, _, errs = apply_actions(
            chart_specs, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("不在 [2, 4]" in e for e in errs))


class ReplaceMapLayerTests(unittest.TestCase):
    """replace_map_layer 指令。"""

    def test_replace_map_layer_success(self):
        # q1 需声明 geoMode=raw 才能被 mapSpecs 引用（planner._validate_plan 硬约束）
        sub_qs = [
            {"id": "q1", "question": "问题 1", "datasetId": "ds1", "geoMode": "raw"},
            {"id": "q2", "question": "问题 2", "datasetId": "ds2"},
        ]
        map_specs = [{"id": "m1", "subQuestionRef": "q1", "layerType": "points"}]
        actions = [{"type": "replace_map_layer", "targetChartId": "m1",
                    "newLayerType": "routes", "reason": "改路线"}]
        _, nm, errs = apply_actions(
            _BASE_CHART_SPECS, map_specs, sub_qs,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(nm[0]["layerType"], "routes")

    def test_replace_map_layer_invalid_layer(self):
        map_specs = [{"id": "m1", "subQuestionRef": "q1", "layerType": "points"}]
        actions = [{"type": "replace_map_layer", "targetChartId": "m1",
                    "newLayerType": "heatmap", "reason": "非法"}]
        _, _, errs = apply_actions(
            _BASE_CHART_SPECS, map_specs, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("newLayerType" in e and "非法" in e for e in errs))

    def test_replace_map_layer_target_missing_silent(self):
        """目标不存在时静默跳过，不报错（避免与"无地图场景"冲突）。"""
        actions = [{"type": "replace_map_layer", "targetChartId": "mX",
                    "newLayerType": "routes", "reason": "无目标"}]
        nc, nm, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])


class AcceptAndEmptyTests(unittest.TestCase):
    """accept 指令与空 actions。"""

    def test_accept_no_op(self):
        actions = [{"type": "accept", "reason": "全部接受"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(nc, _BASE_CHART_SPECS)

    def test_empty_actions_no_op(self):
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            [], _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(nc, _BASE_CHART_SPECS)

    def test_unknown_action_type(self):
        actions = [{"type": "regenerate", "reason": "未知指令"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertTrue(any("未知 type" in e for e in errs))


class IdGenerationTests(unittest.TestCase):
    """add_chart 新 id 生成逻辑。"""

    def test_new_id_avoids_conflict(self):
        # 已有 c1/c2，add_chart 应生成 c3
        actions = [{"type": "add_chart", "newType": "scatter",
                    "newSubQuestionRef": "q1", "reason": "test"}]
        nc, _, errs = apply_actions(
            _BASE_CHART_SPECS, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(nc[-1]["id"], "c3")

    def test_new_id_conflict_append_underscore(self):
        # 已有 c1/c2/c3，add_chart 应生成 c4 而非冲突
        chart_specs = [
            {"id": "c1", "type": "bar", "title": "t1", "subQuestionRef": "q1"},
            {"id": "c2", "type": "line", "title": "t2", "subQuestionRef": "q2"},
            {"id": "c3", "type": "pie", "title": "t3", "subQuestionRef": "q1"},
        ]
        actions = [{"type": "add_chart", "newType": "scatter",
                    "newSubQuestionRef": "q2", "reason": "test"}]
        nc, _, errs = apply_actions(
            chart_specs, _BASE_MAP_SPECS, _BASE_SUB_QUESTIONS,
            actions, _DEFAULT_PROFILE, _EMPTY_META,
        )
        self.assertEqual(errs, [])
        self.assertEqual(nc[-1]["id"], "c4")


if __name__ == "__main__":
    unittest.main()
