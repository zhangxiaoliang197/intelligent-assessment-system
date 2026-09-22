"""技能目录（SKILL.md）加载、静态校验与缓存行为测试。

覆盖：front matter 必填校验、目录名与 id 一致、正文必备四节、取数剧本 need 解析、
红线机检（写死数据源标识 / 数值阈值一律拒绝）、缓存指纹变更触发重载。
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import cache_registry
from agent import skill_catalog

VALID_TEMPLATE = """---
id: {sid}
name: 空军力量态势
description: 红蓝双方空军兵力对比、战损与航迹动态演示
category: 态势分析
order: 10
triggers:
  - 分析红蓝方空军力量态势
  - 对比双方在役与战损飞机数量
  - 我方战机飞行轨迹与动态演示
requiredEntityKinds: [air]
recommendedChartTypes: [bar, pie]
mapModes: [tracks, points]
playback: true
requiredSections: [kpi, chart, map, text]
focusMetrics: [在役数量, 战损数量]
---

## 取数剧本
- need: entityKind=air, mode=aggregate, question=按机型与阵营统计在役与战损数量
- need: entityKind=air, mode=detail, geo=tracks, question=逐架次航迹明细

## 区块剧本
kpi → chart → map → timeline → text

## 呈现偏好
- 地图开启回放，能力圈随飞机移动

