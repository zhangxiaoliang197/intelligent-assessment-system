"""
多智能体 ReAct 工作流引擎

═══════════════════════════════════════════════════════════════════════════
架构说明
═══════════════════════════════════════════════════════════════════════════

本模块是评估系统的核心调度器，实现真正的多智能体 ReAct（Reasoning + Acting）模式。
相比旧版 langgraph_workflow.py 的固定管道线，本模块的关键区别：

  **旧版（固定管道）**:
    orchestrator → data_explore → table_select → text_to_sql → sql_execute → analyst
    无论什么问题，都走同一条路。

  **新版（多智能体 ReAct）**:
    Orchestrator 分析问题 → 动态决定执行路径：
      ├─ 不需要数据 → Knowledge Worker （知识问答）
      ├─ 需要查数据 → Data Worker （Think→Act→Observe 循环探索数据库）
      └─ 需要整体评估 → 专用智能体

    每个智能体都有独立的 ReAct 循环：思考 → 行动 → 观察 → 再思考 → 最终回答。
    智能体自己决定调用什么工具、查什么表、生成什么 SQL，而不是固定步骤。

智能体角色：
  Orchestrator（编排者）  — 分析问题，决定调用哪种子智能体
  Knowledge Worker（知识工）— 不查库，用知识回答通用问题
  Data Worker（数据工）   — ReAct 循环：列表面→探索表→生成SQL→执行
  Synthesizer（综合者）  — 将中间结果综合为最终答案

═══════════════════════════════════════════════════════════════════════════
ReAct 循环说明
═══════════════════════════════════════════════════════════════════════════

每个智能体遵循标准 ReAct 格式：

  THOUGHT: 我对当前情况的分析和思考
  ACTION: tool_name: {"param1": "value1", ...}
  
  （系统执行工具后注入：）
  OBSERVATION: 工具返回结果
  
  ...（可多轮 Think-Act-Observe）...
  
  THOUGHT: 信息充足，可以给出回答了
  FINAL_ANSWER: 最终答案内容

═══════════════════════════════════════════════════════════════════════════
"""
import asyncio
import json
import logging
import re
from typing import TypedDict, Any, Optional, Callable

from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig

from .state import EvaluationState

logger = logging.getLogger("evaluation.react")

# ── SSE 步骤间最小间隔 ──
_YIELD_DELAY = 0.25

# ── 工具执行超时 ──
_TOOL_TIMEOUT = 15


# ═══════════════════════════════════════════════════════════════════════════
# ReAct 状态定义
# ═══════════════════════════════════════════════════════════════════════════

class ReactWorkflowState(TypedDict, total=False):
    """多智能体 ReAct 工作流状态"""

    # ── 输入 ──
    question: str
    session_id: str
    database_id: str
    database_name: str
    attachment_text: str
    database_type: str

    # ── 编排决策 ──
    # 编排者决定的执行路径类型
    # "knowledge" — 知识问答，不查库
    # "data_query" — 需要查数据库
    # "combat_effectiveness" — 作战效能分析
    # "air_superiority" — 制空权分析
    route: str
    query_type: str         # 原始 query_type（如 "combat_effectiveness"）
    plan: str               # 编排者制定的执行计划
    need_chart: bool
    need_conclusion: bool
    intent: str             # 用户意图简述

    # ── 知识工作者产出 ──
    knowledge_answer: str

    # ── 数据工作者 ReAct 历史 ──
    # 记录 Think-Act-Observe 的完整过程
    data_react_traces: list

    # ── 数据工作者产出 ──
    data_final_answer: str  # Data Worker 的最终回答
    generated_sql: str      # 最终生成的 SQL
    raw_results: list       # SQL 执行结果
    chart_config: dict      # 图表配置

    # ── 综合产出 ──
    final_answer: str
    result: dict
    steps: list
    error: str


def _empty_state() -> dict:
    """返回所有非输入字段的默认值"""
    return {
        "route": "knowledge",
        "query_type": "",
        "plan": "",
        "need_chart": False,
        "need_conclusion": True,
        "intent": "",
        "knowledge_answer": "",
        "data_react_traces": [],
        "data_final_answer": "",
        "generated_sql": "",
        "raw_results": [],
        "chart_config": {},
        "final_answer": "",
        "result": {},
        "steps": [],
        "error": "",
    }


def _add_step(steps, step_num, description, status="pending",
              detail="", thinking="", progress=None):
    """向 steps 列表追加步骤记录"""
    if progress is None:
        progress = 100 if status == "completed" else (50 if status == "in_progress" else 0)
    steps.append({
        "step": step_num,
        "description": description,
        "status": status,
        "detail": detail,
        "thinking": thinking,
        "progress": progress,
    })


def _get_llm(config: RunnableConfig):
    """从配置中获取 LLM 调用函数"""
    return config.get("configurable", {}).get("llm_call_fn")


def _react_state_to_eval_state(state: ReactWorkflowState) -> EvaluationState:
    """将 ReactWorkflowState 适配为 EvaluationState。

    用于在 React 工作流中委托调用旧版专业智能体（analyst、text_to_sql 等），
    这些智能体的接口签名要求 EvaluationState。

    Args:
        state: React 工作流状态

    Returns:
        EvaluationState: 适配后的评估状态
    """
    es = EvaluationState(
        question=state.get("question", ""),
        database_id=state.get("database_id", ""),
        database_name=state.get("database_name", ""),
        database_type=state.get("database_type", ""),
    )
    # 将 React 状态中的关键字段映射到 EvaluationState
    es.intent = state.get("intent", "")
    es.analysis_plan = state.get("plan", "")
    es.need_chart = state.get("need_chart", False)
    es.entities = {
        "query_type": "data_query" if state.get("route") == "data_query" else "general_analysis",
        "need_conclusion": state.get("need_conclusion", True),
        "need_chart": state.get("need_chart", False),
        "filters": "",
        "dimensions": [],
    }
    es.generated_sql = state.get("generated_sql", "")
    es.raw_results = state.get("raw_results", [])
    es.steps = []  # 子智能体产出的步骤单独收集
    return es


# ═══════════════════════════════════════════════════════════════════════════
# ReAct 通用执行器
# ═══════════════════════════════════════════════════════════════════════════

