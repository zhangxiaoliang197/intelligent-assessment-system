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

## ⚠️ 第一步（最重要！）：判断问题主题是否与数据源相关

请先回答：用户问题的主题是否与上述数据源的**表名、数据集名、指标名的含义**有关联？

**典型不相关场景（→ 必须选 general_analysis）：**
- 数据源的业务主题与用户问题的领域完全不一致 → **主题不相关**
- 例如：数据源是关于A领域的数据，用户问题问的是B领域的内容 → **主题完全无关**
- 问题领域与数据源的业务主题明显不一致 → **主题不相关**

**典型相关场景：**
- 问题中提到的实体/概念与数据源的表名、字段名、数据集描述直接对应 → 相关
- 问题要求的计算与数据源中预定义的指标一致 → 相关

**规则：如果问题主题与数据源业务不相关 → 直接选 general_analysis，不要尝试查询数据库！**

## 第二步：选择智能体

仅在**问题与数据源相关**的前提下，按以下规则选择智能体：

1. **data_query** — 用户要求从数据库中读取具体数据。例："列出XX"、"统计XX的数量"、"查询XX表"、"XX数据是多少"。
2. **combat_effectiveness** — 用户要求评估整个推演过程。例："评估本次推演的战损"、"分析整个作战过程"。
3. **air_superiority** — 用户明确提到制空权/空域控制/空中力量对比。
4. **general_analysis** — 所有其他情况（含：分析评估结论、趋势判断、知识问答、与数据源无关的任何问题）。

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
    "query_type": "在此填入最终选择的智能体",
    "need_conclusion": true,
    "need_chart": false
}}}}

**注意: query_type 必须根据上述两步判断结果选择！**"""


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
        # 如果用户指定了数据集，只保留选中的
        if state.dataset_ids and datasets:
            selected_ids = set(state.dataset_ids)
            datasets = [ds for ds in datasets if ds.get('id') in selected_ids]

        if datasets:
            parts.append(f"\n数据集描述 ({len(datasets)} 个):")
            for ds in datasets[:5]:
                desc = ds.get('description', '')[:80]
                parts.append(f"  - {ds.get('name', '')}" + (f": {desc}" if desc else ""))

        # 第三步：关联指标（含预定义公式），帮助 LLM 理解可计算的指标
        # 只获取选中数据集的指标，避免不相关指标干扰 LLM 判断
        linked_ds_ids = [ds.get("id") for ds in datasets]
        indicators = fetch_indicators_for_datasets(linked_ds_ids) if linked_ds_ids else []
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
