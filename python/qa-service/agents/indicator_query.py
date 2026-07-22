"""指标查询流水线 — 模块化节点架构。

架构
────────────
本模块将指标分析流水线拆分为独立的节点函数，每个节点负责一个阶段。
编排器 `run_indicator_query` 按顺序依次调用它们，使流程易于阅读、测试和扩展。

节点遵循相同的协议：
* 向 UI 产出 ``{"type": "step", ...}`` 事件。
* 在最后产出 ``{"_return": (data, ...)}``，以便编排器获取返回值。
"""
import asyncio
import logging
import os
import re

from .state import EvaluationState
from .tools import (
    fetch_database_tables, fetch_datasets_for_database,
    fetch_indicators_for_datasets, fetch_table_structure,
    _fetch_dataset_structure_inner, execute_sql_on_database,
)
from .text_to_sql import run_text_to_sql, _validate_sql
from .analyst import run_analyst

logger = logging.getLogger(__name__)

# ── 共享日志文件（与 text_to_sql 写入同一文件） ──
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(_log_dir, exist_ok=True)
_ind_query_log_path = os.path.join(_log_dir, "sql_gen.log")
_ind_query_handler = logging.FileHandler(_ind_query_log_path, encoding="utf-8", mode="a")
_ind_query_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_ind_query_handler.setLevel(logging.DEBUG)
logger.addHandler(_ind_query_handler)
_DB_TIMEOUT = 8


# =========================================================================
# 共享辅助函数
# =========================================================================

def _pick_relevant_tables(all_tables, analysis_plan, question, max_tables=5):
    """基于启发式关键词打分的表选择器。"""
    import re as _re
    if not all_tables:
        return []
    if len(all_tables) <= max_tables:
        return all_tables

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

    search_text = f"{question} {analysis_plan}".lower()
    for cn, en_list in _CN_EN_MAP.items():
        if cn in search_text:
            for en in en_list:
                for t in all_tables:
                    if en in t.lower():
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


def _build_step(step_num, description, status='pending', detail='',
                thinking='', progress=0):
    return dict(step=step_num, description=description, status=status,
                detail=detail, thinking=thinking, progress=progress)


# =========================================================================
# 步骤编号常量
# =========================================================================

class Step:
    """指标分析流水线的集中式步骤编号定义。"""
    DATA_EXPLORE      = 2
    CHECK_DATASETS    = 3
    TABLE_SELECT      = 4
    SQL_GENERATE      = 5
    SQL_EXECUTE       = 6
    RESULT_PREVIEW    = 7
    ANALYST           = 8
    SQL_GEN_THRESHOLD = 5


# =========================================================================
# 阶段 1 – 数据探查（步骤 2）
# =========================================================================

async def data_explore_node(database_id):
    """从目标数据库获取表列表。"""
    yield {"type": "step", "step": _build_step(
        Step.DATA_EXPLORE, "Data Explore", "in_progress",
        detail="Fetching table list...", progress=50)}

    all_tables = []
    db_connected = False
    try:
        loop = asyncio.get_event_loop()
        all_tables = await asyncio.wait_for(
            loop.run_in_executor(None, fetch_database_tables, database_id),
            timeout=_DB_TIMEOUT)
        db_connected = bool(all_tables)
    except asyncio.TimeoutError:
        logger.warning("获取表列表超时")
    except Exception as e:
        logger.warning(f"获取表列表失败: {e}")

    yield {"type": "step", "step": _build_step(
        Step.DATA_EXPLORE, "Data Explore", "completed",
        detail=f"找到 {len(all_tables)} 张数据表",
        thinking="数据库可用表清单：\n" +
                 "\n".join(f"  • {t}" for t in all_tables[:20])
                 + ("\n  ..." if len(all_tables) > 20 else ""),
        progress=100)}
    yield {"_return": (all_tables, db_connected)}


# =========================================================================
# 阶段 2 – 数据集与指标（步骤 3）
# =========================================================================

