"""Regression tests for database-aware SQL generation."""

from __future__ import annotations

import os
import sys
import unittest


SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_ROOT not in sys.path:
    sys.path.insert(0, SERVICE_ROOT)

from agents.sql_dialect import normalize_database_dialect  # noqa: E402
from agents.state import EvaluationState  # noqa: E402
from agents.text_to_sql import _validate_sql, run_text_to_sql  # noqa: E402
from agents.langgraph_workflow import route_by_intent  # noqa: E402


class SqlDialectValidationTests(unittest.TestCase):
    def test_normalizes_configured_and_jdbc_product_names(self) -> None:
        self.assertEqual("oracle", normalize_database_dialect("driver_03", "Oracle"))
        self.assertEqual("mysql", normalize_database_dialect("MySQL", "MySQL 8"))
        self.assertEqual("postgresql", normalize_database_dialect("PostgreSQL", ""))
        self.assertEqual("sqlserver", normalize_database_dialect("SQL Server", ""))
        self.assertEqual("dameng", normalize_database_dialect("达梦数据库V8.1", ""))
        self.assertEqual("dameng", normalize_database_dialect("driver_04", "DM DBMS"))

    def test_rejects_cross_database_syntax(self) -> None:
        valid, message = _validate_sql(
            "SELECT * FROM TASK_LOG LIMIT 10", "oracle"
        )
        self.assertFalse(valid)
        self.assertIn("Oracle 不支持 LIMIT", message)

        valid, message = _validate_sql(
            "SELECT * FROM TASK_LOG WHERE ROWNUM <= 10", "mysql"
        )
        self.assertFalse(valid)
        self.assertIn("MySQL 不支持 Oracle ROWNUM", message)

        self.assertTrue(
            _validate_sql(
                "SELECT NVL(SCORE, 0) FROM TASK_LOG WHERE ROWNUM <= 10",
                "oracle",
            )[0]
        )
        self.assertTrue(
            _validate_sql("SELECT IFNULL(SCORE, 0) FROM TASK_LOG LIMIT 10", "mysql")[0]
        )

    def test_every_database_analysis_intent_uses_dynamic_sql_pipeline(self) -> None:
        for query_type in ("data_query", "combat_effectiveness", "air_superiority"):
            with self.subTest(query_type=query_type):
                self.assertEqual(
                    "data_explore",
                    route_by_intent({
                        "query_type": query_type,
                        "database_id": "db-current",
                    }),
                )
        self.assertEqual(
            "simple_analysis",
            route_by_intent({
                "query_type": "combat_effectiveness",
                "database_id": "",
            }),
        )


class SqlDialectPromptTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _state(database_type: str, product_name: str) -> EvaluationState:
        state = EvaluationState(question="查询前十条任务记录", database_id="db-current")
        state.table_schemas = [{
            "tableName": "TASK_LOG",
            "columns": [
                {"columnName": "ID", "dataType": "NUMBER"},
                {"columnName": "SCORE", "dataType": "NUMBER"},
            ],
            "databaseType": database_type,
            "databaseProductName": product_name,
            "databaseProductVersion": "19c" if product_name == "Oracle" else "8.0",
        }]
        state.analysis_plan = "查询当前表中的前十条记录"
        state.entities = {"query_type": "data_query", "filters": "无"}
        return state

    async def test_oracle_prompt_and_implicit_dialect_correction(self) -> None:
        prompts = []
        responses = iter([
            "```sql\nSELECT * FROM TASK_LOG LIMIT 10\n```",
            "```sql\nSELECT * FROM TASK_LOG WHERE ROWNUM <= 10\n```",
        ])

        async def llm(system_prompt: str, _user_message: str) -> str:
            prompts.append(system_prompt)
            return next(responses)

        state = await run_text_to_sql(
            self._state("driver_03", "Oracle"), llm, max_retries=0
        )

        self.assertTrue(state.sql_valid)
        self.assertEqual("oracle", state.sql_dialect)
        self.assertEqual("SELECT * FROM TASK_LOG WHERE ROWNUM <= 10", state.generated_sql)
        self.assertEqual(2, len(prompts))
        self.assertIn("必须使用 Oracle SQL 语法", prompts[0])
        self.assertIn("Oracle 不支持 LIMIT", prompts[1])

    async def test_mysql_prompt_uses_mysql_rules(self) -> None:
        captured = {}

        async def llm(system_prompt: str, _user_message: str) -> str:
            captured["system"] = system_prompt
            return "```sql\nSELECT IFNULL(SCORE, 0) FROM TASK_LOG LIMIT 10\n```"

        state = await run_text_to_sql(
            self._state("MySQL", "MySQL"), llm, max_retries=0
        )

        self.assertTrue(state.sql_valid)
        self.assertEqual("mysql", state.sql_dialect)
        self.assertIn("必须使用 MySQL 语法", captured["system"])
        self.assertIn("SELECT IFNULL", state.generated_sql)


if __name__ == "__main__":
    unittest.main()
