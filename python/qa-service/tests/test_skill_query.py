import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.skill_query import (
    _normalise_summary_answer,
    _prior_context,
    _summary_context,
    _validate_dataset_scope,
    run_skill_query_workflow,
)


class SkillQueryWorkflowTest(unittest.IsolatedAsyncioTestCase):
    def test_json_fenced_summary_is_normalised_to_readable_markdown(self):
        answer = """```json
{"executionSummary":{"totalSteps":3,"completed":3},"keyFindings":[{"stepName":"数据集检查","finding":"共 7 条"}],"recommendations":["补充指标"]}
```"""

        normalised = _normalise_summary_answer(answer)

        self.assertIn("### 执行概览", normalised)
        self.assertIn("### 关键发现", normalised)
        self.assertIn("共 7 条", normalised)
        self.assertIn("### 建议", normalised)
        self.assertNotIn("```", normalised)
        self.assertFalse(normalised.lstrip().startswith("{"))

    def test_rejects_sql_that_reads_another_dataset_table(self):
        valid, invalid = _validate_dataset_scope(
            "SELECT a.value FROM table_one a JOIN table_two b ON a.id=b.id",
            "table_one",
        )
        self.assertFalse(valid)
        self.assertEqual(invalid, ["table_two"])

    def test_accepts_cte_alias_built_from_allowed_dataset_table(self):
        valid, invalid = _validate_dataset_scope(
            "WITH filtered AS (SELECT * FROM table_one) SELECT * FROM filtered",
            "table_one",
        )
        self.assertTrue(valid)
        self.assertEqual(invalid, [])

    def test_rejects_comma_join_to_another_dataset_table(self):
        valid, invalid = _validate_dataset_scope(
            "SELECT b.* FROM table_one a, table_two b WHERE a.id = b.id",
            "table_one",
        )
        self.assertFalse(valid)
        self.assertEqual(invalid, ["table_two"])

    def test_rejects_cross_schema_reference_even_when_table_name_matches(self):
        valid, invalid = _validate_dataset_scope(
            "SELECT * FROM secret_schema.table_one",
            "table_one",
        )
        self.assertFalse(valid)
        self.assertEqual(invalid, ["secret_schema.table_one"])

    def test_ignores_table_words_inside_comments_and_string_literals(self):
        valid, invalid = _validate_dataset_scope(
            "SELECT 'FROM table_two' AS note FROM table_one -- JOIN table_two\n",
            "table_one",
        )
        self.assertTrue(valid)
        self.assertEqual(invalid, [])

    def test_prior_context_is_valid_json_and_prefers_recent_steps(self):
        results = [
            {
                "order": index,
                "datasetId": f"dataset-{index}",
                "datasetName": f"Dataset {index}",
                "instruction": "x" * 1000,
                "status": "completed",
                "semanticSuccess": True,
                "returnedRows": 1,
                "totalRows": 1,
                "rows": [{"value": "y" * 1000}],
            }
            for index in range(1, 21)
        ]
        context = json.loads(_prior_context(results, max_chars=3500))

        self.assertEqual(context["totalPriorSteps"], 20)
        self.assertLess(context["includedPriorSteps"], 20)
        self.assertEqual(context["steps"][-1]["order"], 20)
        self.assertEqual(
            context["includedPriorSteps"] + context["omittedPriorSteps"],
            20,
        )

    def test_summary_context_keeps_all_twenty_steps_and_valid_json(self):
        results = [
            {
                "order": index,
                "datasetName": f"Dataset {index}",
                "instruction": "summarise " + ("detail " * 100),
                "status": "completed",
                "semanticSuccess": True,
                "returnedRows": 20,
                "totalRows": 20,
                "rows": [{"value": f"row-{row}-" + ("z" * 500)} for row in range(20)],
                "sql": f"SELECT * FROM table_{index}",
            }
            for index in range(1, 21)
        ]
        context = json.loads(_summary_context(results, max_chars=12_000))

        self.assertTrue(context["allStepsIncluded"])
        self.assertEqual(context["totalSteps"], 20)
        self.assertEqual([step["order"] for step in context["steps"]], list(range(1, 21)))

    async def test_queries_datasets_in_order_and_passes_prior_result(self):
        sql_prompts = []

        async def fake_llm(system_prompt, user_prompt):
            if "SQL生成专家" in system_prompt:
                sql_prompts.append(system_prompt)
                table = "table_one" if "table_one" in system_prompt else "table_two"
                dependency_filter = " WHERE value = 10" if table == "table_two" else ""
                return f"```sql\nSELECT * FROM {table}{dependency_filter}\n```"
            return "Combined skill conclusion"

        datasets = [
            {"id": "dataset-one", "name": "First dataset", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second dataset", "tableName": "table_two"},
        ]

        def fake_structure(dataset_id):
            table = "table_one" if dataset_id == "dataset-one" else "table_two"
            return {
                "tableName": table,
                "columns": [{"columnName": "value", "dataType": "integer"}],
                "count": 1,
            }

        def fake_execute(_dataset_id, sql):
            value = 10 if "table_one" in sql else 20
            return {"success": True, "rows": [{"value": value}], "columns": ["value"]}

        skill = {
            "id": "skill-order-test",
            "name": "Ordered query",
            "description": "Query two datasets in order",
            "steps": [
                {"datasetId": "dataset-one", "datasetName": "First dataset", "instruction": "Query first"},
                {"datasetId": "dataset-two", "datasetName": "Second dataset", "instruction": "Use first result"},
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch("agents.skill_query._fetch_dataset_structure_inner", side_effect=fake_structure),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_query.execute_sql_on_dataset", side_effect=fake_execute),
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Compare the datasets",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                    session_id="session-one",
                )
            ]

        result_event = next(event for event in events if event.get("type") == "result")
        results = result_event["result"]["queryResults"]
        planned_steps = [
            event["step"]["step"]
            for event in events
            if event.get("type") == "step" and event["step"].get("status") == "pending"
        ]

        self.assertEqual(planned_steps, ["skill.1", "skill.2", "skill.summary"])
        self.assertEqual([item["datasetId"] for item in results], ["dataset-one", "dataset-two"])
        self.assertEqual(results[0]["rows"], [{"value": 10}])
        self.assertEqual(results[1]["rows"], [{"value": 20}])
        self.assertIn('"value": 10', sql_prompts[1])
        self.assertEqual(result_event["result"]["final_answer"], "Combined skill conclusion")
        self.assertEqual(result_event["result"]["executionSummary"]["status"], "completed")
        self.assertEqual(result_event["result"]["executionSummary"]["successfulSteps"], 2)
        self.assertIn("durationMs", results[0])

    async def test_marks_skill_as_partial_when_one_dataset_query_fails(self):
        async def fake_llm(system_prompt, _user_prompt):
            if "SQL生成专家" in system_prompt:
                table = "table_one" if "table_one" in system_prompt else "table_two"
                dependency_filter = " WHERE value = 10" if table == "table_two" else ""
                return f"SELECT * FROM {table}{dependency_filter}"
            return "Conclusion with failure impact"

        datasets = [
            {"id": "dataset-one", "name": "First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second", "tableName": "table_two"},
        ]

        def fake_structure(dataset_id):
            table = "table_one" if dataset_id == "dataset-one" else "table_two"
            return {"tableName": table, "columns": [{"columnName": "value", "dataType": "integer"}]}

        def fake_execute(_dataset_id, sql):
            if "table_two" in sql:
                return {"success": False, "message": "dataset unavailable"}
            return {"success": True, "rows": [{"value": 10}], "columns": ["value"]}

        skill = {
            "id": "skill-partial-test",
            "name": "Partial query",
            "steps": [
                {"datasetId": "dataset-one", "datasetName": "First", "instruction": "Query first"},
                {"datasetId": "dataset-two", "datasetName": "Second", "instruction": "Query second"},
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch("agents.skill_query._fetch_dataset_structure_inner", side_effect=fake_structure),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_query.execute_sql_on_dataset", side_effect=fake_execute),
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Compare",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        root_final = [
            event["step"] for event in events
            if event.get("type") == "step" and event["step"].get("step") == "skill"
        ][-1]
        self.assertEqual(result["executionSummary"]["status"], "partial")
        self.assertEqual(result["executionSummary"]["successfulSteps"], 1)
        self.assertEqual(result["executionSummary"]["failedSteps"], 1)
        self.assertEqual(root_final["status"], "partial")

    async def test_retries_once_when_generated_sql_ignores_previous_result(self):
        table_two_attempts = 0

        async def fake_llm(system_prompt, _user_prompt):
            nonlocal table_two_attempts
            if "SQL生成专家" in system_prompt:
                if "table_one" in system_prompt:
                    return "SELECT * FROM table_one"
                table_two_attempts += 1
                if table_two_attempts == 1:
                    return "SELECT COUNT(*) AS total FROM table_two"
                return "SELECT * FROM table_two WHERE value = 10"
            return "Conclusion based on deterministic dependency"

        datasets = [
            {"id": "dataset-one", "name": "First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second", "tableName": "table_two"},
        ]

        def fake_structure(dataset_id):
            table = "table_one" if dataset_id == "dataset-one" else "table_two"
            return {"tableName": table, "columns": [{"columnName": "value", "dataType": "integer"}]}

        def fake_execute(_dataset_id, sql):
            return {
                "success": True,
                "rows": [{"value": 10 if "table_one" in sql else 20}],
            }

        skill = {
            "id": "skill-dependency-retry",
            "name": "Dependency retry",
            "steps": [
                {"datasetId": "dataset-one", "instruction": "Get identifiers"},
                {"datasetId": "dataset-two", "instruction": "Use identifiers"},
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch("agents.skill_query._fetch_dataset_structure_inner", side_effect=fake_structure),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_query.execute_sql_on_dataset", side_effect=fake_execute),
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Use first result in second query",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        second = result["queryResults"][1]
        self.assertEqual(table_two_attempts, 2)
        self.assertEqual(second["status"], "completed")
        self.assertTrue(second["dependencyValidated"])
        self.assertEqual(second["dependencyRetryCount"], 1)
        self.assertIn("WHERE value = 10", second["sql"])

    async def test_empty_required_result_is_semantic_failure_and_skips_dependency(self):
        sql_calls = []

        async def fake_llm(system_prompt, _user_prompt):
            if "SQL生成专家" in system_prompt:
                sql_calls.append(system_prompt)
                table = "table_one" if "table_one" in system_prompt else "table_two"
                return f"SELECT * FROM {table}"
            return "Conclusion acknowledging empty and skipped steps"

        datasets = [
            {"id": "dataset-one", "name": "First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second", "tableName": "table_two"},
        ]

        def fake_structure(dataset_id):
            table = "table_one" if dataset_id == "dataset-one" else "table_two"
            return {"tableName": table, "columns": [{"columnName": "value", "dataType": "integer"}]}

        skill = {
            "id": "skill-empty-test",
            "name": "Empty dependency",
            "steps": [
                {"datasetId": "dataset-one", "datasetName": "First", "instruction": "Find matches"},
                {"datasetId": "dataset-two", "datasetName": "Second", "instruction": "Use matches"},
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch("agents.skill_query._fetch_dataset_structure_inner", side_effect=fake_structure),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_query.execute_sql_on_dataset", return_value={"success": True, "rows": []}),
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Check dependencies",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        self.assertEqual(len(sql_calls), 1)
        self.assertEqual(result["queryResults"][0]["status"], "empty")
        self.assertFalse(result["queryResults"][0]["semanticSuccess"])
        self.assertEqual(result["queryResults"][1]["status"], "skipped")
        self.assertEqual(result["executionSummary"]["status"], "error")
        self.assertEqual(result["executionSummary"]["emptySteps"], 1)
        self.assertEqual(result["executionSummary"]["skippedSteps"], 1)

    async def test_on_empty_stop_marks_all_remaining_steps_skipped(self):
        async def fake_llm(system_prompt, _user_prompt):
            if "SQL生成专家" in system_prompt:
                return "SELECT * FROM table_one"
            return "Stopped workflow conclusion"

        datasets = [
            {"id": "dataset-one", "name": "First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second", "tableName": "table_two"},
            {"id": "dataset-three", "name": "Third", "tableName": "table_three"},
        ]
        skill = {
            "id": "skill-empty-stop",
            "name": "Stop on empty",
            "steps": [
                {"datasetId": "dataset-one", "instruction": "Find", "onEmpty": "stop"},
                {"datasetId": "dataset-two", "instruction": "Then second"},
                {"datasetId": "dataset-three", "instruction": "Then third"},
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch(
                "agents.skill_query._fetch_dataset_structure_inner",
                return_value={
                    "tableName": "table_one",
                    "columns": [{"columnName": "value", "dataType": "integer"}],
                },
            ),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_query.execute_sql_on_dataset", return_value={"success": True, "rows": []}) as execute,
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Stop deterministically",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(
            [item["status"] for item in result["queryResults"]],
            ["empty", "skipped", "skipped"],
        )
        self.assertEqual(result["executionSummary"]["skippedSteps"], 2)

    async def test_continue_after_failed_dependency_blocks_unbounded_full_scan(self):
        async def fake_llm(system_prompt, _user_prompt):
            if "SQL生成专家" in system_prompt:
                table = "table_one" if "table_one" in system_prompt else "table_two"
                return f"SELECT * FROM {table}"
            return "Conclusion"

        datasets = [
            {"id": "dataset-one", "name": "First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second", "tableName": "table_two"},
        ]

        def fake_structure(dataset_id):
            table = "table_one" if dataset_id == "dataset-one" else "table_two"
            return {"tableName": table, "columns": [{"columnName": "value", "dataType": "integer"}]}

        def fake_execute(_dataset_id, sql):
            if "table_one" in sql:
                return {"success": False, "message": "first step unavailable"}
            raise AssertionError("unbounded fallback SQL must not reach the database")

        skill = {
            "id": "skill-fallback-test",
            "name": "Bound fallback",
            "steps": [
                {"datasetId": "dataset-one", "instruction": "First"},
                {
                    "datasetId": "dataset-two",
                    "instruction": "Second",
                    "onDependencyFailure": "continue",
                },
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch("agents.skill_query._fetch_dataset_structure_inner", side_effect=fake_structure),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_query.execute_sql_on_dataset", side_effect=fake_execute),
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Fallback safely",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        self.assertEqual(result["queryResults"][0]["status"], "error")
        self.assertEqual(result["queryResults"][1]["status"], "error")
        self.assertIn("无约束全表查询", result["queryResults"][1]["error"])

    async def test_reports_returned_rows_and_truncation_and_emits_substeps(self):
        async def fake_llm(system_prompt, _user_prompt):
            if "SQL生成专家" in system_prompt:
                return "SELECT * FROM table_one"
            return "Complete conclusion"

        skill = {
            "id": "skill-truncation-test",
            "name": "Truncation",
            "steps": [{"datasetId": "dataset-one", "instruction": "Return all"}],
        }
        rows = [{"value": index} for index in range(1000)]

        with (
            patch(
                "agents.skill_query.fetch_datasets_for_database",
                return_value=[{"id": "dataset-one", "name": "First", "tableName": "table_one"}],
            ),
            patch(
                "agents.skill_query._fetch_dataset_structure_inner",
                return_value={
                    "tableName": "table_one",
                    "columns": [{"columnName": "value", "dataType": "integer"}],
                },
            ),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch(
                "agents.skill_query.execute_sql_on_dataset",
                return_value={
                    "success": True,
                    "rows": rows,
                    "rowCount": 1000,
                    "returnedRows": 1000,
                    "truncated": True,
                },
            ),
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Show results",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        item = result["queryResults"][0]
        child_phases = {
            event["step"].get("phase")
            for event in events
            if event.get("type") == "step" and event["step"].get("subStep")
        }
        execution_terminal = next(
            event["step"] for event in events
            if event.get("type") == "step"
            and event["step"].get("phase") == "sql_execution"
            and event["step"].get("status") == "completed"
        )
        self.assertEqual(item["displayedRows"], 100)
        self.assertEqual(item["returnedRows"], 1000)
        self.assertIsNone(item["totalRows"])
        self.assertEqual(item["minimumTotalRows"], 1001)
        self.assertTrue(item["truncated"])
        self.assertEqual(len(item["rows"]), 100)
        self.assertEqual(result["executionSummary"]["truncatedSteps"], 1)
        self.assertIn("完整总数未知", execution_terminal["detail"])
        self.assertIn("至少 1001 行", execution_terminal["detail"])
        self.assertTrue({
            "structure_load", "indicator_load", "sql_generation",
            "scope_validation", "sql_execution",
        }.issubset(child_phases))

    async def test_truncated_result_is_not_accepted_as_complete_dependency(self):
        async def fake_llm(system_prompt, _user_prompt):
            if "SQL生成专家" in system_prompt:
                return "SELECT * FROM table_one"
            return "Conclusion warning about truncation"

        datasets = [
            {"id": "dataset-one", "name": "First", "tableName": "table_one"},
            {"id": "dataset-two", "name": "Second", "tableName": "table_two"},
        ]
        skill = {
            "id": "skill-truncated-dependency",
            "name": "Reject partial dependency",
            "steps": [
                {"datasetId": "dataset-one", "instruction": "Get all IDs"},
                {"datasetId": "dataset-two", "instruction": "Use all IDs"},
            ],
        }

        with (
            patch("agents.skill_query.fetch_datasets_for_database", return_value=datasets),
            patch(
                "agents.skill_query._fetch_dataset_structure_inner",
                return_value={
                    "tableName": "table_one",
                    "columns": [{"columnName": "id", "dataType": "integer"}],
                },
            ),
            patch("agents.skill_query.fetch_indicators_for_datasets", return_value=[]),
            patch(
                "agents.skill_query.execute_sql_on_dataset",
                return_value={
                    "success": True,
                    "rows": [{"id": index + 10} for index in range(1000)],
                    "rowCount": 1000,
                    "returnedRows": 1000,
                    "truncated": True,
                },
            ) as execute,
        ):
            events = [
                event async for event in run_skill_query_workflow(
                    question="Use every identifier",
                    database_id="database-one",
                    skill=skill,
                    llm_call_fn=fake_llm,
                )
            ]

        result = next(event["result"] for event in events if event.get("type") == "result")
        self.assertEqual(execute.call_count, 1)
        self.assertTrue(result["queryResults"][0]["truncated"])
        self.assertEqual(result["queryResults"][1]["status"], "skipped")
        self.assertIn("结果已截断", result["queryResults"][1]["skipReason"])


if __name__ == "__main__":
    unittest.main()
