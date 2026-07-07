import json
import logging
import os
import re
import ssl
import time
import urllib.request

logger = logging.getLogger("air-superiority-agent")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIR_QUERIES_FILE = os.path.join(BASE_DIR, "config", "air_queries.json")

ADMIN_HOST = os.getenv("ADMIN_SERVICE_URL", "http://localhost:10258")
QA_HOST = os.getenv("QA_SERVICE_URL", "http://localhost:10253")


def load_air_queries():
    path = os.getenv("AIR_QUERIES_PATH", AIR_QUERIES_FILE)
    if not os.path.exists(path):
        logger.warning(f"air_queries.json not found at {path}")
        return {"regionRules": {"patterns": [], "placeholder": "{region}", "defaultValue": "全部区域"}, "groups": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_region(user_query, region_rules):
    """从用户提问中提取区域名称"""
    placeholder = region_rules.get("placeholder", "{region}")
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


def select_queries_by_intent(user_query, groups):
    """根据用户提问选择相关查询，使用LLM进行意图匹配"""
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

    # 如果只有少量查询，全部执行
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
    """制空权分析智能体流式执行"""
    config = load_air_queries()
    region_rules = config.get("regionRules", {})
    groups = config.get("groups", [])

    if not groups:
        yield _make_step(4, "analysis", "执行分析计算", "completed",
                         "未找到SQL配置, 请检查 config/air_queries.json", 100)
        return

    placeholder = region_rules.get("placeholder", "{region}")

    # 步骤1: 区域提取
    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     "正在识别用户提问中的目标区域...", 5, sub_step="区域识别")

    region = extract_region(user_query, region_rules)

    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     f"已识别目标区域: {region}", 10, sub_step="区域识别")

    # 步骤2: 意图匹配，选择相关查询
    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     "正在根据提问选择相关分析维度...", 15, sub_step="意图匹配")

    selected = select_queries_by_intent(user_query, groups)
    total = len(selected)

    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     f"已选定 {total} 条相关查询, 开始注入区域参数并执行...", 20)

    # 步骤3: 逐条执行SQL
    all_results = []
    all_summaries = []
    executed = 0

    for q in selected:
        label = q["label"]
        viz_type = q.get("vizType", "table")
        sql_template = q.get("sql", "")
        group_name = q.get("group", "")

        # 注入区域参数
        sql = inject_region(sql_template, region, placeholder)

        yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                         f"正在查询: {label} (区域: {region})", 
                         int(20 + 60 * executed / max(total, 1)),
                         sub_step=group_name)

        exec_result = execute_sql(database_id, sql)
        executed += 1

        if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
            columns = exec_result.get("columns", [])
            rows = exec_result.get("rows", [])

            yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                             f"正在分析: {label} (共{exec_result.get('rowCount')}条数据)",
                             int(20 + 60 * executed / max(total, 1)),
                             sub_step=group_name)

            insight_prompt = f"""请基于以下制空权分析数据做简要分析(200字以内):
分析维度: {group_name} - {label}
区域: {region}
列: {columns}
数据: {str(rows[:10])}
总行数: {len(rows)}

请给出1-2句关键发现，重点关注红蓝双方对比。"""
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

    # 步骤4: 综合评估
    yield _make_step(4, "analysis", "执行分析计算", "in_progress",
                     "正在生成制空权综合评估总结...", 85, sub_step="综合评估")

    if all_summaries:
        summary_prompt = f"""请基于以下各维度的制空权分析数据，给出{region}区域的制空权综合评估总结(300字以内):

用户提问: {user_query}
分析区域: {region}

各维度分析结果:
{chr(10).join(all_summaries)}

请从以下方面进行总结:
1. 红蓝双方在{region}区域的总体制空权对比
2. 各维度（占位、打击、侦察、总体）的能力差异
3. 制空权优势方及优势程度
4. 作战建议"""
        summary = analyze_with_llm(summary_prompt)
    else:
        summary = f"暂无{region}区域的有效制空权数据可供评估"

    yield _make_step(4, "analysis", "执行分析计算", "completed",
                     "制空权分析完成", 100)

    final_result = {
        "type": "air_superiority",
        "region": region,
        "queryResults": all_results,
        "summary": summary
    }

    yield json.dumps({"type": "result", "result": final_result}, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
