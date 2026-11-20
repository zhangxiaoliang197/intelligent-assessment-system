"""Guard 校验单元测试：结构/外联/危险能力/占位符。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.guard import validate_layout, validate_page

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

BUNDLE = {
    "datasets": [{
        "id": "q1",
        "rows": [{"lng": 120, "lat": 30}],
        "geoFeatures": {
            "tracks": [],
            "points": [{"lng": 120, "lat": 30, "name": "点位"}],
            "units": [{"lng": 120, "lat": 30, "name": "点位"}],
            "circles": [],
        },
    }]
}


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

    def test_map_without_geo_features_rejected(self):
        """没有地理要素时禁止渲染 SitMap，避免生成空白地图。"""
        empty_geo_bundle = {
            "datasets": [{
                "id": "q1",
                "rows": [{"side": "红方"}],
                "geoFeatures": {"tracks": [], "points": [], "units": [], "circles": []},
            }]
        }
        issues = validate_page(VALID_HTML, empty_geo_bundle)
        self.assertTrue(any("地理要素" in i for i in issues))

    def test_map_container_without_geo_rejected(self):
        """没有地理要素时，即使不调用 SitMap 也不允许留下空白地图容器。"""
        html = VALID_HTML.replace('id="m1"', 'id="map1"').replace(
            "SitMap.render('#m1', {points: data.datasets[0].geoFeatures.points});", "")
        empty_geo_bundle = {
            "datasets": [{
                "id": "q1",
                "rows": [{"side": "红方"}],
                "geoFeatures": {"tracks": [], "points": [], "units": [], "circles": []},
            }]
        }
        issues = validate_page(html, empty_geo_bundle)
        self.assertTrue(any("地图容器" in i for i in issues))

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

    def test_english_visible_text_rejected(self):
        """界面文案出现英文单词必须被判为不合规。"""
        html = VALID_HTML.replace("<body>", "<body><h1>THREAT OVERVIEW</h1>", 1)
        issues = validate_page(html, BUNDLE)
        self.assertTrue(any("中文" in i for i in issues), issues)

    def test_units_and_codes_are_allowed(self):
        """单位符号与含数字的编号/型号不算英文。"""
        html = VALID_HTML.replace(
            "<body>",
            "<body><p>打击半径 120km，侦察时长 2h，机型 BT-03，任务 M-BL-0001</p>", 1)
        self.assertEqual(validate_page(html, BUNDLE), [])


class LayoutGuardTest(unittest.TestCase):
    """无地理数据时的版式校验：禁止左右分栏、内部滚动与固定一屏高度。"""

    NO_GEO_BUNDLE = {
        "datasets": [{
            "id": "q1",
            "rows": [{"阵营": "红方", "数量": 3}],
            "geoFeatures": {"tracks": [], "points": [], "units": [], "circles": []},
        }]
    }

    def test_geo_page_allows_split_layout(self):
        """有地理要素时左右分栏属于正常版式，不报错。"""
        html = "<style>.main{grid-template-columns:minmax(0,var(--ipage-left,44%)) 1fr}</style>"
        self.assertEqual(validate_layout(html, BUNDLE), [])

    def test_no_geo_split_layout_rejected(self):
        """无地理数据时使用 --ipage-left 左右分栏必须报错。"""
        html = "<style>.main{grid-template-columns:minmax(0,var(--ipage-left,44%)) 1fr}</style>"
        issues = validate_layout(html, self.NO_GEO_BUNDLE)
        self.assertTrue(any("左右分栏" in i for i in issues), issues)

    def test_no_geo_inner_scroll_rejected(self):
        """无地理数据时图表容器内部滚动必须报错。"""
        html = "<style>.chart-col{overflow-y:auto;overscroll-behavior:contain}</style>"
        issues = validate_layout(html, self.NO_GEO_BUNDLE)
        self.assertTrue(any("内部滚动" in i for i in issues), issues)

    def test_no_geo_fixed_viewport_rejected(self):
        """无地理数据时固定一屏高度必须报错。"""
        html = "<style>.single{height:var(--ipage-vh,720px)}</style>"
        issues = validate_layout(html, self.NO_GEO_BUNDLE)
        self.assertTrue(any("一屏高度" in i for i in issues), issues)

    def test_no_geo_flat_layout_passes(self):
        """无地理数据时平铺版式（自适应列 + 自然滚动）通过校验。"""
        html = ("<style>.chart-grid{display:grid;"
                "grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px}</style>")
        self.assertEqual(validate_layout(html, self.NO_GEO_BUNDLE), [])


if __name__ == "__main__":
    unittest.main()
