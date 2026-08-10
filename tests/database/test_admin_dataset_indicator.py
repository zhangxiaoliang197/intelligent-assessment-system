"""Integration tests for dataset / field-annotation / indicator management.

Covers: dataset CRUD, read-structure, field annotations, indicator CRUD,
indicator-dataset linkage and the /export/for-llm schema feed.
"""

from __future__ import annotations

import unittest

from base import BaseServiceTest, require_connected_database

KNOWN_TABLE = "ass_database_config"


class DatasetCrudTests(BaseServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            cls.db_id = require_connected_database(cls)
        except unittest.SkipTest:
            cls.db_id = ""

    def _new_dataset(self, name: str) -> dict:
        payload = {
            "name": name,
            "description": "自动化测试创建的数据集",
            "databaseId": self.db_id or "",
            "tableName": KNOWN_TABLE if self.db_id else "",
        }
        created = self.admin_post("/api/admin/dataset", json=payload)
        self.assertSuccess(created)
        self.assertTrue(created["id"].startswith("ds_"))
        self.created_dataset_ids.append(created["id"])
        return created

    def test_create_list_get_update_delete(self) -> None:
        created = self._new_dataset("数据集-全流程")
        ds_id = created["id"]

        listed = self.admin_get("/api/admin/dataset/list")
        self.assertSuccess(listed)
        ds = next(x for x in listed["datasets"] if x["id"] == ds_id)
        self.assertEqual("数据集-全流程", ds["name"])
        self.assertEqual(KNOWN_TABLE, ds["tableName"])

        detail = self.admin_get(f"/api/admin/dataset/{ds_id}")
        self.assertSuccess(detail)
        self.assertEqual("数据集-全流程", detail["data"]["name"])
        self.assertEqual("", detail["data"]["sqlText"])

        updated = self.admin_put(
            f"/api/admin/dataset/{ds_id}",
            json={"name": "数据集-全流程-改名", "sql": "SELECT * FROM ass_database_config"},
        )
        self.assertSuccess(updated)
        self.assertEqual("数据集已更新", updated["message"])
        detail = self.admin_get(f"/api/admin/dataset/{ds_id}")
        self.assertEqual("数据集-全流程-改名", detail["data"]["name"])
        self.assertEqual("SELECT * FROM ass_database_config", detail["data"]["sqlText"])

        deleted = self.admin_delete(f"/api/admin/dataset/{ds_id}")
        self.assertSuccess(deleted)
        self.assertEqual("数据集已删除", deleted["message"])

    def test_get_missing_dataset_returns_404(self) -> None:
        resp = self.admin_get("/api/admin/dataset/ds_nope", expect=404)
        self.assertIsNone(resp)

    def test_delete_is_idempotent(self) -> None:
        deleted = self.admin_delete("/api/admin/dataset/ds_never")
        self.assertSuccess(deleted)

    def test_list_contains_new_dataset(self) -> None:
        self._new_dataset("数据集-存在性")
        listed = self.admin_get("/api/admin/dataset/list")
        names = {x["name"] for x in listed["datasets"]}
        self.assertIn("数据集-存在性", names)

    def test_uninitialized_structure_returns_clear_message(self) -> None:
        created = self._new_dataset("数据集-未读取结构")
        ds_id = created["id"]
        if not self.db_id:
            self.skipTest("无已连接数据库")
        payload = self.admin_get(f"/api/admin/dataset/{ds_id}/structure")
        # tableName 未通过 read-structure 设置前，不自动带结构
        self.assertIn("columns", payload)

    def test_read_structure_sets_table_and_returns_columns(self) -> None:
        if not self.db_id:
            self.skipTest("无已连接数据库")
        created = self._new_dataset("数据集-读取结构")
        ds_id = created["id"]
        payload = self.admin_post(
            f"/api/admin/dataset/{ds_id}/read-structure",
            json={"tableName": KNOWN_TABLE},
        )
        self.assertSuccess(payload)
        self.assertEqual(KNOWN_TABLE, payload["tableName"])
        self.assertGreaterEqual(payload["count"], 1)
        self.assertIn("columns", payload)

        # 结构已固化到数据集，structure 接口直接返回
        payload = self.admin_get(f"/api/admin/dataset/{ds_id}/structure")
        self.assertSuccess(payload)
        self.assertGreaterEqual(payload["count"], 1)

    def test_read_structure_missing_dataset_400(self) -> None:
        payload = self.admin_post(
            "/api/admin/dataset/ds_nope/read-structure", json={"tableName": KNOWN_TABLE}, expect=400
        )
        self.assertApiError(payload, "数据集不存在")

    def test_read_structure_unsafe_table_name_400(self) -> None:
        created = self._new_dataset("数据集-非法表名")
        payload = self.admin_post(
            f"/api/admin/dataset/{created['id']}/read-structure",
            json={"tableName": "a;b"},
            expect=400,
        )
        self.assertApiError(payload, "不支持的字符")


class FieldAnnotationTests(BaseServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            cls.db_id = require_connected_database(cls)
        except unittest.SkipTest:
            cls.db_id = ""

    def _new_dataset(self) -> str:
        created = self.admin_post(
            "/api/admin/dataset",
            json={"name": "标注-数据集", "databaseId": self.db_id or "", "tableName": KNOWN_TABLE},
        )
        self.created_dataset_ids.append(created["id"])
        return created["id"]

    def test_fields_empty_by_default(self) -> None:
        ds_id = self._new_dataset()
        payload = self.admin_get(f"/api/admin/dataset/{ds_id}/fields")
        self.assertSuccess(payload)
        self.assertEqual(0, payload["total"])
        self.assertEqual([], payload["fields"])

    def test_save_and_read_field_annotations(self) -> None:
        ds_id = self._new_dataset()
        saved = self.admin_post(
            f"/api/admin/dataset/{ds_id}/fields",
            json=[
                {
                    "columnName": "id",
                    "columnType": "varchar",
                    "isPrimaryKey": True,
                    "isNullable": False,
                    "columnComment": "主键",
                    "annotation": "数据库配置主键",
                    "businessMeaning": "唯一标识",
                    "dataCategory": "标识",
                },
                {
                    "columnName": "name",
                    "columnType": "varchar",
                    "isPrimaryKey": False,
                    "isNullable": True,
                    "columnComment": "名称",
                    "annotation": "配置名称",
                    "businessMeaning": "展示名称",
                    "dataCategory": "基础",
                },
            ],
        )
        self.assertSuccess(saved)
        self.assertEqual("标注已保存", saved["message"])
        self.assertEqual(2, saved["total"])

        payload = self.admin_get(f"/api/admin/dataset/{ds_id}/fields")
        self.assertEqual(2, payload["total"])
        by_name = {f["columnName"]: f for f in payload["fields"]}
        self.assertTrue(by_name["id"]["isPrimaryKey"])
        self.assertEqual("数据库配置主键", by_name["id"]["annotation"])

        # 更新单条标注
        field = payload["fields"][0]
        updated = self.admin_put(
            f"/api/admin/dataset/{ds_id}/fields/{field['id']}",
            json={"annotation": "更新的业务含义", "dataCategory": "核心"},
        )
        self.assertSuccess(updated)
        payload = self.admin_get(f"/api/admin/dataset/{ds_id}/fields")
        changed = next(f for f in payload["fields"] if f["id"] == field["id"])
        self.assertEqual("更新的业务含义", changed["annotation"])

    def test_save_fields_missing_dataset_400(self) -> None:
        payload = self.admin_post(
            "/api/admin/dataset/ds_nope/fields", json=[], expect=400
        )
        self.assertApiError(payload, "数据集不存在")

    def test_update_field_missing_field_400(self) -> None:
        payload = self.admin_put(
            "/api/admin/dataset/ds_any/fields/fa_nope",
            json={"annotation": "x"},
            expect=400,
        )
        self.assertApiError(payload, "标注不存在")

    def test_fields_are_replaced_on_resave(self) -> None:
        ds_id = self._new_dataset()
        self.admin_post(f"/api/admin/dataset/{ds_id}/fields", json=[{"columnName": "id"}])
        self.admin_post(
            f"/api/admin/dataset/{ds_id}/fields",
            json=[{"columnName": "id"}, {"columnName": "name"}],
        )
        payload = self.admin_get(f"/api/admin/dataset/{ds_id}/fields")
        self.assertEqual(2, payload["total"])


class IndicatorCrudTests(BaseServiceTest):
    def _new_indicator(self, name: str) -> dict:
        created = self.admin_post(
            "/api/admin/indicator",
            json={
                "name": name,
                "category": "效能",
                "formula": "SUM(SCORE) / COUNT(*)",
                "description": "自动化测试指标",
                "weight": 0.5,
            },
        )
        self.assertSuccess(created)
        self.assertTrue(created["id"].startswith("ind_"))
        self.created_indicator_ids.append(created["id"])
        return created

    def test_create_list_get_update_delete(self) -> None:
        created = self._new_indicator("指标-全流程")
        ind_id = created["id"]

        listed = self.admin_get("/api/admin/indicator/list")
        self.assertSuccess(listed)
        ind = next(x for x in listed["indicators"] if x["id"] == ind_id)
        self.assertEqual("指标-全流程", ind["name"])
        self.assertEqual("效能", ind["category"])
        self.assertEqual(0.5, ind["weight"])

        detail = self.admin_get(f"/api/admin/indicator/{ind_id}")
        self.assertSuccess(detail)
        self.assertEqual("SUM(SCORE) / COUNT(*)", detail["data"]["formula"])

        updated = self.admin_put(
            f"/api/admin/indicator/{ind_id}",
            json={"name": "指标-全流程-改名", "weight": 0.8},
        )
        self.assertSuccess(updated)
        self.assertEqual("指标已更新", updated["message"])
        detail = self.admin_get(f"/api/admin/indicator/{ind_id}")
        self.assertEqual("指标-全流程-改名", detail["data"]["name"])
        self.assertEqual(0.8, detail["data"]["weight"])

        deleted = self.admin_delete(f"/api/admin/indicator/{ind_id}")
        self.assertSuccess(deleted)
        self.assertEqual("指标已删除", deleted["message"])

    def test_get_missing_indicator_returns_404(self) -> None:
        self.admin_get("/api/admin/indicator/ind_nope", expect=404)

    def test_delete_is_idempotent(self) -> None:
        self.assertSuccess(self.admin_delete("/api/admin/indicator/ind_never"))

    def test_link_dataset_and_read_linkage(self) -> None:
        created = self._new_indicator("指标-关联")
        ind_id = created["id"]
        dataset = self.admin_post(
            "/api/admin/dataset", json={"name": "关联-数据集", "databaseId": ""}
        )
        self.assertSuccess(dataset)
        self.created_dataset_ids.append(dataset["id"])

        linked = self.admin_post(
            f"/api/admin/indicator/{ind_id}/link-dataset",
            json={
                "datasetId": dataset["id"],
                "fieldMapping": '{"SCORE": "score"}',
                "calculationMethod": "加权平均",
            },
        )
        self.assertSuccess(linked)
        self.assertEqual("关联已保存", linked["message"])

        linkage = self.admin_get(f"/api/admin/indicator/{ind_id}/linkage")
        self.assertSuccess(linkage)
        self.assertEqual(dataset["id"], linkage["data"]["datasetId"])
        self.assertEqual("加权平均", linkage["data"]["calculationMethod"])
        self.assertEqual('{"SCORE": "score"}', linkage["data"]["fieldMapping"])
        self.assertEqual("关联-数据集", linkage["data"]["datasetName"])
        self.assertIn("linkedFields", linkage["data"])

    def test_link_dataset_missing_indicator_400(self) -> None:
        payload = self.admin_post(
            "/api/admin/indicator/ind_nope/link-dataset", json={"datasetId": "ds_x"}, expect=400
        )
        self.assertApiError(payload, "指标不存在")

    def test_linkage_missing_indicator_400(self) -> None:
        payload = self.admin_get("/api/admin/indicator/ind_nope/linkage", expect=400)
        self.assertApiError(payload, "指标不存在")


class ExportForLlmTests(BaseServiceTest):
    def test_export_returns_schema_and_indicator_feed(self) -> None:
        payload = self.admin_get("/api/admin/export/for-llm")
        self.assertSuccess(payload)
        self.assertIn("data", payload)
        for key in ("schemas", "indicators", "exportTime"):
            self.assertIn(key, payload["data"], f"export 缺少 {key}")
        self.assertIsInstance(payload["data"]["schemas"], list)
        self.assertIsInstance(payload["data"]["indicators"], list)


if __name__ == "__main__":
    unittest.main()
