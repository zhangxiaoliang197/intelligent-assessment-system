"""AI 构建聊天 Agent 的 Prompt 构造。

纯函数模块，只负责拼接 LLM messages，不直接操作 BuildJob 持久化。
任务状态摘要从 BuildJob 对象读取当前状态，保证「下拉面板 / 图谱 / LLM 上下文」同源。

设计原则：
- 意图识别输出严格 JSON；回复输出纯自然语言
- 每轮 LLM 都注入当前任务状态摘要，让 LLM 知道「构建到哪、已有哪些本体/实体」
- 闲聊/偏离构建由系统提示词约束，礼貌拉回构建任务
"""
import config

STAGE_NAMES = {
    -1: "空闲",
    0: "文档解析",
    1: "实体类型提取",
    2: "实体+关系提取",
    3: "验证",
    4: "已完成",
}

# 意图集合（与 orchestrator.INTENT_OPTIONS 保持一致）
INTENT_DESC = (
    "- parse：需要解析/重新解析文档\n"
    "- extract_type：需要提取/重新提取实体类型（类型层）\n"
    "- extract_entity：需要提取/重新提取实体（实例层）\n"
    "- verify：需要执行验证/生成报告\n"
    "- complete：确认完成构建、生成正式本体\n"
    "- edit：需要修改/编辑某个实体类型、实体或关系\n"
    "- chat：闲聊、询问进度、咨询说明等非构建操作\n"
)


def build_state_summary(job) -> str:
    """从 BuildJob 构造当前任务状态摘要文本（注入 LLM 上下文）。"""
    parts = []
    stage = STAGE_NAMES.get(job.running_step, "未知")
    parts.append(f"当前阶段：{stage}（running_step={job.running_step}）")

    confirmed = []
    confirmed.append(f"文档解析{'已' if job.meta_confirmed else '未'}确认")
    confirmed.append(f"实体类型{'已' if job.step1_confirmed else '未'}确认")
    confirmed.append(f"实体+关系{'已' if job.step2_confirmed else '未'}确认")
    confirmed.append(f"验证{'已' if job.step3_confirmed else '未'}确认")
    parts.append("确认状态：" + "，".join(confirmed))

    # 文档内容：已上传则注入全文（LLM 解析和提取的基础）
    if job.source_text:
        source_preview = job.source_text[:3000]
        suffix = "（已截断，仅展示前3000字符）" if len(job.source_text) > 3000 else ""
        parts.append(
            f"已上传文档「{job.source_filename}」({job.char_count}字符)：\n"
            f"---文档内容开始---\n{source_preview}{suffix}\n---文档内容结束---"
        )
    else:
        parts.append("尚未上传文档，默认走闲聊流程")

    ets = job.step1_entity_types or job.step1_concepts or []
    if ets:
        names = [e.get("name", "") for e in ets if isinstance(e, dict) and e.get("name")]
        shown = "、".join(names[:30])
        suffix = "..." if len(names) > 30 else ""
        parts.append(f"已提取实体类型（{len(ets)}个）：{shown}{suffix}")

    ents = job.step2_entities or []
    if ents:
        enames = [e.get("name", "") for e in ents if isinstance(e, dict) and e.get("name")]
        eshown = "、".join(enames[:40])
        esuffix = "..." if len(enames) > 40 else ""
        parts.append(f"已提取实体（{len(ents)}个）：{eshown}{esuffix}")

    rels = job.step3_relations or job.step2_relations or []
    if rels:
        rtups = [
            f"{r.get('source', '')}→{r.get('target', '')}({r.get('relation_type', '')})"
            for r in rels if isinstance(r, dict)
        ]
        rshown = "；".join(rtups[:60])
        rsuffix = "..." if len(rtups) > 60 else ""
        parts.append(f"已提取关系（{len(rels)}条）：{rshown}{rsuffix}")

    ver = job.step3_verification or job.step4_verification
    if ver:
        parts.append(
            f"验证结果：通过 {ver.get('verified_count', '?')} 项，"
            f"存疑 {ver.get('suspect_count', '?')} 项"
        )
        suspects = ver.get("suspects") or []
        if suspects:
            slines = []
            for s in suspects:
                if isinstance(s, dict):
                    slines.append(
                        f"- [{s.get('item_type', '')}] {s.get('item_name', '')}：{s.get('reason', '')}"
                    )
            if slines:
                parts.append("存疑条目明细：\n" + "\n".join(slines))

    if job.ontology_id:
        parts.append(f"已生成正式本体：{job.ontology_id}")

    return "\n".join(parts)


