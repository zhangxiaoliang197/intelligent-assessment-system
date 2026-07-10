"""
LangGraph 工作流引擎

═══════════════════════════════════════════════════════════════════════════
位置：
    本文件位于 qa-service/agents/ 目录下，是评估流程的"主调度器"。
    原有 workflow.py 使用手写 if/else + 状态机实现流程跳转，维护成本高、
    新增分支困难。本文件使用 LangGraph 的 StateGraph 声明式图结构重写了
    整套编排逻辑，节点定义清晰、路由规则可读、流式输出开箱即用。

架构 —— 图的节点拓扑（按分支展开）：
    StateGraph[WorkflowState]
        │
        ├── orchestrator_start_node    ← 入口：构建 LLM prompt
        ├── orchestrator_execute_node  ← 调用 LLM + 意图解析
        │       │
        │       ├─(combat_effectiveness)→ combat_agent_node → END
        │       ├─(air_superiority)     → air_agent_node    → END
        │       ├─(无数据源)            → simple_analysis_node → END
        │       └─(data_query)          → data_explore_node（主线继续）
        │                                      │
        ├── data_explore_node          ← 连接数据库，获取所有表名
        │                                      │
        ├── dataset_check_node         ← 查询数据集/指标管理模块
        │                                      │
        ├── table_select_node          ← 关键词匹配筛选相关表 + 读取表结构
        │                                      │
        ├── text_to_sql_start_node     ← 设置"生成SQL"步骤进度
        │                                      │
        ├── text_to_sql_execute_node   ← 调用 LLM 生成 SQL
        │                                      │
        ├── sql_execute_node           ← 在数据库上执行 SQL
        │                                      │
        │       ├─(need_chart+有数据)  → chart_agent_node  →（继续）
        │       └─(无需图表)           → analyst_start_node →（继续）
        │                                      │
        ├── analyst_start_node         ← 设置"分析建议"步骤进度
        │                                      │
        ├── analyst_execute_node       ← 调用 LLM 生成自然语言分析
        │                                      │
        └── finalize_node              ← 组装最终 result 字典 → END

SSE 流式输出机制：
    endpoint 中调用 run_langgraph_workflow()（本文件的公共 API），
    内部使用 graph.astream(state, config, stream_mode="values") 逐节点
    产生产出状态快照。每份快照中取出 steps 列表，计算增量步骤 yield 给
    前端 SSE 通道。每个步骤之间插入 _YIELD_DELAY 以保证前端有时间渲染。

相比于旧 workflow.py 的 LangGraph 收益：
    - 声明式图结构取代手写 if/else，新增分支只需 add_node + add_edge
    - 自动状态传递：WorkflowState 作为 TypedDict 在节点间自动合并
    - astream 内置流式支持，无需自建队列/回调
    - 编译后的图可复用，多请求共享同一个 _workflow_graph 实例
    - 条件边（conditional_edges）将路由逻辑与流程编排解耦
═══════════════════════════════════════════════════════════════════════════
"""
import asyncio
import json
import logging
import re
from typing import TypedDict, Annotated, Any, Optional

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig

from .state import EvaluationState

logger = logging.getLogger("evaluation.langgraph")

# ── 全局常量 ──────────────────────────────────────────────────────────────
# SSE 步骤间的最小间隔（秒），防止前端渲染跟不上数据推送速度
_YIELD_DELAY = 0.25
# 数据库表列表查询的超时时间（秒）
_DB_TIMEOUT = 8
# ───────────────────────────────────────────────────────────────────────────


class WorkflowState(TypedDict, total=False):
    """
    LangGraph 工作流状态 — 所有节点间传递共享数据的"最小单元"。

    total=False 表示所有字段可选：初始状态只需填入少数字段，
    各节点只覆写自己关心的键，LangGraph 自动 merge 到下一个节点。

    按"生命周期"分组说明如下：
    """

    # ── 输入字段（由调用方 run_langgraph_workflow 传入）──────────────
    question: str           # 用户输入的原始问题
    session_id: str         # 会话标识（用于 SSE session 匹配）
    database_id: str        # 用户选择的数据源 ID（可为空串 = 无数据源）
    database_name: str      # 用户选择的数据源名称（仅用于展示）

    # ── orchestrator 阶段产出（意图识别后写入）────────────────────────
    intent: str             # 大模型识别出的用户意图，如 "综合评估"
    analysis_plan: str      # 大模型生成的分步骤分析计划（自然语言）
    entities: dict          # 大模型提取的实体键值对，含 query_type / need_conclusion 等
    query_type: str         # 路由用查询类型: "data_query" | "combat_effectiveness" | "air_superiority"
    need_conclusion: bool   # 是否需要生成自然语言结论
    need_chart: bool        # 是否需要规划图表（影响 route_chart 路由）

    # ── 数据探查阶段产出 ─────────────────────────────────────────────
    database_tables: list   # 数据源中所有表的名称列表（字符串列表）
    table_schemas: list     # 筛选后各表的列结构字典列表
    dataset_defs: list      # 匹配到的数据集定义字典列表
    indicator_defs: list    # 匹配到的指标定义字典列表
    db_connected: bool      # 是否成功连接到数据源数据库

    # ── SQL 生成 + 执行阶段产出 ──────────────────────────────────────
    generated_sql: str      # LLM 生成的 SQL 语句
    sql_valid: bool         # SQL 生成器判定 SQL 是否有效（含安全检查）
    sql_retry_count: int    # SQL 重试次数（当前版本未使用，预留）
    sql_explanation: str    # SQL 的自然语言解释
    raw_results: list       # SQL 执行后返回的原始行数据（字典列表）
    execution_error: str    # SQL 执行失败时的错误信息

    # ── 图表阶段产出 ─────────────────────────────────────────────────
    chart_config: dict      # 图表配置（vizType / axes / ...），默认 {"vizType": "table"}

    # ── 分析 + 收尾阶段产出 ──────────────────────────────────────────
    final_answer: str       # LLM 生成的最终分析结论（自然语言）
    steps: list             # 前端展示用的步骤列表，每个元素为 {"step": float, "description": str, ...}
    result: dict            # 最终返回给前端的完整结果结构
    error: str              # 全局错误信息，非空时 SSE 推送 error 事件并终止

    # ── 内部传递字段（以下划线开头，仅在节点间传数据，不暴露给前端）──
    _sys_prompt: str        # orchestrator 构建的系统 prompt
    _usr_prompt: str        # orchestrator 构建的用户 prompt


# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def _empty_state() -> dict:
    """
    返回 WorkflowState 中所有非输入字段的默认值。

    用于 run_langgraph_workflow 初始化 initial_state 时合并，
    避免每个请求之间状态残留。
    """
    return {
        "intent": "",
        "analysis_plan": "",
        "entities": {},
        "query_type": "data_query",          # 默认按数据库查询处理
        "need_conclusion": True,              # 默认生成结论
        "need_chart": False,                  # 默认不生成图表
        "database_tables": [],
        "table_schemas": [],
        "dataset_defs": [],
        "indicator_defs": [],
        "db_connected": False,
        "generated_sql": "",
        "sql_valid": False,
        "sql_retry_count": 0,
        "sql_explanation": "",
        "raw_results": [],
        "execution_error": "",
        "chart_config": {},
        "final_answer": "",
        "steps": [],
        "result": {},
        "error": "",
        "_sys_prompt": "",
        "_usr_prompt": "",
    }


def _add_step(steps, step_num, description, status="pending",
              detail="", thinking="", progress=None):
    """
    向 steps 列表追加一条前端可渲染的步骤记录。

    Args:
        steps:      状态中的 steps 列表（原地修改）
        step_num:   步骤编号（支持小数，如 1.1 表示子步骤）
        description:前端展示的步骤标题
        status:     "pending" / "in_progress" / "completed" / "error" / "skipped"
        detail:     步骤附带的详细描述文本
        thinking:   大模型的"思维链"原文，前端可折叠展示
        progress:   0-100 的进度百分比（None 时根据 status 自动推算）
    """
    if progress is None:
        # 根据状态自动推算进度：completed→100, in_progress→50, 其他→0
        progress = 100 if status == "completed" else (50 if status == "in_progress" else 0)
    steps.append({
        "step": step_num,
        "description": description,
        "status": status,
        "detail": detail,
        "thinking": thinking,
        "progress": progress,
    })


def _pick_relevant_tables(all_tables, analysis_plan, question, max_tables=5):
    """
    从全部表名中筛选最相关的表（最多 max_tables 张），用于减少后续 LLM prompt 长度。

    评分策略（多项加分叠加）：
        1. 表名出现在 analysis_plan 原文中 → +100
        2. 表关键字（分词后）与问题关键词重合 → +20/词
        3. 表关键字（分词后）与分析计划关键词重合 → +10/词
        4. analysis_plan 中出现"表 xxx"或"TABLE xxx"格式 → +200
        5. 若无匹配 → 取非系统表（不以 ass_/sys_ 开头）的前 max_tables 张

    Args:
        all_tables:    所有表名的字符串列表
        analysis_plan: orchestrator 生成的分析计划文本
        question:      用户原始问题文本
        max_tables:    最多返回的表数量（默认 5）

    Returns:
        排序后的表名列表（最多 max_tables 个元素）
    """
    if not all_tables:
        return []
    if len(all_tables) <= max_tables:
        return all_tables  # 表本身就不多，全返回

    scores = {t: 0 for t in all_tables}  # 每个表的累积得分

    # ── 策略 1：表名直接出现在分析计划中 → +100 ──
    plan_lower = analysis_plan.lower()
    for t in all_tables:
        if t.lower() in plan_lower:
            scores[t] += 100

    # ── 策略 2+3：关键词匹配（问题 + 分析计划）─────
    for t in all_tables:
        # 分词：将下划线分隔的表名拆成关键词集合
        keywords = set(t.lower().replace("_", " ").split())
        # 去掉常见表前缀后得到"业务名"（如 ass_mission → mission）
        base_name = t.lower()
        for prefix in ["ass_", "test_", "sys_", "tbl_"]:
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
                break
        # 匹配用户问题中的词（至少2字符，避免匹配到"的"/"了"等虚词）
        for word in question.lower().split():
            word = word.strip(",，。.!！?？()（）")
            if len(word) >= 2 and (word in keywords or word in base_name):
                scores[t] += 20
        # 匹配分析计划中的词
        for word in plan_lower.split():
            word = word.strip(",，。.!！?？()（）")
            if len(word) >= 2 and (word in keywords or word in base_name):
                scores[t] += 10

    # ── 策略 4：分析计划中的"表 xxx"格式 → +200 ──
    table_pattern = re.findall(
        r'(?:表\s*|TABLE\s+)([a-zA-Z_][a-zA-Z0-9_]*)',
        analysis_plan, re.IGNORECASE
    )
    for match in table_pattern:
        for t in all_tables:
            if t.lower() == match.lower():
                scores[t] += 200

    # ── 排序并取前 max_tables ──
    sorted_tables = sorted(scores.items(), key=lambda x: -x[1])
    top = [t for t, s in sorted_tables if s > 0]  # 仅保留有得分的
    if not top:
        # 完全没有匹配 → 优先取非系统表
        non_sys = [t for t in all_tables
                   if not t.startswith("ass_") and not t.startswith("sys_")]
        top = non_sys[:max_tables] if non_sys else all_tables[:max_tables]
    return top[:max_tables]


def _get_llm_call_fn(config: RunnableConfig):
    """
    从 LangGraph 的 RunnableConfig 中提取 LLM 调用函数。

    调用方在 config["configurable"]["llm_call_fn"] 中注入，
    这样每个节点都可以通过 config 拿到同一个 LLM 调用入口，
    避免在模块级别耦合具体模型实例。
    """
    return config.get("configurable", {}).get("llm_call_fn")


