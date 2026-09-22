"""实体过滤（Value Linking）注解优先测试。

覆盖两点：
1. 字段级 ``values``/``synonyms`` 注解直接决定匹配词典，SQL 过滤使用**原始值**；
2. 无注解时行为与历史口径一致（不加过滤 / 回落 businessMeaning 解析）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import entity_filter
from agent.dimension_graph import DimensionGraph, TableSpec


def _graph(columns: dict, table: str = "flight_log") -> DimensionGraph:
    """构造单表维度图；columns 形如 {列名: (类型, 业务含义, 字段语义)}。"""
    graph = DimensionGraph("db_test")
    spec = TableSpec(table=table, dataset_id="ds_1")
    for name, triple in columns.items():
        ctype, meaning, col_semantic = (list(triple) + [None, None, None])[:3]
        spec.columns[name] = {
            "type": ctype or "varchar",
            "meaning": meaning or "",
            "pk": False,
            "semantic": col_semantic or {},
        }
    graph.tables[table] = spec
    return graph


class AnnotatedVocabularyTest(unittest.TestCase):

    def _annotated_graph(self) -> DimensionGraph:
        # 列名/业务含义都不含结构信号，仅靠 values/synonyms 注解成为维度列
        return _graph({"\u5f52\u5c5e": ("varchar", "", {
            "role": "dimension",
            "values": {"\u672c\u65b9": "blue", "\u5bf9\u65b9": "red"},
            "synonyms": {"\u6211\u519b": "blue"},
        })})

    def test_dimension_column_comes_from_annotation(self):
        graph = self._annotated_graph()
        cols = [dc.column for dc in graph.dimension_columns()]
        self.assertEqual(cols, ["\u5f52\u5c5e"])

    def test_query_term_maps_to_raw_value(self):
        graph = self._annotated_graph()
        scope, hits = entity_filter.resolve_scope("\u5217\u51fa\u672c\u65b9\u53c2\u4e0e\u7684\u8bb0\u5f55",
                                                  graph, ["flight_log"])
        # SQL 过滤必须用原始值"本方"，而不是规范值 blue
        self.assertEqual(scope, {"flight_log": {"\u5f52\u5c5e": {"\u672c\u65b9"}}})
        self.assertTrue(hits)

    def test_synonym_maps_to_same_raw_value(self):
        graph = self._annotated_graph()
        scope, _ = entity_filter.resolve_scope("\u6211\u519b\u7684\u8f68\u8ff9\u660e\u7ec6",
                                               graph, ["flight_log"])
        self.assertEqual(scope, {"flight_log": {"\u5f52\u5c5e": {"\u672c\u65b9"}}})

    def test_canonical_value_also_matchable(self):
        graph = self._annotated_graph()
        scope, _ = entity_filter.resolve_scope("blue \u7684\u8bb0\u5f55", graph, ["flight_log"])
        self.assertEqual(scope, {"flight_log": {"\u5f52\u5c5e": {"\u672c\u65b9"}}})

    def test_no_annotation_no_filter(self):
        """无注解、无结构信号 → 不产生任何过滤（零误伤，与历史一致）。"""
        graph = _graph({"\u5f52\u5c5e": ("varchar", "", None)})
        scope, hits = entity_filter.resolve_scope("\u5217\u51fa\u672c\u65b9\u7684\u5168\u90e8\u8bb0\u5f55",
                                                 graph, ["flight_log"])
        self.assertEqual(scope, {})
        self.assertEqual(hits, [])

    def test_business_meaning_fallback_still_works(self):
        """未加结构化注解时，历史 businessMeaning 枚举解析照常生效。"""
        graph = _graph({"faction": ("varchar", "\u9635\u8425\uff08\u84dd\u65b9/\u7ea2\u65b9\uff09", None)})
        standards, aliases = entity_filter._build_column_vocabulary(
            graph, graph.dimension_columns()[0])
        self.assertEqual(standards, {"\u84dd\u65b9", "\u7ea2\u65b9"})
        self.assertEqual(aliases, {})


if __name__ == "__main__":
    unittest.main()
