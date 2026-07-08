"""
评估工作流引擎
编排多智能体协作：
  步骤0: 检查数据集管理 & 指标管理（用户预定义信息）
  步骤1: 分析问题意图（LLM）
  步骤2: 数据源探查 → 发现表 → 筛选相关表
  步骤3: 读取对应的表结构
  步骤4: 生成SQL（LLM）
  步骤5: 执行SQL → 获取查询结果
  步骤6: 基于数据生成2-3条建议（LLM）
"""
import asyncio
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
        # 步骤 0: 检查数据集管理和指标管理
        # ═══════════════════════════════════════════
        yield _step_event(0, "检查数据集和指标", "in_progress",
                          detail="正在检查数据集管理和指标管理中的预定义信息...")
        await asyncio.sleep(_YIELD_DELAY)

        from .tools import fetch_datasets_for_database, fetch_indicators_for_datasets

        datasets_found = []
        indicators_found = []
        if state.database_id:
            try:
                datasets_found = fetch_datasets_for_database(state.database_id)
            except Exception as e:
                logger.warning(f"获取数据集失败: {e}")

            if datasets_found:
                ds_names = ", ".join(ds.get("name", "") for ds in datasets_found[:5])
                ds_desc = "\n".join(
                    f"  - {ds.get('name', '')}: {ds.get('description', '')[:100]}"
                    for ds in datasets_found[:5]
                )
                yield _step_event(0.1, "查询数据集描述", "completed",
                                  detail=f"发现 {len(datasets_found)} 个关联数据集: {ds_names}",
                                  thinking=f"【数据集管理 — 用户预定义的描述】\n{ds_desc}")
            else:
                yield _step_event(0.1, "查询数据集描述", "completed",
                                  detail="未找到关联的数据集（将直接使用数据库表结构）",
                                  thinking="数据集管理中无与此数据源关联的数据集")
            await asyncio.sleep(_YIELD_DELAY)

            try:
                ds_ids = [ds.get("id") for ds in datasets_found]
                indicators_found = fetch_indicators_for_datasets(ds_ids)
            except Exception as e:
                logger.warning(f"获取指标失败: {e}")

            if indicators_found:
                ind_names = ", ".join(ind.get("name", "") for ind in indicators_found[:5])
                ind_desc = "\n".join(
                    f"  - {ind.get('name', '')}"
                    + (f" (公式: {ind.get('formula', '')})" if ind.get('formula') else "")
                    + (f" [说明: {ind.get('description', '')}]" if ind.get('description') else "")
                    for ind in indicators_found[:5]
                )
                yield _step_event(0.2, "查询指标定义", "completed",
                                  detail=f"发现 {len(indicators_found)} 个关联指标: {ind_names}",
                                  thinking=f"【指标管理 — 用户预定义的指标】\n{ind_desc}")
            else:
                yield _step_event(0.2, "查询指标定义", "completed",
                                  detail="未找到关联的指标定义",
                                  thinking="指标管理中无与此数据源关联的指标")
            await asyncio.sleep(_YIELD_DELAY)

        total_extra = len(datasets_found) + len(indicators_found)
        yield _step_event(0, "检查数据集和指标", "completed",
                          detail=f"检查完成: {len(datasets_found)} 个数据集, {len(indicators_found)} 个指标",
                          thinking=f"数据集数: {len(datasets_found)} | 指标数: {len(indicators_found)} | 总计额外上下文: {total_extra} 项")
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 1: 分析问题意图
        # ═══════════════════════════════════════════
        yield _step_event(1, "分析问题意图", "in_progress",
                          detail="正在调用大模型分析用户问题...")
        await asyncio.sleep(_YIELD_DELAY)

        sys_prompt, usr_prompt = build_orchestrator_prompt(state)
        yield _step_event(1.1, "大模型调用", "in_progress",
                          detail="正在将问题及上下文发送给大模型进行意图识别...",
                          thinking=f"【发送给模型】\n系统提示词: 约{len(sys_prompt)}字符\n用户问题: {question[:300]}")
        await asyncio.sleep(_YIELD_DELAY)

        try:
            response = await llm_call_fn(sys_prompt, usr_prompt)
        except Exception as e:
            yield _step_event(1.1, "大模型调用", "error",
                              detail=f"调用失败: {str(e)[:100]}")
            await asyncio.sleep(_YIELD_DELAY)
            state.intent = "general_analysis"
            state.entities = {"filters": "", "dimensions": [], "query_type": "general_analysis"}
            state.analysis_plan = "直接回答用户问题"
            state = await run_simple_analysis(state, llm_call_fn)
            yield _step_event(99, "分析报告", "completed",
                              detail="分析报告生成完成",
                              thinking=state.final_answer[:800] if state.final_answer else "")
            yield _make_result(state, session_id)
            return

        yield _step_event(1.1, "大模型调用", "completed",
                          detail="大模型返回意图分析结果",
                          thinking=f"【模型原始响应】\n{response[:800]}")
        await asyncio.sleep(_YIELD_DELAY)

        state = apply_orchestrator_result(state, response)
        intent = state.intent or "综合评估"
        query_type = state.entities.get("query_type", "")
        analysis_plan = state.analysis_plan or ""

        yield _step_event(1.2, "意图识别结果", "completed",
                          detail=f"意图: {intent} | 查询模式: {query_type}",
                          thinking=(
                              f"【意图识别结果】\n"
                              f"问题类型: {intent}\n"
                              f"查询模式: {query_type}\n"
                              f"过滤条件: {state.entities.get('filters', '无')}\n"
                              f"分析维度: {', '.join(state.entities.get('dimensions', [])) or '未指定'}\n"
                              f"【分析计划】\n{analysis_plan[:500]}"
                          ))
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 兜底：只要选了数据源就强制走 data_query
        # ═══════════════════════════════════════════
        if state.database_id and query_type != "data_query":
            query_type = "data_query"
            state.entities["query_type"] = "data_query"
            yield _step_event(1.3, "路由修正", "completed",
                              detail="已选择数据源，自动切换为数据库查询模式",
                              thinking="检测到已连接数据库，将 LLM 返回的 general_analysis 修正为 data_query")
            await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 无数据库 → 直接分析回答
        # ═══════════════════════════════════════════
        if not state.database_id:
            yield _step_event(2, "直接分析", "in_progress",
                              detail="无数据源连接，直接生成回答...")
            await asyncio.sleep(_YIELD_DELAY)
            state = await run_simple_analysis(state, llm_call_fn)
            yield _step_event(2, "直接分析", "completed",
                              detail="分析完成",
                              thinking=state.final_answer[:800] if state.final_answer else "")
            yield _make_result(state, session_id)
            return

        # ═══════════════════════════════════════════
        # 步骤 2: 数据源探查 — 发现表 → 筛选相关表
        # ═══════════════════════════════════════════
        yield _step_event(2, "数据源探查", "in_progress",
                          detail=f"正在连接数据源 [{state.database_name or state.database_id}] 查询数据表...")
        await asyncio.sleep(_YIELD_DELAY)

        from .tools import fetch_database_tables, fetch_table_structure
        all_tables = fetch_database_tables(state.database_id)
        state.database_tables = all_tables

        table_list_str = "\n".join(f"  - {t}" for t in all_tables[:30])
        if len(all_tables) > 30:
            table_list_str += f"\n  ... 共 {len(all_tables)} 张表"
        yield _step_event(2, "数据源探查", "completed",
                          detail=f"发现 {len(all_tables)} 张数据表",
                          thinking=f"【数据库中的表列表】\n{table_list_str}")
        await asyncio.sleep(_YIELD_DELAY)

        # 筛选相关表
        relevant = _pick_relevant_tables(all_tables, state.analysis_plan, state.question)
        skipped = [t for t in all_tables if t not in relevant]

        yield _step_event(2.1, "表筛选", "completed",
                          detail=f"选定 {len(relevant)} 张相关表: {', '.join(relevant)}",
                          thinking=(
                              f"从 {len(all_tables)} 张表中筛选出 {len(relevant)} 张。\n"
                              f"✓ 选中:\n" + "\n".join(f"    - {t}" for t in relevant) +
                              f"\n✗ 跳过:\n" + "\n".join(f"    - {t}" for t in skipped[:20]) +
                              (f"\n    ... 共 {len(skipped)} 张跳过" if len(skipped) > 20 else "")
                          ))
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 3: 读取表结构 — 每张表独立展示
        # ═══════════════════════════════════════════
        yield _step_event(3, "读取表结构", "in_progress",
                          detail=f"正在读取 {len(relevant)} 张相关表的结构定义...")
        await asyncio.sleep(_YIELD_DELAY)

        schemas = []
        for i, table_name in enumerate(relevant):
            yield _step_event(3.1, f"读取表结构 ({i+1}/{len(relevant)})", "in_progress",
                              detail=f"正在读取表 [{table_name}] 的字段信息...")
            await asyncio.sleep(_YIELD_DELAY)
            try:
                s_ = fetch_table_structure(state.database_id, table_name)
                schemas.append(s_)
                cols = s_.get("columns", [])
                col_desc = "\n".join(
                    f"    {c['columnName']:20s} {c['dataType']:12s}"
                    + (" [主键]" if c.get('isPrimaryKey') else "")
                    + (f" -- {c.get('comment', '')}" if c.get('comment') else "")
                    for c in cols
                )
                yield _step_event(3.1, f"读取表结构 ({i+1}/{len(relevant)})", "completed",
                                  detail=f"[{table_name}] 读取完成: {len(cols)} 列",
                                  thinking=f"【表结构: {table_name}】\n{col_desc}")
            except Exception as e:
                logger.warning(f"读取表 {table_name} 结构失败: {e}")
                yield _step_event(3.1, f"读取表结构 ({i+1}/{len(relevant)})", "error",
                                  detail=f"[{table_name}] 读取失败: {str(e)[:100]}")
            await asyncio.sleep(_YIELD_DELAY)

        state.table_schemas = schemas

        col_summary = []
        for s_ in schemas:
            tn = s_.get("tableName", "?")
            cc = s_.get("count", 0)
            cols = ", ".join(c["columnName"] for c in s_.get("columns", [])[:8])
            if cc > 8:
                cols += f" ...共{cc}列"
            col_summary.append(f"{tn}({cc}列): {cols}")
        yield _step_event(3, "读取表结构", "completed",
                          detail=f"已读取 {len(schemas)}/{len(relevant)} 张表结构",
                          thinking="\n".join(f"  - {p}" for p in col_summary))
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 4: 生成SQL（LLM）
        # ═══════════════════════════════════════════
        yield _step_event(4, "生成SQL", "in_progress",
                          detail=f"正在基于 {len(schemas)} 张表结构生成SQL查询...")
        await asyncio.sleep(_YIELD_DELAY)

        state = await run_text_to_sql(state, llm_call_fn)
        await asyncio.sleep(_YIELD_DELAY)

        # yield text-to-sql 内部产生的步骤
        for s in state.steps:
            sd = s if isinstance(s, dict) else s.__dict__
            sn = sd.get('step', 0)
            if sn in (4.1, 4.2):
                yield _step_event(sn, sd.get("description", ""), sd.get("status", ""),
                                  sd.get("detail", ""), sd.get("thinking", ""),
                                  sd.get("progress"))
                await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 5: 执行SQL → 获取查询结果
        # ═══════════════════════════════════════════
        if state.sql_valid and state.generated_sql:
            yield _step_event(5, "执行SQL查询", "in_progress",
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

                    yield _step_event(5, "执行SQL查询", "completed",
                                      detail=f"查询成功，返回 {len(rows)} 行数据",
                                      thinking=f"【SQL执行结果】\n" + "\n".join(preview_parts) +
                                               f"\n\n【执行的SQL】\n{state.generated_sql[:500]}")
                else:
                    state.execution_error = result.get("message", "SQL执行失败")
                    yield _step_event(5, "执行SQL查询", "error",
                                      detail=f"SQL执行失败: {state.execution_error[:200]}",
                                      thinking=f"错误详情: {state.execution_error}")
            else:
                yield _step_event(5, "执行SQL查询", "skipped",
                                  detail="未选择数据源，跳过SQL执行")
        else:
            yield _step_event(5, "执行SQL查询", "skipped",
                              detail="无需执行SQL（SQL生成失败或非查询模式）")
        await asyncio.sleep(_YIELD_DELAY)

        # ═══════════════════════════════════════════
        # 步骤 6: 生成分析建议 (LLM)
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
            "database_used": state.database_id,
        }
    }
