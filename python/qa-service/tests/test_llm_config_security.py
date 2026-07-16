import json
import os
import unittest
from unittest.mock import patch

import main


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LlmConfigSecurityTest(unittest.IsolatedAsyncioTestCase):
    def test_internal_loader_sends_token_and_receives_secret(self):
        payload = {"success": True, "data": {"apiKey": "sk-secret", "model": "model"}}
        with (
            patch.dict(os.environ, {"ADMIN_INTERNAL_TOKEN": "shared-token"}),
            patch("main.urllib.request.urlopen", return_value=_FakeResponse(payload)) as urlopen,
        ):
            config = main.load_llm_config()

        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/admin/internal/config/llm/active"))
        self.assertIn(("X-internal-token", "shared-token"), request.header_items())
        self.assertEqual("sk-secret", config["apiKey"])

    def test_missing_internal_token_fails_closed_without_network_call(self):
        with (
            patch.dict(os.environ, {"ADMIN_INTERNAL_TOKEN": ""}),
            patch("main.urllib.request.urlopen") as urlopen,
        ):
            config = main.load_llm_config()

        urlopen.assert_not_called()
        self.assertEqual("", config["apiKey"])
        self.assertFalse(config["apiKeyConfigured"])

    async def test_public_fallback_never_uses_internal_secret_loader(self):
        with (
            patch("main.urllib.request.urlopen", side_effect=OSError("offline")),
            patch("main.load_llm_config") as internal_loader,
        ):
            response = await main.get_llm_config()

        internal_loader.assert_not_called()
        self.assertEqual("", response["data"]["apiKey"])


if __name__ == "__main__":
    unittest.main()