## 叙事要点
- 先给总量对比，再给结构性差异
"""


class _SkillDirCase(unittest.TestCase):
    """在临时目录里造技能，避免碰真实技能目录。"""

    def setUp(self):
        self._saved_dir = config.IPAGE_SKILLS_DIR
        self.tmp = tempfile.mkdtemp(prefix="ipage_skills_")
        config.IPAGE_SKILLS_DIR = self.tmp
        skill_catalog.clear_cache()

    def tearDown(self):
        config.IPAGE_SKILLS_DIR = self._saved_dir
        skill_catalog.clear_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, dir_name: str, content: str) -> None:
        path = os.path.join(self.tmp, dir_name)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, skill_catalog.SKILL_FILE_NAME), "w", encoding="utf-8") as fh:
            fh.write(content)

    def _valid(self, sid: str = "air-power-situation") -> str:
        return VALID_TEMPLATE.format(sid=sid)

    def _load_one(self, dir_name: str, content: str):
        """写入并加载，返回 (技能或 None, 错误列表)。"""
        self._write(dir_name, content)
        skill_catalog.clear_cache()
        skill, errors = skill_catalog._parse_skill(
            os.path.join(self.tmp, dir_name), dir_name)
        return skill, errors


class LoadValidSkillTest(_SkillDirCase):

    def test_valid_skill_loads_with_metadata_and_needs(self):
        self._write("air-power-situation", self._valid())
        skill_catalog.clear_cache()
        skills = skill_catalog.load_skills()
        self.assertEqual(1, len(skills))
        skill = skills[0]
        self.assertEqual("air-power-situation", skill.id)
        self.assertEqual("空军力量态势", skill.name)
        self.assertTrue(skill.playback)
        self.assertEqual(["air"], skill.required_entity_kinds)
        self.assertEqual(2, len(skill.needs))
        self.assertEqual("air", skill.needs[0].entity_kind)
        self.assertEqual("aggregate", skill.needs[0].mode)
        self.assertEqual("tracks", skill.needs[1].geo)
        self.assertEqual(12, len(skill.version))
        # 语料 = 名称 + 说明 + 3 条 triggers
        self.assertEqual(5, len(skill.corpus))

    def test_get_skill_by_id(self):
        self._write("air-power-situation", self._valid())
        skill_catalog.clear_cache()
        self.assertIsNotNone(skill_catalog.get_skill("air-power-situation"))
        self.assertIsNone(skill_catalog.get_skill("not-exist"))

    def test_meta_does_not_leak_body(self):
        self._write("air-power-situation", self._valid())
        skill_catalog.clear_cache()
        meta = skill_catalog.load_skills()[0].to_meta()
        self.assertNotIn("body_sections", meta)
        self.assertNotIn("needs", meta)
        self.assertEqual(3, meta["triggerCount"])


class FrontMatterValidationTest(_SkillDirCase):

    def test_missing_front_matter(self):
        skill, errors = self._load_one("air-power-situation", "## 取数剧本\n- need: ...\n")
        self.assertIsNone(skill)
        self.assertTrue(any("front matter" in e for e in errors))

    def test_unclosed_front_matter(self):
        skill, errors = self._load_one("air-power-situation", "---\nid: x\n")
        self.assertIsNone(skill)
        self.assertTrue(any("未闭合" in e for e in errors))

    def test_id_must_equal_dir_name(self):
        skill, errors = self._load_one("other-dir", self._valid())
        self.assertIsNone(skill)
        self.assertTrue(any("与目录名" in e for e in errors))

    def test_too_few_triggers(self):
        content = self._valid().replace(
            "  - 我方战机飞行轨迹与动态演示\n", "")
        skill, errors = self._load_one("air-power-situation", content)
        self.assertIsNone(skill)
        self.assertTrue(any("triggers 至少需要" in e for e in errors))

    def test_missing_required_body_section(self):
        content = self._valid().replace("## 叙事要点\n- 先给总量对比，再给结构性差异\n", "")
        skill, errors = self._load_one("air-power-situation", content)
        self.assertIsNone(skill)
        self.assertTrue(any("叙事要点" in e for e in errors))


class DomainValueValidationTest(_SkillDirCase):

    def _break(self, old: str, new: str):
        return self._load_one("air-power-situation", self._valid().replace(old, new))

    def test_invalid_chart_type(self):
        skill, errors = self._break("recommendedChartTypes: [bar, pie]",
                                    "recommendedChartTypes: [bar, sankey]")
        self.assertIsNone(skill)
        self.assertTrue(any("recommendedChartTypes=sankey" in e for e in errors))

    def test_invalid_map_mode(self):
        skill, errors = self._break("mapModes: [tracks, points]",
                                    "mapModes: [tracks, heatmap]")
        self.assertIsNone(skill)
        self.assertTrue(any("mapModes=heatmap" in e for e in errors))

    def test_invalid_required_section(self):
        skill, errors = self._break("requiredSections: [kpi, chart, map, text]",
                                    "requiredSections: [kpi, gauge]")
        self.assertIsNone(skill)
        self.assertTrue(any("requiredSections=gauge" in e for e in errors))

    def test_invalid_entity_kind(self):
        skill, errors = self._break("requiredEntityKinds: [air]",
                                    "requiredEntityKinds: [aircraft]")
        self.assertIsNone(skill)
        self.assertTrue(any("requiredEntityKinds=aircraft" in e for e in errors))

    def test_need_entity_kind_invalid(self):
        skill, errors = self._break("entityKind=air, mode=aggregate",
                                    "entityKind=aircraft, mode=aggregate")
        self.assertIsNone(skill)
        self.assertTrue(any("entityKind=aircraft 非法" in e for e in errors))

    def test_geo_requires_detail_mode(self):
        skill, errors = self._break("entityKind=air, mode=detail, geo=tracks",
                                    "entityKind=air, mode=aggregate, geo=tracks")
        self.assertIsNone(skill)
        self.assertTrue(any("必须配 mode=detail" in e for e in errors))

    def test_need_entity_kind_optional(self):
        """entityKind 可省略：表示不限定实体语义、由规划阶段按目录选表。"""
        content = self._valid().replace("entityKind=air, mode=aggregate", "mode=aggregate")
        skill, errors = self._load_one("air-power-situation", content)
        self.assertEqual([], errors)
        self.assertIsNotNone(skill)
        self.assertEqual(2, len(skill.needs))
        self.assertEqual("", skill.needs[0].entity_kind)
        self.assertEqual("air", skill.needs[1].entity_kind)

    def test_need_without_question_rejected(self):
        skill, errors = self._break(", question=按机型与阵营统计在役与战损数量\n", "\n")
        self.assertIsNone(skill)
        self.assertTrue(any("缺少 question" in e for e in errors))


class RedlineValidationTest(_SkillDirCase):
    """红线：写死数据源或数值的技能必须被拒绝加载。"""

    def test_dataset_id_rejected(self):
        skill, errors = self._break_text("数据源 ds_aircraft_stat 已配置")
        self.assertIsNone(skill)
        self.assertTrue(any("数据集 ID" in e for e in errors))

    def test_mock_table_rejected(self):
        skill, errors = self._break_text("读取 mock_aircraft 表")
        self.assertIsNone(skill)
        self.assertTrue(any("物理表名" in e for e in errors))

    def test_uuid_rejected(self):
        skill, errors = self._break_text("数据集 550e8400-e29b-41d4-a716-446655440000")
        self.assertIsNone(skill)
        self.assertTrue(any("UUID" in e for e in errors))

    def test_percent_rejected(self):
        skill, errors = self._break_text("战损率超过 30% 时告警")
        self.assertIsNone(skill)
        self.assertTrue(any("硬编码百分比" in e for e in errors))

    def test_numeric_threshold_rejected(self):
        skill, errors = self._break_text("数量大于 50 的目标单独列出")
        self.assertIsNone(skill)
        self.assertTrue(any("硬编码数值阈值" in e for e in errors))

    def _break_text(self, extra_line: str):
        content = self._valid().replace(
            "## 叙事要点", f"## 叙事要点\n- {extra_line}\n")
        return self._load_one("air-power-situation", content)


class CacheBehaviourTest(_SkillDirCase):

    def test_cache_reused_until_files_change(self):
        self._write("air-power-situation", self._valid())
        skill_catalog.clear_cache()
        first = skill_catalog.load_skills()
        second = skill_catalog.load_skills()
        self.assertIs(first[0], second[0])  # 命中缓存，同一对象

    def test_file_change_rebuilds_cache(self):
        self._write("air-power-situation", self._valid())
        skill_catalog.clear_cache()
        first = skill_catalog.load_skills()
        self._write("air-power-situation",
                    self._valid().replace("name: 空军力量态势", "name: 空军兵力态势"))
        second = skill_catalog.load_skills()
        self.assertEqual("空军兵力态势", second[0].name)
        self.assertNotEqual(first[0].content_hash, second[0].content_hash)

    def test_invalid_skill_skipped_without_breaking_others(self):
        self._write("air-power-situation", self._valid())
        self._write("bad-skill", "## 缺 front matter\n")
        skill_catalog.clear_cache()
        skills = skill_catalog.load_skills()
        self.assertEqual(["air-power-situation"], [s.id for s in skills])

    def test_registered_in_cache_registry(self):
        names = cache_registry.registered_caches()
        self.assertIn(skill_catalog.SKILL_CACHE_NAME, names)

    def test_clear_cache_via_registry(self):
        self._write("air-power-situation", self._valid())
        skill_catalog.clear_cache()
        skill_catalog.load_skills()
        cleared = cache_registry.invalidate()
        self.assertEqual(1, cleared[skill_catalog.SKILL_CACHE_NAME])


if __name__ == "__main__":
    unittest.main()
