import asyncio
import datetime as dt
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
        self.assertEqual(events[3][1]["verification"]["method"], "empty-without-coordinate-evidence")
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
        events = orchestrator._workflow_events({
            **profile,
            "workflow": [
                {"sequence": 1, "name": "读取", "operator": "collect"},
                {"sequence": 2, "name": "筛选", "operator": "filter"},
                {"sequence": 3, "name": "聚合", "operator": "transform"},
                {"sequence": 4, "name": "可视化", "operator": "visualize"},
            ],
            "focusMetrics": ["完好率"], "chartTypes": ["bar"], "mapLayerTypes": ["points"],
        }, transformed)
        self.assertEqual([event["operator"] for event in events], ["collect", "filter", "transform", "visualize"])
        self.assertEqual(events[1]["appliedOperators"][0]["operator"], "equals")
        self.assertEqual(events[2]["focusMetrics"], ["完好率"])
        self.assertEqual(events[3]["plannedCharts"], 1)

    def test_empty_time_window_is_relaxed_progressively(self):
        now = dt.datetime.now(dt.timezone.utc)
        bundles = [{
            "source": "t_threat", "summary": "2 rows", "rows": 2,
            "payload": {"rows": [
                {"region": "A", "detect_time": (now - dt.timedelta(days=2)).isoformat()},
                {"region": "B", "detect_time": (now - dt.timedelta(days=8)).isoformat()},
            ]},
        }]
        profile = {"parameterBindings": {"时间范围": {"operator": "time-window", "field": "时间范围"}}}
        context = {"skill": {"parameters": {"时间范围": "近24小时"}}}
        # 近 24 小时全空 → 近 7 天命中（2 天前的记录保留、8 天前的被过滤）
        transformed, notice = orchestrator._relax_empty_time_windows(bundles, profile, context)
        self.assertEqual(notice, "所选时间范围无匹配数据，已自动放宽为近 7 天")
        self.assertEqual(len(transformed[0]["payload"]["rows"]), 1)
        self.assertEqual(transformed[0]["payload"]["rows"][0]["region"], "A")
        self.assertEqual(transformed[0]["execution"]["outputRows"], 1)

    def test_relaxation_keeps_original_when_non_time_filters_exclude_everything(self):
        now = dt.datetime.now(dt.timezone.utc)
        bundles = [{
            "source": "t_threat", "summary": "1 row", "rows": 1,
            "payload": {"rows": [
                {"threat_level": "低", "detect_time": (now - dt.timedelta(days=2)).isoformat()},
            ]},
        }]
        profile = {"parameterBindings": {
            "威胁等级": {"operator": "equals", "field": "threat_level"},
            "时间范围": {"operator": "time-window", "field": "时间范围"},
        }}
        context = {"skill": {"parameters": {"威胁等级": "高", "时间范围": "近24小时"}}}
        # 威胁等级=高 排空全部记录，放宽时间窗也无效，保持原结果交由调用方报错
        transformed, notice = orchestrator._relax_empty_time_windows(bundles, profile, context)
        self.assertIsNone(notice)
        self.assertIs(transformed, bundles)

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

    @patch.object(orchestrator, "call_llm_json")
    def test_five_stage_llm_protocol_never_sends_raw_rows(self, call_llm):
        bundle = {
            "datasetId": "real_1", "source": "dataset:ds_a", "summary": "rows",
            "payload": {"rows": [{"区域": "A", "数量": 2, "姓名": "张三"}]},
        }
        call_llm.side_effect = [
            {"datasets": [{"datasetId": "real_1"}], "chartsPlan": [{"type": "bar", "title": "数量"}]},
            # series 数值必须可由证据复算，否则会触发纠错重试（多一次 LLM 调用）
            [{"chartId": "c_1", "type": "bar", "datasetRef": "real_1", "option": {"series": [{"type": "bar", "data": [2]}]}}],
            {"layerId": "main", "points": []},
            {"intro": "介绍", "explanations": []},
        ]
        result = orchestrator._run_llm_orchestration(
            "test", orchestrator._skill_profile(None), {}, [bundle],
        )
        self.assertEqual(call_llm.call_count, 4)
        self.assertIn("charts", result)
        all_messages = str([call.args[0] for call in call_llm.call_args_list])
        self.assertNotIn("张三", all_messages)
        self.assertNotIn("姓名", all_messages)
        self.assertIn("numericStats", all_messages)

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

    async def test_selected_database_filters_authorized_catalog(self):
        profile = orchestrator._skill_profile({"dataSources": ["t_equipment"]})
        catalog = {"success": True, "datasets": [
            {"id": "ds_a", "tableName": "t_equipment", "databaseId": "db_a"},
            {"id": "ds_b", "tableName": "t_equipment", "databaseId": "db_b"},
        ]}
        with patch.object(orchestrator.tools, "list_admin_datasets", return_value=catalog), \
             patch.object(orchestrator.tools, "query_admin_dataset", return_value={
                 "success": True, "rows": [{"value": 1}], "dataset": {"id": "ds_b"},
             }) as query:
            bundles, failures = await orchestrator._collect_real_data(
                "test", profile, {"dataSourceId": "db_b", "_actor": {"userId": "alice"}},
            )
        self.assertEqual(failures, [])
        self.assertEqual(len(bundles), 1)
        self.assertEqual(query.call_args.args[0]["id"], "ds_b")


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
