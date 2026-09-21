"""Critic 视觉反思决策层单元测试（VERIFY 阶段 review_artifact 方案 §7.1）。

覆盖：
- review() 成功路径：LLM 返回 emit_review_decision tool_call，Critic 输出 actions
- review() LLM 未返回 tool_calls：进入重试，2 次失败后返回 _fallback=True
- review() arguments 为空：触发重试
- review() actions 非数组：触发重试
- _build_messages 多模态：截图存在时 user content 为 list（text + image_url）
- _build_messages 纯文本降级：截图缺失时 user content 为 str
- _format_charts_summary / _format_verify_failures / _format_sub_questions 格式化
"""
from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from agent import critic


def _run(coro):
    """同步执行 coroutine（unittest 不引入 pytest-asyncio）。"""
    return asyncio.new_event_loop().run_until_complete(coro)


# ── 测试夹具 ──
_DEFAULT_PROFILE = {
    "skillId": "",
    "skillName": "通用态势分析",
    "chartTypes": ["bar", "line", "pie", "radar", "scatter"],
}

_BASE_CHARTS = [
    {"chartId": "c1", "type": "pie", "title": "图 1", "option": {"series": []}},
    {"chartId": "c2", "type": "bar", "title": "图 2", "option": {"series": []}},
]

_BASE_FAILURES = [
    {"chartId": "c1", "stage": "type_fit", "reason": "pie 图分类数 12 > 8"},
]

_BASE_SUB_QUESTIONS = [
    {"id": "q1", "question": "问题 1", "datasetId": "ds1"},
]

_BASE_SCREENSHOTS = [("c1", "BASE64_PLACEHOLDER"), ("c2", None)]  # c1 有图，c2 无图


def _make_tool_call_result(actions):
    """构造 call_llm_with_tools 成功返回值。"""
    return {
        "content": "",
        "tool_calls": [
            {"id": "call_1", "name": "emit_review_decision", "arguments": {"actions": actions}},
        ],
        "finish_reason": "tool_calls",
    }


class ReviewSuccessTests(unittest.TestCase):
    """review() 成功路径。"""

    def test_review_success_returns_actions(self):
        actions = [
            {"type": "replace_type", "targetChartId": "c1", "newType": "bar",
             "reason": "pie 分类过多"},
        ]
        c = critic.Critic(_DEFAULT_PROFILE, {})
        with mock.patch("agent.critic.call_llm_with_tools",
                        return_value=_make_tool_call_result(actions)) as m:
            result = _run(c.review(
                charts=_BASE_CHARTS,
                screenshots=_BASE_SCREENSHOTS,
                verify_failures=_BASE_FAILURES,
                sub_questions=_BASE_SUB_QUESTIONS,
            ))
        self.assertFalse(result.get("_fallback"))
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["actions"][0]["type"], "replace_type")
        # 校验 LLM 被调用、tool_choice 指定 emit_review_decision
        self.assertEqual(m.call_count, 1)
        args, kwargs = m.call_args
        self.assertEqual(
            kwargs["tool_choice"]["function"]["name"],
            "emit_review_decision",
        )

    def test_review_empty_actions_means_accept(self):
        """空 actions 表示接受，不应触发 fallback。"""
        c = critic.Critic(_DEFAULT_PROFILE, {})
        with mock.patch("agent.critic.call_llm_with_tools",
                        return_value=_make_tool_call_result([])):
            result = _run(c.review(
                charts=_BASE_CHARTS,
                screenshots=_BASE_SCREENSHOTS,
                verify_failures=_BASE_FAILURES,
                sub_questions=_BASE_SUB_QUESTIONS,
            ))
        self.assertFalse(result.get("_fallback"))
        self.assertEqual(result["actions"], [])