def dataset_indicator_node(database_id, indicator_defs):
    """获取数据集和管理端指标；与调用方提供的列表合并。"""
    yield {"type": "step", "step": _build_step(
        Step.CHECK_DATASETS, "Check Datasets & Indicators", "in_progress",
        detail="获取关联数据集与指标配置...", progress=50)}

    datasets_found = []
    admin_indicators = []
    try:
        datasets_found = fetch_datasets_for_database(database_id)
    except Exception as e:
        logger.warning(f"获取数据集失败: {e}")
    try:
        ds_ids = [ds.get("id") for ds in datasets_found]
        admin_indicators = fetch_indicators_for_datasets(ds_ids)
    except Exception as e:
        logger.warning(f"获取指标失败: {e}")

    merged = list(indicator_defs or [])
    existing_names = {ind.get("name", "") for ind in merged}
    for ai in (admin_indicators or []):
        if ai.get("name") not in existing_names:
            merged.append(ai)
            existing_names.add(ai.get("name", ""))

    yield {"type": "step", "step": _build_step(
        Step.CHECK_DATASETS, "Check Datasets & Indicators", "completed",
        detail=f"数据集: {len(datasets_found)} | 指标体系: {len(merged)} 个",
        thinking="指标体系明细：\n" + "\n".join(
            f"  [{ind.get('type', '?')}] {ind.get('name', '?')}"
            + (f" — {ind.get('formula', '')}" if ind.get('formula') else "")
            for ind in merged[:15]
        ) + ("\n  ..." if len(merged) > 15 else ""),
        progress=100)}
    yield {"_return": (datasets_found, merged)}


# =========================================================================
# 阶段 3 – 表选择与结构读取（步骤 4）
# =========================================================================

async def table_select_node(all_tables, datasets_found, analysis_plan, question,
                            database_id, db_connected):
    """选择相关表，然后并行读取表结构。"""
    yield {"type": "step", "step": _build_step(
        Step.TABLE_SELECT, "Select Tables", "in_progress",
        detail="Selecting relevant tables for indicators...", progress=30)}

    # 构建数据集 → 表名查找映射
    dataset_table_map = {}
    for ds in datasets_found:
        tn = ds.get("tableName", "")
        if tn:
            dataset_table_map[tn] = ds

    relevant = _pick_relevant_tables(
        all_tables, analysis_plan, question, max_tables=8)
    for t in list(all_tables):
        if t in dataset_table_map and t not in relevant:
            if len(relevant) < 6:
                relevant.append(t)

    n = len(relevant)
    logger.info(f"[table_select] 从{len(all_tables)}张表中选出了{n}张: {relevant}")
    yield {"type": "step", "step": _build_step(
        Step.TABLE_SELECT, "Select Tables", "in_progress",
        detail=f"Selected {n} tables, reading schemas in parallel...",
        progress=60)}

    if n == 0:
        yield {"type": "step", "step": _build_step(
            Step.TABLE_SELECT, "Select Tables", "completed",
            detail="No tables to read", progress=100)}
        yield {"_return": []}
        return

    loop = asyncio.get_event_loop()

    async def _read_one(table_name):
        ds = dataset_table_map.get(table_name)
        source_tag = "dataset" if ds else ("live" if db_connected else "skip")
        try:
            if ds:
                s_ = await loop.run_in_executor(
                    None, _fetch_dataset_structure_inner, ds.get("id"))
                s_["datasetName"] = ds.get("name", "")
                s_["description"] = ds.get("description", "")
            elif db_connected:
                s_ = await loop.run_in_executor(
                    None, fetch_table_structure, database_id, table_name)
            else:
                return (table_name, None, source_tag, 0, None)
            cols = s_.get("columns", [])
            return (table_name, s_, source_tag, len(cols), None)
        except Exception as e:
            return (table_name, None, source_tag, 0, str(e)[:60])

    tasks = [_read_one(t) for t in relevant]
    schemas = []
    completed = 0

    for coro in asyncio.as_completed(tasks):
        table_name, s_, source_tag, col_count, error = await coro
        completed += 1
        if error:
            yield {"type": "step", "step": _build_step(
                Step.TABLE_SELECT, "Select Tables", "in_progress",
                detail=f"[{table_name}] 读取失败 ({completed}/{n}): {error}",
                progress=60 + int(30 * completed / n))}
        elif s_ is not None:
            schemas.append(s_)
            yield {"type": "step", "step": _build_step(
                Step.TABLE_SELECT, "Select Tables", "in_progress",
                detail=(f"正在读取 [{table_name}] ({completed}/{n})"
                        f" — {col_count} 列 ({source_tag})"),
                progress=60 + int(30 * completed / n))}

    yield {"type": "step", "step": _build_step(
        Step.TABLE_SELECT, "Select Tables", "completed",
        detail=f"已读取 {len(schemas)}/{n} 张表的结构信息",
        thinking="表结构摘要：\n" + "\n".join(
            f"  {s['tableName']}: {len(s.get('columns', []))} 列"
            + (f" ({s.get('description', '')})" if s.get('description') else "")
            for s in schemas
        ),
        progress=100)}
    yield {"_return": schemas}


