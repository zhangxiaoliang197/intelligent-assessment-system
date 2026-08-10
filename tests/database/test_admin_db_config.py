"""Integration tests for database-config CRUD under /api/admin/database."""

from __future__ import annotations

import unittest

from base import BaseServiceTest


def _config(name: str, db: str = "assessment") -> dict:
    return {
        "name": name,
        "type": "MySQL",
        "host": "127.0.0.1",
        "port": 3306,
        "database": db,
        "username": "root",
        "password": "root",
    }


class DatabaseConfigCrudTests(BaseServiceTest):
    def test_list_returns_success_and_known_entries(self) -> None:
        payload = self.admin_get("/api/admin/database/list")
        self.assertSuccess(payload)
        self.assertIn("total", payload)
        self.assertIn("databases", payload)
        self.assertIsInstance(payload["databases"], list)

    def test_created_config_appears_in_list_with_all_fields(self) -> None:
        created = self.admin_post("/api/admin/database", json=_config("CRUD-测试库-1"))
        self.assertSuccess(created)
        self.assertTrue(created["id"].startswith("db_"))
        self.created_database_ids.append(created["id"])

        found = self.find_database(id=created["id"])
        self.assertIsNotNone(found, "新创建的配置应在列表中")
        self.assertEqual("CRUD-测试库-1", found["name"])
        self.assertEqual("MySQL", found["type"])
        self.assertEqual("127.0.0.1", found["host"])
        self.assertEqual(3306, found["port"])
        self.assertEqual("assessment", found["database"])
        self.assertEqual("未连接", found["status"])

    def test_password_is_masked_in_list(self) -> None:
        created = self.admin_post("/api/admin/database", json=_config("CRUD-测试库-2"))
        self.created_database_ids.append(created["id"])
        found = self.find_database(id=created["id"])
        self.assertEqual("******", found["password"])

    def test_create_with_defaults_when_fields_omitted(self) -> None:
        created = self.admin_post("/api/admin/database", json={"name": "CRUD-测试库-仅名字"})
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        found = self.find_database(id=created["id"])
        self.assertEqual("MySQL", found["type"], "type 默认应为 MySQL")
        self.assertEqual("localhost", found["host"], "host 默认应为 localhost")
        self.assertEqual(3306, found["port"], "port 默认应为 3306")

    def test_update_changes_fields(self) -> None:
        created = self.admin_post("/api/admin/database", json=_config("CRUD-测试库-3"))
        self.created_database_ids.append(created["id"])

        updated = self.admin_put(
            f"/api/admin/database/{created['id']}",
            json={"name": "CRUD-测试库-3-改名", "port": 3307, "database": "other"},
        )
        self.assertSuccess(updated)
        self.assertEqual("数据库配置已更新", updated["message"])

        found = self.find_database(id=created["id"])
        self.assertEqual("CRUD-测试库-3-改名", found["name"])
        self.assertEqual(3307, found["port"])
        self.assertEqual("other", found["database"])

    def test_update_resets_status_to_not_connected(self) -> None:
        created = self.admin_post("/api/admin/database", json=_config("CRUD-测试库-4"))
        self.created_database_ids.append(created["id"])
        self.admin_put(f"/api/admin/database/{created['id']}", json={"name": "CRUD-测试库-4-v2"})
        found = self.find_database(id=created["id"])
        self.assertEqual("未连接", found["status"])

    def test_update_non_existent_config_returns_404(self) -> None:
        resp = self.admin_put("/api/admin/database/db_nope", json={"name": "x"}, expect=404)
        self.assertIsNone(resp)  # empty body

    def test_delete_removes_config(self) -> None:
        created = self.admin_post("/api/admin/database", json=_config("CRUD-测试库-5"))
        deleted = self.admin_delete(f"/api/admin/database/{created['id']}")
        self.assertSuccess(deleted)
        self.assertEqual("数据库配置已删除", deleted["message"])
        self.assertIsNone(self.find_database(id=created["id"]))

    def test_delete_is_idempotent(self) -> None:
        deleted = self.admin_delete("/api/admin/database/db_never_created")
        self.assertSuccess(deleted)

    def test_create_config_for_each_supported_type(self) -> None:
        for db_type in ("MySQL", "PostgreSQL", "SQL Server", "Oracle", "达梦数据库V8.1"):
            with self.subTest(db_type=db_type):
                created = self.admin_post(
                    "/api/admin/database",
                    json={"name": f"CRUD-类型-{db_type}", "type": db_type},
                )
                self.assertSuccess(created, f"创建 {db_type} 配置失败")
                self.created_database_ids.append(created["id"])


class RegisteredDataSourceTests(BaseServiceTest):
    """Verifies the 5 data sources requested by the user are actually configured."""

    EXPECTED = {
        "MySQL": "已连接",
        "PostgreSQL": "失败",
        "Oracle": "失败",
        "SQL Server": "失败",
        "达梦数据库V8.1": "失败",
    }

    def test_all_five_configured_types_present(self) -> None:
        dbs = self.list_databases()
        types = {db.get("type") for db in dbs}
        for db_type in self.EXPECTED:
            with self.subTest(db_type=db_type):
                self.assertIn(db_type, types, f"未找到类型为 {db_type} 的数据源配置")

    def test_mysql_connects_and_others_report_failure_status(self) -> None:
        for db_type, expected_status in self.EXPECTED.items():
            with self.subTest(db_type=db_type):
                entries = [db for db in self.list_databases() if db.get("type") == db_type]
                self.assertTrue(entries, f"类型 {db_type} 无配置")
                statuses = {db.get("status") for db in entries}
                if expected_status == "已连接":
                    self.assertIn("已连接", statuses)
                else:
                    # 没有可用实例/驱动时，状态必须是明确的失败，而不是无意义的已连接
                    self.assertNotIn("已连接", statuses)


if __name__ == "__main__":
    unittest.main()
