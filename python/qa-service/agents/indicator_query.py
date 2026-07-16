
"""Indicator Query Pipeline - reuses evaluation agents tools."""
import asyncio
import logging
from .state import EvaluationState
from .tools import (
    fetch_database_tables, fetch_datasets_for_database,
    fetch_indicators_for_datasets, fetch_table_structure,
    _fetch_dataset_structure_inner, execute_sql_on_database,
)
from .text_to_sql import run_text_to_sql
from .analyst import run_analyst

logger = logging.getLogger(__name__)
_DB_TIMEOUT = 8

def _pick_relevant_tables(all_tables, analysis_plan, question, max_tables=5):
    import re as _re
    if not all_tables:
        return []
    if len(all_tables) <= max_tables:
        return all_tables

    # 中文词 → 可能的英文字段/表名映射（帮助中文指标关键词匹配英文表名）
    _CN_EN_MAP = {
        "存活": ["survival", "surviving", "unit_survival"],
        "生存": ["survival", "surviving", "unit_survival"],
        "命中": ["hit", "combat_result"],
        "射击": ["shot", "combat_result"],
        "突防": ["penetration", "breach", "penetration_record"],
        "战损": ["loss", "combat_loss"],
        "损耗": ["loss", "combat_loss", "resource_consume"],
        "补给": ["resource", "consume", "supply", "resource_consume"],
        "维护": ["maintenance", "repair"],
        "防护": ["protection", "protection_capability"],
        "任务": ["mission", "mission_record"],
        "达成": ["mission", "success", "mission_record"],
        "时效": ["timing", "mission_timing"],
        "耗时": ["timing", "mission_timing"],
    }

    scores = {t: 0 for t in all_tables}
    plan_lower = (analysis_plan or '').lower()
    for t in all_tables:
        if t.lower() in plan_lower:
            scores[t] += 100

    # 合并 question + analysis_plan + indicator 关键词为一组搜索词
    search_text = f"{question} {analysis_plan}".lower()
    for cn, en_list in _CN_EN_MAP.items():
        if cn in search_text:
            for en in en_list:
                for t in all_tables:
                    t_lower = t.lower()
                    if en in t_lower:
                        scores[t] += 30

    for t in all_tables:
        keywords = set(t.lower().replace('_', ' ').split())
        base_name = t.lower()
        for prefix in ['ass_', 'test_', 'sys_', 'tbl_']:
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
                break
        for word in question.lower().split():
            word = word.strip(',.?!()')
            if len(word) >= 2 and (word in keywords or word in base_name):
                scores[t] += 20
        for word in plan_lower.split():
            word = word.strip(',.?!()')
            if len(word) >= 2 and (word in keywords or word in base_name):
                scores[t] += 10
    table_pattern = _re.findall(
        r'(?:table\s*|TABLE\s+)([a-zA-Z_][a-zA-Z0-9_]*)',
        analysis_plan or '', _re.IGNORECASE
    )
    for match in table_pattern:
        for t in all_tables:
            if t.lower() == match.lower():
                scores[t] += 200
    sorted_tables = sorted(scores.items(), key=lambda x: -x[1])
    top = [t for t, s in sorted_tables if s > 0]
    if not top:
        non_sys = [t for t in all_tables
                   if not t.startswith('ass_') and not t.startswith('sys_')]
        top = non_sys[:max_tables] if non_sys else all_tables[:max_tables]
    return top[:max_tables]

def _build_step(step_num, description, status='pending', detail='', thinking='', progress=0):
    return dict(step=step_num, description=description, status=status, detail=detail, thinking=thinking, progress=progress)


