"""
制空权分析智能体 (Air Superiority Agent)
负责：根据用户提问，从提问中提取目标区域，加载预配置的制空权分析SQL模板，
     注入区域参数后执行多维度查询，给出红蓝双方对比分析
"""
import asyncio
import json
import logging
import os
import re

from .tools import execute_sql_on_database

logger = logging.getLogger("evaluation.air_superiority")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIR_QUERIES_FILE = os.path.join(BASE_DIR, "config", "air_queries.json")

_YIELD_DELAY = 0.25


def load_air_queries():
    path = os.getenv("AIR_QUERIES_PATH", AIR_QUERIES_FILE)
    if not os.path.exists(path):
        logger.warning(f"air_queries.json not found at {path}")
        return {"regionRules": {"patterns": [], "placeholder": "{region}", "defaultValue": "全部区域"}, "groups": []}
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
        # 移除 JSON 不允许的控制字符（保留 \t \n \r）
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
        return json.loads(cleaned)


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
    response = await llm_call_fn(
        "你是专业军事评估分析专家，简洁回答，不超过200字。",
        prompt
    )
    return response or "分析结果不可用"


def extract_region(user_query, region_rules):
    """从用户提问中提取区域名称"""
    default_value = region_rules.get("defaultValue", "全部区域")
    for rule in region_rules.get("patterns", []):
        pattern = rule.get("regex", "")
        group = rule.get("group", 1)
        suffix = rule.get("suffix", "")
        try:
            match = re.search(pattern, user_query)
            if match and group <= len(match.groups()):
                extracted = match.group(group).strip()
                if suffix and not extracted.endswith(suffix):
                    extracted = extracted + suffix
                return extracted
        except Exception:
            continue
    return default_value


def inject_region(sql, region, placeholder):
    """将区域名称注入SQL中的占位符"""
    return sql.replace(placeholder, region)


async def _select_queries_by_llm(user_query, groups, llm_call_fn):
    query_list = []
    for g in groups:
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


