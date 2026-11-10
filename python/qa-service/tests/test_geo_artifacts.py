"""评估分析空间分布产物单元测试。"""
import os
import sys
import unittest
from unittest.mock import patch

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from agents.geo_artifacts import (  # noqa: E402
    MAX_GEO_COLUMNS,
    GeoTable,
    build_geo_features,
    build_geo_sql,
    choose_geo_table,
    collect_geo_artifact,
    inspect_dataset,
    result_has_geo_rows,
)


def _column(name, data_type="VARCHAR", **extra):
    """构造一列元数据。"""
    item = {"columnName": name, "dataType": data_type}
    item.update(extra)
    return item


def _dataset(table_name, name, columns, **extra):
    """构造数据集元数据。"""
    item = {
        "tableName": table_name,
        "name": name,
        "description": f"{name}描述",
        "columns": columns,
    }
    item.update(extra)
    return item


class InspectDatasetTests(unittest.TestCase):
    def test_longitude_latitude_table_is_points(self):
        geo = inspect_dataset(_dataset(
            "t_air_overall",
            "制空能力综合",
            [
                _column("unit_id", "VARCHAR", isPrimaryKey=True),
                _column("side_name"),
                _column("longitude", "DECIMAL"),
                _column("latitude", "DECIMAL"),
            ],
        ))
        self.assertIsNotNone(geo)
        self.assertEqual(geo.kind, "points")
        self.assertEqual(geo.lng_column, "longitude")
        self.assertEqual(geo.lat_column, "latitude")
        self.assertEqual(geo.name_column, "")

    def test_track_table_is_routes(self):
        geo = inspect_dataset(_dataset(
            "mock_track_point",
            "我方航迹点",
            [
                _column("aircraft_id"),
                _column("aircraft_name"),
                _column("seq", "INT"),
                _column("track_lng", "DECIMAL"),
                _column("track_lat", "DECIMAL"),
                _column("altitude_m", "INT"),
            ],
        ))
        self.assertIsNotNone(geo)
        self.assertEqual(geo.kind, "routes")
        self.assertEqual(geo.seq_column, "seq")
        self.assertEqual(geo.entity_column, "aircraft_id")
        self.assertEqual(geo.name_column, "aircraft_name")

    def test_threat_table_is_areas(self):
        geo = inspect_dataset(_dataset(
            "mock_enemy_threat",
            "敌方威胁单元",
            [
                _column("threat_name"),
                _column("lng", "DECIMAL"),
                _column("lat", "DECIMAL"),
                _column("detect_radius_km", "INT"),
                _column("strike_radius_km", "INT"),
            ],
        ))
        self.assertIsNotNone(geo)
        self.assertEqual(geo.kind, "areas")
        self.assertEqual(geo.radius_columns, ["detect_radius_km", "strike_radius_km"])

    def test_prefers_same_prefix_coordinate_pair(self):
        geo = inspect_dataset(_dataset(
            "mixed_table",
            "混合坐标",
            [
                _column("home_lng", "DECIMAL"),
                _column("home_lat", "DECIMAL"),
                _column("event_lng", "DECIMAL"),
                _column("event_lat", "DECIMAL"),
            ],
        ))
        self.assertIsNotNone(geo)
        self.assertEqual(geo.lng_column, "home_lng")
        self.assertEqual(geo.lat_column, "home_lat")

    def test_without_coordinate_pair_returns_none(self):
        geo = inspect_dataset(_dataset(
            "t_air_capability",
            "制空能力明细",
            [_column("side_name"), _column("score", "DECIMAL")],
        ))
        self.assertIsNone(geo)

    def test_unsafe_table_name_is_rejected(self):
        geo = inspect_dataset({
            "tableName": "t_air_overall; DROP TABLE x",
            "name": "危险表",
            "columns": [_column("longitude", "DECIMAL"), _column("latitude", "DECIMAL")],
        })
        self.assertIsNone(geo)

    def test_column_count_is_capped(self):
        columns = [_column("longitude", "DECIMAL"), _column("latitude", "DECIMAL")]
        columns.extend(_column(f"field_{index}", "INT") for index in range(30))
        geo = inspect_dataset(_dataset("wide_table", "宽表", columns))
        self.assertIsNotNone(geo)
        self.assertLessEqual(len(geo.columns), MAX_GEO_COLUMNS)


