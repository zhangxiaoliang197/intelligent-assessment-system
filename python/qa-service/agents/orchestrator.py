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

## 可选智能体及适用场景
1. **data_query** — 基础查询智能体（默认）。适用：用户直接询问具体数据，如"查询XX"、"列出XX"、"XX有哪些"、"帮我查看XX"。
2. **combat_effectiveness** — 作战效能评估智能体。仅当用户明确要求"评估整个推演过程"中的某方面时使用，如"评估本次推演的战损"、"分析整个作战过程的战果"、"对整体消耗进行评估"。
3. **air_superiority** — 制空权分析智能体。仅当用户明确提及"制空权/空域控制/空中力量对比"时使用。
4. **general_analysis** — 通用问答。仅限纯理论问题（"什么是XX"、"解释XX概念"），完全不涉及数据库查询。

## 选择规则（重要）
- **默认选 data_query**
- 只有用户问题中明确出现"评估整个推演/分析整个作战过程/对整体XX进行评估"等整体性评估表述时，才选 **combat_effectiveness**
- 只有用户明确提及"制空权/空域控制/空中力量对比"时，才选 **air_superiority**
- 单纯的"查询/列出/查看/帮我"等动词，一律选 **data_query**
- 纯概念解释无数据源时选 **general_analysis**

## 是否需要结论（need_conclusion）
- 用户明确说"只看数据/仅列出/不要结论/只要数据"→ false
- 用户明确说"评估/分析/总结/给出结论/给建议"→ true
- 意图不明确（无法判断）→ true（兜底：返回数据 + 简短结论）

## 任务
输出 JSON（不要 markdown 包裹）:
{{
    "intent": "问题类型: 指标计算/趋势分析/对比分析/数据查询/综合评估/作战效能分析/制空权分析",
    "filters": "时间范围、条件等过滤，如无可留空",
    "dimensions": ["分析维度"],
    "analysis_plan": "具体步骤",
    "query_type": "data_query",
    "need_conclusion": true
}}

**注意: 根据问题领域选择最合适的 query_type！need_conclusion 必须为布尔值 true 或 false。**"""


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
        "query_type": plan.get("query_type", "general_analysis"),
        "need_conclusion": plan.get("need_conclusion", True)  # 默认 True 兜底
    }
    state.analysis_plan = plan.get("analysis_plan", "")

    dims = ', '.join(state.entities.get('dimensions', [])) or '未识别'
    filters = state.entities.get('filters', '') or '无'
    need_conclusion = state.entities.get('need_conclusion', True)
    state.add_step(1.2, "意图识别结果", "completed",
                   detail=f"意图: {state.intent} | 模式: {state.entities.get('query_type', '')} | 结论: {'需要' if need_conclusion else '不需要'}",
                   thinking=(
                       f"【意图识别结果】\n"
                       f"问题类型: {state.intent}\n"
                       f"查询模式: {state.entities.get('query_type', '')}\n"
                       f"需要结论: {'是' if need_conclusion else '否'}\n"
                       f"过滤条件: {filters}\n"
                       f"分析维度: {dims}\n\n"
                       f"【分析计划】\n{state.analysis_plan}"
                   ))
    state.update_step(1, status="completed",
                     detail=f"意图识别完成: {state.intent}")
    return state
