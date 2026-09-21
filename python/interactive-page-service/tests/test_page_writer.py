"""PageWriter 单元测试：文本清洗 + 重新设计/修复消息不回灌旧页面。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import page_writer, prompts
from agent.page_writer import PageWriter, strip_code_fence

DOC = "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head></head><body>x</body></html>"

# 能通过 Guard 校验的最小合法页面（结构完整 + 启动入口 + 一个可视化调用 + 长度达标）
VALID_PAGE = (
    "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<title>测试页面</title><style>.ip-card{height:320px}</style></head>"
    "<body><div id=\"chart\" class=\"ip-card\"></div><div id=\"table\"></div>"
    "<script>SitApp.bootstrap(function (data) {"
    "  SitChart.render('#chart', {type: 'bar', title: '测试', xData: [], series: []});"
    "  SitTable.render('#table', {columns: [], rows: [], pageSize: 10});"
    "});</script></body></html>"
)

INVALID_PAGE = "这不是合法页面"

PLAN = {"title": "测试页", "sections": [{"kind": "chart"}], "interactions": []}
BUNDLE = {"question": "测试问题", "generatedAt": "2026-09-18 10:00:00", "datasets": []}


class StripCodeFenceTest(unittest.TestCase):
    def test_pure_html_unchanged(self):
        self.assertEqual(strip_code_fence(DOC), DOC)

    def test_fenced_block_extracted(self):
        raw = "```html\n" + DOC + "\n```"
        self.assertEqual(strip_code_fence(raw), DOC)

    def test_prose_plus_fence(self):
        """前言 + 围栏 + 结尾说明，应只保留文档。"""
        raw = "这是为您生成的页面：\n```html\n" + DOC + "\n```\n希望对您有帮助。"
        self.assertEqual(strip_code_fence(raw), DOC)

    def test_prose_without_fence(self):
        """无围栏但带前后散文，按文档窗口截取。"""
        raw = "好的，页面如下：\n" + DOC + "\n以上是全部内容。"
        self.assertEqual(strip_code_fence(raw), DOC)

    def test_missing_closing_fence(self):
        raw = "```html\n" + DOC
        out = strip_code_fence(raw)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertNotIn("```", out)

    def test_html_tag_fallback(self):
        """没有 DOCTYPE 但有 <html> 时以 <html 为窗口起点。"""
        doc2 = "<html lang=\"zh\"><body>y</body></html>"
        raw = "说明文字\n```\n" + doc2 + "\n```"
        self.assertEqual(strip_code_fence(raw), doc2)

    def test_empty(self):
        self.assertEqual(strip_code_fence(""), "")


class RedesignMessagesTest(unittest.TestCase):
    """消息构造：重新设计与修复都不得回灌历史页面 HTML。"""

    def test_repair_messages_carry_issues_without_previous_html(self):
        msgs = prompts.build_repair_messages(["缺少 </html> 闭合标签"])
        self.assertEqual([m["role"] for m in msgs], ["user"])
        self.assertIn("缺少 </html> 闭合标签", msgs[0]["content"])

    def test_redesign_messages_carry_feedback_without_previous_html(self):
        msgs = prompts.build_redesign_messages("把趋势图改成按任务阶段对比的折线图")
        self.assertEqual([m["role"] for m in msgs], ["user"])
        content = msgs[0]["content"]
        self.assertIn("把趋势图改成按任务阶段对比的折线图", content)
        self.assertIn("重新设计", content)
        # 历史实现是 assistant + previous_html[:12000]，改造后不应再出现旧页面
        self.assertNotIn("<!DOCTYPE html", content)

    def test_sample_and_page_messages_unchanged(self):
        """首次生成链路不受影响：仍为 system + user 两条。"""
        msgs = prompts.build_page_messages("问题", PLAN, BUNDLE, 20)
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])


class RedesignFlowTest(unittest.TestCase):
    """redesign：不复用旧 HTML 作为上下文；失败时保留上一版。"""

    def test_redesign_does_not_feed_previous_html_to_llm(self):
        previous = VALID_PAGE.replace("测试页面", "上一版页面")
        captured = {}

        def fake_write(messages):
            captured["messages"] = messages
            return VALID_PAGE, False

        with mock.patch.object(page_writer, "_llm_write", fake_write):
            html, meta = PageWriter().redesign("原始问题", PLAN, BUNDLE, previous, "把柱状图换成折线图")

        self.assertEqual(html, VALID_PAGE)
        self.assertTrue(meta["revised"])
        msgs = captured["messages"]
        self.assertEqual([m["role"] for m in msgs], ["system", "user", "user"])
        joined = "\n".join(m["content"] for m in msgs)
        self.assertNotIn("上一版页面", joined)
        self.assertIn("把柱状图换成折线图", joined)

    def test_redesign_keeps_previous_page_when_validation_fails(self):
        previous = VALID_PAGE.replace("测试页面", "上一版页面")
        with mock.patch.object(page_writer, "_llm_write", lambda messages: (INVALID_PAGE, False)):
            html, meta = PageWriter().redesign("原始问题", PLAN, BUNDLE, previous, "意见")

        self.assertEqual(html, previous)
        self.assertFalse(meta["revised"])
        self.assertTrue(meta["issues"])

    def test_generate_repair_does_not_feed_invalid_page(self):
        """首次生成的校验重写轮：只给校验问题，不再回灌上一版残缺页面。"""
        calls = []

        def fake_write(messages):
            calls.append(messages)
            return (INVALID_PAGE, False) if len(calls) == 1 else (VALID_PAGE, False)

        with mock.patch.object(page_writer.config, "IPAGE_REPAIR_MAX_ROUNDS", 1), \
                mock.patch.object(page_writer, "_llm_write", fake_write):
            html, meta = PageWriter().generate("问题", PLAN, BUNDLE)

        self.assertEqual(meta["rounds"], 1)
        self.assertEqual(len(calls), 2)
        repair_msgs = calls[1]
        self.assertNotIn("assistant", [m["role"] for m in repair_msgs])
        self.assertNotIn(INVALID_PAGE, repair_msgs[-1]["content"])


class TruncationTest(unittest.TestCase):
    """输出被 max_tokens 截断：必须给出可读原因，而不是只剩「缺少 </html>」。"""

    def test_truncated_generate_reports_reason(self):
        with mock.patch.object(page_writer, "_llm_write", lambda messages: (VALID_PAGE, True)):
            html, meta = PageWriter().generate("问题", PLAN, BUNDLE)

        self.assertTrue(meta["usedTemplate"])
        self.assertTrue(any("截断" in i for i in meta["issues"]))

    def test_truncated_redesign_keeps_previous_with_reason(self):
        previous = VALID_PAGE.replace("测试页面", "上一版页面")
        with mock.patch.object(page_writer.config, "IPAGE_REPAIR_MAX_ROUNDS", 0), \
                mock.patch.object(page_writer, "_llm_write", lambda messages: (VALID_PAGE, True)):
            html, meta = PageWriter().redesign("原始问题", PLAN, BUNDLE, previous, "意见")

        self.assertEqual(html, previous)
        self.assertFalse(meta["revised"])
        self.assertTrue(any("截断" in i for i in meta["issues"]))


if __name__ == "__main__":
    unittest.main()
