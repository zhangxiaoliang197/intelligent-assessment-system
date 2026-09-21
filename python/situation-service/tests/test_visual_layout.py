"""版式骨架与视觉反馈循环单元测试（态势图-版式骨架与视觉反馈循环方案 §四）。

覆盖：
- layout_skeletons：画像构建、拟合排序、5 骨架渲染契约（占位符完整性）
- writer._sit_signature：占位符契约签名提取与破坏检测
- visual_judge：JSON 解析、KPI 填充聚合、强制择优、可选依赖探测
"""
from __future__ import annotations

import asyncio
import unittest

from agent import layout_skeletons
from agent.evidence_store import Evidence, EvidenceStore
from agent.writer import _sit_signature
from agent.visual_judge import _agg_value, _kpi_fill_from_html, _parse_json, pick_winner


def _make_store() -> EvidenceStore:
    """构建带两条证据的测试 store。"""
    store = EvidenceStore(report_id="r_test")
    ev1 = Evidence(
        id="q1", sub_question="各类型数量",
        rows=[{"type": "A", "amount": 10}, {"type": "B", "amount": 20}, {"type": "C", "amount": 30}],
        columns=["type", "amount"], summary="测试", source="ds_1", dataset_ref="ds_1",
    )
    ev2 = Evidence(
        id="q2", sub_question="地理分布",
        rows=[{"lon": 116.4, "lat": 39.9}], columns=["lon", "lat"],
        summary="地理", source="ds_2", dataset_ref="ds_2",
        meta={"geoProfile": {"hasGeo": True}},
    )
    asyncio.run(store.add_evidence(ev1))
    asyncio.run(store.add_evidence(ev2))
    return store


def _charts(n: int) -> list:
    """生成 n 个测试图表元信息。"""
    return [
        {"chartId": f"c{i}", "type": "bar", "title": f"图表{i}",
         "explanation": "说明", "datasetRef": "q1"}
        for i in range(1, n + 1)
    ]


def _sit_tags(html: str) -> list:
    """提取 HTML 中全部 data-sit 类型（用于契约断言）。"""
    import re
    return re.findall(r'data-sit="([a-z_]+)"', html)


class LayoutSkeletonTests(unittest.TestCase):
    """骨架库：画像、排序、渲染契约。"""

    def test_build_profile_counts(self):
        profile = layout_skeletons.build_profile(
            _charts(4), {"points": [1, 2], "routes": []},
            {"intro": "概述", "explanations": [{"chartId": "c1", "text": "x"}]},
            [{"datasetId": "q1", "columns": ["type", "amount"], "rowCount": 3}],
        )
        self.assertEqual(profile["chart_count"], 4)
        self.assertTrue(profile["has_map"])
        self.assertTrue(profile["has_intro"])
        self.assertIn("c1", profile["explanations"])
        self.assertEqual(len(profile["kpi_datasets"]), 1)

    def test_rank_skeletons_map_scenario(self):
        """地图主导场景（空间意图问题 + 有地图产物）：S2 应排第一。"""
        query = "我方战机巡航轨迹分布"
        profile = layout_skeletons.build_profile(_charts(2), {"points": [1]}, None, [], query=query)
        ranked = layout_skeletons.rank_skeletons(profile, query=query)
        self.assertEqual(ranked[0]["id"], "S2")

    def test_rank_skeletons_map_without_geo_intent(self):
        """有地图但无空间意图（地图是配图）：S2 不应以绝对优势霸榜第一。"""
        profile = layout_skeletons.build_profile(_charts(2), {"points": [1]}, None, [])
        self.assertLess(profile["map_importance"], 0.7)
        ranked = layout_skeletons.rank_skeletons(profile)
        # 地图重要性低时 S2 拟合分与简报/叙事型处于同分组，Top1 由扰动决定而非恒为 S2
        self.assertIn(ranked[0]["id"], ("S2", "S4", "S5"))

    def test_rank_skeletons_many_charts_no_map(self):
        """多图表无地图场景：S1/S3 应优于 S2（S2 对无地图强惩罚）。"""
        profile = layout_skeletons.build_profile(_charts(5), None, None, [])
        ranked = layout_skeletons.rank_skeletons(profile)
        ids = [s["id"] for s in ranked]
        self.assertNotEqual(ids[0], "S2")

    def test_render_contract_all_skeletons(self):
        """每个骨架渲染产物必须满足占位符契约：图表占位齐全、地图恰一/零个。"""
        for charts_n, has_map in ((3, True), (2, False), (1, True)):
            profile = layout_skeletons.build_profile(
                _charts(charts_n), {"points": [1]} if has_map else None,
                {"intro": "概述", "explanations": [{"chartId": "c1", "text": "x"}]},
                [{"datasetId": "q1", "columns": ["type"], "rowCount": 3}],
            )
            for sk in layout_skeletons.SKELETONS:
                html = sk["render"](profile, "测试问题")
                tags = _sit_tags(html)
                # 图表占位符数量与 chartId 一致
                self.assertEqual(tags.count("chart"), charts_n,
                                 f"{sk['id']} 图表占位符数量不符")
                # 地图占位符：有地图恰 1 个，无地图 0 个
                self.assertEqual(tags.count("map"), 1 if has_map else 0,
                                 f"{sk['id']} 地图占位符数量不符")
                # narrative 占位符存在（intro 有值）
                self.assertIn("narrative", tags)
                # chart 占位符必须带确定高度（评委渲染与前端挂载共同依赖）
                self.assertNotIn('data-sit="chart" data-ref="c1" style=""', html)
                self.assertIn('data-ref="c1"', html)


