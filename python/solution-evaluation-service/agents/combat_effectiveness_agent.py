import json
import logging
import os
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


def run_stream(database_id):
    queries = load_queries()
    total_queries = sum(len(g["queries"]) for g in queries)
    executed = 0

    if not queries:
        yield _make_step(4, "analysis", "执行分析计算", "completed",
                         "未找到SQL配置, 请检查 config/queries.json", 100)
        return

    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     f"正在连接数据源并执行 {total_queries} 条分析查询...", 5)

    all_results = []
    all_summaries = []

    for group in queries:
        group_name = group["group"]
        for q in group["queries"]:
            label = q["label"]
            viz_type = q.get("vizType", "table")
            sql = q.get("sql", "")

            yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                             f"正在查询: {group_name} - {label}", int(5 + 80 * executed / max(total_queries, 1)),
                             sub_step=group_name)

            exec_result = execute_sql(database_id, sql)
            executed += 1

            if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
                columns = exec_result.get("columns", [])
                rows = exec_result.get("rows", [])

                yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                                 f"正在分析: {group_name} - {label} (共{exec_result.get('rowCount')}条)",
                                 int(5 + 80 * executed / max(total_queries, 1)),
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
        summary_prompt = "请基于以下各维度的简要分析，给出50字以内的整体作战效能评估总结:\n" + "\n".join(all_summaries)
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
