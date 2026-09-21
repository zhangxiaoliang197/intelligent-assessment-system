"""产物质量校验单元测试（态势图-排版多样性与产物质量校验方案 §三）。

覆盖：
- chart_polish：标签防重叠、轴标签旋转/截断、大数据采样、图例补全、配色注入、
  bar 横向旋转；核心约束——只补展示层配置，绝不修改数据值
- map_density：Douglas-Peucker 抽稀、航迹抽稀元信息、密度四档分级、抽稀先于计数的口径
"""
from __future__ import annotations

import copy
import unittest

from agent.chart_polish import polish_chart, polish_charts
from agent.map_density import douglas_peucker, grade_layer_density
from agent.verifier import check_chart_field_mapping


def _bar_chart(categories, series_names=("系列A",)):
    """构造柱状图：xAxis 类目 + 每系列与类目等长的数据。"""
    return {
        "chartId": "c_bar",
        "type": "bar",
        "option": {
            "xAxis": {"type": "category", "data": list(categories)},
            "yAxis": {"type": "value"},
            "series": [
                {"name": name, "type": "bar", "data": list(range(len(categories)))}
                for name in series_names
            ],
        },
    }


class ChartPolishTests(unittest.TestCase):
    """chart option 规范化管线。"""

    def test_pie_label_overlap_injected(self):
        chart = {"chartId": "c1", "type": "pie", "option": {
            "series": [{"name": "占比", "type": "pie", "data": [{"name": "A", "value": 1}]}],
        }}
        out = polish_chart(chart)
        s = out["option"]["series"][0]
        self.assertTrue(s["labelLayout"]["hideOverlap"])
        self.assertEqual(s["labelLayout"]["alignTo"], "labelLine")
        self.assertTrue(s["avoidLabelOverlap"])

    def test_existing_label_layout_preserved(self):
        """已有 labelLayout 只补缺不覆盖（LLM 刻意配置优先）。"""
        chart = {"chartId": "c1", "type": "scatter", "option": {
            "series": [{"type": "scatter", "data": [[1, 2]],
                        "labelLayout": {"hideOverlap": False, "custom": 1}}],
        }}
        s = polish_chart(chart)["option"]["series"][0]
        self.assertFalse(s["labelLayout"]["hideOverlap"])  # 显式配置不被覆盖
        self.assertEqual(s["labelLayout"]["custom"], 1)

    def test_axis_labels_rotated_when_many_categories(self):
        chart = _bar_chart([f"类目{i}" for i in range(10)])
        axis = polish_chart(chart)["option"]["xAxis"]
        self.assertEqual(axis["axisLabel"]["rotate"], 30)
        self.assertEqual(axis["axisLabel"]["interval"], "auto")

    def test_axis_labels_truncated_when_long(self):
        chart = _bar_chart([f"第{i}号非常长的类目名称" for i in range(10)])
        axis = polish_chart(chart)["option"]["xAxis"]
        self.assertEqual(axis["axisLabel"]["overflow"], "truncate")
        self.assertEqual(axis["axisLabel"]["width"], 80)

    def test_few_categories_no_rotation(self):
        chart = _bar_chart(["A", "B", "C"])
        self.assertNotIn("axisLabel", polish_chart(chart)["option"]["xAxis"])

    def test_large_line_series_sampling(self):
        data = list(range(2000))
        chart = {"chartId": "c1", "type": "line", "option": {
            "series": [{"name": "趋势", "type": "line", "data": data}],
        }}
        s = polish_chart(chart)["option"]["series"][0]
        self.assertEqual(s["sampling"], "lttb")
        self.assertTrue(s["large"])
        self.assertFalse(s["showSymbol"])
        self.assertFalse(s["animation"])
        # 数据值不变（抽稀交给 ECharts 渲染层，不动原始数据）
        self.assertEqual(s["data"], data)

    def test_small_line_untouched(self):
        chart = {"chartId": "c1", "type": "line", "option": {
            "series": [{"name": "趋势", "type": "line", "data": list(range(100))}],
        }}
        self.assertNotIn("sampling", polish_chart(chart)["option"]["series"][0])

    def test_legend_added_for_multi_series(self):
        chart = _bar_chart(["A", "B"], series_names=("甲", "乙", "丙"))
        legend = polish_chart(chart)["option"]["legend"]
        self.assertEqual(legend["type"], "scroll")
        self.assertEqual(legend["bottom"], 0)

    def test_existing_legend_upgraded_to_scroll_when_overflow(self):
        chart = _bar_chart(["A", "B"], series_names=tuple(f"s{i}" for i in range(12)))
        chart["option"]["legend"] = {"top": 0}
        legend = polish_chart(chart)["option"]["legend"]
        self.assertEqual(legend["type"], "scroll")
        self.assertEqual(legend["top"], 0)  # 其余配置保留

    def test_palette_injected_when_no_colors(self):
        chart = _bar_chart(["A", "B"], series_names=("甲", "乙"))
        option = polish_chart(chart)["option"]
        self.assertIsInstance(option["color"], list)
        self.assertGreaterEqual(len(option["color"]), 8)

    def test_palette_skipped_when_llm_colored(self):
        """任一系列显式配色 → 视为 LLM 刻意设计，不注入调色板。"""
        chart = _bar_chart(["A", "B"], series_names=("甲", "乙"))
        chart["option"]["series"][0]["itemStyle"] = {"color": "#ff0000"}
        self.assertNotIn("color", polish_chart(chart)["option"])

    def test_bar_rotated_horizontal_when_categories_overflow(self):
        chart = _bar_chart([f"类目{i}" for i in range(25)])
        option = polish_chart(chart)["option"]
        # 类目轴移到 y：横向条形
        self.assertEqual(option["yAxis"]["type"], "category")
        self.assertEqual(option["yAxis"]["data"][0], "类目0")
        self.assertEqual(option["xAxis"]["type"], "value")
        # 横向后不再需要旋转标签
        self.assertNotIn("rotate", option["yAxis"].get("axisLabel", {}))

    def test_bar_not_rotated_below_threshold(self):
        chart = _bar_chart([f"类目{i}" for i in range(10)])
        option = polish_chart(chart)["option"]
        self.assertEqual(option["xAxis"]["type"], "category")

    def test_data_values_never_modified(self):
        """核心约束：规范化只动展示层配置，series.data 深度不变。"""
        chart = _bar_chart([f"第{i}号长类目名称" for i in range(25)], series_names=("甲", "乙"))
        before = copy.deepcopy([s["data"] for s in chart["option"]["series"]])
        polish_chart(chart)
        self.assertEqual([s["data"] for s in chart["option"]["series"]], before)

    def test_polish_charts_skips_invalid_items(self):
        charts = [None, {"noOption": True}, _bar_chart(["A"])]
        out = polish_charts(charts)
        self.assertIsNone(out[0])
        self.assertEqual(out[1], {"noOption": True})