class ReviewFallbackTests(unittest.TestCase):
    """review() 失败降级路径。"""

    def test_review_no_tool_calls_triggers_fallback(self):
        """LLM 未返回 tool_calls → 2 次失败后 fallback。"""
        c = critic.Critic(_DEFAULT_PROFILE, {})
        with mock.patch("agent.critic.call_llm_with_tools",
                        return_value={"content": "x", "tool_calls": [], "finish_reason": "stop"}):
            result = _run(c.review(
                charts=_BASE_CHARTS,
                screenshots=_BASE_SCREENSHOTS,
                verify_failures=_BASE_FAILURES,
                sub_questions=_BASE_SUB_QUESTIONS,
            ))
        self.assertTrue(result.get("_fallback"))
        self.assertEqual(result["actions"], [])

    def test_review_arguments_not_dict_triggers_fallback(self):
        """emit_review_decision.arguments 非 dict → fallback。"""
        bad_result = {
            "content": "",
            "tool_calls": [{"id": "1", "name": "emit_review_decision", "arguments": "not_a_dict"}],
            "finish_reason": "tool_calls",
        }
        c = critic.Critic(_DEFAULT_PROFILE, {})
        with mock.patch("agent.critic.call_llm_with_tools", return_value=bad_result):
            result = _run(c.review(
                charts=_BASE_CHARTS, screenshots=_BASE_SCREENSHOTS,
                verify_failures=_BASE_FAILURES, sub_questions=_BASE_SUB_QUESTIONS,
            ))
        self.assertTrue(result.get("_fallback"))

    def test_review_actions_not_list_triggers_fallback(self):
        """actions 不是数组 → fallback。"""
        bad_result = {
            "content": "",
            "tool_calls": [{"id": "1", "name": "emit_review_decision",
                            "arguments": {"actions": "not_a_list"}}],
            "finish_reason": "tool_calls",
        }
        c = critic.Critic(_DEFAULT_PROFILE, {})
        with mock.patch("agent.critic.call_llm_with_tools", return_value=bad_result):
            result = _run(c.review(
                charts=_BASE_CHARTS, screenshots=_BASE_SCREENSHOTS,
                verify_failures=_BASE_FAILURES, sub_questions=_BASE_SUB_QUESTIONS,
            ))
        self.assertTrue(result.get("_fallback"))

    def test_review_exception_triggers_fallback(self):
        """LLM 调用抛异常 → fallback。"""
        c = critic.Critic(_DEFAULT_PROFILE, {})
        with mock.patch("agent.critic.call_llm_with_tools",
                        side_effect=RuntimeError("LLM 不可用")):
            result = _run(c.review(
                charts=_BASE_CHARTS, screenshots=_BASE_SCREENSHOTS,
                verify_failures=_BASE_FAILURES, sub_questions=_BASE_SUB_QUESTIONS,
            ))
        self.assertTrue(result.get("_fallback"))
        self.assertIn("LLM 不可用", result.get("_error", ""))


class BuildMessagesTests(unittest.TestCase):
    """_build_messages 多模态/纯文本分支。"""

    def test_build_messages_with_screenshots_is_multimodal(self):
        c = critic.Critic(_DEFAULT_PROFILE, {})
        screenshots = [("c1", "B64_1"), ("c2", "B64_2")]
        messages = c._build_messages(
            _BASE_CHARTS, screenshots, _BASE_FAILURES,
            _BASE_SUB_QUESTIONS, ["bar", "line", "pie", "radar", "scatter"],
        )
        self.assertEqual(messages[0]["role"], "system")
        user_content = messages[1]["content"]
        # 多模态：content 是 list，包含 1 个 text + 2 个 image_url
        self.assertIsInstance(user_content, list)
        self.assertEqual(user_content[0]["type"], "text")
        self.assertEqual(len([c for c in user_content if c["type"] == "image_url"]), 2)

    def test_build_messages_without_screenshots_is_text_only(self):
        """所有截图缺失时退化为纯文本。"""
        c = critic.Critic(_DEFAULT_PROFILE, {})
        screenshots = [("c1", None), ("c2", None)]
        messages = c._build_messages(
            _BASE_CHARTS, screenshots, _BASE_FAILURES,
            _BASE_SUB_QUESTIONS, ["bar", "line"],
        )
        # 纯文本：content 是 str
        self.assertIsInstance(messages[1]["content"], str)
        self.assertIn("图 1", messages[1]["content"])
        self.assertIn("pie 图分类数 12 > 8", messages[1]["content"])

    def test_build_messages_mixed_screenshots(self):
        """部分截图存在时只附有效截图。"""
        c = critic.Critic(_DEFAULT_PROFILE, {})
        screenshots = [("c1", "B64_1"), ("c2", None)]
        messages = c._build_messages(
            _BASE_CHARTS, screenshots, _BASE_FAILURES,
            _BASE_SUB_QUESTIONS, ["bar"],
        )
        user_content = messages[1]["content"]
        self.assertIsInstance(user_content, list)
        self.assertEqual(len([c for c in user_content if c["type"] == "image_url"]), 1)


class FormatHelperTests(unittest.TestCase):
    """格式化辅助函数。"""

    def test_format_charts_summary_includes_id_and_type(self):
        s = critic._format_charts_summary(_BASE_CHARTS)
        self.assertIn("c1", s)
        self.assertIn("pie", s)
        self.assertIn("图 1", s)

    def test_format_charts_summary_empty(self):
        self.assertEqual(critic._format_charts_summary([]), "（无）")
        self.assertEqual(critic._format_charts_summary(None), "（无）")

    def test_format_verify_failures_empty(self):
        s = critic._format_verify_failures([])
        self.assertIn("全部通过", s)

    def test_format_verify_failures_with_items(self):
        s = critic._format_verify_failures(_BASE_FAILURES)
        self.assertIn("c1", s)
        self.assertIn("type_fit", s)
        self.assertIn("分类数 12", s)

    def test_format_sub_questions_includes_id(self):
        s = critic._format_sub_questions(_BASE_SUB_QUESTIONS)
        self.assertIn("q1", s)
        self.assertIn("问题 1", s)


if __name__ == "__main__":
    unittest.main()
