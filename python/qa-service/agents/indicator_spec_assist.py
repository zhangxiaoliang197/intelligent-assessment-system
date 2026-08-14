# -*- coding: utf-8 -*-
"""指标规格辅助能力（WS-6 待办收尾）。

覆盖两个运行期/配置期闭环：
1. 知识库指标一键导入：从知识库文档文本中解析"指标名 = 公式"候选，
   逐条生成待确认规格（LLM 建议，需人工确认 + dry-run 后才生效）。
2. 运行期即时绑定：对未配置规格的指标，LLM 只做"公式 term → 物理列"配对，
   代码负责编译 SQL 计划并对来源表做只读 dry-run 探测；确认后回写规格。

所有 LLM 输出都只是建议：必须经过编译校验 + dry-run，任何绑定缺口都明确返回，
不让模型直接产出整条 SQL。
"""

import json
import logging
import os
import re
import urllib.request

from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("evaluation.indicator_spec_assist")

_KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://localhost:10252")


# ── 公式分词 / 目录文本化（与 evaluation_api 中既有实现保持一致） ──────────
def extract_formula_terms(formula: str) -> List[str]:
    """公式分词：中文连续词 + 英文/数字标识符，用于 LLM 绑定建议的 term 清单。"""
    terms = []
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}|[A-Za-z_][A-Za-z0-9_]{1,}", formula or ""):
        t = m.group()
        if t and t not in terms:
            terms.append(t)
    return terms[:20]


def catalog_to_text(catalog: dict) -> str:
    """语义目录 → prompt 上下文文本。"""
    lines = []
    for t in catalog.get("tables", []) or []:
        desc = f"（{t.get('description')}）" if t.get("description") else ""
        lines.append(f"### 表 {t.get('tableName', '')}（数据集: {t.get('datasetName', '')}{desc}）")
        for c in t.get("columns", []) or []:
            parts = [f"  - {c.get('columnName')} ({c.get('dataType', '')})"]
            if c.get("comment"):
                parts.append(f"-- {c['comment']}")
            if c.get("annotation"):
                parts.append(f"[{c['annotation']}]")
            if c.get("businessMeaning"):
                parts.append(f"[{c['businessMeaning']}]")
            lines.append(" ".join(parts))
        km = t.get("keyMappings")
        if km:
            lines.append(f"  连接键: {km}")
    return "\n".join(lines) or "（无目录数据）"


