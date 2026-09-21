"""Planner 质量优化单测（态势图-排版多样性与产物质量校验方案 配套优化）。

覆盖：
1. get_system_prompt(with_map_guide=False) 不注入地图技能指南（Planner 阶段减负）
2. Planner._append_tool_feedback 正确构造 assistant tool_call + tool 反馈消息
3. Planner.plan 失败重试时 messages 逐轮增长（反馈式重试而非原样重发）
4. llm_client 解析失败的 tool_call 被保留（带 parse_error），调用方可拿到 id 构造反馈
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch, AsyncMock

from agent import prompts
from agent.planner import Planner


class SystemPromptTrimTests(unittest.TestCase):
    """Planner 阶段不注入地图技能指南。"""

    def test_full_contains_map_guide(self):
        p = prompts.get_system_prompt(with_map_guide=True)
        self.assertIn("map_draw_area", p)
        self.assertIn("map_place_marker", p)

    def test_trimmed_excludes_map_guide(self):
        p = prompts.get_system_prompt(with_map_guide=False)
        self.assertNotIn("map_draw_area", p)
        self.assertNotIn("map_place_marker", p)

    def test_trimmed_keeps_core_workflow(self):
        """裁剪后仍保留工作流五阶段与硬约束。"""
        p = prompts.get_system_prompt(with_map_guide=False)
        for kw in ("规划", "取数", "产图", "地图", "文本", "WGS84"):
            self.assertIn(kw, p)

    def test_trimmed_significantly_smaller(self):
        full = prompts.get_system_prompt(with_map_guide=True)
        trim = prompts.get_system_prompt(with_map_guide=False)
        self.assertLess(len(trim), len(full) * 0.3)


class ToolFeedbackTests(unittest.TestCase):
    """反馈式重试：assistant tool_call + tool 反馈消息。"""

    def test_append_feedback_with_dict_args(self):
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}]
        plan = {"subQuestions": [], "chartSpecs": []}
        out = Planner._append_tool_feedback(msgs, "call_123", "思考文本", plan, "校验失败")
        self.assertEqual(len(out), 4)
        # assistant 消息携带原始 tool_call
        assistant = out[2]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["tool_calls"][0]["id"], "call_123")
        self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "emit_research_plan")
        self.assertEqual(assistant["tool_calls"][0]["function"]["arguments"], json.dumps(plan, ensure_ascii=False))
        # tool 反馈
        tool = out[3]
        self.assertEqual(tool["role"], "tool")
        self.assertEqual(tool["tool_call_id"], "call_123")
        self.assertEqual(tool["content"], "校验失败")

    def test_append_feedback_with_empty_args(self):
        """arguments 为空（思考链耗尽）时 args_str 为空串。"""
        out = Planner._append_tool_feedback([], "call_x", "", None, "参数为空")
        self.assertEqual(out[0]["tool_calls"][0]["function"]["arguments"], "")


class PlanRetryTests(unittest.TestCase):
    """Planner.plan 重试时 messages 逐轮增长（反馈式重试）。"""

    def _make_planner(self):
        return Planner({}, {"success": False})

    def test_retry_grows_messages_on_args_empty(self):
        """第 1 次 arguments 为空 → 第 2 次请求的 messages 应多出 2 条（assistant+tool）。"""
        planner = self._make_planner()
        captured = []

        def fake_call(messages, **kw):
            captured.append(list(messages))
            return {
                "content": "",
                "tool_calls": [{
                    "id": f"call_{len(captured)}",
                    "name": "emit_research_plan",
                    "arguments": None,
                    "parse_error": {"error": "Expecting value"},
                }],
                "finish_reason": "tool_calls",
            }

        with patch("agent.planner.call_llm_with_tools", side_effect=fake_call):
            asyncio.run(planner.plan("测试问题"))

        self.assertEqual(len(captured), 3)
        # 第 1 次：system + user = 2
        self.assertEqual(len(captured[0]), 2)
        # 第 2 次：+ assistant + tool = 4
        self.assertEqual(len(captured[1]), 4)
        # 第 3 次：再 + assistant + tool = 6
        self.assertEqual(len(captured[2]), 6)
        # 反馈文本应出现在 tool 消息中
        self.assertIn("未提供有效参数", captured[1][3]["content"])

    def test_retry_on_validation_error(self):
        """校验失败时用 tool 反馈具体错误原因。"""
        planner = self._make_planner()
        captured = []
        call_seq = [
            {"content": "", "tool_calls": [{"id": "c1", "name": "emit_research_plan",
                                            "arguments": {"subQuestions": []}, "parse_error": None}],
             "finish_reason": "tool_calls"},
            {"content": "", "tool_calls": [{"id": "c2", "name": "emit_research_plan",
                                            "arguments": {"subQuestions": [{"id": "q1", "datasetId": "x"}],
                                                          "chartSpecs": [{"id": "c1", "type": "bar", "title": "t", "subQuestionRef": "q1"}]},
                                            "parse_error": None}],
             "finish_reason": "tool_calls"},
        ]

        def fake_call(messages, **kw):
            captured.append(list(messages))
            return call_seq[len(captured) - 1]

        with patch("agent.planner.call_llm_with_tools", side_effect=fake_call), \
             patch("agent.planner._validate_plan", side_effect=["subQuestions 至少需要 1 个", None]):
            asyncio.run(planner.plan("测试问题"))

        self.assertEqual(len(captured), 2)
        self.assertEqual(len(captured[0]), 2)
        self.assertEqual(len(captured[1]), 4)
        self.assertIn("subQuestions 至少需要 1 个", captured[1][3]["content"])


if __name__ == "__main__":
    unittest.main()
