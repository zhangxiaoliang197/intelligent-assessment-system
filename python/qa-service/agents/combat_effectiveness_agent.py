"""
作战效能分析智能体 (Combat Effectiveness Agent)

系统架构位置:
  qa-service / agents 层 — 作战效能分析领域智能体

核心职责:
  1. 根据用户自然语言提问，从预配置的 queries.json 中加载作战效能分析SQL模板
  2. 通过关键字匹配 + LLM 双策略选择与用户提问最相关的SQL查询
  3. 逐条执行选定查询，汇总结论并在 need_conclusion=True 时调用 LLM 生成综合评估
  4. 以 SSE 流式事件 (step/result) 的形式向调用方输出进度与最终结果

数据流:
  用户提问 → load_queries() 加载SQL模板 → 关键字/LLM筛选查询
  → execute_sql_on_database() 逐条执行 → LLM逐条分析 → LLM综合评估
  → yield step_event / result 事件
"""
import asyncio
import json
import logging
import os
import re
import time

# 从同包 tools 模块导入数据库执行工具
from .tools import execute_sql_on_database
# 从同包 crewdefs 模块导入作战效能分析智能体的 CrewAI 角色定义
from .crewdefs import COMBAT_EFFECTIVENESS_AGENT

# 模块级 logger，命名空间为 evaluation.combat_effectiveness
logger = logging.getLogger("evaluation.combat_effectiveness")

# 构建系统角色 prompt：将 CrewAI 角色定义拼接为 LLM 的 system message
_COMBAT_SYSTEM_ROLE = (
    f"你是{COMBAT_EFFECTIVENESS_AGENT['role']}。\n"
    f"目标: {COMBAT_EFFECTIVENESS_AGENT['goal']}\n"
    f"{COMBAT_EFFECTIVENESS_AGENT['backstory']}"
)

# 项目根目录 = qa-service 目录（当前文件在 agents/ 子目录下，os.path.dirname 两次回到服务根目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 作战效能分析预配置SQL查询的 JSON 文件默认路径
QUERIES_FILE = os.path.join(BASE_DIR, "config", "queries.json")

# 流式事件之间的延迟（秒），用于给前端展示进度动画留出时间
_YIELD_DELAY = 0.25