# =========================================================================
# 阶段 3.5 – 字段提示（纯数据转换）
# =========================================================================

def build_field_hints(schemas, merged_indicators):
    """为每个指标附加列映射提示，以便生成更准确的 SQL 提示词。"""
    col_index = {}
    for s in schemas:
        tname = s.get("tableName", "")
        for col in s.get("columns", []):
            cname = col.get("columnName", "")
            comment = (col.get("comment", "")
                       or col.get("businessMeaning", "") or "")
            keywords = set(cname.lower().replace("_", " ").split())
            if comment:
                keywords.update(comment.lower().split())
            for kw in keywords:
                kw = kw.strip(",，。.!！?？()（）:：")
                if len(kw) >= 2:
                    col_index.setdefault(kw, []).append(
                        (tname, cname, comment[:60]))

    # 中英对照映射：中文公式词 → 可能的英文列名关键词
    _CN2EN_MAP = {
        # combat_result 相关
        "命中次数": ["hit", "hit_count", "hits"],
        "射击次数": ["fire", "fire_count", "shot", "shots", "fire_times"],
        "摧毁数": ["destroy", "destroy_count", "killed"],
        "命中数": ["hit", "hit_count"],
        "突防次数": ["penetration", "penetration_count", "breach"],
        "总突防次数": ["penetration", "penetration_count", "total_penetration"],
        "成功突防次数": ["penetration", "penetration_success"],
        # mission_record 相关
        "总任务数": ["total_mission", "mission_count", "total_task"],
        "完成任务数": ["completed_mission", "mission_completed", "task_done"],
        "按时完成任务数": ["ontime_mission", "ontime_complete", "timely_completed"],
        "逾期任务数": ["overdue", "overdue_mission", "delayed"],
        "任务总耗时": ["duration", "total_duration", "elapsed"],
        "计划耗时": ["planned_duration", "planned_time", "plan_duration"],
        # resource_consume 相关
        "资源消耗量": ["consumed", "consumption", "resource_used"],
        "资源总量": ["total", "total_resource", "budget"],
        "实际消耗": ["consumed", "actual_consumption", "actual_used"],
        "补给量": ["supply", "resupply", "supplied"],
        # 通用
        "总数量": ["total", "total_count", "count"],
        "成功数": ["success", "success_count", "succeeded"],
        "失败数": ["fail", "failure", "fail_count", "failed"],
        "合格数": ["qualified", "pass", "pass_count", "eligible"],
        "返工数": ["rework", "rework_count"],
        "用时": ["duration", "time", "elapsed", "cost_time"],
        "得分": ["score", "grade", "mark"],
    }

    enhanced = []
    for ind in merged_indicators:
        e = dict(ind)
        formula = ind.get("formula", "")
        hints = []
        formula_words = re.findall(r'[一-龥a-zA-Z_]{2,}', formula)
        for fw in formula_words[:10]:
            # 1) 直接匹配列索引
            matches = col_index.get(fw.lower(), [])
            # 2) 中英映射兜底
            if not matches:
                en_keywords = _CN2EN_MAP.get(fw, [])
                for ekw in en_keywords:
                    matches = col_index.get(ekw.lower(), [])
                    if matches:
                        break
            # 3) 部分匹配：英文关键词模糊匹配列名
            if not matches:
                en_keywords = _CN2EN_MAP.get(fw, [])
                for ekw in en_keywords:
                    for idx_key, idx_vals in col_index.items():
                        if ekw in idx_key or idx_key in ekw:
                            matches.extend(idx_vals)
                    if matches:
                        break
            if matches:
                for tname, cname, ccomment in matches[:2]:
                    hint = f"'{fw}' -> {tname}.{cname}"
                    if ccomment:
                        hint += f" ({ccomment})"
                    hints.append(hint)
        if hints:
            e["_field_hints"] = "; ".join(hints[:5])
        enhanced.append(e)
    return enhanced


