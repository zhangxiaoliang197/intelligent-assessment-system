"""
分析回答智能体 (Analyst)
负责：基于查询结果数据给出2-3条简洁建议（纯分析，不执行SQL）
"""
import json
import logging
from .state import EvaluationState
from .crewdefs import ANALYST_AGENT

logger = logging.getLogger("evaluation.analyst")

ANALYST_SYSTEM_PROMPT = f"""# 角色: {ANALYST_AGENT['role']}
# 目标: {ANALYST_AGENT['goal']}

{ANALYST_AGENT['backstory']}

---

你是数据分析专家。根据SQL查询结果，给出2-3条简洁、可执行的建议。

## 用户问题
{{question}}

## SQL查询
{{sql}}

## 结果统计
{{result_summary}}

## 数据预览(前10行)
{{raw_data}}

## 指标定义
{{indicator_context}}

## 要求
- 只输出2-3条建议，每条1-2句话
- 建议要具体、可操作
- 引用数据中的具体数值
- 不要输出长篇报告

## 格式（每条之间用空行分隔）
1. **建议标题**: 具体说明和数据依据

2. **建议标题**: 具体说明和数据依据

3. **建议标题**: 具体说明和数据依据（如有必要）
"""


async def run_analyst(state: EvaluationState, llm_call_fn) -> EvaluationState:
    """
    基于已有的查询结果生成2-3条分析建议。

    调用 LLM，将 SQL 查询结果、指标定义等上下文传入，让模型输出
    简洁、可执行的分析建议，存入 state.final_answer。

    Args:
        state: 当前评估状态，包含 question、raw_results、generated_sql 等
        llm_call_fn: LLM 调用函数 async fn(system_prompt, user_prompt) -> str

    Returns:
        EvaluationState: 更新后的状态（final_answer 已填充）
    """
    logger.info(f"Running analyst for: {state.question[:100]}")

    # 添加执行步骤记录，供前端展示进度
    state.add_step(7.1, "生成分析建议", "in_progress", "正在基于数据调用大模型生成建议...")

    # 初始化默认值
    result_summary = "未执行SQL"
    raw_data = "无"
    indicator_context = "无"

    # 根据查询结果构建数据摘要和预览
    if state.raw_results:
        total_rows = len(state.raw_results)
        if total_rows > 0:
            # 截取前10行作为数据预览，避免 prompt 过长
            raw_data = json.dumps(state.raw_results[:10], ensure_ascii=False, indent=2)
            if total_rows > 10:
                raw_data += f"\n... (共 {total_rows} 行，仅显示前10行)"
            result_summary = f"查询返回 {total_rows} 行数据"
        else:
            result_summary = "查询返回 0 行"
    elif state.execution_error:
        # SQL 执行失败时，将错误信息作为上下文传递给 LLM
        result_summary = f"失败: {state.execution_error[:100]}"
        raw_data = f"错误: {state.execution_error}"

    # 构建指标定义上下文（最多取前5个指标，控制 prompt 长度）
    if state.indicator_defs:
        parts = []
        for ind in state.indicator_defs[:5]:
            parts.append(f"- {ind.get('name', '')}: {ind.get('formula', '')} {ind.get('description', '')}")
        indicator_context = "\n".join(parts)

    # 将上下文变量注入系统提示模板
    system_prompt = ANALYST_SYSTEM_PROMPT.format(
        question=state.question,
        sql=state.generated_sql or "无需SQL",
        result_summary=result_summary,
        raw_data=raw_data,
        indicator_context=indicator_context
    )

    try:
        # 调用 LLM 生成分析建议
        response = await llm_call_fn(system_prompt, "请基于数据给出2-3条建议。")
        state.final_answer = response
        state.update_step(7.1, status="completed",
                         detail="分析建议已生成",
                         thinking=f"【模型建议】\n{response[:800]}")
    except Exception as e:
        logger.error(f"Analyst failed: {e}")
        state.final_answer = f"生成建议时出错：{str(e)[:200]}"
        state.update_step(7.1, status="error",
                         detail=f"生成失败: {str(e)[:100]}")

    return state


async def run_simple_analysis(state: EvaluationState, llm_call_fn) -> EvaluationState:
    """
    直接问答模式：无需 SQL，直接用 LLM 回答用户问题。

    适用于闲聊、知识问答等不涉及数据库查询的场景。

    Args:
        state: 当前评估状态，包含 question 等
        llm_call_fn: LLM 调用函数 async fn(system_prompt, user_prompt) -> str

    Returns:
        EvaluationState: 更新后的状态（final_answer 已填充）
    """
    # 记录分析步骤
    state.add_step(2, "直接分析", "in_progress", "正在分析问题...")

    # 直接调用 LLM，不经过 SQL 生成与执行流程
    response = await llm_call_fn(
        f"你是专业评估分析专家。直接回答用户问题，简洁清晰。",
        state.question
    )
    state.final_answer = response
    state.update_step(2, status="completed", detail="分析完成",
                     thinking=f"回答:\n{response[:500]}")
    return state
