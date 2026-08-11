from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

import config
import skills.preflight as preflight_module
import skills.store as skill_store
from skills import (
    SkillCatalogError,
    create_skill_definition,
    get_skill,
    list_skill_versions,
    preflight_skill,
    publish_skill_definition,
    recommend_skills,
    rollback_skill_definition,
    update_skill_definition,
)


class SituationSkillGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = config.SITUATION_SKILL_DB
        config.SITUATION_SKILL_DB = f"{self.tempdir.name}/skills.sqlite3"
        skill_store._SCHEMA_READY = False
        preflight_module._SOURCE_CACHE.update(expires=0.0, tables=set(), adminReady=False)

    def tearDown(self):
        config.SITUATION_SKILL_DB = self.original_db
        skill_store._SCHEMA_READY = False
        self.tempdir.cleanup()

    @staticmethod
    def custom_definition():
        source = get_skill("force-readiness")
        assert source is not None
        definition = {
            key: value for key, value in source.items()
            if key in {
                "name", "description", "category", "triggers", "recommendedQuestions",
                "inputHints", "steps", "dataSources", "chartTypes", "mapLayerTypes",
                "focusMetrics", "analysisGoal", "featured",
            }
        }
        definition["name"] = "战备状态自定义检查"
        definition["featured"] = False
        return definition

    def test_custom_skill_lifecycle_versions_and_optimistic_revision(self):
        created = create_skill_definition(self.custom_definition(), "alice")
        self.assertEqual(created["status"], "draft")
        self.assertFalse(created["isBuiltIn"])

        published = publish_skill_definition(created["id"], "alice", "首次发布")
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["version"], 1)

        definition = self.custom_definition()
        definition["description"] = "更新后的描述"
        updated = update_skill_definition(
            created["id"], definition, "alice", expected_revision=published["revision"],
        )
        self.assertEqual(updated["status"], "draft")
        with self.assertRaises(SkillCatalogError):
            update_skill_definition(created["id"], definition, "alice", expected_revision=1)

        republished = publish_skill_definition(created["id"], "alice", "第二次发布")
        self.assertEqual(republished["version"], 2)
        versions = list_skill_versions(created["id"], "alice")
        self.assertEqual([item["version"] for item in versions], [2, 1])

        rolled_back = rollback_skill_definition(created["id"], 1, "alice")
        self.assertEqual(rolled_back["status"], "draft")
        self.assertEqual(rolled_back["description"], created["description"])

    def test_favorite_usage_and_context_improve_recommendation(self):
        custom = create_skill_definition(self.custom_definition(), "alice")
        custom = publish_skill_definition(custom["id"], "alice")
        skill_store.set_favorite("alice", custom["id"], True)
        skill_store.start_usage("r_test", "alice", custom["id"], "检查战备")
        skill_store.finish_usage("r_test", "ready")

        self.assertEqual(skill_store.list_favorite_ids("alice"), [custom["id"]])
        self.assertEqual(skill_store.usage_stats("alice")[custom["id"]]["successes"], 1)
        recommendations = recommend_skills(
            "",
            1,
            user_id="alice",
            favorite_ids=[custom["id"]],
            usage=skill_store.usage_stats("alice"),
            context={"scene": "战备状态"},
        )
        self.assertEqual(recommendations[0]["id"], custom["id"])
        self.assertIn("已收藏", recommendations[0]["recommendationReason"])

    @patch("skills.preflight._probe_health", return_value=True)
    @patch("skills.preflight.admin_client.list_datasets")
    def test_preflight_validates_parameters_and_registered_sources(self, list_datasets, _probe):
        skill = get_skill("force-readiness")
        assert skill is not None
        list_datasets.return_value = {
            "success": True,
            "datasets": [{"tableName": source} for source in skill["dataSources"]],
        }
        result = preflight_skill("force-readiness", "检查战备", {"区域": "A"})
        self.assertTrue(result["ready"])
        self.assertTrue(result["complete"])
        self.assertTrue(all(check["label"] for check in result["checks"]))

        invalid = preflight_skill("force-readiness", "检查战备", {"未定义参数": "x"})
        self.assertFalse(invalid["ready"])
        self.assertTrue(any("未定义参数" in error for error in invalid["errors"]))


if __name__ == "__main__":
    unittest.main()
