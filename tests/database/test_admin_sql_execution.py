"""Integration tests for POST /api/dataquery/execute.

Covers the read-only SQL safety gate in SqlExecutionService as exposed through
the dataquery endpoint, plus execution against the reachable MySQL config.
"""

from __future__ import annotations

import unittest

from base import BaseServiceTest, require_connected_database


class SqlExecutionValidationTests(BaseServiceTest):
    """The safety gate is pure string logic — it needs no live database."""

    def test_missing_database_id_rejected_with_400(self) -> None:
        payload = self.admin_post("/api/dataquery/execute", json={"sql": "SELECT 1"}, expect=400)
        self.assertApiError(payload, "databaseId")

    def test_missing_sql_rejected_with_400(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute", json={"databaseId": "db_x"}, expect=400
        )
        self.assertApiError(payload, "sql")

    def test_empty_sql_rejected(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute", json={"databaseId": "db_x", "sql": "   "}
        )
        self.assertApiError(payload, "SQL不能为空")

    def test_write_keywords_rejected_before_connection(self) -> None:
        # 不以 SELECT/WITH 开头的写语句，先被“只允许只读查询”的前缀校验拦截。
        for keyword, sql in (
            ("INSERT", "INSERT INTO t VALUES (1)"),
            ("UPDATE", "UPDATE t SET a=1"),
            ("DELETE", "DELETE FROM t"),
            ("DROP", "DROP TABLE t"),
            ("TRUNCATE", "TRUNCATE TABLE t"),
            ("ALTER", "ALTER TABLE t ADD c INT"),
            ("CREATE", "CREATE TABLE t (a INT)"),
            ("EXEC", "EXEC sp_who"),
        ):
            with self.subTest(keyword=keyword):
                payload = self.admin_post(
                    "/api/dataquery/execute",
                    json={"databaseId": "db_x", "sql": sql},
                )
                self.assertApiError(payload, "只允许执行SELECT或WITH")

    def test_embedded_write_keyword_in_select_rejected(self) -> None:
        # 以 SELECT 开头但内嵌写关键字的语句，命中关键字扫描。
        for keyword, sql in (
            ("EXECUTE", "SELECT * FROM t EXECUTE x"),
            ("CALL", "SELECT * FROM t CALL x"),
            ("GRANT", "SELECT * FROM t GRANT SELECT ON x"),
        ):
            with self.subTest(keyword=keyword):
                payload = self.admin_post(
                    "/api/dataquery/execute",
                    json={"databaseId": "db_x", "sql": sql},
                )
                self.assertApiError(payload, "禁止执行非只读操作", keyword)

    def test_multiple_statements_rejected(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": "db_x", "sql": "SELECT 1; SELECT 2"},
        )
        self.assertApiError(payload, "只允许一条")

    def test_sql_comments_rejected(self) -> None:
        for sql in ("SELECT 1 -- note", "SELECT 1 /* block */", "SELECT /*x*/ 1"):
            with self.subTest(sql=sql):
                payload = self.admin_post(
                    "/api/dataquery/execute", json={"databaseId": "db_x", "sql": sql}
                )
                self.assertApiError(payload, "只允许一条")

    def test_non_select_statement_rejected(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": "db_x", "sql": "SHOW TABLES"},
        )
        self.assertApiError(payload, "只允许执行SELECT或WITH")

    def test_high_risk_functions_rejected(self) -> None:
        for fn, sql in (
            ("SLEEP", "SELECT SLEEP(5)"),
            ("PG_SLEEP", "SELECT PG_SLEEP(5)"),
            ("BENCHMARK", "SELECT BENCHMARK(10, MD5(1))"),
            ("GET_LOCK", "SELECT GET_LOCK('x', 10)"),
            ("NEXTVAL", "SELECT NEXTVAL('seq')"),
        ):
            with self.subTest(fn=fn):
                payload = self.admin_post(
                    "/api/dataquery/execute", json={"databaseId": "db_x", "sql": sql}
                )
                self.assertApiError(payload, "禁止调用高风险数据库函数", fn)

    def test_load_file_rejected_as_keyword(self) -> None:
        # LOAD_FILE 同时出现在关键字清单中，关键字扫描先于函数扫描命中。
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": "db_x", "sql": "SELECT LOAD_FILE('/etc/passwd')"},
        )
        self.assertApiError(payload, "禁止执行非只读操作", "LOAD_FILE")

    def test_high_risk_packages_rejected(self) -> None:
        # 方法名避开关键字/函数清单，确保命中“高风险数据库包”扫描。
        for pkg, sql in (
            ("UTL_HTTP", "SELECT UTL_HTTP.REQUEST('http://x') FROM DUAL"),
            ("UTL_INADDR", "SELECT UTL_INADDR.GET_HOST_ADDRESS('x') FROM DUAL"),
            ("DBMS_LOCK", "SELECT DBMS_LOCK.REQUEST(1) FROM DUAL"),
            ("DBMS_PIPE", "SELECT DBMS_PIPE.PACKET_INFO() FROM DUAL"),
        ):
            with self.subTest(pkg=pkg):
                payload = self.admin_post(
                    "/api/dataquery/execute", json={"databaseId": "db_x", "sql": sql}
                )
                self.assertApiError(payload, "禁止调用高风险数据库包", pkg)

    def test_select_into_outfile_rejected(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": "db_x", "sql": "SELECT * INTO OUTFILE '/tmp/x' FROM t"},
        )
        self.assertApiError(payload, "禁止执行非只读操作")

    def test_for_update_rejected(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": "db_x", "sql": "SELECT * FROM t FOR UPDATE"},
        )
        self.assertApiError(payload, "禁止执行非只读操作")

    def test_unknown_database_id_returns_clean_error(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": "db_does_not_exist", "sql": "SELECT 1"},
        )
        self.assertApiError(payload, "数据库配置不存在")


