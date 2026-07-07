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


def _api_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def run(database_id):
    queries = load_queries()
    results = []
    all_summaries = []

    for group in queries:
        group_name = group["group"]
        for q in group["queries"]:
            label = q["label"]
            viz_type = q.get("vizType", "table")
            sql = q.get("sql", "")

            logger.info(f"Executing: {group_name}/{label}")
            exec_result = execute_sql(database_id, sql)

            if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
                columns = exec_result.get("columns", [])
                rows = exec_result.get("rows", [])

                data_sample = {
                    "columns": columns,
                    "rows": rows[:10],
                    "totalRows": len(rows)
                }

                insight_prompt = f"""请基于以下数据做简要分析(200字以内):
查询类型: {group_name} - {label}
列: {columns}
数据(前10行): {rows[:10]}
总行数: {len(rows)}

请给出1-2句关键发现。"""
                insight = analyze_with_llm(insight_prompt)
            else:
                data_sample = None
                insight = exec_result.get("message", "查询无数据")

            results.append({
                "group": group_name,
                "label": label,
                "vizType": viz_type,
                "columns": exec_result.get("columns", []),
                "rows": exec_result.get("rows", []),
                "rowCount": exec_result.get("rowCount", 0),
                "insight": insight
            })
            all_summaries.append(f"[{group_name}-{label}]: {insight}")

            time.sleep(0.3)

    if all_summaries:
        summary_prompt = f"请基于以下各维度的简要分析，给出50字以内的整体作战效能评估总结:\n" + "\n".join(all_summaries)
        summary = analyze_with_llm(summary_prompt)
    else:
        summary = "暂无有效数据可供评估"

    return {
        "type": "combat_effectiveness",
        "results": results,
        "summary": summary
    }
