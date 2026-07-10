"""
制空权分析智能体 (Air Superiority Agent)

系统架构位置:
  qa-service / agents 层 — 制空权分析领域智能体

核心职责:
  1. 根据用户自然语言提问，从提问中提取目标区域名称（正则匹配 air_queries.json 中的 regionRules）
  2. 加载预配置的制空权分析SQL模板，通过 LLM 选择与用户提问最相关的查询维度
  3. 将提取的区域名称注入 SQL 模板的占位符中，逐条执行查询
  4. 汇总结论并在 need_conclusion=True 时调用 LLM 生成红蓝双方制空权对比分析

与 combat_effectiveness_agent 的区别:
  - 增加了区域提取 (extract_region) 和 SQL 占位符注入 (inject_region) 环节
  - 使用的配置文件是 air_queries.json（而非 queries.json）
  - 分析视角聚焦红蓝双方对比

数据流:
  用户提问 → load_air_queries() 加载配置 → extract_region() 提取区域
  → _select_queries_by_llm() 选择查询 → inject_region() 注入区域参数
  → execute_sql_on_database() 逐条执行 → LLM逐条分析 → LLM综合评估
  → yield step_event / result 事件
"""
import asyncio
import json
import logging
import os
import re

# 从同包 tools 模块导入数据库执行工具
from .tools import execute_sql_on_database
# 从同包 crewdefs 模块导入制空权分析智能体的 CrewAI 角色定义
from .crewdefs import AIR_SUPERIORITY_AGENT

# 模块级 logger，命名空间为 evaluation.air_superiority
logger = logging.getLogger("evaluation.air_superiority")

# 构建系统角色 prompt：将 CrewAI 角色定义拼接为 LLM 的 system message
_AIR_SYSTEM_ROLE = (
    f"你是{AIR_SUPERIORITY_AGENT['role']}。\n"
    f"目标: {AIR_SUPERIORITY_AGENT['goal']}\n"
    f"{AIR_SUPERIORITY_AGENT['backstory']}"
)

# 项目根目录 = qa-service 目录（当前文件在 agents/ 子目录下，os.path.dirname 两次回到服务根目录）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 制空权分析预配置SQL查询的 JSON 文件默认路径
AIR_QUERIES_FILE = os.path.join(BASE_DIR, "config", "air_queries.json")

# 流式事件之间的延迟（秒），用于给前端展示进度动画留出时间
_YIELD_DELAY = 0.25


def load_air_queries():
    """加载制空权分析的预配置SQL查询列表及区域规则

    优先从环境变量 AIR_QUERIES_PATH 读取配置文件路径，
    若未设置则使用默认路径 config/air_queries.json。
    文件内容包含两部分：regionRules（区域提取规则）和 groups（查询分组）。

    Returns:
        dict: 包含 regionRules 和 groups 的配置字典。
              若文件不存在则返回默认空配置（regionRules 含空 patterns 和默认值，
              groups 为空列表）。
    """
    # 支持通过环境变量覆盖配置文件路径（Docker 部署时通过卷挂载注入）
    path = os.getenv("AIR_QUERIES_PATH", AIR_QUERIES_FILE)
    if not os.path.exists(path):
        logger.warning(f"air_queries.json not found at {path}")
        return {"regionRules": {"patterns": [], "placeholder": "{region}", "defaultValue": "全部区域"}, "groups": []}
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
        # 移除 JSON 不允许的控制字符（保留 \t \n \r）
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
        return json.loads(cleaned)


def _step_event(step_num, description, status, detail="", thinking="", progress=None, sub_step=None):
    """构造流式步骤事件字典

    用于通过 SSE (Server-Sent Events) 向前端推送分析进度。

    Args:
        step_num: 步骤编号，在父级 workflow 中作为子步骤标识
        description: 步骤的简短描述文字
        status: 步骤状态，'in_progress' | 'completed' | 'failed'
        detail: 面向用户的详细进度信息
        thinking: 面向用户的"思考过程"展示内容
        progress: 手动指定的进度百分比 (0-100)，若为 None 则根据 status 自动推断
        sub_step: 可选的子步骤标识

    Returns:
        dict: 符合前端 SSE 事件协议的步骤事件字典
    """
    # 若未手动指定 progress，则根据状态自动推算：completed=100, in_progress=50, 其他=0
    if progress is None:
        progress = 100 if status == "completed" else (50 if status == "in_progress" else 0)
    s = {
        "type": "step",
        "step": {
            "step": step_num, "description": description, "status": status,
            "detail": detail, "thinking": thinking, "progress": progress
        }
    }
    if sub_step:
        s["step"]["subStep"] = sub_step
    return s