def _format_history(history, keep=None) -> str:
    """将聊天历史列表转为紧凑文本（仅取 role + content，保留最近 keep 轮原文）。

    keep 为保留的轮数（1 轮 = user + assistant 两条）；默认取 config.CHAT_HISTORY_KEEP_RECENT。
    """
    if not history:
        return ""
    if keep is None:
        keep = config.CHAT_HISTORY_KEEP_RECENT
    lines = []
    for m in history[-keep * 2:]:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:200]}")
    return "\n".join(lines)


def build_context_history(history, history_summary="", keep_recent=None) -> str:
    """组合「历史摘要 + 最近 keep_recent 轮原文」作为统一对话上下文。

    供意图识别、回复生成、编辑解析共用，保证四处同源。
    """
    if keep_recent is None:
        keep_recent = config.CHAT_HISTORY_KEEP_RECENT
    recent = _format_history(history, keep_recent)
    if history_summary:
        return f"【历史摘要】\n{history_summary}\n\n【最近对话】\n{recent or '（无）'}"
    return recent or "（无）"


def build_intent_messages(job, history, user_message) -> list:
    """构造意图识别的 messages（输出 JSON，intent 字段）。"""
    system = (
        "你是本体构建任务的意图识别器。根据用户输入和当前构建状态，判断用户意图。\n"
        "只返回 JSON，不要任何解释或 markdown。\n\n"
        "关键规则（按优先级）：\n"
        "- 如果「当前构建任务状态」中有已上传文档且文档解析未确认，"
        "用户说「构建本体」「开始构建」「提取本体」「重新解析」等，意图应为 parse\n"
        "- 如果文档已上传并解析出内容（状态中有「已上传文档」）但实体类型尚未提取或未确认，"
        "用户说「确认」「没问题」「继续」「可以」「好的」「开始提取」等肯定性表述，意图应为 extract_type\n"
        "- 如果实体类型已提取（step1_entity_types 非空）但尚未确认（step1_confirmed=False），"
        "用户说「确认」「没问题」「继续」「可以」「好的」「开始提取实体」等肯定性表述，意图应为 extract_entity\n"
        "- 如果实体类型已确认但实体未确认，意图应为 extract_entity\n"
        "- 如果实体已确认但验证未做，用户说「确认」「继续」「验证」等，意图应为 verify\n"
        "- 如果验证已完成（有验证结果）但未确认，用户说「完成」「完成构建」「接受存疑完成构建」「收尾」等，意图应为 complete\n"
        "- 如果所有阶段确认完毕，用户说「完成」「生成」「确认完成」等，意图应为 complete\n"
        "- 如果构建任务完全未开始且无文档，意图应为 chat\n"
        "- 如果用户说「修改」「编辑」「删除」「增加」等，意图应为 edit"
    )
    state = build_state_summary(job)
    history_text = build_context_history(history, getattr(job, "history_summary", ""))
    user = (
        f"当前构建任务状态：\n{state}\n\n"
        f"最近对话：\n{history_text or '（无）'}\n\n"
        f"用户最新输入：{user_message}\n\n"
        f"请判断意图，返回 JSON："
        f'{{"intent": "parse|extract_type|extract_entity|verify|complete|edit|chat", '
        f'"summary": "一句话说明要做的事"}}\n\n'
        f"意图说明：\n{INTENT_DESC}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_reply_messages(job, history, user_message, tool_summary) -> list:
    """构造自然语言回复的 messages（输出纯文本）。"""
    system = (
        "你是本体构建助手，通过对话引导用户完成本体构建。\n"
        "请用自然、简洁的中文回复，说明刚才做了什么和下一步建议。\n"
        "不要在回复中提及进度百分比（如「整体进度为20%」），进度由前端界面展示。\n"
        "必须严格依据「刚才执行的操作结果」如实说明：若结果是拒绝/提示（如「请先…」「实体清单为空」），"
        "应如实转述该提示，不得自行宣称已进入验证、已生成本体或已完成某阶段。\n"
        "严禁照搬最近对话中旧回复的话术：每轮回复只描述本轮「刚才执行的操作结果」对应的动作，"
        "并明确说出本轮启动的是哪个阶段（如「实体+关系提取」不能说成「实体类型提取」，二者是不同阶段）；"
        "若操作结果包含「已确认某阶段清单」，回复需先说明确认了什么、再说明启动了什么。\n"
        "只输出自然语言，不要输出 JSON 或 markdown 标记。\n"
        "若用户闲聊或偏离构建，礼貌地拉回构建任务。"
    )
    state = build_state_summary(job)
    history_text = build_context_history(history, getattr(job, "history_summary", ""))
    user = (
        f"当前构建任务状态：\n{state}\n\n"
        f"最近对话：\n{history_text or '（无）'}\n\n"
        f"用户输入：{user_message}\n\n"
        f"刚才执行的操作结果：{tool_summary or '（无）'}\n\n"
        f"请给出自然语言回复（简洁，说明结果 + 下一步建议，不要提进度百分比）。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_stage_done_messages(job, stage: int, result_summary: str, next_hint: str) -> list:
    """构造后台任务完成后的引导回复 messages（输出纯文本）。

    后台任务收尾时调用：告知用户刚完成的阶段与结果（当前状态），
    并引导下一步。结果数量以 result_summary 为准，禁止编造。
    """
    stage_name = STAGE_NAMES.get(stage, "处理")
    system = (
        "你是本体构建助手。后台刚完成（或失败）一个构建阶段，请告知用户当前状态并引导下一步。\n"
        "用自然、简洁的中文回复，结构为两部分：\n"
        "1) 说明刚完成的阶段与结果：数量、规模必须严格依据给定的「完成结果摘要」和任务状态，不得编造\n"
        "2) 给出下一步建议：依据给定的「下一步提示」，明确告诉用户可以怎么说/怎么做\n"
        "不要提及进度百分比；不要照搬历史话术；只输出自然语言，不要 JSON 或 markdown 标记。"
    )
    state = build_state_summary(job)
    user = (
        f"当前构建任务状态：\n{state}\n\n"
        f"刚结束的阶段：{stage_name}\n"
        f"完成结果摘要：{result_summary}\n"
        f"下一步提示：{next_hint}\n\n"
        f"请生成告知回复（当前状态 + 下一步建议）。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_history_summary_messages(older_history, old_summary="") -> list:
    """构造聊天历史滚动摘要的 messages（输出纯文本摘要，支持增量合并）。

    older_history 为本次需要被压缩的较早消息；old_summary 为已有的历史摘要，
    非空时与 older_history 合并生成新的滚动摘要，避免早期信息丢失。
    """
    older_text = _format_history(older_history, keep=(len(older_history) + 1) // 2)
    system = (
        "你是对话摘要助手。请将本体构建对话历史压缩为一段简洁摘要，"
        "保留关键决策、已提取的本体/实体概况和未完成事项。只输出摘要文本。"
    )
    if old_summary:
        user = (
            f"已有历史摘要：\n{old_summary}\n\n"
            f"新增对话片段：\n{older_text}\n\n"
            f"请将两者合并为一份新的滚动摘要（自然语言，300字以内）。"
        )
    else:
        user = f"对话历史：\n{older_text}\n\n请输出摘要（自然语言，300字以内）。"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
