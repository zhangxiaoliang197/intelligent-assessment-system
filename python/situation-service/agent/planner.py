"""Planner Agent —— 规划层（态势图 Agent 架构重构 v1.1 阶段 1）。

设计目标（参见方案文档 §4.2.1）：
- 用原生 function-calling（tools 协议）替代 JSON 协议，消除解析兜底
- 输出结构化 ResearchPlan：subQuestions / chartSpecs / mapSpecs / narrativeOutline
- 硬约束：subQuestions ≥ 1、chartSpecs ≥ 2（满足"至少 2 图"）
- 降级：调用失败最多重试 2 次（共 3 次）；仍失败则回退 Skill executionPlan 模板

阶段 1 仅提供独立 Planner 类，不动 orchestrator.real_generate；
阶段 2 集成时由新 Orchestrator 调用 Planner.plan()。
"""
import logging
from typing import Any, Dict, List, Optional

from llm_client import call_llm_with_tools
from agent import prompts
import config

logger = logging.getLogger("situation-service")


# ──────────────────────────────────────────────────────────────────
# Planner 输出工具 schema（emit_research_plan）
# 这是 LLM 唯一被允许调用的工具，强制其按结构化 schema 返回规划结果。
# ──────────────────────────────────────────────────────────────────

EMIT_RESEARCH_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_research_plan",
        "description": (
            "提交本次态势图的研究计划。先做意图识别（intent）：仅当属于态势分析需求时才"
            "规划子问题与图表；非态势需求时 subQuestions/chartSpecs/mapSpecs 留空数组并给出 directAnswer。"
            "子问题用于驱动并行数据采集；图表/地图规格用于驱动并行产图；"
            "narrativeOutline 用于指导最后的文本撰写（介绍 + 逐图说明）。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["intent", "subQuestions", "chartSpecs"],
            "properties": {
                "subQuestions": {
                    "type": "array",
                    "description": "研究子问题列表，每个子问题对应一次并行数据采集（intent=situation 时至少 1 个；intent=general 时为空数组）",
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "question", "datasetId"],
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "子问题唯一 ID，如 q1/q2",
                            },
                            "question": {
                                "type": "string",
                                "description": "子问题自然语言描述，需聚焦可量化的事实",
                            },
                            "datasetId": {
                                "type": "string",
                                "description": "要查询的数据集 ID，必须来自上下文给出的可用数据集",
                            },
                            "filters": {
                                "type": "object",
                                "description": "可选：WHERE 过滤条件，key=字段名 value=匹配值或区间",
                            },
                            "aggregation": {
                                "type": "string",
                                "description": "可选：聚合方式，如 sum/avg/count/monthly_sum",
                            },
                        },
                    },
                },
                "chartSpecs": {
                    "type": "array",
                    "description": (
                        "图表规格列表。intent=situation 时数量 2-4 个；intent=general 时为空数组。"
                        "尽量避免 type 重复（除非两个 line 各展示不同维度且必要），"
                        "选型必须匹配数据特征：pie 分类数 ≤ 8、radar 维度 3-12、line 至少 2 个 X 轴点。"
                    ),
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "type", "title", "subQuestionRef"],
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "图表 ID，如 c1/c2",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["bar", "line", "pie", "radar", "scatter"],
                                "description": "图表类型，允许重复",
                            },
                            "title": {
                                "type": "string",
                                "description": "图表标题，应聚焦问题核心",
                            },
                            "subQuestionRef": {
                                "type": "string",
                                "description": "引用的子问题 ID（必须命中 subQuestions[*].id）",
                            },
                            "intent": {
                                "type": "string",
                                "description": "可选：这张图想说明什么",
                            },
                        },
                    },
                },
                "mapSpecs": {
                    "type": "array",
                    "description": "地图图层规格列表。若数据集无地理坐标字段可为空数组",
                    "maxItems": 2,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "subQuestionRef"],
                        "properties": {
                            "id": {"type": "string", "description": "图层 ID，如 m1"},
                            "subQuestionRef": {
                                "type": "string",
                                "description": "引用的子问题 ID",
                            },
                            "layerType": {
                                "type": "string",
                                "enum": ["points", "routes", "areas", "circles"],
                                "description": "可选：图层类型，默认 points",
                            },
                        },
                    },
                },
                "intent": {
                    "type": "string",
                    "enum": ["situation", "general"],
                    "description": "意图识别：situation=态势分析需求（需查询数据集、生成图表/地图/做数据分析）；general=非态势需求（闲聊、通用问答、计算、知识咨询等）",
                },
                "directAnswer": {
                    "type": "string",
                    "description": "intent=general 时的直接回答（中文，无需图表）；intent=situation 时省略",
                },
                "narrativeOutline": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "intro": {
                            "type": "string",
                            "description": "可选：态势介绍的要点（介绍性，非先验结论）",
                        },
                        "chartExplanations": {
                            "type": "array",
                            "description": "可选：每张图的说明要点",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["chartRef"],
                                "properties": {
                                    "chartRef": {
                                        "type": "string",
                                        "description": "引用的 chartSpecs[*].id",
                                    },
                                    "points": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "可选：该图需要说明的要点",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


# 默认 chart 类型池（与 orchestrator._CHART_TYPES 对齐）
_DEFAULT_CHART_TYPES = ["bar", "line", "pie", "radar", "scatter"]


def _allowed_chart_types(profile: Dict[str, Any]) -> set:
    """从 Skill profile 取允许的 chart 类型集合（与现有 _validate_llm_result 对齐）。"""
    skill_types = profile.get("chartTypes") or []
    allowed = {t.lower() for t in skill_types if t.lower() in _DEFAULT_CHART_TYPES}
    return allowed or set(_DEFAULT_CHART_TYPES)


def _build_planner_system_prompt(profile: Dict[str, Any], meta_text: str) -> str:
    """构建 Planner 专用 system prompt。

    与 build_plan_messages 的差异：
    1. 不要求"返回 JSON"，改为"调用 emit_research_plan 工具"
    2. 强调允许相同 type 重复（撤销原"类型互不相同"约束）
    3. 强调图表类型-数据适配规则（避免 pie 塞 30 分类）
    4. 未选 Skill 时不约束图表类型/数量/地图，由 LLM 自由决策
    """
    base = prompts.get_system_prompt()
    allowed_types = sorted(_allowed_chart_types(profile))
    # 未选 Skill 时给"自由规划"提示，避免 LLM 套用固定模板
    if not profile.get("skillId"):
        skill_hint = (
            "用户未选择特定 Skill，请基于问题意图与数据集字段特征自由规划：\n"
            "- 图表类型与数量（2-4 张）由数据特征决定，不要套用固定模板；\n"
            "- 地图图层是否产出由数据是否包含地理坐标字段决定；\n"
            "- 重点指标从数据集字段中识别，不要假设固定主题。\n\n"
        )
    else:
        skill_hint = (
            f"用户已选择 Skill「{profile.get('skillName', '通用态势')}」，"
            "规划应贴合该 Skill 的分析目标与推荐图表类型。\n\n"
        )
    return base + "\n\n" + (
        "【当前阶段：规划（Planner Agent）】\n"
        "你是态势分析规划专家。根据用户问题与下方可用数据集元数据，"
        "调用 emit_research_plan 工具提交研究计划。\n\n"
        + skill_hint +
        "硬约束：\n"
        "0. 意图识别（最先判断）：若用户问题属于态势分析需求（需查询数据集、生成图表/地图/做数据分析），"
        "intent=\"situation\"，按下方约束正常规划；若属于闲聊、通用问答、计算、知识咨询等非态势需求，"
        "intent=\"general\"，subQuestions/chartSpecs/mapSpecs 全部留空数组，并把你的回答写入 directAnswer（中文，无需图表）。\n"
        "1. subQuestions 至少 1 个（intent=situation 时），每个 datasetId 必须来自下方可用数据集；\n"
        f"2. chartSpecs 数量 2-4 个（intent=situation 时），type 只能取 {allowed_types}；\n"
        "3. 允许相同 type 重复（如两个 line 图各展示不同维度），"
        "但选型必须匹配数据特征：\n"
        "   - pie：分类数 ≤ 8（超过应改用 bar 或合并为「其他」）；分片值不得为负；\n"
        "   - radar：维度数 3-12；\n"
        "   - line：X 轴样本 ≥ 2；\n"
        "   - bar：分类数 ≤ 30；\n"
        "   - scatter：点数 ≥ 5；\n"
        "4. chartSpecs[*].subQuestionRef 必须命中 subQuestions[*].id；\n"
        "5. 若数据集元数据中无明显地理坐标字段，mapSpecs 留空数组；\n"
        "6. 数据源无关：不得在 chartSpecs.title 或 narrativeOutline 中出现未在元数据中的具体字段值。\n\n"
        "直接调用 emit_research_plan 工具，不要输出额外文本。\n\n"
        f"可用数据集元数据：\n{meta_text}"
    )


def _validate_plan(plan: Dict[str, Any], profile: Dict[str, Any], meta: Dict[str, Any]) -> Optional[str]:
    """校验 Planner 输出，返回失败原因字符串（None 表示通过）。

    校验项：
    - subQuestions ≥ 1，datasetId 必须在 meta 的可用数据集内
    - chartSpecs 数量 ∈ [2, 4]
    - chartSpecs[*].type 必须在 allowed_types 内
    - chartSpecs[*].subQuestionRef 必须命中 subQuestions[*].id
    """
    if not isinstance(plan, dict):
        return "emit_research_plan 参数不是对象"

    # 意图识别分支：非态势需求（general）时放行空计划，仅要求直接回答非空
    intent = str(plan.get("intent") or "").lower().strip()
    if intent not in ("situation", "general"):
        return "intent 必须是 situation 或 general"
    if intent == "general":
        if not str(plan.get("directAnswer") or "").strip():
            return "intent=general 时 directAnswer 不能为空"
        return None

    # ── 以下为 situation 分支校验 ──
    sub_questions = plan.get("subQuestions")
    if not isinstance(sub_questions, list) or len(sub_questions) < 1:
        return "subQuestions 至少需要 1 个"
    if len(sub_questions) > 6:
        return "subQuestions 不能超过 6 个"

    # 收集 meta 中的可用数据集 ID
    available_dataset_ids = set()
    if isinstance(meta, dict) and meta.get("success"):
        data = meta.get("data", {}) or {}
        for schema in data.get("schemas", []) or []:
            ds_id = str(schema.get("datasetId") or "").strip()
            if ds_id:
                available_dataset_ids.add(ds_id)

    sub_q_ids = set()
    for idx, sq in enumerate(sub_questions):
        if not isinstance(sq, dict):
            return f"subQuestions[{idx}] 不是对象"
        sq_id = str(sq.get("id") or "").strip()
        if not sq_id:
            return f"subQuestions[{idx}].id 为空"
        if sq_id in sub_q_ids:
            return f"subQuestions[{idx}].id 重复: {sq_id}"
        sub_q_ids.add(sq_id)
        ds_id = str(sq.get("datasetId") or "").strip()
        if not ds_id:
            return f"subQuestions[{idx}].datasetId 为空"
        # meta 为空时（mock 测试场景）跳过白名单校验
        if available_dataset_ids and ds_id not in available_dataset_ids:
            return f"subQuestions[{idx}].datasetId={ds_id} 不在可用数据集中"

    chart_specs = plan.get("chartSpecs")
    if not isinstance(chart_specs, list) or len(chart_specs) < 2:
        return "chartSpecs 至少需要 2 个"
    if len(chart_specs) > 4:
        return "chartSpecs 不能超过 4 个"

    allowed = _allowed_chart_types(profile)
    chart_ids = set()
    for idx, cs in enumerate(chart_specs):
        if not isinstance(cs, dict):
            return f"chartSpecs[{idx}] 不是对象"
        cs_id = str(cs.get("id") or "").strip()
        if not cs_id:
            return f"chartSpecs[{idx}].id 为空"
        if cs_id in chart_ids:
            return f"chartSpecs[{idx}].id 重复: {cs_id}"
        chart_ids.add(cs_id)
        chart_type = str(cs.get("type") or "").lower().strip()
        if chart_type not in allowed:
            return f"chartSpecs[{idx}].type={chart_type} 不在允许类型 {sorted(allowed)} 内"
        ref = str(cs.get("subQuestionRef") or "").strip()
        if ref not in sub_q_ids:
            return f"chartSpecs[{idx}].subQuestionRef={ref} 未命中任何子问题 ID"

    # mapSpecs 可选；如提供，校验 subQuestionRef
    map_specs = plan.get("mapSpecs")
    if isinstance(map_specs, list):
        for idx, ms in enumerate(map_specs):
            if not isinstance(ms, dict):
                return f"mapSpecs[{idx}] 不是对象"
            ref = str(ms.get("subQuestionRef") or "").strip()
            if ref and ref not in sub_q_ids:
                return f"mapSpecs[{idx}].subQuestionRef={ref} 未命中任何子问题 ID"

    return None


def _infer_focus_metrics_from_meta(meta: Dict[str, Any], limit: int = 2) -> list:
    """从未选 Skill 的场景下，从 meta schemas 推断数值字段名作为降级指标。"""
    if not isinstance(meta, dict) or not meta.get("success"):
        return []
    schemas = (meta.get("data", {}) or {}).get("schemas") or []
    metrics: list = []
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        for field in schema.get("fields") or []:
            if not isinstance(field, dict):
                continue
            # 数值型字段优先作为指标
            field_type = str(field.get("type") or field.get("dataType") or "").lower()
            name = str(field.get("name") or field.get("fieldName") or "").strip()
            label = str(field.get("businessMeaning") or field.get("comment") or "").strip()
            if name and "int" in field_type or "double" in field_type or "decimal" in field_type or "float" in field_type:
                metrics.append(label or name)
                if len(metrics) >= limit:
                    return metrics
    return metrics[:limit]


def _fallback_plan_from_skill(profile: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Planner 多次失败后的回退：用 Skill profile 或数据集元数据构造最小可用计划。

    保证 chartSpecs ≥ 2：
    - 已选 Skill：按 profile.chartTypes[:2] 与 focusMetrics[:2] 配对
    - 未选 Skill：从 meta schemas 推断数值字段作为指标，图表类型用全集前两个
    """
    focus_metrics = profile.get("focusMetrics") or []
    if not focus_metrics:
        # 未选 Skill 时从 meta 推断数值字段名作为降级指标
        focus_metrics = _infer_focus_metrics_from_meta(meta, limit=2) or ["核心指标 A", "核心指标 B"]
    chart_types = profile.get("chartTypes") or _DEFAULT_CHART_TYPES
    allowed = [t for t in chart_types if t in _allowed_chart_types(profile)] or _DEFAULT_CHART_TYPES

    # 取前两个允许的图表类型（允许相同）
    type_a = allowed[0] if allowed else "bar"
    type_b = allowed[1] if len(allowed) > 1 else allowed[0]

    metric_a = focus_metrics[0] if len(focus_metrics) > 0 else "指标 A"
    metric_b = focus_metrics[1] if len(focus_metrics) > 1 else focus_metrics[0]

    # 取第一个可用数据集作为兜底 datasetId
    fallback_dataset = ""
    if isinstance(meta, dict) and meta.get("success"):
        schemas = (meta.get("data", {}) or {}).get("schemas") or []
        if schemas:
            fallback_dataset = str(schemas[0].get("datasetId") or "").strip()

    sub_q_id = "q1"
    skill_label = profile.get("skillName") or "通用态势"
    return {
        "subQuestions": [
            {
                "id": sub_q_id,
                "question": f"围绕「{skill_label}」采集核心数据",
                "datasetId": fallback_dataset,
            }
        ],
        "chartSpecs": [
            {
                "id": "c1",
                "type": type_a,
                "title": metric_a,
                "subQuestionRef": sub_q_id,
                "intent": "（Planner 降级：使用数据集字段推断的指标）",
            },
            {
                "id": "c2",
                "type": type_b,
                "title": metric_b,
                "subQuestionRef": sub_q_id,
                "intent": "（Planner 降级：使用数据集字段推断的指标）",
            },
        ],
        "mapSpecs": [],
        "narrativeOutline": {
            "intro": f"已围绕「{skill_label}」汇聚真实数据生成态势。",
        },
        "_fallback": True,
    }


class Planner:
    """Planner Agent：基于原生 tool-calling 产出 ResearchPlan。

    使用示例（阶段 2 集成）：
        planner = Planner(profile, meta)
        plan = await planner.plan(query)        # 走 LLM tool-call
        if plan.get("_fallback"):
            yield "error", {"stage": "plan", "fatal": False, ...}
    """

    def __init__(self, profile: Dict[str, Any], meta: Dict[str, Any]):
        self.profile = profile
        self.meta = meta

    def _build_messages(self, query: str) -> List[Dict[str, Any]]:
        meta_text = prompts._format_meta(self.meta)
        system_prompt = _build_planner_system_prompt(self.profile, meta_text)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户问题：{query}"},
        ]

    async def plan(self, query: str) -> Dict[str, Any]:
        """调用 LLM 产出 ResearchPlan。

        失败重试最多 2 次（共 3 次）；3 次均失败则返回 Skill 模板降级计划（_fallback=True）。
        """
        messages = self._build_messages(query)
        max_attempts = 3  # 1 + 2 retries
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            try:
                result = call_llm_with_tools(
                    messages=messages,
                    tools=[EMIT_RESEARCH_PLAN_TOOL],
                    tool_choice={"type": "function", "function": {"name": "emit_research_plan"}},
                    temperature=0.2,
                    max_tokens=min(config.LLM_MAX_TOKENS, 6000),
                )
                tool_calls = result.get("tool_calls") or []
                if not tool_calls:
                    last_error = "LLM 未返回 tool_calls"
                    logger.warning("Planner 第 %s 次未返回 tool_calls: %s", attempt, last_error)
                    continue

                # 取第一个 emit_research_plan 调用
                plan_args = None
                for tc in tool_calls:
                    if tc.get("name") == "emit_research_plan":
                        plan_args = tc.get("arguments")
                        break
                if not isinstance(plan_args, dict):
                    last_error = "emit_research_plan.arguments 解析为空"
                    logger.warning("Planner 第 %s 次 arguments 为空", attempt)
                    continue

                # 校验：失败时进入下一轮重试
                err = _validate_plan(plan_args, self.profile, self.meta)
                if err:
                    last_error = err
                    logger.warning("Planner 第 %s 次校验失败: %s", attempt, err)
                    continue

                plan_args.pop("_fallback", None)
                logger.info(
                    "Planner 成功（第 %s 次）：subQuestions=%s chartSpecs=%s",
                    attempt,
                    len(plan_args.get("subQuestions") or []),
                    len(plan_args.get("chartSpecs") or []),
                )
                return plan_args

            except Exception as exc:
                last_error = str(exc)[:200]
                logger.warning("Planner 第 %s 次异常: %s", attempt, last_error)
                continue

        # 3 次失败 → Skill 模板降级
        logger.warning("Planner 3 次均失败，回退 Skill 模板。最后错误: %s", last_error)
        fallback = _fallback_plan_from_skill(self.profile, self.meta)
        fallback["_planner_error"] = last_error
        return fallback


__all__ = ["Planner", "EMIT_RESEARCH_PLAN_TOOL"]
