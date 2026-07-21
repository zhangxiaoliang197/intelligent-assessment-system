"""Tests for AI drafting, richer orchestration and quality operations."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest


SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from agents import skill_execution_store as runtime_store  # noqa: E402
from agents.skill_ai_service import generate_skill_draft, normalize_ai_draft  # noqa: E402
from agents.skill_quality_service import (  # noqa: E402
    evaluate_execution_quality,
    get_skill_operations_overview,
)
from agents.skill_runner import _order_plan_by_dependencies  # noqa: E402


class SkillAiAndOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def test_ai_draft_is_repaired_into_a_safe_dependency_graph(self):
        draft = normalize_ai_draft(
            """```json
            {
              "name": "任务质量分析", "description": "分析任务质量", "category": "任务评估",
              "steps": [
                {"id": "PLAN", "name": "计划", "description": "核验计划", "datasetKeywords": ["plan"], "dependsOn": ["result"]},
                {"id": "result", "name": "结果", "description": "分析结果", "datasetKeywords": ["result"], "dependsOn": ["plan"]}
              ],
              "outputInstruction": "输出结论"
            }
            ```"""
        )
        self.assertEqual(["plan", "result"], [step["id"] for step in draft["steps"]])
        self.assertEqual([], draft["steps"][0]["dependsOn"])
        self.assertEqual(["plan"], draft["steps"][1]["dependsOn"])
        self.assertEqual("dependency", draft["orchestration"]["mode"])

    async def test_generate_draft_includes_data_source_completeness(self):
        async def fake_llm(_system, _user):
            return '{"name":"库存分析","description":"分析库存","category":"保障评估","steps":[{"id":"stock","name":"库存","description":"查询库存","datasetKeywords":["inventory"]}],"outputInstruction":"总结"}'

        draft = await generate_skill_draft(
            requirement="分析库存余量并提出补给建议",
            datasets=[{"id": "ds-1", "name": "库存", "tableName": "inventory"}],
            llm_call_fn=fake_llm,
        )
        self.assertEqual(1, draft["dataContext"]["datasetCount"])
        self.assertTrue(draft["dataContext"]["dataSourceComplete"])

    def test_dependency_plan_uses_stable_topological_order(self):
        plan = [
            {"sequence": 1, "step": {"id": "result", "dependsOn": ["plan"]}},
            {"sequence": 2, "step": {"id": "plan", "dependsOn": []}},
            {"sequence": 3, "step": {"id": "summary", "dependsOn": ["result"]}},
        ]
        ordered = _order_plan_by_dependencies(plan)
        self.assertEqual(["plan", "result", "summary"], [item["step"]["id"] for item in ordered])
        self.assertEqual([1, 2, 3], [item["sequence"] for item in ordered])


class SkillQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_path = runtime_store._DB_PATH
        runtime_store._DB_PATH = os.path.join(self.temp_dir.name, "runtime.sqlite3")

    def tearDown(self):
        runtime_store._DB_PATH = self.previous_path
        self.temp_dir.cleanup()

    def test_quality_report_is_persisted_and_included_in_operations_overview(self):
        runtime_store.create_execution(
            {
                "runId": "quality-run",
                "skillId": "quality-skill",
                "skillName": "质量 Skill",
                "actorId": "user-1",
                "question": "分析命中率",
                "databaseId": "db-1",
                "totalSteps": 2,
            }
        )
        runtime_store.finish_execution(
            "quality-run",
            status="completed",
            result={
                "final_answer": "结论：命中率稳定。\n建议：继续观察异常波动。",
                "queryResults": [],
                "skillExecution": {
                    "totalSteps": 2,
                    "matchedSteps": 2,
                    "completedSteps": 2,
                    "skippedSteps": 0,
                    "errorSteps": 0,
                    "synthesisStatus": "completed",
                    "overallStatus": "completed",
                    "durationMs": 1200,
                },
            },
        )
        report = evaluate_execution_quality(
            "quality-run", expected_keywords=["命中率", "异常"]
        )
        self.assertGreaterEqual(report["score"], 75)
        self.assertIn(report["grade"], {"A", "B"})
        self.assertEqual("quality-run", runtime_store.get_quality_report("quality-run")["runId"])

        overview = get_skill_operations_overview(
            skill_id="quality-skill", actor_id="user-1", days=30
        )
        self.assertEqual(1, overview["runCount"])
        self.assertEqual(100.0, overview["successRate"])
        self.assertEqual(1, overview["evaluatedRuns"])
        self.assertEqual(report["score"], overview["averageQualityScore"])


if __name__ == "__main__":
    unittest.main()
