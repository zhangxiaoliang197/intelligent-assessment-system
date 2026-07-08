"""
编排智能体 (Orchestrator)
负责：分析用户意图 → 提取实体/条件/维度 → 制定分析计划
"""
import json
import logging
from .state import EvaluationState
from .tools import fetch_database_tables, fetch_datasets_for_database, fetch_indicators_for_datasets

logger = logging.getLogger("evaluation.orchestrator")

ORCHESTRATOR_SYSTEM_PROMPT = """你是智能评估编排专家。分析用户问题，选择合适的智能体执行分析。

## 数据源
{data_source_context}

## 用户问题
{question}

## 可选智能体（agent）及适用场景
1. **data_query** — 通用数据查询智能体。适用：成绩分析、学生排名、及格率统计、各部门绩效对比等常规数据分析。
2. **combat_effectiveness** — 作战效能分析智能体。适用：作战效能评估、火力打击效果、兵力部署分析、武器装备效能等军事作战场景。关键词：作战、效能、打击、兵力、火力、装备效能、战损。
3. **air_superiority** — 制空权分析智能体。适用：制空权评估、空域控制、空中力量对比、红蓝空军对抗分析。关键词：制空权、空域、空军、红蓝对抗、空中力量、制空。
4. **general_analysis** — 通用问答。仅限纯理论问题（"什么是XX"、"解释XX概念"），完全不涉及数据库查询。

## 选择规则
- 只要数据源中列出了表，**默认选 data_query**。
- 如果问题明确涉及"作战效能/火力/兵力/装备效能"等军事术语，选 **combat_effectiveness**。
- 如果问题明确涉及"制空权/空域/空中力量/红蓝空战"等术语，选 **air_superiority**。
- 纯概念解释无数据源时选 **general_analysis**。

## 任务
输出 JSON（不要 markdown 包裹）:
{{
    "intent": "问题类型: 指标计算/趋势分析/对比分析/数据查询/综合评估/作战效能分析/制空权分析",
    "filters": "时间范围、条件等过滤，如无可留空",
    "dimensions": ["分析维度"],
    "analysis_plan": "具体步骤",
    "query_type": "data_query"
}}

**注意: 根据问题领域选择最合适的 query_type！**"""


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
