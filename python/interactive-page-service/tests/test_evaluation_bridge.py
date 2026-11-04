"""评估产物桥接层单元测试：产物 → bundle/plan 的映射、脱敏与兜底。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from agent.evaluation_bridge import build_bundle_and_plan
from models import ArtifactItem, EvaluationArtifacts


def make_artifacts(items, conclusion="", presentation=None, title="", skill_name=""):
    """构造评估产物请求体，便于各用例复用。"""
    return EvaluationArtifacts(
        sourceSessionId="eval-1",
        question="红蓝空中力量对比",
        title=title,
        skillName=skill_name,
        conclusion=conclusion,
        presentation=presentation or {"kpi": True, "chart": True, "map": True, "table": False},
        items=items,
    )


def numeric_item(item_id="q1", name="红方统计"):
    """构造一个可图表的聚合产物。"""
    return ArtifactItem(
        artifactId=item_id,
        name=name,
        purpose="统计红方各机型数量",
        mode="aggregate",
        columns=["机型", "数量"],
        rows=[{"机型": "歼-20", "数量": 3}, {"机型": "歼-16", "数量": 5}],
        totalRows=2,
    )


class BundleMappingTest(unittest.TestCase):
    def test_selected_items_only(self):
        """只勾选两项时，数据包与规划区块只能引用这两项。"""
        artifacts = make_artifacts([
            numeric_item("q1", "红方统计"),
            numeric_item("q2", "蓝方统计"),
        ], conclusion="红方数量略占优")

        bundle, plan, _ = build_bundle_and_plan(artifacts, "红蓝对比")

        self.assertEqual([d["id"] for d in bundle["datasets"]], ["q1", "q2"])
        refs = {s.get("ref") for s in plan["sections"] if s.get("ref")}
        self.assertEqual(refs, {"q1", "q2"})
        self.assertEqual(plan["origin"]["type"], "evaluation")
        self.assertEqual(plan["origin"]["artifactIds"], ["q1", "q2"])
        # 结论随数据包下发，供页面写作直接渲染
        self.assertEqual(bundle.get("conclusion"), "红方数量略占优")
        # 结论勾选后必须有 text 区块
        self.assertTrue(any(s["kind"] == "text" for s in plan["sections"]))

    def test_no_items_only_conclusion_raises(self):
        """只有结论没有数据行时，无法生成页面。"""
        artifacts = make_artifacts([], conclusion="仅有一段文字结论")
        with self.assertRaises(ValueError):
            build_bundle_and_plan(artifacts, "红蓝对比")

    def test_empty_rows_item_skipped(self):
        """无数据行的条目会被跳过；全部为空则报错。"""
        empty = ArtifactItem(artifactId="q1", name="空步骤", columns=["列"], rows=[])
        artifacts = make_artifacts([empty], conclusion="")
        with self.assertRaises(ValueError):
            build_bundle_and_plan(artifacts, "红蓝对比")

    def test_title_fallbacks(self):
        """标题为空时依次回退到技能名与问题。"""
        artifacts = make_artifacts([numeric_item()], skill_name="空中力量评估")
        _, plan, _ = build_bundle_and_plan(artifacts, "红蓝对比")
        self.assertEqual(plan["title"], "空中力量评估 · 态势分析")

        artifacts2 = EvaluationArtifacts(
            question="",
            presentation={"kpi": True, "chart": True, "map": True, "table": False},
            items=[numeric_item()],
        )
        _, plan2, _ = build_bundle_and_plan(artifacts2, "红蓝对比")
        self.assertEqual(plan2["title"], "红蓝对比")


class GeoConversionTest(unittest.TestCase):
    def test_markers_to_points(self):
        """经纬度标点 → geoFeatures.points，且 geo.kind=points。"""
        item = ArtifactItem(
            artifactId="q1",
            name="基地分布",
            mode="detail",
            columns=["名称", "经度", "纬度"],
            rows=[{"名称": "基地A", "经度": 116.4, "纬度": 39.9}],
            totalRows=1,
            geo={"markers": [{"name": "基地A", "lng": 116.4, "lat": 39.9,
                              "props": {"类型": "保障基地"}}]},
        )
        bundle, plan, _ = build_bundle_and_plan(make_artifacts([item]), "")
        entry = bundle["datasets"][0]
        self.assertEqual(entry["geo"]["kind"], "points")
        self.assertEqual(len(entry["geoFeatures"]["points"]), 1)
        self.assertEqual(entry["geoFeatures"]["points"][0]["name"], "基地A")
        self.assertTrue(any(s["kind"] == "map" for s in plan["sections"]))

    def test_areas_to_circles(self):
        """范围圈 → circles（lng/lat/radiusKm）。"""
        item = ArtifactItem(
            artifactId="q1",
            name="防空阵地",
            mode="detail",
            columns=["名称", "经度", "纬度"],
            rows=[{"名称": "阵地A", "经度": 120.0, "纬度": 30.0}],
            totalRows=1,
            geo={"areas": [{"name": "阵地A", "lng": 120.0, "lat": 30.0, "radiusKm": 80}]},
        )
        bundle, _, _ = build_bundle_and_plan(make_artifacts([item]), "")
        entry = bundle["datasets"][0]
        self.assertEqual(entry["geo"]["kind"], "circles")
        self.assertEqual(entry["geoFeatures"]["circles"][0]["radiusKm"], 80.0)


class DataGovernanceTest(unittest.TestCase):
    def test_rows_truncated_to_chart_limit(self):
        """聚合产物超过图表行数上限时截断并标记。"""
        rows = [{"分组": f"G{i}", "数量": i} for i in range(config.IPAGE_CHART_ROW_LIMIT + 100)]
        item = ArtifactItem(artifactId="q1", name="大结果", mode="aggregate",
                            columns=["分组", "数量"], rows=rows, totalRows=len(rows))
        bundle, _, _ = build_bundle_and_plan(make_artifacts([item]), "")
        entry = bundle["datasets"][0]
        self.assertEqual(len(entry["rows"]), config.IPAGE_CHART_ROW_LIMIT)
        self.assertTrue(entry["truncated"])

    def test_sensitive_column_removed(self):
        """敏感列（如姓名）不会进入页面数据包。"""
        item = ArtifactItem(
            artifactId="q1", name="人员", mode="aggregate",
            columns=["姓名", "数量"],
            rows=[{"姓名": "张三", "数量": 2}],
        )
        bundle, _, _ = build_bundle_and_plan(make_artifacts([item]), "")
        entry = bundle["datasets"][0]
        self.assertNotIn("姓名", entry["columns"])
        self.assertNotIn("姓名", entry["rows"][0])

    def test_illegal_id_sanitized_and_unique(self):
        """非法字符被清洗，重复 id 自动去重。"""
        item1 = numeric_item("q 1#", "A")
        item2 = numeric_item("q1", "B")
        bundle, plan, _ = build_bundle_and_plan(make_artifacts([item1, item2]), "")
        ids = [d["id"] for d in bundle["datasets"]]
        self.assertEqual(ids[0], "q1")
        self.assertNotEqual(ids[0], ids[1])
        self.assertTrue(all(s.get("ref", "") in ids or not s.get("ref")
                            for s in plan["sections"]))


class PlanPresentationTest(unittest.TestCase):
    def test_template_fallback_renders_bundle(self):
        """产物数据包可直接被确定性模板兜底渲染（LLM 不可用时仍能出页）。"""
        from agent.template_render import render_template_page

        bundle, _, _ = build_bundle_and_plan(
            make_artifacts([numeric_item()], conclusion="红方数量略占优"), "红蓝对比")
        html = render_template_page(bundle)
        self.assertIn("<!DOCTYPE html", html)
        # 模板在运行时从数据包读取数据集，HTML 中只保留运行时契约
        self.assertIn("SitChart.render", html)
        self.assertIn("SitApp.bootstrap", html)
        # 评估结论由模板按 data.conclusion 渲染
        self.assertIn("data.conclusion", html)

    def test_table_off_by_default(self):
        """有图表可出时，明细表默认关闭。"""
        _, plan, _ = build_bundle_and_plan(make_artifacts([numeric_item()]), "")
        self.assertFalse(any(s["kind"] == "table" for s in plan["sections"]))

    def test_detail_only_falls_back_to_table(self):
        """明细数据没有图表时，自动补明细表，避免页面只剩 KPI/结论。"""
        item = ArtifactItem(
            artifactId="q1", name="明细", mode="detail",
            columns=["区域", "数量"],
            rows=[{"区域": "A", "数量": 1}, {"区域": "B", "数量": 2}],
        )
        _, plan, _ = build_bundle_and_plan(make_artifacts([item]), "")
        self.assertTrue(any(s["kind"] == "table" for s in plan["sections"]))

    def test_table_on(self):
        """显式开启明细表时产生 table 区块。"""
        item = ArtifactItem(
            artifactId="q1", name="明细", mode="detail",
            columns=["区域", "数量"],
            rows=[{"区域": "A", "数量": 1}, {"区域": "B", "数量": 2}],
        )
        presentation = {"kpi": True, "chart": True, "map": True, "table": True}
        _, plan, _ = build_bundle_and_plan(
            make_artifacts([item], presentation=presentation), "")
        self.assertTrue(any(s["kind"] == "table" for s in plan["sections"]))

    def test_fallback_section_when_all_switches_off(self):
        """所有呈现开关关闭时仍至少保留一个可视化区块。"""
        item = ArtifactItem(
            artifactId="q1", name="明细", mode="detail",
            columns=["区域", "数量"],
            rows=[{"区域": "A", "数量": 1}],
        )
        presentation = {"kpi": False, "chart": False, "map": False, "table": False}
        _, plan, _ = build_bundle_and_plan(
            make_artifacts([item], presentation=presentation), "")
        self.assertTrue(plan["sections"])
        self.assertIn(plan["sections"][0]["kind"], ("chart", "table"))


if __name__ == "__main__":
    unittest.main()
