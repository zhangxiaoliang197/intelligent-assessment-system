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
import json
import logging
import os
import re

from .state import EvaluationState
from .tools import (
    fetch_database_tables, fetch_datasets_for_database,
    fetch_indicators_for_datasets, fetch_table_structure,
    _fetch_dataset_structure_inner, execute_sql_on_database,
    fetch_database_config,
)
from .text_to_sql import run_text_to_sql, _validate_sql
from .analyst import run_analyst
from .sufficiency import assess_data_sufficiency, build_indicator_types
from .indicator_engine import (
    build_check_schema, plan_indicators, preflight_indicators,
)

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

def _normalize_name(name: str) -> str:
    """名称归一化：去空格、标点、转小写，便于中文/英文混合匹配。

    消除全半角括号、引号、连接符等差异，例如 "作战 效能（综合）" → "作战效能综合"。
    与 indicator-service/main.py 中的 _normalize_name 保持一致。
    """
    if not name:
        return ""
    return re.sub(r'[\s\u3000（）()【】\[\]《》<>「」“”‘’\-_·、，。！？：；]+', '', name).lower()


def _char_bigrams(text: str) -> set:
    """对中文友好的 2-gram 分词：返回字符串的二元字符集合。

    与 indicator-service/main.py 中的 _char_bigrams 保持一致，
    不引入 jieba 依赖。
    """
    if not text or len(text) < 2:
        return set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _jaccard(set_a: set, set_b: set) -> float:
    """计算两个集合的 Jaccard 相似度。"""
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


def _extract_table_info(t):
    """从 all_tables 元素中提取 (表名, 表注释) 二元组。

    兼容 list[str] 和 list[dict] 两种输入格式：
    - str: 直接作为表名，注释为空
    - dict: 取 tableName 字段，tableComment 字段可能存在
    """
    if isinstance(t, dict):
        return t.get("tableName", ""), t.get("tableComment", "")
    return str(t), ""


def _pick_relevant_tables(all_tables, analysis_plan, question, max_tables=12):
    """基于启发式关键词打分 + 2-gram 语义匹配的表选择器。

    兼容 list[str] 和 list[dict]（含 tableComment）两种输入。
    使用动态阈值替代硬截断：取得分 > 0 的表，按得分降序排列，
    上限 max_tables（默认 12），同分优先非系统表。
    """
    import re as _re
    if not all_tables:
        return []

    # ── 统一转换为 (name, comment) 列表，同时保留原始引用 ──
    table_infos = []
    for t in all_tables:
        name, comment = _extract_table_info(t)
        if name:
            table_infos.append((name, comment, t))

    if len(table_infos) <= max_tables:
        # 表数量未超上限，直接返回全部表名
        return [name for name, _, _ in table_infos]

    scores = {name: 0 for name, _, _ in table_infos}
    plan_lower = (analysis_plan or '').lower()
    question_norm = _normalize_name(question or '')
    question_bigrams = _char_bigrams(question_norm)
    plan_norm = _normalize_name(analysis_plan or '')
    plan_bigrams = _char_bigrams(plan_norm)

    for name, comment, _ in table_infos:
        name_lower = name.lower()
        name_norm = _normalize_name(name)
        name_bigrams = _char_bigrams(name_norm)
        comment_lower = (comment or '').lower()
        comment_norm = _normalize_name(comment)
        comment_bigrams = _char_bigrams(comment_norm)

        # 去掉常见表前缀后得到"业务名"
        base_name = name_lower
        for prefix in ['ass_', 'test_', 'sys_', 'tbl_']:
            if base_name.startswith(prefix):
                base_name = base_name[len(prefix):]
                break

        # ── 策略 1：表名出现在分析计划原文中 → +100 ──
        if name_lower in plan_lower:
            scores[name] += 100

        # ── 策略 2：表名 bigram 与问题 bigram Jaccard ≥ 0.3 → 加分 ──
        if question_bigrams and name_bigrams:
            sim = _jaccard(question_bigrams, name_bigrams)
            if sim >= 0.3:
                scores[name] += int(sim * 30)

        # ── 策略 3：表名 bigram 与分析计划 bigram Jaccard ≥ 0.3 → 加分 ──
        if plan_bigrams and name_bigrams:
            sim = _jaccard(plan_bigrams, name_bigrams)
            if sim >= 0.3:
                scores[name] += int(sim * 15)

        # ── 策略 4：表注释中包含问题 bigram → +15/词 ──
        if comment_bigrams and question_bigrams:
            overlap = comment_bigrams & question_bigrams
            scores[name] += len(overlap) * 15

        # ── 策略 5：表注释 bigram 与问题 bigram Jaccard ≥ 0.3 → 加分 ──
        if question_bigrams and comment_bigrams:
            sim = _jaccard(question_bigrams, comment_bigrams)
            if sim >= 0.3:
                scores[name] += int(sim * 20)

        # ── 策略 6：分析计划中"表 xxx"格式 → +200 ──
        # （在下方统一处理）

    # ── 策略 6：分析计划中的"表 xxx"或"TABLE xxx"格式 → +200 ──
    table_pattern = _re.findall(
        r'(?:table\s*|TABLE\s+|表\s*)([a-zA-Z_][a-zA-Z0-9_]*)',
        analysis_plan or '', _re.IGNORECASE
    )
    for match in table_pattern:
        for name, _, _ in table_infos:
            if name.lower() == match.lower():
                scores[name] += 200

    # ── 排序：按得分降序，同分时非系统表优先 ──
    def _sort_key(item):
        name, score = item
        is_sys = name.lower().startswith(('ass_', 'sys_', 'test_', 'tbl_'))
        return (-score, 1 if is_sys else 0, name.lower())

    sorted_tables = sorted(scores.items(), key=_sort_key)
    top = [name for name, s in sorted_tables if s > 0]

    if not top:
        # 完全无匹配 → fallback：取非系统表前 max_tables 张
        non_sys = [name for name, _, _ in table_infos
                   if not name.lower().startswith(('ass_', 'sys_', 'test_', 'tbl_'))]
        top = non_sys[:max_tables] if non_sys else [name for name, _, _ in table_infos[:max_tables]]

    return top[:max_tables]


