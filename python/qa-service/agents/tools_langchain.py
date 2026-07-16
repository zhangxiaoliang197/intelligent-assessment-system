"""
LangChain @tool 标准化封装 — 将 tools.py 的工具函数包装为 LangChain Tool。

============================================================
模块在系统架构中的位置
============================================================

本模块位于 qa-service 的多智能体框架层（agents/），是底层工具函数
（tools.py）与上层 LLM Tool Calling 之间的适配层（Adapter Layer）。

它通过 LangChain 的 @tool 装饰器，将 tools.py 中的普通 Python 函数
包装为具有标准化 schema（名称、描述、参数类型签名）的 Tool 对象，
使 LLM 能够通过 Function Calling / Tool Calling 机制自主决定
何时调用哪个工具。

============================================================
设计收益
============================================================
1. 自动生成 tool schema（名称、描述、参数类型），LLM Tool Calling 可直接识别
2. 未来可使用 LLM 自主选表（如 "我需要先看看有哪些表" → 调用 get_table_list_tool）
3. 错误处理统一：所有异常被捕获并转为结构化 JSON 字符串返回，不会中断 LLM 流程
4. 数据截断保护：run_database_query 自动限制返回前 50 行，防止 token 溢出

============================================================
依赖关系
============================================================
tools.py（底层 HTTP 调用） → tools_langchain.py（LangChain 封装） → workflow.py（编排使用）
"""
import json
import logging
from langchain_core.tools import tool

# 从底层 tools.py 导入原始函数，使用 _ 前缀别名避免与 @tool 装饰后的函数名冲突
from .tools import (
    fetch_database_tables as _fetch_tables,
    fetch_table_structure as _fetch_structure,
    execute_sql_on_database as _execute_sql,
    fetch_datasets_for_database as _fetch_datasets,
    fetch_indicators_for_datasets as _fetch_indicators,
)

logger = logging.getLogger("evaluation.tools_langchain")


# ═══════════════════════════════════════════════════════════════
# LangChain Tool 定义
# ═══════════════════════════════════════════════════════════════
# 以下每个 @tool 装饰的函数都是一个独立的 LangChain Tool，
# 可直接传入 LLM 的 bind_tools() 或 AgentExecutor 的 tools 参数。
# 每个 Tool 的 docstring 会被 LangChain 自动解析为 tool 的 description，
# 函数签名中的参数类型注解会被解析为 input_schema。

@tool
def get_table_list(database_id: str) -> str:
    """获取数据库中所有表名列表。用于 SQL 生成前了解有哪些可用表。

    调用时机：LLM 在执行 SQL 生成前，需要先了解目标数据库中有哪些表可用。
             这是数据探查（Exploration）阶段的第一步。

    Args:
        database_id: 数据库配置 ID（对应 admin-service 中的 database 记录）

    Returns:
        JSON 格式字符串，包含：
        - tables: 表名字符串列表
        - count:  表的总数量
        - error:  出错时的错误信息（仅在异常时出现）
    """
    try:
        tables = _fetch_tables(database_id)  # 调用底层 HTTP API 获取表名列表
        # 返回结构化 JSON，count 字段方便 LLM 快速了解表数量
        return json.dumps({"tables": tables, "count": len(tables)}, ensure_ascii=False)
    except Exception as e:
        # 异常不向上抛出，而是转为 JSON 错误消息返回，保证 LLM 流程不中断
        return json.dumps({"error": str(e), "tables": []})


@tool
def get_table_info(database_id: str, table_name: str) -> str:
    """读取指定表的完整结构信息（列名、类型、主键、注释）。

    调用时机：LLM 在了解有哪些表后，需要查看具体表的字段结构才能生成正确的 SQL。
             这是数据探查阶段的第二步，通常在 get_table_list 之后调用。

    Args:
        database_id: 数据库配置 ID
        table_name:  要查询结构的表名

    Returns:
        JSON 格式字符串，包含：
        - tableName: 表名
        - columns:   列信息列表，每列含 columnName/dataType/isPrimaryKey/isNullable/comment
        - count:     列数量
        - error:     出错时的错误信息（仅在异常时出现）
    """
    try:
        schema = _fetch_structure(database_id, table_name)  # 通过 information_schema 查询列信息
        # default=str 处理 datetime 等不可 JSON 序列化的类型
        return json.dumps(schema, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "tableName": table_name, "columns": []})


