"""
作战效能分析智能体 (Combat Effectiveness Agent)
负责：根据用户提问，加载预配置的作战效能分析SQL模板，执行多维度查询并给出综合评估
"""
import asyncio
import json
import logging
import os
import re
import time

from .tools import execute_sql_on_database

logger = logging.getLogger("evaluation.combat_effectiveness")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERIES_FILE = os.path.join(BASE_DIR, "config", "queries.json")

_YIELD_DELAY = 0.25


def load_queries():
    path = os.getenv("COMBAT_QUERIES_PATH", QUERIES_FILE)
    if not os.path.exists(path):
        logger.warning(f"queries.json not found at {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _step_event(step_num, description, status, detail="", thinking="", progress=None, sub_step=None):
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
    """将单段 prompt 适配为 system + user 调用"""
    response = await llm_call_fn(
        "你是专业评估分析专家，简洁回答，不超过200字。",
        prompt
    )
    return response or "分析结果不可用"


def _select_queries_by_keywords(user_query, all_queries):
    """简单关键字匹配：优先选用户问题中提到的查询"""
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

    if len(query_list) <= 2:
        return query_list

    # 关键字匹配 vs LLM 兜底
    matched = []
    q_lower = user_query.lower()
    for q in query_list:
        kws = q.get("keywords", [])
        if kws and any(kw.lower() in q_lower for kw in kws):
            matched.append(q)

    if matched:
        logger.info(f"Keyword-matched {len(matched)}/{len(query_list)} queries")
        return matched

    return query_list


async def _select_queries_by_llm(user_query, all_queries, llm_call_fn):
    """用 LLM 选择相关查询"""
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

    if len(query_list) <= 2:
        return query_list

    query_index = ""
    for i, q in enumerate(query_list):
        kws = ", ".join(q.get("keywords", [])) or q["label"]
        query_index += f"[{i}] {q['group']}/{q['label']} 关键词: {kws}\n"

    selection_prompt = f"""用户提问: "{user_query}"

可选SQL查询列表:
{query_index}

请根据用户提问选择相关的查询编号, 返回JSON数组格式: [0, 2, 5] (只包含编号, 不要其他文字)
如果用户问得宽泛则多选, 问得具体则少选。最少选1条。"""

    answer = await _adapted_llm_call(selection_prompt, llm_call_fn)
    try:
        matches = re.findall(r'\d+', answer)
        indices = [int(m) for m in matches if 0 <= int(m) < len(query_list)]
        if not indices:
            return query_list
        return [query_list[i] for i in indices]
    except Exception:
        return query_list


async def run_stream(user_query: str, database_id: str, llm_call_fn):
    """作战效能分析 — 异步流式生成器"""
    all_queries = load_queries()
    if not all_queries:
        yield _step_event(4, "执行分析计算", "completed",
                         detail="未找到SQL配置, 请检查 config/queries.json", progress=100,
                         thinking="作战效能分析智能体已加载，但 queries.json 为空或未找到")
        return

    step_base = 4  # 在 workflow 中作为子步骤

    yield _step_event(step_base, "作战效能分析", "in_progress",
                     detail="正在根据提问匹配分析维度...", progress=5,
                     thinking="【作战效能分析智能体】\n加载了 queries.json 中的预配置SQL模板")

    await asyncio.sleep(_YIELD_DELAY)

    # 先用关键字匹配，再用 LLM
    selected = _select_queries_by_keywords(user_query, all_queries)
    if len(selected) == len(all_queries) or len(selected) == 0:
        selected = await _select_queries_by_llm(user_query, all_queries, llm_call_fn)

    total = len(selected)
    executed = 0

    yield _step_event(step_base, "作战效能分析", "in_progress",
                     detail=f"已选定 {total} 条相关查询, 执行数据查询中...", progress=10,
                     thinking=f"选中 {total} 条查询: " + ", ".join(q["label"] for q in selected))

    await asyncio.sleep(_YIELD_DELAY)

    all_results = []
    all_summaries = []

    for q in selected:
        label = q["label"]
        viz_type = q.get("vizType", "table")
        sql = q.get("sql", "")
        group_name = q.get("group", "")

        yield _step_event(step_base, "作战效能分析", "in_progress",
                         detail=f"正在查询: {label}", progress=int(10 + 75 * executed / max(total, 1)),
                         thinking=f"【执行SQL - {group_name}/{label}】\n{sql[:400]}")

        await asyncio.sleep(_YIELD_DELAY)

        exec_result = execute_sql_on_database(database_id, sql)
        executed += 1

        if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
            columns = exec_result.get("columns", [])
            rows = exec_result.get("rows", [])

            yield _step_event(step_base, "作战效能分析", "in_progress",
                             detail=f"正在分析: {label} ({exec_result.get('rowCount')}条)",
                             progress=int(10 + 75 * executed / max(total, 1)),
                             thinking=f"查询 [{label}] 返回 {len(rows)} 行, 正在调用LLM分析...")

            await asyncio.sleep(_YIELD_DELAY)

            insight_prompt = f"""请基于以下数据做简要分析(200字以内):
查询类型: {group_name} - {label}
列: {columns}
数据(前10行): {str(rows[:10])}
总行数: {len(rows)}

请给出1-2句关键发现。"""
            insight = await _adapted_llm_call(insight_prompt, llm_call_fn)
        else:
            insight = exec_result.get("message", "查询无数据")

        all_results.append({
            "group": group_name,
            "label": label,
            "vizType": viz_type,
            "columns": exec_result.get("columns", []),
            "rows": exec_result.get("rows", []),
            "rowCount": exec_result.get("rowCount", 0),
            "insight": insight
        })
        all_summaries.append(f"[{group_name}-{label}]: {insight}")

        await asyncio.sleep(_YIELD_DELAY)

    yield _step_event(step_base, "作战效能分析", "in_progress",
                     detail="正在生成综合评估总结...", progress=90,
                     thinking="所有查询执行完毕，正在汇总LLM分析...")

    await asyncio.sleep(_YIELD_DELAY)

    if all_summaries:
        summary_prompt = "请基于以下各维度的分析，给出100字以内的评估总结:\n用户提问: " + user_query + "\n" + "\n".join(all_summaries)
        summary = await _adapted_llm_call(summary_prompt, llm_call_fn)
    else:
        summary = "暂无有效数据可供评估"

    yield _step_event(step_base, "作战效能分析", "completed",
                     detail="作战效能分析完成", progress=100,
                     thinking=f"【综合评估总结】\n{summary[:800]}")

    # 最终结果
    final = {
        "type": "result",
        "result": {
            "type": "combat_effectiveness",
            "final_answer": summary,
            "combatResults": all_results,
            "generatedSql": None,
            "rawResults": [],
            "totalRows": sum(r.get("rowCount", 0) for r in all_results),
        }
    }
    yield final
