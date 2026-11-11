"""页级时间轴（SitTimeline）后端契约测试。

覆盖：时间轴桶收敛与生成、三套 SQL 方言的桶表达式、Guard 时间轴规则、
Planner 对 timeseries 子问题与 timeline 区块的校验。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import guard, planner
from agent.researcher import (
    build_page_timeline, build_timeseries_sql, bucket_step_for, page_frame_step,
)


class TimelineBuilderTest(unittest.TestCase):
    """时间轴刻度：单日按目标帧数稀疏采样 + 跨多日沿用原逻辑 + 单桶不生成。"""

    def test_intraday_timeline_uses_target_frames(self):
        entries = [
            {
                "mode": "timeseries", "bucketSeconds": 3600,
                "rows": [{"bucketKey": "2026-07-16 08:00:00", "value": 3},
                         {"bucketKey": "2026-07-16 10:00:00", "value": 5}],
                "geoFeatures": {},
            },
            {
                "mode": "detail",
                "geoFeatures": {
                    "tracks": [{"points": [{"time": "2026-07-16 08:05:00"},
                                           {"time": "2026-07-16 09:35:00"}]}],
                    "units": [{"time": "2026-07-16 09:30:00"}],
                    "points": [],
                },
            },
        ]
        timeline = build_page_timeline(entries)
        self.assertIsNotNone(timeline)
        # 单日 2 小时跨度：目标 60 帧 → 3 分钟/帧，共约 41 帧，不能再退化为 1 分钟/帧
        self.assertEqual(timeline["bucketSeconds"], 180)
        self.assertEqual(timeline["startTime"], "2026-07-16 08:00:00")
        self.assertEqual(timeline["sources"], {"geo": True, "timeseries": True})
        self.assertLessEqual(len(timeline["buckets"]), 60)

    def test_intraday_tail_bucket_covers_end_event(self):
        entries = [{
            "mode": "detail",
            "geoFeatures": {
                "tracks": [{"points": [{"time": "2026-07-16 08:00:00"},
                                       {"time": "2026-07-16 10:03:08"}]}],
                "units": [], "points": [],
            },
        }]
        # 强制 5 分钟步长：对齐桶只到 10:00，必须补出精确的末尾帧，
        # 且该帧时刻不得早于事件时刻（10:03:08），否则事件永远不可见
        with mock.patch("config.IPAGE_TIMELINE_BUCKET", "5minute"):
            timeline = build_page_timeline(entries)
        self.assertIsNotNone(timeline)
        self.assertEqual(timeline["bucketSeconds"], 300)
        self.assertEqual(timeline["buckets"][-1]["t"], "2026-07-16 10:03:08")

    def test_multi_day_timeline_keeps_legacy_coarsening(self):
        entries = [{
            "mode": "detail",
            "geoFeatures": {
                "tracks": [{"points": [{"time": "2026-06-17 08:00:00"},
                                       {"time": "2026-07-16 10:03:08"}]}],
                "units": [], "points": [],
            },
        }]
        timeline = build_page_timeline(entries)
        self.assertIsNotNone(timeline)
        # 跨多日不走目标帧数采样，仍由最大桶数收敛到小时级
        self.assertGreaterEqual(timeline["bucketSeconds"], 3600)

    def test_page_frame_step_respects_target(self):
        # 2 小时跨度目标 60 帧 → 3 分钟档位；帧数不超过目标
        step = page_frame_step(2 * 3600, 60)
        self.assertEqual(step, 180)
        self.assertLessEqual(2 * 3600 / step + 1, 60)

    def test_single_bucket_returns_none(self):
        self.assertIsNone(build_page_timeline([{
            "mode": "timeseries", "bucketSeconds": 86400,
            "rows": [{"bucketKey": "2026-07-16 00:00:00", "value": 1}],
        }]))

    def test_bucket_step_coarsens_to_limit(self):
        # 跨度 30 天：1 分钟档位会超出上限，必须收敛到更粗的档位
        step = bucket_step_for(None, 30 * 86400)
        self.assertGreaterEqual(step, 3600)
        self.assertLessEqual(30 * 86400 / step, 600)


class TimeseriesSqlTest(unittest.TestCase):
    """确定性桶聚合 SQL：三种方言 + 分组 + 别名固定。"""

    COLUMNS = ["记录时间", "机型", "数量"]

    def test_dialect_bucket_expr(self):
        expects = {
            "mysql": "DATE_FORMAT",
            "postgresql": "to_char",
            "h2": "FORMATDATETIME",
        }
        for dialect, marker in expects.items():
            sql = build_timeseries_sql(
                dialect, "mock_track_point", self.COLUMNS, "记录时间", 300,
                ["机型"], {"agg": "count"}, {})
            self.assertIn(marker, sql)
            self.assertIn("AS bucketKey", sql)
            self.assertIn("AS value", sql)
            self.assertIn("GROUP BY 1, 2", sql)

    def test_metric_sum_and_filters(self):
        sql = build_timeseries_sql(
            "mysql", "t", self.COLUMNS, "记录时间", 3600, [],
            {"agg": "sum", "column": "数量"}, {"机型": ["侦察机"], "记录时间": {"gte": "2026-07-16"}})
        self.assertIn("SUM(", sql)
        self.assertIn("机型` IN (", sql)
        self.assertIn("记录时间` >= ", sql)


class TimelineGuardTest(unittest.TestCase):
    """Guard：页面时间轴契约（必须建轴、禁止双时钟、时序图表必须绑定）。"""

    HTML = """<!DOCTYPE html><html><head></head><body>