# ═══════════════════════════════════════════════════════════════════════════
# 节点 1：orchestrator（意图识别）
#   拆分为 start + execute 两个节点，start 先推送进度让前端立即响应，
#   execute 再实际调用 LLM。避免 LLM 耗时期间前端无反馈。
# ═══════════════════════════════════════════════════════════════════════════

async def orchestrator_start_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    构建 orchestrator 的 LLM prompt 并添加初始进度步骤。

    对应 DAG 位置：入口节点 → orchestrator_execute_node
    本节点不调用 LLM，仅做 prompt 构建 + 进度推送，响应极快（<1ms）。

    Args:
        state:  当前工作流状态（含 question / database_id / database_name）
        config: LangGraph 运行时配置

    Returns:
        更新后的状态，添加 _sys_prompt / _usr_prompt 和初始进度步骤
    """
    from .orchestrator import build_orchestrator_prompt
    steps = list(state.get("steps", []))  # 浅拷贝，避免修改上游引用

    # 步骤 1：意图识别 — 标记为进行中
    _add_step(steps, 1, "分析问题意图", "in_progress",
              detail="正在调用大模型分析用户问题...")
    # 子步骤 1.1：大模型调用 — 标记为进行中
    _add_step(steps, 1.1, "大模型调用", "in_progress",
              detail="正在将问题发送给大模型进行意图识别...",
              thinking=f"用户问题: {state['question'][:300]}")

    # 构建 orchestrator 的 system / user prompt（复用已有模块）
    es = EvaluationState(
        question=state["question"],
        database_id=state.get("database_id", ""),
        database_name=state.get("database_name", ""),
    )
    es.steps = []  # 清空，我们不使用 EvaluationState 的 steps
    sys_prompt, usr_prompt = build_orchestrator_prompt(es)

    return {
        **state, "steps": steps,
        "_sys_prompt": sys_prompt, "_usr_prompt": usr_prompt,
    }


async def orchestrator_execute_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    调用 LLM 进行意图识别，解析返回结果，并执行路由修正逻辑。

    对应 DAG 位置：orchestrator_start_node → 本节点 → 条件路由

    核心职责：
        1. 调用 LLM 获取意图 + 分析计划
        2. 解析 LLM 返回的 JSON 意图结果
        3. 路由修正：如果用户已选择数据源但 LLM 判为 general_analysis，
           强制改为 data_query
        4. 作战效能降级：如果没有"整体评估"表述，降级为基础查询
        5. 汇总步骤状态供前端展示

    Args:
        state:  当前状态（含 _sys_prompt / _usr_prompt）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 intent / analysis_plan / query_type 等路由关键字段
    """
    from .orchestrator import apply_orchestrator_result
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))
    sys_prompt = state.get("_sys_prompt", "")
    usr_prompt = state.get("_usr_prompt", "")

    # ── 调用 LLM ──
    try:
        response = await llm_call_fn(sys_prompt, usr_prompt)
    except Exception as e:
        # LLM 调用失败 → 标记错误，降级为 general_analysis
        _add_step(steps, 1.1, "大模型调用", "error",
                  detail=f"调用失败: {str(e)[:100]}")
        return {
            **state, "steps": steps,
            "query_type": "general_analysis",
            "error": f"LLM调用失败: {str(e)[:100]}",
        }

    # ── LLM 调用成功，标记子步骤完成 ──
    _add_step(steps, 1.1, "大模型调用", "completed",
              detail="大模型返回意图分析结果",
              thinking=f"【模型原始响应】\n{response[:800]}")

    # ── 解析 LLM 返回的意图结果 ──
    es = EvaluationState(
        question=state["question"],
        database_id=state.get("database_id", ""),
        database_name=state.get("database_name", ""),
    )
    es.steps = []
    es = apply_orchestrator_result(es, response)
    intent = es.intent or "综合评估"       # 兜底意图
    query_type = es.entities.get("query_type", "")
    need_conclusion = es.entities.get("need_conclusion", True)
    need_chart = es.entities.get("need_chart", False)

    # ── 路由修正 1：有数据源但 LLM 判为通用分析 → 强制切为数据查询 ──
    if state.get("database_id") and query_type == "general_analysis":
        query_type = "data_query"
        es.entities["query_type"] = "data_query"
        _add_step(steps, 1.2, "路由修正", "completed",
                  detail="已选择数据源，自动切换为数据库查询模式")

    # ── 路由修正 2：作战效能降级──
    # 如果 LLM 判为 combat_effectiveness 但用户问题中没有"整体评估"类关键词，
    # 说明用户只是问具体数据而非整体评估，降级为 data_query
    if query_type == "combat_effectiveness":
        q = state["question"]
        overall_kw = ["整个推演", "整个作战", "整体评估", "综合评估",
                      "全过程", "整体战", "整体作", "对整体", "整个方案"]
        if not any(kw in q for kw in overall_kw):
            query_type = "data_query"
            es.entities["query_type"] = "data_query"
            _add_step(steps, 1.2, "路由修正", "completed",
                      detail="未检测到整体评估表述，降级为基础查询")

    # ── 标记步骤 1 完成，附带思维链 ──
    _add_step(steps, 1, "分析问题意图", "completed",
              detail=f"意图: {intent} | 查询模式: {query_type}",
              thinking=(
                  f"【意图识别】\n问题类型: {intent}\n查询模式: {query_type}\n"
                  f"需要结论: {'是' if need_conclusion else '否'}\n"
                  f"【分析计划】\n{es.analysis_plan[:300]}"
              ))

    return {
        **state, "steps": steps,
        "intent": intent, "analysis_plan": es.analysis_plan,
        "entities": es.entities, "query_type": query_type,
        "need_conclusion": need_conclusion, "need_chart": need_chart,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 路由函数 1：按意图分流
# ═══════════════════════════════════════════════════════════════════════════

def route_by_intent(state: WorkflowState) -> str:
    """
    根据 orchestrator 识别出的 query_type 决定下一个节点。

    路由规则（优先级从高到低）：
        - "combat_effectiveness" → combat_agent（作战效能分析专用智能体）
        - "air_superiority"       → air_agent（制空权分析专用智能体）
        - 无 database_id         → simple_analysis（无数据源，走通用分析）
        - 其他（含 data_query）   → data_explore（有数据源，走标准 SQL 管线）

    Args:
        state: 当前状态（含 query_type / database_id）

    Returns:
        下一个节点的名称字符串（必须与 add_node 中注册的名称一致）
    """
    query_type = state.get("query_type", "data_query")
    if query_type == "combat_effectiveness":
        return "combat_agent"
    if query_type == "air_superiority":
        return "air_agent"
    if not state.get("database_id"):
        return "simple_analysis"
    return "data_explore"


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2a：作战效能分析（combat_agent）
# ═══════════════════════════════════════════════════════════════════════════

async def combat_agent_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    作战效能分析专用智能体节点。

    对应 DAG 位置：orchestrator_execute →（路由）→ 本节点 → END
    本节点是终端分支，执行完毕后直接结束工作流。

    流程：
        1. 标记"已选择作战效能分析智能体"
        2. 调用 combat_effectiveness_agent 模块的 run_stream，
           逐事件收集步骤和结果
        3. 取最后一个 result 的 final_answer 作为输出

    Args:
        state:  当前状态（含 question / database_id / need_conclusion）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 steps / result / final_answer
    """
    from .combat_effectiveness_agent import run_stream as combat_stream
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))
    results = []
    final_answer = ""

    _add_step(steps, 1.3, "智能体选择", "completed",
              detail="已选择「作战效能分析」智能体")

    # 流式调用作战效能分析，逐事件收集
    async for event in combat_stream(
        state["question"], state.get("database_id", ""),
        llm_call_fn, state.get("need_conclusion", True),
    ):
        if event.get("type") == "step":
            steps.append(event["step"])
        elif event.get("type") == "result":
            results.append(event["result"])

    # 取最后一个结果作为最终输出
    if results:
        final_answer = results[-1].get("final_answer", "")

    return {
        **state, "steps": steps,
        "result": results[-1] if results else {},
        "final_answer": final_answer,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2b：制空权分析（air_agent）
# ═══════════════════════════════════════════════════════════════════════════

async def air_agent_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    制空权分析专用智能体节点。

    对应 DAG 位置：orchestrator_execute →（路由）→ 本节点 → END
    结构与 combat_agent_node 完全对称，仅使用的分析模块不同。

    Args:
        state:  当前状态（含 question / database_id / need_conclusion）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 steps / result / final_answer
    """
    from .air_superiority_agent import run_stream as air_stream
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))
    results = []
    final_answer = ""

    _add_step(steps, 1.3, "智能体选择", "completed",
              detail="已选择「制空权分析」智能体")

    # 流式调用制空权分析，逐事件收集
    async for event in air_stream(
        state["question"], state.get("database_id", ""),
        llm_call_fn, state.get("need_conclusion", True),
    ):
        if event.get("type") == "step":
            steps.append(event["step"])
        elif event.get("type") == "result":
            results.append(event["result"])

    if results:
        final_answer = results[-1].get("final_answer", "")

    return {
        **state, "steps": steps,
        "result": results[-1] if results else {},
        "final_answer": final_answer,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2c：无数据源通用分析（simple_analysis）
# ═══════════════════════════════════════════════════════════════════════════

async def simple_analysis_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    无数据源模式下的通用分析节点。

    对应 DAG 位置：orchestrator_execute →（路由）→ 本节点 → END
    当用户未选择数据源（database_id 为空）时走此分支。
    不涉及数据库操作，仅用 LLM 生成自然语言回答。

    Args:
        state:  当前状态（含 question）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 steps / final_answer / result
    """
    from .analyst import run_simple_analysis
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))

    es = EvaluationState(
        question=state["question"],
        database_id=state.get("database_id", ""),
    )
    es.steps = []
    es = await run_simple_analysis(es, llm_call_fn)
    steps.extend(es.steps)  # 合并 analyst 模块产出的步骤

    return {
        **state, "steps": steps,
        "final_answer": es.final_answer,
        "result": {"type": "general", "final_answer": es.final_answer},
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 3：数据源探查（data_explore）
# ═══════════════════════════════════════════════════════════════════════════

async def data_explore_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    连接数据源数据库，获取所有表的名称列表。

    对应 DAG 位置：orchestrator_execute →（路由）→ 本节点 → dataset_check_node
    这是标准 SQL 管线的第一个节点。

    实现细节：
        - 使用 run_in_executor 将同步的 fetch_database_tables 放到线程池执行
        - 设置 _DB_TIMEOUT 超时，防止阻塞整个工作流
        - 结果写入 database_tables 和 db_connected 字段

    Args:
        state:  当前状态（含 database_id）
        config: 运行时配置

    Returns:
        更新后的状态，写入 database_tables / db_connected / steps
    """
    from .tools import fetch_database_tables
    steps = list(state.get("steps", []))
    _add_step(steps, 2, "数据源探查", "in_progress",
              detail="正在连接数据源查询数据表...")

    all_tables = []
    db_connected = False
    db_id = state.get("database_id", "")

    try:
        loop = asyncio.get_event_loop()
        # 将同步阻塞调用放到线程池，避免阻塞事件循环
        all_tables = await asyncio.wait_for(
            loop.run_in_executor(None, fetch_database_tables, db_id),
            timeout=_DB_TIMEOUT
        )
        db_connected = bool(all_tables)  # 有表返回则视为连接成功
    except asyncio.TimeoutError:
        logger.warning("获取表列表超时")
    except Exception as e:
        logger.warning(f"获取表列表失败: {e}")

    _add_step(steps, 2, "数据源探查", "completed",
              detail=f"发现 {len(all_tables)} 张数据表")

    return {**state, "steps": steps, "database_tables": all_tables, "db_connected": db_connected}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 4：数据集 + 指标检查（dataset_check）
# ═══════════════════════════════════════════════════════════════════════════

async def dataset_check_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    从数据集管理和指标管理模块查询关联信息。

    对应 DAG 位置：data_explore_node → 本节点 → table_select_node

    流程：
        1. 根据 database_id 查询关联的数据集定义
        2. 根据数据集 ID 列表查询关联的指标定义
        3. 从数据集定义中提取 tableName，构建 dataset_table_map
        4. 如果数据库未连接但有数据集，用数据集中的表名作为 database_tables

    Args:
        state:  当前状态（含 database_id / database_tables）
        config: 运行时配置

    Returns:
        更新后的状态，写入 dataset_defs / indicator_defs / database_tables（可能扩充）
    """
    from .tools import fetch_datasets_for_database, fetch_indicators_for_datasets
    steps = list(state.get("steps", []))
    _add_step(steps, 3, "检查数据集和指标", "in_progress",
              detail="正在从数据集管理和指标管理中查找相关信息...")

    datasets_found = []
    indicators_found = []
    db_id = state.get("database_id", "")

    # ── 查询数据集 ──
    try:
        datasets_found = fetch_datasets_for_database(db_id)
    except Exception as e:
        logger.warning(f"获取数据集失败: {e}")

    if datasets_found:
        ds_names = ", ".join(ds.get("name", "") for ds in datasets_found[:5])
        _add_step(steps, 3.1, "查询数据集", "completed",
                  detail=f"发现 {len(datasets_found)} 个数据集: {ds_names}")
    else:
        _add_step(steps, 3.1, "查询数据集", "completed", detail="未找到关联数据集")

    # ── 查询指标 ──
    try:
        ds_ids = [ds.get("id") for ds in datasets_found]
        indicators_found = fetch_indicators_for_datasets(ds_ids)
    except Exception as e:
        logger.warning(f"获取指标失败: {e}")

    if indicators_found:
        ind_names = ", ".join(ind.get("name", "") for ind in indicators_found[:5])
        _add_step(steps, 3.2, "查询指标", "completed",
                  detail=f"发现 {len(indicators_found)} 个指标: {ind_names}")
    else:
        _add_step(steps, 3.2, "查询指标", "completed", detail="未找到关联指标")

    # ── 构建 表名→数据集 映射（供后续 table_select 使用）──
    dataset_table_map = {}
    for ds in datasets_found:
        tn = ds.get("tableName", "")
        if tn:
            dataset_table_map[tn] = ds

    # 如果数据库未连接但数据集中有表名定义，用数据集表名填充 database_tables
    all_tables = state.get("database_tables", [])
    db_connected = state.get("db_connected", False)
    if not db_connected and dataset_table_map:
        all_tables = list(dataset_table_map.keys())

    _add_step(steps, 3, "检查数据集和指标", "completed",
              detail=f"数据集 {len(datasets_found)} 个 | 指标 {len(indicators_found)} 个")

    return {
        **state, "steps": steps,
        "database_tables": all_tables,
        "dataset_defs": datasets_found,
        "indicator_defs": indicators_found,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 5：选表 + 读表结构（table_select）
# ═══════════════════════════════════════════════════════════════════════════

async def table_select_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    从全部表中筛选相关表并读取每张表的列结构。

    对应 DAG 位置：dataset_check_node → 本节点 → text_to_sql_start_node

    流程：
        1. 构建 dataset_table_map（表名 → 数据集定义）
        2. 用 _pick_relevant_tables 进行关键词匹配筛选
        3. 将数据集关联的表也加入（如果没有超出限制）
        4. 对每张选中的表，优先从数据集定义读取结构，次选实时连接数据库读取
        5. 将表结构存入 table_schemas

    Args:
        state:  当前状态（含 database_tables / dataset_defs / analysis_plan / question）
        config: 运行时配置

    Returns:
        更新后的状态，写入 table_schemas / steps
    """
    from .tools import fetch_table_structure, _fetch_dataset_structure_inner
    steps = list(state.get("steps", []))
    all_tables = state.get("database_tables", [])
    db_id = state.get("database_id", "")
    db_connected = state.get("db_connected", False)
    analysis_plan = state.get("analysis_plan", "")
    question = state.get("question", "")

    _add_step(steps, 4, "选择数据表", "in_progress",
              detail="正在根据分析计划和数据集信息筛选相关数据表...")

    # ── 构建表名→数据集映射 ──
    dataset_table_map = {}
    for ds in state.get("dataset_defs", []):
        tn = ds.get("tableName", "")
        if tn:
            dataset_table_map[tn] = ds

    # ── 关键词匹配筛选 ──
    relevant = _pick_relevant_tables(all_tables, analysis_plan, question)
    # 将数据集中的表也加入（若未超出限制），确保有结构定义的优先
    for t in list(all_tables):
        if t in dataset_table_map and t not in relevant:
            if len(relevant) < 6:
                relevant.append(t)

    _add_step(steps, 4, "选择数据表", "completed",
              detail=f"选定 {len(relevant)} 张表: {', '.join(relevant)}")

    _add_step(steps, 4.1, "读取表结构", "in_progress",
              detail=f"正在读取 {len(relevant)} 张表的结构定义...")

    # ── 逐表读取结构 ──
    schemas = []
    for i, table_name in enumerate(relevant):
        ds = dataset_table_map.get(table_name)
        # 标记数据来源：数据集标注 / 实时读取 / 跳过
        source_tag = "数据集标注" if ds else ("实时读取" if db_connected else "跳过")
        try:
            if ds:
                # 优先从数据集管理模块读取（有业务标注）
                s_ = _fetch_dataset_structure_inner(ds.get("id"))
                s_["datasetName"] = ds.get("name", "")
                s_["description"] = ds.get("description", "")
            elif db_connected:
                # 数据库有连接但无数据集标注 → 实时读取
                s_ = fetch_table_structure(db_id, table_name)
            else:
                # 既无数据集也无连接 → 跳过
                continue
            schemas.append(s_)
            cols = s_.get("columns", [])
            _add_step(steps, 4.1, f"表结构 ({i+1}/{len(relevant)})", "completed",
                      detail=f"[{table_name}] {len(cols)} 列 ({source_tag})")
        except Exception as e:
            _add_step(steps, 4.1, f"表结构 ({i+1}/{len(relevant)})", "error",
                      detail=f"[{table_name}] 失败: {str(e)[:80]}")

    _add_step(steps, 4.1, "读取表结构", "completed",
              detail=f"已读取 {len(schemas)}/{len(relevant)} 张表")

    return {**state, "steps": steps, "table_schemas": schemas}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 6：Text-to-SQL（拆分为 start + execute 以支持流式进度推送）
# ═══════════════════════════════════════════════════════════════════════════

async def text_to_sql_start_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    设置"生成SQL"步骤的初始进度。

    对应 DAG 位置：table_select_node → 本节点 → text_to_sql_execute_node
    不调用 LLM，仅推送进度步骤，前端立刻可见。

    Args:
        state:  当前状态
        config: 运行时配置

    Returns:
        更新后的状态（仅 steps 有变化）
    """
    steps = list(state.get("steps", []))
    schemas = state.get("table_schemas", [])
    _add_step(steps, 5, "生成SQL", "in_progress",
              detail=f"正在基于 {len(schemas)} 张表结构生成SQL查询...")
    return {**state, "steps": steps}


async def text_to_sql_execute_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    调用 LLM 生成 SQL 查询语句。

    对应 DAG 位置：text_to_sql_start_node → 本节点 → sql_execute_node

    将表结构、指标定义、分析计划等信息组装为 prompt 送入 LLM，
    由 text_to_sql 模块完成 SQL 生成 + 安全检查。

    Args:
        state:  当前状态（含 question / table_schemas / indicator_defs / analysis_plan）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 generated_sql / sql_valid / sql_explanation / steps
    """
    from .text_to_sql import run_text_to_sql
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))
    schemas = state.get("table_schemas", [])

    # 组装给 text_to_sql 模块的状态
    es = EvaluationState(
        question=state["question"],
        database_id=state.get("database_id", ""),
    )
    es.table_schemas = schemas
    es.indicator_defs = state.get("indicator_defs", [])
    es.analysis_plan = state.get("analysis_plan", "")
    es.entities = state.get("entities", {})
    es.steps = []

    es = await run_text_to_sql(es, llm_call_fn)
    steps.extend(es.steps)  # 合并 text_to_sql 内部产出的子步骤

    return {
        **state, "steps": steps,
        "generated_sql": es.generated_sql,
        "sql_valid": es.sql_valid,
        "sql_explanation": es.sql_explanation,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 7：SQL 执行（sql_execute）
# ═══════════════════════════════════════════════════════════════════════════

async def sql_execute_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    在目标数据库上执行生成的 SQL，收集查询结果。

    对应 DAG 位置：text_to_sql_execute_node → 本节点 → 条件路由

    跳过条件（标记为 skipped）：
        - sql_valid 为 False 或 SQL 为空 → 无需执行
        - db_connected 为 False → 数据库未连接

    Args:
        state:  当前状态（含 generated_sql / sql_valid / database_id / db_connected）
        config: 运行时配置

    Returns:
        更新后的状态，写入 raw_results / execution_error / steps
    """
    from .tools import execute_sql_on_database
    steps = list(state.get("steps", []))
    sql_valid = state.get("sql_valid", False)
    sql = state.get("generated_sql", "")
    db_id = state.get("database_id", "")
    db_connected = state.get("db_connected", False)

    # ── 跳过条件 1：SQL 无效或为空 ──
    if not sql_valid or not sql:
        _add_step(steps, 6, "执行SQL查询", "skipped", detail="无需执行SQL")
        return {**state, "steps": steps}

    # ── 跳过条件 2：数据库未连接 ──
    if not db_connected:
        _add_step(steps, 6, "执行SQL查询", "skipped", detail="数据库未连接")
        return {**state, "steps": steps}

    # ── 执行 SQL ──
    _add_step(steps, 6, "执行SQL查询", "in_progress",
              detail="正在连接数据库执行SQL查询...",
              thinking=f"【执行的SQL】\n{sql[:600]}")

    result = execute_sql_on_database(db_id, sql)  # 同步调用（工具函数封装）
    raw_results = []
    execution_error = ""

    if result.get("success"):
        # 兼容多种返回字段名
        rows = result.get("rows", result.get("data", result.get("results", [])))
        raw_results = rows
        _add_step(steps, 6, "执行SQL查询", "completed",
                  detail=f"查询成功，返回 {len(rows)} 行数据")
    else:
        execution_error = result.get("message", "SQL执行失败")
        _add_step(steps, 6, "执行SQL查询", "error",
                  detail=f"SQL执行失败: {execution_error[:100]}")

    return {**state, "steps": steps, "raw_results": raw_results, "execution_error": execution_error}


# ═══════════════════════════════════════════════════════════════════════════
# 路由函数 2：是否需要图表
# ═══════════════════════════════════════════════════════════════════════════

def route_chart(state: WorkflowState) -> str:
    """
    根据 need_chart / raw_results / db_connected 决定是否进入图表规划节点。

    路由规则：
        - need_chart=True + raw_results 非空 + db_connected=True → chart_agent
        - 以上任一条件不满足 → analyst（跳过图表，直接生成分析建议）

    Args:
        state: 当前状态（含 need_chart / raw_results / db_connected）

    Returns:
        "chart_agent" 或 "analyst" 字符串
    """
    if (state.get("need_chart")
            and state.get("raw_results")
            and state.get("db_connected")):
        return "chart_agent"
    return "analyst"


# ═══════════════════════════════════════════════════════════════════════════
# 节点 8：图表规划（chart_agent）
# ═══════════════════════════════════════════════════════════════════════════

async def chart_agent_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    根据查询结果的列结构和样本数据，调用 LLM 规划最合适的图表类型。

    对应 DAG 位置：sql_execute →（条件路由）→ 本节点 → analyst_start_node
    条件节点，仅在 route_chart 返回 "chart_agent" 时执行。

    图表规划逻辑：
        - 取 raw_results 第一行的 keys 作为候选列
        - 取前 5 行作为样本数据
        - 调用 chart_agent 模块让 LLM 决定 vizType 和轴映射
        - 默认 vizType 为 "table"（表格展示，不求图表）

    Args:
        state:  当前状态（含 raw_results / question）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 chart_config / steps
    """
    from .chart_agent import run_chart_agent
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))
    raw = state.get("raw_results", [])

    _add_step(steps, 6.5, "图表规划", "in_progress",
              detail="正在根据查询结果规划图表...")

    chart_config = {"vizType": "table"}  # 默认值：表格

    # raw_results 必须是字典列表才有列结构可分析
    if raw and isinstance(raw[0], dict):
        columns = list(raw[0].keys())
        try:
            chart_config = await run_chart_agent(
                columns=columns, sample_rows=raw[:5],
                total_rows=len(raw), question=state["question"],
                llm_call_fn=llm_call_fn,
            )
            viz = chart_config.get("vizType", "table")
            if viz != "table":
                _add_step(steps, 6.5, "图表规划", "completed",
                          detail=f"已规划 {viz} 图表")
            else:
                _add_step(steps, 6.5, "图表规划", "skipped",
                          detail="数据不适合图表展示")
        except Exception as e:
            logger.warning(f"Chart agent failed: {e}")
            _add_step(steps, 6.5, "图表规划", "error",
                      detail=f"图表规划失败: {str(e)[:80]}")
    else:
        _add_step(steps, 6.5, "图表规划", "skipped", detail="数据格式不支持图表")

    return {**state, "steps": steps, "chart_config": chart_config}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 9：生成分析建议（analyst，拆分为 start + execute）
