"""Integration tests for database connection testing (live + graceful failure)."""

from __future__ import annotations

import unittest

from base import BaseServiceTest


class ConnectionTestApiTests(BaseServiceTest):
    def test_missing_database_id_rejected_with_400(self) -> None:
        payload = self.admin_post("/api/admin/database/nope/test", expect=404)

    def test_dataquery_test_connection_missing_id(self) -> None:
        payload = self.admin_post("/api/dataquery/test-connection", json={}, expect=400)
        self.assertApiError(payload, "databaseId")

    def test_dataquery_test_connection_unknown_id(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/test-connection", json={"databaseId": "db_nope"}, expect=400
        )
        self.assertApiError(payload, "数据库配置不存在")

    def test_connection_success_for_reachable_mysql(self) -> None:
        db_id = self.connected_mysql_id()
        if not db_id:
            self.skipTest("没有已连接的 MySQL 数据源")
        payload = self.admin_post(f"/api/admin/database/{db_id}/test")
        self.assertSuccess(payload)
        self.assertIn("ms", payload.get("latency", ""))
        self.assertTrue(payload.get("dbVersion"))

    def test_unreachable_postgresql_fails_gracefully(self) -> None:
        created = self.admin_post(
            "/api/admin/database",
            json={
                "name": "连接测试-不可达PG",
                "type": "PostgreSQL",
                "host": "127.0.0.1",
                "port": 59998,
                "database": "x",
                "username": "u",
                "password": "p",
            },
        )
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        payload = self.admin_post(f"/api/admin/database/{created['id']}/test")
        self.assertFalse(payload.get("success", True))
        self.assertIn("失败", payload.get("message", ""))
        # 状态被持久化为失败
        found = self.find_database(id=created["id"])
        self.assertEqual("失败", found["status"])
        self.assertTrue(found.get("errorMsg"))

    def test_missing_driver_jar_fails_gracefully(self) -> None:
        created = self.admin_post(
            "/api/admin/database",
            json={
                "name": "连接测试-缺驱动Oracle",
                "type": "Oracle",
                "host": "127.0.0.1",
                "port": 1521,
                "database": "ORCL",
                "username": "system",
                "password": "x",
            },
        )
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        payload = self.admin_post(f"/api/admin/database/{created['id']}/test")
        self.assertFalse(payload.get("success", True))
        self.assertIn("JAR", payload.get("message", ""))

    def test_dataquery_test_connection_on_reachable_mysql(self) -> None:
        db_id = self.connected_mysql_id()
        if not db_id:
            self.skipTest("没有已连接的 MySQL 数据源")
        payload = self.admin_post(
            "/api/dataquery/test-connection", json={"databaseId": db_id}
        )
        self.assertSuccess(payload)
        self.assertIn("ms", payload.get("latency", ""))


if __name__ == "__main__":
    unittest.main()
