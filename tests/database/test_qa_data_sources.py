"""Integration tests for the qa-service data-source proxy layer.

These hit the running qa-service, which in turn proxies to admin-service —
so they exercise the exact chain the frontend uses.
"""

from __future__ import annotations

import unittest

from base import BaseServiceTest

EXPECTED_TYPES = {"MySQL", "PostgreSQL", "Oracle", "SQL Server", "达梦数据库V8.1"}


class QaHealthTests(BaseServiceTest):
    def test_health_reports_healthy_and_skill_catalog(self) -> None:
        payload = self.qa_get("/health")
        self.assertEqual("healthy", payload["status"])
        self.assertTrue(payload["skillCatalog"]["ready"])
        self.assertEqual(30, payload["skillCatalog"]["skillCount"])


class QaDataSourcesTests(BaseServiceTest):
    def test_data_sources_returns_mapped_sources(self) -> None:
        payload = self.qa_get("/evaluation/data-sources")
        self.assertSuccess(payload)
        self.assertIn("dataSources", payload)
        self.assertGreaterEqual(len(payload["dataSources"]), 5)

    def test_all_five_types_present(self) -> None:
        payload = self.qa_get("/evaluation/data-sources")
        types = {ds["type"] for ds in payload["dataSources"]}
        for expected in EXPECTED_TYPES:
            self.assertIn(expected, types, f"dataSources 缺少 {expected}")

    def test_each_source_has_expected_shape(self) -> None:
        payload = self.qa_get("/evaluation/data-sources")
        for ds in payload["dataSources"]:
            for key in ("id", "name", "type", "host", "port", "dbName", "status"):
                self.assertIn(key, ds, f"数据源对象缺少 {key}")

    def test_mysql_is_available_and_others_are_not(self) -> None:
        payload = self.qa_get("/evaluation/data-sources")
        status_by_type = {ds["type"]: ds["status"] for ds in payload["dataSources"]}
        self.assertEqual("available", status_by_type.get("MySQL"))
        for db_type in ("PostgreSQL", "Oracle", "SQL Server", "达梦数据库V8.1"):
            self.assertNotEqual("available", status_by_type.get(db_type), f"{db_type} 不应可用")

    def test_datasets_for_connected_mysql(self) -> None:
        mysql = self.find_database(type="MySQL")
        if not mysql:
            self.skipTest("没有 MySQL 数据源")
        db_id = self.connected_mysql_id()
        if not db_id:
            self.skipTest("MySQL 未连接")
        payload = self.qa_get(f"/evaluation/data-sources/{db_id}/datasets")
        self.assertSuccess(payload)
        self.assertIn("datasets", payload)
        for ds in payload["datasets"]:
            self.assertTrue(ds.get("id"))
            self.assertTrue(ds.get("tableName"))


class QaSkillsCatalogTests(BaseServiceTest):
    def test_skills_catalog_counts(self) -> None:
        payload = self.qa_get("/evaluation/skills")
        self.assertSuccess(payload)
        self.assertEqual(30, payload["builtInTotal"])
        self.assertGreaterEqual(payload["total"], 30)
        self.assertIn("skills", payload)

    def test_skills_with_data_source_context(self) -> None:
        db_id = self.connected_mysql_id()
        if not db_id:
            self.skipTest("MySQL 未连接")
        payload = self.qa_get(f"/evaluation/skills?dataSourceId={db_id}")
        self.assertSuccess(payload)
        for skill in payload["skills"]:
            self.assertIn("stepCount", skill)


if __name__ == "__main__":
    unittest.main()
