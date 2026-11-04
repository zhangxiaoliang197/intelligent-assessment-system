"""评估产物模式编排测试：跳过规划/取数，直接生成页面；评估产物页修订不重新规划。"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from agent import orchestrator
from models import ArtifactItem, EvaluationArtifacts, PageRecord
from store import page_store

PAGE_HTML = "<!DOCTYPE html><html><body>评估态势页面</body></html>"


class _FakeWriter:
    """替身：跳过真实 LLM，直接返回页面并记录调用参数。"""

    def __init__(self):
        self.generate_calls = []
        self.redesign_calls = []

    def generate(self, query, plan, bundle, skill_context=None):
        self.generate_calls.append({"query": query, "plan": plan, "bundle": bundle})
        return PAGE_HTML, {"usedTemplate": False, "issues": []}

    def redesign(self, query, plan, bundle, previous_html, feedback, skill_context=None):
        self.redesign_calls.append({"query": query, "plan": plan, "feedback": feedback})
        return PAGE_HTML, {"usedTemplate": False, "revised": True, "issues": []}


def _artifacts() -> EvaluationArtifacts:
    return EvaluationArtifacts(
        sourceSessionId="eval-1",
        question="红蓝空中力量对比",
        title="评估态势",
        conclusion="红方数量略占优",
        presentation={"kpi": True, "chart": True, "map": False, "table": False},
        items=[
            ArtifactItem(
                artifactId="q1", name="红方统计", purpose="统计红方机型数量",
                mode="aggregate", columns=["机型", "数量"],
                rows=[{"机型": "歼-20", "数量": 3}, {"机型": "歼-16", "数量": 5}],
                totalRows=2,
            ),
            ArtifactItem(
                artifactId="q2", name="蓝方统计", purpose="统计蓝方机型数量",
                mode="aggregate", columns=["机型", "数量"],
                rows=[{"机型": "F-16", "数量": 4}], totalRows=1,
            ),
        ],
    )


class EvaluationArtifactOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ipage-eval-test-")
        config.IPAGE_DB = os.path.join(self.tmpdir, "eval_pages.sqlite3")
        page_store._initialized = False
        page_store.init_db()

    async def _collect(self, page, artifacts=None, meta=None):
        return [ev async for ev in orchestrator.generate_stream(
            page, meta or {}, page.query, artifacts=artifacts)]

    def test_artifact_mode_generates_without_planner(self):
        """产物模式：事件为 plan/dataset/page/done，规划与取数完全不参与。"""
        page = PageRecord(pageId="evalpage1", userId="u1", query="红蓝空中力量对比")
        writer = _FakeWriter()
        with mock.patch.object(orchestrator, "PageWriter", lambda: writer), \
                mock.patch.object(orchestrator, "Planner",
                                  side_effect=AssertionError("产物模式不应调用 Planner")):
            events = asyncio.run(self._collect(page, artifacts=_artifacts()))

        kinds = [e["event"] for e in events]
        self.assertIn("plan", kinds)
        self.assertEqual(kinds.count("dataset"), 2)
        self.assertIn("page", kinds)
        self.assertEqual(kinds[-1], "done")

        stored = page_store.get_page("evalpage1")
        self.assertEqual(stored["status"], "ready")
        self.assertEqual([d["id"] for d in stored["dataBundle"]["datasets"]], ["q1", "q2"])
        self.assertEqual(stored["plan"]["origin"]["type"], "evaluation")
        self.assertEqual(writer.generate_calls[0]["query"], "红蓝空中力量对比")

    def test_artifact_mode_rejects_parent(self):
        """产物模式不允许基于历史页面修订。"""
        page = PageRecord(pageId="evalpage2", userId="u1", query="x", parentId="p1")
        events = asyncio.run(self._collect(page, artifacts=_artifacts()))
        self.assertEqual(events[-1]["event"], "error")

    def test_evaluation_page_revision_uses_redesign_only(self):
        """评估产物页修订：只调 redesign，不调 Planner / 增量取数。"""
        parent_plan = {
            "title": "评估态势", "intent": "data_page", "subQuestions": [],
            "sections": [{"id": "s1", "kind": "chart", "title": "红方统计", "ref": "q1"}],
            "interactions": [],
            "origin": {"type": "evaluation", "sessionId": "eval-1", "artifactIds": ["q1"]},
        }
        page_store.upsert_page({
            "id": "evalparent",
            "title": "评估态势",
            "query": "红蓝空中力量对比",
            "userId": "u1",
            "teamIds": [],
            "status": "ready",
            "intent": "data_page",
            "directAnswer": "",
            "html": PAGE_HTML,
            "dataBundle": {"question": "红蓝空中力量对比",
                           "datasets": [{"id": "q1", "name": "红方统计",
                                         "mode": "aggregate", "columns": ["机型", "数量"],
                                         "rows": [{"机型": "歼-20", "数量": 3}]}]},
            "plan": parent_plan,
            "parentId": "",
            "sessionId": "s1",
            "sqlLog": [],
            "error": "",
        })
        page = PageRecord(pageId="evalchild", userId="u1",
                          query="把图表改到第一屏", parentId="evalparent")
        writer = _FakeWriter()
        with mock.patch.object(orchestrator, "PageWriter", lambda: writer), \
                mock.patch.object(orchestrator, "Planner",
                                  side_effect=AssertionError("评估页修订不应重新规划")):
            events = asyncio.run(self._collect(page, artifacts=None))

        self.assertTrue(writer.redesign_calls)
        self.assertFalse(writer.generate_calls)
        stored = page_store.get_page("evalchild")
        self.assertEqual(stored["status"], "ready")
        self.assertEqual(stored["plan"]["origin"]["type"], "evaluation")
        self.assertEqual(stored["dataBundle"]["datasets"][0]["id"], "q1")
        self.assertEqual(events[-1]["event"], "done")


if __name__ == "__main__":
    unittest.main()
