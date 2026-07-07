import json
import logging
import os
import re
import ssl
import time
import urllib.request

logger = logging.getLogger("combat-effectiveness-agent")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERIES_FILE = os.path.join(BASE_DIR, "config", "queries.json")

ADMIN_HOST = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
QA_HOST = os.getenv("QA_SERVICE_URL", "http://localhost:10253")


def load_queries():
    path = os.getenv("COMBAT_QUERIES_PATH", QUERIES_FILE)
    if not os.path.exists(path):
        logger.warning(f"queries.json not found at {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def execute_sql(database_id, sql):
    body = json.dumps({"databaseId": database_id, "sql": sql}).encode("utf-8")
    req = urllib.request.Request(
        f"{ADMIN_HOST}/api/dataquery/execute",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": str(e), "columns": [], "rows": [], "rowCount": 0}


def analyze_with_llm(prompt):
    body = json.dumps({"query": prompt, "top_k": 3}).encode("utf-8")
    req = urllib.request.Request(
        f"{QA_HOST}/qa/chat",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=180, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("answer", "")
    except Exception as e:
        return f"大模型分析失败: {str(e)[:200]}"


def _make_step(step_num, step_type, description, status, detail, progress, sub_step=None):
    s = {
        "step": step_num,
        "type": step_type,
        "description": description,
        "status": status,
        "detail": detail,
        "progress": progress
    }
    if sub_step:
        s["subStep"] = sub_step
    return json.dumps({"type": "step", "step": s}, ensure_ascii=False).encode("utf-8") + b"\n"


def select_queries_by_intent(user_query, all_queries):
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

    query_index = ""
    for i, q in enumerate(query_list):
        kws = ", ".join(q.get("keywords", [])) or q["label"]
        query_index += f"[{i}] {q['group']}/{q['label']} 关键词: {kws}\n"

    selection_prompt = f"""用户提问: "{user_query}"

可选SQL查询列表:
{query_index}

请根据用户提问选择相关的查询编号, 返回JSON数组格式: [0, 2, 5] (只包含编号, 不要其他文字)
如果用户问得宽泛则多选, 问得具体则少选。如果所有查询都相关则全选。最少选1条。"""

    answer = analyze_with_llm(selection_prompt)
    try:
        matches = re.findall(r'\d+', answer)
        indices = [int(m) for m in matches if 0 <= int(m) < len(query_list)]
        if not indices:
            return query_list
        return [query_list[i] for i in indices]
    except Exception:
        return query_list


def run_stream(user_query, database_id):
    all_queries = load_queries()
    if not all_queries:
        yield _make_step(4, "analysis", "执行分析计算", "completed",
                         "未找到SQL配置, 请检查 config/queries.json", 100)
        return

    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     f"正在根据提问选择相关分析维度...", 5)

    selected = select_queries_by_intent(user_query, all_queries)
    total = len(selected)
    executed = 0

    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     f"已选定 {total} 条相关查询, 开始执行数据查询...", 10)

    all_results = []
    all_summaries = []

    for q in selected:
        label = q["label"]
        viz_type = q.get("vizType", "table")
        sql = q.get("sql", "")
        group_name = q.get("group", "")

        yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                         f"正在查询: {label}", int(10 + 75 * executed / max(total, 1)),
                         sub_step=group_name)

        exec_result = execute_sql(database_id, sql)
        executed += 1

        if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
            columns = exec_result.get("columns", [])
            rows = exec_result.get("rows", [])

            yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                             f"正在分析: {label} (共{exec_result.get('rowCount')}条)",
                             int(10 + 75 * executed / max(total, 1)),
                             sub_step=group_name)

            insight_prompt = f"""请基于以下数据做简要分析(200字以内):
查询类型: {group_name} - {label}
列: {columns}
数据(前10行): {str(rows[:10])}
总行数: {len(rows)}

请给出1-2句关键发现。"""
            insight = analyze_with_llm(insight_prompt)
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

        time.sleep(0.2)

    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     "正在生成综合评估总结...", 90, sub_step="综合评估")

    if all_summaries:
        summary_prompt = "请基于以下各维度的简要分析，并结合用户意图，给出100字以内的评估总结:\n用户提问: " + user_query + "\n" + "\n".join(all_summaries)
        summary = analyze_with_llm(summary_prompt)
    else:
        summary = "暂无有效数据可供评估"

    yield _make_step(4, "analysis", "执行分析计算", "completed",
                     "分析计算完成", 100)

    final_result = {
        "type": "combat_effectiveness",
        "results": all_results,
        "summary": summary
    }

    yield json.dumps({"type": "result", "result": final_result}, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
