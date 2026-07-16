import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.state import EvaluationState
from agents.text_to_sql import _clean_sql, _extract_sql, _validate_sql, run_text_to_sql


class ReadOnlySqlValidationTest(unittest.TestCase):
    def assertAllowed(self, sql):
        valid, error = _validate_sql(sql)
        self.assertTrue(valid, error)

    def assertBlocked(self, sql):
        valid, _error = _validate_sql(sql)
        self.assertFalse(valid, sql)

    def test_allows_common_read_only_dialects(self):
        allowed = [
            "SELECT id, name FROM public.orders WHERE note = 'DROP; -- 仅是文本';",
            'SELECT "update", [delete], `create` FROM mixed_identifiers',
            "WITH RECURSIVE tree AS (SELECT id FROM nodes UNION ALL SELECT n.id FROM nodes n JOIN tree t ON n.parent_id=t.id) SELECT * FROM tree",
            "SELECT payload #>> '{user,name}' FROM events",
            "SELECT q'[text; DROP isn''t SQL here]' AS content FROM dual",
            "SELECT $$semicolon; CALL hidden()$$ AS content",
            "SELECT /*+ INDEX(orders idx_orders) */ id FROM orders",
            "-- leading explanation\nSELECT COUNT(*) FROM orders",
        ]
        for sql in allowed:
            with self.subTest(sql=sql):
                self.assertAllowed(sql)

    def test_blocks_multiple_statements_and_procedures(self):
        blocked = [
            "SELECT 1; CALL dangerous_proc()",
            "SELECT 1;;",
            "SELECT 1; -- hidden trailing content",
            "WITH data AS (SELECT 1) SELECT * FROM data; DELETE FROM users",
            "WITH data AS (SELECT 1) VALUES (1)",
            "CALL dangerous_proc()",
            "EXEC xp_cmdshell 'whoami'",
        ]
        for sql in blocked:
            with self.subTest(sql=sql):
                self.assertBlocked(sql)

    def test_blocks_select_side_effects_and_locks(self):
        blocked = [
            "SELECT * FROM users INTO OUTFILE '/tmp/users.csv'",
            "SELECT * INTO copied_users FROM users",
            "SELECT LOAD_FILE('/etc/passwd')",
            "SELECT nextval('sequence_name')",
            "SELECT pg_advisory_lock(42)",
            "SELECT get_lock('name', 30)",
            "SELECT pg_sleep(30)",
            "SELECT NEXT VALUE FOR order_sequence",
            "SELECT * FROM users FOR UPDATE",
            "SELECT * FROM users FOR SHARE",
            "SELECT @value := 1",
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT set_config('search_path', 'public', false)",
            "SELECT * FROM dblink('remote', 'DELETE FROM users RETURNING *') AS t(id int)",
        ]
        for sql in blocked:
            with self.subTest(sql=sql):
                self.assertBlocked(sql)

    def test_blocks_data_modifying_cte_and_executable_comments(self):
        blocked = [
            "WITH removed AS (DELETE FROM users RETURNING *) SELECT * FROM removed",
            "SELECT 1 /*!50000 INTO OUTFILE '/tmp/value' */",
            "SELECT 1 /*M! INTO OUTFILE '/tmp/value' */",
            "SEL/**/ECT 1",
        ]
        for sql in blocked:
            with self.subTest(sql=sql):
                self.assertBlocked(sql)

    def test_rejects_malformed_or_oversized_sql(self):
        blocked = [
            "",
            "SELECT ('unterminated'",
            "SELECT 'unterminated",
            "SELECT /* unterminated",
            "SELECT \x00 FROM users",
            "SELECT " + "x" * 100_001,
        ]
        for sql in blocked:
            with self.subTest(sql=sql[:80]):
                self.assertBlocked(sql)

    def test_extraction_preserves_statement_boundary_until_validation(self):
        sql = _extract_sql("```sql\nSELECT 1; CALL dangerous_proc()\n```")
        self.assertEqual(sql, "SELECT 1; CALL dangerous_proc()")
        self.assertBlocked(sql)

        valid_sql = _extract_sql("```sql\nSELECT 1;\n```")
        self.assertAllowed(valid_sql)
        self.assertEqual(_clean_sql(valid_sql), "SELECT 1")


class TextToSqlRetryFeedbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_prompt_contains_previous_sql_and_validation_error(self):
        prompts = []

        async def fake_llm(system_prompt, user_prompt):
            prompts.append((system_prompt, user_prompt))
            if len(prompts) == 1:
                return "```sql\nSELECT * FROM orders; CALL dangerous_proc()\n```"
            return "```sql\nSELECT * FROM orders\n```"

        state = EvaluationState(
            question="查询订单",
            database_id="database-one",
            table_schemas=[{
                "tableName": "orders",
                "columns": [{"columnName": "id", "dataType": "integer"}],
            }],
        )
        result = await run_text_to_sql(state, fake_llm, max_retries=1)

        self.assertTrue(result.sql_valid)
        self.assertEqual(result.generated_sql, "SELECT * FROM orders")
        self.assertEqual(len(prompts), 2)
        retry_system, retry_user = prompts[1]
        first_system, _first_user = prompts[0]
        self.assertIn("生产环境结果集上限为1000行", first_system)
        self.assertIn("禁止请求或承诺返回无限/全部明细数据", first_system)
        self.assertIn("上次生成结果校验失败", retry_system)
        self.assertIn("SELECT * FROM orders; CALL dangerous_proc()", retry_system)
        self.assertIn("只允许执行一条SQL语句", retry_system)
        self.assertIn("纠错重试", retry_user)


if __name__ == "__main__":
    unittest.main()
