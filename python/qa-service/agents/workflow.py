"""
评估工作流引擎
编排多智能体协作：
  步骤1: 分析问题意图（LLM）
  步骤2: 数据源探查 → 发现数据库所有表
  步骤3: 检查数据集管理 & 指标管理 → 辅助选表
  步骤4: 结合数据集/指标选表 → 读取表结构
  步骤5: 生成SQL（LLM）
  步骤6: 执行SQL → 获取查询结果
  步骤7: 基于数据生成2-3条建议（LLM）
"""
import asyncio
import concurrent.futures
import json
import logging
import re
from .state import EvaluationState
from .orchestrator import build_orchestrator_prompt, apply_orchestrator_result
from .text_to_sql import run_text_to_sql
from .analyst import run_analyst, run_simple_analysis
from .tools import execute_sql_on_database

logger = logging.getLogger("evaluation.workflow")

_YIELD_DELAY = 0.25
_DB_TIMEOUT = 8  # 数据库连接超时（秒）


def _step_event(step_num, description, status, detail="", thinking="", progress=None):
    if progress is None:
        progress = 100 if status == "completed" else (50 if status == "in_progress" else 0)
    return {
        "type": "step",
        "step": {
            "step": step_num, "description": description, "status": status,
            "detail": detail, "thinking": thinking, "progress": progress
        }
    }


def _pick_relevant_tables(all_tables, analysis_plan, question, max_tables=5):
    if not all_tables:
        return []
    if len(all_tables) <= max_tables:
        return all_tables
    scores = {t: 0 for t in all_tables}
    plan_lower = analysis_plan.lower()
    for t in all_tables:
        if t.lower() in plan_lower:
            scores[t] += 100
    for t in all_tables:
        keywords = set(t.lower().replace("_", " ").split())
        base_name = t.lower()
        for prefix in ["ass_", "test_", "sys_", "tbl_"]:
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
                break
        for word in question.lower().split():
            word = word.strip(",，。.!！?？()（）")
            if len(word) >= 2 and (word in keywords or word in base_name):
                scores[t] += 20
        for word in plan_lower.split():
            word = word.strip(",，。.!！?？()（）")
            if len(word) >= 2 and (word in keywords or word in base_name):
                scores[t] += 10
    table_pattern = re.findall(r'(?:表\s*|TABLE\s+)([a-zA-Z_][a-zA-Z0-9_]*)', analysis_plan, re.IGNORECASE)
    for match in table_pattern:
        for t in all_tables:
            if t.lower() == match.lower():
                scores[t] += 200
    sorted_tables = sorted(scores.items(), key=lambda x: -x[1])
    top = [t for t, s in sorted_tables if s > 0]
    if not top:
        non_sys = [t for t in all_tables if not t.startswith("ass_") and not t.startswith("sys_")]
        top = non_sys[:max_tables] if non_sys else all_tables[:max_tables]
    return top[:max_tables]


