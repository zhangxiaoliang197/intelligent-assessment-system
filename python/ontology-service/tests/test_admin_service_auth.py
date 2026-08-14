import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


class OntologyAdminServiceAuthTests(unittest.TestCase):
    def test_llm_config_uses_internal_authenticated_endpoint(self):
        path = Path(__file__).resolve().parents[1] / "llm_client.py"
        with patch.dict(os.environ, {"INTERNAL_SERVICE_TOKEN": "test-ontology-token"}):
            spec = importlib.util.spec_from_file_location("ontology_llm_auth_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
        response = MagicMock()
        response.read.return_value = b'{"success":true,"data":{"type":"vllm","apiUrl":"http://localhost:1"}}'
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            module.load_llm_config()
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/admin/internal/config/llm/active"))
        self.assertEqual(request.get_header("X-service-token"), "test-ontology-token")