async def _adapted_llm_call(prompt: str, llm_call_fn) -> str:
    """将单段 prompt 适配为 system + user 调用（使用 CrewAI 角色定义）

    传入的 llm_call_fn 签名为 async (system_prompt, user_prompt) -> str，
    本函数将 CrewAI 角色定义作为 system prompt，将调用方传入的 prompt 作为 user prompt。

    Args:
        prompt: 用户消息内容
        llm_call_fn: 异步 LLM 调用函数，签名为 async (system, user) -> str

    Returns:
        str: LLM 的响应文本；若 LLM 返回空或 None，则返回兜底文本 "分析结果不可用"
    """
    response = await llm_call_fn(
        _AIR_SYSTEM_ROLE,
        prompt
    )
    return response or "分析结果不可用"


def extract_region(user_query, region_rules):
    """从用户提问中提取区域名称

    遍历 air_queries.json 中 regionRules.patterns 列表的正则表达式规则，
    逐个尝试匹配用户提问文本。第一个成功匹配的规则将提取对应捕获组的内容，
    并可按规则配置附加后缀（如 "区域"、"地区" 等）。

    Args:
        user_query: 用户的自然语言提问
        region_rules: 从 air_queries.json 加载的 regionRules 字典，
                      包含 patterns（正则规则列表）、defaultValue（默认值）、
                      placeholder（占位符标识）

    Returns:
        str: 提取到的区域名称；若所有规则均未匹配则返回 defaultValue（默认 "全部区域"）
    """
    # 获取默认值作为兜底
    default_value = region_rules.get("defaultValue", "全部区域")
    # 按顺序遍历正则规则，第一个匹配即返回
    for rule in region_rules.get("patterns", []):
        pattern = rule.get("regex", "")  # 正则表达式字符串
        group = rule.get("group", 1)      # 捕获组编号（默认为第1组）
        suffix = rule.get("suffix", "")   # 可选的后缀追加（如 "区域"）
        try:
            match = re.search(pattern, user_query)
            # 确保匹配成功且捕获组编号有效
            if match and group <= len(match.groups()):
                extracted = match.group(group).strip()
                # 如果配置了后缀且提取结果不以该后缀结尾，则追加后缀
                if suffix and not extracted.endswith(suffix):
                    extracted = extracted + suffix
                return extracted
        except Exception:
            # 单个规则匹配异常时跳过，继续尝试下一条规则
            continue
    # 所有规则均未命中，返回默认值
    return default_value


def inject_region(sql, region, placeholder):
    """将区域名称注入SQL中的占位符

    对 SQL 模板字符串执行简单的字符串替换，将所有占位符（默认 {region}）
    替换为提取到的具体区域名称。

    Args:
        sql: 包含占位符的 SQL 模板字符串
        region: 从用户提问中提取的区域名称
        placeholder: 占位符标识字符串（默认 "{region}"）

    Returns:
        str: 已完成占位符替换的 SQL 语句
    """
    return sql.replace(placeholder, region)


async def _select_queries_by_llm(user_query, groups, llm_call_fn):
    """用 LLM 选择与用户提问最相关的制空权分析查询

    将 groups 中的所有查询扁平化为编号列表，构造选择 prompt 发送给 LLM，
    由 LLM 根据用户提问语义选择最相关的查询编号。

    Args:
        user_query: 用户的自然语言提问
        groups: 从 air_queries.json 加载的查询分组列表
        llm_call_fn: 异步 LLM 调用函数

    Returns:
        list[dict]: LLM 筛选后的查询列表；若查询总数 ≤ 2 则直接返回全部；
                    若 LLM 解析失败则回退返回全部查询
    """
    # 将分组结构扁平化为单层查询列表并编号
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

    # 查询数 ≤ 2 时无需 LLM 选择，直接返回全部
    if len(query_list) <= 2:
        return query_list

    # 构建查询索引文本供 LLM 参考
    query_index = ""
    for i, q in enumerate(query_list):
        kws = ", ".join(q.get("keywords", [])) or q["label"]
        query_index += f"[{i}] {q['group']}/{q['label']} 关键词: {kws}\n"

    # 构造选择 prompt，要求 LLM 返回 JSON 数组格式的编号列表
    selection_prompt = f"""用户提问: "{user_query}"

可选SQL查询列表:
{query_index}

请根据用户提问选择相关的查询编号, 返回JSON数组格式: [0, 2, 5] (只包含编号, 不要其他文字)
如果用户问得宽泛则多选, 问得具体则少选。最少选1条。"""

    answer = await _adapted_llm_call(selection_prompt, llm_call_fn)
    try:
        # 从 LLM 返回中提取所有数字，过滤出有效的查询编号
        matches = re.findall(r'\d+', answer)
        indices = [int(m) for m in matches if 0 <= int(m) < len(query_list)]
        if not indices:
            return query_list
        return [query_list[i] for i in indices]
    except Exception:
        # 任何解析异常都回退返回全部查询
        return query_list