# =========================================================================
# 阶段 4 – SQL 生成（步骤 5）
# =========================================================================

async def sql_generate_node(schemas, enhanced_indicators, analysis_plan,
                            question, database_id, llm_call_fn):
    """步骤 5 — 委托给 text_to_sql，转发清晰的摘要。"""
    yield {"type": "step", "step": _build_step(
        Step.SQL_GENERATE, "Generate SQL", "in_progress",
        detail=f"Generating SQL from {len(schemas)} table schemas...",
        progress=50)}

    es = EvaluationState(question=question, database_id=database_id)
    es.table_schemas = schemas
    es.indicator_defs = enhanced_indicators
    es.analysis_plan = analysis_plan or ""
    es.entities = {"query_type": "data_query", "filters": "",
                   "need_conclusion": True}
    es.steps = []

    # 记录送入 SQL 生成的上下文
    ind_names = [ind.get("name", "?") for ind in (enhanced_indicators or [])]
    logger.info("=" * 60)
    logger.info(f"[sql_generate_node] question={question[:100]}")
    logger.info(f"[sql_generate_node] schemas={len(schemas)}张表, indicators={len(enhanced_indicators)}个")
    logger.info(f"[sql_generate_node] 表名: {[s.get('tableName','?') for s in schemas]}")
    logger.info(f"[sql_generate_node] 指标: {ind_names}")
    logger.info(f"[sql_generate_node] analysis_plan(前300): {analysis_plan[:300] if analysis_plan else '(空)'}")

    try:
        es = await run_text_to_sql(es, llm_call_fn)
    except Exception as e:
        es.execution_error = str(e)[:200]
        logger.error(f"Text-to-SQL 失败: {e}")
        yield {"type": "step", "step": _build_step(
            Step.SQL_GENERATE, "Generate SQL", "error",
            detail=f"SQL 生成失败: {str(e)[:100]}", progress=100)}
        yield {"_return": (es, False)}
        return

    # 多条语句防护
    if es.sql_valid and es.generated_sql:
        raw = es.generated_sql
        if ";" in raw:
            parts = raw.split(";")
            first = ""
            for p in parts:
                p = p.strip()
                if p.upper().startswith("SELECT") or \
                   p.upper().startswith("WITH"):
                    first = p
                    break
            if first:
                logger.info(
                    f"检测到多条 SQL 语句，"
                    f"取第一条 SELECT（{len(first)} 字符）")
                es.generated_sql = first
                ok, err = _validate_sql(first)
                es.sql_valid = ok
                if not ok:
                    es.execution_error = err

    if not es.sql_valid or not es.generated_sql:
        validation_error = es.execution_error or "未生成有效 SQL"
        es.execution_error = validation_error
        yield {"type": "step", "step": _build_step(
            Step.SQL_GENERATE, "Generate SQL", "error",
            detail=validation_error[:120], progress=100)}
        yield {"_return": (es, False)}
        return

    # 将 text_to_sql 内部的步骤合并为一条简洁的摘要
    sql_gen_steps = [s for s in (es.steps or [])
                     if s.get("description", "").startswith("生成SQL")]
    was_retried = any("第" in s.get("description", "")
                      for s in sql_gen_steps)
    last = sql_gen_steps[-1] if sql_gen_steps else None
    status = last.get("status", "pending") if last else "pending"

    gen_detail = f"SQL 生成成功 ({len(es.generated_sql)} 字符)"
    if was_retried:
        gen_detail += "（内部重试后成功）"
    yield {"type": "step", "step": _build_step(
        Step.SQL_GENERATE, "Generate SQL",
        status if status != "pending" else "completed",
        detail=gen_detail,
        thinking=f"[生成的SQL]\n{es.generated_sql.strip()}",
        progress=100)}
    yield {"_return": (es, True)}


