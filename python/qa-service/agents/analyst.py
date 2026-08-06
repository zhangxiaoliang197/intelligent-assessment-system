"""
分析回答智能体 (Analyst)
负责：基于查询结果数据给出结构化、场景化的分析结论（纯分析，不执行SQL）

============================================================
模块在系统架构中的位置
============================================================
本模块位于 qa-service 的多智能体框架层（agents/），是指标分析流水线
「阶段 8 — 生成分析」的实现。它消费 EvaluationState 中的查询结果与
数据充分性报告，按场景选择对应 Prompt，调用 LLM 生成自然语言分析结论。

============================================================
场景化路由（判定与解读分离）
============================================================
数据充分性由 sufficiency.assess_data_sufficiency 确定性判定，结果存入
state.sufficiency_report。本模块据其 scenario 字段路由到四个 Prompt：

  - no_data        → ANALYST_NO_DATA_PROMPT          无相关数据声明 + 后续指引
  - insufficient   → ANALYST_INSUFFICIENT_DATA_PROMPT 覆盖表 + 不足原因 + 后续指引
  - sufficient + 计算型指标 → ANALYST_COMPUTED_METRICS_PROMPT  计算分解 + 对标 + 业务含义
  - sufficient + 纯直接型   → ANALYST_STANDARD_PROMPT          数值 + 含义 + 建议

所有 Prompt 强制统一标题层级：## 分析结论 / ### 指标明细 / ### 后续建议，
并在文末以 > 术语说明 引用块解释公式术语，保证跨场景一致性。
"""
import json
import logging
from .state import EvaluationState
from .crewdefs import ANALYST_AGENT

logger = logging.getLogger("evaluation.analyst")


# ============================================================
# 角色头（所有场景 Prompt 共用）
# ============================================================

_ROLE_HEADER = (
    f"# 角色: {ANALYST_AGENT['role']}\n"
    f"# 目标: {ANALYST_AGENT['goal']}\n"
    f"{ANALYST_AGENT['backstory']}\n"
    "---\n"
)


# ============================================================
# 场景 1：无相关数据（区分「库无数据」与「查询技术失败」）
# ============================================================

ANALYST_NO_DATA_PROMPT = _ROLE_HEADER + """## 硬约束（最高优先级，必须遵守）
- 数据库中未检索到任何相关数据，**禁止编造任何数值**
- **禁止输出含数值的表格**（如指标值表、计算结果表）
- **禁止基于指标公式推算具体数值**
- 不使用"抱歉/失败"等情绪化措辞，保持专业语气

## 场景判定
{scenario_reason}
数据库中未检索到与「{question}」相关的数据。

## 用户问题
{question}

## 涉及指标（仅名称，供理解问题背景）
{indicator_context}

## 输出要求（严格按此结构，使用 Markdown）
## 分析结论
用一句话显式声明：当前数据库中未检索到与该问题相关的数据。
说明已尝试查询但返回 0 行，**不得呈现任何指标数值**。

**可能原因**：
- 3 条以内客观陈述（如数据未录入、筛选条件不匹配、数据源不对应）

### 后续建议
- 2-3 条可操作指引（调整筛选条件 / 更换数据源 / 联系数据管理员补录数据）
- 每条含具体动作
"""


# ============================================================
# 场景 1b：查询技术失败（SQL 生成/执行失败，不注入公式与表结构）
# ============================================================

ANALYST_TECHNICAL_FAILURE_PROMPT = _ROLE_HEADER + """## 硬约束（最高优先级，必须遵守）
- 查询未能成功执行，**禁止编造任何数值**
- **禁止输出含数值的表格**
- **禁止基于指标公式推算具体数值**
- 不使用"抱歉/失败"等情绪化措辞，保持专业语气

## 场景判定
查询技术失败，未能获取数据。
{scenario_reason}

## 用户问题
{question}

## 涉及指标（仅名称）
{indicator_context}

## 输出要求（严格按此结构，使用 Markdown）
## 分析结论
用一句话显式声明：数据查询未能成功执行，暂无法获取相关数据。
**不得呈现任何指标数值，不得推测查询结果**。

**失败原因**：
- 基于上述场景判定客观陈述，不臆测

### 后续建议
- 2-3 条可操作排查指引（检查大模型配置 maxTokens / 检查数据库连接 / 联系管理员）
- 每条含具体动作
"""


