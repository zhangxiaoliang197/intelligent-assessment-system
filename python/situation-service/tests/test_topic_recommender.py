from __future__ import annotations

import unittest

from topic_recommender import build_contextual_generation_query, recommend_topic_situations


class TopicRecommendationTests(unittest.TestCase):
    def test_default_topics_cover_complementary_dimensions(self):
        result = recommend_topic_situations(
            "战斗机巡航覆盖范围态势",
            context={"selectedRegion": "华北", "skillName": "巡航覆盖分析"},
        )

        self.assertEqual(result["total"], 4)
        self.assertEqual(
            [item["dimension"] for item in result["items"]],
            ["空间聚焦", "时间演化", "对比研判", "风险预警"],
        )
        self.assertIn("华北", result["items"][0]["query"])
        self.assertIn("区域：华北", result["contextTags"])

    def test_user_follow_up_becomes_first_standalone_topic(self):
        result = recommend_topic_situations(
            "舰艇编队部署态势",
            "只看补给薄弱的编队",
            {"selectedTimeRange": ["2026-08-01", "2026-08-31"]},
            limit=3,
        )

        first = result["items"][0]
        self.assertEqual(first["dimension"], "追问专题")
        self.assertIn("舰艇编队部署态势", first["query"])
        self.assertIn("只看补给薄弱的编队", first["query"])
        self.assertEqual(result["total"], 3)

    def test_resolved_skill_is_attached_to_topic(self):
        result = recommend_topic_situations(
            "雷达探测范围态势",
            skill_resolver=lambda _query: {
                "id": "recon-warning-coverage",
                "name": "侦察预警覆盖分析",
                "recommendationReason": "命中覆盖盲区",
            },
            limit=1,
        )

        topic = result["items"][0]
        self.assertEqual(topic["skillId"], "recon-warning-coverage")
        self.assertEqual(topic["skillName"], "侦察预警覆盖分析")

    def test_follow_up_generation_keeps_parent_context_and_evidence_boundary(self):
        query = build_contextual_generation_query("再看华北", "雷达探测范围态势")

        self.assertIn("上一轮态势主题：雷达探测范围态势", query)
        self.assertIn("当前用户追问：再看华北", query)
        self.assertIn("不得臆造", query)
        self.assertEqual(build_contextual_generation_query("同一问题", "同一问题"), "")


if __name__ == "__main__":
    unittest.main()
