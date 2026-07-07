"""
编排智能体 (Orchestrator)
负责：分析用户意图 → 提取实体/条件/维度 → 制定分析计划
"""
import json
import logging
from .state import EvaluationState
from .tools import fetch_database_tables, fetch_datasets_for_database, fetch_indicators_for_datasets

logger = logging.getLogger("evaluation.orchestrator")

ORCHESTRATOR_SYSTEM_PROMPT = """你是智能评估编排专家。分析用户问题，制定数据查询和分析计划。

## 数据源
{data_source_context}

## 问题
{question}

## 任务
输出JSON（不要markdown包裹）:
{{
    "intent": "问题类型:指标计算/趋势分析/对比分析/数据查询/综合评估/理论问答",
    "filters": "时间范围、条件等过滤",
    "dimensions": ["分析维度"],
    "analysis_plan": "具体分析步骤，注明需查询的表和字段",
    "query_type": "data_query或general_analysis"
}}"""


def parse_orchestrator_response(response_text: str) -> dict:
    text = response_text.strip()
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse orchestrator response: {text[:500]}")
        return {
            "intent": "general_analysis",
            "filters": "",
            "dimensions": [],
            "analysis_plan": "直接回答用户问题",
            "query_type": "general_analysis"
        }


def build_data_source_context(state: EvaluationState) -> str:
    """构建数据源上下文信息（表列表 + 数据集描述 + 指标定义）"""
    if not state.database_id:
        return "未选择数据源（只能进行理论分析）"

    try:
        tables = fetch_database_tables(state.database_id)
        if not tables:
            return f"数据源已选择（ID: {state.database_id}），但未发现数据表"

        parts = [f"数据源: {state.database_name or state.database_id}"]
        parts.append(f"可用数据表 ({len(tables)} 张):")
        for t in tables[:30]:
            parts.append(f"  - {t}")
        if len(tables) > 30:
            parts.append(f"  ... 还有 {len(tables) - 30} 张表")

        # 关联数据集（含预定义描述）
        datasets = fetch_datasets_for_database(state.database_id)
        if datasets:
            parts.append(f"\n数据集描述 ({len(datasets)} 个):")
            for ds in datasets[:5]:
                desc = ds.get('description', '')[:80]
                parts.append(f"  - {ds.get('name', '')}" + (f": {desc}" if desc else ""))

        # 关联指标（含预定义公式）
        linked_ds_ids = [ds.get("id") for ds in datasets]
        indicators = fetch_indicators_for_datasets(linked_ds_ids)
        if indicators:
            parts.append(f"\n指标定义 ({len(indicators)} 个):")
            for ind in indicators[:5]:
                formula = ind.get('formula', '')[:100]
                desc = ind.get('description', '')[:60]
                parts.append(f"  - {ind.get('name', '')}" +
                            (f" (公式: {formula})" if formula else "") +
                            (f" (说明: {desc})" if desc else ""))

        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"Failed to build data source context: {e}")
        return f"数据源已选择（ID: {state.database_id}），获取表信息失败"


def build_orchestrator_prompt(state: EvaluationState) -> tuple:
    """构建 orchestrator 的 system prompt 和 user message"""
    data_source_context = build_data_source_context(state)
    system_prompt = ORCHESTRATOR_SYSTEM_PROMPT.format(
        question=state.question,
        data_source_context=data_source_context
    )
    user_message = f"用户问题：{state.question}"
    return system_prompt, user_message


def apply_orchestrator_result(state: EvaluationState, response_text: str) -> EvaluationState:
    """解析 LLM 响应并更新 state"""
    plan = parse_orchestrator_response(response_text)
    state.intent = plan.get("intent", "general_analysis")
    state.entities = {
        "filters": plan.get("filters", ""),
        "dimensions": plan.get("dimensions", []),
        "query_type": plan.get("query_type", "general_analysis")
    }
    state.analysis_plan = plan.get("analysis_plan", "")

    dims = ', '.join(state.entities.get('dimensions', [])) or '未识别'
    filters = state.entities.get('filters', '') or '无'
    state.add_step(1.2, "意图识别结果", "completed",
                   detail=f"意图: {state.intent} | 模式: {state.entities.get('query_type', '')}",
                   thinking=(
                       f"【意图识别结果】\n"
                       f"问题类型: {state.intent}\n"
                       f"查询模式: {state.entities.get('query_type', '')}\n"
                       f"过滤条件: {filters}\n"
                       f"分析维度: {dims}\n\n"
                       f"【分析计划】\n{state.analysis_plan}"
                   ))
    state.update_step(1, status="completed",
                     detail=f"意图识别完成: {state.intent}")
    return state
