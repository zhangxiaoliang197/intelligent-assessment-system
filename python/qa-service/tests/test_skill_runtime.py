import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from agents import skill_execution_store as runtime_store, skill_runner  # noqa: E402
from agents.skill_runner import (  # noqa: E402
    cancel_skill_run,
    get_skill_execution,
    preflight_skill_execution,
    run_skill_step_trial,
    run_skill_workflow,
)
from agents.skill_runtime_service import (  # noqa: E402
    compare_skill_executions,
    create_skill_schedule,
    delete_skill_schedule,
    get_skill_schedule,
    next_cron_time,
    poll_and_run_due_schedules,
    run_skill_batch,
    update_skill_schedule,
    validate_cron_expression,
)


def sample_skill():
    return {
        "id": "runtime-test",
        "name": "运行治理测试",
        "description": "验证运行治理",
        "category": "测试",
        "revision": 3,
        "outputInstruction": "总结结果",
        "steps": [
            {
                "id": "loss",
                "name": "战损",
                "description": "查询战损",
                "datasetKeywords": ["combat_loss"],
            }
        ],
    }


class RuntimeStoreMixin:
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_path = runtime_store._DB_PATH
        runtime_store._DB_PATH = os.path.join(self.temp_dir.name, "runtime.sqlite3")

    def tearDown(self):
        runtime_store._DB_PATH = self.previous_path
        self.temp_dir.cleanup()


class ExecutionStoreTests(RuntimeStoreMixin, unittest.TestCase):
    def test_execution_step_and_final_result_are_persisted(self):
        runtime_store.create_execution({
            "runId": "run-1",
            "skill": sample_skill(),
            "question": "测试",
            "databaseId": "db-1",
        })
        runtime_store.record_execution_step("run-1", {
            "type": "step",
            "step": {
                "step": "skill-dataset-1",
                "sequence": 1,
                "description": "战损",
                "phase": "dataset",
                "status": "completed",
                "durationMs": 12,
            },
        })
        result = {
            "final_answer": "完成",
            "queryResults": [{"sequence": 1, "stepId": "loss", "status": "completed"}],
            "skillExecution": {
                "totalSteps": 1,
                "matchedSteps": 1,
                "completedSteps": 1,
                "skippedSteps": 0,
                "errorSteps": 0,
                "overallStatus": "completed",
                "durationMs": 22,
            },
        }
        runtime_store.finish_execution("run-1", status="completed", result=result)

        stored = runtime_store.get_execution("run-1")
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["completedSteps"], 1)
        self.assertEqual(stored["steps"][0]["result"]["stepId"], "loss")
        self.assertEqual(runtime_store.list_executions(skill_id="runtime-test")["total"], 1)


