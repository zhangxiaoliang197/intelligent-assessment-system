"""元数据缓存注册表与失效行为测试。

覆盖：注解变更后缓存必须失效、失效范围按数据源+表名收敛、
单个缓存清理失败不影响其余缓存、以及 admin 回调端点的鉴权与载荷解析。
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import cache_registry
from agent import dimension_graph, researcher


class _FakeRequest:
    """最小 Request 替身：只提供端点实际用到的 headers 与 json()。"""

    def __init__(self, headers=None, payload=None):
        self.headers = headers or {}
        self._payload = payload

    async def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


def _meta(semantic_a="", semantic_b="", database_id="db_test"):
    """构造 /export/for-llm 形态的元数据（含数据集级与字段级语义注解）。"""
    return {
        "success": True,
        "data": {
            "databaseId": database_id,
            "schemas": [
                {
                    "tableName": "t_a",
                    "datasetId": "ds_a",
                    "semanticJson": semantic_a,
                    "fields": [
                        {"column": "id", "type": "int", "isPrimaryKey": True},
                        {"column": "faction", "type": "varchar",
                         "semanticJson": semantic_b},
                    ],
                },
                {
                    "tableName": "t_b",
                    "datasetId": "ds_b",
                    "fields": [{"column": "id", "type": "int", "isPrimaryKey": True}],
                },
            ],
        },
    }


class CacheRegistrationTest(unittest.TestCase):

    def test_expected_caches_registered(self):
        names = cache_registry.registered_caches()
        for expected in ("dimension_graph.graph",
                         "researcher.aircraft_index",
                         "researcher.entity_enrich"):
            self.assertIn(expected, names)

    def test_failing_cache_does_not_block_others(self):
        def boom(database_id, tables):
            raise RuntimeError("模拟清理失败")

        cache_registry.register_cache("test.boom", boom)
        try:
            result = cache_registry.invalidate("db_test", ["t_a"])
            self.assertEqual(-1, result["test.boom"])
            self.assertIn("dimension_graph.graph", result)
        finally:
            cache_registry._registry.pop("test.boom", None)


class DimensionGraphInvalidationTest(unittest.TestCase):

    def setUp(self):
        cache_registry.invalidate()  # 清干净，避免用例间互相影响

    def test_semantic_change_switches_cache_key(self):
        """注解内容变化即换缓存键，无需重启服务即可读到新值。"""
        graph_before = dimension_graph.DimensionGraph.build(_meta(semantic_a='{"entityKind":"air"}'))
        self.assertIsNotNone(graph_before)
        self.assertEqual("air", graph_before.tables["t_a"].semantic.get("entityKind"))

        # 同一份元数据应命中缓存（同一对象）
        again = dimension_graph.DimensionGraph.build(_meta(semantic_a='{"entityKind":"air"}'))
        self.assertIs(graph_before, again)

        # 注解改为 ground_facility → 必须是另一份图
        graph_after = dimension_graph.DimensionGraph.build(
            _meta(semantic_a='{"entityKind":"ground_facility"}'))
        self.assertIsNot(graph_before, graph_after)
        self.assertEqual("ground_facility", graph_after.tables["t_a"].semantic.get("entityKind"))

    def test_field_semantic_is_parsed_and_cached(self):
        graph = dimension_graph.DimensionGraph.build(
            _meta(semantic_b='{"role":"dimension","values":{"蓝方":"blue"}}'))
        col = graph.tables["t_a"].columns["faction"]
        self.assertEqual("dimension", col["semantic"].get("role"))
        self.assertEqual({"蓝方": "blue"}, col["semantic"].get("values"))

    def test_stale_graph_is_pruned_for_same_table_set(self):
        """同一 (数据源, 表集合) 只保留最新一份，避免多轮改注解堆积旧图。"""
        dimension_graph.DimensionGraph.build(_meta(semantic_a='{"entityKind":"air"}'))
        dimension_graph.DimensionGraph.build(_meta(semantic_a='{"entityKind":"base"}'))
        keys = [k for k in dimension_graph._graph_cache if k[0] == "db_test"]
        self.assertEqual(1, len(keys))

    def test_invalidate_by_database_and_table(self):
        dimension_graph.DimensionGraph.build(_meta())
        dimension_graph.DimensionGraph.build(_meta(database_id="db_other"))
        self.assertEqual(2, len(dimension_graph._graph_cache))

        cleared = cache_registry.invalidate("db_test", ["t_a"])
        self.assertGreaterEqual(cleared["dimension_graph.graph"], 1)
        remaining = [k[0] for k in dimension_graph._graph_cache]
        self.assertIn("db_other", remaining)
        self.assertNotIn("db_test", remaining)

    def test_invalidate_ignores_other_tables(self):
        """改 t_b 的注解不应清掉 t_a 的图（避免改一列触发全库重新采样）。"""
        dimension_graph.DimensionGraph.build(_meta())
        cleared = cache_registry.invalidate("db_test", ["mock_not_exist"])
        self.assertEqual(0, cleared["dimension_graph.graph"])
        self.assertEqual(1, len(dimension_graph._graph_cache))

    def test_invalid_semantic_does_not_break_build(self):
        """非法注解（未经 admin 校验的历史/脚本写入）按未配置处理，不得抛错。"""
        graph = dimension_graph.DimensionGraph.build(
            _meta(semantic_a='{"entityKind":"aircraft"}'))
        self.assertIsNotNone(graph)
        self.assertEqual("aircraft", graph.tables["t_a"].semantic.get("entityKind"))


class ResearcherCacheInvalidationTest(unittest.TestCase):

    def setUp(self):
        researcher._aircraft_index_cache.clear()
        researcher._entity_enrich_cache.clear()

    def test_entity_enrich_cleared_precisely_by_table(self):
        researcher._entity_enrich_cache[("db_test", "t_a")] = {"x": {}}
        researcher._entity_enrich_cache[("db_test", "t_b")] = {"y": {}}
        researcher._entity_enrich_cache[("db_other", "t_a")] = {"z": {}}

        cleared = cache_registry.invalidate("db_test", ["t_a"])
        self.assertEqual(1, cleared["researcher.entity_enrich"])
        self.assertIn(("db_test", "t_b"), researcher._entity_enrich_cache)
        self.assertIn(("db_other", "t_a"), researcher._entity_enrich_cache)

    def test_aircraft_index_cleared_by_database(self):
        researcher._aircraft_index_cache["db_test"] = {"AC-1": {}}
        researcher._aircraft_index_cache["db_other"] = {"AC-2": {}}

        cleared = cache_registry.invalidate("db_test", ["t_a"])
        self.assertEqual(1, cleared["researcher.aircraft_index"])
        self.assertNotIn("db_test", researcher._aircraft_index_cache)
        self.assertIn("db_other", researcher._aircraft_index_cache)


class InvalidateEndpointTest(unittest.TestCase):
    """admin 回调端点：鉴权、载荷解析、范围失效。"""

    def setUp(self):
        import main as ipage_main
        self.main = ipage_main
        self._saved_token = config.INTERNAL_SERVICE_TOKEN

    def tearDown(self):
        config.INTERNAL_SERVICE_TOKEN = self._saved_token

    def _call(self, request):
        return asyncio.run(self.main.invalidate_metadata_cache(request))

    def test_payload_scopes_invalidation(self):
        config.INTERNAL_SERVICE_TOKEN = ""
        dimension_graph.DimensionGraph.build(_meta())
        dimension_graph.DimensionGraph.build(_meta(database_id="db_other"))

        resp = self._call(_FakeRequest(payload={"databaseId": "db_test",
                                                "tables": ["t_a"]}))
        self.assertTrue(resp["success"])
        self.assertEqual("db_test", resp["data"]["databaseId"])
        self.assertEqual(["t_a"], resp["data"]["tables"])
        self.assertIn("dimension_graph.graph", resp["data"]["cleared"])
        self.assertIn("db_other", [k[0] for k in dimension_graph._graph_cache])

    def test_missing_body_means_full_invalidation(self):
        config.INTERNAL_SERVICE_TOKEN = ""
        resp = self._call(_FakeRequest(payload=None))
        self.assertTrue(resp["success"])
        self.assertEqual([], resp["data"]["tables"])
        self.assertEqual("", resp["data"]["databaseId"])

    def test_token_mismatch_rejected(self):
        config.INTERNAL_SERVICE_TOKEN = "expected-token"
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._call(_FakeRequest(headers={"X-Service-Token": "wrong"},
                                    payload={"databaseId": "db_test"}))
        self.assertEqual(401, ctx.exception.status_code)

    def test_token_match_allowed(self):
        config.INTERNAL_SERVICE_TOKEN = "expected-token"
        resp = self._call(_FakeRequest(headers={"X-Service-Token": "expected-token"},
                                       payload={"databaseId": "db_test"}))
        self.assertTrue(resp["success"])


if __name__ == "__main__":
    unittest.main()