# =========================================================================
# 阶段 5 – SQL 执行（步骤 6 — 包含自动修正与重试）
# =========================================================================

async def sql_execute_node(database_id, es, llm_call_fn):
    """步骤 6 — 执行 SQL，失败时自动修正并重试。"""
    yield {"type": "step", "step": _build_step(
        Step.SQL_EXECUTE, "Execute SQL", "in_progress",
        detail="Executing SQL on target database...",
        thinking=f"[SQL]\n{es.generated_sql[:600]}",
        progress=50)}

    result = execute_sql_on_database(database_id, es.generated_sql)

    # 成功路径
    if result.get("success"):
        rows = result.get("rows",
                          result.get("data",
                                     result.get("results", [])))
        yield {"type": "step", "step": _build_step(
            Step.SQL_EXECUTE, "Execute SQL", "completed",
            detail=f"查询成功: {len(rows)} 行返回",
            progress=100)}
        yield {"_return": (rows, True)}
        return

    # 失败 → 自动修正并重试
    err = result.get("message", "执行失败")
    logger.warning(f"SQL 执行失败: {err[:100]}")

    yield {"type": "step", "step": _build_step(
        Step.SQL_EXECUTE, "Execute SQL", "in_progress",
        detail=f"SQL 执行失败: {err[:80]}，正在修正重试...",
        progress=50)}

    es.previous_error = err
    es.steps = [s for s in (es.steps or [])
                if s.get("step", 0) < Step.SQL_GEN_THRESHOLD]

    try:
        es = await run_text_to_sql(es, llm_call_fn)
    except Exception as e2:
        es.execution_error = f"SQL 修正失败: {str(e2)[:200]}"
        logger.error(f"Text-to-SQL 重试失败: {e2}")
        yield {"type": "step", "step": _build_step(
            Step.SQL_EXECUTE, "Execute SQL", "error",
            detail=f"SQL 修正失败: {str(e2)[:100]}", progress=100)}
        yield {"_return": ([], False)}
        return

    if not es.sql_valid or not es.generated_sql:
        es.execution_error = "修正后仍无法生成有效 SQL"
        yield {"type": "step", "step": _build_step(
            Step.SQL_EXECUTE, "Execute SQL", "error",
            detail=es.execution_error, progress=100)}
        yield {"_return": ([], False)}
        return

    # 重新执行修正后的 SQL
    yield {"type": "step", "step": _build_step(
        Step.SQL_EXECUTE, "Execute SQL", "in_progress",
        detail="Re-executing corrected SQL...",
        thinking=f"[修正后的SQL]\n{es.generated_sql[:600]}",
        progress=60)}

    result = execute_sql_on_database(database_id, es.generated_sql)

    if not result.get("success"):
        err2 = result.get("message", "Execution failed")
        es.execution_error = f"修正后执行仍失败: {err2[:200]}"
        yield {"type": "step", "step": _build_step(
            Step.SQL_EXECUTE, "Execute SQL", "error",
            detail=f"修正后执行仍失败: {err2[:100]}", progress=100)}
        yield {"_return": ([], False)}
        return

    rows = result.get("rows",
                      result.get("data",
                                 result.get("results", [])))
    yield {"type": "step", "step": _build_step(
        Step.SQL_EXECUTE, "Execute SQL", "completed",
        detail=f"查询成功: {len(rows)} 行返回（修正后重试成功）",
        progress=100)}
    yield {"_return": (rows, True)}


# =========================================================================
# 阶段 6 – 结果预览（步骤 7）
# =========================================================================

def result_preview_node(raw_results):
    """步骤 7 — 渲染 5 行的表格预览。"""
    if not raw_results or not isinstance(raw_results[0], dict):
        return
    cols = list(raw_results[0].keys())
    preview = (
        f"前 {min(5, len(raw_results))} 行数据预览：\n"
        + " | ".join(cols[:10]) + "\n"
        + "-" * 60 + "\n"
    )
    for r in raw_results[:5]:
        preview += " | ".join(str(r.get(c, ""))
                              for c in cols[:10]) + "\n"
    yield {"type": "step", "step": _build_step(
        Step.RESULT_PREVIEW, "Result Preview", "completed",
        detail=f"列: {', '.join(cols[:10])} | 共 {len(raw_results)} 行",
        thinking=preview,
        progress=100)}