class SitSignatureTests(unittest.TestCase):
    """占位符契约签名。"""

    HTML = (
        '<div data-sit="kpi" data-ref="q1"></div>'
        '<div data-sit="chart" data-ref="c1" style="height:320px"></div>'
        '<div data-sit="map" style="height:400px"></div>'
    )

    def test_signature_extraction(self):
        sig = _sit_signature(self.HTML)
        self.assertEqual(sig, [("kpi", "q1"), ("chart", "c1"), ("map", "")])

    def test_signature_detects_removed_placeholder(self):
        broken = self.HTML.replace('data-sit="chart" data-ref="c1" style="height:320px"', "")
        self.assertNotEqual(_sit_signature(broken), _sit_signature(self.HTML))

    def test_signature_detects_changed_ref(self):
        broken = self.HTML.replace('data-ref="c1"', 'data-ref="c9"')
        self.assertNotEqual(_sit_signature(broken), _sit_signature(self.HTML))

    def test_signature_ignores_style_changes(self):
        changed = self.HTML.replace("height:320px", "height:280px")
        self.assertEqual(_sit_signature(changed), _sit_signature(self.HTML))


class VisualJudgePureTests(unittest.TestCase):
    """visual_judge 纯函数（不依赖浏览器）。"""

    def test_parse_json_plain_and_wrapped(self):
        data = {"scores": {"alignment": 8}, "total": 8}
        self.assertEqual(_parse_json('{"scores": {"alignment": 8}, "total": 8}'), data)
        wrapped = '```json\n{"scores": {"alignment": 8}, "total": 8}\n```'
        self.assertEqual(_parse_json(wrapped), data)
        with self.assertRaises(ValueError):
            _parse_json("完全不是 JSON")

    def test_agg_value(self):
        rows = [{"amount": 10}, {"amount": 20}, {"amount": None}]
        self.assertEqual(_agg_value(rows, "amount", "sum"), 30)
        self.assertEqual(_agg_value(rows, "amount", "avg"), 15)
        self.assertEqual(_agg_value(rows, "amount", "max"), 20)
        self.assertEqual(_agg_value(rows, "type", "count"), 3)
        self.assertEqual(_agg_value(rows, "missing", "count"), 3)
        self.assertEqual(_agg_value(rows, "missing", "sum"), "-")

    def test_kpi_fill_uses_real_evidence(self):
        store = _make_store()
        html = (
            '<div data-sit="kpi" data-ref="q1" '
            'data-metrics=\'[{"label":"总量","column":"amount","agg":"sum"}]\'></div>'
        )
        fills = _kpi_fill_from_html(html, store)
        self.assertEqual(len(fills), 1)
        self.assertIn("60.0", fills[0]["html"])  # 10+20+30 聚合为 60

    def test_pick_winner_none_and_basis_mismatch(self):
        skel = {"html": "s", "rule": 8.0, "vlm": None, "total": 8.0, "vlm_ok": False}
        # 自定义缺失 → 骨架直接获胜
        self.assertIs(pick_winner(skel, None), skel)

        cust = {"html": "c", "rule": 9.0, "vlm": None, "total": 9.0, "vlm_ok": False}
        # 骨架 vlm_ok=True / 自定义 False：口径不一致，退骨架
        skel_vlm = dict(skel, vlm_ok=True)
        self.assertIs(pick_winner(skel_vlm, cust), skel_vlm)

    def test_pick_winner_margin(self):
        skel = {"html": "s", "total": 8.0, "vlm_ok": True}
        # 自定义 8.2 未超过 8.0 + 0.5 margin → 保留骨架
        self.assertIs(pick_winner(skel, {"html": "c", "total": 8.2, "vlm_ok": True}), skel)
        # 自定义 8.8 > 8.5 → 采纳自定义
        self.assertEqual(pick_winner(skel, {"html": "c", "total": 8.8, "vlm_ok": True})["html"], "c")


