"""SQLite 页面产物存储 CRUD 与团队可见性测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from store import page_store


class PageStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ipage-test-")
        config.IPAGE_DB = os.path.join(self.tmpdir, "test_pages.sqlite3")
        page_store._initialized = False
        page_store.init_db()

    def _page(self, page_id="p1", user="u1", teams=None):
        return {
            "id": page_id,
            "title": "测试页面",
            "query": "问题",
            "userId": user,
            "teamIds": teams or [],
            "status": "ready",
            "intent": "data_page",
            "directAnswer": "",
            "html": "<!DOCTYPE html><html><body>x</body></html>",
            "dataBundle": {"datasets": []},
            "plan": {"intent": "data_page"},
            "parentId": "",
            "sqlLog": [{"qid": "q1"}],
            "error": "",
        }

    def test_upsert_and_get(self):
        self.assertTrue(page_store.upsert_page(self._page()))
        item = page_store.get_page("p1")
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "测试页面")
        self.assertEqual(item["dataBundle"], {"datasets": []})
        self.assertEqual(item["sqlLog"], [{"qid": "q1"}])
        self.assertEqual(item["pageId"], "p1")

    def test_update_overwrites(self):
        page_store.upsert_page(self._page())
        page = self._page()
        page["title"] = "更新后"
        page["status"] = "ready"
        page_store.upsert_page(page)
        item = page_store.get_page("p1")
        self.assertEqual(item["title"], "更新后")
        self.assertEqual(len(page_store.list_pages("u1", [], 1, 10)["items"]), 1)

    def test_team_visibility(self):
        page_store.upsert_page(self._page("p-team", user="owner", teams=["t1", "t2"]))
        # 同团队可见
        self.assertEqual(page_store.list_pages("other", ["t1"], 1, 10, role="viewer")["total"], 1)
        # 无关用户不可见
        self.assertEqual(page_store.list_pages("stranger", [], 1, 10, role="viewer")["total"], 0)
        # admin 全可见
        self.assertEqual(page_store.list_pages("admin", [], 1, 10, role="admin")["total"], 1)
        # 本人可见
        self.assertEqual(page_store.list_pages("owner", ["other-team"], 1, 10, role="viewer")["total"], 1)

    def test_list_summary_has_no_html(self):
        page_store.upsert_page(self._page())
        items = page_store.list_pages("u1", [], 1, 10)["items"]
        self.assertNotIn("html", items[0])
        self.assertTrue(items[0]["hasHtml"])

    def test_delete(self):
        page_store.upsert_page(self._page())
        self.assertTrue(page_store.delete_page("p1"))
        self.assertIsNone(page_store.get_page("p1"))
        self.assertFalse(page_store.delete_page("p1"))


if __name__ == "__main__":
    unittest.main()
