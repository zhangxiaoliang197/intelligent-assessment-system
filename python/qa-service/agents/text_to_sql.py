"""
Text-to-SQL 智能体
================================================================
系统架构位置：qa-service / agents 层
上游调用方：workflow 模块（编排完成后，由数据查询智能体路径触发）
下游依赖：state 模块（EvaluationState）、crewdefs 模块（SQL_AGENT 配置）
外部依赖：LLM 调用函数（由 workflow 注入的 llm_call_fn）

核心职责：
  根据用户自然语言问题 + workflow 预筛选的表结构 + 指标定义 → 生成正确的 SELECT SQL

关键设计决策：
  - 表筛选由 workflow 完成（预取相关表 schema 写入 state.table_schemas），
    此处只负责 SQL 生成，不做表选择
  - 支持重试机制：SQL 校验失败时自动重试（最多 max_retries 次）
  - 输出 SQL 经过多重清理：去除注释头、末尾分号、特殊控制字符

数据流：
  state.table_schemas / state.indicator_defs / state.question
    → TEXT_TO_SQL_SYSTEM_PROMPT.format()
    → llm_call_fn() 调用大模型
    → _extract_sql() 提取 SQL
    → _validate_sql() 安全校验
    → _clean_sql() / _sanitize_sql_ending() 清理
    → state.generated_sql
"""
import json
import logging
import re
from .state import EvaluationState
from .crewdefs import SQL_AGENT

logger = logging.getLogger("evaluation.text_to_sql")

