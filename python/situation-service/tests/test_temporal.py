from __future__ import annotations

import datetime as dt
import unittest

from temporal import apply_temporal_constraints, build_temporal_instruction, resolve_temporal_context
from agent.orchestrator import _real_generate_v2_body


NOW = dt.datetime(2026, 9, 2, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))


class TemporalContextTests(unittest.TestCase):
    def test_absolute_as_of_date_is_strict_snapshot(self):
        temporal = resolve_temporal_context("回溯到2026年8月15日的装备态势", now=NOW)

        self.assertTrue(temporal["active"])
        self.assertEqual(temporal["mode"], "as_of")
        self.assertTrue(temporal["strict"])
        self.assertIn("2026-08-15", temporal["end"])
        self.assertIn("禁止使用该时点之后的数据", build_temporal_instruction(temporal))

    def test_selected_range_has_priority_over_query_relative_time(self):
        temporal = resolve_temporal_context(
            "分析近7天态势",
            {"selectedTimeRange": [
                dt.datetime(2026, 7, 1, tzinfo=NOW.tzinfo).timestamp() * 1000,
                dt.datetime(2026, 7, 31, tzinfo=NOW.tzinfo).timestamp() * 1000,
            ]},
            now=NOW,
        )

        self.assertEqual(temporal["source"], "selected-range")
        self.assertEqual(temporal["label"], "2026-07-01 至 2026-07-31")

    def test_relative_period_is_resolved_deterministically(self):
        temporal = resolve_temporal_context("回看上周的行动态势", now=NOW)

        self.assertEqual(temporal["mode"], "range")
        self.assertIn("2026-08-24", temporal["start"])
        self.assertIn("2026-08-30", temporal["end"])

    def test_precise_timestamp_and_recent_hours_are_supported(self):
        snapshot = resolve_temporal_context("回溯到 2026-08-15 13:30 的态势", now=NOW)
        recent = resolve_temporal_context("分析近24小时态势演化", now=NOW)

        self.assertEqual(snapshot["mode"], "as_of")
        self.assertIn("13:30", snapshot["end"])
        self.assertEqual(recent["mode"], "range")
        self.assertEqual(recent["label"], "近 24 小时")

    def test_unspecified_history_request_requires_boundary(self):
        temporal = resolve_temporal_context("请生成历史态势回溯", now=NOW)

        self.assertTrue(temporal["requiresClarification"])
        self.assertEqual(temporal["label"], "待明确的历史时间范围")

    def test_plan_gets_real_time_field_and_drops_unsupported_dataset(self):
        plan = {
            "intent": "situation",
            "subQuestions": [
                {"id": "q1", "question": "查询轨迹", "datasetId": "with_time"},
                {"id": "q2", "question": "查询静态表", "datasetId": "without_time"},
            ],
            "chartSpecs": [
                {"id": "c1", "type": "line", "title": "趋势", "subQuestionRef": "q1"},
                {"id": "c2", "type": "bar", "title": "静态", "subQuestionRef": "q2"},
            ],
            "mapSpecs": [],
        }
        meta = {"success": True, "data": {"schemas": [
            {"datasetId": "with_time", "fields": [
                {"column": "record_time", "type": "datetime", "businessMeaning": "记录时间"},
                {"column": "value", "type": "decimal"},
            ]},
            {"datasetId": "without_time", "fields": [{"column": "name", "type": "varchar"}]},
        ]}}
        temporal = resolve_temporal_context("分析2026-08-01到2026-08-15的变化", now=NOW)

        constrained = apply_temporal_constraints(plan, temporal, meta)

        self.assertEqual(len(constrained["subQuestions"]), 1)
        self.assertEqual(len(constrained["chartSpecs"]), 1)
        boundary = constrained["subQuestions"][0]["filters"]["record_time"]
        self.assertIn("2026-08-01", boundary["gte"])
        self.assertIn("2026-08-15", boundary["lte"])
        self.assertEqual(constrained["_temporal"]["unsupportedSubQuestionIds"], ["q2"])


class TemporalOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_unspecified_history_request_answers_without_querying_current_data(self):
        events = [
            event async for event in _real_generate_v2_body(
                "请生成历史态势回溯",
                "r_temporal_clarification",
                runtime_context={},
            )
        ]

        self.assertEqual([event_type for event_type, _ in events], ["plan", "narrative", "done"])
        self.assertEqual(events[0][1]["status"], "needs-time-range")
        self.assertIn("不会用当前数据替代", events[1][1]["intro"])
        self.assertEqual(events[-1][1]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
