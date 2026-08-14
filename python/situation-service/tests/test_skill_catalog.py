from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import orchestrator
import skills.catalog as skill_catalog
from skills import (
    SkillCatalogError,
    build_skill_context,
    catalog_summary,
    get_skill,
    list_skills,
    recommend_skills,
)


class SituationSkillCatalogTests(unittest.TestCase):
    def test_catalog_and_default_markdown_storage_are_checkout_relative(self):
        """A fresh clone must not depend on a developer-specific absolute path."""

        service_directory = Path(skill_catalog.__file__).resolve().parent.parent
        self.assertEqual(
            service_directory / "config" / "situation_skills.json",
            skill_catalog._CATALOG_PATH,
        )
        self.assertTrue(skill_catalog._CATALOG_PATH.is_file())
        with patch.dict(os.environ, {"SITUATION_SKILL_MD_OVERRIDE_DIR": ""}):
            self.assertEqual(
                service_directory / "data" / "situation-skill-markdown-overrides",
                skill_catalog.get_markdown_override_directory(),
            )

    def test_catalog_has_30_valid_skills_in_project_categories(self):
        summary = catalog_summary()
        self.assertGreaterEqual(summary["total"], 30)
        self.assertEqual(sum(item["count"] for item in summary["categories"]), summary["total"])
        self.assertGreaterEqual(len(summary["categories"]), 7)

        skills = list_skills(limit=100)
        builtins = [skill for skill in skills if skill.get("isBuiltIn")]
        self.assertEqual(len({skill["id"] for skill in builtins}), 30)
        self.assertTrue(all(len(skill["steps"]) >= 2 for skill in skills))
        self.assertTrue(all(skill["chartTypes"] for skill in skills))
        self.assertTrue(all(skill["mapLayerTypes"] for skill in skills))

    def test_search_filters_name_trigger_metric_and_category(self):
        self.assertEqual(list_skills(query="弹药库存")[0]["id"], "ammunition-inventory")
        self.assertEqual(list_skills(query="覆盖盲区")[0]["id"], "recon-warning-coverage")
        readiness = list_skills(category="战备保障", limit=100)
        self.assertEqual(len(readiness), 7)
        self.assertTrue(all(skill["category"] == "战备保障" for skill in readiness))

    def test_recommendation_is_explainable_and_fills_requested_limit(self):
        recommendations = recommend_skills("分析区域威胁热力和高威胁目标", 3)
        self.assertEqual(len(recommendations), 3)
        self.assertEqual(recommendations[0]["id"], "regional-threat-heatmap")
        self.assertIn("威胁热力", recommendations[0]["matchedTriggers"])
        self.assertTrue(recommendations[0]["recommendationReason"])
        self.assertEqual(recommend_skills("看一下战备", 1)[0]["id"], "force-readiness")

    def test_build_context_contains_auditable_plan_and_safe_parameters(self):
        context = build_skill_context(
            "force-readiness",
            "评估 A 区域战备",
            {"区域": "A", "单位": "一营"},
        )
        self.assertEqual(context["skillName"], "部队战备状态分析")
        self.assertEqual(len(context["executionPlan"]), 3)
        self.assertIn("评估 A 区域战备", context["instruction"])
        self.assertEqual(context["parameters"]["区域"], "A")

        with self.assertRaises(SkillCatalogError):
            build_skill_context("force-readiness", "test", {"bad": {"nested": True}})
        with self.assertRaises(SkillCatalogError):
            build_skill_context("missing-skill", "test")

    def test_each_skill_can_build_an_execution_context(self):
        for skill in list_skills(limit=100):
            with self.subTest(skill=skill["id"]):
                context = build_skill_context(skill["id"], "")
                self.assertEqual(context["skillId"], skill["id"])
                self.assertTrue(context["query"])
                self.assertEqual(context["chartTypes"], skill["chartTypes"])


class SituationSkillOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_skill_lookup_returns_copy(self):
        skill = get_skill("force-readiness")
        self.assertIsNotNone(skill)
        assert skill is not None
        skill["name"] = "mutated"
        self.assertEqual(get_skill("force-readiness")["name"], "部队战备状态分析")


if __name__ == "__main__":
    unittest.main()
