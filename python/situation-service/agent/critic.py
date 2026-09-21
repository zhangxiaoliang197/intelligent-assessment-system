"""Critic —— VERIFY 阶段视觉反思决策层。

设计目标（参见方案文档 §3.3.2）：
- 一个 LLM tool：emit_review_decision，输出**定性编辑指令**而非数值/option 字段
- 五类指令：replace_type / drop_chart / add_chart / replace_map_layer / accept
- Critic 只看截图 + 失败原因 + sub_questions 摘要 + allowed_types，不看完整 option JSON
  （避免 LLM 抄数值，对齐 METAL / See-it-Say-it-Sorted 的 qualitative-edits 模式）
- 截图缺失时降级为纯文本信号决策（chart type + title + verify 失败原因）
- LLM 调用失败返回 _fallback=True，由 orchestrator 回退到原 rewrite_ids 路径

对齐业界实践：
- METAL (arxiv 2502.17651)：Critic 提定性编辑，Actor 据此修订
- See it. Say it. Sorted. (arxiv 2508.15222)：qualitative edits over brittle numbers
- ReLook Forced Optimization：仅接受严格提升的修订
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import config
from llm_client import call_llm_with_tools

logger = logging.getLogger("situation-service")


# ──────────────────────────────────────────────────────────────────
# Critic 输出工具 schema（emit_review_decision）
# 与 Planner.emit_research_plan 风格对齐：LLM 唯一被允许调用的工具
# ──────────────────────────────────────────────────────────────────

EMIT_REVIEW_DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_review_decision",
        "description": (
            "提交对当前 chart 产物集的视觉反思决策。仅输出定性编辑指令与理由，"
            "不要输出数值/坐标/具体 option 字段——这些由 Writer 重新生成。"
            "空 actions 数组表示接受当前产物，不再迭代。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["actions"],
            "properties": {
                "actions": {
                    "type": "array",
                    "description": (
                        "编辑指令列表。每项对应一个 chart 的修订决策。"
                        "replace_type=换图表类型；drop_chart=丢弃该图（达到数量下限时慎用）；"
                        "add_chart=补一张图（必须命中已有 subQuestionRef）；"
                        "replace_map_layer=调整地图图层类型；accept=接受该图（占位）。"
                    ),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "reason"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "replace_type",
                                    "drop_chart",
                                    "add_chart",
                                    "replace_map_layer",
                                    "accept",
                                ],
                                "description": "编辑指令类型",
                            },
                            "targetChartId": {
                                "type": "string",
                                "description": (
                                    "目标 chartId。replace_type / drop_chart / replace_map_layer 必填；"
                                    "add_chart / accept 留空"
                                ),
                            },
                            "newType": {
                                "type": "string",
                                "enum": ["bar", "line", "pie", "radar", "scatter"],
                                "description": "新图表类型（replace_type / add_chart 必填）",
                            },
                            "newLayerType": {
                                "type": "string",
                                "enum": ["points", "routes", "areas", "circles"],
                                "description": "新地图图层类型（replace_map_layer 必填）",
                            },
                            "newSubQuestionRef": {
                                "type": "string",
                                "description": (
                                    "add_chart 时必须命中已有 subQuestions[*].id；"
                                    "其他指令留空"
                                ),
                            },
                            "rationale": {
                                "type": "string",
                                "description": "本指令的视觉/数据理由（中文，<=80 字）",
                            },
                            "reason": {
                                "type": "string",
                                "description": "简短理由（与 rationale 等价，向后兼容字段）",
                            },
                        },
                    },
                },
            },
        },
    },
}


# Critic 系统提示词
_CRITIC_SYSTEM_PROMPT = """【当前阶段：视觉反思（Critic Agent）】

你是态势图产物的视觉反思专家。下方给出了当前已生成的 chart 产物清单、
对应的渲染截图（如有）、规则校验失败原因、当前 chartSpecs 的类型分布、
以及可用的子问题列表（add_chart 时必须命中其 id）。

