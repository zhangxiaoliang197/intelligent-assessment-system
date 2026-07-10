"""
编排智能体 (Orchestrator)
================================================================
系统架构位置：qa-service / agents 层
上游调用方：workflow 模块（评估流程的主控循环）
下游依赖：tools 模块（fetch_database_tables / fetch_datasets_for_database /
           fetch_indicators_for_datasets）、crewdefs 模块（ORCHESTRATOR_AGENT 配置）
状态管理：读写 EvaluationState（共享工作流状态）

核心职责：
  1. 分析用户自然语言问题的意图（数据查询 / 作战效能 / 制空权 / 通用问答）
  2. 从问题中提取过滤条件、分析维度等关键实体
  3. 制定分步分析计划（analysis_plan）
  4. 决定是否需要 AI 结论、是否需要图表输出

数据流：
  用户问题 → build_orchestrator_prompt() 构建 LLM prompt
          → LLM 调用（由 workflow 发起）
          → parse_orchestrator_response() 解析 JSON
          → apply_orchestrator_result() 写入 state
"""
import json
import logging
from .state import EvaluationState
from .tools import fetch_database_tables, fetch_datasets_for_database, fetch_indicators_for_datasets
from .crewdefs import ORCHESTRATOR_AGENT

logger = logging.getLogger("evaluation.orchestrator")

# ============================================================================
# System Prompt：发送给 LLM 的编排指令模板
# 使用 Python f-string 语法，双花括号 {{ 表示一个字面花括号
# 运行时通过 .format() 填充 data_source_context 和 question
# ============================================================================
ORCHESTRATOR_SYSTEM_PROMPT = f"""# 角色: {ORCHESTRATOR_AGENT['role']}
# 目标: {ORCHESTRATOR_AGENT['goal']}

{ORCHESTRATOR_AGENT['backstory']}

---

你是智能评估编排专家。分析用户问题，选择合适的智能体执行分析。

## 数据源
{{data_source_context}}

## 用户问题
{{question}}

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

## 是否需要图表（need_chart）
- 用户明确提到"图表/柱状图/饼图/折线图/画图/可视化/图形展示"→ true
- 其他情况 → false

## 任务
输出 JSON（不要 markdown 包裹）:
{{{{
    "intent": "问题类型: 指标计算/趋势分析/对比分析/数据查询/综合评估/作战效能分析/制空权分析",
    "filters": "时间范围、条件等过滤，如无可留空",
    "dimensions": ["分析维度"],
    "analysis_plan": "具体步骤",
    "query_type": "data_query",
    "need_conclusion": true,
    "need_chart": false
}}}}

**注意: 根据问题领域选择最合适的 query_type！need_conclusion 必须为布尔值 true 或 false。**"""


def parse_orchestrator_response(response_text: str) -> dict:
    """
    解析编排智能体 LLM 的原始响应文本，提取 JSON 结果。

    支持的响应格式：
    1. ```json ... ``` 代码块包裹的 JSON
    2. ``` ... ``` 代码块包裹的 JSON（无语言标记）
    3. 裸 JSON 文本
    4. 如果均解析失败，用正则兜底提取花括号内的 JSON
    5. 最终兜底：返回 general_analysis 模式

    Args:
        response_text: LLM 返回的原始文本

    Returns:
        dict: 包含 intent / filters / dimensions / analysis_plan / query_type 等字段
    """
    text = response_text.strip()

    # 尝试从 markdown json 代码块中提取
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()
    elif "```" in text:
        # 无语言标记的代码块
        start = text.index("```") + 3
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 标准解析失败，用正则兜底匹配第一个 JSON 对象
        import re
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        # 最终兜底：无法解析时默认走通用分析模式
        logger.warning(f"Failed to parse orchestrator response: {text[:500]}")
        return {
            "intent": "general_analysis",
            "filters": "",
            "dimensions": [],
            "analysis_plan": "直接回答用户问题",
            "query_type": "general_analysis"
        }


