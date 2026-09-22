"""技能语义匹配测试：余弦打分、top-k 均值、双阈值与歧义门控、降级、缓存。

不联网：向量接口由注入的假实现替代（按文本查表返回预设向量）。
"""
import math
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from agent import skill_catalog, skill_matcher

SKILL_TEMPLATE = """---
id: {sid}
name: {name}
description: {desc}
order: {order}
triggers:
  - {t1}
  - {t2}
  - {t3}
---

## 取数剧本
- need: entityKind=air, mode=aggregate, question=统计数量

## 区块剧本
kpi → chart → text

## 呈现偏好
- 克制配色

## 叙事要点
- 先给总量
"""


def _unit(cos_value: float):
    """构造与 [1, 0] 余弦恰为 cos_value 的单位向量。"""
    return [cos_value, math.sqrt(max(0.0, 1.0 - cos_value * cos_value))]


class _FakeEmbedder:
    """假向量服务：按文本查表返回预设向量，未知文本返回正交向量。"""

    def __init__(self):
        self.table = {}
        self.calls = 0

    def __call__(self, texts, timeout=0):
        self.calls += 1
        return [list(self.table.get(str(t), [0.0, 0.0, 1.0])) for t in texts]


class _MatcherCase(unittest.TestCase):

    def setUp(self):
        self._saved_dir = config.IPAGE_SKILLS_DIR
        self._saved_cfg = (
            config.IPAGE_SKILL_MATCH_HIGH, config.IPAGE_SKILL_MATCH_LOW,
            config.IPAGE_SKILL_MATCH_MARGIN, config.IPAGE_SKILL_MATCH_TOP_K,
            config.IPAGE_SKILL_MATCH_ENABLED,
        )
        # 阈值固定，避免受默认值调整影响
        config.IPAGE_SKILL_MATCH_HIGH = 0.80
        config.IPAGE_SKILL_MATCH_LOW = 0.50
        config.IPAGE_SKILL_MATCH_MARGIN = 0.05
        config.IPAGE_SKILL_MATCH_TOP_K = 3
        config.IPAGE_SKILL_MATCH_ENABLED = True

        self.tmp = tempfile.mkdtemp(prefix="ipage_skill_match_")
        config.IPAGE_SKILLS_DIR = self.tmp

        self.embed = _FakeEmbedder()
        self._saved_embed = skill_matcher.embed_texts
        skill_matcher.embed_texts = self.embed
        skill_catalog.clear_cache()
        skill_matcher.clear_cache()

    def tearDown(self):
        skill_matcher.embed_texts = self._saved_embed
        (config.IPAGE_SKILL_MATCH_HIGH, config.IPAGE_SKILL_MATCH_LOW,
         config.IPAGE_SKILL_MATCH_MARGIN, config.IPAGE_SKILL_MATCH_TOP_K,
         config.IPAGE_SKILL_MATCH_ENABLED) = self._saved_cfg
        config.IPAGE_SKILLS_DIR = self._saved_dir
        skill_catalog.clear_cache()
        skill_matcher.clear_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_skill(self, sid, name, desc, triggers, vector, order=10):
        content = SKILL_TEMPLATE.format(sid=sid, name=name, desc=desc, order=order,
                                        t1=triggers[0], t2=triggers[1], t3=triggers[2])
        path = os.path.join(self.tmp, sid)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, skill_catalog.SKILL_FILE_NAME), "w", encoding="utf-8") as fh:
            fh.write(content)
        for text in [name, desc] + list(triggers):
            self.embed.table[text] = list(vector)
        skill_catalog.clear_cache()
        return sid

    def _ask(self, query, cos_value=1.0):
        """查询向量默认取 [1, 0]，使技能得分恰等于其语料向量的余弦分量。"""
        self.embed.table[query] = _unit(cos_value)
        return skill_matcher.match(query)