_REACT_SYSTEM_TEMPLATE = """你是 {role}。你的目标是：{goal}

{backstory}

---

## 关键规则（必须严格遵守！）
你必须严格遵循 ReAct（推理+行动）模式。每次输出必须从以下两种格式之一开始：

```
THOUGHT: <你对当前情况的分析和思考，要做什么、为什么做>
ACTION: tool_name: {{"param": "value"}}
```

或者（仅当确信不需要更多信息时）：

```
THOUGHT: <你的最终分析>
FINAL_ANSWER: <你的最终回答内容>
```

规则:
1. 每次只能输出一个 ACTION
2. 执行 ACTION 后，你会收到 OBSERVATION，然后继续思考
3. 最多执行 {max_turns} 轮 ACTION
4. 当你认为信息充分时，输出 FINAL_ANSWER 结束
5. 不要重复执行相同参数的相同工具
6. 如果连续两次 ACTION 都没有进展，立即输出 FINAL_ANSWER
7. 重要: 不要让 FINAL_ANSWER 包含 THOUGHT 或 ACTION，这是两种互斥的格式
8. 重要: 不要用 markdown 代码块（```）包裹你的回答
9. 如果工具不需要参数，使用 ACTION: tool_name: {{}}
10. 如果你选择 FINAL_ANSWER，直接输出最终答案文字，不要再嵌套 THOUGHT/ACTION

## 可用工具

{tools_desc}

## 当前任务

用户问题：{question}
"""


async def _run_react_loop(
    system_prompt: str,
    question: str,
    tools: dict,
    llm_call_fn,
    max_turns: int = 6,
    on_trace: Optional[Callable] = None,
) -> dict:
    """执行完整的 ReAct Think→Act→Observe 循环。

    Args:
        system_prompt: 系统提示词（含角色、工具描述）
        question:      用户问题
        tools:         工具字典 {tool_name: tool_function}
        llm_call_fn:   LLM 调用函数
        max_turns:     最大行动轮数
        on_trace:      可选回调，每轮执行后被调用 on_trace(trace_entry)

    Returns:
        dict: {"answer": str, "traces": list, "actions_taken": int}
    """
    traces = []
    # 累积的对话历史（用于后续轮次注入 LLM 上下文）
    conversation_log = ""
    final_answer = ""
    actions_taken = 0
    last_action_sig = ""

    for turn in range(max_turns):
        # ── 构建本轮的用户消息 ──
        if turn == 0:
            user_msg = question
        else:
            # 将对话历史作为新一轮的 user_message 发送给 LLM
            user_msg = (
                f"以下是之前的操作记录：\n\n{conversation_log}\n\n"
                "请继续。根据以上观察，输出下一轮 THOUGHT + ACTION 或 FINAL_ANSWER。"
            )

        try:
            response = await llm_call_fn(system_prompt, user_msg)
        except Exception as e:
            logger.error(f"ReAct LLM 调用失败 (第{turn+1}轮): {e}")
            final_answer = f"分析过程出错：{str(e)[:200]}"
            traces.append({"turn": turn, "type": "error", "content": str(e)})
            break

        # ── 解析响应 ──
        thought, action, action_input, is_final, final_text = _parse_react_response(response)

        if is_final:
            final_answer = final_text
            traces.append({"turn": turn, "type": "final", "thought": thought, "answer": final_text})
            if on_trace:
                on_trace(traces[-1])
            break

        if not action:
            # 无法解析 ACTION，尝试当作最终答案
            logger.warning(f"ReAct 第{turn+1}轮未解析到有效 ACTION，当作最终答案处理")
            final_answer = response.strip()
            traces.append({"turn": turn, "type": "fallback", "content": final_answer})
            if on_trace:
                on_trace(traces[-1])
            break

        # ── 去重检查 ──
        action_sig = f"{action}:{json.dumps(action_input, sort_keys=True, ensure_ascii=False)}"
        if action_sig == last_action_sig:
            logger.warning(f"ReAct 检测到重复操作 {action_sig}，强制结束")
            traces.append({"turn": turn, "type": "warn", "content": "检测到重复操作，跳过"})
            if on_trace:
                on_trace(traces[-1])
            continue
        last_action_sig = action_sig

        # ── 执行工具 ──
        if action not in tools:
            observation = f"错误：未知工具 '{action}'。可用工具：{', '.join(tools.keys())}"
        else:
            try:
                result = tools[action](**action_input)
                # 如果工具返回的是协程，await 它
                if asyncio.iscoroutine(result):
                    observation = json.dumps(await result, ensure_ascii=False, default=str)
                elif isinstance(result, (dict, list)):
                    observation = json.dumps(result, ensure_ascii=False, default=str)
                else:
                    observation = str(result)
            except Exception as e:
                observation = f"工具执行错误: {str(e)[:300]}"

        actions_taken += 1
        trace_entry = {
            "turn": turn, "type": "action",
            "thought": thought, "action": action,
            "action_input": action_input, "observation": observation,
        }
        traces.append(trace_entry)
        if on_trace:
            on_trace(trace_entry)

        # 将观察追加到对话历史
        conversation_log += (
            f"【第{turn+1}轮】\n"
            f"THOUGHT: {thought}\n"
            f"ACTION: {action}: {json.dumps(action_input, ensure_ascii=False)[:300]}\n"
            f"OBSERVATION: {observation[:500]}\n\n"
        )

    if not final_answer:
        # 达到最大轮数仍未得出答案，强制生成
        try:
            force_msg = (
                f"已达到最大行动轮数。以下是之前的操作记录：\n\n{conversation_log}\n\n"
                "请基于已有信息给出 FINAL_ANSWER。"
            )
            response = await llm_call_fn(system_prompt, force_msg)
            _, _, _, _, final_answer = _parse_react_response(response)
            if not final_answer:
                final_answer = response.strip()
        except Exception as e:
            final_answer = f"分析过程达到最大轮数: {str(e)[:200]}"

    return {"answer": final_answer, "traces": traces, "actions_taken": actions_taken}