def load_queries():
    """加载作战效能分析的预配置SQL查询列表

    优先从环境变量 COMBAT_QUERIES_PATH 读取配置文件路径，
    若未设置则使用默认路径 config/queries.json。
    文件内容会被清洗（移除 JSON 规范不允许的控制字符）后解析返回。

    Returns:
        list[dict]: 查询分组列表，每个分组包含 group 名称和 queries 子列表。
                    若文件不存在则返回空列表 []。
    """
    # 支持通过环境变量覆盖配置文件路径（Docker 部署时通过卷挂载注入）
    path = os.getenv("COMBAT_QUERIES_PATH", QUERIES_FILE)
    if not os.path.exists(path):
        logger.warning(f"queries.json not found at {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
        # 移除 JSON 不允许的控制字符（保留 \t \n \r）
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
        return json.loads(cleaned)


def _step_event(step_num, description, status, detail="", thinking="", progress=None, sub_step=None):
    """构造流式步骤事件字典

    用于通过 SSE (Server-Sent Events) 向前端推送分析进度。

    Args:
        step_num: 步骤编号，在父级 workflow 中作为子步骤标识
        description: 步骤的简短描述文字
        status: 步骤状态，'in_progress' | 'completed' | 'failed'
        detail: 面向用户的详细进度信息
        thinking: 面向用户的"思考过程"展示内容
        progress: 手动指定的进度百分比 (0-100)，若为 None 则根据 status 自动推断
        sub_step: 可选的子步骤标识

    Returns:
        dict: 符合前端 SSE 事件协议的步骤事件字典
    """
    # 若未手动指定 progress，则根据状态自动推算：completed=100, in_progress=50, 其他=0
    if progress is None:
        progress = 100 if status == "completed" else (50 if status == "in_progress" else 0)
    s = {
        "type": "step",
        "step": {
            "step": step_num, "description": description, "status": status,
            "detail": detail, "thinking": thinking, "progress": progress
        }
    }
    if sub_step:
        s["step"]["subStep"] = sub_step
    return s


async def _adapted_llm_call(prompt: str, llm_call_fn) -> str:
    """将单段 prompt 适配为 system + user 调用（使用 CrewAI 角色定义）

    传入的 llm_call_fn 签名为 async (system_prompt, user_prompt) -> str，
    本函数将 CrewAI 角色定义作为 system prompt，将调用方传入的 prompt 作为 user prompt。

    Args:
        prompt: 用户消息内容
        llm_call_fn: 异步 LLM 调用函数，签名为 async (system, user) -> str

    Returns:
        str: LLM 的响应文本；若 LLM 返回空或 None，则返回兜底文本 "分析结果不可用"
    """
    response = await llm_call_fn(
        _COMBAT_SYSTEM_ROLE,
        prompt
    )
    return response or "分析结果不可用"


def _select_queries_by_keywords(user_query, all_queries):
    """简单关键字匹配：优先选用户问题中提到的查询

    将所有分组中的查询扁平化为列表，然后检查用户提问中是否包含各查询
    预配置的关键字。若有关键字命中则优先返回命中的查询子集；
    若无命中或查询总数 ≤ 2，则返回全部查询（交由 LLM 选择）。

    Args:
        user_query: 用户的自然语言提问
        all_queries: 从 queries.json 加载的查询分组列表

    Returns:
        list[dict]: 筛选后的查询列表，每个元素包含 group/label/sql/vizType/keywords 字段
    """
    # 将分组结构扁平化为单层查询列表
    query_list = []
    for g in all_queries:
        for q in g.get("queries", []):
            query_list.append({
                "group": g.get("group", ""),
                "label": q.get("label", ""),
                "sql": q.get("sql", ""),
                "vizType": q.get("vizType", "table"),
                "keywords": q.get("keywords", [])
            })

    # 查询数 ≤ 2 时无需筛选，直接返回全部
    if len(query_list) <= 2:
        return query_list

    # 关键字匹配 vs LLM 兜底
    matched = []
    q_lower = user_query.lower()
    for q in query_list:
        kws = q.get("keywords", [])
        # 任意关键字在用户提问中出现即视为命中
        if kws and any(kw.lower() in q_lower for kw in kws):
            matched.append(q)

    # 若有关键字命中则返回命中子集，否则返回全部（交由 LLM 选择）
    if matched:
        logger.info(f"Keyword-matched {len(matched)}/{len(query_list)} queries")
        return matched

    return query_list


async def _select_queries_by_llm(user_query, all_queries, llm_call_fn):
    """用 LLM 选择相关查询

    构造查询索引 prompt 发送给 LLM，由 LLM 根据用户提问语义选择最相关的
    查询编号。若 LLM 返回无效编号或解析失败，则回退返回全部查询。

    Args:
        user_query: 用户的自然语言提问
        all_queries: 从 queries.json 加载的查询分组列表
        llm_call_fn: 异步 LLM 调用函数

    Returns:
        list[dict]: LLM 筛选后的查询列表
    """
    # 将分组结构扁平化为单层查询列表并编号
    query_list = []
    for g in all_queries:
        for q in g.get("queries", []):
            query_list.append({
                "group": g.get("group", ""),
                "label": q.get("label", ""),
                "sql": q.get("sql", ""),
                "vizType": q.get("vizType", "table"),
                "keywords": q.get("keywords", [])
            })

    # 查询数 ≤ 2 时无需 LLM 选择，直接返回
    if len(query_list) <= 2:
        return query_list

    # 构建查询索引文本供 LLM 参考
    query_index = ""
    for i, q in enumerate(query_list):
        kws = ", ".join(q.get("keywords", [])) or q["label"]
        query_index += f"[{i}] {q['group']}/{q['label']} 关键词: {kws}\n"

    # 构造选择 prompt，要求 LLM 返回 JSON 数组格式的编号列表
    selection_prompt = f"""用户提问: "{user_query}"

可选SQL查询列表:
{query_index}

请根据用户提问选择相关的查询编号, 返回JSON数组格式: [0, 2, 5] (只包含编号, 不要其他文字)
如果用户问得宽泛则多选, 问得具体则少选。最少选1条。"""

    answer = await _adapted_llm_call(selection_prompt, llm_call_fn)
    try:
        # 从 LLM 返回中提取所有数字，过滤出有效的查询编号
        matches = re.findall(r'\d+', answer)
        indices = [int(m) for m in matches if 0 <= int(m) < len(query_list)]
        if not indices:
            return query_list
        return [query_list[i] for i in indices]
    except Exception:
        # 任何解析异常都回退返回全部查询
        return query_list


async def run_stream(
    user_query: str,
    database_id: str,
    llm_call_fn,
    need_conclusion: bool = True,
):
    """Compatibility entrypoint using the dynamic, dialect-aware SQL pipeline.

    Historical versions executed SQL templates from ``queries.json`` directly.
    That is unsafe for internal deployments whose tables and database products
    differ, so even direct callers now delegate to the metadata-driven workflow.
    """
    from .langgraph_workflow import run_langgraph_workflow

    async for event in run_langgraph_workflow(
        question=user_query,
        llm_call_fn=llm_call_fn,
        database_id=database_id,
    ):
        yield event


async def _legacy_run_stream(user_query: str, database_id: str, llm_call_fn, need_conclusion: bool = True):
    """作战效能分析 — 异步流式生成器

    该函数是作战效能分析的主入口，以异步生成器形式逐步 yield SSE 事件。
    工作流程：
      1. 加载 queries.json 中的预配置SQL模板
      2. 关键字 + LLM 双策略选择相关查询
      3. 逐条执行SQL并通过 LLM 生成逐条分析
      4. 汇总各维度分析，调用 LLM 生成综合评估结论

    Args:
        user_query: 用户的自然语言提问
        database_id: 目标数据库标识符，传递给 execute_sql_on_database
        llm_call_fn: 异步 LLM 调用函数，签名为 async (system, user) -> str
        need_conclusion: True=执行SQL+LLM生成结论; False=仅执行SQL返回数据（不调用LLM分析）

    Yields:
        dict: SSE 事件字典
            - type="step": 进度步骤事件，含 step/description/status/detail/thinking/progress
            - type="result": 最终结果事件，含 type/region/final_answer/results 等字段
    """
    # 加载预配置的SQL查询模板
    all_queries = load_queries()
    if not all_queries:
        # 配置文件不存在或为空时，直接返回完成事件并终止
        yield _step_event(4, "执行分析计算", "completed",
                         detail="未找到SQL配置, 请检查 config/queries.json", progress=100,
                         thinking="作战效能分析智能体已加载，但 queries.json 为空或未找到")
        return

    # 在 workflow 中作为子步骤，step_base 固定为 4
    step_base = 4  # 在 workflow 中作为子步骤

    # 开始分析：向用户展示初始进度
    yield _step_event(step_base, "作战效能分析", "in_progress",
                     detail="正在根据提问匹配分析维度...", progress=5,
                     thinking="【作战效能分析智能体】\n加载了 queries.json 中的预配置SQL模板")

    await asyncio.sleep(_YIELD_DELAY)

    # 查询选择：先用关键字匹配（快速、离线），匹配不到再用 LLM 语义选择
    selected = _select_queries_by_keywords(user_query, all_queries)
    if len(selected) == len(all_queries) or len(selected) == 0:
        selected = await _select_queries_by_llm(user_query, all_queries, llm_call_fn)

    total = len(selected)
    executed = 0  # 已执行查询计数，用于进度计算

    # 告知用户选定结果
    mode_label = "查询+结论" if need_conclusion else "仅查询数据"
    yield _step_event(step_base, "作战效能分析", "in_progress",
                     detail=f"已选定 {total} 条相关查询, 模式: {mode_label}", progress=10,
                     thinking=f"选中 {total} 条查询: " + ", ".join(q["label"] for q in selected))

    await asyncio.sleep(_YIELD_DELAY)

    # 累积所有查询的执行结果和各维度的 LLM 分析摘要
    all_results = []
    all_summaries = []

    # 逐条执行选定查询
    for q in selected:
        label = q["label"]
        sql = q.get("sql", "")
        group_name = q.get("group", "")

        # 推送当前查询的执行进度
        yield _step_event(step_base, "作战效能分析", "in_progress",
                         detail=f"正在查询: {label}", progress=int(10 + 75 * executed / max(total, 1)),
                         thinking=f"【执行SQL - {group_name}/{label}】\n{sql[:400]}")

        await asyncio.sleep(_YIELD_DELAY)

        # 在目标数据库上执行 SQL 查询
        exec_result = execute_sql_on_database(database_id, sql)
        executed += 1

        insight = ""
        # 查询成功且有数据时，根据 need_conclusion 决定是否调用 LLM 生成分析
        if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
            columns = exec_result.get("columns", [])
            rows = exec_result.get("rows", [])

            if need_conclusion:
                # 需要结论模式：推送 LLM 分析进度
                yield _step_event(step_base, "作战效能分析", "in_progress",
                                 detail=f"正在分析: {label} ({exec_result.get('rowCount')}条)",
                                 progress=int(10 + 75 * executed / max(total, 1)),
                                 thinking=f"查询 [{label}] 返回 {len(rows)} 行, 正在调用LLM分析...")

                await asyncio.sleep(_YIELD_DELAY)

                # 构造逐条分析的 prompt，限制前10行数据以避免 token 超限
                insight_prompt = f"""请基于以下数据做简要分析(100字以内):
查询类型: {group_name} - {label}
列: {columns}
数据(前10行): {str(rows[:10])}
总行数: {len(rows)}

请给出1-2句关键发现。"""
                insight = await _adapted_llm_call(insight_prompt, llm_call_fn)
            else:
                # 仅数据模式：跳过 LLM 分析，直接报告查询完成
                yield _step_event(step_base, "作战效能分析", "in_progress",
                                 detail=f"已查询: {label} ({exec_result.get('rowCount')}条)",
                                 progress=int(10 + 75 * executed / max(total, 1)),
                                 thinking=f"查询 [{label}] 返回 {len(rows)} 行 (仅数据模式，跳过LLM分析)")
                await asyncio.sleep(_YIELD_DELAY)
        else:
            # 查询失败或无数据时，使用错误消息作为 insight
            insight = exec_result.get("message", "查询无数据")

        # 将本条查询的完整结果追加到汇总列表
        all_results.append({
            "group": group_name,
            "label": label,
            "sql": sql,
            "columns": exec_result.get("columns", []),
            "rows": exec_result.get("rows", []),
            "rowCount": exec_result.get("rowCount", 0),
            "insight": insight
        })
        # 仅在有内容时才加入摘要列表（用于后续综合评估）
        if insight:
            all_summaries.append(f"[{group_name}-{label}]: {insight}")

        await asyncio.sleep(_YIELD_DELAY)

    # 综合评估（仅 need_conclusion=True 时生成）
    summary = ""
    if need_conclusion:
        # 推送综合评估进度
        yield _step_event(step_base, "作战效能分析", "in_progress",
                         detail="正在生成综合评估总结...", progress=90,
                         thinking="所有查询执行完毕，正在汇总LLM分析...")

        await asyncio.sleep(_YIELD_DELAY)

        # 拼接所有维度的分析摘要，调用 LLM 生成最终综合评估
        if all_summaries:
            summary_prompt = "请基于以下各维度的分析，给出100字以内的评估总结:\n用户提问: " + user_query + "\n" + "\n".join(all_summaries)
            summary = await _adapted_llm_call(summary_prompt, llm_call_fn)
        else:
            # 没有任何有效数据时的兜底文案
            summary = "暂无有效数据可供评估"

        # 推送完成事件
        yield _step_event(step_base, "作战效能分析", "completed",
                         detail="作战效能分析完成", progress=100,
                         thinking=f"【综合评估总结】\n{summary[:800]}")
    else:
        # 仅数据模式：推送完成事件，不包含 LLM 生成的结论
        yield _step_event(step_base, "作战效能分析", "completed",
                         detail=f"作战效能查询完成（仅数据模式），共 {len(all_results)} 条查询结果", progress=100,
                         thinking="用户未要求结论，仅返回查询数据")

    # 构造并推送最终结果事件 — 统一 results 字段名
    final = {
        "type": "result",
        "result": {
            "type": "combat_effectiveness",
            "final_answer": summary,
            "results": all_results,
            "need_conclusion": need_conclusion,
            "generatedSql": None,
            "rawResults": [],
            "totalRows": sum(r.get("rowCount", 0) for r in all_results),
        }
    }
    yield final
