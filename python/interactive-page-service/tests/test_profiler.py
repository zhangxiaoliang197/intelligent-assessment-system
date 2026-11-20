"""能力画像（profiler）测试：静态识别、统计增强、投影坐标与缓存。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import profiler


def _schema(**overrides):
    """构造一张军事通用表的数据集元数据。"""
    schema = {
        "datasetId": "ds_equip",
        "datasetName": "车辆状态",
        "tableName": "vehicle_status",
        "fields": [
            {"column": "vehicle_id", "type": "VARCHAR(32)", "isPrimaryKey": True,
             "comment": "车辆编号"},
            {"column": "vehicle_name", "type": "VARCHAR(64)", "comment": "名称"},
            {"column": "category", "type": "VARCHAR(32)", "comment": "类别"},
            {"column": "side", "type": "VARCHAR(16)", "comment": "归属"},
            {"column": "lng", "type": "DECIMAL(10,6)", "comment": "经度"},
            {"column": "lat", "type": "DECIMAL(10,6)", "comment": "纬度"},
            {"column": "report_time", "type": "DATETIME", "comment": "上报时间"},
            {"column": "health", "type": "VARCHAR(16)", "comment": "健康状态"},
            {"column": "speed_kmh", "type": "DECIMAL(8,2)", "comment": "速度"},
        ],
    }
    schema.update(overrides)
    return schema


def _meta(schema):
    return {"success": True, "data": {"dbType": "mysql", "schemas": [schema]}}


def _stats_payload(lng_min="-120", lng_max="130", lat_min="18", lat_max="54", rows=100):
    """构造一条聚合统计结果（列顺序与 _stat_columns 一致）。"""
    columns = ["vehicle_id", "vehicle_name", "category", "side", "lng", "lat",
               "report_time", "health", "speed_kmh"]
    row = {"r0": rows}
    for idx, col in enumerate(columns):
        row[f"c{idx}_n"] = rows
        row[f"c{idx}_d"] = rows if col in ("vehicle_id", "vehicle_name") else 3
        row[f"c{idx}_min"] = lng_min if col == "lng" else (lat_min if col == "lat" else "2026-11-01")
        row[f"c{idx}_max"] = lng_max if col == "lng" else (lat_max if col == "lat" else "2026-11-07")
    return {"success": True, "columns": list(row.keys()), "rows": [row]}


def _enum_payload(values):
    return {"success": True, "columns": ["v", "n"],
            "rows": [{"v": v, "n": 10} for v in values]}


class StaticProfileTest(unittest.TestCase):
    def setUp(self):
        profiler.clear_cache()
        # 测试不访问真实 admin：数据源类型探测直接失败，回退全局方言
        patcher = mock.patch.object(profiler.admin_client, "query_databases",
                                    return_value={"success": False})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_chinese_and_english_columns(self):
        """中英文列名/注释都能识别坐标、时间、归属、状态、类别、度量。"""
        profile = profiler.build_profiles(_meta(_schema()))["byId"]["ds_equip"]
        cap = profile["capabilities"]
        self.assertEqual((cap["geo"]["lng"], cap["geo"]["lat"]), ("lng", "lat"))
        self.assertEqual(cap["time"]["column"], "report_time")
        self.assertIn("side", cap["affiliation"])
        self.assertIn("health", cap["status"])
        self.assertIn("category", cap["category"])
        self.assertIn("speed_kmh", cap["measures"])
        self.assertEqual(cap["entity"]["key"], "vehicle_id")
        self.assertEqual(cap["entity"]["kind"], "platform_ground")

    def test_annotation_wins(self):
        """注解声明的坐标/时间优先于列名推断。"""
        schema = _schema(
            semanticJson='{"entityKind":"facility","geometry":{"lngColumn":"lng","latColumn":"lat"},'
                         '"eventTimeColumn":"report_time"}')
        profile = profiler.build_profiles(_meta(schema))["byId"]["ds_equip"]
        cap = profile["capabilities"]
        self.assertEqual(cap["geo"]["source"], "annotation")
        self.assertEqual(cap["entity"]["kind"], "facility")

    def test_summarize_contains_capabilities(self):
        profile = profiler.build_profiles(_meta(_schema()))["byId"]["ds_equip"]
        text = profiler.summarize(profile)
        self.assertIn("坐标(lng/lat)", text)
        self.assertIn("时间(report_time)", text)
        self.assertIn("归属(side)", text)
        self.assertIn("状态(health)", text)

    def test_cache_reuse(self):
        """同一结构重复构建应命中缓存，不重复统计。"""
        with mock.patch.object(profiler.admin_client, "execute_dataset_sql",
                               return_value=_stats_payload()) as call:
            profiler.build_profiles(_meta(_schema()), use_stats=True)
            first = call.call_count
            profiler.build_profiles(_meta(_schema()), use_stats=True)
        self.assertGreaterEqual(first, 1)
        self.assertEqual(call.call_count, first)


class StatsProfileTest(unittest.TestCase):
    def setUp(self):
        profiler.clear_cache()
        patcher = mock.patch.object(profiler.admin_client, "query_databases",
                                    return_value={"success": False})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stats_enrich_values_and_unique(self):
        """统计增强补齐行数、枚举值、唯一性。"""
        with mock.patch.object(profiler.admin_client, "execute_dataset_sql",
                               side_effect=[_stats_payload(),
                                            _enum_payload(["我方", "敌方"]),
                                            _enum_payload(["正常", "故障"])]):
            profile = profiler.build_profiles(_meta(_schema()), use_stats=True)["byId"]["ds_equip"]
        self.assertTrue(profile["stats"])
        self.assertEqual(profile["rowCount"], 100)
        cols = profile["columns"]
        self.assertTrue(cols["vehicle_id"]["unique"])
        self.assertEqual(cols["side"]["values"], ["我方", "敌方"])
        self.assertEqual(cols["health"]["values"], ["正常", "故障"])

    def test_projected_coordinates_not_geo_capable(self):
        """值域超出经纬度范围的坐标按投影坐标处理，不参与地图。"""
        payload = _stats_payload(lng_min="500000", lng_max="600000",
                                 lat_min="3000000", lat_max="3100000")
        with mock.patch.object(profiler.admin_client, "execute_dataset_sql",
                               side_effect=[payload, _enum_payload(["我方"]),
                                            _enum_payload(["正常"])]):
            profile = profiler.build_profiles(_meta(_schema()), use_stats=True)["byId"]["ds_equip"]
        self.assertEqual(profile["capabilities"]["geo"]["coordType"], "projected")
        self.assertTrue(any("投影坐标" in w for w in profile["warnings"]))

    def test_stats_failure_degrades(self):
        """统计 SQL 异常时只告警，静态画像仍然可用。"""
        with mock.patch.object(profiler.admin_client, "execute_dataset_sql",
                               side_effect=RuntimeError("db down")):
            profile = profiler.build_profiles(_meta(_schema()), use_stats=True)["byId"]["ds_equip"]
        self.assertFalse(profile["stats"])
        self.assertEqual(profile["capabilities"]["time"]["column"], "report_time")
        self.assertTrue(profile["warnings"])


class PlannerIntegrationTest(unittest.TestCase):
    def setUp(self):
        profiler.clear_cache()

    def test_geo_capable_uses_profile(self):
        """Planner 的坐标能力判定能读到画像结果。"""
        from agent import planner
        meta = _meta(_schema())
        profiler.ensure_profiles(meta)
        self.assertIn("ds_equip", planner._geo_capable_ids(meta))
        self.assertIn("ds_equip", planner._time_capable_ids(meta))


if __name__ == "__main__":
    unittest.main()
