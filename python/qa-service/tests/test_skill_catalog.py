"""Unit tests for the built-in evaluation Skill catalog.

These tests deliberately use only the Python standard library so they can run
in an offline deployment without installing a separate test framework.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


QA_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(QA_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(QA_SERVICE_ROOT))

from agents.skill_catalog import (  # noqa: E402
    list_builtin_skills,
    recommend_skills,
    resolve_skill_datasets,
    skill_availability,
)


def _step(step_id: str, *keywords: str) -> dict:
    """Build the smallest valid dataset step needed by resolver tests."""
    return {
        "id": step_id,
        "name": f"{step_id} step",
        "description": f"Resolve the {step_id} dataset",
        "datasetKeywords": list(keywords),
    }


class SkillCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skills = list_builtin_skills()

    def test_catalog_contains_exactly_fifteen_unique_well_formed_skills(self) -> None:
        self.assertEqual(15, len(self.skills))

        skill_ids = [skill["id"] for skill in self.skills]
        self.assertEqual(len(skill_ids), len(set(skill_ids)), "Skill IDs must be unique")

        required_skill_fields = {
            "id",
            "name",
            "description",
            "category",
            "triggers",
            "recommendedQuestions",
            "steps",
            "outputInstruction",
        }
        required_step_fields = {"id", "name", "description", "datasetKeywords"}

        for skill in self.skills:
            with self.subTest(skill=skill.get("id")):
                self.assertTrue(required_skill_fields.issubset(skill))
                self.assertRegex(skill["id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                for field in ("name", "description", "category", "outputInstruction"):
                    self.assertIsInstance(skill[field], str)
                    self.assertTrue(skill[field].strip())

                self.assertIsInstance(skill["triggers"], list)
                self.assertTrue(skill["triggers"])
                self.assertTrue(all(isinstance(item, str) and item.strip() for item in skill["triggers"]))
                self.assertIsInstance(skill["recommendedQuestions"], list)
                self.assertTrue(skill["recommendedQuestions"])
                self.assertTrue(
                    all(isinstance(item, str) and item.strip() for item in skill["recommendedQuestions"])
                )

                self.assertIsInstance(skill["steps"], list)
                self.assertTrue(skill["steps"])
                step_ids = []
                for step in skill["steps"]:
                    self.assertTrue(required_step_fields.issubset(step))
                    self.assertTrue(all(step[field] for field in required_step_fields))
                    self.assertIsInstance(step["datasetKeywords"], list)
                    self.assertTrue(
                        all(
                            isinstance(keyword, str) and keyword.strip()
                            for keyword in step["datasetKeywords"]
                        )
                    )
                    step_ids.append(step["id"])
                self.assertEqual(len(step_ids), len(set(step_ids)), "Step IDs must be unique per Skill")

    def test_recommendation_for_air_superiority_selects_the_matching_skill(self) -> None:
        recommendations = recommend_skills(
            "请对比目标区域红蓝双方的制空权和空中优势",
            limit=3,
        )

        self.assertTrue(recommendations)
        self.assertEqual("air-superiority-comparison", recommendations[0]["id"])
        self.assertIn("制空权", recommendations[0]["matchedTriggers"])
        self.assertGreater(recommendations[0]["recommendationScore"], 0)

    def test_dataset_resolution_preserves_declared_step_order(self) -> None:
        skill = {
            "steps": [
                _step("loss", "combat_loss"),
                _step("result", "combat_result"),
                _step("resource", "resource_consume"),
            ]
        }
        datasets = [
            {"id": "ds-resource", "name": "资源消耗", "tableName": "resource_consume"},
            {"id": "ds-loss", "name": "战损明细", "tableName": "combat_loss"},
            {"id": "ds-result", "name": "战果明细", "tableName": "combat_result"},
        ]

        plan = resolve_skill_datasets(skill, datasets)

        self.assertEqual([1, 2, 3], [item["sequence"] for item in plan])
        self.assertEqual(["loss", "result", "resource"], [item["step"]["id"] for item in plan])
        self.assertEqual(
            ["combat_loss", "combat_result", "resource_consume"],
            [item["dataset"]["tableName"] for item in plan],
        )

    def test_exact_table_name_match_wins_over_partial_or_name_matches(self) -> None:
        skill = {"steps": [_step("loss", "combat_loss")]}
        datasets = [
            {"id": "partial", "name": "A", "tableName": "combat_loss_archive"},
            {"id": "name-only", "name": "combat_loss", "tableName": "loss_records"},
            {"id": "exact", "name": "Z", "tableName": "combat_loss"},
        ]

        plan = resolve_skill_datasets(skill, datasets)

        self.assertEqual("exact", plan[0]["dataset"]["id"])
        self.assertEqual(120, plan[0]["score"])
        self.assertEqual("combat_loss", plan[0]["matchedKeyword"])

    def test_unmatched_step_is_not_guessed_from_unrelated_datasets(self) -> None:
        skill = {"steps": [_step("air", "air_overall", "制空权")]}
        unrelated = [
            {
                "id": "inventory",
                "name": "后勤库存",
                "tableName": "supply_inventory",
                "description": "记录仓储物资余量",
            },
            {
                "id": "maintenance",
                "name": "维修工单",
                "tableName": "maintenance_order",
                "description": "装备检修记录",
            },
        ]

        plan = resolve_skill_datasets(skill, unrelated)

        self.assertEqual(1, len(plan))
        self.assertIsNone(plan[0]["dataset"])
        self.assertEqual(0, plan[0]["score"])
        self.assertEqual("", plan[0]["matchedKeyword"])

    def test_short_english_keywords_only_match_identifier_tokens(self) -> None:
        false_positive_cases = [
            (_step("command", "order"), {"id": "border", "name": "边界", "tableName": "border_status"}),
            (_step("force", "unit"), {"id": "ammo", "name": "弹药库存", "tableName": "ammunition_inventory"}),
        ]
        for step, dataset in false_positive_cases:
            with self.subTest(keyword=step["datasetKeywords"][0], table=dataset["tableName"]):
                plan = resolve_skill_datasets({"steps": [step]}, [dataset])
                self.assertIsNone(plan[0]["dataset"])

    def test_availability_reports_partial_and_empty_match_counts(self) -> None:
        skill = {
            "steps": [
                _step("loss", "combat_loss"),
                _step("result", "combat_result"),
                _step("resource", "resource_consume"),
            ]
        }
        partial_datasets = [
            {"id": "ds-result", "name": "战果明细", "tableName": "combat_result"},
            {"id": "ds-loss", "name": "战损明细", "tableName": "combat_loss"},
        ]

        partial = skill_availability(skill, partial_datasets)
        self.assertEqual(2, partial["matchedSteps"])
        self.assertEqual(3, partial["totalSteps"])
        self.assertTrue(partial["available"])
        self.assertFalse(partial["complete"])
        self.assertEqual([True, True, False], [item["matched"] for item in partial["datasetPlan"]])
        self.assertEqual([1, 2, 3], [item["sequence"] for item in partial["datasetPlan"]])

        empty = skill_availability(skill, [])
        self.assertEqual(0, empty["matchedSteps"])
        self.assertEqual(3, empty["totalSteps"])
        self.assertFalse(empty["available"])
        self.assertFalse(empty["complete"])
        self.assertEqual([False, False, False], [item["matched"] for item in empty["datasetPlan"]])


if __name__ == "__main__":
    unittest.main()
