"""技能槽位解析与规划约束测试。

覆盖：实体语义槽位 → datasetId 的确定性解析（含地理能力过滤、字段角色排序、
无法解析时如实记入 unresolved）、技能区块约束校验、未套用技能时校验行为不变。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import planner, skill_catalog


def _schema(ds_id, name, entity_kind, coords=True, roles=()):
    """构造 /export/for-llm 形态的数据集（含数据集级与字段级语义注解）。"""
    fields = [{"column": "id", "type": "int", "isPrimaryKey": True}]
    if coords:
        fields.append({"column": "p_lng", "type": "double"})
        fields.append({"column": "p_lat", "type": "double"})
    for role in roles:
        fields.append({"column": f"f_{role}", "type": "varchar",
                       "semanticJson": json.dumps({"role": role}, ensure_ascii=False)})
    return {
        "datasetId": ds_id,
        "name": name,
        "tableName": f"t_{ds_id}",
        "semanticJson": json.dumps({"entityKind": entity_kind}, ensure_ascii=False),
        "fields": fields,
    }


def _meta(*schemas):
    return {"success": True, "data": {"schemas": list(schemas)}}


def _skill(needs, **overrides):
    data = dict(
        id="skill-a", name="技能甲", description="说明",
        triggers=["a", "b", "c"],
        needs=[skill_catalog.Need(**need) for need in needs],
    )
    data.update(overrides)
    return skill_catalog.Skill(**data)


def _ctx(skill, **overrides):
    ctx = {"id": skill.id, "applied": True, "matchedBy": "auto", "score": 0.9,
           "skill": skill, "needs": [], "unresolvedNeeds": []}
    ctx.update(overrides)
    return ctx


class ResolveSkillDatasetsTest(unittest.TestCase):

    def test_resolves_by_entity_kind(self):
        meta = _meta(_schema("ds_air", "机型统计表", "air"))
        skill = _skill([{"entity_kind": "air", "mode": "aggregate", "geo": "none",
                         "question": "统计在役与战损数量"}])
        needs, unresolved = planner.resolve_skill_datasets(meta, skill)
        self.assertEqual([], unresolved)
        self.assertEqual(1, len(needs))
        self.assertEqual("ds_air", needs[0]["datasetId"])
        self.assertEqual("机型统计表", needs[0]["datasetName"])
        self.assertEqual("aggregate", needs[0]["mode"])
        self.assertEqual("统计在役与战损数量", needs[0]["question"])

    def test_unresolved_when_entity_kind_absent(self):
        meta = _meta(_schema("ds_air", "机型统计表", "air"))
        skill = _skill([{"entity_kind": "base", "mode": "detail", "geo": "points",
                         "question": "基地位置"}])
        needs, unresolved = planner.resolve_skill_datasets(meta, skill)
        # 需求不丢弃：保留描述交由规划阶段按目录选表，避免技能的数据意图丢失
        self.assertEqual(1, len(needs))
        self.assertEqual("", needs[0]["datasetId"])
        self.assertFalse(needs[0]["resolved"])
        self.assertEqual("基地位置", needs[0]["question"])
        self.assertEqual(1, len(unresolved))
        self.assertIn("entityKind=base", unresolved[0])

    def test_soft_need_without_entity_kind(self):
        meta = _meta(_schema("ds_event", "打击事件表", "other"))
        skill = _skill([{"entity_kind": "", "mode": "detail", "geo": "points",
                         "question": "打击事件位置与效果"}])
        needs, unresolved = planner.resolve_skill_datasets(meta, skill)
        self.assertEqual([], unresolved)
        self.assertEqual(1, len(needs))
        self.assertEqual("", needs[0]["datasetId"])
        self.assertIn("按目录选表", needs[0]["reason"])
        self.assertEqual("打击事件位置与效果", needs[0]["question"])

    def test_geo_need_requires_coordinate_fields(self):
        meta = _meta(_schema("ds_air", "机型统计表", "air", coords=False))
        skill = _skill([{"entity_kind": "air", "mode": "detail", "geo": "tracks",
                         "question": "航迹明细"}])
        needs, unresolved = planner.resolve_skill_datasets(meta, skill)
        self.assertEqual(1, len(needs))
        self.assertEqual("", needs[0]["datasetId"])
        self.assertIn("需具备坐标", needs[0]["reason"])
        self.assertIn("需具备坐标", unresolved[0])

    def test_geo_need_ignores_non_coordinate_dataset(self):
        meta = _meta(_schema("ds_air_no_geo", "无坐标表", "air", coords=False),
                     _schema("ds_air_geo", "有坐标表", "air", coords=True))
        skill = _skill([{"entity_kind": "air", "mode": "detail", "geo": "points",
                         "question": "单位位置"}])
        needs, _ = planner.resolve_skill_datasets(meta, skill)
        self.assertEqual("ds_air_geo", needs[0]["datasetId"])

    def test_role_match_prefers_track_like_dataset(self):
        """同为 air 且都有坐标时，含 seq/time 角色的数据集优先用于航迹。"""
        meta = _meta(_schema("ds_plain", "普通位置表", "air"),
                     _schema("ds_track", "航迹表", "air", roles=("seq", "time")))
        skill = _skill([{"entity_kind": "air", "mode": "detail", "geo": "tracks",
                         "question": "航迹明细"}])
        needs, _ = planner.resolve_skill_datasets(meta, skill)
        self.assertEqual("ds_track", needs[0]["datasetId"])

    def test_multiple_needs_resolved_independently(self):
        meta = _meta(_schema("ds_air", "机型统计表", "air"),
                     _schema("ds_base", "基地表", "base"))
        skill = _skill([
            {"entity_kind": "air", "mode": "aggregate", "geo": "none", "question": "统计"},
            {"entity_kind": "base", "mode": "detail", "geo": "points", "question": "基地"},
        ])
        needs, unresolved = planner.resolve_skill_datasets(meta, skill)
        self.assertEqual(["ds_air", "ds_base"], [n["datasetId"] for n in needs])
        self.assertEqual([], unresolved)

    def test_none_skill_returns_empty(self):
        self.assertEqual(([], []), planner.resolve_skill_datasets(_meta(), None))

    def test_bad_meta_does_not_raise(self):
        skill = _skill([{"entity_kind": "air", "mode": "aggregate", "geo": "none",
                         "question": "统计"}])
        needs, unresolved = planner.resolve_skill_datasets(None, skill)
        self.assertEqual(1, len(needs))
        self.assertFalse(needs[0]["resolved"])
        self.assertEqual(1, len(unresolved))


class SkillConstraintValidationTest(unittest.TestCase):

    def setUp(self):
        self.skill = _skill(
            [{"entity_kind": "air", "mode": "detail", "geo": "points", "question": "位置"}],
            required_sections=["kpi", "chart", "map", "text"],
            map_modes=["tracks", "points"],
        )

    def _plan(self, kinds):
        return {
            "intent": "data_page",
            "title": "标题",
            "subQuestions": [{"id": "q1", "datasetId": "ds_air", "question": "位置",
                              "mode": "detail", "geo": "points"}],
            "sections": [
                {"id": f"s{i}", "kind": kind, "title": kind, "ref": "q1"}
                for i, kind in enumerate(kinds, 1)
            ],
        }

    def test_valid_plan_passes_with_skill(self):
        plan = self._plan(["kpi", "chart", "map", "text"])
        self.assertIsNone(planner._validate(plan, {"ds_air"}, {"ds_air"}, _ctx(self.skill)))

    def test_missing_required_section_rejected(self):
        plan = self._plan(["kpi", "chart", "text"])
        err = planner._validate(plan, {"ds_air"}, {"ds_air"}, _ctx(self.skill))
        self.assertIsNotNone(err)
        self.assertIn("技能「技能甲」", err)
        self.assertIn("map", err)

    def test_missing_map_when_map_modes_declared(self):
        skill = _skill([{"entity_kind": "air", "mode": "detail", "geo": "points",
                         "question": "位置"}],
                       required_sections=["kpi", "chart", "text"],
                       map_modes=["points"])
        plan = self._plan(["kpi", "chart", "text"])
        err = planner._validate(plan, {"ds_air"}, {"ds_air"}, _ctx(skill))
        self.assertIsNotNone(err)
        self.assertIn("要求包含地图区块", err)

    def test_same_plan_passes_without_skill_context(self):
        """未套用技能时，同样的规划不得被技能约束拦下（零回归）。"""
        plan = self._plan(["kpi", "chart", "text"])
        self.assertIsNone(planner._validate(plan, {"ds_air"}, {"ds_air"}, None))
        self.assertIsNone(planner._validate(plan, {"ds_air"}, {"ds_air"}))
        self.assertIsNone(planner._validate(
            plan, {"ds_air"}, {"ds_air"}, {"applied": False, "skill": self.skill}))

    def test_geo_rule_still_applies_with_skill(self):
        """通用规则（地图 ref 必须有 geo）在技能场景下依然生效。"""
        plan = self._plan(["kpi", "chart", "map", "text"])
        plan["subQuestions"][0]["geo"] = "none"
        err = planner._validate(plan, {"ds_air"}, {"ds_air"}, _ctx(self.skill))
        self.assertIsNotNone(err)
        self.assertIn("未声明 geo", err)


if __name__ == "__main__":
    unittest.main()