class SkillRuntimeTests(RuntimeStoreMixin, unittest.IsolatedAsyncioTestCase):
    async def test_preflight_checks_dataset_and_schema_completeness(self):
        with (
            patch(
                "agents.skill_runner.fetch_datasets_for_database",
                return_value=[{"id": "loss-ds", "name": "战损", "tableName": "combat_loss"}],
            ),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_loss", "columns": [{"columnName": "id"}]},
            ),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
        ):
            result = await preflight_skill_execution(
                database_id="db-1", database_name="测试库", skill=sample_skill()
            )
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["completeness"], 1.0)
        self.assertTrue(result["datasetPlan"][0]["schemaReady"])

    async def test_workflow_has_run_id_and_durable_result(self):
        async def fake_text_to_sql(state, _llm, max_retries=1):
            state.generated_sql = "SELECT * FROM combat_loss"
            state.sql_valid = True
            return state

        async def fake_llm(_system, _user):
            return "运行完成"

        with (
            patch(
                "agents.skill_runner.fetch_datasets_for_database",
                return_value=[{"id": "loss-ds", "name": "战损", "tableName": "combat_loss"}],
            ),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_loss", "columns": [{"columnName": "id"}]},
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
                    skill=sample_skill(),
                    llm_call_fn=fake_llm,
                    run_id="governed-run",
                    actor_id="user-1",
                )
            ]
        self.assertTrue(all(event["runId"] == "governed-run" for event in events))
        stored = get_skill_execution("governed-run")
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["actorId"], "user-1")
        self.assertEqual(stored["result"]["final_answer"], "运行完成")

    async def test_active_workflow_can_be_cancelled(self):
        def slow_catalog(_database_id, _active_only):
            time.sleep(0.5)
            return []

        async def fake_llm(_system, _user):
            return "不应调用"

        async def collect():
            return [
                event
                async for event in run_skill_workflow(
                    question="取消测试",
                    database_id="db-1",
                    database_name="测试库",
                    skill=sample_skill(),
                    llm_call_fn=fake_llm,
                    run_id="cancel-run",
                )
            ]

        with patch("agents.skill_runner.fetch_datasets_for_database", side_effect=slow_catalog):
            task = asyncio.create_task(collect())
            await asyncio.sleep(0.05)
            cancellation = cancel_skill_run("cancel-run", "user-1")
            events = await asyncio.wait_for(task, timeout=2)
        self.assertTrue(cancellation["accepted"])
        result = next(event["result"] for event in events if event["type"] == "result")
        self.assertEqual(result["skillExecution"]["overallStatus"], "cancelled")
        self.assertEqual(get_skill_execution("cancel-run")["status"], "cancelled")

    async def test_overall_timeout_produces_a_durable_terminal_result(self):
        async def fake_llm(_system, _user):
            return "不应调用"

        with patch(
            "agents.skill_runner._next_event_or_cancel",
            side_effect=skill_runner._SkillRunTimedOut("Skill 执行超过整体超时限制"),
        ):
            events = [
                event
                async for event in run_skill_workflow(
                    question="超时测试",
                    database_id="db-1",
                    database_name="测试库",
                    skill=sample_skill(),
                    llm_call_fn=fake_llm,
                    run_id="timeout-run",
                    timeout_seconds=30,
                )
            ]
        result = next(event["result"] for event in events if event["type"] == "result")
        self.assertEqual("timed_out", result["skillExecution"]["overallStatus"])
        self.assertEqual(30, result["skillExecution"]["timeoutSeconds"])
        self.assertEqual("timed_out", get_skill_execution("timeout-run")["status"])

    async def test_skip_dependents_blocks_descendants_even_when_run_if_is_always(self):
        skill = sample_skill()
        skill["orchestration"] = {
            "mode": "dependency",
            "maxConcurrency": 1,
            "timeoutSeconds": 600,
            "failurePolicy": "continue",
        }
        skill["steps"][0].update({"onFailure": "skip_dependents"})
        skill["steps"].append({
            "id": "summary",
            "name": "汇总",
            "description": "汇总战损",
            "datasetKeywords": ["combat_loss"],
            "allowReuse": True,
            "dependsOn": ["loss"],
            "runIf": "always",
        })

        async def fake_text_to_sql(state, _llm, max_retries=1):
            state.generated_sql = "SELECT * FROM combat_loss"
            state.sql_valid = True
            return state

        async def fake_llm(_system, _user):
            return "不生成结论"

        with (
            patch(
                "agents.skill_runner.fetch_datasets_for_database",
                return_value=[{"id": "loss-ds", "name": "战损", "tableName": "combat_loss"}],
            ),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_loss", "columns": [{"columnName": "id"}]},
            ),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_runner.run_text_to_sql", side_effect=fake_text_to_sql),
            patch(
                "agents.skill_runner.execute_sql_on_database",
                return_value={"success": False, "message": "模拟失败"},
            ) as execute_sql,
        ):
            events = [
                event
                async for event in run_skill_workflow(
                    question="依赖失败测试",
                    database_id="db-1",
                    database_name="测试库",
                    skill=skill,
                    llm_call_fn=fake_llm,
                    run_id="skip-dependent-run",
                    include_synthesis=False,
                )
            ]
        result = next(event["result"] for event in events if event["type"] == "result")
        self.assertEqual(["error", "skipped"], [item["status"] for item in result["queryResults"]])
        self.assertIn("skip_dependents", result["queryResults"][1]["error"])
        self.assertEqual(1, execute_sql.call_count)

    async def test_single_step_trial_avoids_synthesis(self):
        skill = sample_skill()

        async def fake_text_to_sql(state, _llm, max_retries=1):
            state.generated_sql = "SELECT * FROM combat_loss"
            state.sql_valid = True
            return state

        async def forbidden_llm(_system, _user):
            self.fail("单步试运行不应调用结论生成")

        with (
            patch(
                "agents.skill_runner.fetch_datasets_for_database",
                return_value=[{"id": "loss-ds", "name": "战损", "tableName": "combat_loss"}],
            ),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_loss", "columns": [{"columnName": "id"}]},
            ),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_runner.run_text_to_sql", side_effect=fake_text_to_sql),
            patch(
                "agents.skill_runner.execute_sql_on_database",
                return_value={"success": True, "columns": ["id"], "rows": [{"id": 1}]},
            ),
        ):
            trial = await run_skill_step_trial(
                question="测试",
                database_id="db-1",
                database_name="测试库",
                skill=skill,
                llm_call_fn=forbidden_llm,
                step_id="loss",
                run_id="trial-run",
            )
        self.assertEqual(trial["status"], "completed")
        self.assertEqual(trial["stepResult"]["stepId"], "loss")
        self.assertEqual(trial["stepResult"]["originalSequence"], 1)

    async def test_batch_and_due_schedule_use_governed_workflow(self):
        skill = sample_skill()

        async def fake_text_to_sql(state, _llm, max_retries=1):
            state.generated_sql = "SELECT * FROM combat_loss"
            state.sql_valid = True
            return state

        async def fake_llm(_system, _user):
            return "批量完成"

        runtime_patches = (
            patch(
                "agents.skill_runner.fetch_datasets_for_database",
                return_value=[{"id": "loss-ds", "name": "战损", "tableName": "combat_loss"}],
            ),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_loss", "columns": [{"columnName": "id"}]},
            ),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_runner.run_text_to_sql", side_effect=fake_text_to_sql),
            patch(
                "agents.skill_runner.execute_sql_on_database",
                return_value={"success": True, "columns": ["id"], "rows": [{"id": 1}]},
            ),
        )
        with runtime_patches[0], runtime_patches[1], runtime_patches[2], runtime_patches[3], runtime_patches[4]:
            batch = await run_skill_batch(
                items=[
                    {"skillId": skill["id"], "query": "任务一", "dataSourceId": "db-1"},
                    {"skillId": skill["id"], "query": "任务二", "dataSourceId": "db-1"},
                ],
                skill_resolver=lambda _skill_id: skill,
                llm_call_fn=fake_llm,
                actor_id="user-1",
            )
        self.assertEqual(batch["status"], "completed")
        self.assertEqual(len(batch["items"]), 2)
        self.assertTrue(all(item["runId"] for item in batch["items"]))

        schedule = create_skill_schedule(
            {
                "skillId": skill["id"],
                "question": "定时任务",
                "databaseId": "db-1",
                "cron": "*/5 * * * *",
                "timezone": "UTC",
                "nextRunAt": "2026-01-01T00:00:00.000Z",
            },
            created_by="user-1",
        )
        schedule_patches = (
            patch(
                "agents.skill_runner.fetch_datasets_for_database",
                return_value=[{"id": "loss-ds", "name": "战损", "tableName": "combat_loss"}],
            ),
            patch(
                "agents.skill_runner._fetch_dataset_structure_inner",
                return_value={"tableName": "combat_loss", "columns": [{"columnName": "id"}]},
            ),
            patch("agents.skill_runner.fetch_indicators_for_datasets", return_value=[]),
            patch("agents.skill_runner.run_text_to_sql", side_effect=fake_text_to_sql),
            patch(
                "agents.skill_runner.execute_sql_on_database",
                return_value={"success": True, "columns": ["id"], "rows": [{"id": 1}]},
            ),
        )
        with schedule_patches[0], schedule_patches[1], schedule_patches[2], schedule_patches[3], schedule_patches[4]:
            outcomes = await poll_and_run_due_schedules(
                skill_resolver=lambda _skill_id: skill,
                llm_call_fn=fake_llm,
                now="2026-07-20T00:00:00.000Z",
            )
        self.assertEqual(outcomes[0]["scheduleId"], schedule["scheduleId"])
        self.assertEqual(outcomes[0]["status"], "completed")
        self.assertEqual(get_skill_schedule(schedule["scheduleId"])["lastRunId"], outcomes[0]["runId"])