class StyleTokensTests(unittest.TestCase):
    """主题令牌层：钳制、对比度校验、预设确定性、CSS 拼装白名单。"""

    def test_sanitize_empty_equals_default(self):
        from agent.style_tokens import DEFAULT_TOKENS, sanitize_tokens
        self.assertEqual(sanitize_tokens({}), dict(DEFAULT_TOKENS))
        self.assertEqual(sanitize_tokens(None), dict(DEFAULT_TOKENS))
        self.assertEqual(sanitize_tokens("垃圾输入"), dict(DEFAULT_TOKENS))

    def test_sanitize_clamps_numbers(self):
        from agent.style_tokens import sanitize_tokens
        tokens = sanitize_tokens({"radius": 50, "gap": 5, "pad": 999, "title_weight": 100})
        self.assertEqual(tokens["radius"], 16)   # 上边界
        self.assertEqual(tokens["gap"], 12)      # 下边界
        self.assertEqual(tokens["pad"], 24)      # 上边界
        self.assertEqual(tokens["title_weight"], 600)

    def test_sanitize_rejects_bad_hex(self):
        from agent.style_tokens import sanitize_tokens
        tokens = sanitize_tokens({"primary": "javascript:alert(1)", "bg": "#zzz"})
        self.assertEqual(tokens["primary"], "#2563eb")
        self.assertEqual(tokens["bg"], "#f5f7fa")

    def test_sanitize_contrast_fallback(self):
        """正文色太浅（对比 <4.5）→ 回退默认深色。"""
        from agent.style_tokens import DEFAULT_TOKENS, sanitize_tokens
        tokens = sanitize_tokens({"text": "#999999", "muted": "#aaaaaa"})
        self.assertEqual(tokens["text"], DEFAULT_TOKENS["text"])
        self.assertEqual(tokens["muted"], DEFAULT_TOKENS["muted"])

    def test_sanitize_clamps_dark_bg_to_light(self):
        """LLM 给了深色页面底 → 钳制到浅色域（可读性兜底）。"""
        from agent.style_tokens import sanitize_tokens, _contrast
        tokens = sanitize_tokens({"bg": "#111111"})
        self.assertGreaterEqual(_contrast(tokens["text"], tokens["bg"]), 4.5)

    def test_presets_all_pass_own_gate(self):
        """预设池全部通过自身对比度校验（sanitize 后可读性达标）。"""
        from agent.style_tokens import _PRESETS, sanitize_tokens, _contrast
        for preset in _PRESETS:
            clean = sanitize_tokens(preset)
            # 预设色经 HSL 往返可能产生 ±1 的精度漂移，只校验可读性不回退到默认
            self.assertGreaterEqual(_contrast(clean["primary"], clean["card"]), 3.0,
                                     f"{preset['mood']} 主色对比度不足")
            self.assertGreaterEqual(_contrast(clean["accent"], clean["card"]), 3.0,
                                     f"{preset['mood']} 强调色对比度不足")
            self.assertGreaterEqual(_contrast(clean["text"], clean["card"]), 4.5)

    def test_preset_pick_deterministic(self):
        from agent.style_tokens import pick_preset
        self.assertEqual(pick_preset("电商运输态势"), pick_preset("电商运输态势"))
        self.assertEqual(pick_preset(""), pick_preset(""))

    def test_tokens_to_css_whitelist_only(self):
        """css 块只含白名单变量；mood（LLM 自由文本）绝不进入 CSS。"""
        from agent.style_tokens import sanitize_tokens, tokens_to_css
        tokens = sanitize_tokens({"mood": "邪恶<style>alert(1)</style>风格"})
        css = tokens_to_css(tokens)
        self.assertTrue(css.startswith(":root{--sit-primary:"))
        self.assertIn("--sit-accent:", css)
        self.assertNotIn("alert", css)          # mood 不进 CSS
        self.assertNotIn("<style>", css)

    def test_llm_generation_falls_back_to_preset(self):
        """LLM 不可用时（mock 抛异常）→ 预设主题，source=preset。"""
        from unittest.mock import patch
        from agent import style_tokens
        with patch.object(style_tokens, "call_llm", side_effect=RuntimeError("402")):
            result = style_tokens.generate_style_tokens("测试", "3 图表")
        self.assertEqual(result["source"], "preset")
        self.assertTrue(result["css"].startswith(":root{"))