# ============================================================================
# System Prompt：发送给 LLM 的 SQL 生成指令模板
# 占位符 {table_context} / {indicator_context} / {question} / {analysis_plan} / {filters}
# 运行时通过 .format() 填充
# ============================================================================
TEXT_TO_SQL_SYSTEM_PROMPT = f"""# 角色: {SQL_AGENT['role']}
# 目标: {SQL_AGENT['goal']}

{SQL_AGENT['backstory']}

---

你是SQL生成专家。根据表结构生成SELECT查询。

## 表结构
{{table_context}}

## 指标定义
{{indicator_context}}

## 问题
{{question}}

## 分析计划
{{analysis_plan}}

## 过滤条件
{{filters}}

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
    """
    Text-to-SQL 主入口：根据 state 中的上下文生成 SQL 查询。

    流程：
    1. 前置检查：无数据源 / general_analysis 模式 → 跳过 SQL 生成
    2. 从 state.table_schemas 构建表结构上下文文本
    3. 从 state.indicator_defs 构建指标描述文本
    4. 调用 LLM 生成 SQL（带重试机制）
    5. 校验 SQL 安全性 → 成功则写入 state.generated_sql
    6. 失败时：检测模型是否明确返回"无需 SQL"标记；否则重试

    Args:
        state: 当前工作流状态（含 table_schemas / indicator_defs / question 等）
        llm_call_fn: LLM 调用函数，签名为 async (system_prompt: str, user_message: str) -> str
        max_retries: SQL 校验失败时的最大重试次数，默认 1（即最多尝试 2 次）

    Returns:
        EvaluationState: 更新后的工作流状态（含 generated_sql / sql_valid）
    """
    logger.info(f"Running text-to-sql for: {state.question[:100]}")

    # 前置检查 1：无数据源时跳过 SQL 生成
    if not state.database_id:
        state.add_step(99, "SQL生成", "skipped", "未选择数据源")
        state.generated_sql = ""
        state.sql_valid = False
        return state

    # 前置检查 2：纯概念问答模式不需要查询数据库
    query_type = state.entities.get("query_type", "")
    if query_type == "general_analysis":
        state.add_step(99, "SQL生成", "skipped", "无需查询数据")
        state.generated_sql = ""
        state.sql_valid = False
        return state

    # workflow 已预取并筛选 table_schemas，直接使用
    table_count = len(state.table_schemas)

    # =========================================================================
    # 构建表结构文本：遍历 state.table_schemas，拼装每个表的列信息
    # 包含：表名、数据集名、描述、列名、数据类型、主键标记、注释、业务含义
    # =========================================================================
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

    # =========================================================================
    # 构建指标描述文本：公式 + 说明，帮助 LLM 理解如何计算指标
    # =========================================================================
    indicator_context_parts = []
    for ind in (state.indicator_defs or []):
        ic = f"\n### {ind.get('name', '')}"
        if ind.get("formula"):
            ic += f"\n  公式: {ind['formula']}"
        if ind.get("description"):
            ic += f"\n  说明: {ind['description']}"
        indicator_context_parts.append(ic)
    indicator_context = "\n".join(indicator_context_parts) if indicator_context_parts else "无可用指标"

    # =========================================================================
    # 生成 SQL（带重试机制）
    # 首次尝试 → 校验失败 → 将错误信息反馈给 LLM 重试 → 最多 max_retries 次重试
    # =========================================================================
    sql = ""
    last_error = None
    attempts = 0

    while attempts <= max_retries:
        # 构建步骤标签：首次无标签，重试时标注次数
        attempt_label = "" if attempts == 0 else f" (第{attempts+1}次)"
        step_id = 5 if attempts == 0 else 5.2

        # 重试时记录上次错误原因
        if attempts > 0 and last_error:
            state.add_step(step_id, f"SQL重试{attempt_label}", "in_progress",
                          detail=f"上次错误: {last_error[:120]}")

        state.add_step(5.1, f"生成SQL{attempt_label}", "in_progress",
                      detail=f"正在调用大模型生成SQL...（{table_count} 张表）")

        # 填充 prompt 模板，注入当前上下文
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
                # SQL 提取成功，进行安全校验
                is_valid, error_msg = _validate_sql(sql)
                if is_valid:
                    # 校验通过：清理 SQL 并写入 state
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
                    # 校验失败：记录错误，准备重试
                    last_error = error_msg
                    state.add_step(5.1, f"生成SQL{attempt_label}", "in_progress",
                                   detail=f"SQL校验失败: {error_msg[:120]}")
                    logger.warning(f"SQL validation failed: {error_msg}")
            else:
                # 未提取到 SQL：检查模型是否明确表示"无需查询"
                no_sql = _extract_no_sql(response)
                if no_sql:
                    state.add_step(5.1, "生成SQL", "skipped",
                                   detail=f"模型判断无需SQL: {no_sql.get('reason', '')[:120]}")
                    state.generated_sql = ""
                    state.sql_valid = False
                    return state
                # 模型未返回有效 SQL 也未标记 no_sql，准备重试
                last_error = "模型未返回有效SQL"
                state.add_step(5.1, "生成SQL", "in_progress",
                               detail="未提取到SQL，准备重试",
                               thinking=f"模型原始响应:\n{response[:500]}")

        except Exception as e:
            last_error = str(e)[:300]
            logger.error(f"Text-to-SQL attempt {attempts + 1} failed: {e}")
            state.add_step(5.1, "生成SQL", "error",
                          detail=f"调用失败: {last_error[:120]}")
            # 超时错误不重试，避免无限等待
            if "timeout" in last_error.lower() or "timed out" in last_error.lower():
                break

        attempts += 1

    # 所有尝试均失败：记录最终错误
    state.add_step(99, "SQL生成", "error",
                  detail=f"失败: {last_error[:200]}" if last_error else "失败: 未知错误")
    state.generated_sql = ""
    state.sql_valid = False
    return state


def _extract_sql(response_text: str) -> str:
    """
    从 LLM 响应文本中提取 SQL 语句。

    支持三种输出格式：
    1. ```sql ... ``` 代码块（优先匹配）
    2. ``` ... ``` 通用代码块（无语言标记，取第一个代码块内容）
    3. 裸文本中以 SELECT 开头的语句（正则兜底）

    Args:
        response_text: LLM 返回的原始文本

    Returns:
        str: 提取出的 SQL 语句（已去除末尾分号和特殊字符）；无法提取时返回空字符串
    """
    text = response_text.strip()
    sql = ""

    # 策略 1：优先匹配 ```sql 标记的代码块
    if "```sql" in text:
        start = text.index("```sql") + 6
        end = text.index("```", start) if "```" in text[start:] else len(text)
        sql = text[start:end].strip()
    elif "```" in text:
        # 策略 2：无语言标记，取第一个代码块的内容
        lines = text.split("\n")
        in_block, sql_lines = False, []
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break  # 遇到闭合标记，结束
                in_block = True
                continue  # 跳过开启标记行
            if in_block:
                sql_lines.append(line)
        if sql_lines:
            sql = "\n".join(sql_lines).strip()
    else:
        # 策略 3：无代码块时，用正则匹配 SELECT 开头的语句
        select_match = re.search(r'(SELECT\s+.+?(?:;|$))', text, re.IGNORECASE | re.DOTALL)
        if select_match:
            sql = select_match.group(1).strip()

    # 统一去除末尾分号和特殊字符（Oracle 等数据库对分号敏感）
    return _sanitize_sql_ending(sql)


def _extract_no_sql(response_text: str) -> dict:
    """
    检查 LLM 响应是否包含"无需 SQL"的显式标记。

    当 LLM 判断用户问题无需数据库查询时，会返回包含 {"no_sql": true} 的 JSON。
    例如：纯理论问题、概念解释等场景。

    Args:
        response_text: LLM 返回的原始文本

    Returns:
        dict: 包含 no_sql 标记的字典；未检测到则返回空字典 {}
    """
    text = response_text.strip()
    try:
        # 尝试从 json 代码块中提取
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        # 仅解析以 { 开头的 JSON 对象
        data = json.loads(text) if text.startswith("{") else None
        if data and data.get("no_sql"):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def _clean_sql(sql: str) -> str:
    """
    清理 SQL 语句的前导注释和空白行。

    跳过 SQL 文本开头的：
    - 空行
    - 以 -- 开头的注释行
    - 以 # 开头的注释行（部分 SQL 方言支持）

    这样可以去除 LLM 在 SQL 前附加的解释性注释，保留纯净的 SQL。

    Args:
        sql: 原始 SQL 字符串

    Returns:
        str: 清理后的 SQL（已去除前导注释 + 末尾分号和特殊字符）
    """
    lines = sql.strip().split("\n")
    result = []
    started = False
    for line in lines:
        stripped = line.strip()
        # 跳过前置的注释行和空行：在遇到第一条有效行之前，忽略注释
        if not started and (not stripped or stripped.startswith("--") or stripped.startswith("#")):
            continue
        started = True
        result.append(line)
    sql = "\n".join(result).strip()
    return _sanitize_sql_ending(sql)


def _sanitize_sql_ending(sql: str) -> str:
    """
    去除 SQL 末尾的分号、特殊空白字符和尾随空行。

    某些数据库（如 Oracle）对末尾分号敏感，JDBC 执行时可能导致语法错误。
    此函数确保输出 SQL 末尾干净，可被各数据库 JDBC 驱动安全执行。

    处理步骤：
    1. 去除末尾分号（可能连续多个 ;;）
    2. 去除不可见 ASCII 控制字符（保留正常空格 0x20）
    3. 去除末尾多余的换行符

    Args:
        sql: SQL 字符串

    Returns:
        str: 清理后的 SQL
    """
    if not sql:
        return ""
    # 去除末尾分号（可能多个）：先 rstrip 常规空白，再 rstrip 分号
    sql = sql.rstrip().rstrip(";").rstrip()
    # 去除末尾不可见控制字符（保留正常空格）：\x00-\x1f 和 \x7f（DEL）
    sql = sql.rstrip("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"
                     "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x7f")
    # 去掉末尾多余空行
    while sql.endswith("\n") or sql.endswith("\r"):
        sql = sql[:-1]
    return sql


def _validate_sql(sql: str) -> tuple:
    """
    SQL 安全校验：确保生成的 SQL 仅包含只读查询操作。

    校验规则：
    1. 禁止危险关键字：INSERT / UPDATE / DELETE / TRUNCATE / DROP / ALTER / CREATE / EXEC / EXECUTE
       （使用单词边界正则匹配，避免误判字段名中含有关键字的情况）
    2. 必须以 SELECT 或 WITH（CTE）开头
    3. 括号必须成对匹配

    Args:
        sql: 待校验的 SQL 字符串

    Returns:
        tuple[bool, str]: (是否通过校验, 错误信息)
        - (True, "") 表示校验通过
        - (False, "错误描述") 表示校验失败及原因
    """
    cleaned = _clean_sql(sql)
    sql_upper = cleaned.upper()

    # 检查 1：禁止危险关键字（使用 \b 单词边界，避免匹配字段名中的子串）
    dangerous = ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE", "EXEC", "EXECUTE"]
    for keyword in dangerous:
        if re.search(r'\b' + keyword + r'\b', sql_upper):
            return False, f"SQL包含禁止关键字: {keyword}"

    # 检查 2：SQL 必须以 SELECT 或 WITH（CTE 公共表表达式）开头
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, f"SQL必须以SELECT或WITH开头（当前以 '{cleaned[:30]}...' 开头）"

    # 检查 3：括号必须成对
    if cleaned.count("(") != cleaned.count(")"):
        return False, "括号不匹配"

    return True, ""
