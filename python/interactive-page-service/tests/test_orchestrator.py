"""Orchestrator 修订分支测试：新页面必须继承父页面的取数上下文与元数据。

背景：修订分支曾只把父页面 plan/dataBundle 取到局部变量，未落库，导致修订产物
intent=''、dataBundle={} —— 离开当前会话后重新加载时前端走占位符、无数据渲染，
即“修改后的页面打不开、不显示”。
"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from agent import orchestrator
from models import PageRecord
from store import page_store

PARENT_HTML = "<!DOCTYPE html><html lang=\"zh-CN\"><body>父页面</body></html>"


class _FakeWriter:
    """替身：跳过真实 LLM 调用，直接返回校验通过的重设计结果。"""

    def redesign(self, query, plan, bundle, previous_html, feedback):
        return "<!DOCTYPE html><html><body>重新设计</body></html>", {
            "usedTemplate": False, "revised": True, "issues": [],
        }


class RevisionMetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ipage-orch-test-")
        config.IPAGE_DB = os.path.join(self.tmpdir, "orch_pages.sqlite3")
        page_store._initialized = False
        page_store.init_db()
        page_store.upsert_page({
            "id": "parent1",
            "title": "红蓝空中力量对比分析",
            "query": "红蓝空中力量对比",
            "userId": "u1",
            "teamIds": [],
            "status": "ready",
            "intent": "data_page",
            "directAnswer": "",
            "html": PARENT_HTML,
            "dataBundle": {"question": "红蓝空中力量对比", "datasets": [{"id": "q1"}]},
            "plan": {"title": "红蓝空中力量对比分析", "intent": "data_page", "subQuestions": []},
            "parentId": "",
            "sqlLog": [{"qid": "q1", "sql": "select 1"}],
            "error": "",
        })

    async def _collect(self, page):
        return [ev async for ev in orchestrator.generate_stream(page, {}, page.query)]

    def test_revision_inherits_parent_metadata(self):
        page = PageRecord(pageId="child1", userId="u1", query="加入飞行轨迹以及动态演示",
                          parentId="parent1")
        with mock.patch.object(orchestrator, "PageWriter", lambda: _FakeWriter()):
            events = asyncio.run(self._collect(page))

        # plan 事件带标题，前端不必等 done 事件才有标题
        plan_event = next(e for e in events if e["event"] == "plan")
        self.assertTrue(plan_event["data"].get("reused"))
        self.assertEqual(plan_event["data"].get("title"), "红蓝空中力量对比分析")

        stored = page_store.get_page("child1")
        self.assertEqual(stored["status"], "ready")
        # 关键断言：修订产物自带取数上下文与元数据，可脱离当前会话重新加载
        self.assertEqual(stored["intent"], "data_page")
        self.assertEqual(stored["title"], "红蓝空中力量对比分析")
        self.assertEqual(stored["plan"], {"title": "红蓝空中力量对比分析",
                                          "intent": "data_page", "subQuestions": []})
        self.assertEqual(stored["dataBundle"]["datasets"], [{"id": "q1"}])
        self.assertEqual(stored["sqlLog"], [{"qid": "q1", "sql": "select 1"}])
        # 修改意见仍记录在 query 中
        self.assertEqual(stored["query"], "加入飞行轨迹以及动态演示")

    def test_revision_falls_back_when_parent_missing(self):
        """父页面不存在时按既有行为失败，不产生半成品页面。"""
        page = PageRecord(pageId="child2", userId="u1", query="改一下", parentId="missing")
        events = asyncio.run(self._collect(page))

        self.assertEqual(events[-1]["event"], "error")
        stored = page_store.get_page("child2")
        self.assertEqual(stored["status"], "failed")


class IncrementalRevisionTest(unittest.TestCase):
    """修订增量取数：只补取新增/变更子问题，航迹进入数据包后才有时间轴。

    背景：修订曾无条件复用父页面数据包，而父规划从未取过航迹表，
    因此「加入飞行轨迹以及动态演示」这类取数需求在修订链路上永远无法生效。
    """

    async def _collect_events(self, page):
        """在事件循环内收集编排事件（异步推导式不能在同步函数中使用）。"""
        return [ev async for ev in orchestrator.generate_stream(page, {}, page.query)]

    def test_diff_detects_new_and_changed_only(self):
        parent = {"subQuestions": [
            {"id": "q1", "datasetId": "ds-a", "question": "总量",
             "mode": "aggregate", "geo": "none"},
            {"id": "q2", "datasetId": "ds-b", "question": "分布",
             "mode": "aggregate", "geo": "none"},
        ]}
        new = {"subQuestions": [
            dict(parent["subQuestions"][0]),                          # 原样沿用 → 不取数
            {**parent["subQuestions"][1], "question": "按阵营分布"},   # 口径变化 → 取数
            {"id": "q3", "datasetId": "ds-track", "question": "航迹",
             "mode": "detail", "geo": "tracks"},                      # 新增 → 取数
        ]}
        added = orchestrator._diff_sub_questions(parent, new)
        self.assertEqual([sq["id"] for sq in added], ["q2", "q3"])

    def test_merge_reuses_parent_entries_and_builds_timeline(self):
        parent_entries = [{"id": "q1", "name": "总量"}, {"id": "q2", "name": "分布"}]
        parent_logs = [{"qid": "q1", "sql": "select 1"}, {"qid": "q2", "sql": "select 2"}]
        new_entries = [{
            "id": "q3", "name": "航迹",
            "geoFeatures": {"tracks": [{"id": "ac1", "name": "侦察01", "faction": "蓝方",
                                        "points": [{"time": "2026-03-01 08:00:00"},
                                                   {"time": "2026-03-01 09:00:00"}]}]},
        }]
        new_plan = {
            "subQuestions": [
                {"id": "q1", "datasetId": "ds-a", "question": "总量"},
                {"id": "q2", "datasetId": "ds-b", "question": "分布"},
                {"id": "q3", "datasetId": "ds-track", "question": "航迹"},
                {"id": "q4", "datasetId": "ds-none", "question": "取数失败的表"},
            ],
            "sections": [
                {"id": "s1", "kind": "chart", "ref": "q1"},
                {"id": "s2", "kind": "map", "ref": "q3"},
                {"id": "s3", "kind": "chart", "ref": "q4"},
                {"id": "s4", "kind": "text", "ref": ""},
            ],
        }
        entries, logs, available = orchestrator._merge_incremental(
            new_plan, parent_entries, parent_logs, new_entries, [{"qid": "q3"}])

        # 未变化的 q1/q2 沿用父条目，新增 q3 用本次取数结果，无数据的 q4 被剔除
        self.assertEqual([e["id"] for e in entries], ["q1", "q2", "q3"])
        self.assertEqual([l["qid"] for l in logs], ["q1", "q2", "q3"])
        self.assertEqual(available, {"q1", "q2", "q3"})
        self.assertEqual([sq["id"] for sq in new_plan["subQuestions"]], ["q1", "q2", "q3"])
        self.assertEqual([s["id"] for s in new_plan["sections"]], ["s1", "s2", "s4"])
        # 航迹带时间 → 时间轴（动态演示）才有据可依
        timeline = orchestrator.build_map_timeline(entries)
        self.assertIsNotNone(timeline)
        self.assertEqual(timeline["startDate"], "2026-03-01")

    def test_revision_fetches_only_incremental_sub_questions(self):
        tmpdir = tempfile.mkdtemp(prefix="ipage-orch-inc-")
        config.IPAGE_DB = os.path.join(tmpdir, "orch_inc.sqlite3")
        page_store._initialized = False
        page_store.init_db()
        page_store.upsert_page({
            "id": "parent-inc", "title": "空中力量对比", "query": "红蓝空中力量对比",
            "userId": "u1", "teamIds": [], "status": "ready", "intent": "data_page",
            "directAnswer": "", "html": PARENT_HTML,
            "dataBundle": {"question": "红蓝空中力量对比",
                           "datasets": [{"id": "q1", "name": "总量"}]},
            "plan": {"intent": "data_page", "title": "空中力量对比", "subQuestions": [
                {"id": "q1", "datasetId": "ds-a", "question": "总量",
                 "mode": "aggregate", "geo": "none"}],
                "sections": [{"id": "s1", "kind": "chart", "ref": "q1"}]},
            "parentId": "", "sqlLog": [{"qid": "q1", "sql": "select 1"}], "error": "",
        })

        class _FakePlanner:
            def __init__(self, meta):
                pass

            def plan(self, query, parent_query="", parent_plan=None):
                return {
                    "intent": "data_page", "title": "空中力量对比",
                    "subQuestions": [
                        {"id": "q1", "datasetId": "ds-a", "question": "总量",
                         "mode": "aggregate", "geo": "none"},
                        {"id": "q6", "datasetId": "ds-track", "question": "飞行轨迹",
                         "mode": "detail", "geo": "tracks"},
                    ],
                    "sections": [{"id": "s1", "kind": "chart", "ref": "q1"},
                                 {"id": "s2", "kind": "map", "ref": "q6"}],
                }

        fetched = []

        async def fake_research(plan, meta, query, entity_scope=None, entity_hits=None):
            fetched.extend(str(sq.get("id")) for sq in plan.get("subQuestions") or [])
            yield ("__datasets__", {"entries": [{
                "id": "q6", "name": "航迹",
                "geoFeatures": {"tracks": [{"id": "ac1", "name": "侦察01",
                                            "points": [{"time": "2026-03-01 08:00:00"},
                                                       {"time": "2026-03-01 08:30:00"}]}]},
            }], "sqlLog": [{"qid": "q6"}]})

        page = PageRecord(pageId="child3", userId="u1",
                          query="加入飞行轨迹以及动态演示", parentId="parent-inc")
        with mock.patch.object(orchestrator, "Planner", _FakePlanner), \
                mock.patch.object(orchestrator, "_research_all", fake_research), \
                mock.patch.object(orchestrator, "PageWriter", lambda: _FakeWriter()):
            events = asyncio.run(self._collect_events(page))

        # 只为新增子问题 q6 取数，q1 直接继承父页面数据（不重复查询）
        self.assertEqual(fetched, ["q6"])
        page_event = next(e for e in events if e["event"] == "page")
        bundle = page_event["data"]["bundle"]
        self.assertEqual([d["id"] for d in bundle["datasets"]], ["q1", "q6"])
        self.assertEqual(bundle["question"], "红蓝空中力量对比")
        self.assertIsNotNone(bundle.get("mapTimeline"))
        stored = page_store.get_page("child3")
        self.assertEqual([d["id"] for d in stored["dataBundle"]["datasets"]], ["q1", "q6"])
        self.assertEqual([s["qid"] for s in stored["sqlLog"]], ["q1", "q6"])


if __name__ == "__main__":
    unittest.main()