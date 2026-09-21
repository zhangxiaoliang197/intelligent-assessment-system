"""Researcher 纯函数测试：脱敏 / 抽稀 / 地理特征整形 / 摘要。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from agent import researcher


class SanitizeTest(unittest.TestCase):
    def test_sensitive_columns_removed(self):
        rows = [{"id": 1, "手机号": "13800000000", "value": 12}]
        cleaned = researcher._sanitize_rows(rows, ["id", "手机号", "value"], set())
        self.assertNotIn("手机号", cleaned[0])
        self.assertIn("value", cleaned[0])

    def test_dataset_marked_sensitive(self):
        rows = [{"id": 1, "secret_col": "x", "n": 2}]
        cleaned = researcher._sanitize_rows(rows, ["id", "secret_col", "n"], {"secret_col"})
        self.assertNotIn("secret_col", cleaned[0])

    def test_long_text_truncated(self):
        long_text = "x" * 500
        rows = [{"id": 1, "memo": long_text}]
        cleaned = researcher._sanitize_rows(rows, ["id", "memo"], set())
        self.assertTrue(cleaned[0]["memo"].endswith("…"))
        self.assertLessEqual(len(cleaned[0]["memo"]), 201)

    def test_datetime_serialized(self):
        import datetime as dt
        rows = [{"id": 1, "ts": dt.datetime(2024, 1, 2, 3, 4, 5)}]
        cleaned = researcher._sanitize_rows(rows, ["id", "ts"], set())
        self.assertTrue(cleaned[0]["ts"].startswith("2024-01-02"))


class CoordDetectTest(unittest.TestCase):
    def test_track_prefix_pair(self):
        pairs = researcher._find_coord_pairs(
            ["id", "aircraft_id", "seq", "track_lng", "track_lat"])
        prefixes = {p[0] for p in pairs}
        self.assertIn("track", prefixes)

    def test_bare_pair(self):
        pairs = researcher._find_coord_pairs(["id", "lng", "lat", "name"])
        self.assertEqual(pairs, [("", "lng", "lat")])

    def test_no_pair(self):
        self.assertEqual(researcher._find_coord_pairs(["id", "name"]), [])


class GeoFeaturesTest(unittest.TestCase):
    def _track_rows(self):
        rows = []
        for ac, order in [("蓝鹰01", [3, 1, 2]), ("红隼02", [1, 2])]:
            for seq in order:
                rows.append({
                    "id": f"{ac}-{seq}",
                    "aircraft_id": ac,
                    "seq": seq,
                    "record_time": f"2024-01-01 0{seq}:00:00",
                    "track_lng": 120.0 + seq * 0.1,
                    "track_lat": 30.0 + seq * 0.1,
                    "faction": "蓝方" if ac.startswith("蓝") else "红方",
                })
        return rows

    def test_tracks_grouped_sorted(self):
        cols = ["id", "aircraft_id", "seq", "record_time", "track_lng", "track_lat", "faction"]
        result = researcher.build_geo_features(self._track_rows(), cols, "tracks")
        self.assertEqual(result["kind"], "tracks")
        self.assertEqual(len(result["tracks"]), 2)
        blue = next(t for t in result["tracks"] if t["name"] == "蓝鹰01")
        seqs = [p["seq"] for p in blue["points"]]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(blue["faction"], "蓝方")
        self.assertIn("lng", blue["points"][0])

    def test_points_with_event_prefix(self):
        cols = ["name", "event_lng", "event_lat", "type"]
        rows = [
            {"name": "事件A", "event_lng": 121.1, "event_lat": 31.1, "type": "target"},
            {"name": "事件B", "event_lng": 122.2, "event_lat": 32.2, "type": "threat"},
        ]
        result = researcher.build_geo_features(rows, cols, "points")
        self.assertEqual(result["kind"], "points")
        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(result["points"][0]["kind"], "target")

    def test_circles(self):
        cols = ["name", "lng", "lat", "radius_km"]
        rows = [{"name": "打击圈", "lng": 120.0, "lat": 30.0, "radius_km": 150}]
        result = researcher.build_geo_features(rows, cols, "circles")
        self.assertEqual(result["kind"], "circles")
        self.assertEqual(result["circles"][0]["radiusKm"], 150)

    def test_hint_tracks_without_id_falls_back_to_points(self):
        cols = ["lng", "lat", "name"]
        rows = [{"lng": 120.0, "lat": 30.0, "name": "目标"}]
        result = researcher.build_geo_features(rows, cols, "tracks")
        self.assertEqual(result["kind"], "points")

    def test_no_coords_returns_none(self):
        result = researcher.build_geo_features([{"id": 1, "name": "x"}], ["id", "name"], "points")
        self.assertEqual(result["kind"], "none")

    # ── 批次一新契约：敌机分组、档案 enrich、任务拆轨、单位语义 ──

    ENEMY_COLS = ["id", "enemy_aircraft_id", "enemy_aircraft_name", "mission_id", "seq",
                  "record_time", "track_lng", "track_lat", "altitude_m", "speed_kmh",
                  "heading_deg", "coverage_overlap_count"]

    def _enemy_rows(self, acid="AC-RD-01", mission="M-001", n=3):
        rows = []
        for seq in range(1, n + 1):
            rows.append({
                "id": f"{acid}-{mission}-{seq}",
                "enemy_aircraft_id": acid,
                "enemy_aircraft_name": f"{acid}呼号",
                "mission_id": mission,
                "seq": seq,
                "record_time": f"2026-07-15 0{seq}:00:00",
                "track_lng": 119.0 + seq * 0.2,
                "track_lat": 25.0 + seq * 0.2,
                "altitude_m": 8000, "speed_kmh": 900, "heading_deg": 120,
                "coverage_overlap_count": 1,
            })
        return rows

    def test_enemy_tracks_enriched_from_aircraft_index(self):
        """敌机航迹按 enemy_aircraft_id 分组，阵营/机型/定值半径来自档案索引。"""
        index = {"AC-RD-01": {"faction": "红方", "category": "重型截击机",
                              "typeId": "RT-01", "strikeRadiusKm": 130, "callsign": "敌机01"}}
        result = researcher.build_geo_features(
            self._enemy_rows(), self.ENEMY_COLS, "tracks",
            table_name="mock_enemy_track_point", aircraft_index=index)
        self.assertEqual(result["kind"], "tracks")
        self.assertEqual(len(result["tracks"]), 1)
        tr = result["tracks"][0]
        self.assertEqual(tr["id"], "AC-RD-01")
        self.assertEqual(tr["faction"], "红方")
        self.assertEqual(tr["category"], "重型截击机")
        self.assertEqual(tr["strikeRadiusKm"], 130)
        self.assertEqual(tr["missionId"], "M-001")
        p = tr["points"][0]
        self.assertEqual(p["time"], "2026-07-15 01:00:00")
        self.assertEqual(p["alt"], 8000)
        self.assertEqual(p["speed"], 900)
        self.assertEqual(p["heading"], 120)

    def test_enemy_track_faction_fallback_without_index(self):
        """档案索引缺失时敌机表按表名兜底蓝方（敌方=蓝方），半径为空由前端默认。"""
        result = researcher.build_geo_features(
            self._enemy_rows(), self.ENEMY_COLS, "tracks",
            table_name="mock_enemy_track_point", aircraft_index={})
        tr = result["tracks"][0]
        self.assertEqual(tr["faction"], "蓝方")
        self.assertIsNone(tr["strikeRadiusKm"])

    def test_tracks_split_by_mission(self):
        """同一飞机不同任务必须拆成两条航迹。"""
        rows = self._enemy_rows(mission="M-001") + self._enemy_rows(mission="M-002")
        result = researcher.build_geo_features(
            rows, self.ENEMY_COLS, "tracks", table_name="mock_enemy_track_point")
        missions = {t["missionId"] for t in result["tracks"]}
        self.assertEqual(missions, {"M-001", "M-002"})

    def test_event_units_semantics(self):
        """事件点带 unitKind/阵营/类型/状态/时间。"""
        cols = ["id", "target_name", "event_time", "event_lng", "event_lat",
                "damage_type", "severity", "faction"]
        rows = [{"id": 1, "target_name": "雷达站A", "event_time": "2026-07-16 10:00:00",
                 "event_lng": 120.1, "event_lat": 24.2, "damage_type": "摧毁",
                 "severity": "严重", "faction": "红方"}]
        result = researcher.build_geo_features(
            rows, cols, "points", table_name="mock_battle_damage")
        u = result["units"][0]
        self.assertEqual(u["unitKind"], "event_damage")
        self.assertEqual(u["faction"], "红方")
        self.assertEqual(u["type"], "摧毁")
        self.assertEqual(u["status"], "严重")
        self.assertEqual(u["time"], "2026-07-16 10:00:00")
        # points 与 units 同构，保持旧消费方兼容
        self.assertEqual(result["points"][0]["name"], "雷达站A")

    def test_base_units_dedup(self):
        """飞机档案表多行同基地聚合成一个基地点。"""
        cols = ["aircraft_id", "callsign", "faction", "aircraft_type_id",
                "base_name", "home_lng", "home_lat", "status"]
        rows = [
            {"aircraft_id": "AC-BL-01", "callsign": "蓝鹰01", "faction": "蓝方",
             "aircraft_type_id": "BT-01", "base_name": "福州基地",
             "home_lng": 119.3, "home_lat": 26.0, "status": "在役"},
            {"aircraft_id": "AC-BL-02", "callsign": "蓝鹰02", "faction": "蓝方",
             "aircraft_type_id": "BT-01", "base_name": "福州基地",
             "home_lng": 119.3, "home_lat": 26.0, "status": "在役"},
        ]
        result = researcher.build_geo_features(
            rows, cols, "points", table_name="mock_aircraft")
        self.assertEqual(len(result["units"]), 1)
        u = result["units"][0]
        self.assertEqual(u["unitKind"], "base")
        self.assertEqual(u["name"], "福州基地")
        self.assertEqual(u["faction"], "蓝方")

    def test_unknown_unit_kind_other_fallback(self):
        """未识别表/类型用 other（前端圆点兜底）。"""
        cols = ["id", "lng", "lat", "name"]
        result = researcher.build_geo_features(
            [{"id": 1, "lng": 120.0, "lat": 30.0, "name": "未知单位"}],
            cols, "points", table_name="some_new_table")
        self.assertEqual(result["units"][0]["unitKind"], "other")

    def test_circles_carry_faction_and_range_type(self):
        cols = ["name", "faction", "range_type", "lng", "lat", "radius_km"]
        rows = [{"name": "蓝方雷达", "faction": "蓝方", "range_type": "侦察范围",
                 "lng": 120.0, "lat": 30.0, "radius_km": 200}]
        result = researcher.build_geo_features(rows, cols, "circles")
        c = result["circles"][0]
        self.assertEqual(c["faction"], "蓝方")
        self.assertEqual(c["rangeType"], "侦察范围")
        self.assertEqual(c["kind"], "recon")

    def test_circles_multi_radius_pairs_radius_with_kind(self):
        """一表多半径：探测/打击各自成圈，半径与类型必须配对（不得错配）。"""
        cols = ["threat_id", "threat_name", "threat_type", "lng", "lat",
                "detect_radius_km", "strike_radius_km", "status"]
        rows = [{"threat_id": "TH-04", "threat_name": "敌岸舰导弹阵地F",
                 "threat_type": "岸舰导弹阵地", "lng": 119.5, "lat": 23.6,
                 "detect_radius_km": 80, "strike_radius_km": 150, "status": "活跃"}]
        result = researcher.build_geo_features(rows, cols, "circles",
                                               table_name="mock_enemy_threat")
        by_kind = {c["kind"]: c for c in result["circles"]}
        self.assertEqual(sorted(by_kind), ["recon", "strike"])
        self.assertEqual(by_kind["strike"]["radiusKm"], 150)     # 打击圈取打击半径
        self.assertEqual(by_kind["recon"]["radiusKm"], 80)       # 探测圈取探测半径
        self.assertEqual(by_kind["strike"]["rangeType"], "打击范围")
        self.assertEqual(by_kind["recon"]["rangeType"], "侦察范围")
        for c in result["circles"]:
            self.assertIn("敌岸舰导弹阵地F", c["name"])            # 多半径时圈名带范围后缀

    def test_circles_emit_center_unit_symbol(self):
        """circles 模式须同时给出圆心单位符号，否则地图上只剩孤圈。"""
        cols = ["threat_id", "threat_name", "threat_type", "lng", "lat",
                "detect_radius_km", "strike_radius_km", "status"]
        rows = [{"threat_id": "TH-04", "threat_name": "敌岸舰导弹阵地F",
                 "threat_type": "岸舰导弹阵地", "lng": 119.5, "lat": 23.6,
                 "detect_radius_km": 80, "strike_radius_km": 150, "status": "活跃"}]
        result = researcher.build_geo_features(rows, cols, "circles",
                                               table_name="mock_enemy_threat")
        self.assertEqual(len(result["units"]), 1)                # 每行一个符号，不随半径列翻倍
        u = result["units"][0]
        self.assertEqual(u["unitKind"], "threat")
        self.assertEqual(u["name"], "敌岸舰导弹阵地F")
        self.assertEqual(u["faction"], "蓝方")                     # enemy 表兜底敌方=蓝方
        self.assertEqual(u["type"], "岸舰导弹阵地")

    def test_circles_zero_radius_skipped(self):
        """半径为 0/空的能力列不成圈（如阵地无打击能力时 strike_radius_km=0）。"""
        cols = ["name", "lng", "lat", "recon_radius_km", "strike_radius_km"]
        rows = [{"name": "阵地", "lng": 120.0, "lat": 30.0,
                 "recon_radius_km": 50, "strike_radius_km": 0}]
        result = researcher.build_geo_features(rows, cols, "circles")
        self.assertEqual(len(result["circles"]), 1)
        self.assertEqual(result["circles"][0]["kind"], "recon")
        self.assertEqual(result["circles"][0]["radiusKm"], 50)

    def test_tracks_carry_both_radius_fields(self):
        """航迹同时输出打击/侦察半径，供运行时画动态能力圈。"""
        index = {"AC-RD-01": {"faction": "红方", "category": "重型截击机",
                              "typeId": "RT-01", "strikeRadiusKm": 130,
                              "reconRadiusKm": 260, "callsign": "敌机01"}}
        result = researcher.build_geo_features(
            self._enemy_rows(), self.ENEMY_COLS, "tracks",
            table_name="mock_enemy_track_point", aircraft_index=index)
        tr = result["tracks"][0]
        self.assertEqual(tr["strikeRadiusKm"], 130)
        self.assertEqual(tr["reconRadiusKm"], 260)

    def test_tracks_radius_none_without_index(self):
        """无档案索引时两个半径字段均为 None（由前端按默认值降级）。"""
        result = researcher.build_geo_features(
            self._enemy_rows(), self.ENEMY_COLS, "tracks",
            table_name="mock_enemy_track_point", aircraft_index={})
        tr = result["tracks"][0]
        self.assertIsNone(tr["strikeRadiusKm"])
        self.assertIsNone(tr["reconRadiusKm"])


class SemanticIndexEntryTest(unittest.TestCase):
    """通用维度 enrich 的半径语义分流。"""

    def _graph(self, table: str, columns: dict):
        from agent.dimension_graph import DimensionGraph, TableSpec
        graph = DimensionGraph("db-test")
        graph.tables[table] = TableSpec(table=table, dataset_id="ds-test",
                                        columns=columns)
        return graph

    def test_strike_and_recon_radius_by_column_name(self):
        graph = self._graph("mock_aircraft_type", {
            "strike_radius_km": {}, "recon_radius_km": {},
        })
        entry = researcher._semantic_index_entry(graph, "mock_aircraft_type", {
            "strike_radius_km": "130", "recon_radius_km": 260,
        })
        self.assertEqual(entry["strikeRadiusKm"], 130.0)
        self.assertEqual(entry["reconRadiusKm"], 260.0)

    def test_detect_radius_maps_to_recon(self):
        """探测半径（detect_radius）视为侦察半径。"""
        graph = self._graph("type_table", {"detect_radius_km": {}})
        entry = researcher._semantic_index_entry(graph, "type_table", {"detect_radius_km": 180})
        self.assertEqual(entry["reconRadiusKm"], 180.0)
        self.assertIsNone(entry["strikeRadiusKm"])

    def test_bare_radius_not_used_for_capability_ring(self):
        """语义不明的裸 radius 列不参与动态能力圈。"""
        graph = self._graph("some_table", {"radius_km": {}})
        entry = researcher._semantic_index_entry(graph, "some_table", {"radius_km": 150})
        self.assertIsNone(entry["strikeRadiusKm"])
        self.assertIsNone(entry["reconRadiusKm"])


class MapTimelineTest(unittest.TestCase):
    def test_timeline_aggregates_tracks_and_units(self):
        entries = [{
            "geoFeatures": {
                "tracks": [
                    {"id": "AC-RD-01", "name": "敌机01", "faction": "红方",
                     "category": "重型截击机", "missionId": "M1",
                     "points": [{"time": "2026-07-15 08:00:00"}, {"time": "2026-07-15 10:30:00"}]},
                    {"id": "AC-RD-02", "name": "敌机02", "faction": "红方",
                     "category": "多用途战机", "missionId": "M2",
                     "points": [{"time": "2026-08-02 09:00:00"}, {"time": "2026-08-02 11:00:00"}]},
                ],
                "units": [{"time": "2026-09-01 12:00:00"}],
            }
        }]
        tl = researcher.build_map_timeline(entries)
        self.assertEqual(tl["startDate"], "2026-07-15")
        self.assertEqual(tl["endDate"], "2026-09-01")
        self.assertEqual(len(tl["missions"]), 2)
        self.assertEqual(tl["missions"][0]["missionId"], "M1")
        self.assertEqual(tl["missions"][0]["startTime"], "08:00")
        self.assertEqual(tl["missions"][0]["endTime"], "10:30")

    def test_timeline_none_without_tracks(self):
        self.assertIsNone(researcher.build_map_timeline(
            [{"geoFeatures": {"tracks": [], "units": [{"time": "2026-07-15 10:00:00"}]}}]))

    def test_find_time_field_excludes_commission_date(self):
        """服役日期等档案日期列不能被识别为态势时间字段。"""
        # 只有 commission_date 时应判定为无态势时间
        self.assertIsNone(researcher._find_time_field(
            ["aircraft_id", "callsign", "commission_date", "home_lng", "home_lat"]))
        # 同时存在事件时间列时优先命中事件时间
        self.assertEqual(researcher._find_time_field(
            ["id", "record_time", "commission_date"]), "record_time")
        self.assertEqual(researcher._find_time_field(
            ["target_id", "destroyed_time"]), "destroyed_time")

    def test_aircraft_base_units_time_not_polluted_by_commission_date(self):
        """飞机档案表（基地点）的 unit.time 不得取 commission_date，避免污染时间轴。"""
        cols = ["aircraft_id", "callsign", "base_name", "faction", "status",
                "commission_date", "home_lng", "home_lat"]
        rows = [{
            "aircraft_id": "AC-BL-12", "callsign": "鲲鹏01", "base_name": "汕头基地",
            "faction": "蓝方", "status": "在役", "commission_date": "2022-10-01",
            "home_lng": 116.723, "home_lat": 23.362,
        }]
        result = researcher.build_geo_features(
            rows, cols, "points", table_name="mock_aircraft")
        self.assertEqual(len(result["units"]), 1)
        self.assertIsNone(result["units"][0]["time"])
        self.assertEqual(result["units"][0]["name"], "汕头基地")
        # 时间轴汇总不被档案日期拉到 2022 年
        tl = researcher.build_map_timeline([{"geoFeatures": result}])
        self.assertIsNone(tl)


class ThinningTest(unittest.TestCase):
    def test_indices_keep_ends_and_ordered(self):
        idx = researcher._thin_indices(10, 10)
        self.assertEqual(idx, list(range(10)))
        idx2 = researcher._thin_indices(1000, 200)
        self.assertEqual(len(idx2), 200)
        self.assertEqual(idx2[0], 0)
        self.assertEqual(idx2[-1], 999)
        self.assertEqual(idx2, sorted(idx2))

    def test_points_thinned_to_limit(self):
        cols = ["name", "lng", "lat"]
        rows = [{"name": f"p{i}", "lng": 120 + i * 0.001, "lat": 30 + i * 0.001}
                for i in range(config.IPAGE_MAP_POINT_LIMIT + 500)]
        result = researcher.build_geo_features(rows, cols, "points")
        self.assertLessEqual(len(result["points"]), config.IPAGE_MAP_POINT_LIMIT)
        self.assertEqual(result["points"][0]["name"], "p0")


class SummaryTest(unittest.TestCase):
    def test_summary_contains_stats(self):
        rows = [{"cat": "红方", "n": 10}, {"cat": "红方", "n": 20}, {"cat": "蓝方", "n": 30}]
        text = researcher.build_summary(["cat", "n"], rows)
        self.assertIn("行数：3", text)
        self.assertIn("n:", text)
        self.assertIn("红方", text)

    def test_summary_empty(self):
        self.assertEqual(researcher.build_summary(["id"], []), "（无数据）")


if __name__ == "__main__":
    unittest.main()