# ============================================================
# 场景 2：数据量不足（含逐指标覆盖表）
# ============================================================

ANALYST_INSUFFICIENT_DATA_PROMPT = _ROLE_HEADER + """## 硬约束（最高优先级，必须遵守）
- **不编造未出现的数值**；对缺失指标不得基于公式推算具体数值
- 覆盖表数据必须与数据覆盖报告一致，不得篡改
- 不输出原始 SQL 结果表

## 场景判定
数据可用但不充分。{scenario_reason}

## 用户问题
{question}

## 数据覆盖报告（确定性统计，请原样采用，不得篡改）
{sufficiency_report_table}

## 可用数据预览（前10行）
{raw_data}

## 指标定义
{indicator_context}

## 输出要求（严格按此结构，使用 Markdown）
## 分析结论
用一句话说明数据可用但不充分，并给出覆盖率（如「2/3 个指标具备数据」）。

### 指标明细
按下表逐指标列出，**直接采用**数据覆盖报告的内容：

| 指标 | 是否有数据 | 可用记录数 | 缺失维度 |
|------|:---------:|-----------:|---------|
（填入每个指标的状态，与覆盖报告一致）

**不足原因**：解释为何不足以支撑综合分析（如趋势需≥3 个时间点，当前仅 1 个）。

**可分析范围**：明确告知基于现有数据可进行哪些分析。

### 后续建议
- 补齐缺失维度的具体建议（补录哪些数据/字段）
- 调整分析目标的替代方案
"""


# ============================================================
# 场景 3：计算类指标呈现（计算分解 + 对标 + 业务含义）
# ============================================================

ANALYST_COMPUTED_METRICS_PROMPT = _ROLE_HEADER + """## 硬约束（最高优先级，必须遵守）
- 计算分解的各分量必须与查询结果数值一致，**不得编造结果集中未出现的数值**
- 无内部可对比数据时，**不得编造外部基准值**
- 百分比保留1位小数；计数取整；金额/物理量保留2位小数
- 禁止直接粘贴 SQL 结果表作为主回答

## 用户问题
{question}

## 查询结果（前10行，含原始数值）
{raw_data}

## 指标定义与计算方法
{indicator_context}

## 指标类型
{indicator_types}  （direct=直接查询型，computed=计算型）

## 输出要求（严格按此结构，使用 Markdown）
## 分析结论
用一句话概括整体发现。

### 指标明细
对每个 **computed** 指标，按以下卡片格式输出：

**{{指标名称}}：{{计算结果}}{{单位}}**
- 计算分解：{{分量A}} {{运算符}} {{分量B}} ... = {{结果}}
- 对标解读：仅当结果集内部可对比时给出（如同比/跨群体/跨指标）；无可对比则写"暂无可对标基准"
- 业务含义：一句话解释该数值反映的状况

对 **direct** 指标，输出精简描述（数值+单位+一句含义），不展开分解。

### 后续建议
- 2-3 条可操作建议，每条含「发现+依据+动作」

> 术语说明：对每个公式涉及的术语给出定义，如"合格率=合格人数÷总人数×100%"
"""


# ============================================================
# 场景 4：标准（充分数据，纯直接型指标）
# ============================================================

ANALYST_STANDARD_PROMPT = _ROLE_HEADER + """## 用户问题
{question}

## SQL查询
{sql}

## 结果统计
{result_summary}

## 数据预览(前10行)
{raw_data}

## 指标定义
{indicator_context}

## 输出要求（严格按此结构，使用 Markdown）
## 分析结论
用一句话概括整体发现。

### 指标明细
逐指标给出数值+单位+一句含义；多个指标时用列表呈现。
引用具体数值，不做空泛评论。

### 后续建议
- 2-3 条可操作建议，每条含「发现+依据+动作」

> 术语说明：涉及公式/术语时给出定义；无则省略本段

## 硬约束
- 不输出原始 SQL 结果表
- 不编造未出现的数值
- 保持简洁，不做长篇报告
"""


