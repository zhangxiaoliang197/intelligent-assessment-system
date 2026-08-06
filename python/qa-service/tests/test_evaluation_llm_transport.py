from __future__ import annotations

import os
import ssl
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from evaluation_api import _open_llm_request  # noqa: E402


class EvaluationLlmTransportTests(unittest.TestCase):
    def test_llm_transport_ignores_environment_proxy_by_default(self):
        opener = MagicMock()
        request = urllib.request.Request("https://example.invalid/v1/chat/completions")

        with (
            patch.dict(os.environ, {"LLM_TRUST_ENV": "false"}),
            patch("urllib.request.build_opener", return_value=opener) as build_opener,
        ):
            _open_llm_request(request, timeout=12, ssl_ctx=ssl.create_default_context())

        proxy_handlers = [
            handler for handler in build_opener.call_args.args
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(1, len(proxy_handlers))
        self.assertEqual({}, proxy_handlers[0].proxies)
        opener.open.assert_called_once_with(request, timeout=12)

    def test_llm_transport_can_explicitly_trust_environment_proxy(self):
        opener = MagicMock()
        request = urllib.request.Request("https://example.invalid/v1/chat/completions")

        with (
            patch.dict(
                os.environ,
                {
                    "LLM_TRUST_ENV": "true",
                    "HTTPS_PROXY": "http://proxy.example.invalid:8080",
                },
            ),
            patch("urllib.request.build_opener", return_value=opener) as build_opener,
        ):
            _open_llm_request(request, timeout=12, ssl_ctx=ssl.create_default_context())

        proxy_handlers = [
            handler for handler in build_opener.call_args.args
            if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(1, len(proxy_handlers))
        self.assertIn("https", proxy_handlers[0].proxies)


if __name__ == "__main__":
    unittest.main()