def _build_step(step_num, description, status='pending', detail='',
                thinking='', progress=0, phase='data_query'):
    return dict(step=step_num, description=description, status=status,
                detail=detail, thinking=thinking, progress=progress, phase=phase)


def _extract_rows(result):
    return result.get("rows", result.get("data", result.get("results", [])))


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
    SUFFICIENCY       = 7
    RESULT_PREVIEW    = 8
    ANALYST           = 9
    SQL_GEN_THRESHOLD = 5


# =========================================================================
# 阶段 1 – 数据探查（步骤 2）
# =========================================================================

async def data_explore_node(database_id):
    """从目标数据库获取表列表（含表注释，用于后续表选择的语义匹配）。"""
    yield {"type": "step", "step": _build_step(
        Step.DATA_EXPLORE, "Data Explore", "in_progress",
        detail="Fetching table list...", progress=50)}

    all_tables = []
    db_connected = False
    try:
        loop = asyncio.get_event_loop()
        all_tables = await asyncio.wait_for(
            loop.run_in_executor(
                None, fetch_database_tables, database_id, False, False, True),
            timeout=_DB_TIMEOUT)
        db_connected = bool(all_tables)
    except asyncio.TimeoutError:
        logger.warning("获取表列表超时")
    except Exception as e:
        logger.warning(f"获取表列表失败: {e}")

    # all_tables 为 list[dict]（含 tableName/tableComment），显示时提取表名
    table_names = [_extract_table_info(t)[0] for t in all_tables]
    yield {"type": "step", "step": _build_step(
        Step.DATA_EXPLORE, "Data Explore", "completed",
        detail=f"找到 {len(all_tables)} 张数据表",
        thinking="数据库可用表清单：\n" +
                 "\n".join(f"  • {tn}" for tn in table_names[:20])
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

    # 兜底过滤：admin_indicators 是按当前 database_id 过滤后的权威来源；
    # indicator_defs 来自 LLM 生成的指标体系，可能含不属于当前数据源的指标
    # （例如选了 db_olist 但 LLM 幻觉生成了"毛利率"，实际属于 db_tianchi）。
    # 处理策略：同名时用 admin 版本替换（带正确的 dataset_id/field_mapping）；
    # 仅在 admin 中不存在的 LLM 生成指标才保留（概念性指标，让后续 SQL 必要性判断处理）。
    if admin_indicators:
        admin_names = {ai.get("name", "") for ai in admin_indicators}
        deduped = list(admin_indicators)  # admin 版本优先纳入
        seen = set(admin_names)
        for ind in merged:
            name = ind.get("name", "")
            # 仅保留 admin 中没有的 LLM 生成指标（避免名称冲突导致字段映射错位）
            if name and name not in seen:
                deduped.append(ind)
                seen.add(name)
        if len(deduped) != len(merged):
            logger.info(
                f"[dataset_indicator] 按数据源兜底过滤："
                f"传入 {len(merged)} → 过滤后 {len(deduped)} 个指标"
                f"（admin 权威 {len(admin_indicators)} + LLM 新增 {len(deduped) - len(admin_indicators)}）")
        merged = deduped

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
                            database_id, db_connected, required_tables=None):
    """选择相关表，然后并行读取表结构。

    required_tables: 可选，指标规格(sourceTables)引用的表名；
      这些表必须被读取（确定性编译路径），即使启发式打分未命中。
    """
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
    # all_tables 可能是 list[dict]（含 tableName/tableComment），
    # 需从中提取表名与 dataset_table_map（key 为表名字符串）比较
    for t in list(all_tables):
        tname = _extract_table_info(t)[0]
        if tname in dataset_table_map and tname not in relevant:
            if len(relevant) < 6:
                relevant.append(tname)

    # 指标规格引用的表必须覆盖（确定性编译路径）
    if required_tables:
        for t in list(all_tables):
            tname = _extract_table_info(t)[0]
            if tname in required_tables and tname not in relevant:
                relevant.append(tname)

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
# 阶段 3.5 – 字段提示（纯数据转换 + LLM 语义兜底）
# =========================================================================


async def _llm_match_formula_words(formula_words, schemas, llm_call_fn):
    """用 LLM 批量判断公式词对应哪些列。失败返回空 dict。

    作为 build_field_hints 的第 4 级兜底：当本地三级匹配
    (admin fieldMapping / bigram Jaccard / 精确匹配) 全部未命中时，
    一次 LLM 调用批量判断所有未命中公式词对应哪些列。
    """
    if not formula_words or not llm_call_fn:
        return {}

    # 构建列清单 + comment 反查表
    col_lines = []
    col_lookup = {}  # (table, column) -> comment，用于回填注释
    for s in schemas:
        tname = s.get("tableName", "")
        for col in s.get("columns", []):
            cname = col.get("columnName", "")
            comment = (col.get("comment", "")
                       or col.get("businessMeaning", "") or "")
            col_lines.append(f"- {tname}.{cname} ({comment})")
            col_lookup[(tname, cname)] = comment[:60]

    if not col_lines:
        return {}

    system_prompt = (
        "你是数据库字段映射专家。给定指标公式中的概念词和数据库列清单，"
        "判断每个概念词最可能对应哪些列。\n"
        "只返回严格的 JSON，格式：\n"
        '{"概念词": [{"table":"表名","column":"列名"}, ...]}\n'
        "规则：\n"
        "1. 每个概念词最多返回2个最相关的列\n"
        "2. 找不到对应列则返回空数组 []\n"
        "3. 只返回 JSON，不要任何其他文字，不要 markdown 代码块"
    )
    user_message = (
        f"概念词列表：\n{chr(10).join(formula_words)}\n\n"
        f"数据库列清单：\n{chr(10).join(col_lines)}"
    )

    try:
        response = await llm_call_fn(system_prompt, user_message)
        logger.info(f"[build_field_hints] LLM批量匹配 {len(formula_words)} 个公式词，"
                    f"响应 {len(response)} 字符")
    except Exception as e:
        logger.warning(f"[build_field_hints] LLM 调用失败，降级: {e}")
        return {}

    # 解析 JSON（容错：剥离 markdown 代码块和前后说明）
    json_match = re.search(r'\{.*\}', response, re.DOTALL)
    if not json_match:
        logger.warning("[build_field_hints] LLM 响应未找到 JSON")
        return {}
    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.warning(f"[build_field_hints] LLM JSON 解析失败: {e}")
        return {}

    # 转换格式 + 回填 comment
    matches = {}
    for word, cols in result.items():
        col_list = []
        for c in (cols if isinstance(cols, list) else [])[:2]:
            t = c.get("table", "") if isinstance(c, dict) else ""
            col = c.get("column", "") if isinstance(c, dict) else ""
            if t and col:
                cmt = col_lookup.get((t, col), "")
                col_list.append((t, col, cmt))
        if col_list:
            matches[word] = col_list
    logger.info(f"[build_field_hints] LLM 返回 {len(matches)} 个公式词的映射")
    return matches


async def build_field_hints(schemas, merged_indicators, llm_call_fn=None):
    """为每个指标附加列映射提示，以便生成更准确的 SQL 提示词。

    优先级：
    1. admin 已配置的 fieldMapping（JSON 字符串，格式 {"中文计算项": "表名.字段名"}）
       — 用户在管理后台预先配置的权威映射，标注 [admin配置]
    2. bigram Jaccard 模糊匹配 — 公式词与列名/列注释的 2-gram 语义相似度
    3. 精确命中列索引 — 公式词直接匹配列名关键词
    4. LLM 语义匹配 — 上述三级全部未命中时，批量调 LLM 判断公式词对应列（兜底）
    """
    # ── 构建列索引：(关键词) → [(表名, 列名, 注释), ...] ──
    col_index = {}
    # 同时构建 bigram 索引：(列名+注释的 bigram) → [(表名, 列名, 注释), ...]
    col_bigram_index = []
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
            # 构建 bigram 索引条目
            col_text = _normalize_name(f"{cname} {comment}")
            col_bigrams = _char_bigrams(col_text)
            if col_bigrams:
                col_bigram_index.append((col_bigrams, tname, cname, comment[:60]))

    # ── 第一遍：本地三级匹配，收集未命中公式词 ──
    pending_llm_words = set()       # 跨指标去重的未命中公式词
    per_ind_local = []              # [(e, hints, unmatched), ...]
    for ind in merged_indicators:
        e = dict(ind)

        # ── 存储 calculationMethod 供下游 prompt 使用 ──
        calc_method = ind.get("calculationMethod") or ""
        if calc_method:
            e["_calc_method"] = calc_method[:500]

        hints = []

        # ── 优先级 1：admin 已配置的 fieldMapping（JSON 字符串）──
        field_mapping_str = ind.get("fieldMapping") or ""
        if field_mapping_str and field_mapping_str.strip() not in ("", "{}"):
            try:
                mapping = json.loads(field_mapping_str) if isinstance(field_mapping_str, str) else field_mapping_str
                if isinstance(mapping, dict):
                    for cn_term, col_path in mapping.items():
                        col_path_str = str(col_path) if col_path else ""
                        if "." in col_path_str:
                            fm_tname, fm_cname = col_path_str.split(".", 1)
                        else:
                            fm_tname, fm_cname = "(见表)", col_path_str
                        hints.append(f"'{cn_term}' -> {fm_tname}.{fm_cname} [admin配置]")
            except (json.JSONDecodeError, ValueError, TypeError) as ex:
                logger.warning(f"指标 {ind.get('name', '')} fieldMapping 解析失败: {ex}")

        # ── 优先级 2 & 3：bigram 模糊匹配 + 精确命中（仅当无 admin 配置时）──
        unmatched = []
        if not hints:
            formula = ind.get("formula", "")
            formula_words = re.findall(r'[一-龥a-zA-Z_]{2,}', formula)
            for fw in formula_words[:10]:
                # 优先：精确命中列索引
                matches = col_index.get(fw.lower(), [])

                # 兜底：bigram Jaccard 模糊匹配
                if not matches:
                    fw_bigrams = _char_bigrams(_normalize_name(fw))
                    if fw_bigrams:
                        scored = []
                        for col_bg, tname, cname, ccomment in col_bigram_index:
                            sim = _jaccard(fw_bigrams, col_bg)
                            if sim >= 0.3:
                                scored.append((sim, tname, cname, ccomment))
                        # 按相似度降序取 top-2
                        scored.sort(key=lambda x: -x[0])
                        matches = [(t, c, cm) for _, t, c, cm in scored[:2]]

                if matches:
                    for tname, cname, ccomment in matches[:2]:
                        hint = f"'{fw}' -> {tname}.{cname}"
                        if ccomment:
                            hint += f" ({ccomment})"
                        hints.append(hint)
                else:
                    unmatched.append(fw)  # 三级本地全未命中 → 待 LLM 处理

        per_ind_local.append((e, hints, unmatched))
        pending_llm_words.update(unmatched)

    # ── 优先级 4：LLM 批量语义匹配（兜底）──
    llm_result = {}
    if pending_llm_words:
        llm_result = await _llm_match_formula_words(
            list(pending_llm_words), schemas, llm_call_fn)

    # ── 第二遍：回填 LLM 结果 + 组装最终 hints ──
    enhanced = []
    for e, hints, unmatched in per_ind_local:
        for fw in unmatched:
            for tname, cname, ccomment in llm_result.get(fw, [])[:2]:
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
                            question, database_id, llm_call_fn, database_type=""):
    """步骤 5 — 委托给 text_to_sql，转发清晰的摘要。"""
    yield {"type": "step", "step": _build_step(
        Step.SQL_GENERATE, "Generate SQL", "in_progress",
        detail=f"Generating SQL from {len(schemas)} table schemas...",
        progress=50)}

    es = EvaluationState(question=question, database_id=database_id,
                         database_type=database_type)
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

    if result.get("success"):
        rows = _extract_rows(result)
        yield {"type": "step", "step": _build_step(
            Step.SQL_EXECUTE, "Execute SQL", "completed",
            detail=f"查询成功: {len(rows)} 行返回",
            progress=100)}
        yield {"_return": (rows, True)}
        return

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

    rows = _extract_rows(result)
    yield {"type": "step", "step": _build_step(
        Step.SQL_EXECUTE, "Execute SQL", "completed",
        detail=f"查询成功: {len(rows)} 行返回（修正后重试成功）",
        progress=100)}
    yield {"_return": (rows, True)}


