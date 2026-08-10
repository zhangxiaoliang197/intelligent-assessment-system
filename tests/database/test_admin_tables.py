"""Integration tests for table discovery / column metadata endpoints.

Requires a reachable MySQL config (the metadata database).
"""

from __future__ import annotations

import unittest

from base import BaseServiceTest, require_connected_database

KNOWN_TABLE = "ass_database_config"


@unittest.skipUnless(
    BaseServiceTest.any_connected_id(), "需要一个已连接的数据库配置（MySQL）"
)
class TableMetadataTests(BaseServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.db_id = require_connected_database(cls)

    # ------------------------------------------------------- table listing

    def test_list_tables_returns_table_objects(self) -> None:
        payload = self.admin_get(f"/api/admin/database/{self.db_id}/tables")
        self.assertSuccess(payload)
        self.assertIn("tables", payload)
        self.assertIn("total", payload)
        self.assertTrue(payload["total"] >= 1)
        sample = payload["tables"][0]
        for key in ("tableName", "schemaName", "catalogName", "tableComment"):
            self.assertIn(key, sample, f"表对象缺少 {key}")
        self.assertIn("_diag", payload)
        self.assertIn("databaseProductName", payload)

    def test_metadata_database_contains_system_tables(self) -> None:
        payload = self.admin_get(f"/api/admin/database/{self.db_id}/tables")
        names = {t["tableName"].lower() for t in payload["tables"]}
        for expected in ("ass_database_config", "ass_driver", "ass_dataset", "ass_indicator"):
            self.assertIn(expected, names, f"元数据库应包含 {expected}")

    def test_list_tables_with_columns(self) -> None:
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/tables?includeColumns=true"
        )
        self.assertSuccess(payload)
        config = next(t for t in payload["tables"] if t["tableName"] == KNOWN_TABLE)
        self.assertIn("columns", config)
        self.assertIn("columnCount", config)
        self.assertTrue(config["columnCount"] >= 1)
        self.assertIn("columnName", config["columns"][0])

    def test_list_tables_unknown_database_returns_400(self) -> None:
        payload = self.admin_get("/api/admin/database/db_nope/tables", expect=400)
        self.assertApiError(payload, "数据库配置不存在")

    def test_list_tables_unsupported_type_reports_driver_missing(self) -> None:
        created = self.admin_post(
            "/api/admin/database",
            json={"name": "表测试-未知类型", "type": "NotADatabase", "host": "x", "port": 1},
        )
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        payload = self.admin_get(f"/api/admin/database/{created['id']}/tables", expect=400)
        self.assertApiError(payload, "不支持的数据库类型")

    # ------------------------------------------------------- column reads

    def test_columns_for_known_table(self) -> None:
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/table/{KNOWN_TABLE}/columns"
        )
        self.assertSuccess(payload)
        self.assertEqual(KNOWN_TABLE, payload["tableName"])
        self.assertIn("columns", payload)
        self.assertIn("count", payload)
        self.assertEqual(len(payload["columns"]), payload["count"])
        col = payload["columns"][0]
        for key in ("columnName", "dataType", "isNullable", "isPrimaryKey", "comment"):
            self.assertIn(key, col, f"列对象缺少 {key}")

    def test_primary_key_column_is_marked(self) -> None:
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/table/{KNOWN_TABLE}/columns"
        )
        id_col = next(c for c in payload["columns"] if c["columnName"] == "id")
        self.assertTrue(id_col["isPrimaryKey"], "id 列应标记为主键")

    def test_table_structure_endpoint_matches_columns(self) -> None:
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/table-structure?tableName={KNOWN_TABLE}"
        )
        self.assertSuccess(payload)
        self.assertEqual(KNOWN_TABLE, payload["tableName"])
        self.assertGreaterEqual(payload["count"], 1)

    def test_table_structure_requires_table_name_param(self) -> None:
        self.admin_get(f"/api/admin/database/{self.db_id}/table-structure", expect=400)

    def test_unsafe_table_name_rejected(self) -> None:
        # 路径里的分号会被 Spring 当作矩阵参数剥离，改用 URL 编码的单引号
        # 触发 isSafeMetadataTableName 的字符白名单校验。
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/table/evil%27x/columns", expect=400
        )
        self.assertApiError(payload, "不支持的字符")

    def test_missing_table_on_connected_database_reports_failure(self) -> None:
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/table/no_such_table_xyz/columns"
        )
        # 表不存在：JDBC 返回空列集（success:true, count:0）或报错，不能是 500
        self.assertIn("success", payload)
        self.assertIn("columns", payload)

    def test_profile_keys_attached_to_column_reads(self) -> None:
        payload = self.admin_get(
            f"/api/admin/database/{self.db_id}/table/{KNOWN_TABLE}/columns"
        )
        for key in ("databaseType", "databaseProductName", "databaseProductVersion", "identifierQuoteString"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