class GeoFeaturesTests(unittest.TestCase):
    def _geo_table(self, kind, **columns):
        base = {
            "table_name": "t_demo",
            "dataset_name": "演示表",
            "description": "",
            "lng_column": "lng",
            "lat_column": "lat",
            "kind": kind,
        }
        base.update(columns)
        return GeoTable(**base)

    def test_markers(self):
        table = self._geo_table("points", name_column="name", columns=["name", "lng", "lat"])
        features = build_geo_features(table, [
            {"name": "目标A", "lng": 116.3, "lat": 30.5, "status": "完好"},
            {"name": "目标B", "lng": 0, "lat": 0},
        ])
        self.assertEqual(len(features["markers"]), 2)
        self.assertEqual(features["markers"][0]["props"], {"status": "完好"})

    def test_routes_grouped_and_sorted(self):
        table = self._geo_table(
            "routes",
            name_column="aircraft_name",
            seq_column="seq",
            entity_column="aircraft_id",
            columns=["aircraft_id", "aircraft_name", "seq", "lng", "lat"],
        )
        features = build_geo_features(table, [
            {"aircraft_id": "A1", "aircraft_name": "一号机", "seq": 2, "lng": 116.4, "lat": 30.6},
            {"aircraft_id": "A1", "aircraft_name": "一号机", "seq": 1, "lng": 116.3, "lat": 30.5},
            {"aircraft_id": "A2", "aircraft_name": "二号机", "seq": 1, "lng": 117.0, "lat": 31.0},
        ])
        self.assertEqual(len(features["routes"]), 1)
        self.assertEqual(features["routes"][0]["name"], "A1")
        self.assertEqual(features["routes"][0]["points"][0], {"lng": 116.3, "lat": 30.5})

    def test_areas_support_detect_and_strike_radius(self):
        table = self._geo_table(
            "areas",
            name_column="threat_name",
            radius_columns=["detect_radius_km", "strike_radius_km"],
            columns=["threat_name", "lng", "lat", "detect_radius_km", "strike_radius_km"],
        )
        features = build_geo_features(table, [{
            "threat_name": "阵地A",
            "lng": 116.3,
            "lat": 30.5,
            "detect_radius_km": 120,
            "strike_radius_km": 60,
        }])
        self.assertEqual(len(features["areas"]), 2)
        self.assertEqual(features["areas"][0]["name"], "阵地A·探测范围")
        self.assertEqual(features["areas"][1]["radiusKm"], 60)

    def test_invalid_coordinates_are_filtered(self):
        table = self._geo_table("points", name_column="name", columns=["name", "lng", "lat"])
        features = build_geo_features(table, [
            {"name": "异常点", "lng": 999, "lat": 30},
            {"name": "正常点", "lng": 116.3, "lat": 30.5},
        ])
        self.assertEqual(len(features["markers"]), 1)
        self.assertEqual(features["markers"][0]["name"], "正常点")


class GeoSelectTests(unittest.TestCase):
    def _table(self, table_name, kind="points", text=""):
        return GeoTable(
            table_name=table_name,
            dataset_name=table_name,
            description="",
            lng_column="lng",
            lat_column="lat",
            kind=kind,
            columns=["lng", "lat"],
            text_for_score=text,
        )

    def test_used_table_has_priority(self):
        used = self._table("t_used", "points", "制空能力")
        better = self._table("t_other", "routes", "制空能力航迹")
        chosen = choose_geo_table([used, better], ["t_used"], "对比制空能力")
        self.assertEqual(chosen.table_name, "t_used")

    def test_semantic_match_when_no_used_table(self):
        points = self._table("t_points", "points", "兵力部署 单位")
        tracks = self._table("t_tracks", "routes", "飞行航迹 飞机")
        chosen = choose_geo_table([points, tracks], ["t_unrelated"], "分析飞机航迹")
        self.assertEqual(chosen.table_name, "t_tracks")

    def test_single_geo_table_is_fallback(self):
        only = self._table("t_only", "points", "无关描述")
        chosen = choose_geo_table([only], [], "完全无关的问题")
        self.assertEqual(chosen.table_name, "t_only")

    def test_multiple_unmatched_tables_are_skipped(self):
        first = self._table("t_a", "points", "完全无关甲")
        second = self._table("t_b", "points", "完全无关乙")
        self.assertIsNone(choose_geo_table([first, second], [], "天气怎么样"))