# ═══════════════════════════════════════════════════════════════════════════

async def analyst_start_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    设置"生成分析建议"步骤的初始进度。

    对应 DAG 位置：chart_agent_node 或 sql_execute_node → 本节点 → analyst_execute_node
    不调用 LLM，仅推送进度步骤。

    Args:
        state:  当前状态
        config: 运行时配置

    Returns:
        更新后的状态（仅 steps 有变化）
    """
    steps = list(state.get("steps", []))
    _add_step(steps, 101, "生成分析建议", "in_progress",
              detail="正在基于数据调用大模型生成建议...")
    return {**state, "steps": steps}


async def analyst_execute_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    调用 LLM 基于查询结果生成自然语言分析建议。

    对应 DAG 位置：analyst_start_node → 本节点 → finalize_node

    将 raw_results / indicator_defs / generated_sql 等信息传入 analyst 模块，
    产出 final_answer（自然语言的最终分析结论）。

    Args:
        state:  当前状态（含 question / raw_results / indicator_defs / generated_sql）
        config: 运行时配置（含 llm_call_fn）

    Returns:
        更新后的状态，写入 final_answer / steps
    """
    from .analyst import run_analyst
    llm_call_fn = _get_llm_call_fn(config)
    steps = list(state.get("steps", []))

    es = EvaluationState(
        question=state["question"],
        database_id=state.get("database_id", ""),
    )
    es.raw_results = state.get("raw_results", [])
    es.execution_error = state.get("execution_error")
    es.indicator_defs = state.get("indicator_defs", [])
    es.generated_sql = state.get("generated_sql", "")
    es.steps = []

    es = await run_analyst(es, llm_call_fn)
    steps.extend(es.steps)  # 合并 analyst 内部产出的子步骤

    return {**state, "steps": steps, "final_answer": es.final_answer}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 10：收尾（finalize）
