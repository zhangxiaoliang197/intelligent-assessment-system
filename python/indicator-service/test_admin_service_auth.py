import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


class IndicatorAdminServiceAuthTests(unittest.TestCase):
    def test_admin_url_get_includes_service_token(self):
        path = Path(__file__).resolve().with_name("utils.py")
        with patch.dict(os.environ, {"INTERNAL_SERVICE_TOKEN": "test-indicator-token"}):
            spec = importlib.util.spec_from_file_location("indicator_utils_auth_test", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
        response = MagicMock()
        response.read.return_value = b'{"success":true}'
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            module.http_get("http://localhost:10258/api/admin/indicator/list")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-service-token"), "test-indicator-token")

