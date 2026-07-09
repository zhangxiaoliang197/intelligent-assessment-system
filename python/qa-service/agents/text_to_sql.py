"""
Text-to-SQL 智能体
负责：根据问题 + 预筛选的表结构 → 生成正确的 SQL
（表筛选由 workflow 完成，此处只负责 SQL 生成）
"""
import json
import logging
import re
from .state import EvaluationState

logger = logging.getLogger("evaluation.text_to_sql")

TEXT_TO_SQL_SYSTEM_PROMPT = """你是SQL生成专家。根据表结构生成SELECT查询。

## 表结构
{table_context}

## 指标定义
{indicator_context}

## 问题
{question}

## 分析计划
{analysis_plan}

## 过滤条件
{filters}

## 规则
1. 只生成SELECT，禁止INSERT/UPDATE/DELETE/DROP/ALTER/CREATE
2. 正确使用表名和字段名
3. WHERE条件注意字段类型：时间用函数、数字直接比较、字符串加引号
4. 多表用JOIN
5. 聚合用GROUP BY
6. 不要添加LIMIT，返回全部数据

## 输出
```sql
-- 说明
SELECT ...
```
"""


async def run_text_to_sql(state: EvaluationState, llm_call_fn, max_retries: int = 1) -> EvaluationState:
    logger.info(f"Running text-to-sql for: {state.question[:100]}")

    if not state.database_id:
        state.add_step(99, "SQL生成", "skipped", "未选择数据源")
        state.generated_sql = ""
        state.sql_valid = False
        return state

    query_type = state.entities.get("query_type", "")
    if query_type == "general_analysis":
        state.add_step(99, "SQL生成", "skipped", "无需查询数据")
        state.generated_sql = ""
        state.sql_valid = False
        return state

    # workflow 已预取并筛选 table_schemas，直接使用
    table_count = len(state.table_schemas)

    # 构建表结构文本
    table_context_parts = []
    for schema in state.table_schemas:
        table_name = schema.get("tableName", "")
        desc = schema.get("description", "")
        ds_name = schema.get("datasetName", "")
        header = f"\n### 表: {table_name}"
        if ds_name and ds_name != table_name:
            header += f" ({ds_name})"
        if desc:
            header += f"\n描述: {desc}"
        table_context_parts.append(header + "\n列:")
        for col in schema.get("columns", []):
            parts = [f"  - {col['columnName']} ({col['dataType']})"]
            if col.get("isPrimaryKey"):
                parts.append("[主键]")
            if col.get("comment"):
                parts.append(f"-- {col['comment']}")
            if col.get("businessMeaning"):
                parts.append(f"[含义: {col['businessMeaning']}]")
            table_context_parts.append(" ".join(parts))
    table_context = "\n".join(table_context_parts) if table_context_parts else "无可用表"

    # 构建指标描述
    indicator_context_parts = []
    for ind in (state.indicator_defs or []):
        ic = f"\n### {ind.get('name', '')}"
        if ind.get("formula"):
            ic += f"\n  公式: {ind['formula']}"
        if ind.get("description"):
            ic += f"\n  说明: {ind['description']}"
        indicator_context_parts.append(ic)
    indicator_context = "\n".join(indicator_context_parts) if indicator_context_parts else "无可用指标"

    # 生成 SQL（重试机制）
    sql = ""
    last_error = None
    attempts = 0

    while attempts <= max_retries:
        attempt_label = "" if attempts == 0 else f" (第{attempts+1}次)"
        step_id = 5 if attempts == 0 else 5.2

        if attempts > 0 and last_error:
            state.add_step(step_id, f"SQL重试{attempt_label}", "in_progress",
                          detail=f"上次错误: {last_error[:120]}")

        state.add_step(5.1, f"生成SQL{attempt_label}", "in_progress",
                      detail=f"正在调用大模型生成SQL...（{table_count} 张表）")

        system_prompt = TEXT_TO_SQL_SYSTEM_PROMPT.format(
            table_context=table_context,
            indicator_context=indicator_context,
            question=state.question,
            analysis_plan=state.analysis_plan,
            filters=state.entities.get("filters", "无")
        )

        try:
            response = await llm_call_fn(system_prompt,
                                        f"请根据以上 {table_count} 张表的结构生成SQL查询。")
            sql = _extract_sql(response)

            if sql:
                is_valid, error_msg = _validate_sql(sql)
                if is_valid:
                    state.generated_sql = _clean_sql(sql)
                    state.sql_valid = True
                    state.add_step(5.1, f"生成SQL{attempt_label}", "completed",
                                   detail=f"SQL生成成功 ({len(sql)} 字符)",
                                   thinking=(
                                       f"【模型输出】\n{response[:500]}\n\n"
                                       f"【最终SQL】\n{sql[:600]}" +
                                       (f"\n... 共 {len(sql)} 字符" if len(sql) > 600 else "")
                                   ))
                    logger.info(f"SQL generated after {attempts + 1} attempts")
                    return state
                else:
                    last_error = error_msg
                    state.add_step(5.1, f"生成SQL{attempt_label}", "in_progress",
                                   detail=f"SQL校验失败: {error_msg[:120]}")
                    logger.warning(f"SQL validation failed: {error_msg}")
            else:
                no_sql = _extract_no_sql(response)
                if no_sql:
                    state.add_step(5.1, "生成SQL", "skipped",
                                   detail=f"模型判断无需SQL: {no_sql.get('reason', '')[:120]}")
                    state.generated_sql = ""
                    state.sql_valid = False
                    return state
                last_error = "模型未返回有效SQL"
                state.add_step(5.1, "生成SQL", "in_progress",
                               detail="未提取到SQL，准备重试",
                               thinking=f"模型原始响应:\n{response[:500]}")

        except Exception as e:
            last_error = str(e)[:300]
            logger.error(f"Text-to-SQL attempt {attempts + 1} failed: {e}")
            state.add_step(5.1, "生成SQL", "error",
                          detail=f"调用失败: {last_error[:120]}")
            if "timeout" in last_error.lower() or "timed out" in last_error.lower():
                # 超时不重试
                break

        attempts += 1

    state.add_step(99, "SQL生成", "error",
                  detail=f"失败: {last_error[:200]}" if last_error else "失败: 未知错误")
    state.generated_sql = ""
    state.sql_valid = False
    return state


