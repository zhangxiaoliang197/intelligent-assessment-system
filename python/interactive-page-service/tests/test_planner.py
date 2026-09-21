"""Planner 规划校验与兜底测试（不调用 LLM）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import planner, prompts


def _meta(schemas):
    """构造 /export/for-llm 形态的元数据。"""
    return {"success": True, "data": {"schemas": schemas}}


PLAN_OK = {
    "intent": "data_page",
    "title": "空中力量对比",
    "subQuestions": [{
        "id": "q1", "datasetId": "ds-aircraft",
        "question": "双方飞机数量", "mode": "aggregate", "geo": "none",
    }],
    "sections": [
        {"id": "s1", "kind": "kpi", "title": "核心指标", "ref": "q1"},
        {"id": "s2", "kind": "chart", "title": "数量对比", "ref": "q1"},
        {"id": "s3", "kind": "text", "title": "分析结论", "ref": "q1"},
    ],
}


class PlannerValidateTest(unittest.TestCase):
    def setUp(self):
        meta = _meta([{"datasetId": "ds-aircraft", "name": "飞机",
                       "fields": [{"name": "id"}, {"name": "count"}]}])
        self.available = planner._available_dataset_ids(meta)
        self.geo_capable = planner._geo_capable_ids(meta)

    def test_valid_plan(self):
        self.assertIsNone(planner._validate(PLAN_OK, self.available, self.geo_capable))

    def test_general_requires_answer(self):
        plan = {"intent": "general", "directAnswer": ""}
        self.assertIn("directAnswer", planner._validate(plan, self.available, self.geo_capable))

    def test_general_ok(self):
        self.assertIsNone(
            planner._validate({"intent": "general", "directAnswer": "态势分析流程包括…"},
                              self.available, self.geo_capable))

    def test_unknown_dataset_rejected(self):
        plan = {**PLAN_OK, "subQuestions": [
            {**PLAN_OK["subQuestions"][0], "datasetId": "ds-not-exist"}]}
        issues = planner._validate(plan, self.available, self.geo_capable)
        self.assertIsNotNone(issues)
        self.assertIn("不在可用数据集", issues)

    def test_requires_chart_or_map(self):
        plan = {**PLAN_OK, "sections": [
            {"id": "s1", "kind": "kpi", "title": "指标", "ref": "q1"},
            {"id": "s4", "kind": "table", "title": "明细", "ref": "q1"},
            {"id": "s3", "kind": "text", "title": "结论", "ref": "q1"},
        ]}
        self.assertIn("chart 或 map", planner._validate(plan, self.available, self.geo_capable))

    def test_requires_text_section(self):
        plan = {**PLAN_OK, "sections": [
            {"id": "s1", "kind": "kpi", "title": "指标", "ref": "q1"},
            {"id": "s2", "kind": "chart", "title": "对比", "ref": "q1"},
            {"id": "s5", "kind": "filters", "title": "筛选"},
        ]}
        self.assertIn("text", planner._validate(plan, self.available, self.geo_capable))

    def test_duplicate_subquestion_id(self):
        plan = {**PLAN_OK, "subQuestions": PLAN_OK["subQuestions"] * 2}
        self.assertIn("重复", planner._validate(plan, self.available, self.geo_capable))

    def test_bad_ref(self):
        plan = {**PLAN_OK, "sections": [
            *PLAN_OK["sections"],
            {"id": "s9", "kind": "table", "title": "明细", "ref": "qX"},
        ]}
        self.assertIn("qX", planner._validate(plan, self.available, self.geo_capable))


class PlannerGeoTest(unittest.TestCase):
    def test_geo_capable_detects_track_coords(self):
        meta = _meta([{"datasetId": "ds-track", "name": "航迹", "fields": [
            {"name": "id"}, {"name": "aircraft_id"}, {"name": "seq"},
            {"name": "track_lng"}, {"name": "track_lat"}]}])
        self.assertIn("ds-track", planner._geo_capable_ids(meta))

    def test_geo_on_non_spatial_dataset_rejected(self):
        meta = _meta([{"datasetId": "ds-plain", "name": "字典",
                       "fields": [{"name": "id"}, {"name": "name"}]}])
        available = planner._available_dataset_ids(meta)
        geo_capable = planner._geo_capable_ids(meta)
        plan = {**PLAN_OK, "subQuestions": [{
            "id": "q1", "datasetId": "ds-plain", "question": "点",
            "mode": "detail", "geo": "points"}]}
        # sections 中地图引用 q1 时应报错（无地图区时仅警告坐标缺失，由 Researcher 处理）
        plan["sections"] = [
            {"id": "s1", "kind": "kpi", "title": "指标", "ref": "q1"},
            {"id": "s2", "kind": "map", "title": "分布", "ref": "q1"},
            {"id": "s3", "kind": "text", "title": "结论", "ref": "q1"},
        ]
        issue = planner._validate(plan, available, geo_capable)
        self.assertIsNotNone(issue)
        self.assertIn("经纬度", issue)


class PlannerFallbackTest(unittest.TestCase):
    def test_fallback_when_no_datasets(self):
        p = planner.Planner(_meta([]))
        out = p.plan("你好")
        self.assertEqual(out["intent"], "general")
        self.assertIn("数据集", out["directAnswer"])

    def test_fallback_uses_first_dataset(self):
        meta = _meta([{"datasetId": "ds1", "name": "表一",
                       "fields": [{"name": "id"}, {"name": "lng"}, {"name": "lat"}]}])
        out = planner._fallback_plan(meta, "随便看看")
        self.assertEqual(out["intent"], "data_page")
        self.assertEqual(out["subQuestions"][0]["datasetId"], "ds1")
        self.assertEqual(out["subQuestions"][0]["geo"], "points")
        self.assertTrue(any(s["kind"] == "map" for s in out["sections"]))


class PlannerReplanTest(unittest.TestCase):
    """修订延续式规划：已有子问题原样沿用，只为新需求追加子问题。"""

    PARENT_PLAN = {"subQuestions": [
        {"id": "q1", "datasetId": "ds-aircraft", "question": "双方飞机数量",
         "mode": "aggregate", "geo": "none"},
    ]}

    def test_replan_messages_carry_existing_sub_questions(self):
        msgs = prompts.build_replan_messages("加入飞行轨迹以及动态演示", "（目录）", self.PARENT_PLAN)
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        content = msgs[1]["content"]
        self.assertIn("加入飞行轨迹以及动态演示", content)
        self.assertIn("q1", content)
        self.assertIn("原样沿用", content)
        self.assertIn("tracks", content)

    def test_plan_switches_to_replan_prompt_when_parent_plan_given(self):
        meta = _meta([{"datasetId": "ds-aircraft", "name": "飞机",
                       "fields": [{"name": "id"}, {"name": "count"}]}])
        captured = {}

        def fake_call(messages, tools, tool_choice=None, temperature=0.2, max_tokens=6000, **kw):
            captured["messages"] = messages
            return {"content": "", "finish_reason": "stop", "raw_usage": {},
                    "tool_calls": [{"id": "1", "name": "emit_page_plan",
                                    "arguments": PLAN_OK}]}

        with mock.patch.object(planner, "call_llm_with_tools", fake_call):
            out = planner.Planner(meta).plan("加入飞行轨迹", parent_plan=self.PARENT_PLAN)

        self.assertEqual(out["subQuestions"][0]["id"], "q1")
        self.assertIn("延续式规划", captured["messages"][1]["content"])

    def test_plan_without_parent_plan_uses_plain_prompt(self):
        meta = _meta([{"datasetId": "ds-aircraft", "name": "飞机",
                       "fields": [{"name": "id"}, {"name": "count"}]}])
        captured = {}

        def fake_call(messages, tools, tool_choice=None, temperature=0.2, max_tokens=6000, **kw):
            captured["messages"] = messages
            return {"content": "", "finish_reason": "stop", "raw_usage": {},
                    "tool_calls": [{"id": "1", "name": "emit_page_plan",
                                    "arguments": PLAN_OK}]}

        with mock.patch.object(planner, "call_llm_with_tools", fake_call):
            planner.Planner(meta).plan("双方飞机数量")

        self.assertNotIn("延续式规划", captured["messages"][1]["content"])
        self.assertIn("用户问题：双方飞机数量", captured["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