# =========================================================================
# 阶段 7 – 生成分析（步骤 8）
# =========================================================================

async def analyst_node(es, raw_results, stream_llm_gen):
    """步骤 8 — 委托给 run_analyst，以流式文本事件实时输出 token。

    使用队列桥接模式：在异步后台任务中调用 LLM，将 token 推入队列；
    主循环消费队列并产出 ``{"type": "text", ...}`` 事件，
    前端即可像正常 AI 响应一样逐词渲染分析结果。
    """
    yield {"type": "step", "step": _build_step(
        Step.ANALYST, "Generate Analysis", "in_progress",
        detail="正在基于数据调用大模型生成建议...", progress=50)}

    es.raw_results = raw_results
    # 保留上游已设置的 execution_error（SQL 生成/执行失败时，analyst 使用无数据模式）
    if not raw_results:
        pass
    else:
        es.execution_error = None

    token_queue = asyncio.Queue()
    accumulated_text = ""
    exception_ref = None

    async def bridge_llm_fn(system_prompt, user_message):
        """桥接函数：消费实时 LLM 流，将 token 推入队列并返回完整文本。"""
        nonlocal accumulated_text, exception_ref
        try:
            async for chunk in stream_llm_gen(system_prompt, user_message):
                accumulated_text += chunk
                await token_queue.put(chunk)
        except Exception as e:
            exception_ref = e
            raise
        finally:
            await token_queue.put(None)
        return accumulated_text

    # 在后台启动分析师任务
    task = asyncio.create_task(run_analyst(es, bridge_llm_fn))

    # 从队列消费 token，产出文本事件
    while True:
        chunk = await token_queue.get()
        if chunk is None:
            break
        yield {"type": "text", "content": chunk}

    # 等待分析师任务完成
    try:
        es = await task
    except Exception as e:
        logger.error(f"分析师任务失败: {e}")
        es.final_answer = accumulated_text or f"分析失败: {str(e)[:200]}"

    # 从 run_analyst 的内部子步骤中提取思考过程
    analyst_thinking = ""
    for s in (es.steps or []):
        if s.get("description", "").startswith("生成分析"):
            analyst_thinking = s.get("thinking", "")
            break

    yield {"type": "step", "step": _build_step(
        Step.ANALYST, "Generate Analysis", "completed",
        detail=f"分析完成 ({len(es.final_answer or '')} 字符)",
        thinking=analyst_thinking,
        progress=100)}
    yield {"_return": es.final_answer}


# =========================================================================
# 概念类指标检查 — 概念类指标不走 SQL 管线
# =========================================================================

def _check_needs_sql(indicator_defs):
    """检查指标是否需要 SQL 查询，还是可以直接从概念层面回答。
    
    某些指标（如纯定义、描述性内容）无需数据库查询。
    返回 False 以跳过整个 SQL 流水线。
    """
    if not indicator_defs:
        return True
    all_conceptual = all(
        ind.get("type") == "conceptual" for ind in indicator_defs
    )
    return not all_conceptual


async def _concept_answer_flow(question, indicator_defs, llm_call_fn,
                                stream_llm_gen=None):
    """直接通过 LLM 处理纯概念类指标，无需 SQL。"""
    indicator_names = "、".join(
        ind.get("name", "") for ind in (indicator_defs or [])
    )
    yield {"type": "step", "step": _build_step(
        Step.ANALYST, "Generate Analysis", "in_progress",
        detail=f"概念类指标（{indicator_names}），无需查询数据，直接分析...",
        progress=50)}

    prompt = (
        f"用户问题：{question}\n\n"
        f"涉及的概念指标：{indicator_names}\n"
        f"指标定义明细：\n" +
        "\n".join(
            f"- {ind.get('name', '')}: {ind.get('formula', '') or ind.get('description', '')}"
            for ind in (indicator_defs or [])
        ) +
        "\n\n请基于以上指标定义，给出 2-3 条定性分析建议。不要编造数据。"
    )

    response = await llm_call_fn(
        "你是专业评估分析专家。请基于用户问题和指标定义进行分析。",
        prompt
    )

    yield {"type": "text", "content": response}
    yield {"type": "step", "step": _build_step(
        Step.ANALYST, "Generate Analysis", "completed",
        detail=f"分析完成（概念类指标）", progress=100)}

    yield {
        "type": "result",
        "final_answer": response or "分析完成",
        "generatedSql": "",
        "rawResults": [],
        "totalRows": 0,
        "query_type": "data_query",
        "database_used": "",
    }