def build_data_source_context(state: EvaluationState) -> str:
    """
    构建数据源上下文信息，供 LLM 在编排 prompt 中参考。

    从当前 state 的 database_id 出发，依次获取：
    1. 数据库下的所有表名列表（最多展示 30 张）
    2. 关联的数据集及其预定义描述（最多 5 个）
    3. 数据集关联的指标定义及其公式（最多 5 个）

    这些信息帮助 LLM 判断：
    - 用户问题是否可在此数据源上回答
    - 应该选择哪个查询智能体

    Args:
        state: 当前工作流状态

    Returns:
        str: 格式化的数据源上下文字符串，包含表/数据集/指标信息
    """
    if not state.database_id:
        return "未选择数据源（只能进行理论分析）"

    try:
        # 第一步：获取所有表名
        tables = fetch_database_tables(state.database_id)
        if not tables:
            return f"数据源已选择（ID: {state.database_id}），但未发现数据表"

        parts = [f"数据源: {state.database_name or state.database_id}"]
        parts.append(f"可用数据表 ({len(tables)} 张):")
        for t in tables[:30]:
            parts.append(f"  - {t}")
        if len(tables) > 30:
            parts.append(f"  ... 还有 {len(tables) - 30} 张表")

        # 第二步：关联数据集（含预定义描述），帮助 LLM 理解表的作用
        datasets = fetch_datasets_for_database(state.database_id)
        if datasets:
            parts.append(f"\n数据集描述 ({len(datasets)} 个):")
            for ds in datasets[:5]:
                desc = ds.get('description', '')[:80]
                parts.append(f"  - {ds.get('name', '')}" + (f": {desc}" if desc else ""))

        # 第三步：关联指标（含预定义公式），帮助 LLM 理解可计算的指标
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
    """
    构建发送给 LLM 的 system prompt 和 user message。

    将数据源上下文和用户问题填入 ORCHESTRATOR_SYSTEM_PROMPT 模板的占位符。

    Args:
        state: 当前工作流状态

    Returns:
        tuple[str, str]: (system_prompt, user_message)
    """
    data_source_context = build_data_source_context(state)
    system_prompt = ORCHESTRATOR_SYSTEM_PROMPT.format(
        question=state.question,
        data_source_context=data_source_context
    )
    user_message = f"用户问题：{state.question}"
    return system_prompt, user_message


def apply_orchestrator_result(state: EvaluationState, response_text: str) -> EvaluationState:
    """
    解析 LLM 的编排结果并更新到工作流状态。

    职责：
    1. 调用 parse_orchestrator_response() 解析 JSON
    2. 将意图、过滤条件、维度、查询模式、结论/图表标记写入 state
    3. 记录分步执行状态（step 1.2 意图识别结果）

    Args:
        state: 当前工作流状态
        response_text: LLM 返回的编排结果原始文本

    Returns:
        EvaluationState: 更新后的工作流状态
    """
    plan = parse_orchestrator_response(response_text)

    # 将解析结果写入 state 的核心字段
    state.intent = plan.get("intent", "general_analysis")
    state.entities = {
        "filters": plan.get("filters", ""),
        "dimensions": plan.get("dimensions", []),
        "query_type": plan.get("query_type", "general_analysis"),
        "need_conclusion": plan.get("need_conclusion", True),  # 默认 True 兜底
        "need_chart": plan.get("need_chart", False),
    }
    state.need_chart = plan.get("need_chart", False)
    state.analysis_plan = plan.get("analysis_plan", "")

    # 构建可读的维度/过滤摘要，用于 UI 展示
    dims = ', '.join(state.entities.get('dimensions', [])) or '未识别'
    filters = state.entities.get('filters', '') or '无'
    need_conclusion = state.entities.get('need_conclusion', True)

    # 记录步骤 1.2：意图识别结果（含详细 thinking 信息）
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
    # 更新顶层步骤 1 的整体状态
    state.update_step(1, status="completed",
                     detail=f"意图识别完成: {state.intent}")
    return state
