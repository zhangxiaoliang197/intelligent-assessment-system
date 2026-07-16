import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import evaluation_api
from evaluation_api import (
    EvaluationSkillPayload,
    _bounded_execution_result,
    _validate_skill_payload,
)


class EvaluationSkillValidationTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_server_dataset_name_and_preserves_step_order(self):
        datasets = [
            {"id": "dataset-one", "name": "Server First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Server Second", "tableName": "table_two"},
        ]
        payload = EvaluationSkillPayload(
            name="  Ordered evaluation  ",
            description="  Query in order  ",
            databaseId="database-one",
            steps=[
                {"datasetId": "dataset-two", "datasetName": "Stale", "instruction": "  Second first  "},
                {"datasetId": "dataset-one", "datasetName": "Stale", "instruction": "Then first"},
            ],
        )

        with patch("evaluation_api.fetch_datasets_for_database", return_value=datasets):
            result = await _validate_skill_payload(payload)

        self.assertEqual(result["name"], "Ordered evaluation")
        self.assertEqual(
            [step["datasetId"] for step in result["steps"]],
            ["dataset-two", "dataset-one"],
        )
        self.assertEqual(result["steps"][0]["datasetName"], "Server Second")
        self.assertEqual(result["steps"][0]["instruction"], "Second first")
        self.assertFalse(result["steps"][0]["dependsOnPrevious"])
        self.assertTrue(result["steps"][1]["dependsOnPrevious"])
        self.assertEqual(result["steps"][1]["onDependencyFailure"], "skip")
        self.assertTrue(result["steps"][1]["requireNonEmpty"])
        self.assertEqual(result["steps"][1]["onEmpty"], "continue")

    async def test_rejects_dataset_outside_selected_database(self):
        payload = EvaluationSkillPayload(
            name="Invalid scope",
            databaseId="database-one",
            steps=[
                {"datasetId": "dataset-other", "instruction": "Query it"},
            ],
        )

        with patch("evaluation_api.fetch_datasets_for_database", return_value=[]):
            with self.assertRaisesRegex(ValueError, "不属于当前数据源"):
                await _validate_skill_payload(payload)

    async def test_rejects_dataset_without_physical_table(self):
        payload = EvaluationSkillPayload(
            name="No table",
            databaseId="database-one",
            steps=[
                {"datasetId": "dataset-one", "instruction": "Query it"},
            ],
        )
        datasets = [{"id": "dataset-one", "name": "Logical only", "tableName": ""}]

        with patch("evaluation_api.fetch_datasets_for_database", return_value=datasets):
            with self.assertRaisesRegex(ValueError, "未关联物理表"):
                await _validate_skill_payload(payload)

    async def test_rejects_more_than_twenty_steps_before_remote_lookup(self):
        payload = EvaluationSkillPayload(
            name="Too many",
            databaseId="database-one",
            steps=[
                {"datasetId": f"dataset-{index}", "instruction": "Query it"}
                for index in range(21)
            ],
        )

        with patch("evaluation_api.fetch_datasets_for_database") as fetch:
            with self.assertRaisesRegex(ValueError, "最多支持 20"):
                await _validate_skill_payload(payload)
            fetch.assert_not_called()

    def test_bounds_persisted_skill_results_without_losing_execution_metadata(self):
        rows = [{"id": index} for index in range(150)]
        result = _bounded_execution_result({
            "type": "skill_query",
            "executionSummary": {"status": "completed", "truncatedSteps": 1},
            "queryResults": [{"order": 1, "rows": rows, "truncated": True}],
            "final_answer": "A" * 60000,
        })

        self.assertEqual(len(result["queryResults"][0]["rows"]), 100)
        self.assertTrue(result["queryResults"][0]["truncated"])
        self.assertEqual(result["executionSummary"]["truncatedSteps"], 1)
        self.assertEqual(len(result["final_answer"]), 50000)

    def test_legacy_skill_migration_is_idempotent_and_preserves_id(self):
        original_checked = evaluation_api._skill_migration_checked
        original_legacy = evaluation_api._legacy_eval_skills
        evaluation_api._skill_migration_checked = False
        evaluation_api._legacy_eval_skills = [{
            "id": "skill-legacy01",
            "name": "Legacy",
            "databaseId": "database-one",
            "steps": [{"datasetId": "dataset-one", "instruction": "Query"}],
        }]
        try:
            with patch("evaluation_api.fetch_evaluation_skills", return_value={
                "success": True,
                "skills": [],
            }), patch("evaluation_api.create_evaluation_skill", return_value={
                "success": True,
                "skill": {"id": "skill-legacy01"},
            }) as create:
                first = evaluation_api._ensure_legacy_skills_migrated()
                second = evaluation_api._ensure_legacy_skills_migrated()

            self.assertTrue(first["success"])
            self.assertTrue(second["success"])
            create.assert_called_once()
            self.assertEqual(create.call_args.args[0]["id"], "skill-legacy01")
        finally:
            evaluation_api._skill_migration_checked = original_checked
            evaluation_api._legacy_eval_skills = original_legacy


if __name__ == "__main__":
    unittest.main()