# ============================================================
# 上下文格式化辅助函数
# ============================================================

def _format_coverage_table(report: dict) -> str:
    """将 sufficiency_report.per_indicator 格式化为 Markdown 覆盖表。

    Args:
        report: assess_data_sufficiency 返回的评估报告

    Returns:
        Markdown 表格字符串
    """
    per_ind = report.get("per_indicator", [])
    if not per_ind:
        return "（无指标定义）"
    lines = [
        "| 指标 | 是否有数据 | 可用记录数 | 缺失维度 |",
        "|------|:---------:|-----------:|---------|",
    ]
    for p in per_ind:
        status = "✓" if p.get("has_data") else "✗"
        miss = "、".join(p.get("missing_dimensions", [])) or "—"
        lines.append(
            f"| {p.get('name', '')} | {status} | "
            f"{p.get('row_count', 0)} | {miss} |")
    return "\n".join(lines)


def _format_indicator_types(indicator_types: dict,
                            indicator_defs: list) -> str:
    """格式化指标类型列表，供计算型 Prompt 注入。

    Args:
        indicator_types: {指标名: "direct"|"computed"} 映射
        indicator_defs:  指标定义列表（用于保持顺序）

    Returns:
        每行一个指标的类型说明
    """
    parts = []
    for ind in (indicator_defs or []):
        name = ind.get("name", "")
        if not name:
            continue
        t = indicator_types.get(name, "direct")
        parts.append(f"- {name}: {t}")
    return "\n".join(parts) if parts else "无"


# ============================================================
# 主函数
# ============================================================