def _parse_react_response(text: str) -> tuple:
    """解析 LLM 的 ReAct 格式响应。

    处理常见的 LLM 输出问题：
    - 代码块包裹（```...```）
    - 错误地将 ReAct 格式放在 FINAL_ANSWER 后面
    - Windows 换行符 \\r\\n

    Returns:
        (thought, action_name, action_params, is_final, final_text)
    """
    # 去除代码块包裹
    text = text.strip()
    text = re.sub(r'```[\w]*\s*', '', text)  # 去除 ``` 标记
    text = re.sub(r'^\s*```\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)

    # 统一换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 提取 THOUGHT
    thought_match = re.search(
        r'THOUGHT:\s*(.+?)(?=\n(?:ACTION|FINAL_ANSWER|OBSERVATION):|\Z)',
        text, re.DOTALL | re.IGNORECASE
    )
    thought = thought_match.group(1).strip() if thought_match else ""

    # 检查 FINAL_ANSWER — 但要防止 FINAL_ANSWER 中嵌套 ACTION 的情况
    final_match = re.search(r'FINAL_ANSWER:\s*(.+)', text, re.DOTALL | re.IGNORECASE)
    if final_match:
        final_content = final_match.group(1).strip()
        # 如果 FINAL_ANSWER 的内容中包含 ACTION 模式，说明 LLM 格式错误
        # 此时尝试从整个响应中解析 ACTION
        has_action_inside = re.search(r'ACTION:\s*\w+', final_content, re.IGNORECASE)
        if not has_action_inside:
            return thought, "", {}, True, final_content

    # 检查 ACTION（支持多种格式）
    # 格式1: ACTION: tool_name: {"param": "value"} 或 ACTION: tool_name: {}
    action_match = re.search(
        r'ACTION:\s*(\w+)\s*:\s*(\{.*?\})',
        text, re.DOTALL | re.IGNORECASE
    )
    if action_match:
        action_name = action_match.group(1).strip()
        try:
            action_params = json.loads(action_match.group(2))
        except json.JSONDecodeError:
            bracelet_match = re.search(r'\{.+\}', action_match.group(2), re.DOTALL)
            if bracelet_match:
                try:
                    action_params = json.loads(bracelet_match.group())
                except json.JSONDecodeError:
                    action_params = {}
            else:
                action_params = {}
        return thought, action_name, action_params, False, ""

    # 格式2: ACTION: tool_name（无参数）
    action_match2 = re.search(r'ACTION:\s*(\w+)\s*$', text, re.IGNORECASE | re.MULTILINE)
    if action_match2:
        action_name = action_match2.group(1).strip()
        # 确保不是 FINAL_ANSWER 之后的假 ACTION
        is_after_final = final_match and text.find(action_match2.group()) > text.find(final_match.group())
        if not is_after_final:
            return thought, action_name, {}, False, ""

    # FINAL_ANSWER 匹配但内容中有 ACTION → 重新提取真正的 FINAL_ANSWER
    if final_match:
        final_content = final_match.group(1).strip()
        return thought, "", {}, True, final_content[:2000]

    # 都不匹配，尝试当作纯文本最终答案
    return thought, "", {}, True, text


# ═══════════════════════════════════════════════════════════════════════════
# 工具定义（Data Worker 可用）
# ═══════════════════════════════════════════════════════════════════════════

def _build_tools(db_id: str) -> dict:
    """构建 Data Worker 可用的工具集。

    Args:
        db_id: 数据源 ID

    Returns:
        dict: {tool_name: callable}
    """
    from .tools import (
        fetch_database_tables,
        fetch_table_structure,
        execute_sql_on_database,
        fetch_datasets_for_database,
        fetch_indicators_for_datasets,
    )

    def list_tables() -> dict:
        """列出数据源中的所有表名、数据集和指标"""
        tables = fetch_database_tables(db_id)
        datasets = fetch_datasets_for_database(db_id)
        ds_info = [{"name": d.get("name", ""), "tableName": d.get("tableName", ""),
                     "description": d.get("description", "")[:80]} for d in datasets]

        # 获取关联指标
        indicators = []
        try:
            ds_ids = [d.get("id") for d in datasets]
            indicators = fetch_indicators_for_datasets(ds_ids)
        except Exception:
            pass
        ind_info = [{"name": i.get("name", ""), "unit": i.get("unit", ""),
                      "description": (i.get("description", "") or "")[:60]} for i in indicators]

        return {
            "table_count": len(tables),
            "tables": tables[:30],
            "datasets": ds_info[:10],
            "indicators": ind_info[:20],
        }

    def explore_table(table_name: str) -> dict:
        """查看指定表的结构。优先使用数据集增强结构（含业务标注），
        回退到 JDBC 原始元数据。

        Args:
            table_name: 表名
        """
        # 先检查是否有关联的数据集（用户在基础管理中配置的业务标注）
        datasets = fetch_datasets_for_database(db_id)
        ds_map = {d.get("tableName", ""): d for d in datasets}
        ds = ds_map.get(table_name)

        if ds:
            try:
                from .tools import _fetch_dataset_structure_inner
                structure = _fetch_dataset_structure_inner(ds.get("id"))
                columns = structure.get("columns", [])
                col_info = []
                for c in columns:
                    col_info.append({
                        "name": c.get("columnName", ""),
                        "type": c.get("dataType", ""),
                        "comment": (c.get("annotation", "")
                                   or c.get("businessMeaning", "")
                                   or c.get("comment", "")),
                        "isPrimaryKey": c.get("isPrimaryKey", False),
                        "category": c.get("dataCategory", ""),
                    })
                return {
                    "tableName": structure.get("tableName", table_name),
                    "columnCount": len(col_info),
                    "columns": col_info,
                    "datasetName": ds.get("name", table_name),
                    "description": (ds.get("description", "") or "")[:150],
                }
            except Exception:
                pass  # 增强路径失败，回退到原始 JDBC 路径

        # 回退：直接读取 JDBC 元数据（无用户标注）
        structure = fetch_table_structure(db_id, table_name)
        columns = structure.get("columns", [])
        col_info = []
        for c in columns:
            col_info.append({
                "name": c.get("columnName", ""),
                "type": c.get("dataType", ""),
                "comment": c.get("comment", ""),
                "isPrimaryKey": c.get("isPrimaryKey", False),
            })
        return {
            "tableName": structure.get("tableName", table_name),
            "columnCount": len(col_info),
            "columns": col_info,
        }

    def run_sql(sql: str) -> dict:
        """在数据源上执行 SELECT 查询。

        Args:
            sql: 要执行的 SQL 语句（仅允许 SELECT/WITH 开头）
        """
        # 基础安全检查
        sql_upper = sql.strip().upper()
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
            return {"error": "只允许执行 SELECT 或 WITH 语句"}
        dangerous = ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE"]
        for kw in dangerous:
            if re.search(r'\b' + kw + r'\b', sql_upper):
                return {"error": f"禁止关键字: {kw}"}

        result = execute_sql_on_database(db_id, sql)
        if result.get("success"):
            rows = result.get("rows", result.get("data", []))
            columns = result.get("columns", [])
            return {
                "success": True,
                "rowCount": len(rows),
                "rows": rows[:100],  # 最多返回 100 行供分析
                "columns": columns,
                "truncated": len(rows) > 100,
            }
        return {"success": False, "error": result.get("message", "执行失败")}

    return {
        "list_tables": list_tables,
        "explore_table": explore_table,
        "run_sql": run_sql,
    }


# ── 探索阶段工具描述（不含 run_sql，仅用于 Phase1 数据库结构探索）──
_EXPLORATION_TOOLS_DESC = """
### list_tables
列出数据源中的所有表名、数据集和指标定义。
无需参数。
示例: ACTION: list_tables: {}

### explore_table
查看指定表的完整结构（列名、类型、注释、主键）。
参数: table_name (字符串)
示例: ACTION: explore_table: {"table_name": "t_combat_record"}
"""


def _build_exploration_tools(db_id: str) -> dict:
    """构建 Data Worker Phase1 探索阶段工具集（仅探索，不含 run_sql）。

    Args:
        db_id: 数据源 ID

    Returns:
        dict: {tool_name: callable}，仅含 list_tables 和 explore_table
    """
    from .tools import (
        fetch_database_tables, fetch_table_structure,
        fetch_datasets_for_database, fetch_indicators_for_datasets,
    )

    def list_tables() -> dict:
        """列出数据源中的所有表名、数据集和指标"""
        tables = fetch_database_tables(db_id)
        datasets = fetch_datasets_for_database(db_id)
        ds_info = [{"name": d.get("name", ""), "tableName": d.get("tableName", ""),
                     "description": d.get("description", "")[:80]} for d in datasets]
        indicators = []
        try:
            ds_ids = [d.get("id") for d in datasets]
            indicators = fetch_indicators_for_datasets(ds_ids)
        except Exception:
            pass
        ind_info = [{"name": i.get("name", ""), "unit": i.get("unit", ""),
                      "description": (i.get("description", "") or "")[:60]} for i in indicators]
        return {
            "table_count": len(tables),
            "tables": tables[:30],
            "datasets": ds_info[:10],
            "indicators": ind_info[:20],
        }

    def explore_table(table_name: str) -> dict:
        """查看指定表的结构。优先使用数据集增强结构（含业务标注），
        回退到 JDBC 原始元数据。"""
        datasets = fetch_datasets_for_database(db_id)
        ds_map = {d.get("tableName", ""): d for d in datasets}
        ds = ds_map.get(table_name)

        if ds:
            try:
                from .tools import _fetch_dataset_structure_inner
                structure = _fetch_dataset_structure_inner(ds.get("id"))
                columns = structure.get("columns", [])
                col_info = []
                for c in columns:
                    col_info.append({
                        "name": c.get("columnName", ""),
                        "type": c.get("dataType", ""),
                        "comment": (c.get("annotation", "")
                                   or c.get("businessMeaning", "")
                                   or c.get("comment", "")),
                        "isPrimaryKey": c.get("isPrimaryKey", False),
                        "category": c.get("dataCategory", ""),
                    })
                return {
                    "tableName": structure.get("tableName", table_name),
                    "columnCount": len(col_info),
                    "columns": col_info,
                    "datasetName": ds.get("name", table_name),
                    "description": (ds.get("description", "") or "")[:150],
                }
            except Exception:
                pass

        structure = fetch_table_structure(db_id, table_name)
        columns = structure.get("columns", [])
        col_info = []
        for c in columns:
            col_info.append({
                "name": c.get("columnName", ""),
                "type": c.get("dataType", ""),
                "comment": c.get("comment", ""),
                "isPrimaryKey": c.get("isPrimaryKey", False),
            })
        return {
            "tableName": structure.get("tableName", table_name),
            "columnCount": len(col_info),
            "columns": col_info,
        }

    return {
        "list_tables": list_tables,
        "explore_table": explore_table,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 1：编排者（Orchestrator）— 委托 orchestrator.py 专业智能体
# ═══════════════════════════════════════════════════════════════════════════

async def orchestrator_node(state: ReactWorkflowState, config: RunnableConfig) -> ReactWorkflowState:
    """编排者节点：分析问题，动态规划执行路径。

    采用两层判断：
    1. 前置关键词兜底 — 快速识别明确不涉及数据的通用问题
    2. **委托 orchestrator.py 专业智能体** — 调用 LLM 进行意图识别和路径规划

    Args:
        state:  工作流状态
        config: LangGraph 运行配置（含 llm_call_fn）

    Returns:
        更新后的状态（含 route 决策）
    """
    from .orchestrator import build_orchestrator_prompt, apply_orchestrator_result
    llm_call_fn = _get_llm(config)
    steps = list(state.get("steps", []))
    question = state["question"]
    database_id = state.get("database_id", "")
    database_name = state.get("database_name", "")
    attachment_text = (state.get("attachment_text") or "").strip()

    _add_step(steps, 1, "智能编排", "in_progress",
              detail="正在分析问题，规划执行路径...")

    # ══════════════════════════════════════════════════════════════════
    # 第一层：前置关键词兜底（不依赖 LLM，确保可靠性）
    # ══════════════════════════════════════════════════════════════════
    _NON_DATA_KEYWORDS = [
        "地理位置", "位置信息", "在哪儿", "在哪里", "坐标", "经纬度",
        "北纬", "东经", "南纬", "西经", "经度", "纬度",
        "地图", "标注", "属于哪个", "哪个省", "哪个市", "哪个国家",
        "今天天气", "天气预报", "多少度", "天气如何", "今天几号",
        "星期几", "现在几点", "当前时间",
        "你是谁", "你能做什么", "你会什么", "介绍一下自己",
        "你的功能", "你的能力",
        "什么是", "的概念", "的定义", "什么意思",
        "解释一下", "说明一下",
        "怎么用", "如何使用", "帮助",
    ]
    q_lower = question.lower()
    is_clearly_non_data = any(kw in q_lower for kw in _NON_DATA_KEYWORDS)

    if is_clearly_non_data:
        route = "knowledge"
        plan = "检测到通用问题关键词，无需查询数据库"
        _add_step(steps, 1, "智能编排", "completed",
                  detail=f"路径: {route} | 关键词预检 → 知识问答",
                  thinking=f"【编排决策】\n问题类型: 通用知识问答\n关键词匹配: 命中非数据查询模式\n路径: knowledge")
        return {**state, "steps": steps, "route": route, "plan": plan,
                "need_chart": False, "need_conclusion": True}

    # ══════════════════════════════════════════════════════════════════
    # 第二层：委托 orchestrator.py 专业智能体进行 LLM 智能路由
    # ══════════════════════════════════════════════════════════════════
    # 构建 EvaluationState 以调用 orchestrator.py 的接口
    es = EvaluationState(
        question=question,
        database_id=database_id,
        database_name=database_name,
    )
    es.steps = []
    es.attachment_text = attachment_text

    # 使用 orchestrator.py 的专业 prompt（含数据集、指标上下文的动态构建）
    sys_prompt, usr_prompt = build_orchestrator_prompt(es)

    # ── 注入附件文本 ──
    if attachment_text:
        usr_prompt = (
            f"用户上传了一份参考文档，以下为其内容：\n\n"
            f"---\n{attachment_text[:5000]}\n---\n\n"
            f"用户问题：{usr_prompt}"
        )

    route = "knowledge"
    plan = ""
    need_chart = False
    need_conclusion = True
    intent = ""
    query_type = ""
    database_type = ""

    try:
        response = await llm_call_fn(sys_prompt, usr_prompt)
        # 委托 orchestrator.py 解析 LLM 响应
        es = apply_orchestrator_result(es, response)

        intent = es.intent or ""
        plan = es.analysis_plan or ""
        need_conclusion = es.entities.get("need_conclusion", True)
        need_chart = es.entities.get("need_chart", False)
        query_type = es.entities.get("query_type", "")

        # 将 orchestrator 的 query_type 映射为 React workflow 的 route
        if query_type in ("general_analysis",):
            route = "knowledge"
        elif query_type == "combat_effectiveness":
            # 作战效能分析: 有数据源走专用智能体，无数据源走 knowledge
            route = "combat_effectiveness" if database_id else "knowledge"
        elif query_type == "air_superiority":
            # 制空权分析: 有数据源走专用智能体，无数据源走 knowledge
            route = "air_superiority" if database_id else "knowledge"
        else:
            # data_query 或未识别: 有数据源走 data_query
            route = "data_query" if database_id else "knowledge"

        logger.info(f"编排决策(委托 orchestrator.py): route={route}, query_type={query_type}, plan={plan[:80]}")
    except Exception as e:
        logger.warning(f"编排者 LLM 调用失败: {e}")
        route = "data_query" if database_id else "knowledge"
        plan = f"编排者调用失败，使用{'数据查询' if database_id else '知识问答'}兜底"

    # ══════════════════════════════════════════════════════════════════
    # 第三层：路由修正（确保有数据源时优先走 data_query）
    # ══════════════════════════════════════════════════════════════════
    if route == "knowledge" and database_id and not is_clearly_non_data:
        route = "data_query"
        plan = f"路由修正：已选数据源，强制走数据查询。原计划: {plan}"

    _add_step(steps, 1, "智能编排", "completed",
              detail=f"路径: {route} | {plan[:80]}",
              thinking=f"【编排决策】\n路径: {route}\n意图: {intent}\n执行计划: {plan}\n"
                       f"需要图表: {'是' if need_chart else '否'}\n"
                       f"需要结论: {'是' if need_conclusion else '否'}")

    return {
        **state, "steps": steps, "route": route, "plan": plan,
        "need_chart": need_chart, "need_conclusion": need_conclusion,
        "intent": intent, "query_type": query_type, "database_type": database_type,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 路由函数
# ═══════════════════════════════════════════════════════════════════════════

def route_from_orchestrator(state: ReactWorkflowState) -> str:
    """编排者之后的条件路由"""
    route = state.get("route", "knowledge")
    db_id = state.get("database_id", "")
    if route == "combat_effectiveness" and db_id:
        return "combat_worker"
    if route == "air_superiority" and db_id:
        return "air_worker"
    if route == "data_query" and db_id:
        return "data_worker"
    return "knowledge_worker"


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2a：知识工作者（Knowledge Worker）— 委托 analyst.run_simple_analysis
# ═══════════════════════════════════════════════════════════════════════════

async def knowledge_worker_node(state: ReactWorkflowState, config: RunnableConfig) -> ReactWorkflowState:
    """知识工作者节点：委托 analyst.run_simple_analysis() 专业智能体。

    适用于：概念解释、知识问答、地理位置、天气等通用问题。
    不再使用内联 ReAct 循环，而是委托旧版 langgraph_workflow 中已验证的
    analyst 模块的纯问答能力。
    """
    from .analyst import run_simple_analysis
    llm_call_fn = _get_llm(config)
    steps = list(state.get("steps", []))
    question = state["question"]
    attachment_text = (state.get("attachment_text") or "").strip()

    _add_step(steps, 2, "知识分析", "in_progress",
              detail="正在调用分析智能体（analyst.run_simple_analysis）...")

    # 构建 EvaluationState 并委托给 analyst 模块
    es = EvaluationState(
        question=question,
        database_id=state.get("database_id", ""),
    )
    es.steps = []
    # 注入附件文本到问题中
    if attachment_text:
        es.question = (
            f"用户上传了一份参考文档，以下为其内容：\n\n"
            f"---\n{attachment_text[:5000]}\n---\n\n"
            f"用户问题：{question}"
        )

    es = await run_simple_analysis(es, llm_call_fn)

    # 合并 analyst 模块产出的步骤
    analyst_step_count = len(es.steps)
    steps.extend(es.steps)

    _add_step(steps, 2, "知识分析", "completed",
              detail=f"分析完成（委托 analyst 智能体，产出 {analyst_step_count} 子步骤）",
              thinking=f"【analyst 回答】\n{es.final_answer[:500]}")

    return {
        **state, "steps": steps,
        "knowledge_answer": es.final_answer,
        "final_answer": es.final_answer,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2b：作战效能分析（combat_worker）— 委托 combat_effectiveness_agent
# ═══════════════════════════════════════════════════════════════════════════

async def combat_worker_node(state: ReactWorkflowState, config: RunnableConfig) -> ReactWorkflowState:
    """作战效能分析节点：委托 combat_effectiveness_agent._legacy_run_stream()。

    使用预配置的 queries.json SQL 模板，逐条执行并通过 LLM 生成分析。
    对应旧版 langgraph_workflow 的 combat_agent_node。
    """
    from .combat_effectiveness_agent import _legacy_run_stream
    llm_call_fn = _get_llm(config)
    steps = list(state.get("steps", []))
    results_list = []
    final_answer = ""

    _add_step(steps, 1.3, "智能体选择", "completed",
              detail="已选择「作战效能分析」智能体")

    # 流式调用作战效能分析专用智能体
    async for event in _legacy_run_stream(
        state["question"],
        state.get("database_id", ""),
        llm_call_fn,
        state.get("need_conclusion", True),
    ):
        if event.get("type") == "step":
            steps.append(event["step"])
        elif event.get("type") == "result":
            results_list.append(event["result"])

    if results_list:
        last_result = results_list[-1]
        final_answer = last_result.get("final_answer", "")

    return {
        **state, "steps": steps,
        "result": results_list[-1] if results_list else {},
        "final_answer": final_answer,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2c：制空权分析（air_worker）— 委托 air_superiority_agent
# ═══════════════════════════════════════════════════════════════════════════

async def air_worker_node(state: ReactWorkflowState, config: RunnableConfig) -> ReactWorkflowState:
    """制空权分析节点：委托 air_superiority_agent._legacy_run_stream()。

    使用预配置的 air_queries.json SQL 模板，识别区域 → 注入占位符 →
    逐条执行 → 红蓝双方制空权对比分析。
    对应旧版 langgraph_workflow 的 air_agent_node。
    """
    from .air_superiority_agent import _legacy_run_stream
    llm_call_fn = _get_llm(config)
    steps = list(state.get("steps", []))
    results_list = []
    final_answer = ""

    _add_step(steps, 1.3, "智能体选择", "completed",
              detail="已选择「制空权分析」智能体")

    # 流式调用制空权分析专用智能体
    async for event in _legacy_run_stream(
        state["question"],
        state.get("database_id", ""),
        llm_call_fn,
        state.get("need_conclusion", True),
    ):
        if event.get("type") == "step":
            steps.append(event["step"])
        elif event.get("type") == "result":
            results_list.append(event["result"])

    if results_list:
        last_result = results_list[-1]
        final_answer = last_result.get("final_answer", "")

    return {
        **state, "steps": steps,
        "result": results_list[-1] if results_list else {},
        "final_answer": final_answer,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2d：数据工作者（Data Worker）— 完整 ReAct 循环
# ═══════════════════════════════════════════════════════════════════════════

_DATA_WORKER_EXPLORE_BACKSTORY = """你是数据探索专家，擅长探索数据库结构、理解表关系。

你的工作流程（ReAct 探索模式）：
1. THOUGHT: 思考需要了解数据库的哪些信息 → ACTION: list_tables 列出所有表
2. THOUGHT: 分析哪些表与用户问题相关 → ACTION: explore_table 逐一查看表结构
3. 探索完成（信息充足后），输出 FINAL_ANSWER 总结：发现了哪些表、推荐查什么表、
   以及建议如何生成 SQL。

重要：
- 你只负责探索和理解数据库结构，不编写 SQL，不执行查询！
- 如果表名/字段名与用户问题主题明显无关，直接在 FINAL_ANSWER 中说明
- 探索完成后，后续的 SQL 生成和数据分析将由专业智能体完成"""


async def data_worker_node(state: ReactWorkflowState, config: RunnableConfig) -> ReactWorkflowState:
    """数据工作者节点：两阶段处理。

    Phase 1: ReAct 自主探索数据库结构（list_tables + explore_table）
             让 LLM 动态决定看哪些表，而非固定关键词匹配。

    Phase 2: 委托专业智能体完成 SQL 生成、执行和分析
             1. text_to_sql.run_text_to_sql() → 生成 SQL
             2. tools.execute_sql_on_database() → 执行 SQL
             3. analyst.run_analyst() → 生成分析建议

    这样既保留了 ReAct 的灵活性（动态选表），又复用了已验证的专业智能体能力。
    """
    from .text_to_sql import run_text_to_sql
    from .analyst import run_analyst
    from .tools import (
        fetch_table_structure, _fetch_dataset_structure_inner,
        fetch_datasets_for_database, fetch_indicators_for_datasets,
        execute_sql_on_database, fetch_database_config,
    )
    llm_call_fn = _get_llm(config)
    steps = list(state.get("steps", []))
    question = state["question"]
    db_id = state.get("database_id", "")
    plan = state.get("plan", "")
    database_type = state.get("database_type", "")
    attachment_text = (state.get("attachment_text") or "").strip()

    # ══════════════════════════════════════════════════════════════════
    # Phase 1：ReAct 数据库结构探索
    # ══════════════════════════════════════════════════════════════════
    _add_step(steps, 2, "数据探索", "in_progress",
              detail="智能体正在自主探索数据库结构...")

    # 获取数据库类型配置
    try:
        db_config = await asyncio.get_event_loop().run_in_executor(
            None, fetch_database_config, db_id)
        if db_config:
            database_type = db_config.get("type", "") or database_type
    except Exception:
        pass

    # 构建探索阶段工具（仅 list_tables + explore_table，不含 run_sql）
    exploration_tools = _build_exploration_tools(db_id)

    # 构建探索阶段的上下文
    question_context = f"{question}\n\n编排建议: {plan}"
    if database_type:
        question_context += f"\n数据库类型: {database_type}"
    if attachment_text:
        question_context += (
            f"\n\n用户参考文档：\n---\n{attachment_text[:3000]}\n---"
        )

    explore_system_prompt = _REACT_SYSTEM_TEMPLATE.format(
        role="数据探索专家",
        goal="探索数据库结构，理解表关系，为后续 SQL 生成提供基础",
        backstory=_DATA_WORKER_EXPLORE_BACKSTORY,
        tools_desc=_EXPLORATION_TOOLS_DESC,
        question=question_context,
        max_turns=6,
    )

    # 收集探索阶段的步骤
    explored_tables = set()
    sub_step_counter = [1]

    def on_explore_trace(trace):
        """每轮探索行动时追加步骤记录"""
        if trace.get("type") == "action":
            action_name = trace.get("action", "")
            action_input = trace.get("action_input", {})
            observation = trace.get("observation", "")

            if action_name == "list_tables":
                desc = "列出数据表"
            elif action_name == "explore_table":
                table = action_input.get("table_name", "")
                desc = f"查看表结构: {table}"
                explored_tables.add(table)
            else:
                desc = f"执行: {action_name}"

            try:
                obs_data = json.loads(observation) if isinstance(observation, str) else observation
            except json.JSONDecodeError:
                obs_data = {}

            if action_name == "list_tables":
                detail = f"发现 {obs_data.get('table_count', 0)} 张数据表"
            elif action_name == "explore_table":
                detail = f"表 {action_input.get('table_name', '')} 共 {obs_data.get('columnCount', 0)} 列"
            else:
                detail = ""

            sub_step_num = 2 + sub_step_counter[0]
            _add_step(steps, sub_step_num, desc, "completed",
                      detail=detail,
                      thinking=f"思考: {trace.get('thought', '')[:200]}\n观察: {observation[:300]}")
            sub_step_counter[0] += 1

    explore_result = await _run_react_loop(
        system_prompt=explore_system_prompt,
        question=f"请探索数据库结构，为以下问题做准备：{question}\n编排建议: {plan}",
        tools=exploration_tools,
        llm_call_fn=llm_call_fn,
        max_turns=6,
        on_trace=on_explore_trace,
    )

    exploration_summary = explore_result["answer"]
    logger.info(f"Phase1 探索完成，探索了 {len(explored_tables)} 张表: {explored_tables}")

    # ══════════════════════════════════════════════════════════════════
    # Phase 2：委托专业智能体（text_to_sql + analyst）
    # ══════════════════════════════════════════════════════════════════
    _add_step(steps, 3, "生成SQL与分析", "in_progress",
              detail="探索完成，正在委托 text_to_sql + analyst 智能体...")

    # ── 构建 table_schemas（从探索阶段获取表结构）──
    table_schemas = []
    datasets = await asyncio.get_event_loop().run_in_executor(
        None, fetch_datasets_for_database, db_id)
    ds_map = {d.get("tableName", ""): d for d in datasets}

    for table_name in list(explored_tables):
        ds = ds_map.get(table_name)
        try:
            if ds:
                s_ = _fetch_dataset_structure_inner(ds.get("id"))
                s_["datasetName"] = ds.get("name", "")
                s_["description"] = ds.get("description", "")
            else:
                s_ = fetch_table_structure(db_id, table_name)
            table_schemas.append(s_)
        except Exception as e:
            logger.warning(f"获取表 {table_name} 结构失败: {e}")

    # 如果探索阶段没有探索任何表（LLM 判断数据不相关），直接返回
    if not table_schemas:
        _add_step(steps, 3, "生成SQL与分析", "skipped",
                  detail="探索结果：当前数据源主题与问题不相关，跳过数据库查询",
                  thinking=f"探索总结:\n{exploration_summary[:500]}")
        return {
            **state, "steps": steps,
            "data_final_answer": exploration_summary,
            "final_answer": exploration_summary,
            "raw_results": [], "generated_sql": "",
            "database_type": database_type,
        }

    # ── 构建 EvaluationState 并委托 text_to_sql 智能体生成 SQL ──
    es = EvaluationState(
        question=question,
        database_id=db_id,
        database_name=state.get("database_name", ""),
        database_type=database_type,
    )
    es.table_schemas = table_schemas
    es.indicator_defs = await asyncio.get_event_loop().run_in_executor(
        None, fetch_indicators_for_datasets,
        [d.get("id") for d in datasets])
    es.analysis_plan = plan
    es.entities = {
        "query_type": "data_query",
        "need_conclusion": state.get("need_conclusion", True),
        "need_chart": state.get("need_chart", False),
        "filters": "",
        "dimensions": [],
    }
    es.steps = []

    # Step 1: 委托 text_to_sql 生成 SQL
    es = await run_text_to_sql(es, llm_call_fn)
    steps.extend(es.steps)

    generated_sql = es.generated_sql

    # Step 2: 委托 tools 执行 SQL
    raw_results = []
    execution_error = ""
    if generated_sql and es.sql_valid:
        _add_step(steps, 4, "执行SQL查询", "in_progress",
                  detail="正在执行 text_to_sql 生成的 SQL...")
        exec_start = len(steps)
        result = execute_sql_on_database(db_id, generated_sql)
        if result.get("success"):
            raw_results = result.get("rows", result.get("data", result.get("results", [])))
            _add_step(steps, 4, "执行SQL查询", "completed",
                      detail=f"查询成功，返回 {len(raw_results)} 行数据")
        else:
            execution_error = result.get("message", "SQL执行失败")
            _add_step(steps, 4, "执行SQL查询", "error",
                      detail=f"SQL执行失败: {execution_error[:100]}")
        # 确保步骤编号不冲突
        exec_step_count = len(steps) - exec_start
    else:
        _add_step(steps, 4, "执行SQL查询", "skipped",
                  detail="SQL 无效或未生成")
        raw_results = []
        execution_error = "SQL 生成失败"

    # Step 3: 委托 analyst 智能体生成分析建议
    es.raw_results = raw_results
    es.execution_error = execution_error
    es.generated_sql = generated_sql
    es.steps = []

    es = await run_analyst(es, llm_call_fn)
    steps.extend(es.steps)

    final_answer = es.final_answer

    _add_step(steps, 3, "生成SQL与分析", "completed",
              detail=f"SQL {'生成成功' if generated_sql else '未生成'}，"
                     f"分析{'完成' if final_answer else '未生成'}")

    # 构建探索阶段的思考总结
    thinking_parts = [f"【Phase1 探索总结】\n{exploration_summary[:500]}"]
    thinking = "\n\n".join(thinking_parts)

    return {
        **state, "steps": steps,
        "data_react_traces": explore_result["traces"],
        "data_final_answer": final_answer,
        "generated_sql": generated_sql,
        "raw_results": raw_results,
        "final_answer": final_answer,
        "database_type": database_type,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 3：综合者（Synthesizer）— 可选的最终综合
# ═══════════════════════════════════════════════════════════════════════════

_SYNTHESIZER_PROMPT = """# 角色: 综合评估专家
# 目标: 将中间分析结果综合为结构清晰的最终回答

你是综合评估专家。请根据以下信息生成最终回答。

## 用户问题
{question}

## 分析结果
{analysis_result}

## 结果数据
{data_context}

## 要求
- 如果已有分析结果，保持其内容不变，仅做格式优化
- 如果分析结果中包含'数据不相关'的说明，保留该说明
- 输出结构清晰、语言简洁

直接输出最终回答文本。"""


async def synthesizer_node(state: ReactWorkflowState, config: RunnableConfig) -> ReactWorkflowState:
    """综合者节点：将中间结果综合为最终答案。

    负责：
    1. 图表规划（数据查询路径且有结果时，复用旧版 chart_agent）
    2. 组装前端所需的完整 result 字典，格式与旧版兼容
    """
    from .chart_agent import run_chart_agent
    llm_call_fn = _get_llm(config)
    steps = list(state.get("steps", []))
    final_answer = state.get("final_answer", "")
    route = state.get("route", "knowledge")
    question = state["question"]
    raw_results = state.get("raw_results", [])
    generated_sql = state.get("generated_sql", "")

    # 动态计算当前步骤编号：取已有步骤最大编号 + 1
    last_step_num = max((s["step"] for s in steps), default=1)

    # ── 图表规划（need_chart + 有结果时）──
    chart_config = {"vizType": "table"}
    need_chart = state.get("need_chart", False)
    if need_chart and route == "data_query" and raw_results:
        chart_step = last_step_num + 1
        _add_step(steps, chart_step, "图表规划", "in_progress",
                  detail="正在根据查询结果规划图表...")

        if raw_results and isinstance(raw_results[0], dict):
            columns = list(raw_results[0].keys())
            try:
                chart_config = await run_chart_agent(
                    columns=columns,
                    sample_rows=raw_results[:5],
                    total_rows=len(raw_results),
                    question=question,
                    llm_call_fn=llm_call_fn,
                )
                viz = chart_config.get("vizType", "table")
                if viz != "table":
                    _add_step(steps, chart_step, "图表规划", "completed",
                              detail=f"已规划 {viz} 图表")
                else:
                    _add_step(steps, chart_step, "图表规划", "skipped",
                              detail="数据不适合图表展示")
            except Exception as e:
                logger.warning(f"图表规划失败: {e}")
                _add_step(steps, chart_step, "图表规划", "error",
                          detail=f"图表规划失败: {str(e)[:80]}")
        else:
            _add_step(steps, chart_step, "图表规划", "skipped",
                      detail="数据格式不支持图表")
        synth_step = chart_step + 1
    else:
        synth_step = last_step_num + 1

    _add_step(steps, synth_step, "综合输出", "in_progress",
              detail="正在整理输出结果...")

    # ── 作战效能/制空权分支：worker 节点已设置 result，直接透传 ──
    if route in ("combat_effectiveness", "air_superiority"):
        existing_result = state.get("result", {})
        _add_step(steps, synth_step, "综合输出", "completed",
                  detail="分析流程完成")
        return {**state, "steps": steps, "result": existing_result,
                "final_answer": final_answer or existing_result.get("final_answer", "")}

    # 构建与旧版 finalize_node 完全兼容的结果格式
    # 从 Data Worker 探索总结中提取分析思路
    sql_explanation = ""
    if route == "data_query":
        traces = state.get("data_react_traces", [])
        # 取探索阶段的最终总结作为 SQL 解释
        for t in reversed(traces):
            if t.get("type") == "final":
                sql_explanation = t.get("answer", t.get("thought", ""))[:300]
                break

    result = {
        "type": "data_query" if route == "data_query" else "general",
        "final_answer": final_answer or "分析完成",
        "analysis": final_answer or "分析完成",  # 兼容旧字段名
        "generatedSql": generated_sql,
        "sqlExplanation": sql_explanation,
        "rawResults": raw_results[:20],
        "totalRows": len(raw_results),
        "columns": [list(r.keys()) for r in raw_results[:1]][0] if raw_results else [],
        "intent": state.get("intent", ""),
        "query_type": "data_query" if route == "data_query" else "general_analysis",
        "need_conclusion": state.get("need_conclusion", True),
        "need_chart": need_chart,
        "database_used": state.get("database_id", ""),
        "database_name": state.get("database_name", ""),
        "chartConfig": chart_config if chart_config else None,
    }

    _add_step(steps, synth_step, "综合输出", "completed",
              detail="分析流程完成")

    return {**state, "steps": steps, "result": result, "final_answer": final_answer}


# ═══════════════════════════════════════════════════════════════════════════
# 图构建
# ═══════════════════════════════════════════════════════════════════════════

def build_react_workflow_graph() -> StateGraph:
    """构建多智能体 ReAct 工作流图。

    拓扑结构：

        orchestrator ──(route)──→ knowledge_worker ──→ synthesizer ──→ END
                             ├──→ combat_worker ──────→ synthesizer ──→ END
                             ├──→ air_worker ─────────→ synthesizer ──→ END
                             └──→ data_worker ────────→ synthesizer ──→ END

    关键区别：这不是固定管道，而是一条"决策→执行→综合"的动态路径。
    Data Worker 内部有自己的 ReAct 循环（Think→Act→Observe），
    可以自主决定探索哪些表、生成什么 SQL、是否需要重试。
    """
    graph = StateGraph(ReactWorkflowState)

    # 注册节点
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("knowledge_worker", knowledge_worker_node)
    graph.add_node("combat_worker", combat_worker_node)
    graph.add_node("air_worker", air_worker_node)
    graph.add_node("data_worker", data_worker_node)
    graph.add_node("synthesizer", synthesizer_node)

    # 声明边
    graph.set_entry_point("orchestrator")

    # 编排者 → 条件路由到各智能体
    graph.add_conditional_edges("orchestrator", route_from_orchestrator, {
        "knowledge_worker": "knowledge_worker",
        "combat_worker": "combat_worker",
        "air_worker": "air_worker",
        "data_worker": "data_worker",
    })

    # 各工作者 → 综合者 → 结束
    graph.add_edge("knowledge_worker", "synthesizer")
    graph.add_edge("combat_worker", "synthesizer")
    graph.add_edge("air_worker", "synthesizer")
    graph.add_edge("data_worker", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph


# 编译一次，全局复用
_react_workflow_graph = build_react_workflow_graph().compile()


# ═══════════════════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════════════════

async def run_react_workflow(
    question: str,
    llm_call_fn,
    session_id: str = "",
    database_id: str = "",
    database_name: str = "",
    attachment_text: str = "",
):
    """对外暴露的多智能体 ReAct 工作流入口。

    使用 SSE 流式输出评估全流程。每个 yield 产生一个 SSE 事件字典。

    SSE 事件类型：
        {"type": "step",    "step": {...}}       # 进度步骤
        {"type": "result",  "result": {...}, ...} # 最终结果
        {"type": "error",   "message": "...", ...}# 错误事件

    Args:
        question:     用户输入的问题
        llm_call_fn:  LLM 调用函数 (async callable)
        session_id:   会话 ID
        database_id:  数据源 ID
        database_name:数据源名称
        attachment_text: 附件文本

    Yields:
        dict: SSE 事件
    """
    initial_state: ReactWorkflowState = {
        "question": question,
        "session_id": session_id,
        "database_id": database_id,
        "database_name": database_name,
        "attachment_text": attachment_text,
        **_empty_state(),
    }

    config = {"configurable": {"llm_call_fn": llm_call_fn}}
    seen_step_count = 0

    try:
        async for chunk in _react_workflow_graph.astream(
            initial_state, config, stream_mode="values"
        ):
            steps = chunk.get("steps", [])
            new_steps = steps[seen_step_count:]
            for s in new_steps:
                yield {"type": "step", "step": s}
                await asyncio.sleep(_YIELD_DELAY)
            seen_step_count = len(steps)

            # 输出结果
            result = chunk.get("result", {})
            if result:
                yield {
                    "type": "result",
                    "session_id": session_id,
                    "result": result,
                    "final_answer": chunk.get("final_answer", ""),
                }

            # 输出错误
            error = chunk.get("error", "")
            if error:
                yield {"type": "error", "message": error, "session_id": session_id}
                return

    except Exception as e:
        logger.error(f"ReAct workflow 失败: {e}", exc_info=True)
        yield {
            "type": "error",
            "message": f"评估流程异常: {str(e)[:500]}",
            "session_id": session_id,
        }
