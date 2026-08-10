"""Offline unit tests for the 5-dialect SQL normalization / validation layer.

These tests need only the qa-service sources on sys.path (handled by
run_tests.py) and make no network calls. They pin the dialect behaviour the
whole data-source feature relies on.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from agents.sql_dialect import (
    database_profile_from_schemas,
    normalize_database_dialect,
    sql_dialect_prompt,
)
from agents.text_to_sql import _validate_sql, _validate_sql_dialect
from agents.langgraph_workflow import route_by_intent


class NormalizeDialectTests(unittest.TestCase):
    """Mapping from configured driver names / JDBC product names to a dialect."""

    def test_configured_driver_names_map_to_stable_dialects(self) -> None:
        cases = [
            ("MySQL", "", "mysql"),
            ("PostgreSQL", "", "postgresql"),
            ("SQL Server", "", "sqlserver"),
            ("Oracle", "", "oracle"),
            ("达梦数据库V8.1", "", "dameng"),
            ("MongoDB", "", "ansi"),  # unsupported type degrades to ANSI
        ]
        for db_type, product, expected in cases:
            with self.subTest(db_type=db_type):
                self.assertEqual(expected, normalize_database_dialect(db_type, product))

    def test_jdbc_product_names_map_to_dialects(self) -> None:
        cases = [
            ("", "MySQL 8.0.36", "mysql"),
            ("", "PostgreSQL 16.2", "postgresql"),
            ("", "Microsoft SQL Server 2022", "sqlserver"),
            ("", "Oracle Database 19c", "oracle"),
            ("", "DM DBMS V8", "dameng"),
            ("", "H2 2.2.224", "h2"),
            ("", "SQLite 3.45", "sqlite"),
        ]
        for db_type, product, expected in cases:
            with self.subTest(product=product):
                self.assertEqual(expected, normalize_database_dialect(db_type, product))

    def test_dameng_variants_all_normalize_to_dameng(self) -> None:
        cases = [
            ("达梦数据库V8.1", ""),
            ("达梦数据库 V8.1", ""),
            ("driver_04", "DM DBMS"),
            ("driver_04", "DMDBMS V8"),
            ("DM", "达梦数据库"),
        ]
        for db_type, product in cases:
            with self.subTest(db_type=db_type, product=product):
                self.assertEqual("dameng", normalize_database_dialect(db_type, product))

    def test_sqlserver_variants_normalize_to_sqlserver(self) -> None:
        for name in ("SQL Server", "sqlserver", "Microsoft SQL Server", "MSSQL"):
            with self.subTest(name=name):
                self.assertEqual("sqlserver", normalize_database_dialect(name, ""))

    def test_case_and_whitespace_insensitive(self) -> None:
        self.assertEqual("mysql", normalize_database_dialect("mysql", ""))
        self.assertEqual("mysql", normalize_database_dialect("MY SQL", "MySQL 8"))
        self.assertEqual("postgresql", normalize_database_dialect("Postgres", ""))
        self.assertEqual("postgresql", normalize_database_dialect("", "postgres ql"))

    def test_mariadb_normalizes_to_mysql(self) -> None:
        self.assertEqual("mysql", normalize_database_dialect("MariaDB", ""))
        self.assertEqual("mysql", normalize_database_dialect("", "MariaDB 10.6"))

    def test_empty_inputs_fall_back_to_ansi(self) -> None:
        self.assertEqual("ansi", normalize_database_dialect("", ""))
        self.assertEqual("ansi", normalize_database_dialect(None, None))


class ProfileFromSchemasTests(unittest.TestCase):
    def test_profile_built_from_schema_metadata(self) -> None:
        schemas = [
            {
                "tableName": "TASK_LOG",
                "databaseType": "Oracle",
                "databaseProductName": "Oracle Database 19c",
                "databaseProductVersion": "19c",
            }
        ]
        profile = database_profile_from_schemas(schemas)
        self.assertEqual("oracle", profile["dialect"])
        self.assertEqual("Oracle", profile["databaseType"])
        self.assertEqual("Oracle Database 19c", profile["databaseProductName"])
        self.assertEqual("19c", profile["databaseProductVersion"])

    def test_missing_metadata_yields_ansi(self) -> None:
        profile = database_profile_from_schemas([])
        self.assertEqual("ansi", profile["dialect"])

    def test_explicit_args_override_schema_values(self) -> None:
        schemas = [{"databaseType": "PostgreSQL", "databaseProductName": "PostgreSQL 16"}]
        profile = database_profile_from_schemas(
            schemas, database_type="MySQL", database_product_name="MySQL 8"
        )
        self.assertEqual("mysql", profile["dialect"])


class DialectPromptTests(unittest.TestCase):
    def test_prompt_heading_names_the_target_database(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "达梦数据库V8.1", "databaseProductName": "DM DBMS"})
        self.assertIn("SQL 方言：dameng", prompt)

    def test_mysql_rules_mention_mysql_functions(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "MySQL", "databaseProductName": "MySQL 8"})
        self.assertIn("必须使用 MySQL 语法", prompt)
        self.assertIn("STR_TO_DATE", prompt)
        self.assertIn("GROUP_CONCAT", prompt)

    def test_oracle_rules_mention_oracle_functions(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "Oracle", "databaseProductName": "Oracle 19c"})
        self.assertIn("必须使用 Oracle SQL 语法", prompt)
        self.assertIn("LISTAGG", prompt)
        self.assertIn("表别名不能写 AS", prompt)

    def test_postgresql_rules_mention_string_agg(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "PostgreSQL", "databaseProductName": "PostgreSQL 16"})
        self.assertIn("必须使用 PostgreSQL 语法", prompt)
        self.assertIn("STRING_AGG", prompt)

    def test_sqlserver_rules_mention_top(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "SQL Server", "databaseProductName": "SQL Server 2022"})
        self.assertIn("必须使用 SQL Server T-SQL", prompt)
        self.assertIn("TOP", prompt)

    def test_dameng_rules_prefer_oracle_compat(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "达梦数据库V8.1", "databaseProductName": ""})
        self.assertIn("达梦数据库 SQL 方言", prompt)
        self.assertIn("NVL/COALESCE", prompt)

    def test_unknown_database_uses_ansi_rules(self) -> None:
        prompt = sql_dialect_prompt({"databaseType": "UnknownDB", "databaseProductName": ""})
        self.assertIn("SQL 方言：ansi", prompt)
        self.assertIn("保守的 ANSI SQL", prompt)


class SqlDialectValidationMatrixTests(unittest.TestCase):
    """Cross-dialect SQL rejection matrix for all five target dialects."""

    VALID_PER_DIALECT = {
        "oracle": ["SELECT NVL(SCORE, 0) AS S FROM TASK_LOG WHERE ROWNUM <= 10"],
        "mysql": ["SELECT IFNULL(SCORE, 0) FROM TASK_LOG LIMIT 10"],
        "postgresql": ["SELECT COALESCE(SCORE, 0) FROM TASK_LOG LIMIT 10"],
        "sqlserver": ["SELECT TOP 10 ISNULL(SCORE, 0) FROM TASK_LOG"],
        "dameng": ["SELECT NVL(SCORE, 0) AS S FROM TASK_LOG WHERE ROWNUM <= 10"],
    }

    INVALID_PER_DIALECT = {
        "oracle": [
            ("SELECT * FROM TASK_LOG LIMIT 10", "LIMIT"),
            ("SELECT * FROM `TASK_LOG`", "反引号"),
            ("SELECT IFNULL(SCORE, 0) FROM TASK_LOG", "MySQL 函数"),
            ("SELECT * FROM TASK_LOG AS T", "AS"),
        ],
        "mysql": [
            ("SELECT * FROM TASK_LOG WHERE ROWNUM <= 10", "ROWNUM"),
            ("SELECT NVL(SCORE, 0) FROM TASK_LOG", "Oracle 函数"),
            ("SELECT * FROM TASK_LOG FETCH FIRST 10 ROWS ONLY", "FETCH"),
            ("SELECT * FROM TASK_LOG WHERE ID::int = 1", "类型转换"),
        ],
        "postgresql": [
            ("SELECT * FROM `TASK_LOG`", "反引号"),
            ("SELECT * FROM TASK_LOG WHERE ROWNUM <= 10", "ROWNUM"),
            ("SELECT TOP 10 * FROM TASK_LOG", "TOP"),
            ("SELECT IFNULL(SCORE, 0) FROM TASK_LOG", "厂商专用函数"),
        ],
        "sqlserver": [
            ("SELECT * FROM TASK_LOG LIMIT 10", "LIMIT"),
            ("SELECT * FROM TASK_LOG WHERE ROWNUM <= 10", "ROWNUM"),
            ("SELECT NVL(SCORE, 0) FROM TASK_LOG", "厂商专用函数"),
        ],
        "dameng": [
            ("SELECT * FROM TASK_LOG LIMIT 10", "LIMIT"),
            ("SELECT * FROM `TASK_LOG`", "反引号"),
            ("SELECT IFNULL(SCORE, 0) FROM TASK_LOG", "MySQL 函数"),
        ],
    }

    def test_each_dialect_accepts_its_own_syntax(self) -> None:
        for dialect, sqls in self.VALID_PER_DIALECT.items():
            for sql in sqls:
                with self.subTest(dialect=dialect, sql=sql):
                    valid, message = _validate_sql(sql, dialect)
                    self.assertTrue(valid, f"{dialect} should accept {sql!r}: {message}")

    def test_each_dialect_rejects_cross_dialect_syntax(self) -> None:
        for dialect, cases in self.INVALID_PER_DIALECT.items():
            for sql, needle in cases:
                with self.subTest(dialect=dialect, sql=sql):
                    valid, message = _validate_sql(sql, dialect)
                    self.assertFalse(valid, f"{dialect} should reject {sql!r}")
                    self.assertIn(needle, message, f"{message!r} missing {needle!r}")

    def test_rejection_message_prefixes_dialect(self) -> None:
        valid, message = _validate_sql("SELECT * FROM T LIMIT 5", "oracle")
        self.assertFalse(valid)
        self.assertTrue(message.startswith("oracle 方言不兼容"), message)

    def test_valid_dialect_sql_runs_clean(self) -> None:
        for sql in ("SELECT 1", "SELECT * FROM T", "WITH c AS (SELECT 1) SELECT * FROM c"):
            with self.subTest(sql=sql):
                self.assertTrue(_validate_sql(sql, "mysql")[0])


class SqlSafetyValidationTests(unittest.TestCase):
    """The dangerous-keyword/function gate shared by every dialect."""

    def test_dangerous_write_keywords_rejected(self) -> None:
        for sql in (
            "INSERT INTO T VALUES (1)",
            "UPDATE T SET A = 1",
            "DELETE FROM T",
            "DROP TABLE T",
            "TRUNCATE TABLE T",
            "ALTER TABLE T ADD C INT",
            "CREATE TABLE T (A INT)",
            "EXEC sp_who",
            "EXECUTE x",
            "MERGE INTO T USING S",
        ):
            with self.subTest(sql=sql):
                valid, message = _validate_sql(sql, "mysql")
                self.assertFalse(valid, f"{sql!r} should be rejected")
                self.assertIn("禁止", message)

    def test_dangerous_functions_rejected(self) -> None:
        for sql in (
            "SELECT SLEEP(5)",
            "SELECT PG_SLEEP(5)",
            "SELECT BENCHMARK(10, MD5(1))",
            "SELECT LOAD_FILE('/etc/passwd')",
            "SELECT GET_LOCK('x', 1)",
            "SELECT UTL_HTTP.REQUEST('http://x') FROM DUAL",
            "SELECT DBMS_LOCK.SLEEP(5) FROM DUAL",
            "SELECT SYS_EVAL('x') FROM DUAL",
            "SELECT NEXTVAL('seq')",
        ):
            with self.subTest(sql=sql):
                valid, message = _validate_sql(sql, "mysql")
                self.assertFalse(valid, f"{sql!r} should be rejected")
                self.assertIn("禁止", message)

    def test_benign_select_passes_safety_gate(self) -> None:
        for sql in (
            "SELECT * FROM TASK_LOG",
            "SELECT COUNT(*) FROM TASK_LOG WHERE SCORE > 90",
            "SELECT COALESCE(SCORE, 0) FROM TASK_LOG",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(_validate_sql(sql, "mysql")[0])

    def test_dialect_scanner_is_case_insensitive(self) -> None:
        valid, message = _validate_sql("SELECT * FROM T limit 5", "oracle")
        self.assertFalse(valid)
        self.assertIn("LIMIT", message)
        valid, message = _validate_sql("SELECT * FROM T WHERE rownum <= 5", "mysql")
        self.assertFalse(valid)
        self.assertIn("ROWNUM", message)


class RouteByIntentTests(unittest.TestCase):
    def test_data_analysis_intents_use_dynamic_sql_pipeline(self) -> None:
        for query_type in ("data_query", "combat_effectiveness", "air_superiority"):
            with self.subTest(query_type=query_type):
                self.assertEqual(
                    "data_explore",
                    route_by_intent({"query_type": query_type, "database_id": "db-x"}),
                )

    def test_without_database_falls_back_to_simple_analysis(self) -> None:
        self.assertEqual(
            "simple_analysis",
            route_by_intent({"query_type": "combat_effectiveness", "database_id": ""}),
        )


if __name__ == "__main__":
    unittest.main()