class CosineTest(unittest.TestCase):

    def test_cosine_basic(self):
        self.assertAlmostEqual(1.0, skill_matcher._cosine([1, 0], [1, 0]), places=6)
        self.assertAlmostEqual(0.0, skill_matcher._cosine([1, 0], [0, 1]), places=6)
        self.assertAlmostEqual(0.0, skill_matcher._cosine([0, 0], [1, 0]), places=6)
        self.assertAlmostEqual(0.0, skill_matcher._cosine([1, 0], [1, 0, 0]), places=6)

    def test_score_skill_uses_top_k_mean(self):
        query = [1.0, 0.0]
        vectors = [_unit(0.9), _unit(0.8), _unit(0.7), _unit(0.3), _unit(0.1)]
        score = skill_matcher._score_skill(query, vectors, 3)
        self.assertAlmostEqual((0.9 + 0.8 + 0.7) / 3, score, places=6)

    def test_score_skill_empty_vectors(self):
        self.assertEqual(0.0, skill_matcher._score_skill([1.0, 0.0], [], 3))


class ThresholdGateTest(_MatcherCase):

    def test_auto_apply_when_high_and_unambiguous(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))
        self._add_skill("skill-b", "技能乙", "乙类分析方法",
                        ["乙问题一", "乙问题二", "乙问题三"], _unit(0.50))
        result = self._ask("用户提问")
        self.assertEqual("skill-a", result.auto_id)
        self.assertIn("技能甲", result.reason)
        self.assertIn("skill-a", [c["id"] for c in result.candidates])

    def test_ambiguous_top_two_not_auto_applied(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))
        self._add_skill("skill-b", "技能乙", "乙类分析方法",
                        ["乙问题一", "乙问题二", "乙问题三"], _unit(0.88))
        result = self._ask("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("歧义", result.reason)

    def test_between_low_and_high_returns_candidates_only(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.60))
        result = self._ask("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("未达自动套用阈值", result.reason)
        self.assertTrue(result.candidates)

    def test_below_low_skips_skill(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.30))
        result = self._ask("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("低于候选阈值", result.reason)

    def test_candidates_sorted_and_limited(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.70))
        self._add_skill("skill-b", "技能乙", "乙类分析方法",
                        ["乙问题一", "乙问题二", "乙问题三"], _unit(0.60))
        result = self._ask("用户提问")
        scores = [c["score"] for c in result.candidates]
        self.assertEqual(sorted(scores, reverse=True), scores)
        self.assertLessEqual(len(result.candidates), 3)


class DegradeTest(_MatcherCase):

    def test_empty_skill_dir(self):
        result = skill_matcher.match("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("技能目录为空", result.reason)

    def test_vector_service_unavailable(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))
        skill_matcher.embed_texts = lambda texts, timeout=0: None
        result = skill_matcher.match("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("向量服务不可用", result.reason)

    def test_vector_service_raises(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))

        def boom(texts, timeout=0):
            raise RuntimeError("模拟向量服务异常")

        skill_matcher.embed_texts = boom
        result = skill_matcher.match("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("向量服务异常", result.reason)

    def test_match_disabled(self):
        config.IPAGE_SKILL_MATCH_ENABLED = False
        result = skill_matcher.match("用户提问")
        self.assertEqual("", result.auto_id)
        self.assertIn("技能匹配已关闭", result.reason)

    def test_empty_query(self):
        result = skill_matcher.match("   ")
        self.assertEqual("", result.auto_id)
        self.assertIn("问题为空", result.reason)


class VectorCacheTest(_MatcherCase):

    def test_corpus_vectors_computed_once(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))
        self._ask("用户提问")
        first = self.embed.calls  # 语料一次 + query 一次
        self._ask("用户提问")
        self.assertEqual(first + 1, self.embed.calls)  # 第二次只编码 query

    def test_skill_change_invalidates_corpus_cache(self):
        self._add_skill("skill-a", "技能甲", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))
        self._ask("用户提问")
        calls_before = self.embed.calls
        # 改动技能内容 → 指纹变化 → 必须重新编码语料
        self._add_skill("skill-a", "技能甲改", "甲类分析方法",
                        ["甲问题一", "甲问题二", "甲问题三"], _unit(0.90))
        self._ask("用户提问")
        self.assertGreater(self.embed.calls, calls_before + 1)

    def test_registered_in_cache_registry(self):
        import cache_registry
        self.assertIn(skill_matcher.MATCHER_CACHE_NAME, cache_registry.registered_caches())


if __name__ == "__main__":
    unittest.main()