@tool
def run_database_query(database_id: str, sql: str) -> str:
    """在指定数据库上执行 SELECT 查询，返回结果数据。

    调用时机：LLM 生成 SQL 并经过安全校验后，需要实际执行查询获取数据。
             这是执行（Execution）阶段的核心工具。

    安全措施：
    1. 底层 tools.py 通过 admin-service 的 execute-sql 接口执行，由 Java 端做 SQL 注入防护
    2. 本层限制返回前 50 行数据，防止大量数据撑爆 LLM 上下文窗口

    Args:
        database_id: 数据库配置 ID
        sql:         要执行的 SELECT 查询语句

    Returns:
        JSON 格式字符串，包含：
        - success:    是否执行成功
        - columns:    列名列表
        - rows:       数据行（最多 50 行）
        - totalRows:  实际总行数
        - truncated:  是否因超过 50 行而被截断
        - error:      出错时的错误信息（仅在失败时出现）
    """
    try:
        result = _execute_sql(database_id, sql)  # 通过 admin-service 代理执行 SQL
        if result.get("success"):
            rows = result.get("rows", [])
            # 限制返回前 50 行：防止大量数据导致 LLM token 超限
            # truncated 标记告知 LLM 数据已被截断，需要时可建议缩小查询范围
            return json.dumps({
                "success": True,
                "columns": result.get("columns", []),
                "rows": rows[:50],          # 仅返回前 50 行
                "totalRows": len(rows),     # 告知 LLM 实际总行数
                "truncated": len(rows) > 50,  # 标记是否被截断
            }, ensure_ascii=False, default=str)
        return json.dumps({"success": False, "error": result.get("message", "未知错误")})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool
def get_datasets_for_db(database_id: str) -> str:
    """获取与数据库关联的数据集列表（含业务描述、表映射）。

    调用时机：LLM 在数据探查阶段，需要了解数据库中表的业务含义和上下文信息。
             数据集是用户在前端管理的数据资产，包含对表的业务描述和字段标注。

    与 get_table_list 的区别：
    - get_table_list：返回纯技术表名
    - get_datasets_for_db：返回带业务语义的数据集（表名 + 业务描述 + 标注）

    Args:
        database_id: 数据库配置 ID

    Returns:
        JSON 格式字符串，每个数据集包含：
        - name:        数据集名称（业务名称）
        - tableName:   对应的物理表名
        - description: 业务描述（截断至 100 字符）
        - error:       出错时的错误信息（仅在异常时出现）
    """
    try:
        datasets = _fetch_datasets(database_id)  # 从 admin-service 获取数据集列表
        # 对每个数据集做摘要处理：只保留 name/tableName/description 前 100 字
        # 避免完整 description 过长导致 token 浪费
        summary = [{"name": d.get("name", ""), "tableName": d.get("tableName", ""),
                     "description": d.get("description", "")[:100]} for d in datasets]
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def get_indicators_for_datasets(dataset_ids: list[str]) -> str:
    """获取关联到指定数据集的指标定义（含公式、说明）。

    调用时机：LLM 在 SQL 生成阶段，需要了解可用的指标计算逻辑，
             以便生成包含聚合/计算逻辑的 SQL 语句。

    指标（Indicator）是用户预定义的业务计算规则，例如：
    - 命中率 = 命中次数 / 攻击次数 × 100%
    - 任务达成率 = 完成任务数 / 总任务数 × 100%

    Args:
        dataset_ids: 数据集 ID 列表（用于过滤关联的指标）

    Returns:
        JSON 格式字符串，每个指标包含：
        - name:        指标名称
        - formula:     计算公式
        - description: 指标说明（截断至 100 字符）
        - error:       出错时的错误信息（仅在异常时出现）
    """
    try:
        indicators = _fetch_indicators(dataset_ids)  # 按数据集 ID 过滤获取指标
        # 摘要处理：只保留 name/formula/description 前 100 字
        summary = [{"name": i.get("name", ""), "formula": i.get("formula", ""),
                     "description": i.get("description", "")[:100]} for i in indicators]
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════
# Tool 集合 — 按场景组织
# ═══════════════════════════════════════════════════════════════
# 说明：以下列表将 Tool 按工作流阶段分组，用于在不同节点中绑定不同工具集。
# 这样可以限制 LLM 在每个阶段的可用工具范围，避免工具选择混乱。

# 数据探查阶段可用工具：用于了解数据库中有哪些表、表结构、业务含义
# 使用场景：编排阶段之后、SQL 生成之前
EXPLORATION_TOOLS = [
    get_table_list,        # 获取所有表名列表
    get_table_info,        # 获取指定表的结构信息
    get_datasets_for_db,   # 获取数据集的业务描述
]

# SQL 执行阶段可用工具：用于执行 SQL 并查看表结构
# 使用场景：SQL 生成并校验通过后、数据分析之前
EXECUTION_TOOLS = [
    run_database_query,    # 执行 SQL 查询
    get_table_info,        # 保留表结构查看能力（SQL 重试时可能需要）
]

# 全阶段工具集合：包含所有 5 个工具，用于需要完整能力的场景
# 使用场景：通用 Agent、调试、或需要 LLM 自主规划工具调用链路的场景
ALL_TOOLS = [
    get_table_list,
    get_table_info,
    run_database_query,
    get_datasets_for_db,
    get_indicators_for_datasets,
]