def _extract_sql(response_text: str) -> str:
    text = response_text.strip()
    if "```sql" in text:
        start = text.index("```sql") + 6
        end = text.index("```", start) if "```" in text[start:] else len(text)
        return text[start:end].strip()
    if "```" in text:
        lines = text.split("\n")
        in_block, sql_lines = False, []
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                sql_lines.append(line)
        if sql_lines:
            return "\n".join(sql_lines).strip()
    select_match = re.search(r'(SELECT\s+.+?(?:;|$))', text, re.IGNORECASE | re.DOTALL)
    if select_match:
        return select_match.group(1).strip().rstrip(";")
    return ""


def _extract_no_sql(response_text: str) -> dict:
    text = response_text.strip()
    try:
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        data = json.loads(text) if text.startswith("{") else None
        if data and data.get("no_sql"):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def _clean_sql(sql: str) -> str:
    """去除 SQL 前的注释行和空白，返回以 SELECT 开头的纯净 SQL"""
    lines = sql.strip().split("\n")
    result = []
    started = False
    for line in lines:
        stripped = line.strip()
        # 跳过前置的注释行和空行
        if not started and (not stripped or stripped.startswith("--") or stripped.startswith("#")):
            continue
        started = True
        result.append(line)
    return "\n".join(result).strip()


def _validate_sql(sql: str) -> tuple:
    cleaned = _clean_sql(sql)
    sql_upper = cleaned.upper()
    dangerous = ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE", "EXEC", "EXECUTE"]
    for keyword in dangerous:
        if re.search(r'\b' + keyword + r'\b', sql_upper):
            return False, f"SQL包含禁止关键字: {keyword}"
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, f"SQL必须以SELECT或WITH开头（当前以 '{cleaned[:30]}...' 开头）"
    if cleaned.count("(") != cleaned.count(")"):
        return False, "括号不匹配"
    return True, ""
