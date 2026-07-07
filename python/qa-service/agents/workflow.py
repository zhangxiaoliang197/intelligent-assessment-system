"""
评估工作流引擎
编排多智能体协作：Orchestrator -> Text-to-SQL -> SQL执行 -> Analyst
"""
import asyncio
import json
import logging
import re
from .state import EvaluationState
from .orchestrator import build_orchestrator_prompt, apply_orchestrator_result
from .text_to_sql import run_text_to_sql
from .analyst import run_analyst, run_simple_analysis

logger = logging.getLogger("evaluation.workflow")


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


_yield_delay = 0.25


def _step_event(step_num, description, status, detail="", thinking="", progress=None):
    return {
        "type": "step",
        "step": {"step": step_num, "description": description, "status": status,
                  "detail": detail, "thinking": thinking, "progress": progress}
    }


async def run_evaluation_workflow(
    question, llm_call_fn, session_id=None, database_id="", database_name="",
):
    state = EvaluationState(question=question, session_id=session_id,
                            database_id=database_id, database_name=database_name)
    try:
        # ── 步骤 1: 意图分析 ──
        yield _step_event(1, "分析问题意图", "in_progress", "正在调用大模型分析用户问题...")
        await asyncio.sleep(_yield_delay)

        sys_prompt, usr_prompt = build_orchestrator_prompt(state)
        yield _step_event(1.1, "大模型调用", "in_progress", "正在调用大模型进行意图识别...",
                          thinking=f"发送给模型的问题:\n{question[:300]}")
        await asyncio.sleep(_yield_delay)

        try:
            response = await llm_call_fn(sys_prompt, usr_prompt)
        except Exception as e:
            yield _step_event(1.1, "大模型调用", "error", detail=f"调用失败: {str(e)[:100]}")
            await asyncio.sleep(_yield_delay)
            state.intent = "general_analysis"
            state.entities = {"filters": "", "dimensions": [], "query_type": "general_analysis"}
            state.analysis_plan = "直接回答用户问题"
            state = await run_simple_analysis(state, llm_call_fn)
            yield _step_event(101, "分析报告", "completed",
                              detail="分析报告生成完成",
                              thinking=state.final_answer[:800] if state.final_answer else "")
            yield {"type": "result", "session_id": session_id,
                   "final_answer": state.final_answer or "分析失败",
                   "raw_results": [], "total_rows": 0, "generated_sql": "",
                   "query_type": "general_analysis"}
            return

        yield _step_event(1.1, "大模型调用", "completed", "大模型返回意图分析结果",
                          thinking=f"模型原始响应:\n{response[:800]}")
        await asyncio.sleep(_yield_delay)

        state = apply_orchestrator_result(state, response)
        intent = state.intent or "综合评估"
        query_type = state.entities.get("query_type", "")
        analysis_plan = state.analysis_plan or ""
        yield _step_event(1.2, "意图识别结果",
                          "completed",
                          f"意图: {intent} | 模式: {query_type}",
                          thinking=f"【意图识别结果】\n问题类型: {intent}\n查询模式: {query_type}\n"
                                   f"过滤条件: {state.entities.get('filters', '无')}\n"
                                   f"分析维度: {', '.join(state.entities.get('dimensions', [])) or '未指定'}\n"
                                   f"【分析计划】\n{analysis_plan[:500]}")
        await asyncio.sleep(_yield_delay)

        # ── 阶段2: Text-to-SQL ──
        if query_type != "data_query" or not state.database_id:
            state = await run_simple_analysis(state, llm_call_fn)
            yield _step_event(101, "分析报告", "completed",
                              detail="分析报告生成完成",
                              thinking=state.final_answer[:800] if state.final_answer else "")
            yield {"type": "result", "session_id": session_id,
                   "final_answer": state.final_answer or "分析完成",
                   "raw_results": [], "total_rows": 0, "generated_sql": "",
                   "query_type": query_type or "general_analysis"}
            return

        # ── 数据源探查 ──
        yield _step_event(2, "数据源探查", "in_progress",
                          detail=f"正在连接数据源 [{state.database_name or state.database_id}]...")
        await asyncio.sleep(_yield_delay)

        from .tools import fetch_database_tables, fetch_table_structure
        all_tables = fetch_database_tables(state.database_id)
        state.database_tables = all_tables

        table_list_str = "\n".join(f"  - {t}" for t in all_tables)
        yield _step_event(2, "数据源探查", "completed",
                          detail=f"发现 {len(all_tables)} 张数据表",
                          thinking=f"可用表列表:\n{table_list_str}")
        await asyncio.sleep(_yield_delay)

        # ── 表筛选 ──
        relevant = _pick_relevant_tables(all_tables, state.analysis_plan, state.question)
        skipped = [t for t in all_tables if t not in relevant]
        yield _step_event(2.1, "表筛选", "completed",
                          detail=f"选定 {len(relevant)} 张相关表：{', '.join(relevant)}",
                          thinking=(f"从 {len(all_tables)} 张表中筛选出 {len(relevant)} 张。\n"
                                    f"✓ 选中:\n" + "\n".join(f"    - {t}" for t in relevant) +
                                    f"\n✗ 跳过:\n" + "\n".join(f"    - {t}" for t in skipped)))
        await asyncio.sleep(_yield_delay)

        # ── 读取表结构 ──
        yield _step_event(3, "读取表结构", "in_progress",
                          detail=f"正在读取 {len(relevant)} 张相关表的结构...")
        await asyncio.sleep(_yield_delay)

        schemas = []
        for table_name in relevant:
            try:
                s_ = fetch_table_structure(state.database_id, table_name)
                schemas.append(s_)
            except Exception as e:
                logger.warning(f"Failed to read structure for {table_name}: {e}")
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
        await asyncio.sleep(_yield_delay)

        # ── SQL 生成 ──
        state = await run_text_to_sql(state, llm_call_fn)
        await asyncio.sleep(_yield_delay)

        # yield text-to-sql 内部产生的步骤
        for s in state.steps:
            sd = s.__dict__ if hasattr(s, '__dict__') else s
            sn = sd.get('step', 0)
            if sn in (4.1, 4.2, 99):
                yield _step_event(sd["step"], sd["description"], sd["status"],
                                  sd.get("detail", ""), sd.get("thinking", ""),
                                  sd.get("progress"))
                await asyncio.sleep(_yield_delay)

        # ── SQL 执行 + 分析 ──
        if state.sql_valid and state.generated_sql:
            yield _step_event(100, "SQL执行", "in_progress", "正在执行SQL查询到数据库...")
            await asyncio.sleep(_yield_delay)

        state = await run_analyst(state, llm_call_fn)
        await asyncio.sleep(_yield_delay)

        for s in state.steps:
            sd = s.__dict__ if hasattr(s, '__dict__') else s
            sn = sd.get('step', 0)
            if sn in (100, 101):
                yield _step_event(sd["step"], sd["description"], sd["status"],
                                  sd.get("detail", ""), sd.get("thinking", ""),
                                  sd.get("progress"))
                await asyncio.sleep(_yield_delay)

        # ── 最终结果 ──
        yield {
            "type": "result",
            "session_id": session_id,
            "intent": state.intent,
            "generated_sql": state.generated_sql,
            "raw_results": state.raw_results[:20] if state.raw_results else [],
            "total_rows": len(state.raw_results),
            "final_answer": state.final_answer,
            "database_used": state.database_id,
            "query_type": state.entities.get("query_type", "general_analysis")
        }

    except Exception as e:
        logger.error(f"Evaluation workflow failed: {e}", exc_info=True)
        yield {"type": "error", "message": f"评估流程异常: {str(e)[:500]}",
               "session_id": session_id}
