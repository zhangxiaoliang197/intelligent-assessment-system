import unittest
from unittest.mock import patch
from starlette.requests import Request
from fastapi.testclient import TestClient

from agent import tools
from main import _actor, app
import config
from models import DraftContext, DraftRequest
from store import draft as draft_store


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

    def test_invalid_signature_cannot_override_report_identity(self):
        client = TestClient(app)
        with patch("main.preflight_skill"), patch("main._run_generation", new=unittest.mock.AsyncMock()):
            response = client.post(
                "/situation/generate",
                headers={"X-User-Id": "victim", "X-User-Role": "admin", "X-Actor-Signature": "bad"},
                json={"query": "identity test", "userId": "body-admin", "teamIds": ["secret"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        report_id = response.json()["data"]["reportId"]
        import main
        report = main._INFLIGHT[report_id]
        self.assertEqual(report.userId, "local-user")
        self.assertEqual(report.teamIds, [])
        main._INFLIGHT.pop(report_id, None)
        main._STREAM_SESSIONS.pop(report_id, None)

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
        with patch.object(tools.config, "INTERNAL_SERVICE_TOKEN", "test-service-token"), \
             tools.actor_context({"userId": "alice", "teamIds": ["red"], "role": "viewer"}):
            headers = tools._identity_headers()
        self.assertEqual(headers["X-User-Id"], "alice")
        self.assertEqual(headers["X-Team-Ids"], "red")
        self.assertTrue(headers["X-Service-Token"])

    @patch("main.draft_store.create_draft", return_value="d_secure")
    def test_draft_body_identity_cannot_override_actor(self, create_draft):
        client = TestClient(app)
        response = client.post("/situation/draft", json={
            "source": "manual", "userId": "admin", "teamIds": ["secret-team"],
        })
        self.assertEqual(response.status_code, 200)
        draft = create_draft.call_args.args[0]
        self.assertEqual(draft.userId, "local-user")
        self.assertEqual(draft.teamIds, [])

    def test_draft_id_is_unpredictable_and_owner_scoped_one_time(self):
        draft_id = draft_store.create_draft(DraftRequest(
            context=DraftContext(query="owner-only"), userId="alice", teamIds=["red"],
        ))
        self.assertRegex(draft_id, r"^d_[0-9a-f]{32}$")
        self.assertIsNone(draft_store.get_draft(draft_id, user_id="mallory", team_ids=[]))
        owned = draft_store.get_draft(
            draft_id, user_id="alice", team_ids=[], consume=True,
        )
        self.assertEqual(owned["context"]["query"], "owner-only")
        self.assertIsNone(draft_store.get_draft(draft_id, user_id="alice", team_ids=[]))

    @patch("urllib.request.urlopen")
    def test_llm_config_uses_internal_service_endpoint(self, urlopen):
        from llm_client import load_llm_config

        response = unittest.mock.MagicMock()
        response.read.return_value = b'{"success":true,"data":{"type":"vllm","apiUrl":"http://localhost:1"}}'
        response.__enter__.return_value = response
        urlopen.return_value = response
        load_llm_config()
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/admin/internal/config/llm/active"))
        self.assertEqual(request.get_header("X-service-token"), config.INTERNAL_SERVICE_TOKEN)


if __name__ == "__main__":
    unittest.main()
