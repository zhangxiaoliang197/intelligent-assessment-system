"""AI 构建聊天 Agent 的 LLM 编排层。

复用 llm_client 的 call_llm / call_llm_json 与 config 的 get_chat_llm_params，
负责：意图分类、自然语言回复生成、聊天历史滚动摘要。

不直接操作 BuildJob 持久化（job 状态更新由 main.py 编排层负责），
本模块保持纯 LLM 编排职责，避免与 main.py 循环导入。
"""
import logging

from llm_client import call_llm, call_llm_json
import config
from agent import prompts

logger = logging.getLogger("ontology-service")

# 合法意图集合（与 prompts.INTENT_DESC 保持一致）
INTENT_OPTIONS = [
    "parse", "extract_type", "extract_entity", "verify", "complete", "edit", "chat",
]

# 编辑类动词硬匹配：用户明确要增删改时，无论当前阶段/确认状态如何，都应识别为 edit，
# 保证「随时可删、随时可改」。放在 LLM 分类之前，避免阶段状态干扰判断。
EDIT_KEYWORDS = (
    "删除", "删掉", "移除", "去掉", "不要这条", "去掉这条",
    "修改", "改成", "改为", "编辑", "改名", "重命名", "更新",
    "新增", "添加", "加上", "增加", "补充",
)


def classify_intent(job, history, user_message) -> dict:
    """识别用户输入意图，返回 {"intent", "summary"}。

    编辑动词硬匹配优先：命中删除/修改/新增等词直接判为 edit（不经过 LLM，
    避免因阶段未确认而被误判为 chat/verify）。否则用 plan 档小参数调用 LLM，
    失败时回退 chat（不阻塞对话）。
    """
    # 编辑意图硬匹配（最高优先级，保证「随时可删/改」）
    if any(kw in user_message for kw in EDIT_KEYWORDS):
        return {"intent": "edit", "summary": user_message}

    messages = prompts.build_intent_messages(job, history, user_message)
    max_tokens, thinking = config.get_chat_llm_params("plan")
    try:
        data = call_llm_json(messages, temperature=0.2, max_tokens=max_tokens, thinking_type=thinking)
    except Exception as e:
        logger.warning(f"意图分类失败，回退 chat: {e}")
        return {"intent": "chat", "summary": user_message}

    intent = str(data.get("intent", "chat")).strip().lower()
    if intent not in INTENT_OPTIONS:
        intent = "chat"
    return {"intent": intent, "summary": data.get("summary", "")}


def generate_reply(job, history, user_message, tool_summary) -> str:
    """根据工具执行结果生成自然语言回复（纯文本）。"""
    messages = prompts.build_reply_messages(job, history, user_message, tool_summary)
    max_tokens, thinking = config.get_chat_llm_params("chat")
    return call_llm(messages, temperature=0.5, max_tokens=max_tokens, thinking_type=thinking)


def summarize_history(older_history, old_summary="") -> str:
    """对较早聊天历史生成滚动摘要（纯文本），支持与旧摘要增量合并。

    older_history 为本次需要压缩的较早消息；old_summary 为已有历史摘要。
    失败返回空串，由调用方决定是否保留旧摘要兜底。
    """
    messages = prompts.build_history_summary_messages(older_history, old_summary)
    max_tokens, thinking = config.get_chat_llm_params("chat")
    try:
        return call_llm(messages, temperature=0.3, max_tokens=max_tokens, thinking_type=thinking)
    except Exception as e:
        logger.warning(f"聊天历史摘要生成失败: {e}")
        return ""