class SemanticFitTests(unittest.TestCase):
    """叙事语义拟合：加分规则与排序影响。"""

    def _profile(self) -> dict:
        """边缘画像：S1/S4 竞争区间（3 图、有介绍）。"""
        return layout_skeletons.build_profile(
            _charts(3), None,
            {"intro": "概述", "explanations": [{"chartId": "c1", "text": "x"}]},
            [{"datasetId": "q1", "columns": ["type"], "rowCount": 3}],
        )

    def test_semantic_none_is_pure_profile(self):
        """semantic=None 时与旧签名行为完全一致（现状旁路）。"""
        p = self._profile()
        for sk in layout_skeletons.SKELETONS:
            self.assertEqual(sk["fit"](p), sk["fit"](p, None))

    def test_alert_bonus_s1(self):
        p = self._profile()
        self.assertAlmostEqual(
            layout_skeletons._fit_s1(p, {"polarity": "alert"}),
            layout_skeletons._fit_s1(p) + 0.10,
        )

    def test_geo_focus_bonus_s2(self):
        """有地图产物时，叙事焦点含空间词 → S2 +0.12。"""
        p = layout_skeletons.build_profile(_charts(2), {"points": [1]}, None, [])
        self.assertAlmostEqual(
            layout_skeletons._fit_s2(p, {"polarity": "neutral", "focus": "geo 分布"}),
            layout_skeletons._fit_s2(p) + 0.12,
        )

    def test_no_map_s2_disqualified(self):
        """无地图产物时 S2 直接出局（杜绝"无图的大图版式"），语义加分也不复活。"""
        p = self._profile()  # 无地图
        self.assertEqual(layout_skeletons._fit_s2(p), 0.0)
        self.assertEqual(layout_skeletons._fit_s2(p, {"focus": "geo 分布"}), 0.0)

    def test_unknown_polarity_no_effect(self):
        p = self._profile()
        self.assertAlmostEqual(
            layout_skeletons._fit_s1(p, {"polarity": "bogus"}),
            layout_skeletons._fit_s1(p),
        )

    def test_polarity_flips_ranking(self):
        """平手决胜：alert 语义使 S1 拟合分反超 S4（分差验证；Top1 落点由同分扰动收口）。"""
        p = self._profile()
        # 纯画像：S4 高于 S1
        self.assertGreater(layout_skeletons._fit_s4(p), layout_skeletons._fit_s1(p))
        # alert 语义：S1 +0.10 后反超
        self.assertGreater(
            layout_skeletons._fit_s1(p, {"polarity": "alert"}),
            layout_skeletons._fit_s4(p, {"polarity": "alert"}),
        )

    def test_tie_rotation_deterministic(self):
        """同分扰动：同问题同画像结果可复现，且 5 骨架全体保留不丢失。"""
        p = self._profile()
        r1 = [s["id"] for s in layout_skeletons.rank_skeletons(p, query="问题甲")]
        r2 = [s["id"] for s in layout_skeletons.rank_skeletons(p, query="问题甲")]
        self.assertEqual(r1, r2)
        self.assertEqual(sorted(r1), ["S1", "S2", "S3", "S4", "S5"])

    def test_tie_rotation_diversity(self):
        """同分组内 Top1 随问题轮转（跨任务多样性）：该画像 S4/S1 同分，二者都应能居首。"""
        p = self._profile()
        tops = {
            layout_skeletons.rank_skeletons(p, query=f"态势问题{i}")[0]["id"]
            for i in range(10)
        }
        self.assertEqual(tops, {"S1", "S4"})