class ScheduleAndComparisonTests(RuntimeStoreMixin, unittest.TestCase):
    def test_cron_schedule_is_persistent_and_editable(self):
        validate_cron_expression("*/15 * * * *")
        next_at = next_cron_time("*/15 * * * *", "Asia/Shanghai", after="2026-07-20T00:01:00Z")
        self.assertEqual(next_at, "2026-07-20T00:15:00.000Z")
        schedule = create_skill_schedule(
            {
                "name": "每小时评估",
                "skillId": "runtime-test",
                "question": "检查战损",
                "databaseId": "db-1",
                "cron": "0 * * * *",
                "timezone": "UTC",
            },
            created_by="user-1",
        )
        updated = update_skill_schedule(schedule["scheduleId"], {"enabled": False})
        self.assertFalse(updated["enabled"])
        self.assertTrue(delete_skill_schedule(schedule["scheduleId"]))

    def test_compare_completed_runs(self):
        for index, duration in enumerate((100, 140), start=1):
            run_id = f"compare-{index}"
            runtime_store.create_execution({
                "runId": run_id,
                "skill": sample_skill(),
                "databaseId": "db-1",
            })
            runtime_store.finish_execution(
                run_id,
                status="completed",
                result={
                    "final_answer": f"答案 {index}",
                    "queryResults": [{
                        "sequence": 1,
                        "stepId": "loss",
                        "stepName": "战损",
                        "status": "completed",
                        "totalRows": index,
                        "durationMs": duration,
                        "sql": "SELECT * FROM combat_loss",
                    }],
                    "skillExecution": {
                        "totalSteps": 1,
                        "completedSteps": 1,
                        "durationMs": duration,
                        "overallStatus": "completed",
                    },
                },
            )
        comparison = compare_skill_executions(["compare-1", "compare-2"])
        self.assertEqual(comparison["baselineRunId"], "compare-1")
        self.assertEqual(comparison["differences"][0]["durationDeltaMs"], 40)
        self.assertTrue(comparison["differences"][0]["answerChanged"])


if __name__ == "__main__":
    unittest.main()