<p>页面级时间轴验证用静态文本，用于满足最小页面长度校验。时间轴应由页面唯一时钟驱动，
地图与图表都订阅同一条时间轴事件，不得各自维护播放器。该段文字需要足够长，
避免触发"页面内容过短"的守门规则。</p>
<script>
SitApp.bootstrap(function(data){
  SitTimeline.render('#tl', {axis:data.timeline.buckets});
  SitChart.render('#c', {type:'line', timeline:{mode:'trend'}, rows:data.datasets[0].rows});
});
</script></body></html>"""

    BUNDLE = {
        "timeline": {"buckets": [{"t": "2026-07-16 08:00:00"},
                                 {"t": "2026-07-16 08:01:00"}]},
        "datasets": [{"mode": "timeseries"}],
    }

    def test_valid_page_passes(self):
        self.assertEqual(guard.validate_page(self.HTML, self.BUNDLE), [])

    def test_missing_timeline_component(self):
        html = self.HTML.replace("SitTimeline.render", "")
        issues = guard.validate_page(html, self.BUNDLE)
        self.assertTrue(any("SitTimeline.render" in i for i in issues), issues)

    def test_double_clock_rejected(self):
        html = self.HTML + "\n<script>SitMap.render('#m', {timeline:true, playback:{}});</script>"
        issues = guard.validate_page(html, self.BUNDLE)
        self.assertTrue(any("双时钟" in i for i in issues), issues)

    def test_chart_timeline_binding_is_optional(self):
        # 图表联动按需：数据口径与地图时间对不上时允许静态展示，Guard 不再强制绑定
        html = self.HTML.replace("timeline:{mode:'trend'}", "xData:[]")
        self.assertEqual(guard.validate_page(html, self.BUNDLE), [])


class PlannerTimeseriesValidationTest(unittest.TestCase):
    """Planner：timeseries 必须 geo=none、必须有 timeline 区块、ref 必须指向时序/地理子问题。"""

    def setUp(self):
        self.plan = {
            "intent": "data_page", "title": "测试",
            "subQuestions": [{
                "id": "q1", "datasetId": "ds1", "question": "按时间统计",
                "mode": "timeseries", "geo": "none", "bucket": "minute",
                "groupBy": ["机型"],
            }],
            "sections": [
                {"id": "s1", "kind": "kpi", "title": "KPI"},
                {"id": "s2", "kind": "timeline", "title": "时间轴", "ref": "q1"},
                {"id": "s3", "kind": "chart", "title": "趋势", "ref": "q1"},
                {"id": "s4", "kind": "text", "title": "结论"},
            ],
        }

    def test_valid_timeseries_plan(self):
        err = planner._validate(self.plan, {"ds1"}, set(), None, {"ds1"})
        self.assertIsNone(err)

    def test_timeseries_requires_timeline_section(self):
        plan = dict(self.plan)
        plan["sections"] = [s for s in self.plan["sections"] if s["kind"] != "timeline"]
        err = planner._validate(plan, {"ds1"}, set(), None, {"ds1"})
        self.assertIsNotNone(err)
        self.assertIn("timeline", err)

    def test_timeseries_rejects_geo(self):
        plan = dict(self.plan)
        plan["subQuestions"] = [dict(self.plan["subQuestions"][0], geo="points")]
        err = planner._validate(plan, {"ds1"}, {"ds1"}, None, {"ds1"})
        self.assertIsNotNone(err)
        self.assertIn("geo", err)


if __name__ == "__main__":
    unittest.main()