async def run_stream(user_query: str, database_id: str, llm_call_fn, need_conclusion: bool = True):
    """制空权分析 — 异步流式生成器

    该函数是制空权分析的主入口，以异步生成器形式逐步 yield SSE 事件。
    工作流程：
      1. 加载 air_queries.json 中的预配置SQL模板和区域规则
      2. 从用户提问中通过正则提取目标区域名称
      3. LLM 选择相关查询维度
      4. 将区域名称注入 SQL 占位符，逐条执行查询
      5. 通过 LLM 生成各维度分析及综合红蓝对比评估

    Args:
        user_query: 用户的自然语言提问
        database_id: 目标数据库标识符，传递给 execute_sql_on_database
        llm_call_fn: 异步 LLM 调用函数，签名为 async (system, user) -> str
        need_conclusion: True=执行SQL+LLM生成结论; False=仅执行SQL返回数据（不调用LLM分析）

    Yields:
        dict: SSE 事件字典
            - type="step": 进度步骤事件，含 step/description/status/detail/thinking/progress
            - type="result": 最终结果事件，含 type/region/final_answer/results 等字段
    """
    # 加载配置文件，包含区域规则和查询分组
    config = load_air_queries()
    region_rules = config.get("regionRules", {})
    groups = config.get("groups", [])
    placeholder = region_rules.get("placeholder", "{region}")

    # 配置文件中无查询分组时，直接返回完成事件并终止
    if not groups:
        yield _step_event(4, "制空权分析", "completed",
                         detail="未找到SQL配置, 请检查 config/air_queries.json", progress=100,
                         thinking="制空权分析智能体已加载，但 air_queries.json 为空或未找到")
        return

    # 在 workflow 中作为子步骤，step_base 固定为 4
    step_base = 4

    # 开始分析：向用户展示初始进度
    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail="正在识别目标区域...", progress=5,
                     thinking="【制空权分析智能体】\n从用户提问中提取区域信息，匹配预配置的SQL模板")

    await asyncio.sleep(_YIELD_DELAY)

    # 步骤1: 从用户提问中通过正则提取目标区域名称
    region = extract_region(user_query, region_rules)

    # 告知用户区域识别结果
    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail=f"已识别区域: {region}", progress=10,
                     thinking=f"提取到区域: {region}\n区域规则: {json.dumps(region_rules, ensure_ascii=False)[:300]}")

    await asyncio.sleep(_YIELD_DELAY)

    # 步骤2: 通过 LLM 选择与用户提问最相关的查询维度
    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail="正在匹配分析维度...", progress=15,
                     thinking="根据用户提问从 air_queries.json 中选择相关分析维度")

    await asyncio.sleep(_YIELD_DELAY)

    selected = await _select_queries_by_llm(user_query, groups, llm_call_fn)
    total = len(selected)

    # 告知用户查询选择结果
    mode_label = "查询+结论" if need_conclusion else "仅查询数据"
    yield _step_event(step_base, "制空权分析", "in_progress",
                     detail=f"已选定 {total} 条相关查询, 区域 [{region}], 模式: {mode_label}", progress=20,
                     thinking=f"选中 {total} 条查询, 区域={region}: " + ", ".join(q["label"] for q in selected))

    await asyncio.sleep(_YIELD_DELAY)

    # 步骤3: 逐条执行选定查询，注入区域参数后执行 SQL
    all_results = []
    all_summaries = []
    executed = 0  # 已执行查询计数，用于进度计算

    for q in selected:
        label = q["label"]
        sql = q.get("sql", "")
        group_name = q.get("group", "")

        # 将区域名称注入 SQL 模板中的占位符（默认 {region}）
        sql = inject_region(sql, region, placeholder)

        # 推送当前查询的执行进度
        yield _step_event(step_base, "制空权分析", "in_progress",
                         detail=f"正在查询: {label} (区域: {region})",
                         progress=int(20 + 60 * executed / max(total, 1)),
                         thinking=f"【执行SQL - {group_name}/{label}】\n区域={region}\n{sql[:400]}")

        await asyncio.sleep(_YIELD_DELAY)

        # 在目标数据库上执行已注入区域参数的 SQL 查询
        exec_result = execute_sql_on_database(database_id, sql)
        executed += 1

        insight = ""
        # 查询成功且有数据时，根据 need_conclusion 决定是否调用 LLM 生成分析
        if exec_result.get("success") and exec_result.get("rowCount", 0) > 0:
            columns = exec_result.get("columns", [])
            rows = exec_result.get("rows", [])

            if need_conclusion:
                # 需要结论模式：推送 LLM 分析进度
                yield _step_event(step_base, "制空权分析", "in_progress",
                                 detail=f"正在分析: {label} ({exec_result.get('rowCount')}条)",
                                 progress=int(20 + 60 * executed / max(total, 1)),
                                 thinking=f"查询 [{label}] 返回 {len(rows)} 行, 正在调用LLM分析...")

                await asyncio.sleep(_YIELD_DELAY)

                # 构造制空权逐条分析的 prompt，强调红蓝双方对比视角
                insight_prompt = f"""请基于以下制空权分析数据做简要分析(100字以内):
分析维度: {group_name} - {label}
区域: {region}
列: {columns}
数据: {str(rows[:10])}
总行数: {len(rows)}

请给出1-2句关键发现，重点关注红蓝双方对比。"""
                insight = await _adapted_llm_call(insight_prompt, llm_call_fn)
            else:
                # 仅数据模式：跳过 LLM 分析，直接报告查询完成
                yield _step_event(step_base, "制空权分析", "in_progress",
                                 detail=f"已查询: {label} ({exec_result.get('rowCount')}条)",
                                 progress=int(20 + 60 * executed / max(total, 1)),
                                 thinking=f"查询 [{label}] 返回 {len(rows)} 行 (仅数据模式，跳过LLM分析)")
                await asyncio.sleep(_YIELD_DELAY)
        else:
            # 查询失败或无数据时，使用错误消息作为 insight
            insight = exec_result.get("message", "查询无数据")

        # 将本条查询的完整结果追加到汇总列表
        all_results.append({
            "group": group_name,
            "label": label,
            "sql": sql,
            "columns": exec_result.get("columns", []),
            "rows": exec_result.get("rows", []),
            "rowCount": exec_result.get("rowCount", 0),
            "insight": insight
        })
        # 仅在有内容时才加入摘要列表（用于后续综合评估）
        if insight:
            all_summaries.append(f"[{group_name}-{label}]: {insight}")

        await asyncio.sleep(_YIELD_DELAY)

    # 步骤4: 综合评估（仅 need_conclusion=True 时生成）
    summary = ""
    if need_conclusion:
        # 推送综合评估进度
        yield _step_event(step_base, "制空权分析", "in_progress",
                         detail="正在生成制空权综合评估总结...", progress=85,
                         thinking="所有查询执行完毕，正在汇总LLM分析...")

        await asyncio.sleep(_YIELD_DELAY)

        # 拼接所有维度的分析摘要，调用 LLM 生成制空权综合评估
        if all_summaries:
            summary_prompt = f"""请基于以下各维度的制空权分析数据，给出{region}区域的制空权综合评估总结(100字以内):

用户提问: {user_query}
分析区域: {region}

各维度分析结果:
{chr(10).join(all_summaries)}

请简明给出红蓝双方制空权对比结论。"""
            summary = await _adapted_llm_call(summary_prompt, llm_call_fn)
        else:
            # 没有任何有效数据时的兜底文案，包含区域信息
            summary = f"暂无{region}区域的有效制空权数据可供评估"

        # 推送制空权分析完成事件
        yield _step_event(step_base, "制空权分析", "completed",
                         detail="制空权分析完成", progress=100,
                         thinking=f"【制空权综合评估 — {region}】\n{summary[:800]}")
    else:
        # 仅数据模式：推送完成事件，不包含 LLM 生成的结论
        yield _step_event(step_base, "制空权分析", "completed",
                         detail=f"制空权查询完成（仅数据模式），共 {len(all_results)} 条查询结果", progress=100,
                         thinking="用户未要求结论，仅返回查询数据")

    # 构造并推送最终结果事件 — 统一 results 字段名
    final = {
        "type": "result",
        "result": {
            "type": "air_superiority",
            "region": region,
            "final_answer": summary,
            "results": all_results,
            "need_conclusion": need_conclusion,
            "generatedSql": None,
            "rawResults": [],
            "totalRows": sum(r.get("rowCount", 0) for r in all_results),
        }
    }
    yield final
