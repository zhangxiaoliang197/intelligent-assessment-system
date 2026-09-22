"""技能剧本注入的提示词测试。

核心断言：**未命中技能时，三个 build_*_messages 的输出与改造前逐字节一致** ——
这是「不影响当前生成效果」的硬证据；命中时才追加技能指南。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import prompts, skill_catalog

CATALOG = "1. 数据集ID: ds_air｜名称: 机型统计表\n   字段:\n    - id int"


def _skill(**overrides) -> skill_catalog.Skill:
    data = dict(
        id="air-power-situation",
        name="空军力量态势",
        description="红蓝双方空军兵力对比与航迹动态演示",
        triggers=["分析红蓝方空军力量态势", "对比双方在役与战损飞机数量",
                  "我方战机飞行轨迹与动态演示"],
        required_sections=["kpi", "chart", "map", "text"],
        map_modes=["tracks", "points"],
        playback=True,
        recommended_chart_types=["bar", "pie"],
        interactions=["阵营筛选联动", "时间轴回放"],
        needs=[skill_catalog.Need(entity_kind="air", mode="detail", geo="tracks",
                                  question="逐架次航迹明细")],
        body_sections={
            "取数剧本": "- need: entityKind=air, mode=detail, geo=tracks, question=逐架次航迹明细",
            "区块剧本": "kpi → chart → map → timeline → text",
            "呈现偏好": "- 地图开启回放，能力圈随飞机移动",
            "叙事要点": "- 先给总量对比，再给结构性差异",
        },
        content_hash="a" * 64,
    )
    data.update(overrides)
    return skill_catalog.Skill(**data)


def _ctx(**overrides) -> dict:
    ctx = {
        "id": "air-power-situation",
        "applied": True,
        "matchedBy": "auto",
        "score": 0.7123,
        "reason": "自动套用「空军力量态势」，匹配度 0.712",
        "candidates": [{"id": "air-power-situation", "name": "空军力量态势", "score": 0.7123}],
        "skill": _skill(),
        "needs": [{"entityKind": "air", "mode": "detail", "geo": "tracks",
                   "question": "逐架次航迹明细", "datasetId": "ds_track",
                   "datasetName": "航迹明细", "resolved": True, "reason": ""},
                  {"entityKind": "base", "mode": "detail", "geo": "points",
                   "question": "双方基地位置与驻场机型", "datasetId": "",
                   "datasetName": "", "resolved": False,
                   "reason": "entityKind=base 且需具备坐标（geo=points） 没有匹配的数据集"}],
        "unresolvedNeeds": ["entityKind=base 且需具备坐标（geo=points） 没有匹配的数据集"],
    }
    ctx.update(overrides)
    return ctx


class ZeroRegressionTest(unittest.TestCase):
    """未命中技能时必须与改造前逐字节一致。"""

    def test_plan_messages_identical_without_skill(self):
        expected_system = prompts.PLANNER_SYSTEM_SUFFIX + CATALOG
        for ctx in (None, {}, {"applied": False, "skill": _skill()}):
            messages = prompts.build_plan_messages("分析态势", CATALOG, "", ctx)
            self.assertEqual(expected_system, messages[0]["content"])
            self.assertEqual("用户问题：分析态势", messages[1]["content"])

    def test_plan_messages_identical_with_parent_query(self):
        expected_system = prompts.PLANNER_SYSTEM_SUFFIX + CATALOG
        messages = prompts.build_plan_messages("追问", CATALOG, "上文问题", None)
        self.assertEqual(expected_system, messages[0]["content"])
        self.assertEqual("承接上文：上文问题\n用户问题：追问", messages[1]["content"])

    def test_replan_messages_identical_without_skill(self):
        base = prompts.build_replan_messages("加轨迹", CATALOG, {"subQuestions": []})
        with_none = prompts.build_replan_messages("加轨迹", CATALOG, {"subQuestions": []}, None)
        self.assertEqual(base[0]["content"], with_none[0]["content"])
        self.assertEqual(prompts.PLANNER_SYSTEM_SUFFIX + CATALOG, with_none[0]["content"])
        self.assertEqual(base[1]["content"], with_none[1]["content"])

    def test_page_messages_identical_without_skill(self):
        plan = {"title": "标题", "sections": [], "interactions": []}
        bundle = {"question": "问题", "generatedAt": "now", "datasets": []}
        base = prompts.build_page_messages("问题", plan, bundle, 20)
        with_none = prompts.build_page_messages("问题", plan, bundle, 20, None)
        self.assertEqual(prompts.PAGE_SYSTEM_HEADER, with_none[0]["content"])
        self.assertEqual(base[0]["content"], with_none[0]["content"])
        self.assertEqual(base[1]["content"], with_none[1]["content"])


class SkillGuideTest(unittest.TestCase):

    def test_guides_empty_when_not_applied(self):
        self.assertEqual("", prompts.format_skill_plan_guide(None))
        self.assertEqual("", prompts.format_skill_plan_guide({}))
        self.assertEqual("", prompts.format_skill_plan_guide({"applied": False, "skill": _skill()}))
        self.assertEqual("", prompts.format_skill_page_guide(None))
        self.assertEqual("", prompts.format_skill_page_guide(
            {"applied": False, "skill": _skill()}))

    def test_plan_guide_carries_resolved_datasets_and_constraints(self):
        guide = prompts.format_skill_plan_guide(_ctx())
        self.assertIn("空军力量态势", guide)
        self.assertIn("自动匹配", guide)
        self.assertIn("0.712", guide)
        # 取数剧本必须给出已解析的数据集 ID，而不是让模型自己猜
        self.assertIn("ds_track", guide)
        self.assertIn("航迹明细", guide)
        self.assertIn("区块剧本", guide)
        self.assertIn("sections 必须覆盖这些区块类型：kpi、chart、map、text", guide)
        self.assertIn("必须包含地图区块", guide)
        self.assertIn("entityKind=base", guide)  # 未解析需求如实告知

    def test_plan_guide_when_no_needs_declared(self):
        guide = prompts.format_skill_plan_guide(_ctx(needs=[], unresolvedNeeds=[]))
        self.assertIn("没有声明的数据需求", guide)

    def test_plan_guide_carries_soft_need_question(self):
        """未解析的需求必须把「要回答什么」带进提示词，否则技能的数据意图就丢了。"""
        ctx = _ctx(needs=[{"entityKind": "other", "mode": "detail", "geo": "points",
                           "question": "打击事件位置与效果", "datasetId": "",
                           "datasetName": "", "resolved": False,
                           "reason": "entityKind=other 没有匹配的数据集"}])
        guide = prompts.format_skill_plan_guide(ctx)
        self.assertIn("待选表", guide)
        self.assertIn("打击事件位置与效果", guide)
        self.assertNotIn("数据集ID=", guide)

    def test_plan_guide_soft_need_without_entity_kind(self):
        ctx = _ctx(unresolvedNeeds=[], needs=[{
            "entityKind": "", "mode": "aggregate", "geo": "none",
            "question": "按任务统计架次", "datasetId": "", "datasetName": "",
            "resolved": False, "reason": "未限定实体语义，按目录选表"}])
        guide = prompts.format_skill_plan_guide(ctx)
        self.assertIn("未限定实体语义，按目录选表", guide)
        self.assertIn("按任务统计架次", guide)

    def test_page_guide_carries_presentation_and_narrative(self):
        guide = prompts.format_skill_page_guide(_ctx())
        self.assertIn("呈现偏好", guide)
        self.assertIn("叙事要点", guide)
        self.assertIn("区块剧本", guide)
        self.assertIn("spec.playback", guide)
        self.assertIn("推荐图表类型：bar、pie", guide)
        self.assertIn("交互要求", guide)

    def test_page_guide_without_optional_fields(self):
        guide = prompts.format_skill_page_guide(_ctx(
            skill=_skill(playback=False, interactions=[], recommended_chart_types=[])))
        self.assertNotIn("spec.playback", guide)
        self.assertNotIn("交互要求", guide)

    def test_plan_messages_appended_when_applied(self):
        messages = prompts.build_plan_messages("分析态势", CATALOG, "", _ctx())
        content = messages[0]["content"]
        self.assertTrue(content.startswith(prompts.PLANNER_SYSTEM_SUFFIX))
        self.assertIn("ds_track", content)
        # 数据集目录仍然在消息末尾（技能指南插在系统提示与目录之间）
        self.assertTrue(content.endswith(CATALOG))
        # 用户消息不因技能而改变
        self.assertEqual("用户问题：分析态势", messages[1]["content"])

    def test_page_messages_appended_when_applied(self):
        plan = {"title": "标题", "sections": [], "interactions": []}
        bundle = {"question": "问题", "generatedAt": "now", "datasets": []}
        messages = prompts.build_page_messages("问题", plan, bundle, 20, _ctx())
        content = messages[0]["content"]
        self.assertTrue(content.startswith(prompts.PAGE_SYSTEM_HEADER))
        self.assertIn("叙事要点", content)


if __name__ == "__main__":
    unittest.main()
