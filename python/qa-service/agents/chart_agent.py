"""
图表智能体 (Chart Agent)
在 SQL 执行后，根据列名 + 样本数据（前 5 行）规划图表配置。
前端用全量数据填充渲染，因此 LLM 只收到样本数据，不接收全量。
"""
import json
import logging

logger = logging.getLogger("evaluation.chart")

CHART_SYSTEM_PROMPT = """你是图表设计专家。根据 SQL 查询结果的列名和样本数据，设计最合适的 ECharts 图表。

## 输入信息
- 用户问题: {question}
- 列名: {columns}
- 样本数据（前 5 行）: {sample_rows}
- 总行数: {total_rows}

## 图表类型选择规则
| 条件 | vizType |
|------|---------|
| 2 列 + 多行 + 第 2 列适合看占比 | pie |
| 2 列 + 多行 + 第 2 列适合直接对比 | bar |
| 3+ 列 + 首列文本 + 其余为数值 | bar |
| 首列是时间/日期 | line |
| 仅 1 行数据 | table |
| 数据为空 | table |
| 文本列多于数值列 | table |

## 字段映射
- xAxis: X 轴（分类轴）字段名，必须是第一列（通常是维度/分类字段）
- yAxis: Y 轴（数值轴）字段名列表，其余数值列

## 输出 JSON（不要 markdown 包裹）
{{
    "vizType": "bar",
    "chartTitle": "图表标题",
    "xAxis": "分类字段名",
    "yAxis": ["数值字段1", "数值字段2"]
}}
"""


async def run_chart_agent(
    columns: list,
    sample_rows: list,
    total_rows: int,
    question: str,
    llm_call_fn,
) -> dict:
    """
    根据列名 + 样本数据，调用 LLM 规划图表配置。

    Args:
        columns: 列名列表，如 ["区域", "红方战损", "蓝方战损"]
        sample_rows: 样本数据（前 5 行），每行为 dict，如 [{"区域": "A区", ...}, ...]
        total_rows: 总行数
        question: 用户原始问题
        llm_call_fn: LLM 调用函数 async fn(system_prompt, user_prompt) -> str

    Returns:
        dict: {"vizType": "bar", "chartTitle": "...", "xAxis": "...", "yAxis": [...]}
              或 {"vizType": "table"}（不适合图表）
    """
    if not columns or not sample_rows:
        logger.info("Chart agent: 无数据，返回 table")
        return {"vizType": "table"}

    if total_rows <= 1:
        logger.info("Chart agent: 仅 1 行数据，不适合图表")
        return {"vizType": "table"}

    # 仅保留前 5 行作为样本
    sample = sample_rows[:5]
    sample_text = json.dumps(sample, ensure_ascii=False)

    system_prompt = CHART_SYSTEM_PROMPT.format(
        question=question,
        columns=json.dumps(columns, ensure_ascii=False),
        sample_rows=sample_text,
        total_rows=total_rows,
    )

    user_prompt = f"用户问题: {question}\n\n请根据以上样本数据设计图表。"

    try:
        response = await llm_call_fn(system_prompt, user_prompt)
        logger.info(f"Chart agent raw response: {response[:500]}")
        config = _parse_chart_response(response)
        return config
    except Exception as e:
        logger.warning(f"Chart agent 调用失败，降级为表格: {e}")
        return {"vizType": "table"}


def _parse_chart_response(text: str) -> dict:
    """解析 LLM 返回的图表配置 JSON"""
    text = text.strip()

    # 提取 JSON
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start) if "```" in text[start:] else len(text)
        text = text[start:end].strip()

    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                config = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning(f"Chart agent JSON 解析失败: {text[:300]}")
                return {"vizType": "table"}
        else:
            return {"vizType": "table"}

    # 校验必要字段
    viz_type = config.get("vizType", "table")
    if viz_type not in ("bar", "line", "pie"):
        viz_type = "table"

    return {
        "vizType": viz_type,
        "chartTitle": config.get("chartTitle", ""),
        "xAxis": config.get("xAxis", ""),
        "yAxis": config.get("yAxis", []),
    }