# =========================================================================
# 阶段 6 – 结果预览（步骤 7）
# =========================================================================

def result_preview_node(raw_results, sufficiency_report=None,
                        indicator_types=None):
    """步骤 7 — 按场景渲染结果预览。

    根据数据充分性评估结果输出不同的预览内容（显示在执行面板的思考区，
    供技术视图查看；主对话区的解读由 analyst 阶段的流式文本负责）：

      - no_data      → 无数据声明 + 判定理由
      - insufficient → 逐指标覆盖表 + 判定理由
      - sufficient   → 5 行数据预览（含计算型指标时附简要摘要）

    Args:
        raw_results:         SQL 执行返回的行列表
        sufficiency_report:  assess_data_sufficiency 的返回报告
        indicator_types:     {指标名: "direct"|"computed"} 映射
    """
    report = sufficiency_report or {}
    scenario = report.get("scenario", "sufficient")
    reason = report.get("reason", "")

    # ── 无数据场景 ──
    if scenario == "no_data" or not raw_results:
        yield {"type": "step", "step": _build_step(
            Step.RESULT_PREVIEW, "Result Preview", "completed",
            detail=f"无数据可预览（{reason[:60]}）" if reason else "无数据可预览",
            thinking=f"数据充分性判定：no_data\n{reason}",
            progress=100)}
        return

    # ── 数据不足场景：输出逐指标覆盖表 ──
    if scenario == "insufficient":
        per_ind = report.get("per_indicator", [])
        lines = ["数据覆盖报告："]
        for p in per_ind:
            status = "✓" if p.get("has_data") else "✗"
            miss = "、".join(p.get("missing_dimensions", [])) or "—"
            lines.append(
                f"  [{status}] {p.get('name', '')} "
                f"| 可用 {p.get('row_count', 0)} 行 | 缺失: {miss}")
        lines.append(f"\n判定理由：{reason}")
        yield {"type": "step", "step": _build_step(
            Step.RESULT_PREVIEW, "Result Preview", "completed",
            detail=(f"数据不足：{report.get('indicators_with_data', 0)}/"
                    f"{report.get('indicators_total', 0)} 个指标有数据"),
            thinking="\n".join(lines),
            progress=100)}
        return

    # ── 数据充分场景：5 行预览 + 计算型指标摘要 ──
    if not isinstance(raw_results[0], dict):
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
    detail = f"列: {', '.join(cols[:10])} | 共 {len(raw_results)} 行"

    # 计算型指标简要摘要
    types = indicator_types or {}
    computed_names = [n for n, t in types.items() if t == "computed"]
    if computed_names:
        preview += f"\n计算型指标：{', '.join(computed_names[:8])}"
        detail += f" | 计算型 {len(computed_names)} 个"

    yield {"type": "step", "step": _build_step(
        Step.RESULT_PREVIEW, "Result Preview", "completed",
        detail=detail,
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

def _spec_table_names(indicator_defs):
    """收集指标规格 sourceTables 引用的物理表名。"""
    names = []
    for ind in indicator_defs or []:
        spec_raw = ind.get("indicatorSpec") or ind.get("_spec") or ""
        spec = None
        if isinstance(spec_raw, str) and spec_raw.strip():
            try:
                spec = json.loads(spec_raw)
            except json.JSONDecodeError:
                spec = None
        elif isinstance(spec_raw, dict):
            spec = spec_raw
        if not spec:
            continue
        for st in spec.get("sourceTables") or []:
            tn = st.get("tableName", "") if isinstance(st, dict) else ""
            if tn and tn not in names:
                names.append(tn)
    return names


def _has_spec(indicator_defs):
    for ind in indicator_defs or []:
        spec = ind.get("indicatorSpec") or ind.get("_spec") or ""
        if spec:
            return True
    return False


async def _compiled_query_flow(question, database_id, merged,
                               schemas, llm_call_fn, stream_llm_gen,
                               selection_note="", quote_style="none"):
    """确定性编译路径：Preflight → 计划编译 → 执行 → 分析。"""
    from .indicator_engine import build_check_schema, plan_indicators, preflight_indicators

    check_schema = build_check_schema(schemas)
    spec_indicators = [ind for ind in merged
                       if ind.get("indicatorSpec") or ind.get("_spec")]

    # ── 参数抽取（LLM 窄任务 + 确定性兜底） ──
    params = await _extract_query_params(question, spec_indicators, llm_call_fn)
    if params:
        logger.info(f"[compiled] 抽取参数: {params}")

    # ── Preflight 就绪度检查（查询前） ──
    preflight = preflight_indicators(spec_indicators, check_schema=check_schema,
                                     question=question, quote_style=quote_style)
    yield {"type": "step", "step": _build_step(
        Step.SUFFICIENCY, "Preflight Readiness", "completed",
        detail=(f"就绪 {preflight['ready']}/{preflight['total']} 个指标"
                f"{selection_note}"),
        thinking=("指标就绪度：\n" + "\n".join(
            f"  [{p['status']}] {p['name']}" + (f" — {p['reason']}" if p["reason"] else "")
            for p in preflight["per_indicator"])),
        progress=100)}

    # ── 查询计划编译 ──
    plan_result = plan_indicators(spec_indicators, params=params,
                                  check_schema=check_schema,
                                  quote_style=quote_style)
    plans = [p for p in plan_result.get("plans", []) if p.get("ok")]
    if not plans:
        reason = "；".join(plan_result.get("gaps", []) or ["无可用查询计划"])
        yield {"type": "step", "step": _build_step(
            Step.SQL_GENERATE, "Compile Query Plan", "error",
            detail=reason[:120], progress=100)}
        # 让 analyst 输出缺口说明
        es = EvaluationState(question=question, database_id=database_id)
        es.indicator_defs = merged
        es.sufficiency_report = {
            "scenario": "insufficient",
            "reason": f"指标规格存在缺口：{reason[:200]}",
            "per_indicator": preflight.get("per_indicator", []),
        }
        es.execution_error = reason[:200]
        async for ev in analyst_node(es, [], stream_llm_gen):
            yield ev
        yield {"type": "result",
               "final_answer": es.final_answer or f"指标查询计划不可用：{reason[:200]}",
               "generatedSql": "", "rawResults": [], "totalRows": 0,
               "query_type": "data_query", "database_used": database_id,
               "preflight": preflight, "queryPlan": plan_result}
        return

    all_sql = [p["sql"] for p in plans]
    yield {"type": "step", "step": _build_step(
        Step.SQL_GENERATE, "Compile Query Plan", "completed",
        detail=f"生成 {len(all_sql)} 条确定性 SQL",
        thinking="\n\n".join(f"--- 计划 {i + 1} ---\n{sql}"
                             for i, sql in enumerate(all_sql)),
        progress=100)}

    # ── 执行（每条计划独立执行，按计划归并结果） ──
    raw_results = []
    exec_ok = True
    es = EvaluationState(question=question, database_id=database_id)
    es.indicator_defs = merged
    for i, p in enumerate(plans):
        result = execute_sql_on_database(database_id, p["sql"])
        if not result.get("success"):
            exec_ok = False
            msg = result.get("message", "执行失败")
            yield {"type": "step", "step": _build_step(
                Step.SQL_EXECUTE, f"Execute Plan {i + 1}", "error",
                detail=msg[:120], progress=100)}
            es.execution_error = msg[:300]
            continue
        rows = _extract_rows(result)
        raw_results.extend(rows)
        yield {"type": "step", "step": _build_step(
            Step.SQL_EXECUTE, f"Execute Plan {i + 1}", "completed",
            detail=f"返回 {len(rows)} 行", progress=100)}

    es.generated_sql = "; ".join(all_sql) if len(all_sql) > 1 else all_sql[0]
    es.raw_results = raw_results
    es.sufficiency_report = {
        "scenario": "sufficient" if (exec_ok and raw_results) else "no_data",
        "total_rows": len(raw_results),
        "reason": (f"确定性查询完成（{len(raw_results)} 行，"
                   f"{len(all_sql)} 条计划）") if exec_ok else "查询执行失败",
        "per_indicator": preflight.get("per_indicator", []),
    }
    es.indicator_types = build_indicator_types(merged)

    for ev in result_preview_node(raw_results, es.sufficiency_report,
                                  es.indicator_types):
        yield ev
    async for ev in analyst_node(es, raw_results, stream_llm_gen):
        yield ev

    yield {"type": "result",
           "final_answer": es.final_answer or "分析完成",
           "generatedSql": es.generated_sql,
           "rawResults": raw_results[:20],
           "totalRows": len(raw_results),
           "query_type": "data_query", "database_used": database_id,
           "preflight": preflight, "queryPlan": plan_result}


async def _extract_query_params(question, spec_indicators, llm_call_fn):
    """从问题中抽取规格参数值（LLM 窄任务；失败用问题文本关键词兜底）。"""
    params = {}
    specs = []
    for ind in spec_indicators:
        spec_raw = ind.get("indicatorSpec") or ind.get("_spec") or ""
        if isinstance(spec_raw, str) and spec_raw.strip():
            try:
                spec = json.loads(spec_raw)
            except json.JSONDecodeError:
                continue
        elif isinstance(spec_raw, dict):
            spec = spec_raw
        else:
            continue
        if spec.get("parameters"):
            specs.append(spec)
    if not specs or not question:
        return {}

    all_params = []
    for spec in specs:
        for p in spec.get("parameters", []):
            name = p.get("name", "")
            term = p.get("term", "")
            if name and name not in all_params:
                all_params.append({"name": name, "term": term,
                                   "target": p.get("target", {})})

    system_prompt = (
        "从用户问题中抽取指标查询参数的取值。只返回严格 JSON 对象："
        '{"参数名": "值"}。找不到就给空字符串 ""。不要任何其他文字。'
    )
    user_message = (
        f"问题：{question}\n"
        f"参数：{json.dumps(all_params, ensure_ascii=False)}"
    )
    if llm_call_fn:
        try:
            response = await llm_call_fn(system_prompt, user_message)
            import re as _re
            m = _re.search(r"\{.*\}", response or "", _re.DOTALL)
            if m:
                parsed = json.loads(m.group())
                if isinstance(parsed, dict):
                    for name, val in parsed.items():
                        if val not in (None, ""):
                            params[name] = str(val)
        except Exception as e:
            logger.warning(f"[compiled] LLM 参数抽取失败，走关键词兜底: {e}")

    # 兜底：问题中 term 后跟值的模式
    if not params:
        for p in all_params:
            term = p.get("term", "")
            if not term:
                continue
            m = re.search(re.escape(term) + r"[：:为是]?\s*([^\s，。；,!?]{1,30})", question)
            if m:
                params[p["name"]] = m.group(1).strip()
    return params


async def run_indicator_query(question, database_id, database_name,
                              indicator_defs, analysis_plan,
                              llm_call_fn, stream_llm_gen=None,
                              selected_indicator_names=None):
    """编排完整的指标分析流水线。

    按顺序调用各个阶段节点。节点产出的事件直接转发给调用方；
    ``_return`` 哨兵值在内部消费，用于在节点之间传递数据。

    Args:
        stream_llm_gen: 可选的异步生成器，用于在分析师阶段进行实时 token 流式输出。
        selected_indicator_names: 可选的指标名称列表。非空时仅查询这些指标
            （在 dataset_indicator_node 合并 admin 指标之后过滤），数据充分性
            判定也相应只针对这些指标。为 None/空时查询全部指标（向后兼容）。
    """

    # ── 获取数据库类型（用于 SQL 方言适配）─────────────────────────
    db_config = fetch_database_config(database_id) if database_id else {}
    database_type = db_config.get("type", "")
    from .indicator_engine import _quote_style_for
    quote_style = _quote_style_for(database_type)

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

    selection_note = ""

    # ── 按用户选择过滤指标（在 admin 指标合并之后过滤，避免未选指标被合并回来）──
    # selected_indicator_names 非空时，仅保留用户选中的指标。过滤后整条管线
    # （字段提示 / SQL 生成 / 充分性判定 / 分析）都只针对选中指标。
    selection_total = len(merged)  # 过滤前的指标总数（含合并的 admin 指标）
    if selected_indicator_names:
        sel = {_normalize_name(n) for n in selected_indicator_names if n}
        before = len(merged)
        merged = [ind for ind in merged
                  if _normalize_name(ind.get("name", "")) in sel]
        logger.info(
            f"[select] 用户选中 {len(selected_indicator_names)} 个，"
            f"合并后过滤 {before}->{len(merged)} 个指标进行查询")
        if not merged:
            # 选中名称与解析到的指标全部未匹配（名称差异过大）→ 兜底用全部指标
            logger.warning("[select] 选中指标均未匹配到已解析指标，回退为查询全部")
            merged = list(indicator_defs or [])

    # ── 步骤 4: 表选择与结构读取 ─────────────────────────────────────
    schemas = None
    required_tables = _spec_table_names(merged)
    async for ev in table_select_node(all_tables, datasets, analysis_plan,
                                      question, database_id, db_connected,
                                      required_tables=required_tables):
        if "_return" in ev:
            schemas = ev["_return"]
        else:
            yield ev

    # ── 确定性编译路径：有指标规格的指标优先走编译（不依赖运行期 LLM 猜 SQL） ──
    if _has_spec(merged):
        async for ev in _compiled_query_flow(
                question, database_id, merged, schemas,
                llm_call_fn, stream_llm_gen, selection_note=selection_note,
                quote_style=quote_style):
            yield ev
        return

    # ── 字段提示（本地三级匹配 + LLM 语义兜底）────────────────────────────
    enhanced_indicators = await build_field_hints(schemas, merged, llm_call_fn)

    # ── 步骤 5: 生成 SQL ───────────────────────────────────────────
    es = gen_ok = None
    async for ev in sql_generate_node(schemas, enhanced_indicators,
                                      analysis_plan, question,
                                      database_id, llm_call_fn,
                                      database_type):
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

    # ── 步骤 6.5: 数据充分性评估（确定性判定，不依赖 LLM） ───────────
    # 区分「技术失败」与「库无数据」：gen_ok/exec_ok 任一为 False 即技术失败
    technical_failure = (not gen_ok) or (not exec_ok)
    failure_msg = es.execution_error or ""
    sufficiency_report = assess_data_sufficiency(
        raw_results, enhanced_indicators, question,
        technical_failure=technical_failure, error_msg=failure_msg)
    es.sufficiency_report = sufficiency_report
    es.indicator_types = build_indicator_types(enhanced_indicators)
    # 选中指标时在步骤中标注「已选择 N/M」，便于用户确认过滤生效
    if selected_indicator_names and selection_total:
        selection_note = (f" | 已选择 {sufficiency_report['indicators_total']}/"
                          f"{selection_total} 个指标")
    yield {"type": "step", "step": _build_step(
        Step.SUFFICIENCY, "Assess Data Sufficiency", "completed",
        detail=(f"场景判定：{sufficiency_report['scenario']} | "
                f"{sufficiency_report['reason'][:80]}{selection_note}"),
        thinking=(f"覆盖率 {sufficiency_report['indicators_with_data']}/"
                  f"{sufficiency_report['indicators_total']} | "
                  f"意图 {sufficiency_report['intent']} | "
                  f"行数 {sufficiency_report['total_rows']}"
                  f"{selection_note}"),
        progress=100)}

    # ── 步骤 7: 结果预览（按场景渲染，无数据/不足/充分各有分支） ──────
    for ev in result_preview_node(raw_results, sufficiency_report,
                                  es.indicator_types):
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
