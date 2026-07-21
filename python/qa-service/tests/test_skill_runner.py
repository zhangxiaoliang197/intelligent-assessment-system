import os
import sys
import unittest
from unittest.mock import patch


SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from agents.skill_runner import (  # noqa: E402
    _is_dataset_scoped_sql,
    run_skill_workflow,
)


class DatasetScopeTests(unittest.TestCase):
    def test_allows_current_table_and_rejects_cte(self):
        self.assertEqual(_is_dataset_scoped_sql("SELECT * FROM combat_loss", "combat_loss"), (True, ""))
        allowed, _ = _is_dataset_scoped_sql(
            "WITH recent AS (SELECT * FROM combat_loss) SELECT * FROM recent",
            "combat_loss",
        )
        self.assertFalse(allowed)

    def test_rejects_cross_dataset_access_variants(self):
        rejected = [
            "SELECT * FROM combat_loss JOIN combat_result ON 1=1",
            "SELECT * FROM combat_loss a, combat_result b",
            "SELECT * FROM other_schema.combat_loss",
            'SELECT * FROM "combat_loss-archive"',
            "SELECT * FROM combat_loss@remote_db",
            'SELECT * FROM combat_loss@"REMOTE_LINK"',
            "SELECT * FROM combat_loss CROSS APPLY OPENJSON(payload)",
            "SELECT * FROM combat_loss STRAIGHT_JOIN secret_table ON 1=1",
            "SELECT * FROM combat_loss WHERE EXISTS (TABLE secret_table)",
        ]
        for sql in rejected:
            with self.subTest(sql=sql):
                allowed, _ = _is_dataset_scoped_sql(sql, "combat_loss")
                self.assertFalse(allowed)


class SkillWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_dataset_steps_in_declaration_order(self):
        skill = {
            "id": "test-sequential-skill",
            "name": "顺序测试 Skill",
            "description": "验证数据集顺序",
            "category": "测试",
            "outputInstruction": "按顺序总结",
            "steps": [
                {
                    "id": "loss",
                    "name": "先查战损",
                    "description": "查询战损",
                    "datasetKeywords": ["combat_loss"],
                },
                {
                    "id": "result",
                    "name": "再查战果",
                    "description": "查询战果",
                    "datasetKeywords": ["combat_result"],
                },
            ],
        }
        datasets = [
            {"id": "result-ds", "name": "战果", "tableName": "combat_result"},
            {"id": "loss-ds", "name": "战损", "tableName": "combat_loss"},
        ]
        generated_tables = []
        executed_sql = []

        async def fake_text_to_sql(state, _llm, max_retries=1):
            self.assertEqual(max_retries, 0)
            table_name = state.table_schemas[0]["tableName"]
            generated_tables.append(table_name)
            state.generated_sql = f"SELECT * FROM {table_name}"
            state.sql_valid = True
            return state

        async def fake_llm(_system, _user):
            return "顺序执行完成"

        def fake_structure(dataset_id):
            table_name = "combat_loss" if dataset_id == "loss-ds" else "combat_result"
            return {"tableName": table_name, "columns": [{"columnName": "id", "dataType": "int"}]}

        def fake_execute(_database_id, sql):
            executed_sql.append(sql)
            if len(executed_sql) == 1:
                return {
                    "success": True,
                    "columns": ["id"],
                    "rows": [{"id": index} for index in range(25)],
                    "truncated": False,
                }
            return {
                "success": True,
                "columns": ["id"],
                "rows": [{"id": 1}],
                "truncated": True,
            }

        with (
            patch("agents.skill_runner.fetch_datasets_for_database", return_value=datasets),
            patch("agents.skill_runner._fetch_dataset_structure_inner", side_effect=fake_structure),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_runner.run_text_to_sql", side_effect=fake_text_to_sql),
            patch("agents.skill_runner.execute_sql_on_database", side_effect=fake_execute),
        ):
            events = [
                event
                async for event in run_skill_workflow(
                    question="测试",
                    database_id="db-1",
                    database_name="测试库",
                    skill=skill,
                    llm_call_fn=fake_llm,
                    session_id="session-1",
                )
            ]

        self.assertEqual(generated_tables, ["combat_loss", "combat_result"])
        self.assertEqual(
            executed_sql,
            ["SELECT * FROM combat_loss", "SELECT * FROM combat_result"],
        )
        completed_stages = [
            event["step"]["description"]
            for event in events
            if event["type"] == "step"
            and event["step"].get("phase") == "dataset"
            and event["step"]["status"] == "completed"
        ]
        self.assertEqual(completed_stages, ["先查战损", "再查战果"])
        result_events = [event for event in events if event["type"] == "result"]
        self.assertEqual(len(result_events), 1)
        result = result_events[0]["result"]
        self.assertEqual(result["skillExecution"]["completedSteps"], 2)
        self.assertEqual(result["final_answer"], "顺序执行完成")
        self.assertTrue(result["queryResults"][0]["displayTruncated"])
        self.assertFalse(result["queryResults"][0]["queryTruncated"])
        self.assertEqual(len(result["queryResults"][0]["rows"]), 20)
        self.assertTrue(result["queryResults"][1]["queryTruncated"])

    async def test_synthesis_failure_marks_the_run_partial(self):
        skill = {
            "id": "test-synthesis-status",
            "name": "汇总状态测试",
            "description": "验证汇总失败不会显示全部完成",
            "category": "测试",
            "outputInstruction": "总结",
            "steps": [{
                "id": "result",
                "name": "查询战果",
                "description": "查询战果数据",
                "datasetKeywords": ["combat_result"],
            }],
        }
        datasets = [{"id": "result-ds", "name": "战果", "tableName": "combat_result"}]

        async def fake_text_to_sql(state, _llm, max_retries=1):
            state.generated_sql = "SELECT * FROM combat_result"
            state.sql_valid = True
            return state

        async def failing_llm(_system, _user):
            raise RuntimeError("synthesis unavailable")

        with (
            patch("agents.skill_runner.fetch_datasets_for_database", return_value=datasets),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_result", "columns": [{"columnName": "id"}]},
            ),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_runner.run_text_to_sql", side_effect=fake_text_to_sql),
            patch(
                "agents.skill_runner.execute_sql_on_database",
                return_value={"success": True, "columns": ["id"], "rows": [{"id": 1}]},
            ),
        ):
            events = [
                event
                async for event in run_skill_workflow(
                    question="测试",
                    database_id="db-1",
                    database_name="测试库",
                    skill=skill,
                    llm_call_fn=failing_llm,
                )
            ]

        result = next(event["result"] for event in events if event["type"] == "result")
        self.assertEqual(result["skillExecution"]["completedSteps"], 1)
        self.assertEqual(result["skillExecution"]["synthesisStatus"], "error")
        self.assertEqual(result["skillExecution"]["overallStatus"], "partial")


if __name__ == "__main__":
    unittest.main()