# ═══════════════════════════════════════════════════════════════════════════

async def finalize_node(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
    """
    组装最终返回给前端的 result 字典。

    对应 DAG 位置：analyst_execute_node → 本节点 → END
    这是图中的最后一个业务节点。

    组装逻辑：
        - 如果已有 result（如 combat_agent 分支直接写入），跳过组装
        - 否则从状态中提取所有关键字段，构造标准 result 结构
        - raw_results 截断为前 20 行（防止数据量过大）

    Args:
        state:  当前状态（所有业务字段）
        config: 运行时配置

    Returns:
        更新后的状态，写入 result
    """
    steps = list(state.get("steps", []))
    existing = state.get("result", {})
    # 如果已有 result（专用智能体分支已写入），不覆盖
    if existing:
        return {**state, "steps": steps}

    # 截断原始结果，防止前端渲染过大数据集
    raw_results = state.get("raw_results", [])[:20]
    result = {
        "type": "data_query" if state.get("query_type") == "data_query" else "general",
        "final_answer": state.get("final_answer", "分析完成"),
        "generatedSql": state.get("generated_sql", ""),
        "rawResults": raw_results,
        "totalRows": len(state.get("raw_results", [])),  # 总行数（含截断部分）
        "intent": state.get("intent", ""),
        "query_type": state.get("query_type", "data_query"),
        "need_conclusion": state.get("need_conclusion", True),
        "database_used": state.get("database_id", ""),
        "need_chart": state.get("need_chart", False),
        "chartConfig": state.get("chart_config") if state.get("chart_config") else None,
    }

    return {**state, "steps": steps, "result": result}


# ═══════════════════════════════════════════════════════════════════════════
# 图构建：build_workflow_graph
# ═══════════════════════════════════════════════════════════════════════════

def build_workflow_graph() -> StateGraph:
    """
    构建 LangGraph StateGraph 并声明节点和边的拓扑结构。

    注意：
        - combat_agent / air_agent / simple_analysis 三条分支直接到 END，
          不走 data_explore → ... → finalize 主线。
        - chart_agent 是条件节点，仅在 route_chart 返回 "chart_agent" 时执行；
          无论是否执行，最终都汇入 analyst_start。

    Returns:
        构建完成但未编译的 StateGraph 实例
    """
    graph = StateGraph(WorkflowState)

    # ═══ 注册所有节点 ═══
    graph.add_node("orchestrator_start", orchestrator_start_node)
    graph.add_node("orchestrator_execute", orchestrator_execute_node)
    graph.add_node("combat_agent", combat_agent_node)
    graph.add_node("air_agent", air_agent_node)
    graph.add_node("simple_analysis", simple_analysis_node)
    graph.add_node("data_explore", data_explore_node)
    graph.add_node("dataset_check", dataset_check_node)
    graph.add_node("table_select", table_select_node)
    graph.add_node("text_to_sql_start", text_to_sql_start_node)
    graph.add_node("text_to_sql_execute", text_to_sql_execute_node)
    graph.add_node("sql_execute", sql_execute_node)
    graph.add_node("chart_agent", chart_agent_node)
    graph.add_node("analyst_start", analyst_start_node)
    graph.add_node("analyst_execute", analyst_execute_node)
    graph.add_node("finalize", finalize_node)

    # ═══ 声明边 ═══

    # 入口 → orchestrator 两步链
    graph.set_entry_point("orchestrator_start")
    graph.add_edge("orchestrator_start", "orchestrator_execute")

    # orchestrator 之后按意图分流（条件边）
    graph.add_conditional_edges("orchestrator_execute", route_by_intent, {
        "combat_agent": "combat_agent",
        "air_agent": "air_agent",
        "simple_analysis": "simple_analysis",
        "data_explore": "data_explore",
    })

    # 三条快捷出口（直接到 END）
    graph.add_edge("combat_agent", END)
    graph.add_edge("air_agent", END)
    graph.add_edge("simple_analysis", END)

    # 标准 SQL 管线（线性链）
    graph.add_edge("data_explore", "dataset_check")
    graph.add_edge("dataset_check", "table_select")
    graph.add_edge("table_select", "text_to_sql_start")
    graph.add_edge("text_to_sql_start", "text_to_sql_execute")
    graph.add_edge("text_to_sql_execute", "sql_execute")

    # SQL 执行后按是否需要图表分流
    graph.add_conditional_edges("sql_execute", route_chart, {
        "chart_agent": "chart_agent", "analyst": "analyst_start",
    })
    graph.add_edge("chart_agent", "analyst_start")  # 图表规划后汇入分析
    graph.add_edge("analyst_start", "analyst_execute")
    graph.add_edge("analyst_execute", "finalize")
    graph.add_edge("finalize", END)

    return graph


# 编译一次，全局复用 — 所有请求共享同一个编译好的图实例
_workflow_graph = build_workflow_graph().compile()


# ═══════════════════════════════════════════════════════════════════════════
# 公共 API：run_langgraph_workflow
# ═══════════════════════════════════════════════════════════════════════════

async def run_langgraph_workflow(
    question: str,
    llm_call_fn,
    session_id: str = "",
    database_id: str = "",
    database_name: str = "",
):
    """
    对外暴露的 LangGraph 工作流入口 — 使用 SSE 流式输出评估全流程。

    调用方（通常是 endpoint 函数）以 async for 遍历本函数返回的异步生成器，
    每个 yield 产生一个 SSE 事件字典。

    SSE 事件类型：
        {"type": "step",    "step": {...}}       # 进度步骤（前端渲染步骤卡片）
        {"type": "result",  "result": {...}, ...} # 最终结果（nodes 完成后的 result）
        {"type": "error",   "message": "...", ...}# 错误事件（LLM 调用失败等）

    流式输出实现细节：
        1. 构建初始状态 initial_state（合并用户输入 + _empty_state 默认值）
        2. 调用 _workflow_graph.astream(state, config, stream_mode="values")
           - stream_mode="values" 表示每完成一个节点，yield 完整的状态快照
        3. 维护 seen_step_count 游标，每次拿到新的状态快照后：
           - 从 steps[seen_step_count:] 中提取增量步骤
           - 逐步骤 yield，每步 sleep _YIELD_DELAY
           - 更新游标
        4. 检查 result / error 字段，yield 对应事件
        5. 顶层 try/except 兜底捕获图执行时的异常

    Args:
        question:     用户输入的问题
        llm_call_fn:  LLM 调用函数 (async callable)，由调用方注入
        session_id:   会话 ID（SSE 通道标识）
        database_id:  数据源 ID（空串 = 无数据源）
        database_name:数据源名称

    Yields:
        dict: SSE 事件，含 type / step / result / error / session_id 等字段
    """
    # 构建初始状态：用户输入 + 所有默认值
    initial_state: WorkflowState = {
        "question": question,
        "session_id": session_id,
        "database_id": database_id,
        "database_name": database_name,
        **_empty_state(),  # 展开默认值 —— 保证所有字段有初始值
    }

    config = {"configurable": {"llm_call_fn": llm_call_fn}}
    seen_step_count = 0  # 游标：记录已推送过的步骤数量

    try:
        # stream_mode="values"：每完成一个节点后 yield 完整的 WorkflowState 快照
        async for chunk in _workflow_graph.astream(initial_state, config, stream_mode="values"):
            steps = chunk.get("steps", [])
            # 计算增量步骤（之前未推送过的）
            new_steps = steps[seen_step_count:]
            for s in new_steps:
                yield {"type": "step", "step": s}
                # 步骤间插入延迟，前端有时间完成渲染动画
                await asyncio.sleep(_YIELD_DELAY)
            seen_step_count = len(steps)

            # 如果有结果产出，yield result 事件
            result = chunk.get("result", {})
            if result:
                yield {
                    "type": "result",
                    "session_id": session_id,
                    "result": result,
                    "final_answer": chunk.get("final_answer", ""),
                }

            # 如果有错误，yield error 事件并终止流式输出
            error = chunk.get("error", "")
            if error:
                yield {"type": "error", "message": error, "session_id": session_id}
                return

    except Exception as e:
        # 顶层兜底：捕获图编译/执行过程中的未预期异常
        logger.error(f"LangGraph workflow failed: {e}", exc_info=True)
        yield {
            "type": "error",
            "message": f"评估流程异常: {str(e)[:500]}",
            "session_id": session_id,
        }
