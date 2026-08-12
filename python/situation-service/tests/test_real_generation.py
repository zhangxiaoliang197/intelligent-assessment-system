import asyncio
import unittest
from unittest.mock import patch

from agent import orchestrator
import main
from models import Report


class RealOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_generation_uses_evidence_then_llm_in_required_order(self):
        bundles = [{
            "source": "t_equipment",
            "summary": "真实装备表返回 2 条可用记录",
            "rows": 2,
            "payload": {"success": True, "rows": [
                {"区域": "A", "完好率": "91"},
                {"区域": "B", "完好率": "83"},
            ]},
        }]
        llm_result = {
            "charts": [{
                "chartId": "c_real",
                "type": "bar",
                "title": "装备完好率",
                "datasetRef": "real_1_t_equipment",
                "option": {
                    "xAxis": {"type": "category", "data": ["A", "B"]},
                    "yAxis": {"type": "value"},
                    "series": [{"type": "bar", "data": [91, 83]}],
                },
            }],
            "mapLayer": {"layerId": "real_map", "points": []},
            "narrative": {
                "intro": "基于真实装备记录生成。",
                "explanations": [{"chartId": "c_real", "text": "A、B 区域对比。"}],
            },
        }
        with patch.object(orchestrator, "_collect_real_data", return_value=(bundles, [])), \
             patch.object(orchestrator, "_run_llm_orchestration", return_value=llm_result):
            events = [
                event async for event in orchestrator.real_generate(
                    "对比装备完好率", "r_real", {"dataSources": ["t_equipment"]}, {}
                )
            ]

        types = [event_type for event_type, _ in events]
        self.assertEqual(types, ["plan", "dataset", "chart", "map_layer", "narrative", "done"])
        self.assertTrue(events[1][1]["realData"])
        self.assertEqual(events[2][1]["option"]["series"][0]["data"], [91, 83])
        self.assertTrue(events[2][1]["verification"]["verified"])
        self.assertEqual(events[2][1]["provenance"]["datasetId"], "real_1_t_equipment")
        self.assertEqual(events[-1][1]["orchestration"], "llm")

    async def test_llm_failure_falls_back_to_real_rows_not_mock_data(self):
        bundles = [{
            "source": "indicator",
            "summary": "真实指标目录返回 2 条可用记录",
            "rows": 2,
            "payload": {"indicators": [
                {"name": "任务完成率", "value": "88"},
                {"name": "装备完好率", "value": "76"},
            ]},
        }]
        with patch.object(orchestrator, "_collect_real_data", return_value=(bundles, [])), \
             patch.object(orchestrator, "_run_llm_orchestration", side_effect=RuntimeError("LLM unavailable")), \
             patch.object(orchestrator.config, "SITUATION_ALLOW_DATA_FALLBACK", True):
            events = [
                event async for event in orchestrator.real_generate("指标态势", "r_partial", None, {})
            ]

        self.assertIn("error", [event_type for event_type, _ in events])
        chart = next(data for event_type, data in events if event_type == "chart")
        values = chart["option"]["series"][0]["data"]
        self.assertEqual(values, [88.0, 76.0])
        self.assertEqual(events[-1][1]["status"], "partial")

    def test_parameters_execute_before_orchestration(self):
        bundles = [{
            "source": "t_equipment", "summary": "3 rows", "rows": 3,
            "payload": {"rows": [
                {"区域": "A", "完好率": 91},
                {"区域": "B", "完好率": 83},
                {"区域": "A", "完好率": 72},
            ]},
        }]
        profile = {
            "parameterBindings": {
                "区域": {"operator": "equals", "field": "区域"},
                "阈值": {"operator": "numeric-threshold", "field": "完好率"},
                "Top N": {"operator": "limit"},
            },
            "workflow": [{"sequence": 1, "operator": "collect"}],
        }
        context = {"skill": {"parameters": {"区域": "A", "阈值": 80, "Top N": 1}}}
        transformed = orchestrator._apply_execution_plan(bundles, profile, context)
        self.assertEqual(transformed[0]["payload"]["rows"], [{"区域": "A", "完好率": 91}])
        self.assertEqual(transformed[0]["execution"]["inputRows"], 3)
        self.assertEqual(transformed[0]["execution"]["outputRows"], 1)

    def test_llm_evidence_is_aggregated_and_sensitive_fields_removed(self):
        bundle = {
            "datasetId": "real_1", "source": "dataset:ds_a", "summary": "rows",
            "payload": {"rows": [
                {"区域": "A", "数量": 2, "姓名": "张三", "apiKey": "secret"},
                {"区域": "A", "数量": 3, "姓名": "李四", "apiKey": "secret2"},
            ]},
        }
        payload = orchestrator._prompt_payload([bundle])[0]
        self.assertNotIn("姓名", payload["columns"])
        self.assertNotIn("apiKey", payload["columns"])
        self.assertEqual(payload["numericStats"]["数量"]["sum"], 5)
        self.assertEqual(payload["samples"], [])

    def test_unverifiable_chart_and_unsafe_option_are_rejected(self):
        bundles = [{
            "datasetId": "real_1", "source": "test", "payload": {"rows": [{"value": 3}]},
        }]
        profile = orchestrator._skill_profile(None)
        base = {"charts": [{
            "chartId": "c", "type": "bar", "datasetRef": "real_1",
            "option": {"series": [{"type": "bar", "data": [99]}]},
        }]}
        with self.assertRaisesRegex(ValueError, "无法由证据"):
            orchestrator._validate_llm_result(base, profile, bundles)
        base["charts"][0]["option"] = {
            "series": [{"type": "bar", "data": [3]}],
            "image": "https://attacker.invalid/a.png",
        }
        with self.assertRaisesRegex(ValueError, "外部资源"):
            orchestrator._validate_llm_result(base, profile, bundles)


class SharedSSESessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_subscribers_share_one_generation_and_resume_by_event_id(self):
        calls = 0

        async def fake_generate(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            yield "dataset", {"datasetId": "real_1", "source": "test", "summary": "real", "rows": 1}
            await asyncio.sleep(0)
            yield "done", {"reportId": "r_shared", "status": "ready", "partial": False}

        report = Report(reportId="r_shared", title="test", query="test")
        session = main._GenerationSession(report, None, {})

        async def collect(cursor=0):
            return [chunk async for chunk in main._stream_session(session, cursor)]

        with patch.object(main, "generate", fake_generate), \
             patch.object(main, "_persist", return_value=True), \
             patch.object(main, "_finish_skill_usage"):
            task = asyncio.create_task(main._run_generation("r_shared", session))
            first, second = await asyncio.gather(collect(), collect())
            await task
            resumed = await collect(cursor=1)

        self.assertEqual(calls, 1)
        self.assertEqual(first, second)
        self.assertTrue(any("event: dataset" in chunk for chunk in first))
        self.assertTrue(any("event: done" in chunk for chunk in first))
        self.assertFalse(any("event: dataset" in chunk for chunk in resumed))
        self.assertTrue(any("id: 2" in chunk and "event: done" in chunk for chunk in resumed))


if __name__ == "__main__":
    unittest.main()
