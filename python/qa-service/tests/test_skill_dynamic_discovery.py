import os
import sys
import unittest
from unittest.mock import patch


SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from agents.skill_catalog import resolve_skill_datasets, skill_availability  # noqa: E402
from agents.skill_runner import _resolve_runtime_datasets  # noqa: E402
from agents.tools import fetch_skill_datasets_for_database  # noqa: E402


class SkillDynamicDiscoveryTests(unittest.TestCase):
    def test_live_tables_fill_an_empty_managed_dataset_catalog(self):
        def fake_get(path, timeout=30):
            if path == "dataset/list":
                return {"success": True, "datasets": []}
            self.assertIn("database/db-live/tables?includeColumns=true", path)
            return {
                "success": True,
                "databaseType": "driver_03",
                "databaseProductName": "Oracle",
                "databaseProductVersion": "19c",
                "identifierQuoteString": "\"",
                "tables": [{
                    "tableName": "INNER_NET_RECORD_2026",
                    "columns": [{"columnName": "毁伤数量", "comment": "目标摧毁数"}],
                }],
            }

        with patch("agents.tools._api_get", side_effect=fake_get):
            datasets = fetch_skill_datasets_for_database("db-live", strict=True)

        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0]["tableName"], "INNER_NET_RECORD_2026")
        self.assertTrue(datasets[0]["isLiveTable"])
        self.assertTrue(datasets[0]["id"].startswith("live-"))
        self.assertEqual("Oracle", datasets[0]["databaseProductName"])
        self.assertEqual("19c", datasets[0]["databaseProductVersion"])

    def test_column_comments_match_without_a_fixed_table_name(self):
        skill = {"steps": [{
            "id": "result",
            "name": "核验战果",
            "description": "统计摧毁情况",
            "datasetKeywords": ["摧毁"],
        }]}
        datasets = [{
            "id": "live-1",
            "name": "T_001",
            "tableName": "T_001",
            "columns": [{"columnName": "value_a", "comment": "摧毁目标数量"}],
            "isLiveTable": True,
        }]

        plan = resolve_skill_datasets(skill, datasets)
        self.assertEqual(plan[0]["dataset"]["tableName"], "T_001")

    def test_stale_exact_binding_falls_back_to_current_metadata(self):
        skill = {"steps": [{
            "id": "result",
            "name": "核验战果",
            "description": "统计摧毁情况",
            "datasetId": "dataset-from-another-database",
            "datasetKeywords": ["摧毁"],
        }]}
        datasets = [{
            "id": "current-live-table",
            "name": "当前表",
            "tableName": "CURRENT_TABLE",
            "columns": [{"columnName": "destroyed", "comment": "摧毁数量"}],
        }]

        plan = resolve_skill_datasets(skill, datasets)
        self.assertEqual(plan[0]["dataset"]["id"], "current-live-table")

    def test_catalog_marks_real_tables_as_runtime_selectable(self):
        skill = {"steps": [{
            "id": "unknown",
            "name": "业务步骤",
            "description": "内网业务语义",
            "datasetKeywords": ["完全不同的语义"],
        }]}
        availability = skill_availability(
            skill,
            [{"id": "live-1", "name": "X1", "tableName": "X1"}],
        )
        self.assertTrue(availability["available"])
        self.assertTrue(availability["runtimeSelectable"])
        self.assertEqual(availability["matchedSteps"], 0)


class SkillRuntimeTableSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_selection_is_limited_to_actual_table_names(self):
        skill = {
            "id": "dynamic-test",
            "name": "动态匹配",
            "description": "按真实字段匹配",
            "steps": [{
                "id": "result",
                "name": "查询完成情况",
                "description": "统计任务完成情况",
                "datasetKeywords": ["任务完成"],
            }],
        }
        datasets = [{
            "id": "live-actual",
            "name": "X_42",
            "tableName": "X_42",
            "columns": [{"columnName": "done_flag", "comment": "是否完成任务"}],
            "isLiveTable": True,
        }]
        plan = resolve_skill_datasets(skill, datasets)
        self.assertIsNone(plan[0]["dataset"])

        async def fake_llm(_system, _user):
            return '{"matches":[{"stepId":"result","tableName":"X_42"}]}'

        resolved = await _resolve_runtime_datasets(
            skill=skill,
            plan=plan,
            datasets=datasets,
            question="分析任务完成率",
            llm_call_fn=fake_llm,
        )
        self.assertEqual(resolved[0]["dataset"]["tableName"], "X_42")
        self.assertEqual(resolved[0]["matchedKeyword"], "runtime-schema")


if __name__ == "__main__":
    unittest.main()
