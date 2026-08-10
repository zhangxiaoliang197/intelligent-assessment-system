"""Edge-case and robustness tests for the data-source feature."""

from __future__ import annotations

import unittest

from base import BaseServiceTest


class DatabaseConfigEdgeCasesTests(BaseServiceTest):
    def test_empty_password_accepted(self) -> None:
        # 列表接口恒将密码脱敏为 ******，此处仅验证空密码可正常创建与回读。
        created = self.admin_post(
            "/api/admin/database",
            json={"name": "边界-空密码", "type": "PostgreSQL", "password": ""},
        )
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        found = self.find_database(id=created["id"])
        self.assertEqual("PostgreSQL", found["type"])
        self.assertEqual("******", found["password"])

    def test_unicode_name_roundtrip(self) -> None:
        name = "边界-中文数据库配置 名字_#测试"
        created = self.admin_post("/api/admin/database", json={"name": name})
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        found = self.find_database(id=created["id"])
        self.assertEqual(name, found["name"])

    def test_html_special_chars_stored_as_is(self) -> None:
        name = '边界-<script>alert(1)</script> & "quoted"'
        created = self.admin_post("/api/admin/database", json={"name": name})
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        found = self.find_database(id=created["id"])
        self.assertEqual(name, found["name"])

    def test_zero_port_accepted_and_fails_cleanly(self) -> None:
        created = self.admin_post(
            "/api/admin/database", json={"name": "边界-端口0", "port": 0}
        )
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        payload = self.admin_post(f"/api/admin/database/{created['id']}/test")
        self.assertFalse(payload.get("success", True))

    def test_unknown_type_connection_test_graceful(self) -> None:
        created = self.admin_post(
            "/api/admin/database",
            json={"name": "边界-未知类型", "type": "NotADatabase"},
        )
        self.assertSuccess(created)
        self.created_database_ids.append(created["id"])
        payload = self.admin_post(f"/api/admin/database/{created['id']}/test")
        self.assertFalse(payload.get("success", True))
        self.assertIn("驱动", payload.get("message", ""))

    def test_dataquery_test_connection_unknown_type_graceful(self) -> None:
        created = self.admin_post(
            "/api/admin/database",
            json={"name": "边界-未知类型2", "type": "NotADatabase"},
        )
        self.created_database_ids.append(created["id"])
        payload = self.admin_post(
            "/api/dataquery/test-connection", json={"databaseId": created["id"]}
        )
        self.assertFalse(payload.get("success", True))
        self.assertIn("驱动", payload.get("message", ""))

    def test_create_with_blank_name_does_not_crash(self) -> None:
        # 服务端不做名称校验，但必须返回可解析的 JSON，而不是 500 堆栈
        resp = self.admin_post("/api/admin/database", json={"name": ""})
        if isinstance(resp, dict) and resp.get("success"):
            self.created_database_ids.append(resp["id"])

    def test_multiple_creates_have_distinct_ids(self) -> None:
        ids = set()
        for i in range(3):
            created = self.admin_post("/api/admin/database", json={"name": f"边界-去重-{i}"})
            self.assertSuccess(created)
            ids.add(created["id"])
            self.created_database_ids.append(created["id"])
        self.assertEqual(3, len(ids))


if __name__ == "__main__":
    unittest.main()
