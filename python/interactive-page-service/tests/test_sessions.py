"""对话式会话与消息 CRUD + 存量迁移测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from store import page_store


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ipage-session-test-")
        config.IPAGE_DB = os.path.join(self.tmpdir, "test_sessions.sqlite3")
        page_store._initialized = False
        page_store.init_db()

    def _page(self, page_id="p1", user="u1", status="ready", intent="data_page"):
        return {
            "id": page_id,
            "title": "测试页面",
            "query": "问题",
            "userId": user,
            "teamIds": [],
            "status": status,
            "intent": intent,
            "directAnswer": "",
            "html": "<!DOCTYPE html><body>x</body></html>",
            "dataBundle": {},
            "plan": {},
            "parentId": "",
            "sessionId": "",
            "sqlLog": [],
            "error": "",
        }

    def test_create_and_list_sessions(self):
        s = page_store.create_session("u1", [], "测试会话")
        self.assertTrue(s["sessionId"].startswith("s_"))
        result = page_store.list_sessions("u1", [], 1, 10)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["title"], "测试会话")

    def test_append_message_and_get_session(self):
        s = page_store.create_session("u1", [], "测试")
        sid = s["sessionId"]
        page_store.append_message(sid, "user", "text", "你好")
        page_store.append_message(sid, "ai", "direct", "已完成", page_id="")
        detail = page_store.get_session(sid)
        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["messages"]), 2)
        self.assertEqual(detail["messages"][0]["role"], "user")
        self.assertEqual(detail["messages"][1]["kind"], "direct")

    def test_set_page_session(self):
        page_store.upsert_page(self._page("p1"))
        s = page_store.create_session("u1", [], "测试")
        self.assertTrue(page_store.set_page_session("p1", s["sessionId"]))
        page = page_store.get_page("p1")
        self.assertEqual(page["sessionId"], s["sessionId"])
        # get_session 应该在 pages 列表中列出该页面
        detail = page_store.get_session(s["sessionId"])
        self.assertEqual(len(detail["pages"]), 1)
        self.assertEqual(detail["pages"][0]["pageId"], "p1")

    def test_delete_session_removes_messages(self):
        s = page_store.create_session("u1", [], "测试")
        sid = s["sessionId"]
        page_store.append_message(sid, "user", "text", "问题")
        self.assertTrue(page_store.delete_session(sid))
        self.assertIsNone(page_store.get_session(sid))

    def test_delete_messages_by_page(self):
        s = page_store.create_session("u1", [], "测试")
        sid = s["sessionId"]
        page_store.append_message(sid, "ai", "page_card", '{"pageId":"p1"}', page_id="p1")
        page_store.delete_messages_by_page("p1")
        detail = page_store.get_session(sid)
        self.assertEqual(len(detail["messages"]), 0)

    def test_legacy_migration(self):
        """存量页面（session_id 为空）应在 init_db 时迁移到历史记录会话。"""
        page_store.upsert_page(self._page("p1", user="u1", status="ready"))
        page_store.upsert_page(self._page("p2", user="u1", status="ready", intent="general"))
        page_store.upsert_page(self._page("p3", user="u1", status="failed"))
        # 重新 init 触发迁移
        page_store._initialized = False
        page_store.init_db()
        sessions = page_store.list_sessions("u1", [], 1, 10)
        self.assertEqual(sessions["total"], 1)
        self.assertEqual(sessions["items"][0]["title"], "历史记录")
        detail = page_store.get_session(sessions["items"][0]["sessionId"])
        # 三个页面各 2 条消息（user + ai），共 6 条
        self.assertEqual(len(detail["messages"]), 6)
        self.assertEqual(len(detail["pages"]), 3)
        # 迁移过的页面 session_id 应已回填
        self.assertEqual(page_store.get_page("p1")["sessionId"], detail["sessionId"])


if __name__ == "__main__":
    unittest.main()
