"""Guard 校验单元测试：结构/外联/危险能力/占位符。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.guard import validate_page

VALID_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>测试页</title></head>
<body>
<div id="c1" style="height:320px"></div>
<div id="m1" style="height:420px"></div>
<script>
SitApp.bootstrap(function (data) {
  SitChart.render('#c1', {type:'bar', xData:['a'], series:[{name:'s', data:[1]}]});
  SitMap.render('#m1', {points: data.datasets[0].geoFeatures.points});
});
</script>
</body></html>"""

BUNDLE = {"datasets": [{"id": "q1", "rows": [{"lng": 120, "lat": 30}]}]}


class GuardTest(unittest.TestCase):
    def test_valid_page_passes(self):
        self.assertEqual(validate_page(VALID_HTML, BUNDLE), [])

    def test_charset_meta_allowed(self):
        issues = validate_page(VALID_HTML, BUNDLE)
        self.assertFalse(any("meta" in i for i in issues))

    def test_missing_bootstrap(self):
        html = VALID_HTML.replace("SitApp.bootstrap", "function boot")
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("bootstrap" in i for i in issues))

    def test_external_script_forbidden(self):
        html = VALID_HTML.replace(
            "<script>",
            '<script src="https://cdn.example.com/x.js"></script><script>', 1)
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("script src" in i for i in issues))

    def test_fetch_forbidden(self):
        html = VALID_HTML.replace(
            "SitChart.render",
            "fetch('https://x.example.com'); SitChart.render", 1)
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("fetch" in i for i in issues))

    def test_echarts_direct_forbidden(self):
        html = VALID_HTML.replace(
            "SitChart.render('#c1'",
            "echarts.init(document.querySelector('#c1')); SitChart.render('#c1'", 1)
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("echarts" in i for i in issues))

    def test_http_literal_forbidden(self):
        html = VALID_HTML.replace(
            "SitChart.render",
            "var u = 'http://1.2.3.4/x'; SitChart.render", 1)
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("http" in i for i in issues))

    def test_secret_literal_forbidden(self):
        html = VALID_HTML.replace(
            "SitChart.render",
            "var k = 'sk-1234567890abcdef1234'; SitChart.render", 1)
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("Key" in i or "凭据" in i for i in issues))

    def test_missing_visualization(self):
        html = VALID_HTML.replace("SitChart.render('#c1', ", "void 0; ").replace(
            "SitMap.render('#m1', ", "void 0; ")
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("SitChart" in i for i in issues))

    def test_missing_dataset_reference(self):
        html = VALID_HTML.replace("data.datasets[0]", "data.datasets[0]")
        html = html.replace("datasets[0].geoFeatures", "datasets[0].geoFeatures")
        html = html.replace("SitMap.render('#m1', {points: data.datasets[0].geoFeatures.points});",
                            "SitMap.render('#m1', {points: data.datasets['q9'].geoFeatures.points});")
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("q9" in i for i in issues))

    def test_preamble_before_doctype_rejected(self):
        """LLM 在文档前输出寒暄说明文字必须被判为不合规。"""
        html = "这是为您生成的页面：\n" + VALID_HTML
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("开头" in i for i in issues))

    def test_markdown_fence_rejected(self):
        """Markdown 代码围栏标记不允许残留。"""
        html = "```html\n" + VALID_HTML + "\n```"
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("围栏" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