class ArtifactPromptInjectionTests(unittest.TestCase):
    """artifact prompt 注入：主题令牌与叙事指导。"""

    def _messages(self, tokens=None, semantic=None):
        from agent import prompts
        return prompts.build_artifact_messages(
            "测试问题", [{"chartId": "c1", "type": "bar", "title": "图1"}],
            None, [], {"intro": "概述", "explanations": []},
            tokens=tokens, semantic=semantic,
        )

    def test_no_injection_by_default(self):
        system = self._messages()[0]["content"]
        self.assertNotIn("主题令牌", system)
        self.assertNotIn("叙事指导", system)

    def test_tokens_injected(self):
        tokens = {"primary": "#0f766e", "accent": "#d97706", "mood": "沉静监测风",
                  "bg": "#f3f8f6", "card": "#ffffff", "text": "#134e4a",
                  "muted": "#5c7a75", "radius": 10, "gap": 16, "pad": 16,
                  "title_weight": 700}
        system = self._messages(tokens=tokens)[0]["content"]
        self.assertIn("【主题令牌（必须遵守）】", system)
        self.assertIn("#0f766e", system)
        self.assertIn("沉静监测风", system)
        self.assertIn(":root{--sit-primary", system)

    def test_semantic_injected(self):
        system = self._messages(semantic={"polarity": "alert", "focus": "异常项"})[0]["content"]
        self.assertIn("【叙事指导", system)
        self.assertIn("预警", system)
        self.assertIn("异常项", system)


class DependencyProbeTests(unittest.TestCase):
    """可选依赖探测：playwright/chromium 缺失时应判定不可用而非抛异常。"""

    def test_is_available_returns_bool(self):
        from agent import visual_judge
        self.assertIsInstance(visual_judge.is_available(), bool)


class ProfileFactorTests(unittest.TestCase):
    """产物画像多因子构建（多因素骨架选型 §三.③）：地图重要性/句式意图/数据体量/图型构成。"""

    def _profile(self, charts=None, map_layer=None, datasets=None, query="", semantic=None):
        return layout_skeletons.build_profile(
            charts if charts is not None else _charts(2),
            map_layer, None,
            datasets or [], query=query, semantic=semantic,
        )

    def test_map_importance_no_map_is_zero(self):
        self.assertEqual(self._profile(map_layer=None)["map_importance"], 0.0)

    def test_map_importance_geo_query_boost(self):
        """空间意图问题使地图重要性显著上升（配图 → 主角）。"""
        plain = self._profile(map_layer={"points": [1]})["map_importance"]
        geo = self._profile(map_layer={"points": [1]}, query="我方战机巡航轨迹分布")["map_importance"]
        self.assertEqual(plain, 0.4)
        self.assertEqual(geo, 0.7)  # 基础 0.4 + 空间意图 0.3

    def test_map_importance_scales_with_features(self):
        many = self._profile(map_layer={"points": list(range(50))})["map_importance"]
        few = self._profile(map_layer={"points": [1]})["map_importance"]
        self.assertGreater(many, few)

    def test_question_intent_rules(self):
        self.assertEqual(self._profile(query="各基地出动架次对比")["question_intent"], "compare")
        self.assertEqual(self._profile(query="重点目标预警监控")["question_intent"], "alert")
        self.assertEqual(self._profile(query="近一周出动量变化趋势")["question_intent"], "trend")
        self.assertEqual(self._profile(query="总体情况如何")["question_intent"], "overview")

    def test_question_intent_semantic_overrides_query(self):
        """Planner 叙事标签优先于关键词规则。"""
        p = self._profile(query="总体情况如何", semantic={"polarity": "alert"})
        self.assertEqual(p["question_intent"], "alert")

    def test_data_volume_tiers(self):
        mk = lambda n: [{"datasetId": "d1", "columns": ["a"], "rowCount": n}]
        self.assertEqual(self._profile(datasets=mk(100))["data_volume"], "small")
        self.assertEqual(self._profile(datasets=mk(500))["data_volume"], "medium")
        self.assertEqual(self._profile(datasets=mk(5000))["data_volume"], "large")

    def test_chart_type_mix_counts(self):
        charts = [
            {"chartId": "c1", "type": "bar", "title": "a"},
            {"chartId": "c2", "type": "line", "title": "b"},
            {"chartId": "c3", "type": "pie", "title": "c"},
            {"chartId": "c4", "type": "bar", "title": "d"},
        ]
        mix = self._profile(charts=charts)["chart_type_mix"]
        self.assertEqual(mix, {"bar": 2, "line": 1, "pie": 1})


if __name__ == "__main__":
    unittest.main()
