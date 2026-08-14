import importlib.util
import os
from pathlib import Path
import unittest
import urllib
import urllib.request
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AdminServiceAuthTests(unittest.TestCase):
    def test_agent_admin_get_and_post_include_service_token(self):
        with patch.dict(os.environ, {"INTERNAL_SERVICE_TOKEN": "test-internal-token"}):
            tools = _load("qa_admin_tools_test", ROOT / "agents" / "tools.py")
        response = MagicMock()
        response.read.return_value = b'{"success":true}'
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            tools._api_get("database/list")
            get_request = urlopen.call_args.args[0]
            tools._api_post("database/db/execute-sql", {"sql": "SELECT 1"})
            post_request = urlopen.call_args.args[0]
        self.assertEqual(get_request.get_header("X-service-token"), "test-internal-token")
        self.assertEqual(post_request.get_header("X-service-token"), "test-internal-token")

    def test_main_admin_request_includes_service_token(self):
        # Importing the full FastAPI module is expensive; execute the small request factory
        # contract in isolation while preserving its real source.
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        start = source.index("def _admin_request(")
        end = source.index("\n\n", source.index("    return req", start))
        namespace = {
            "ADMIN_SERVICE_URL": "http://admin.internal",
            "INTERNAL_SERVICE_TOKEN": "test-main-token",
            "urllib": urllib,
        }
        exec(source[start:end], namespace)
        request = namespace["_admin_request"]("/api/admin/config/llm/list")
        self.assertEqual(request.get_header("X-service-token"), "test-main-token")