async def run_stream(user_query: str, database_id: str, llm_call_fn, need_conclusion: bool = True):
    """制空权分析 — 异步流式生成器

    Args:
        need_conclusion: True=执行SQL+LLM生成结论; False=仅执行SQL返回数据
    """
    config = load_air_queries()
    region_rules = config.get("regionRules", {})
    groups = config.get("groups", [])
    placeholder = region_rules.get("placeholder", "{region}")

    if not groups:
        yield _step_event(4, "制空权分析", "completed",
                         detail="未找到SQL配置, 请检查 config/air_queries.json", progress=100,
                         thinking="制空权分析智能体已加载，但 air_queries.json 为空或未找到")
        return

    step_base = 4

    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail="正在识别目标区域...", progress=5,
                     thinking="【制空权分析智能体】\n从用户提问中提取区域信息，匹配预配置的SQL模板")

    await asyncio.sleep(_YIELD_DELAY)

    # 步骤1: 区域提取
    region = extract_region(user_query, region_rules)

    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail=f"已识别区域: {region}", progress=10,
                     thinking=f"提取到区域: {region}\n区域规则: {json.dumps(region_rules, ensure_ascii=False)[:300]}")

    await asyncio.sleep(_YIELD_DELAY)

    # 步骤2: 选择相关查询
    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail="正在匹配分析维度...", progress=15,
                     thinking="根据用户提问从 air_queries.json 中选择相关分析维度")

    await asyncio.sleep(_YIELD_DELAY)

    selected = await _select_queries_by_llm(user_query, groups, llm_call_fn)
    total = len(selected)

    mode_label = "查询+结论" if need_conclusion else "仅查询数据"
    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail=f"已选定 {total} 条相关查询, 区域 [{region}], 模式: {mode_label}", progress=20,
                     thinking=f"选中 {total} 条查询, 区域={region}: " + ", ".join(q["label"] for q in selected))

    await asyncio.sleep(_YIELD_DELAY)

    # 步骤3: 逐条执行
    all_results = []
    all_summaries = []
    executed = 0

    for q in selected:
        label = q["label"]
        sql = q.get("sql", "")
        group_name = q.get("group", "")

        # 注入区域参数
        sql = inject_region(sql, region, placeholder)

        yield _step_event(step_base, "制空权分析", "in_progress",
                         detail=f"正在查询: {label} (区域: {region})",
                         progress=int(20 + 60 * executed / max(total, 1)),
                         thinking=f"【执行SQL - {group_name}/{label}】\n区域={region}\n{sql[:400]}")

        await asyncio.sleep(_YIELD_DELAY)

        exec_result = execute_sql_on_database(database_id, sql)
        executed += 1

        insight = ""
        if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
            columns = exec_result.get("columns", [])
            rows = exec_result.get("rows", [])

            if need_conclusion:
                yield _step_event(step_base, "制空权分析", "in_progress",
                                 detail=f"正在分析: {label} ({exec_result.get('rowCount')}条)",
                                 progress=int(20 + 60 * executed / max(total, 1)),
                                 thinking=f"查询 [{label}] 返回 {len(rows)} 行, 正在调用LLM分析...")

                await asyncio.sleep(_YIELD_DELAY)

                insight_prompt = f"""请基于以下制空权分析数据做简要分析(100字以内):
分析维度: {group_name} - {label}
区域: {region}
列: {columns}
数据: {str(rows[:10])}
总行数: {len(rows)}

请给出1-2句关键发现，重点关注红蓝双方对比。"""
                insight = await _adapted_llm_call(insight_prompt, llm_call_fn)
            else:
                yield _step_event(step_base, "制空权分析", "in_progress",
                                 detail=f"已查询: {label} ({exec_result.get('rowCount')}条)",
                                 progress=int(20 + 60 * executed / max(total, 1)),
                                 thinking=f"查询 [{label}] 返回 {len(rows)} 行 (仅数据模式，跳过LLM分析)")
                await asyncio.sleep(_YIELD_DELAY)
        else:
            insight = exec_result.get("message", "查询无数据")

        all_results.append({
            "group": group_name,
            "label": label,
            "sql": sql,
            "columns": exec_result.get("columns", []),
            "rows": exec_result.get("rows", []),
            "rowCount": exec_result.get("rowCount", 0),
            "insight": insight
        })
        if insight:
            all_summaries.append(f"[{group_name}-{label}]: {insight}")

        await asyncio.sleep(_YIELD_DELAY)

    # 步骤4: 综合评估（仅 need_conclusion=True 时生成）
    summary = ""
    if need_conclusion:
        yield _step_event(step_base, "制空权分析", "in_progress",
                         detail="正在生成制空权综合评估总结...", progress=85,
                         thinking="所有查询执行完毕，正在汇总LLM分析...")

        await asyncio.sleep(_YIELD_DELAY)

        if all_summaries:
            summary_prompt = f"""请基于以下各维度的制空权分析数据，给出{region}区域的制空权综合评估总结(100字以内):

用户提问: {user_query}
分析区域: {region}

各维度分析结果:
{chr(10).join(all_summaries)}

请简明给出红蓝双方制空权对比结论。"""
            summary = await _adapted_llm_call(summary_prompt, llm_call_fn)
        else:
            summary = f"暂无{region}区域的有效制空权数据可供评估"

        yield _step_event(step_base, "制空权分析", "completed",
                         detail="制空权分析完成", progress=100,
                         thinking=f"【制空权综合评估 — {region}】\n{summary[:800]}")
    else:
        yield _step_event(step_base, "制空权分析", "completed",
                         detail=f"制空权查询完成（仅数据模式），共 {len(all_results)} 条查询结果", progress=100,
                         thinking="用户未要求结论，仅返回查询数据")

    # 最终结果 — 统一 results 字段名
    final = {
        "type": "result",
        "result": {
            "type": "air_superiority",
            "region": region,
            "final_answer": summary,
            "results": all_results,
            "need_conclusion": need_conclusion,
            "generatedSql": None,
            "rawResults": [],
            "totalRows": sum(r.get("rowCount", 0) for r in all_results),
        }
    }
    yield final