# =========================================================================
# 编排器（公共 API）
# =========================================================================

async def run_indicator_query(question, database_id, database_name,
                              indicator_defs, analysis_plan,
                              llm_call_fn, stream_llm_gen=None):
    """编排完整的指标分析流水线。

    按顺序调用各个阶段节点。节点产出的事件直接转发给调用方；
    ``_return`` 哨兵值在内部消费，用于在节点之间传递数据。

    Args:
        stream_llm_gen: 可选的异步生成器，用于在分析师阶段进行实时 token 流式输出。
    """

    # ── SQL 必要性判断（概念类指标不走 SQL 管线）─────────────────
    if not _check_needs_sql(indicator_defs):
        logger.info(f"检测到概念类指标，跳过 SQL 管线。指标数={len(indicator_defs)}")
        async for ev in _concept_answer_flow(question, indicator_defs,
                                              llm_call_fn, stream_llm_gen):
            yield ev
        return

    # ── 步骤 2: 数据探查 ───────────────────────────────────────────
    all_tables = db_connected = None
    async for ev in data_explore_node(database_id):
        if "_return" in ev:
            all_tables, db_connected = ev["_return"]
        else:
            yield ev

    # ── 步骤 3: 检查数据集与指标 ────────────────────────────────────
    datasets = merged = None
    for ev in dataset_indicator_node(database_id, indicator_defs):
        if "_return" in ev:
            datasets, merged = ev["_return"]
        else:
            yield ev

    # ── 步骤 4: 表选择与结构读取 ─────────────────────────────────────
    schemas = None
    async for ev in table_select_node(all_tables, datasets, analysis_plan,
                                      question, database_id, db_connected):
        if "_return" in ev:
            schemas = ev["_return"]
        else:
            yield ev

    # ── 纯数据转换：字段提示 ────────────────────────────────────────────
    enhanced_indicators = build_field_hints(schemas, merged)

    # ── 步骤 5: 生成 SQL ───────────────────────────────────────────
    es = gen_ok = None
    async for ev in sql_generate_node(schemas, enhanced_indicators,
                                      analysis_plan, question,
                                      database_id, llm_call_fn):
        if "_return" in ev:
            es, gen_ok = ev["_return"]
        else:
            yield ev

    # ── 步骤 6: 执行 SQL（仅当生成成功时） ─────────────────────────────
    raw_results = []
    exec_ok = False
    if gen_ok:
        async for ev in sql_execute_node(database_id, es, llm_call_fn):
            if "_return" in ev:
                raw_results, exec_ok = ev["_return"]
            else:
                yield ev

    # ── 步骤 7: 结果预览（仅当执行成功时） ───────────────────────────
    if exec_ok:
        for ev in result_preview_node(raw_results):
            yield ev

    # ── 步骤 8: 生成分析（即使失败也始终执行） ────────────────────────
    async for ev in analyst_node(es, raw_results, stream_llm_gen):
        if "_return" in ev:
            pass  # final_answer 已在 es 中
        else:
            yield ev

    # ── 最终结果 ───────────────────────────────────────────────────
    raw_preview = raw_results[:20] if raw_results else []
    yield {
        "type": "result",
        "final_answer": es.final_answer or "分析完成",
        "generatedSql": es.generated_sql or "",
        "rawResults": raw_preview,
        "totalRows": len(raw_results) if raw_results else 0,
        "query_type": "data_query",
        "database_used": database_id,
    }