async def run_analyst(state: EvaluationState, llm_call_fn,
                      stream_llm_gen=None) -> EvaluationState:
    """基于查询结果与数据充分性报告，按场景生成结构化分析结论。

    根据 state.sufficiency_report.scenario 路由到对应 Prompt：
      - no_data      → 无数据声明 + 后续指引
      - insufficient → 覆盖表 + 不足原因 + 后续指引
      - sufficient 且存在计算型指标 → 计算分解 + 对标 + 业务含义
      - sufficient 且纯直接型       → 数值 + 含义 + 建议

    支持流式（stream_llm_gen）与非流式（llm_call_fn）两种调用方式。

    Args:
        state:          当前评估状态，含 question / raw_results /
                        generated_sql / sufficiency_report / indicator_types 等
        llm_call_fn:    LLM 调用函数 async fn(system_prompt, user_prompt) -> str
        stream_llm_gen: 可选的流式生成器 async gen(system_prompt, user_prompt)
                        -> AsyncGenerator[str]；提供时逐 token 消费

    Returns:
        更新后的 EvaluationState（final_answer 已填充）
    """
    logger.info(f"Running analyst for: {state.question[:100]}")

    # 添加执行步骤记录，供前端展示进度
    state.add_step(7.1, "生成分析建议", "in_progress",
                   "正在基于数据调用大模型生成建议...")

    # ── 初始化上下文默认值 ──
    result_summary = "未执行SQL"
    raw_data = "无"
    indicator_context = "无"
    indicator_names_only = "无"  # no_data 场景专用：仅指标名称，不含公式
    table_context = "无"

    # ── 构建数据摘要与预览 ──
    if state.raw_results:
        total_rows = len(state.raw_results)
        if total_rows > 0:
            raw_data = json.dumps(state.raw_results[:10], ensure_ascii=False, indent=2)
            if total_rows > 10:
                raw_data += f"\n... (共 {total_rows} 行，仅显示前10行)"
            result_summary = f"查询返回 {total_rows} 行数据"
        else:
            result_summary = "查询返回 0 行"
    elif state.execution_error:
        result_summary = f"失败: {state.execution_error[:100]}"
        raw_data = f"错误: {state.execution_error}"

    # ── 构建指标定义上下文（最多前5个，控制 prompt 长度）──
    # indicator_context:       含公式与说明，供 insufficient/computed/standard 场景使用
    # indicator_names_only:    仅名称，供 no_data 场景使用（避免公式诱导 LLM 编造数值）
    if state.indicator_defs:
        parts = []
        name_parts = []
        for ind in state.indicator_defs[:5]:
            parts.append(
                f"- {ind.get('name', '')}: {ind.get('formula', '')} "
                f"{ind.get('description', '')}")
            name_parts.append(f"- {ind.get('name', '')}")
        indicator_context = "\n".join(parts)
        indicator_names_only = "\n".join(name_parts)

    # ── 构建表结构上下文（无数据场景使用）──
    if hasattr(state, 'table_schemas') and state.table_schemas:
        table_parts = []
        for schema in state.table_schemas:
            table_name = schema.get("tableName", "")
            desc = schema.get("description", "")
            cols = schema.get("columns", [])
            col_list = "、".join(c.get("columnName", "") for c in cols[:10])
            table_parts.append(
                f"- {table_name}: {len(cols)} 列 ({col_list})"
                + (f" — {desc}" if desc else ""))
        table_context = "\n".join(table_parts)

    # ── 读取数据充分性报告 ──
    report = state.sufficiency_report or {}
    scenario = report.get("scenario", "sufficient")
    scenario_reason = report.get("reason", "")

    # ── 向后兼容兜底：未注入 sufficiency_report 的调用方（如 langgraph /
    #    react 路径），若查询无数据，降级为 no_data 场景，保持原有行为 ──
    if not state.sufficiency_report and not state.raw_results:
        scenario = "no_data"
        scenario_reason = (
            f"查询技术失败：{state.execution_error[:120]}"
            if state.execution_error
            else "查询成功但返回 0 行，数据库中无相关数据")

    # ── 场景化 Prompt 路由 ──
    indicator_types = state.indicator_types or {}
    has_computed = any(t == "computed" for t in indicator_types.values())

    if scenario == "no_data":
        # 区分「查询技术失败」与「库无数据」两个子场景：
        # 技术失败 → TECHNICAL_FAILURE_PROMPT（不注入公式/表结构，避免诱导编造）
        # 库无数据 → 精简版 NO_DATA_PROMPT（仅指标名称，无公式/表结构）
        if report.get("technical_failure"):
            system_prompt = ANALYST_TECHNICAL_FAILURE_PROMPT.format(
                scenario_reason=scenario_reason,
                question=state.question,
                indicator_context=indicator_names_only,
            )
            user_msg = "请按结构输出查询失败说明与排查建议。"
        else:
            system_prompt = ANALYST_NO_DATA_PROMPT.format(
                scenario_reason=scenario_reason,
                question=state.question,
                indicator_context=indicator_names_only,
            )
            user_msg = "请按结构输出无数据分析结论与后续指引。"
    elif scenario == "insufficient":
        system_prompt = ANALYST_INSUFFICIENT_DATA_PROMPT.format(
            scenario_reason=scenario_reason,
            question=state.question,
            sufficiency_report_table=_format_coverage_table(report),
            raw_data=raw_data,
            indicator_context=indicator_context,
        )
        user_msg = "请按结构输出数据不足分析结论与覆盖表。"
    elif has_computed:
        system_prompt = ANALYST_COMPUTED_METRICS_PROMPT.format(
            question=state.question,
            raw_data=raw_data,
            indicator_context=indicator_context,
            indicator_types=_format_indicator_types(
                indicator_types, state.indicator_defs),
        )
        user_msg = "请按结构输出计算类指标分析结论，含计算分解与对标。"
    else:
        system_prompt = ANALYST_STANDARD_PROMPT.format(
            question=state.question,
            sql=state.generated_sql or "无需SQL",
            result_summary=result_summary,
            raw_data=raw_data,
            indicator_context=indicator_context,
        )
        user_msg = "请基于数据给出结构化分析结论。"

    logger.info(f"[analyst] 场景={scenario}, has_computed={has_computed}, "
                f"prompt长度={len(system_prompt)}")

    try:
        if stream_llm_gen:
            response = ""
            async for chunk in stream_llm_gen(system_prompt, user_msg):
                response += chunk
        else:
            response = await llm_call_fn(system_prompt, user_msg)
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