class GeoSqlTests(unittest.TestCase):
    def _table(self):
        return GeoTable(
            table_name="t_demo",
            dataset_name="演示",
            description="",
            lng_column="lng",
            lat_column="lat",
            seq_column="seq",
            columns=["name", "seq", "lng", "lat"],
        )

    def test_mysql_limit(self):
        sql = build_geo_sql(self._table(), "mysql", 200)
        self.assertIn("LIMIT 200", sql)
        self.assertIn("lng IS NOT NULL AND lat IS NOT NULL", sql)
        self.assertIn("ORDER BY seq", sql)

    def test_oracle_fetch_first(self):
        sql = build_geo_sql(self._table(), "oracle", 200)
        self.assertIn("FETCH FIRST 200 ROWS ONLY", sql)
        self.assertNotIn("LIMIT", sql)

    def test_sqlserver_top(self):
        sql = build_geo_sql(self._table(), "sqlserver", 200)
        self.assertTrue(sql.startswith("SELECT TOP 200"))


class CollectGeoArtifactTests(unittest.TestCase):
    def _dataset(self):
        return _dataset(
            "t_air_overall",
            "制空能力综合",
            [
                _column("unit_id", "VARCHAR", isPrimaryKey=True),
                _column("side_name"),
                _column("longitude", "DECIMAL"),
                _column("latitude", "DECIMAL"),
                _column("overall_score", "DECIMAL"),
            ],
            databaseType="MySQL",
        )

    def test_skips_when_result_already_has_geo_rows(self):
        result = {
            "type": "data_query",
            "rawResults": [{"longitude": 116.3, "latitude": 30.5}],
        }
        self.assertTrue(result_has_geo_rows(result))
        with patch("agents.geo_artifacts.fetch_skill_datasets_for_database") as fetch:
            self.assertIsNone(collect_geo_artifact("db1", "问题", result))
            fetch.assert_not_called()

    def test_builds_artifact_from_coordinate_query(self):
        result = {
            "type": "data_query",
            "generatedSql": "SELECT side_name, AVG(score) FROM t_air_capability GROUP BY side_name",
            "rawResults": [{"side_name": "红方", "avg_score": 88}],
        }
        with patch(
            "agents.geo_artifacts.fetch_skill_datasets_for_database",
            return_value=[self._dataset()],
        ), patch(
            "agents.geo_artifacts.execute_sql_on_database",
            return_value={
                "success": True,
                "columns": ["unit_id", "side_name", "longitude", "latitude", "overall_score"],
                "rows": [
                    {"unit_id": "U-101", "side_name": "红方", "longitude": 116.3, "latitude": 30.5, "overall_score": 88},
                    {"unit_id": "U-102", "side_name": "蓝方", "longitude": 117.1, "latitude": 31.2, "overall_score": 70},
                ],
            },
        ) as execute:
            artifact = collect_geo_artifact("db1", "对比红蓝双方制空能力", result)
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["artifactId"], "geo1")
        self.assertEqual(artifact["mode"], "detail")
        self.assertEqual(len(artifact["geo"]["markers"]), 2)
        self.assertEqual(artifact["geo"]["markers"][0]["name"], "U-101")
        self.assertIn("制空能力综合", artifact["name"])
        execute.assert_called_once()

    def test_degrades_when_query_fails(self):
        result = {
            "type": "data_query",
            "generatedSql": "SELECT * FROM t_air_overall",
            "rawResults": [{"side_name": "红方"}],
        }
        with patch(
            "agents.geo_artifacts.fetch_skill_datasets_for_database",
            return_value=[self._dataset()],
        ), patch(
            "agents.geo_artifacts.execute_sql_on_database",
            side_effect=RuntimeError("数据库不可用"),
        ):
            self.assertIsNone(collect_geo_artifact("db1", "制空能力", result))

    def test_degrades_when_no_coordinate_table(self):
        result = {"type": "skill", "queryResults": []}
        only_text = _dataset(
            "t_air_capability",
            "制空能力明细",
            [_column("side_name"), _column("score", "DECIMAL")],
        )
        with patch(
            "agents.geo_artifacts.fetch_skill_datasets_for_database",
            return_value=[only_text],
        ):
            self.assertIsNone(collect_geo_artifact("db1", "制空能力", result))

    def test_skips_unsupported_result_type(self):
        with patch("agents.geo_artifacts.fetch_skill_datasets_for_database") as fetch:
            self.assertIsNone(collect_geo_artifact(
                "db1", "问题", {"type": "knowledge"}
            ))
            fetch.assert_not_called()

    def test_skips_result_without_data_rows(self):
        with patch("agents.geo_artifacts.fetch_skill_datasets_for_database") as fetch:
            self.assertIsNone(collect_geo_artifact(
                "db1", "什么是制空能力", {"type": "general", "final_answer": "概念解释"}
            ))
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
