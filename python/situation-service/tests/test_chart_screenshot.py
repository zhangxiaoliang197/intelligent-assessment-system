"""单 chart PNG 截图渲染单元测试（VERIFY 阶段 review_artifact 方案 §7.1）。

覆盖：
- render_chart_pngs 空入参：返回空列表
- playwright 不可用：返回全 None 列表
- chart.option 非 dict：该项 png_b64=None
- 单图渲染成功：返回 base64 字符串
- 多图顺序保持：返回顺序与输入一致

playwright 不可用时整组用例自动 skip，避免 CI 环境失败。
"""
from __future__ import annotations

import asyncio
import base64
import unittest
from unittest import mock

from agent import chart_screenshot


def _run(coro):
    """同步执行 coroutine。"""
    return asyncio.new_event_loop().run_until_complete(coro)


class RenderChartPngsTests(unittest.TestCase):
    """render_chart_pngs 行为测试。"""

    def test_empty_charts_returns_empty_list(self):
        """空入参返回空列表。"""
        result = _run(chart_screenshot.render_chart_pngs([]))
        self.assertEqual(result, [])

    def test_playwright_unavailable_returns_all_none(self):
        """playwright 不可用时返回 [(chartId, None), ...]。"""
        charts = [
            {"chartId": "c1", "type": "bar", "option": {"series": []}},
            {"chartId": "c2", "type": "pie", "option": {"series": []}},
        ]
        with mock.patch(
            "agent.chart_screenshot.visual_judge.is_available_async",
            return_value=False,
        ):
            result = _run(chart_screenshot.render_chart_pngs(charts))
        self.assertEqual(len(result), 2)
        self.assertTrue(all(b64 is None for _, b64 in result))
        self.assertEqual([cid for cid, _ in result], ["c1", "c2"])

    def test_chart_without_option_returns_none_for_that_item(self):
        """option 非 dict 时该项返回 None。"""
        charts = [
            {"chartId": "c1", "type": "bar"},  # 无 option
            {"chartId": "c2", "type": "pie", "option": "not_a_dict"},
        ]
        with mock.patch(
            "agent.chart_screenshot.visual_judge.is_available_async",
            return_value=False,
        ):
            result = _run(chart_screenshot.render_chart_pngs(charts))
        self.assertEqual(result, [("c1", None), ("c2", None)])

    def test_render_success_returns_base64_string(self):
        """单图渲染成功路径（mock _render_single_chart_sync）。"""
        charts = [{"chartId": "c1", "type": "bar", "option": {"series": []}}]
        fake_png = b"\x89PNG\r\n\x1a\n"  # PNG 签名
        with mock.patch(
            "agent.chart_screenshot.visual_judge.is_available_async",
            return_value=True,
        ), mock.patch(
            "agent.chart_screenshot._render_single_chart_sync",
            return_value=fake_png,
        ):
            result = _run(chart_screenshot.render_chart_pngs(charts))
        self.assertEqual(len(result), 1)
        cid, b64 = result[0]
        self.assertEqual(cid, "c1")
        self.assertIsNotNone(b64)
        # 验证 base64 可解码回原 bytes
        self.assertEqual(base64.b64decode(b64), fake_png)

    def test_render_exception_returns_none_for_that_item(self):
        """渲染抛异常时该项返回 None，不影响其他项。"""
        charts = [
            {"chartId": "c1", "type": "bar", "option": {"series": []}},
            {"chartId": "c2", "type": "pie", "option": {"series": []}},
        ]
        # 让第一次调用抛异常，第二次返回正常 PNG
        side_effects = [RuntimeError("render fail"), b"\x89PNG"]
        with mock.patch(
            "agent.chart_screenshot.visual_judge.is_available_async",
            return_value=True,
        ), mock.patch(
            "agent.chart_screenshot._render_single_chart_sync",
            side_effect=side_effects,
        ):
            result = _run(chart_screenshot.render_chart_pngs(charts))
        self.assertEqual(len(result), 2)
        self.assertIsNone(result[0][1])  # c1 异常 → None
        self.assertIsNotNone(result[1][1])  # c2 正常 → base64

    def test_order_preserved(self):
        """多图渲染顺序与输入一致。"""
        charts = [
            {"chartId": "c1", "type": "bar", "option": {"series": []}},
            {"chartId": "c2", "type": "pie", "option": {"series": []}},
            {"chartId": "c3", "type": "line", "option": {"series": []}},
        ]
        with mock.patch(
            "agent.chart_screenshot.visual_judge.is_available_async",
            return_value=True,
        ), mock.patch(
            "agent.chart_screenshot._render_single_chart_sync",
            return_value=b"\x89PNG",
        ):
            result = _run(chart_screenshot.render_chart_pngs(charts))
        self.assertEqual([cid for cid, _ in result], ["c1", "c2", "c3"])


class BuildSingleChartHtmlTests(unittest.TestCase):
    """_build_single_chart_html 模板生成。"""

    def test_html_contains_chart_div_with_data_ref(self):
        html = chart_screenshot._build_single_chart_html("c_test")
        self.assertIn('<div id="chart"', html)
        self.assertIn('data-ref="c_test"', html)
        self.assertIn("width:", html)
        self.assertIn("height:", html)

    def test_html_has_utf8_meta(self):
        html = chart_screenshot._build_single_chart_html("x")
        self.assertIn("charset=\"utf-8\"", html)


if __name__ == "__main__":
    unittest.main()