async def run_indicator_query(question, database_id, database_name,
                               indicator_defs, analysis_plan, llm_call_fn):
    """Run indicator query pipeline using existing evaluation tools."""
    # Step 1: data explore
    yield {"type": "step", "step": _build_step(
        2, "Data Explore", "in_progress", detail="Fetching table list...", progress=50)}
    all_tables = []
    db_connected = False
    try:
        loop = asyncio.get_event_loop()
        all_tables = await asyncio.wait_for(
            loop.run_in_executor(None, fetch_database_tables, database_id), timeout=_DB_TIMEOUT)
        db_connected = bool(all_tables)
    except asyncio.TimeoutError:
        logger.warning("Table list timeout")
    except Exception as e:
        logger.warning(f"Table list failed: {e}")
    yield {"type": "step", "step": _build_step(
        2, "Data Explore", "completed",
        detail=f"找到 {len(all_tables)} 张数据表",
        thinking=f"数据库可用表清单：\n" + "\n".join(f"  • {t}" for t in all_tables[:20])
                + ("\n  ..." if len(all_tables) > 20 else ""),
        progress=100)}

    # Step 2: dataset + indicator check
    yield {"type": "step", "step": _build_step(
        3, "Check Datasets & Indicators", "in_progress",
        detail="获取关联数据集与指标配置...", progress=50)}
    datasets_found = []
    admin_indicators = []
    try:
        datasets_found = fetch_datasets_for_database(database_id)
    except Exception as e:
        logger.warning(f"Dataset fetch failed: {e}")
    try:
        ds_ids = [ds.get("id") for ds in datasets_found]
        admin_indicators = fetch_indicators_for_datasets(ds_ids)
    except Exception as e:
        logger.warning(f"Indicator fetch failed: {e}")

    merged_indicators = list(indicator_defs or [])
    existing_names = {ind.get("name", "") for ind in merged_indicators}
    for ai in (admin_indicators or []):
        if ai.get("name") not in existing_names:
            merged_indicators.append(ai)
            existing_names.add(ai.get("name", ""))

    yield {"type": "step", "step": _build_step(
        3, "Check Datasets & Indicators", "completed",
        detail=f"数据集: {len(datasets_found)} | 指标体系: {len(merged_indicators)} 个",
        thinking="指标体系明细：\n" + "\n".join(
            f"  [{ind.get('type', '?')}] {ind.get('name', '?')}"
            + (f" — {ind.get('formula', '')}" if ind.get('formula') else "")
            for ind in merged_indicators[:15]
        ) + ("\n  ..." if len(merged_indicators) > 15 else ""),
        progress=100)}

    # Step 3: table select + structure read
    yield {"type": "step", "step": _build_step(
        4, "Select Tables", "in_progress",
        detail="Selecting relevant tables for indicators...", progress=50)}

    dataset_table_map = {}
    for ds in datasets_found:
        tn = ds.get("tableName", "")
        if tn:
            dataset_table_map[tn] = ds

    relevant = _pick_relevant_tables(all_tables, analysis_plan, question, max_tables=8)
    for t in list(all_tables):
        if t in dataset_table_map and t not in relevant:
            if len(relevant) < 6:
                relevant.append(t)

    yield {"type": "step", "step": _build_step(
        4, "Select Tables", "completed",
        detail=f"Selected {len(relevant)} tables: {', '.join(relevant)}",
        progress=60)}

    schemas = []
    for i, table_name in enumerate(relevant):
        ds = dataset_table_map.get(table_name)
        source_tag = "dataset" if ds else ("live" if db_connected else "skip")
        try:
            if ds:
                s_ = _fetch_dataset_structure_inner(ds.get("id"))
                s_["datasetName"] = ds.get("name", "")
                s_["description"] = ds.get("description", "")
            elif db_connected:
                s_ = fetch_table_structure(database_id, table_name)
            else:
                continue
            schemas.append(s_)
            cols = s_.get("columns", [])
            sub_step = 4.0 + (i + 1) * 0.1  # 4.1, 4.2, 4.3 ...
            yield {"type": "step", "step": _build_step(
                sub_step, f"读取表结构 ({i+1}/{len(relevant)})", "completed",
                detail=f"[{table_name}] {len(cols)} 列 ({source_tag})", progress=100)}
        except Exception as e:
            sub_step = 4.0 + (i + 1) * 0.1
            yield {"type": "step", "step": _build_step(
                sub_step, f"读取表结构 ({i+1}/{len(relevant)})", "error",
                detail=f"[{table_name}]: {str(e)[:80]}", progress=100)}
    yield {"type": "step", "step": _build_step(
        4.91, "读取表结构完成", "completed",
        detail=f"已读取 {len(schemas)}/{len(relevant)} 张表的结构信息",
        thinking="表结构摘要：\n" + "\n".join(
            f"  {s['tableName']}: {len(s.get('columns', []))} 列"
            + (f" ({s.get('description', '')})" if s.get('description') else "")
            for s in schemas
        ),
        progress=100)}

    # Step 4: SQL generation
    # ── 构建字段映射提示，帮助 LLM 将指标公式翻译到具体列 ──
    col_index = {}  # {keyword: [(table, column, comment)]}
    for s in schemas:
        tname = s.get("tableName", "")
        for col in s.get("columns", []):
            cname = col.get("columnName", "")
            comment = col.get("comment", "") or col.get("businessMeaning", "") or ""
            # 用列名和注释中的每个词作为索引关键词
            keywords = set(cname.lower().replace("_", " ").split())
            if comment:
                keywords.update(comment.lower().split())
            for kw in keywords:
                kw = kw.strip(",，。.!！?？()（）:：")
                if len(kw) >= 2:
                    col_index.setdefault(kw, []).append((tname, cname, comment[:60]))

    # 为每个指标补充字段映射提示
    enhanced_indicators = []
    for ind in merged_indicators:
        enhanced = dict(ind)
        formula = ind.get("formula", "")
        hints = []
        # 从公式中抽取关键词，在列索引中查找匹配
        import re as _re2
        formula_words = _re2.findall(r'[一-龥a-zA-Z_]{2,}', formula)
        for fw in formula_words[:10]:
            fw_lower = fw.lower()
            matches = col_index.get(fw_lower, [])
            if matches:
                for tname, cname, ccomment in matches[:2]:
                    hint = f"'{fw}' -> {tname}.{cname}"
                    if ccomment:
                        hint += f" ({ccomment})"
                    hints.append(hint)
        if hints:
            enhanced["_field_hints"] = "; ".join(hints[:5])
        enhanced_indicators.append(enhanced)

    es = EvaluationState(question=question, database_id=database_id)
    es.table_schemas = schemas
    es.indicator_defs = enhanced_indicators
    es.analysis_plan = analysis_plan or ""
    es.entities = {"query_type": "data_query", "filters": "", "need_conclusion": True}
    es.steps = []

    # ─── Step 4-5: SQL 生成 + 执行（带执行失败自动重试） ───
    MAX_EXECUTION_RETRIES = 1   # 执行失败最多重试 1 次（共 2 次执行机会）
    raw_results = []
    execution_error = ""
    last_generated_sql = ""

    for exec_attempt in range(MAX_EXECUTION_RETRIES + 1):  # 0 = initial, 1+ = retry
        is_retry = exec_attempt > 0
        step_label = f" (第{exec_attempt + 1}次)" if is_retry else ""

        # ── 重试时设置错误上下文 ──
        if is_retry and execution_error:
            es.previous_error = execution_error
            es.steps = [s for s in (es.steps or [])
                        if s.get("step", 0) != 5 and s.get("step", 0) != 5.1 and s.get("step", 0) != 6]
            logger.info(f"Execution retry {exec_attempt}: error={execution_error[:100]}")

        # ── SQL 生成 ──
        yield {"type": "step", "step": _build_step(
            5, f"Generate SQL{step_label}", "in_progress",
            detail=f"Generating SQL from {len(schemas)} table schemas..."
                  + (f" (修正上次错误)" if is_retry else ""),
            progress=50)}

        try:
            es = await run_text_to_sql(es, llm_call_fn)
        except Exception as e:
            logger.error(f"Text-to-SQL failed: {e}")
            yield {"type": "step", "step": _build_step(
                5, f"Generate SQL{step_label}", "error",
                detail=f"SQL generation failed: {str(e)[:100]}", progress=100)}
            if not is_retry and exec_attempt < MAX_EXECUTION_RETRIES:
                execution_error = f"SQL生成异常: {str(e)[:200]}"
                continue
            yield {"type": "result", "final_answer": f"SQL generation failed: {str(e)[:200]}"}
            return

        for s in es.steps:
            yield {"type": "step", "step": {
                "step": s.get("step", 0), "description": s.get("description", ""),
                "status": s.get("status", "pending"), "detail": s.get("detail", ""),
                "thinking": s.get("thinking", ""), "progress": s.get("progress", 0),
            }}

        # ── 多语句兜底：只取第一条 SELECT ──
        if es.sql_valid and es.generated_sql:
            raw_sql = es.generated_sql
            if ";" in raw_sql:
                parts = raw_sql.split(";")
                first_select = ""
                for part in parts:
                    part = part.strip()
                    if part.upper().startswith("SELECT") or part.upper().startswith("WITH"):
                        first_select = part
                        break
                if first_select:
                    logger.info(f"Multi-statement SQL detected, taking first SELECT ({len(first_select)} chars)")
                    es.generated_sql = first_select
                    is_valid, err = _validate_sql(first_select)
                    es.sql_valid = is_valid
                    if not is_valid:
                        es.execution_error = err

        if not es.sql_valid or not es.generated_sql:
            validation_error = es.execution_error or "No valid SQL generated"
            if exec_attempt < MAX_EXECUTION_RETRIES:
                execution_error = validation_error
                logger.warning(f"SQL validation failed (attempt {exec_attempt + 1}): {validation_error[:100]}")
                yield {"type": "step", "step": _build_step(
                    5, "Retry SQL", "in_progress",
                    detail=f"SQL校验失败，正在重试...", progress=20)}
                continue
            yield {"type": "result", "final_answer": validation_error}
            return

        last_generated_sql = es.generated_sql

        yield {"type": "step", "step": _build_step(
            5, f"Generate SQL{step_label}", "completed",
            detail=f"SQL 生成成功 ({len(last_generated_sql)} 字符)"
                   + ("（修正后重试成功）" if is_retry else ""),
            thinking=f"[生成的SQL]\n{last_generated_sql.strip()}",
            progress=100)}

        # ── SQL 执行 ──
        yield {"type": "step", "step": _build_step(
            6, f"Execute SQL{step_label}", "in_progress",
            detail="Executing SQL on target database...",
            thinking=f"[SQL]\n{es.generated_sql[:600]}",
            progress=50)}

        result = execute_sql_on_database(database_id, es.generated_sql)

        if result.get("success"):
            rows = result.get("rows", result.get("data", result.get("results", [])))
            raw_results = rows
            execution_error = ""
            yield {"type": "step", "step": _build_step(
                6, f"Execute SQL{step_label}", "completed",
                detail=f"Query OK: {len(rows)} rows returned"
                       + (f" (第{exec_attempt + 1}次重试成功)" if is_retry else ""),
                progress=100)}
            if rows and isinstance(rows[0], dict):
                cols = list(rows[0].keys())
                preview_text = "前 " + str(min(5, len(rows))) + " 行数据预览：\n"
                preview_text += " | ".join(cols[:10]) + "\n"
                preview_text += "-" * 60 + "\n"
                for r in rows[:5]:
                    preview_text += " | ".join(str(r.get(c, "")) for c in cols[:10]) + "\n"
                yield {"type": "step", "step": _build_step(
                    6.1, "Result Preview", "completed",
                    detail=f"列: {', '.join(cols[:10])} | 共 {len(rows)} 行",
                    thinking=preview_text,
                    progress=100)}
            break  # ── 执行成功，跳出重试循环 ──

        # ── 执行失败 ──
        execution_error = result.get("message", "Execution failed")
        logger.warning(f"SQL execution failed (attempt {exec_attempt + 1}): {execution_error[:100]}")
        yield {"type": "step", "step": _build_step(
            6, f"Execute SQL{step_label}", "error",
            detail=f"SQL execution failed: {execution_error[:100]}", progress=100)}

        if exec_attempt < MAX_EXECUTION_RETRIES:
            yield {"type": "step", "step": _build_step(
                5, "Retry SQL", "in_progress",
                detail=f"正在根据错误信息重试SQL生成...", progress=20)}

    # Step 7: analysis
    yield {"type": "step", "step": _build_step(
        7, "Generate Analysis", "in_progress",
        detail="Generating analysis from query results...", progress=50)}

    es.raw_results = raw_results
    es.execution_error = execution_error or None

    try:
        es = await run_analyst(es, llm_call_fn)
    except Exception as e:
        logger.error(f"Analyst failed: {e}")
        es.final_answer = f"Analysis failed: {str(e)[:200]}"

    for s in es.steps:
        yield {"type": "step", "step": {
            "step": s.get("step", 0), "description": s.get("description", ""),
            "status": s.get("status", "pending"), "detail": s.get("detail", ""),
            "thinking": s.get("thinking", ""), "progress": s.get("progress", 0),
        }}

    yield {"type": "step", "step": _build_step(
        7, "Generate Analysis", "completed",
        detail=f"分析完成 ({len(es.final_answer or '')} 字符)",
        progress=100)}

    # Final result
    raw_preview = raw_results[:20] if raw_results else []
    yield {
        "type": "result",
        "final_answer": es.final_answer or "Analysis complete",
        "generatedSql": es.generated_sql,
        "rawResults": raw_preview,
        "totalRows": len(raw_results),
        "query_type": "data_query",
        "database_used": database_id,
    }