# ── 知识库文档 → 候选指标 ────────────────────────────────────────────────
def fetch_knowledge_content(knowledge_id: str, top_k: int = 30) -> str:
    """按文档标题检索知识库分片，拼接为文本内容。

    knowledge-service 不提供整篇文档内容接口，按标题搜索能拿到该文档的
    高分分片；拼接后用于解析指标公式候选。
    """
    try:
        body = json.dumps({"query": knowledge_id, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            f"{_KNOWLEDGE_SERVICE_URL}/knowledge/search", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        chunks = data.get("results", []) or []
        if not chunks:
            # 兜底：按标题本身精确查一次
            body = json.dumps({"query": knowledge_id, "top_k": 5}).encode("utf-8")
            req = urllib.request.Request(
                f"{_KNOWLEDGE_SERVICE_URL}/knowledge/search", data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp2:
                data2 = json.loads(resp2.read().decode("utf-8"))
            chunks = data2.get("results", []) or []
        texts = []
        seen = set()
        for c in chunks:
            text = (c.get("content") or c.get("text") or "").strip()
            if text and text not in seen:
                seen.add(text)
                texts.append(text)
        return "\n".join(texts)
    except Exception as e:
        logger.warning(f"知识库检索失败: {e}")
        return ""


_FORMULA_LINE_RE = re.compile(
    r"^\s*([\u4e00-\u9fffA-Za-z0-9（）()・%％/．.\-]{2,30})"
    r"\s*[=＝]\s*(.{3,200})\s*$")


def parse_knowledge_candidates(content: str, source_title: str = "") -> List[Dict[str, Any]]:
    """从文档文本解析候选指标："指标名 = 公式" 行。

    宽松规则：等号左侧为业务词（中文/字母数字），右侧含计算语义
    （算术/比较/括号/函数或中文词），长度受限，避免把普通句子当公式。
    """
    candidates = []
    seen = set()
    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _FORMULA_LINE_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip("=＝ \t")
        formula = m.group(2).strip()
        if len(name) < 2 or len(formula) < 3:
            continue
        # 右侧需含计算信号：运算符号/函数/中文计量词，或“率/额/数/值”等业务词
        if not re.search(r"[+\-*/%×÷()]|COUNT|SUM|AVG|MAX|MIN|ROUND|DATEDIFF|"
                         r"[\u4e00-\u9fff]{2,}", formula):
            continue
        key = f"{name}|{formula}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "name": name,
            "formula": formula,
            "source": source_title or "",
        })
    return candidates


# ── LLM 绑定建议（窄任务：只出候选 JSON，不生成整条 SQL） ────────────────
async def suggest_bindings(
    indicator_name: str,
    formula: str,
    database_id: str,
    current_spec: Optional[dict] = None,
    llm_call: Optional[Callable] = None,
) -> Dict[str, Any]:
    """基于公式 + 语义目录生成绑定建议，返回 pending 规格候选。

    返回 {"success": bool, "suggestedSpec": dict, "terms": list, "message": str}
    """
    from agents.tools import fetch_database_catalog

    if llm_call is None:
        from evaluation_api import async_llm_call
        llm_call = async_llm_call

    formula = (formula or "").strip()
    if not formula:
        return {"success": False, "message": "缺少公式"}
    terms = extract_formula_terms(formula)
    if not terms:
        return {"success": False, "message": "未能从公式中解析出计算项"}

    catalog = fetch_database_catalog(database_id)
    catalog_text = catalog_to_text(catalog)
    current = current_spec or {}

    system_prompt = (
        "你是数据库指标配置助手。给定指标公式中的计算项（term）和数据库语义目录，"
        "为每个 term 建议绑定。只返回严格 JSON，不要其他文字：\n"
        '{"sourceTables": [{"alias": "a", "tableName": "物理表名"}...],\n'
        ' "keyMappings": [{"left": "a.列", "right": "b.列"}...],\n'
        ' "bindings": [{"term": "公式词", "kind": "agg", "agg": "COUNT|SUM|AVG|MIN|MAX",\n'
        '   "table": "别名", "column": "物理列名"}...],\n'
        ' "dimensions": [{"alias": "d", "table": "别名", "column": "物理列名"}...],\n'
        ' "parameters": [{"name": "参数名", "term": "公式词", "type": "filter",\n'
        '   "target": {"table": "别名", "column": "物理列名"}}...],\n'
        ' "notes": ["一句话说明每个绑定依据"]}\n'
        "规则：\n"
        "1. 表名/列名必须严格来自上方语义目录；\n"
        "2. 找不到对应列的 term 不要强行绑定，notes 里说明；\n"
        "3. 跨表时给出 keyMappings；\n"
        "4. agg 只允许 COUNT/SUM/AVG/MIN/MAX；\n"
        "5. 若某 term 表示过滤条件（如某物品），放入 parameters.target。"
    )
    user_message = (
        f"指标名称：{indicator_name or '未知'}\n"
        f"公式：{formula}\n"
        f"计算项：{', '.join(terms)}\n\n"
        f"当前已有规格（可为空）：\n{json.dumps(current, ensure_ascii=False)[:1000]}\n\n"
        f"数据库语义目录：\n{catalog_text[:6000]}"
    )

    try:
        response = await llm_call(system_prompt, user_message)
    except Exception as e:
        logger.warning(f"LLM 绑定建议失败: {e}")
        return {"success": False, "message": f"LLM 调用失败: {str(e)[:120]}"}

    m = re.search(r"\{.*\}", response, re.DOTALL)
    if not m:
        return {"success": False, "message": "LLM 响应未包含 JSON"}
    try:
        suggested = json.loads(m.group())
    except json.JSONDecodeError as e:
        return {"success": False, "message": f"JSON 解析失败: {e}"}

    suggested.setdefault("formula", formula)
    suggested.setdefault("terms", terms)
    suggested.setdefault("status", "pending")
    return {"success": True, "suggestedSpec": suggested, "terms": terms}


# ── 编译 + dry-run 校验（运行期即时绑定三道校验中的后两道） ──────────────
def _quote_table(table: str, quote_style: str) -> str:
    if quote_style == "backtick":
        return f"`{table}`"
    if quote_style == "double":
        return f'"{table}"'
    return table


def compile_and_probe_spec(
    spec: Dict[str, Any],
    database_id: str,
    db_type: str = "",
) -> Dict[str, Any]:
    """编译规格并 dry-run 探测来源表（只读 SELECT LIMIT 1）。

    返回 {"ok", "sql", "errors", "gaps", "checks": [{"table","ok","message"}]}
    """
    from agents.indicator_engine import _quote_style_for, build_check_schema, compile_indicator_spec
    from agents.tools import execute_sql_on_database, fetch_database_catalog

    quote_style = _quote_style_for(db_type)
    catalog = fetch_database_catalog(database_id)
    schemas = []
    for t in catalog.get("tables", []) or []:
        schemas.append({
            "tableName": t.get("tableName", ""),
            "columns": t.get("columns", []) or [],
        })
    check_schema = build_check_schema(schemas)

    ok, plan = compile_indicator_spec(spec, check_schema=check_schema, quote_style=quote_style)
    # 安全护栏：多来源表但无连接键时禁止合并为笛卡尔积（LLM 建议常见缺口）
    source_tables = spec.get("sourceTables") or []
    key_mappings = spec.get("keyMappings") or []
    if len(source_tables) > 1 and not key_mappings:
        ok = False
        plan["gaps"] = list(plan.get("gaps", [])) + [
            "多张来源表但缺少 keyMappings 连接键，请补充表间关联后再确认"]
    checks = []
    tables = []
    for st in source_tables:
        t = st.get("tableName")
        if t:
            tables.append(t)
    for pa in (spec.get("preAggregations") or {}).values():
        if isinstance(pa, dict) and pa.get("table"):
            tables.append(pa["table"])
    for t in dict.fromkeys(tables):
        quoted = _quote_table(t, quote_style)
        try:
            res = execute_sql_on_database(
                database_id, f"SELECT * FROM {quoted} LIMIT 1")
            if res.get("success"):
                checks.append({"table": t, "ok": True, "message": "可读，列存在"})
            else:
                checks.append({
                    "table": t, "ok": False,
                    "message": str(res.get("message", "读取失败"))[:160]})
        except Exception as e:
            checks.append({"table": t, "ok": False, "message": str(e)[:160]})

    return {
        "ok": ok and all(c["ok"] for c in checks),
        "sql": plan.get("sql", "") if ok else "",
        "errors": plan.get("errors", []),
        "gaps": plan.get("gaps", []),
        "checks": checks,
    }
