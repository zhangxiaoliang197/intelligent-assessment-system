"""Critic 编辑指令翻译器 —— 把定性编辑指令翻译为新 chartSpecs/mapSpecs。

设计目标（参见方案文档 §3.3.4）：
- 纯确定性代码，零 LLM 调用，可单测
- 五类指令：replace_type / drop_chart / add_chart / replace_map_layer / accept
- 任一指令失败不立刻中断，收集所有 errors，最后统一校验
- 最终过 planner.validate_plan_against_meta，与 Planner 同口径，避免绕过硬约束
- 失败时调用方回退到原 rewrite_ids 重写路径（行为与现状兼容）

对齐业界实践：
- METAL (arxiv 2502.17651)：Critic 提定性编辑，Actor 据此修订
- See it. Say it. Sorted. (arxiv 2508.15222)：qualitative edits over brittle numbers
- ReLook Forced Optimization：仅接受严格提升的修订
"""
import logging
from typing import Any, Dict, List, Tuple

from agent.planner import validate_plan_against_meta

logger = logging.getLogger("situation-service")


# ── 编辑指令类型枚举（与 critic.EMIT_REVIEW_DECISION_TOOL 对齐）──
ACTION_REPLACE_TYPE = "replace_type"
ACTION_DROP_CHART = "drop_chart"
ACTION_ADD_CHART = "add_chart"
ACTION_REPLACE_MAP_LAYER = "replace_map_layer"
ACTION_ACCEPT = "accept"

_VALID_CHART_TYPES = {"bar", "line", "pie", "radar", "scatter"}
_VALID_MAP_LAYER_TYPES = {"points", "routes", "areas", "circles"}


def apply_actions(
    chart_specs: List[Dict[str, Any]],
    map_specs: List[Dict[str, Any]],
    sub_questions: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
    profile: Dict[str, Any],
    meta: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """应用 Critic 编辑指令到 chartSpecs/mapSpecs，返回新快照。

    Args:
        chart_specs: 原 chartSpecs 列表（不会被修改，函数内做深拷贝）
        map_specs: 原 mapSpecs 列表（同上）
        sub_questions: Planner 输出的子问题列表（add_chart 引用其 id）
        actions: Critic 输出的编辑指令列表，每项含 type/targetChartId/...
        profile: Skill profile（用于推断 allowed_types，由 validate_plan_against_meta 使用）
        meta: 数据集元数据（含 geo_profile.annotate_meta 标注）

    Returns:
        (new_chart_specs, new_map_specs, errors)
        errors 非空时调用方应回退到原 rewrite_ids 路径
    """
    new_chart_specs: List[Dict[str, Any]] = [dict(c) for c in chart_specs]
    new_map_specs: List[Dict[str, Any]] = [dict(m) for m in map_specs]
    errors: List[str] = []
    existing_ids = {str(c.get("id") or "") for c in new_chart_specs}
    sub_q_ids = {str(q.get("id") or "") for q in sub_questions if isinstance(q, dict)}

    for idx, action in enumerate(actions or []):
        if not isinstance(action, dict):
            errors.append(f"actions[{idx}] 不是对象")
            continue

        a_type = str(action.get("type") or "").strip()

        if a_type == ACTION_ACCEPT:
            # 占位指令，与空 actions 等价；不做任何修订
            continue

        elif a_type == ACTION_REPLACE_TYPE:
            cid = str(action.get("targetChartId") or "").strip()
            new_type = str(action.get("newType") or "").strip().lower()
            if not cid:
                errors.append(f"actions[{idx}] replace_type 缺少 targetChartId")
                continue
            if new_type not in _VALID_CHART_TYPES:
                errors.append(f"actions[{idx}] replace_type.newType={new_type} 非法")
                continue
            target = next((c for c in new_chart_specs if str(c.get("id") or "") == cid), None)
            if target is None:
                errors.append(f"actions[{idx}] replace_type 目标 {cid} 不存在")
                continue
            target["type"] = new_type
            logger.info("Critic 翻译: replace_type %s -> %s", cid, new_type)

        elif a_type == ACTION_DROP_CHART:
            cid = str(action.get("targetChartId") or "").strip()
            if not cid:
                errors.append(f"actions[{idx}] drop_chart 缺少 targetChartId")
                continue
            if cid not in existing_ids:
                errors.append(f"actions[{idx}] drop_chart 目标 {cid} 不存在")
                continue
            new_chart_specs = [c for c in new_chart_specs if str(c.get("id") or "") != cid]
            existing_ids.discard(cid)
            logger.info("Critic 翻译: drop_chart %s", cid)

        elif a_type == ACTION_ADD_CHART:
            sub_ref = str(action.get("newSubQuestionRef") or "").strip()
            new_type = str(action.get("newType") or "bar").strip().lower()
            if sub_ref not in sub_q_ids:
                errors.append(
                    f"actions[{idx}] add_chart.newSubQuestionRef={sub_ref} 未命中子问题"
                )
                continue
            if new_type not in _VALID_CHART_TYPES:
                errors.append(f"actions[{idx}] add_chart.newType={new_type} 非法")
                continue
            # 生成不冲突的新 chartId：c{n}，冲突时追加 _
            new_id = f"c{len(new_chart_specs) + 1}"
            while new_id in existing_ids:
                new_id = new_id + "_"
            rationale = str(action.get("rationale") or action.get("reason") or "Critic 补图")
            new_chart_specs.append({
                "id": new_id,
                "type": new_type,
                "title": rationale[:40],
                "subQuestionRef": sub_ref,
                "intent": rationale,
            })
            existing_ids.add(new_id)
            logger.info("Critic 翻译: add_chart id=%s type=%s subRef=%s", new_id, new_type, sub_ref)

        elif a_type == ACTION_REPLACE_MAP_LAYER:
            cid = str(action.get("targetChartId") or "").strip()
            new_layer = str(action.get("newLayerType") or "").strip().lower()
            if not cid:
                errors.append(f"actions[{idx}] replace_map_layer 缺少 targetChartId")
                continue
            if new_layer not in _VALID_MAP_LAYER_TYPES:
                errors.append(
                    f"actions[{idx}] replace_map_layer.newLayerType={new_layer} 非法"
                )
                continue
            target = next(
                (m for m in new_map_specs if str(m.get("id") or "") == cid), None
            )
            if target is None:
                # mapSpecs 为空时降级：忽略指令，不报错（避免与"无地图场景"冲突）
                logger.info("Critic 翻译: replace_map_layer %s 无目标，跳过", cid)
                continue
            target["layerType"] = new_layer
            logger.info("Critic 翻译: replace_map_layer %s -> %s", cid, new_layer)

        else:
            errors.append(f"actions[{idx}] 未知 type={a_type}")
            continue

    # 数量硬约束（Planner 同口径）
    if not (2 <= len(new_chart_specs) <= 4):
        errors.append(
            f"修订后 chartSpecs 数量 {len(new_chart_specs)} 不在 [2, 4]"
        )

    # 复用 planner 校验：subQuestionRef 命中、type 在 allowed_types、mapSpecs 地理能力
    plan = {
        "subQuestions": sub_questions,
        "chartSpecs": new_chart_specs,
        "mapSpecs": new_map_specs,
        "intent": "situation",
    }
    err = validate_plan_against_meta(plan, profile, meta)
    if err:
        errors.append(f"校验失败: {err}")

    return new_chart_specs, new_map_specs, errors


__all__ = ["apply_actions"]