@unittest.skipUnless(
    BaseServiceTest.any_connected_id(), "需要一个已连接的数据库配置（MySQL）"
)
class SqlExecutionAgainstMySqlTests(BaseServiceTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.db_id = require_connected_database(cls)

    def test_select_literal(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": self.db_id, "sql": "SELECT 1 AS one"},
        )
        self.assertSuccess(payload)
        self.assertEqual(["one"], payload["columns"])
        self.assertEqual(1, payload["rowCount"])
        self.assertEqual("1", payload["rows"][0]["one"])
        self.assertIn("ms", payload["executionTime"])

    def test_select_from_real_table(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={"databaseId": self.db_id, "sql": "SELECT id, name FROM ass_database_config LIMIT 5"},
        )
        self.assertSuccess(payload)
        self.assertIn("id", payload["columns"])
        self.assertIn("name", payload["columns"])
        self.assertTrue(payload["rowCount"] >= 1)

    def test_aggregate_query(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={
                "databaseId": self.db_id,
                "sql": "SELECT COUNT(*) AS total FROM ass_database_config",
            },
        )
        self.assertSuccess(payload)
        self.assertEqual(["total"], payload["columns"])
        self.assertRegex(payload["rows"][0]["total"], r"^\d+$")

    def test_with_cte_passes(self) -> None:
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={
                "databaseId": self.db_id,
                "sql": "WITH x AS (SELECT id FROM ass_database_config) SELECT COUNT(*) AS n FROM x",
            },
        )
        self.assertSuccess(payload)
        self.assertEqual("n", payload["columns"][0])

    def test_mysql_dialect_invalid_sql_rejected_server_side(self) -> None:
        # Oracle ROWNUM is invalid for a MySQL target and must be rejected.
        payload = self.admin_post(
            "/api/dataquery/execute",
            json={
                "databaseId": self.db_id,
                "sql": "SELECT * FROM ass_database_config WHERE ROWNUM <= 5",
            },
        )
        self.assertFalse(payload.get("success", True))

    def test_unreachable_database_reports_sql_execution_failure(self) -> None:
        # A configured-but-unreachable database must fail gracefully with a
        # clean error, never a 500 / stack trace.
        created = self.admin_post(
            "/api/admin/database",
            json={
                "name": "临时不可达库",
                "type": "PostgreSQL",
                "host": "127.0.0.1",
                "port": 59999,
                "database": "nope",
                "username": "u",
                "password": "p",
            },
        )
        self.assertSuccess(created)
        db_id = created["id"]
        self.created_database_ids.append(db_id)
        try:
            payload = self.admin_post(
                "/api/dataquery/execute",
                json={"databaseId": db_id, "sql": "SELECT 1"},
            )
            self.assertApiError(payload, "SQL执行失败")
        finally:
            self.admin_delete(f"/api/admin/database/{db_id}")


if __name__ == "__main__":
    unittest.main()
