import unittest
from unittest.mock import patch
from starlette.requests import Request

from agent import tools
from main import _actor


class DataSecurityTests(unittest.TestCase):
    def test_unsigned_identity_headers_are_downgraded(self):
        request = Request({
            "type": "http", "method": "GET", "path": "/", "query_string": b"",
            "headers": [(b"x-user-id", b"victim"), (b"x-user-role", b"admin")],
            "server": ("test", 80), "client": ("test", 1), "scheme": "http",
        })
        actor = _actor(request)
        self.assertEqual(actor["userId"], "local-user")
        self.assertEqual(actor["role"], "viewer")
        self.assertFalse(actor["trusted"])

    @patch("agent.tools._http_json")
    def test_dataset_query_uses_server_template_not_stored_sql(self, http_json):
        http_json.return_value = {"success": True, "rows": []}
        dataset = {
            "id": "ds_safe", "tableName": "equipment",
            "sql": "SELECT * FROM unrelated_secret_table",
        }
        tools.query_admin_dataset(dataset, 20)
        _, url, body = http_json.call_args.args[:3]
        self.assertTrue(url.endswith("/api/admin/dataset/ds_safe/query"))
        self.assertEqual(body, {"limit": 20})
        self.assertNotIn("sql", body)

    def test_actor_headers_propagate_to_downstream(self):
        with tools.actor_context({"userId": "alice", "teamIds": ["red"], "role": "viewer"}):
            headers = tools._identity_headers()
        self.assertEqual(headers["X-User-Id"], "alice")
        self.assertEqual(headers["X-Team-Ids"], "red")
        self.assertTrue(headers["X-Service-Token"])


if __name__ == "__main__":
    unittest.main()
