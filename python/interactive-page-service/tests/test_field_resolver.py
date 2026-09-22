"""字段解析器测试：注解优先 + 注解缺失零回归。

覆盖两类断言：
1. **注解命中**：中文列名/非约定命名也能解析出坐标、时间、拆分键、半径、单位大类、符号、阵营；
2. **注解缺失等价**：``spec=None`` 时每个方法与列名启发式结果完全一致（零回归的构造性证明）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import dimension_graph as dg  # noqa: F401  兼容既有导入路径
from agent import field_resolver
from agent.field_resolver import FieldResolver, build_resolver


def _spec(table: str, columns: dict, semantic: dict = None) -> "dg.TableSpec":
    """构造 TableSpec：columns 形如 {列名: (类型, 业务含义, 字段语义)}。"""
    spec = dg.TableSpec(table=table, dataset_id="ds_1")
    spec.semantic = dict(semantic or {})
    for name, triple in columns.items():
        ctype, meaning, col_semantic = (list(triple) + [None, None, None])[:3]
        spec.columns[name] = {
            "type": ctype or "varchar",
            "meaning": meaning or "",
            "pk": False,
            "semantic": col_semantic or {},
        }
    return spec


class ResolverFallbackTest(unittest.TestCase):
    """spec=None：必须与改造前完全一致。"""

    def test_coord_pair_matches_legacy(self):
        columns = ["id", "track_lng", "track_lat", "lng", "lat"]
        resolver = FieldResolver(None, columns, "t")
        pairs = field_resolver.find_coord_pairs(columns)
        self.assertEqual(resolver.coord_pair(), (pairs[0][1], pairs[0][2]))
        self.assertIsNone(FieldResolver(None, ["id", "name"], "t").coord_pair())

    def test_time_and_sort_match_legacy(self):
        columns = ["aircraft_id", "seq", "record_time", "commission_date"]
        resolver = FieldResolver(None, columns, "t")
        self.assertEqual(resolver.event_time_column(),
                         field_resolver.find_time_field(columns))
        self.assertEqual(resolver.sort_column(), "seq")

    def test_time_falls_back_to_event_time_when_no_seq(self):
        resolver = FieldResolver(None, ["event_time"], "t")
        self.assertEqual(resolver.sort_column(), "event_time")

    def test_unit_kind_matches_legacy_table_map(self):
        self.assertEqual(FieldResolver(None, ["id"], "mock_enemy_threat").unit_kind(), "threat")
        self.assertEqual(FieldResolver(None, ["id"], "mock_aircraft").unit_kind(), "base")
        self.assertEqual(FieldResolver(None, ["id"], "orders").unit_kind(), "")

    def test_textual_fallback_disabled_without_annotation(self):
        """只有 businessMeaning 含"时间"、列名无线索时，不得被隐式识别（存量数据不变）。"""
        spec = _spec("orders", {"create_stamp": ("varchar", "事件时间", None)})
        resolver = FieldResolver(spec, ["create_stamp"], "orders")
        self.assertFalse(resolver.textual_fallback_enabled)
        self.assertIsNone(resolver.event_time_column())

    def test_radius_columns_match_legacy(self):
        columns = ["name", "lng", "lat", "radius_km", "detect_radius_km"]
        resolver = FieldResolver(None, columns, "t")
        self.assertEqual(resolver.radius_columns(), ["radius_km", "detect_radius_km"])
        self.assertEqual(resolver.radius_kind_of("detect_radius_km"), "recon")
        self.assertEqual(resolver.radius_kind_of("radius_km"), "")
        self.assertEqual(resolver.radius_kind_of("strike_radius_km"), "strike")

    def test_faction_of_matches_legacy(self):
        resolver = FieldResolver(None, ["faction"], "mock_enemy_threat")
        self.assertEqual(resolver.faction_of({"faction": "红方"}), ("红方", ""))
        # 无有效值 → 表名含 enemy 兜底敌方=蓝方
        self.assertEqual(resolver.faction_of({"faction": "RED"}, fallback_unit="蓝方"),
                         ("蓝方", ""))
        self.assertEqual(resolver.faction_of({"faction": "RED"}), ("", ""))

    def test_track_group_matches_legacy(self):
        resolver = FieldResolver(None, ["aircraft_id", "mission_id"], "t")
        self.assertEqual(resolver.track_group_columns("aircraft_id", "mission_id"),
                         ["aircraft_id", "mission_id"])
        self.assertEqual(resolver.track_group_columns("aircraft_id"), ["aircraft_id"])
        self.assertEqual(resolver.track_group_columns(None, None, "callsign"), ["callsign"])


class ResolverAnnotationTest(unittest.TestCase):
    """注解命中：完全不同于命名习惯的字段也能解析。"""

    def _cn_spec(self) -> "dg.TableSpec":
        """一张"全中文列名"的航迹表。"""
        return _spec(
            "flight_log",
            {
                "实体编号": ("varchar", "平台编号", {"role": "id"}),
                "架次": ("int", "架次号", {"role": "seq"}),
                "观测时刻": ("datetime", "观测时间", {"role": "time"}),
                "经度": ("decimal", "经度", {"role": "lng"}),
                "纬度": ("decimal", "纬度", {"role": "lat"}),
                "高度": ("int", "高度", {"role": "altitude"}),
                "速度": ("int", "速度", {"role": "speed"}),
                "航向": ("int", "航向", {"role": "heading"}),
                "归属": ("varchar", "阵营", {
                    "role": "dimension",
                    "values": {"本方": "blue", "对方": "red"},
                    "synonyms": {"我军": "blue", "敌军": "red"},
                }),
                "载荷": ("varchar", "挂载", {"role": "dimension"}),
            },
            {
                "entityKind": "air",
                "symbolDefault": "fighter",
                "trackGroupKey": ["实体编号", "架次"],
                "eventTimeColumn": "观测时刻",
                "geometry": {"lngColumn": "经度", "latColumn": "纬度"},
            },
        )

    def test_all_semantic_slots_resolved(self):
        spec = self._cn_spec()
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        self.assertEqual(resolver.coord_pair(), ("经度", "纬度"))
        self.assertEqual(resolver.event_time_column(), "观测时刻")
        self.assertEqual(resolver.sort_column(), "架次")
        self.assertEqual(resolver.track_group_columns("实体编号"), ["实体编号", "架次"])
        self.assertEqual(resolver.unit_kind(), "aircraft")
        self.assertEqual(resolver.symbol("载荷"), "fighter")
        self.assertEqual(resolver.altitude_column(), "高度")
        self.assertEqual(resolver.speed_column(), "速度")
        self.assertEqual(resolver.heading_column(), "航向")
        self.assertEqual(resolver.notes, [])

    def test_faction_canonical_and_color(self):
        spec = self._cn_spec()
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        column = resolver.faction_column()
        self.assertEqual(column, "归属")
        self.assertEqual(resolver.faction_of({"归属": "本方"}, column=column),
                         ("blue", "#1d4ed8"))
        # 同义词也要能命中同一规范值
        self.assertEqual(resolver.canonical_value("归属", "敌军"), "red")

    def test_value_term_map_uses_raw_values_for_sql(self):
        spec = self._cn_spec()
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        standards, terms = resolver.value_term_map("归属")
        # SQL 过滤必须用原始值，不能用规范值
        self.assertEqual(standards, {"本方", "对方"})
        self.assertEqual(terms["我军"], "本方")
        self.assertEqual(terms["blue"], "本方")
        self.assertEqual(terms["敌军"], "对方")
        self.assertEqual(resolver.value_term_map("载荷"), (set(), {}))

    def test_track_group_requires_all_columns(self):
        """注解里有不存在的列 → 整体回落历史口径，不半生效。"""
        spec = self._cn_spec()
        spec.semantic["trackGroupKey"] = ["实体编号", "不存在的列"]
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        self.assertEqual(resolver.track_group_columns("实体编号", "架次"),
                         ["实体编号", "架次"])
        self.assertTrue(any("不存在的列" in note for note in resolver.notes))

    def test_unknown_symbol_and_status_are_ignored(self):
        spec = _spec("t", {
            "状态": ("varchar", "状态", {"role": "status",
                                      "values": {"重度受损": "critical", "未知档": "weird"}}),
        }, {"symbolDefault": "transformer"})
        resolver = FieldResolver(spec, ["状态"], "t")
        self.assertEqual(resolver.symbol(), "")
        self.assertEqual(resolver.status_key("状态", "重度受损"), "critical")
        self.assertEqual(resolver.status_key("状态", "未知档"), "")
        self.assertTrue(any("weird" in note for note in resolver.notes))

    def test_radius_column_from_annotation_and_meaning(self):
        spec = _spec("air_defense", {
            "圆点": ("varchar", "阵地名", None),
            "覆盖距离": ("decimal", "打击半径（公里）", {"role": "radius"}),
            "lon": ("decimal", "经度", None),
            "lat": ("decimal", "纬度", None),
        }, {"entityKind": "ground_facility",
            "geometry": {"lngColumn": "lon", "latColumn": "lat",
                         "radiusColumn": "覆盖距离"}})
        resolver = FieldResolver(spec, list(spec.columns.keys()), "air_defense")
        self.assertEqual(resolver.radius_columns(), ["覆盖距离"])
        self.assertEqual(resolver.radius_kind_of("覆盖距离"), "strike")
        self.assertEqual(resolver.unit_kind(), "facility")

    def test_textual_fallback_enabled_once_annotated(self):
        """一旦声明了结构化语义，业务含义文本才作为 ② 层参与识别。"""
        spec = _spec("orders", {
            "obs_stamp": ("varchar", "事件时间", {"role": "name"}),
        })
        resolver = FieldResolver(spec, ["obs_stamp"], "orders")
        self.assertTrue(resolver.textual_fallback_enabled)
        self.assertEqual(resolver.event_time_column(), "obs_stamp")

    def test_value_domain_note(self):
        spec = self._cn_spec()
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        self.assertIn("归属", resolver.value_domain_note("归属", ["本方"]))
        self.assertEqual("", resolver.value_domain_note("归属", ["本方", "对方"]))

    def test_value_drift_note_uses_rows_without_sampling(self):
        """零成本漂移告警：用内存行发现注解值域外的取值（不查库）。"""
        spec = self._cn_spec()
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        notes = resolver.value_drift_notes([{"归属": "本方"}, {"归属": "第三方"}])
        self.assertEqual(1, len(notes))
        self.assertIn("第三方", notes[0])
        self.assertIn("归属", notes[0])
        # 取值都在注解值域内 → 不告警
        self.assertEqual([], resolver.value_drift_notes([{"归属": "本方"}, {"归属": "对方"}]))

    def test_value_drift_note_skips_unannotated_columns(self):
        spec = self._cn_spec()
        resolver = FieldResolver(spec, list(spec.columns.keys()), "flight_log")
        self.assertEqual([], resolver.value_drift_notes([{"载荷": "空空导弹"}]))


class BuildResolverTest(unittest.TestCase):

    def test_build_resolver_degrades_on_bad_meta(self):
        resolver = build_resolver({"success": False}, "t", ["lng", "lat"])
        self.assertIsNone(resolver.spec)
        self.assertEqual(resolver.coord_pair(), ("lng", "lat"))

    def test_build_resolver_reads_graph_spec(self):
        meta = {
            "success": True,
            "data": {
                "databaseId": "db_1",
                "schemas": [{
                    "datasetId": "ds_1", "tableName": "t_a",
                    "semanticJson": '{"entityKind":"ground_facility"}',
                    "fields": [{"column": "lng", "type": "decimal"},
                               {"column": "lat", "type": "decimal"}],
                }],
            },
        }
        resolver = build_resolver(meta, "t_a", ["lng", "lat"])
        self.assertIsNotNone(resolver.spec)
        self.assertEqual(resolver.unit_kind(), "facility")


if __name__ == "__main__":
    unittest.main()