class MapDensityTests(unittest.TestCase):
    """地图密度分级与航迹抽稀。"""

    def test_douglas_peucker_collinear_keeps_endpoints_only(self):
        """共线点列抽稀后只剩首尾（中间点对形状无贡献）。"""
        pts = [{"lng": i * 0.01, "lat": i * 0.01} for i in range(100)]
        out = douglas_peucker(pts, tolerance=0.001)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])

    def test_douglas_peucker_preserves_spike(self):
        """形状特征点（突刺）在容差内必须保留，且相对顺序不变。"""
        pts = [
            {"lng": 0, "lat": 0}, {"lng": 1, "lat": 0}, {"lng": 2, "lat": 1},
            {"lng": 3, "lat": 0}, {"lng": 4, "lat": 0},
        ]
        out = douglas_peucker(pts, tolerance=0.5)
        self.assertEqual([p["lng"] for p in out], [0, 2, 4])

    def test_route_thinned_over_threshold(self):
        """单条路线超阈值 → 抽稀并记录 thinned 元信息（平滑曲线保留形状特征点）。"""
        # 抛物线轨迹：曲率均匀分布，自适应容差下保留少量形状点而非塌缩为端点
        pts = [{"lng": i * 0.01, "lat": (i * 0.01) ** 2 * 0.01} for i in range(1000)]
        layer = grade_layer_density({"layerId": "L1", "routes": [{"name": "航迹1", "points": pts}]})
        route = layer["routes"][0]
        self.assertIn("thinned", route)
        self.assertEqual(route["thinned"]["original"], 1000)
        kept = len(route["points"])
        self.assertLessEqual(kept, 500)
        self.assertGreater(kept, 2)
        # 首尾点必保留（轨迹起止是业务关键信息）
        self.assertEqual(route["points"][0]["lng"], pts[0]["lng"])
        self.assertEqual(route["points"][-1]["lng"], pts[-1]["lng"])

    def test_route_below_threshold_untouched(self):
        pts = [{"lng": i, "lat": i} for i in range(100)]
        layer = grade_layer_density({"layerId": "L1", "routes": [{"points": pts}]})
        self.assertNotIn("thinned", layer["routes"][0])
        self.assertEqual(len(layer["routes"][0]["points"]), 100)

    def test_grade_normal_for_sparse_distributed_points(self):
        pts = [{"lng": i * 2.0, "lat": i * 2.0} for i in range(10)]
        layer = grade_layer_density({"layerId": "L1", "points": pts})
        self.assertEqual(layer["density"], "normal")

    def test_grade_cluster_by_count(self):
        pts = [{"lng": 100 + i * 0.1, "lat": 30} for i in range(300)]
        layer = grade_layer_density({"layerId": "L1", "points": pts})
        self.assertEqual(layer["density"], "cluster")

    def test_grade_cluster_by_spatial_aggregation(self):
        """点数未达阈值但空间高度聚集（最近邻均距 < 0.5°）→ cluster。"""
        pts = [{"lng": 100 + (i % 8) * 0.05, "lat": 30 + (i // 8) * 0.05} for i in range(64)]
        layer = grade_layer_density({"layerId": "L1", "points": pts})
        self.assertEqual(layer["density"], "cluster")

    def test_grade_heavy_by_feature_count(self):
        pts = [{"lng": 100 + i * 0.01, "lat": 30 + i * 0.01} for i in range(2000)]
        layer = grade_layer_density({"layerId": "L1", "points": pts})
        self.assertEqual(layer["density"], "heavy")

    def test_thinning_precedes_grading(self):
        """抽稀先于密度计数：3000 共线点抽稀到 2 点 → 不判 heavy（口径为渲染后）。"""
        pts = [{"lng": 100 + i * 0.001, "lat": 30.0} for i in range(3000)]
        layer = grade_layer_density({"layerId": "L1", "routes": [{"points": pts}]})
        self.assertEqual(layer["routes"][0]["thinned"]["kept"], 2)
        self.assertNotEqual(layer["density"], "heavy")

    def test_empty_layer_gets_normal(self):
        layer = grade_layer_density({"layerId": "L1"})
        self.assertEqual(layer["density"], "normal")

    def test_business_fields_preserved(self):
        """分级只追加 density/thinned 字段，业务字段不丢失。"""
        pts = [{"lng": 100 + i * 0.1, "lat": 30, "name": f"目标{i}", "extra": i} for i in range(300)]
        layer = grade_layer_density({"layerId": "L1", "points": pts, "layerConfig": {"k": 1}})
        self.assertEqual(layer["layerConfig"], {"k": 1})
        self.assertEqual(layer["points"][0]["name"], "目标0")
        self.assertEqual(layer["points"][299]["extra"], 299)


class FieldMappingVerifyTests(unittest.TestCase):
    """fieldMapping 校验：虚拟计数列 count 放行，其余列名必须命中真实列。"""

    def _chart(self, fm):
        return {
            "chartId": "c_test",
            "type": "pie",
            "fieldMapping": fm,
            "provenance": {"columns": ["range_id", "range_type", "radius_km"]},
        }

    def test_virtual_count_column_passes(self):
        """pie 按分类计数（yFields=['count']）→ 放行（虚拟计数列契约）。"""
        chart = self._chart({"xField": "range_type", "yFields": ["count"]})
        self.assertIsNone(check_chart_field_mapping(chart, None))

    def test_count_case_insensitive(self):
        chart = self._chart({"xField": "range_type", "yFields": ["COUNT"]})
        self.assertIsNone(check_chart_field_mapping(chart, None))

    def test_mixed_count_and_real_column(self):
        """count 与真实列混用 → 真实列逐名校验。"""
        ok = self._chart({"xField": "range_type", "yFields": ["count", "radius_km"]})
        self.assertIsNone(check_chart_field_mapping(ok, None))
        bad = self._chart({"xField": "range_type", "yFields": ["count", "不存在列"]})
        self.assertIn("yFields", check_chart_field_mapping(bad, None))

    def test_fake_column_still_rejected(self):
        chart = self._chart({"xField": "range_type", "yFields": ["fake_col"]})
        self.assertIn("fake_col", check_chart_field_mapping(chart, None))

    def test_fake_xfield_still_rejected(self):
        chart = self._chart({"xField": "not_a_col", "yFields": ["count"]})
        self.assertIn("xField", check_chart_field_mapping(chart, None))

    def test_no_field_mapping_skipped(self):
        self.assertIsNone(check_chart_field_mapping({"chartId": "c", "type": "bar"}, None))


if __name__ == "__main__":
    unittest.main()