请基于以下原则做决策：

1. 看截图判断每张图的可读性：
   - 标签是否重叠？图例是否缺失？配色是否区分度不足？
   - 数据是否过于稀疏/密集，导致当前 type 不合适？
2. 规则失败原因优先级最高：
   - 若 verify 报 "pie 图分类数 12 > 8" → replace_type 为 bar
   - 若 verify 报 "scatter 点数 3 < 5" → replace_type 为 bar 或 line
   - 若 verify 报 "radar 维度 2 < 3" → drop_chart 或 replace_type 为 bar
3. 数量硬约束：修订后 chartSpecs 总数必须 ∈ [2, 4]：
   - 当前 4 张时禁止 add_chart；当前 2 张时 drop_chart 必须同时 add_chart 补位
4. add_chart.newSubQuestionRef 必须从下方"可用子问题"中选取，禁止编造
5. 仅提定性编辑指令，**不要输出数值/坐标/option 字段**——这些由 Writer 重新生成
6. 接受当前产物（无需修订）时返回空 actions 数组

直接调用 emit_review_decision 工具提交决策，不要输出额外文本。"""


def _format_charts_summary(charts: List[Dict[str, Any]]) -> str:
    """格式化 chart 产物清单为文本摘要（不含 option 数值）。"""
    lines: List[str] = []
    for c in charts or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("chartId") or "")
        ctype = str(c.get("type") or "").lower()
        title = str(c.get("title") or "")
        lines.append(f"- chartId={cid} type={ctype} title={title!r}")
    return "\n".join(lines) or "（无）"


def _format_verify_failures(failures: List[Dict[str, Any]]) -> str:
    """格式化 verify 失败原因（chartId + stage + reason）。"""
    if not failures:
        return "（无失败项，规则全部通过）"
    lines: List[str] = []
    for f in failures:
        if not isinstance(f, dict):
            continue
        cid = str(f.get("chartId") or "")
        stage = str(f.get("stage") or "")
        reason = str(f.get("reason") or "")[:100]
        lines.append(f"- chartId={cid} stage={stage} reason={reason}")
    return "\n".join(lines)


def _format_sub_questions(sub_questions: List[Dict[str, Any]]) -> str:
    """格式化可用子问题列表（id + question 简述）。"""
    lines: List[str] = []
    for q in sub_questions or []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "")
        question = str(q.get("question") or "")[:60]
        lines.append(f"- id={qid} question={question!r}")
    return "\n".join(lines) or "（无）"


class Critic:
    """视觉反思决策者：基于 chart 截图 + verify 失败原因输出定性编辑指令。

    使用示例（orchestrator 集成）：
        critic = Critic(profile, meta)
        screenshots = await chart_screenshot.render_chart_pngs(charts)
        review = await critic.review(
            charts=charts,
            screenshots=screenshots,
            verify_failures=verify_result.get("chart_result", {}).get("failures", []),
            sub_questions=plan.get("subQuestions") or [],
        )
        if review.get("_fallback"):
            # 回退到原 rewrite_ids 路径
            ...
        else:
            new_chart_specs, new_map_specs, errs = critic_translator.apply_actions(
                chart_specs, map_specs, sub_questions,
                review.get("actions") or [], profile, meta,
            )
    """

    def __init__(self, profile: Dict[str, Any], meta: Dict[str, Any]):
        self.profile = profile
        self.meta = meta

    def _build_messages(
        self,
        charts: List[Dict[str, Any]],
        screenshots: List[Tuple[str, Optional[str]]],
        verify_failures: List[Dict[str, Any]],
        sub_questions: List[Dict[str, Any]],
        allowed_types: List[str],
    ) -> List[Dict[str, Any]]:
        """构建 system + user 消息，含可选多模态图片。"""
        charts_summary = _format_charts_summary(charts)
        failures_text = _format_verify_failures(verify_failures)
        sub_q_text = _format_sub_questions(sub_questions)

        text_part = (
            f"当前 chart 产物清单：\n{charts_summary}\n\n"
            f"规则校验失败原因：\n{failures_text}\n\n"
            f"可用子问题（add_chart 必须命中其 id）：\n{sub_q_text}\n\n"
            f"允许的图表类型：{allowed_types}\n\n"
            "请基于截图（若有）与失败原因，调用 emit_review_decision 提交编辑指令。"
        )

        # 多模态：若截图存在，user content 用数组（text + image_url）
        # 若所有截图缺失，退化为纯文本（仍走 tool-call 协议）
        valid_screenshots = [
            (cid, b64) for cid, b64 in screenshots if b64
        ]
        if valid_screenshots:
            content: List[Dict[str, Any]] = [{"type": "text", "text": text_part}]
            for cid, b64 in valid_screenshots:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            user_msg = {"role": "user", "content": content}
        else:
            user_msg = {"role": "user", "content": text_part}

        return [
            {"role": "system", "content": _CRITIC_SYSTEM_PROMPT},
            user_msg,
        ]

    async def review(
        self,
        charts: List[Dict[str, Any]],
        screenshots: List[Tuple[str, Optional[str]]],
        verify_failures: List[Dict[str, Any]],
        sub_questions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """调用 LLM 产出编辑指令集合。

        Args:
            charts: 当前 chart 产物列表（含 chartId / type / title / option）
            screenshots: chart_screenshot.render_chart_pngs 的返回值
            verify_failures: verifier.verify_charts 返回的 failures 列表
            sub_questions: Planner 输出的子问题列表（add_chart 引用其 id）

        Returns:
            {"actions": [...], "_fallback": False} 成功
            {"actions": [], "_fallback": True, "_error": str} 失败（调用方应回退）
        """
        # 从 profile 推断 allowed_types（与 planner._allowed_chart_types 同口径）
        from agent.planner import _allowed_chart_types
        allowed_types = sorted(_allowed_chart_types(self.profile))

        messages = self._build_messages(
            charts, screenshots, verify_failures, sub_questions, allowed_types,
        )

        max_attempts = 2  # 1 + 1 retry
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            try:
                result = call_llm_with_tools(
                    messages=messages,
                    tools=[EMIT_REVIEW_DECISION_TOOL],
                    tool_choice={
                        "type": "function",
                        "function": {"name": "emit_review_decision"},
                    },
                    temperature=0.2,
                    max_tokens=min(config.LLM_MAX_TOKENS, 4000),
                )
                tool_calls = result.get("tool_calls") or []
                if not tool_calls:
                    last_error = "LLM 未返回 tool_calls"
                    logger.warning("Critic 第 %s 次未返回 tool_calls: %s", attempt, last_error)
                    continue

                # 取第一个 emit_review_decision 调用
                plan_args = None
                for tc in tool_calls:
                    if tc.get("name") == "emit_review_decision":
                        plan_args = tc.get("arguments")
                        break
                if not isinstance(plan_args, dict):
                    last_error = "emit_review_decision.arguments 解析为空"
                    logger.warning("Critic 第 %s 次 arguments 为空", attempt)
                    continue

                actions = plan_args.get("actions")
                if not isinstance(actions, list):
                    last_error = "actions 不是数组"
                    logger.warning("Critic 第 %s 次 actions 非数组", attempt)
                    continue

                logger.info(
                    "Critic 成功（第 %s 次）：actions=%s",
                    attempt,
                    [str(a.get("type") or "") for a in actions],
                )
                return {"actions": actions, "_fallback": False}

            except Exception as exc:
                last_error = str(exc)[:200]
                logger.warning("Critic 第 %s 次异常: %s", attempt, last_error)
                continue

        # 重试用尽 → 降级
        logger.warning("Critic %s 次均失败，回退 rewrite_ids。最后错误: %s",
                       max_attempts, last_error)
        return {"actions": [], "_fallback": True, "_error": last_error}


__all__ = ["Critic", "EMIT_REVIEW_DECISION_TOOL"]