async def run_evaluation_workflow(
    question, llm_call_fn, session_id=None, database_id="", database_name="",
):
    state = EvaluationState(question=question, session_id=session_id,
                            database_id=database_id, database_name=database_name)
    try:
        # ═══════════════════════════════════════════
        # 步骤 1: 分析问题意图
        # ═══════════════════════════════════════════
        yield _step_event(1, "分析问题意图", "in_progress",
                          detail="正在调用大模型分析用户问题...")
        await asyncio.sleep(_YIELD_DELAY)

        sys_prompt, usr_prompt = build_orchestrator_prompt(state)
        yield _step_event(1.1, "大模型调用", "in_progress",
                          detail="正在将问题发送给大模型进行意图识别...",
                          thinking=f"用户问题: {question[:300]}")
        await asyncio.sleep(_YIELD_DELAY)

        try:
            response = await llm_call_fn(sys_prompt, usr_prompt)
        except Exception as e:
            yield _step_event(1.1, "大模型调用", "error",
                              detail=f"调用失败: {str(e)[:100]}")
            await asyncio.sleep(_YIELD_DELAY)
            state = await run_simple_analysis(state, llm_call_fn)
            yield _make_result(state, session_id)
            return

        yield _step_event(1.1, "大模型调用", "completed",
                          detail="大模型返回意图分析结果",
                          thinking=f"【模型原始响应】\n{response[:800]}")
        await asyncio.sleep(_YIELD_DELAY)

        state = apply_orchestrator_result(state, response)
        intent = state.intent or "综合评估"
        query_type = state.entities.get("query_type", "")
        need_conclusion = state.entities.get("need_conclusion", True)
        analysis_plan = state.analysis_plan or ""

        # 路由兜底：general_analysis 有数据源时降级为 data_query
        if state.database_id and query_type == "general_analysis":
            query_type = "data_query"
            state.entities["query_type"] = "data_query"
            yield _step_event(1.2, "路由修正", "completed",
                              detail="已选择数据源，自动切换为数据库查询模式")
            await asyncio.sleep(_YIELD_DELAY)

        # 二次校验：combat_effectiveness 需用户明确表达"整体评估整个推演/作战过程"
        if query_type == "combat_effectiveness":
            q = state.question
            overall_keywords = ["整个推演", "整个作战", "整体评估", "综合评估",
                                "全过程", "整体战", "整体作", "对整体", "整个方案"]
            if not any(kw in q for kw in overall_keywords):
                query_type = "data_query"
                state.entities["query_type"] = "data_query"
                yield _step_event(1.2, "路由修正", "completed",
                                  detail="未检测到整体评估表述，降级为基础查询")
                await asyncio.sleep(_YIELD_DELAY)

        yield _step_event(1, "分析问题意图", "completed",
                          detail=f"意图: {intent} | 查询模式: {query_type}",
                          thinking=(
                              f"【意图识别】\n问题类型: {intent}\n查询模式: {query_type}\n"
                              f"需要结论: {'是' if need_conclusion else '否'}\n"
                              f"分析维度: {', '.join(state.entities.get('dimensions', [])) or '未指定'}\n"
                              f"【分析计划】\n{analysis_plan[:300]}"
                          ))
        await asyncio.sleep(_YIELD_DELAY)

        # 无数据库 → 直接分析
        if not state.database_id:
            state = await run_simple_analysis(state, llm_call_fn)
            yield _make_result(state, session_id)
            return

        # 领域智能体路由
        if query_type == "combat_effectiveness":
            yield _step_event(1.3, "智能体选择", "completed",
                              detail="已选择「作战效能分析」智能体")
            await asyncio.sleep(_YIELD_DELAY)
            from .combat_effectiveness_agent import run_stream as combat_stream
            async for event in combat_stream(state.question, state.database_id, llm_call_fn, need_conclusion):
                if isinstance(event, dict):
                    yield event
                    await asyncio.sleep(_YIELD_DELAY)
            return

        if query_type == "air_superiority":
            yield _step_event(1.3, "智能体选择", "completed",
                              detail="已选择「制空权分析」智能体")
            await asyncio.sleep(_YIELD_DELAY)
            from .air_superiority_agent import run_stream as air_stream
            async for event in air_stream(state.question, state.database_id, llm_call_fn, need_conclusion):
                if isinstance(event, dict):
                    yield event
                    await asyncio.sleep(_YIELD_DELAY)
            return

        # ═══════════════════════════════════════════
        # 步骤 2: 数据源探查 — 获取数据库所有表
        # ═══════════════════════════════════════════
        from .tools import (fetch_database_tables, fetch_table_structure,
                           _fetch_dataset_structure_inner,
                           fetch_datasets_for_database, fetch_indicators_for_datasets)

        yield _step_event(2, "数据源探查", "in_progress",
                          detail=f"正在连接数据源查询数据表...")
        await asyncio.sleep(_YIELD_DELAY)

        all_tables = []
        db_connected = False
        try:
            loop = asyncio.get_event_loop()
            all_tables = await asyncio.wait_for(
                loop.run_in_executor(None, fetch_database_tables, state.database_id),
                timeout=_DB_TIMEOUT
            )
            db_connected = bool(all_tables)
        except asyncio.TimeoutError:
            logger.warning(f"获取表列表超时 ({_DB_TIMEOUT}s)")
        except Exception as e:
            logger.warning(f"获取表列表失败: {e}")

        table_list_str = "\n".join(f"  - {t}" for t in all_tables[:30])
        if len(all_tables) > 30:
            table_list_str += f"\n  ... 共 {len(all_tables)} 张表"

        yield _step_event(2, "数据源探查", "completed",
                          detail=f"发现 {len(all_tables)} 张数据表",
                          thinking=f"【数据库表列表】\n{table_list_str}")
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 3: 检查数据集和指标 — 用于辅助选表
        # ═══════════════════════════════════════════
        yield _step_event(3, "检查数据集和指标", "in_progress",
                          detail="正在从数据集管理和指标管理中查找相关信息...")
        await asyncio.sleep(_YIELD_DELAY)

        datasets_found = []
        indicators_found = []
        try:
            datasets_found = fetch_datasets_for_database(state.database_id)
        except Exception as e:
            logger.warning(f"获取数据集失败: {e}")

        if datasets_found:
            ds_names = ", ".join(ds.get("name", "") for ds in datasets_found[:5])
            ds_desc_lines = [f"  - {ds.get('name', '')} → 表 {ds.get('tableName', '')}"
                            + (f": {ds.get('description', '')[:80]}" if ds.get('description') else "")
                            for ds in datasets_found[:5]]
            yield _step_event(3.1, "查询数据集", "completed",
                              detail=f"发现 {len(datasets_found)} 个数据集: {ds_names}",
                              thinking="【数据集管理】\n" + "\n".join(ds_desc_lines))
        else:
            yield _step_event(3.1, "查询数据集", "completed",
                              detail="未找到关联数据集",
                              thinking="数据集管理中无与此数据源关联的数据集。将直接使用数据库表结构。")
        await asyncio.sleep(_YIELD_DELAY)

        try:
            ds_ids = [ds.get("id") for ds in datasets_found]
            indicators_found = fetch_indicators_for_datasets(ds_ids)
        except Exception as e:
            logger.warning(f"获取指标失败: {e}")

        if indicators_found:
            ind_names = ", ".join(ind.get("name", "") for ind in indicators_found[:5])
            ind_desc_lines = [f"  - {ind.get('name', '')}"
                            + (f" (公式: {ind.get('formula', '')})" if ind.get('formula') else "")
                            + (f" [说明: {ind.get('description', '')}]" if ind.get('description') else "")
                            for ind in indicators_found[:5]]
            yield _step_event(3.2, "查询指标", "completed",
                              detail=f"发现 {len(indicators_found)} 个指标: {ind_names}",
                              thinking="【指标管理】\n" + "\n".join(ind_desc_lines))
        else:
            yield _step_event(3.2, "查询指标", "completed",
                              detail="未找到关联指标",
                              thinking="指标管理中无关联指标。后续分析将不依赖预定义指标。")
        await asyncio.sleep(_YIELD_DELAY)

        # 构建数据集映射：表名 → 数据集（含字段标注）
        dataset_table_map = {}
        for ds in datasets_found:
            tn = ds.get("tableName", "")
            if tn:
                dataset_table_map[tn] = ds
        state.dataset_defs = datasets_found
        state.indicator_defs = indicators_found

        # 降级：数据库没连上但有数据集，用数据集的表名
        if not db_connected:
            ds_tables = list(dataset_table_map.keys())
            if ds_tables:
                all_tables = ds_tables
                yield _step_event(3, "检查数据集和指标", "completed",
                                  detail=f"数据库未连接，数据集提供 {len(all_tables)} 张表",
                                  thinking="【降级】数据库连接失败，使用数据集管理的表定义")
            else:
                yield _step_event(3, "检查数据集和指标", "error",
                                  detail="数据库未连接且无可用数据集",
                                  thinking="无法继续：需配置正确的数据库连接或创建数据集")
                yield _make_result(state, session_id)
                return
        else:
            yield _step_event(3, "检查数据集和指标", "completed",
                              detail=f"数据集 {len(datasets_found)} 个 | 指标 {len(indicators_found)} 个",
                              thinking="数据集和指标检查完毕，将用于辅助表选择和SQL生成")
        await asyncio.sleep(_YIELD_DELAY)

        state.database_tables = all_tables

        # ═══════════════════════════════════════════
        # 步骤 4: 结合数据集/指标选表 → 读取表结构
        # ═══════════════════════════════════════════
        yield _step_event(4, "选择数据表", "in_progress",
                          detail="正在根据分析计划和数据集信息筛选相关数据表...")
        await asyncio.sleep(_YIELD_DELAY)

        # 选表时考虑数据集关联
        relevant = _pick_relevant_tables(all_tables, state.analysis_plan, state.question)
        # 数据集关联的表优先保留
        for t in list(all_tables):
            if t in dataset_table_map and t not in relevant:
                if len(relevant) < 6:
                    relevant.append(t)
        skipped = [t for t in all_tables if t not in relevant]

        yield _step_event(4, "选择数据表", "completed",
                          detail=f"选定 {len(relevant)} 张表: {', '.join(relevant)}",
                          thinking=(
                              f"从 {len(all_tables)} 张表中筛选出 {len(relevant)} 张。\n"
                              f"✓ 选中:\n" + "\n".join(
                                  f"    - {t}" + (" ← 数据集「" + dataset_table_map[t].get('name', '') + "」" if t in dataset_table_map else "")
                                  for t in relevant
                              ) +
                              f"\n✗ 跳过: {', '.join(skipped)}"
                          ))
        await asyncio.sleep(_YIELD_DELAY)

        # 读取表结构
        yield _step_event(4.1, "读取表结构", "in_progress",
                          detail=f"正在读取 {len(relevant)} 张表的结构定义...")
        await asyncio.sleep(_YIELD_DELAY)

        schemas = []
        for i, table_name in enumerate(relevant):
            ds = dataset_table_map.get(table_name)
            source_tag = "数据集标注" if ds else ("实时读取" if db_connected else "跳过")
            yield _step_event(4.1, f"读取表结构 ({i+1}/{len(relevant)})", "in_progress",
                              detail=f"[{table_name}] 来源: {source_tag}...")
            await asyncio.sleep(_YIELD_DELAY)
            try:
                if ds:
                    s_ = _fetch_dataset_structure_inner(ds.get("id"))
                    s_["datasetName"] = ds.get("name", "")
                    s_["datasetId"] = ds.get("id", "")
                    s_["description"] = ds.get("description", "")
                elif db_connected:
                    s_ = fetch_table_structure(state.database_id, table_name)
                else:
                    continue
                schemas.append(s_)
                cols = s_.get("columns", [])
                col_lines = []
                for c in cols:
                    line = f"    {c['columnName']:20s} {c['dataType']:12s}"
                    if c.get('isPrimaryKey'):
                        line += " [PK]"
                    bm = c.get('businessMeaning', '')
                    if bm:
                        line += f"  → {bm}"
                    elif c.get('comment'):
                        line += f"  -- {c.get('comment', '')}"
                    col_lines.append(line)
                yield _step_event(4.1, f"读取表结构 ({i+1}/{len(relevant)})", "completed",
                                  detail=f"[{table_name}] {len(cols)} 列 ({source_tag})",
                                  thinking=f"【{table_name} | {source_tag}】\n" + "\n".join(col_lines))
            except Exception as e:
                yield _step_event(4.1, f"读取表结构 ({i+1}/{len(relevant)})", "error",
                                  detail=f"[{table_name}] 失败: {str(e)[:80]}")

        state.table_schemas = schemas

        col_summary = []
        for s_ in schemas:
            tn = s_.get("tableName", "?")
            cc = s_.get("count", 0)
            cols = ", ".join(c["columnName"] for c in s_.get("columns", [])[:8])
            col_summary.append(f"{tn}({cc}列): {cols}")
        yield _step_event(4.1, "读取表结构", "completed",
                          detail=f"已读取 {len(schemas)}/{len(relevant)} 张表",
                          thinking="\n".join(f"  - {p}" for p in col_summary))
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 5: 生成SQL（LLM）
        # ═══════════════════════════════════════════
        yield _step_event(5, "生成SQL", "in_progress",
                          detail=f"正在基于 {len(schemas)} 张表结构生成SQL查询...")
        await asyncio.sleep(_YIELD_DELAY)

        state = await run_text_to_sql(state, llm_call_fn)
        await asyncio.sleep(_YIELD_DELAY)

        # yield text-to-sql 内部产生的步骤
        for s in state.steps:
            sd = s if isinstance(s, dict) else s.__dict__
            sn = sd.get('step', 0)
            if sn in (5.1, 5.2):
                yield _step_event(sn, sd.get("description", ""), sd.get("status", ""),
                                  sd.get("detail", ""), sd.get("thinking", ""),
                                  sd.get("progress"))
                await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 6: 执行SQL → 获取查询结果
        # ═══════════════════════════════════════════
        if state.sql_valid and state.generated_sql:
            if not db_connected and not any(dataset_table_map.get(t) for t in relevant):
                yield _step_event(6, "执行SQL查询", "skipped",
                                  detail="数据库未连接，跳过SQL执行（可在数据集管理中配置关联数据库后重试）",
                                  thinking="当前处于数据集降级模式，缺少数据库连接无法执行SQL。生成的SQL代码仅供参考。")
            else:
                yield _step_event(6, "执行SQL查询", "in_progress",
                                  detail="正在连接数据库执行SQL查询...",
                                  thinking=f"【执行的SQL】\n{state.generated_sql[:600]}")
                await asyncio.sleep(_YIELD_DELAY)

                if state.database_id:
                    result = execute_sql_on_database(state.database_id, state.generated_sql)
                    if result.get("success"):
                        rows = result.get("rows", result.get("data", result.get("results", [])))
                        state.raw_results = rows
                        state.execution_error = None

                        preview_parts = []
                        if rows:
                            sample = rows[0]
                            if isinstance(sample, dict):
                                col_names = list(sample.keys())
                                preview_parts.append(f"字段: {', '.join(col_names[:15])}")
                            for i, row in enumerate(rows[:5]):
                                preview_parts.append(f"第{i+1}行: {json.dumps(row, ensure_ascii=False, default=str)[:200]}")
                            if len(rows) > 5:
                                preview_parts.append(f"... 共 {len(rows)} 行数据")

                        yield _step_event(6, "执行SQL查询", "completed",
                                          detail=f"查询成功，返回 {len(rows)} 行数据",
                                          thinking=f"【SQL执行结果】\n" + "\n".join(preview_parts) +
                                                   f"\n\n【执行的SQL】\n{state.generated_sql[:500]}")
                    else:
                        state.execution_error = result.get("message", "SQL执行失败")
                        yield _step_event(6, "执行SQL查询", "error",
                                          detail=f"SQL执行失败（数据库可能不可达）",
                                          thinking=f"错误详情: {state.execution_error}\n\n【生成的SQL供参考】\n{state.generated_sql[:500]}")
                else:
                    yield _step_event(6, "执行SQL查询", "skipped",
                                      detail="未选择数据源，跳过SQL执行")
        else:
            yield _step_event(6, "执行SQL查询", "skipped",
                              detail="无需执行SQL（SQL生成失败或非查询模式）")
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 6.5: 图表规划（Chart Agent）— 仅在需要图表且有数据时执行
        # ═══════════════════════════════════════════
        if state.need_chart and state.raw_results and db_connected:
            yield _step_event(6.5, "图表规划", "in_progress",
                              detail="正在根据查询结果规划图表...")
            await asyncio.sleep(_YIELD_DELAY)

            try:
                from .chart_agent import run_chart_agent

                # 提取列名：从 raw_results 第一行推断
                raw = state.raw_results
                if raw and isinstance(raw[0], dict):
                    columns = list(raw[0].keys())
                    chart_config = await run_chart_agent(
                        columns=columns,
                        sample_rows=raw[:5],
                        total_rows=len(raw),
                        question=state.question,
                        llm_call_fn=llm_call_fn,
                    )
                    state.chart_config = chart_config

                    viz = chart_config.get("vizType", "table")
                    if viz != "table":
                        yield _step_event(6.5, "图表规划", "completed",
                                          detail=f"已规划 {viz} 图表: {chart_config.get('chartTitle', '')}",
                                          thinking=f"【图表配置】\n{json.dumps(chart_config, ensure_ascii=False)}")
                    else:
                        yield _step_event(6.5, "图表规划", "skipped",
                                          detail="数据不适合图表展示，使用表格")
                else:
                    yield _step_event(6.5, "图表规划", "skipped",
                                      detail="数据格式不支持图表")
            except Exception as e:
                logger.warning(f"Chart agent failed: {e}")
                yield _step_event(6.5, "图表规划", "error",
                                  detail=f"图表规划失败，降级为表格: {str(e)[:80]}")

        # ═══════════════════════════════════════════
        # 步骤 7: 生成分析建议 (LLM)
        # ═══════════════════════════════════════════
        state = await run_analyst(state, llm_call_fn)
        await asyncio.sleep(_YIELD_DELAY)

        for s in state.steps:
            sd = s if isinstance(s, dict) else s.__dict__
            sn = sd.get('step', 0)
            if sn in (101,):
                yield _step_event(sn, sd.get("description", ""), sd.get("status", ""),
                                  sd.get("detail", ""), sd.get("thinking", ""),
                                  sd.get("progress"))
                await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 最终结果
        # ═══════════════════════════════════════════
        yield _make_result(state, session_id)

    except Exception as e:
        logger.error(f"Evaluation workflow failed: {e}", exc_info=True)
        yield {"type": "error", "message": f"评估流程异常: {str(e)[:500]}",
               "session_id": session_id}


def _make_result(state: EvaluationState, session_id: str) -> dict:
    """构造符合前端期望的结果对象"""
    query_type = state.entities.get("query_type", "general_analysis")
    need_conclusion = state.entities.get("need_conclusion", True)
    raw_results = state.raw_results[:20] if state.raw_results else []

    # 前端模板通过 msg.result.type 判断展示类型
    result_type = "data_query" if query_type == "data_query" else "general"

    return {
        "type": "result",
        "session_id": session_id,
        "result": {
            "type": result_type,
            "final_answer": state.final_answer or "分析完成",
            "generatedSql": state.generated_sql,
            "rawResults": raw_results,
            "totalRows": len(state.raw_results),
            "intent": state.intent,
            "query_type": query_type,
            "need_conclusion": need_conclusion,
            "database_used": state.database_id,
            "need_chart": state.need_chart,
            "chartConfig": state.chart_config if state.chart_config else None,
        }
    }
