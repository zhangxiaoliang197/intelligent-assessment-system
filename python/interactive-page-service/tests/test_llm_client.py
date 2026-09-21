"""LLM 客户端测试：内容非空但被 max_tokens 截断时必须可识别且留痕。"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm_client
from llm_client import LLMTruncatedText, call_llm


def _fake_response(payload: dict):
    """构造 urlopen 可用的响应替身（同时支持 with 与 read）。"""
    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _Resp(json.dumps(payload).encode("utf-8"))


class TruncationTest(unittest.TestCase):
    """finish_reason=length 且有内容：既不报错也不静默，而是标记 + WARNING。"""

    def setUp(self):
        self.llm_cfg = {
            "type": "deepseek", "apiUrl": "https://api.deepseek.com/v1",
            "apiKey": "test-key", "model": "deepseek-chat",
        }

    def _call(self, payload: dict) -> str:
        with mock.patch.object(llm_client, "load_llm_config", lambda: self.llm_cfg), \
                mock.patch.object(llm_client, "_validate_endpoint", lambda url: None), \
                mock.patch.object(llm_client, "_ssl_context", lambda: None), \
                mock.patch.object(llm_client.urllib.request, "urlopen",
                                  lambda req, timeout=None, context=None: _fake_response(payload)):
            return call_llm([{"role": "user", "content": "生成页面"}], max_tokens=100)

    def test_truncated_content_is_flagged_and_logged(self):
        payload = {
            "choices": [{"message": {"content": "<!DOCTYPE html><html>"},
                         "finish_reason": "length"}],
            "usage": {"completion_tokens": 100},
        }
        with self.assertLogs("ipage-service", level="WARNING") as captured:
            out = self._call(payload)

        self.assertIsInstance(out, LLMTruncatedText)
        # 继承 str：既有字符串用法（清洗、校验、拼接）完全不受影响
        self.assertEqual(out, "<!DOCTYPE html><html>")
        self.assertTrue(any("截断" in line for line in captured.output))

    def test_normal_content_is_plain_str(self):
        payload = {
            "choices": [{"message": {"content": "<html></html>"},
                         "finish_reason": "stop"}],
            "usage": {"completion_tokens": 5},
        }
        out = self._call(payload)
        self.assertNotIsInstance(out, LLMTruncatedText)
        self.assertEqual(out, "<html></html>")


if __name__ == "__main__":
    unittest.main()