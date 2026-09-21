"""确定性模板兜底页面必须通过 Guard 且包含三类可视化入口。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.guard import validate_page
from agent.template_render import render_template_page
from agent.page_writer import strip_code_fence


BUNDLE = {
    "question": "红蓝空中力量对比",
    "generatedAt": "2024-01-01 00:00:00",
    "datasets": [
        {
            "id": "q1", "name": "战机数量", "mode": "aggregate",
            "columns": ["faction", "cnt"],
            "rows": [{"faction": "蓝方", "cnt": 12}, {"faction": "红方", "cnt": 9}],
            "totalRows": 2, "truncated": False,
            "geo": {"kind": "none"}, "summary": "行数：2",
            "geoFeatures": {"tracks": [], "points": [], "circles": []},
            "warnings": [],
        },
        {
            "id": "q2", "name": "飞机位置", "mode": "detail",
            "columns": ["name", "lng", "lat", "faction"],
            "rows": [
                {"name": "蓝鹰01", "lng": 120.1, "lat": 30.1, "faction": "蓝方"},
                {"name": "红隼02", "lng": 121.2, "lat": 31.2, "faction": "红方"},
            ],
            "totalRows": 2, "truncated": False,
            "geo": {"kind": "points"},
            "geoFeatures": {"tracks": [], "points": [
                {"lng": 120.1, "lat": 30.1, "name": "蓝鹰01", "kind": "target", "props": {}},
                {"lng": 121.2, "lat": 31.2, "name": "红隼02", "kind": "threat", "props": {}},
            ], "circles": []},
            "warnings": [],
        },
    ],
}


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.html = render_template_page(BUNDLE)

    def test_template_passes_guard(self):
        issues = validate_page(self.html, BUNDLE)
        self.assertEqual(issues, [], msg="；".join(issues))

    def test_template_uses_bootstrap_and_kit(self):
        self.assertIn("SitApp.bootstrap", self.html)
        self.assertIn("SitChart.render", self.html)
        self.assertIn("SitMap.render", self.html)
        self.assertIn("SitTable.render", self.html)
        self.assertIn("SitApp.ready", self.html)

    def test_template_is_full_document(self):
        low = self.html.lower()
        self.assertTrue(low.lstrip().startswith("<!doctype html>"))
        self.assertIn("</html>", low)

    def test_no_external_urls(self):
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertNotIn("<script src", self.html.lower())


class StripFenceTest(unittest.TestCase):
    def test_strip_html_fence(self):
        raw = "```html\n<!DOCTYPE html><html></html>\n```"
        out = strip_code_fence(raw)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertNotIn("```", out)

    def test_plain_html_unchanged(self):
        raw = "<!DOCTYPE html><html></html>"
        self.assertEqual(strip_code_fence(raw), raw)


if __name__ == "__main__":
    unittest.main()
