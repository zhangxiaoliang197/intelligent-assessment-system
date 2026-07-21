"""HTTP/import smoke tests for governed Skill runtime endpoints."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch


SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agents import skill_execution_store as runtime_store  # noqa: E402
from skill_api import skill_api_router  # noqa: E402


BUILTIN_SKILL_ID = "combat-effectiveness-overview"


class SkillRuntimeApiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_path = runtime_store._DB_PATH
        runtime_store._DB_PATH = os.path.join(self.temp_dir.name, "runtime.sqlite3")
        app = FastAPI()
        app.include_router(skill_api_router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        runtime_store._DB_PATH = self.previous_path
        self.temp_dir.cleanup()

    def test_main_and_router_modules_import_with_runtime_routes(self):
        main_module = importlib.import_module("main")
        importlib.import_module("evaluation_api")
        importlib.import_module("skill_api")
        main_client = TestClient(main_module.app)
        try:
            response = main_client.get("/evaluation/schedules")
        finally:
            main_client.close()
        self.assertEqual(response.status_code, 200, response.text)

    def test_preflight_and_trial_contracts(self):
        preflight = {
            "skillId": BUILTIN_SKILL_ID,
            "databaseId": "db-1",
            "status": "ready",
            "ready": True,
            "matchedSteps": 1,
            "totalSteps": 1,
            "completeness": 1.0,
            "checks": [],
            "datasetPlan": [],
        }
        with patch("skill_api.preflight_skill_execution", new=AsyncMock(return_value=preflight)):
            response = self.client.post(
                f"/evaluation/skills/{BUILTIN_SKILL_ID}/preflight",
                json={"dataSourceId": "db-1"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["runnable"])

        trial = {
            "runId": "trial-api-run",
            "status": "completed",
            "skillId": BUILTIN_SKILL_ID,
            "stepId": "overview",
            "stepResult": {"stepId": "overview", "status": "completed"},
            "durationMs": 10,
        }
        with patch("skill_api.run_skill_step_trial", new=AsyncMock(return_value=trial)):
            response = self.client.post(
                f"/evaluation/skills/{BUILTIN_SKILL_ID}/trial",
                json={
                    "query": "测试",
                    "dataSourceId": "db-1",
                    "stepId": "overview",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["execution"]["type"], "trial")

    def test_ai_draft_route_returns_an_editable_private_draft(self):
        draft = {
            "name": "智能草稿",
            "description": "智能创建的草稿",
            "category": "任务评估",
            "triggers": ["任务评估"],
            "recommendedQuestions": [],
            "steps": [{
                "id": "plan",
                "name": "计划",
                "description": "核验计划",
                "datasetKeywords": ["plan"],
                "dependsOn": [],
            }],
            "outputInstruction": "总结",
            "visibility": "private",
            "orchestration": {"mode": "sequential", "timeoutSeconds": 600},
            "dataContext": {"datasetCount": 0, "dataSourceComplete": False},
        }
        with patch("skill_api.generate_skill_draft", new=AsyncMock(return_value=draft)):
            response = self.client.post(
                "/evaluation/skills/ai-draft",
                json={"requirement": "分析任务完成质量", "maxSteps": 5},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual("private", response.json()["draft"]["visibility"])
        self.assertFalse(response.json()["dataContext"]["dataSourceComplete"])

    def test_schedule_crud_batch_submission_and_comparison(self):
        created = self.client.post(
            "/evaluation/schedules",
            json={
                "skillId": BUILTIN_SKILL_ID,
                "name": "冒烟调度",
                "cron": "*/5 * * * *",
                "timezone": "Asia/Shanghai",
                "enabled": True,
                "query": "评估战斗效能",
                "dataSourceId": "db-1",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        schedule_id = created.json()["id"]
        self.assertTrue(schedule_id)
        listed = self.client.get("/evaluation/schedules")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        updated = self.client.put(
            f"/evaluation/schedules/{schedule_id}", json={"enabled": False}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["enabled"])

        def discard_background(coroutine):
            coroutine.close()
            return None

        with patch("skill_api._spawn", side_effect=discard_background):
            batch = self.client.post(
                "/evaluation/batches",
                json={
                    "skillId": BUILTIN_SKILL_ID,
                    "name": "冒烟批量",
                    "dataSourceId": "db-1",
                    "queries": ["问题一", "问题二"],
                },
            )
        self.assertEqual(batch.status_code, 202, batch.text)
        self.assertEqual(batch.json()["total"], 2)
        self.assertEqual(batch.json()["status"], "queued")

        for index, duration in enumerate((30, 45), start=1):
            run_id = f"api-compare-{index}"
            runtime_store.create_execution({
                "runId": run_id,
                "skillId": BUILTIN_SKILL_ID,
                "skillName": "作战效能综合评估",
                "actorId": "local-admin",
                "question": f"问题 {index}",
                "databaseId": "db-1",
            })
            runtime_store.finish_execution(
                run_id,
                status="completed",
                result={
                    "final_answer": f"结论 {index}",
                    "queryResults": [],
                    "skillExecution": {
                        "totalSteps": 1,
                        "completedSteps": 1,
                        "durationMs": duration,
                        "overallStatus": "completed",
                    },
                },
            )
        compared = self.client.post(
            "/evaluation/executions/compare",
            json={"runIds": ["api-compare-1", "api-compare-2"]},
        )
        self.assertEqual(compared.status_code, 200, compared.text)
        self.assertEqual(len(compared.json()["items"]), 2)
        self.assertEqual(compared.json()["differences"][0]["durationDeltaMs"], 15)

        quality = self.client.post(
            "/evaluation/quality/evaluate",
            json={"runId": "api-compare-1", "expectedKeywords": ["结论"]},
        )
        self.assertEqual(quality.status_code, 200, quality.text)
        self.assertGreater(quality.json()["score"], 0)
        overview = self.client.get(
            "/evaluation/quality/overview", params={"skillId": BUILTIN_SKILL_ID}
        )
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(2, overview.json()["runCount"])
        self.assertEqual(1, overview.json()["evaluatedRuns"])

        deleted = self.client.delete(f"/evaluation/schedules/{schedule_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])


if __name__ == "__main__":
    unittest.main()
