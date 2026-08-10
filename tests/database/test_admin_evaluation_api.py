"""Integration tests for the EvaluationController endpoints.

These are the endpoints the qa-service text-to-SQL pipeline actually calls:
execute-sql, evaluation context export and dataset full-structure.
"""

from __future__ import annotations

import unittest

from base import BaseServiceTest, require_connected_database


@unittest.skipUnless(
    BaseServiceTest.any_connected_id(), "需要一个已连接的数据库配置（MySQL）"
)
class EvaluationControllerTests(BaseServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.db_id = require_connected_database(cls)

    def test_database_execute_sql_endpoint(self) -> None:
        payload = self.admin_post(
            f"/api/admin/database/{self.db_id}/execute-sql",
            json={"sql": "SELECT 1 AS one"},
        )
        self.assertSuccess(payload)
        self.assertEqual(["one"], payload["columns"])
        self.assertEqual("1", payload["rows"][0]["one"])

    def test_database_execute_sql_empty_sql_400(self) -> None:
        payload = self.admin_post(
            f"/api/admin/database/{self.db_id}/execute-sql", json={"sql": "   "}, expect=400
        )
        self.assertApiError(payload, "SQL不能为空")

    def test_database_execute_sql_write_rejected(self) -> None:
        payload = self.admin_post(
            f"/api/admin/database/{self.db_id}/execute-sql",
            json={"sql": "UPDATE ass_database_config SET name = 'x'"},
        )
        self.assertApiError(payload, "只允许执行SELECT或WITH")

    def test_dataset_execute_sql_works_on_linked_dataset(self) -> None:
        created = self.admin_post(
            "/api/admin/dataset",
            json={
                "name": "执行-数据集",
                "databaseId": self.db_id,
                "tableName": "ass_database_config",
            },
        )
        self.assertSuccess(created)
        self.created_dataset_ids.append(created["id"])
        payload = self.admin_post(
            f"/api/admin/dataset/{created['id']}/execute-sql",
            json={"sql": "SELECT COUNT(*) AS n FROM ass_database_config"},
        )
        self.assertSuccess(payload)
        self.assertIn("n", payload["columns"])

    def test_dataset_execute_sql_empty_sql_400(self) -> None:
        created = self.admin_post(
            "/api/admin/dataset", json={"name": "执行-空SQL", "databaseId": ""}
        )
        self.created_dataset_ids.append(created["id"])
        payload = self.admin_post(
            f"/api/admin/dataset/{created['id']}/execute-sql", json={"sql": ""}, expect=400
        )
        self.assertApiError(payload, "SQL不能为空")

    def test_evaluation_context_returns_schemas_and_indicators(self) -> None:
        payload = self.admin_post(
            "/api/admin/evaluation/context",
            json={"datasetIds": [], "indicatorIds": []},
        )
        self.assertSuccess(payload)
        self.assertIn("schemas", payload)
        self.assertIn("indicators", payload)

    def test_full_structure_for_linked_dataset(self) -> None:
        created = self.admin_post(
            "/api/admin/dataset",
            json={
                "name": "结构-数据集",
                "databaseId": self.db_id,
                "tableName": "ass_database_config",
            },
        )
        self.created_dataset_ids.append(created["id"])
        payload = self.admin_get(f"/api/admin/dataset/{created['id']}/full-structure")
        self.assertSuccess(payload)
        self.assertEqual("ass_database_config", payload["tableName"])
        self.assertIn("columns", payload)
        self.assertIn("count", payload)
        self.assertGreaterEqual(payload["count"], 1)

    def test_full_structure_missing_dataset(self) -> None:
        payload = self.admin_get("/api/admin/dataset/ds_nope/full-structure")
        self.assertApiError(payload, "数据集不存在")


if __name__ == "__main__":
    unittest.main()
