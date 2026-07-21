"""LLM-assisted Skill drafting with deterministic validation and repair.

The model is only used to propose a draft.  This module owns the contract that
turns the proposal into a safe, editable catalog payload; publishing still goes
through the normal governance API.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List


class SkillAiDraftError(ValueError):
    """Raised when an AI response cannot be converted into a Skill draft."""


def _text(value: Any, maximum: int = 500) -> str:
    return str(value or "").strip()[:maximum]


def _strings(value: Any, *, limit: int, maximum: int = 80) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _text(item, maximum)
        key = cleaned.lower()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _slug(value: Any, fallback: str) -> str:
    text = _text(value, 64).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


def _integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _extract_object(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise SkillAiDraftError("智能创建未返回可识别的 JSON Skill 草稿")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise SkillAiDraftError(f"智能创建返回格式无效: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise SkillAiDraftError("智能创建结果必须是 JSON 对象")
    return value


def normalize_ai_draft(raw: str | Dict[str, Any], *, max_steps: int = 6) -> Dict[str, Any]:
    proposal = _extract_object(raw) if isinstance(raw, str) else dict(raw)
    max_steps = max(1, min(int(max_steps), 12))
    raw_steps = proposal.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SkillAiDraftError("智能创建结果至少需要一个执行步骤")

    steps: List[Dict[str, Any]] = []
    ids: set[str] = set()
    for index, item in enumerate(raw_steps[:max_steps], start=1):
        if not isinstance(item, dict):
            continue
        step_id = _slug(item.get("id"), f"step-{index}")
        if step_id in ids:
            step_id = f"{step_id}-{index}"
        ids.add(step_id)
        keywords = _strings(
            item.get("datasetKeywords") or item.get("dataset_keywords"),
            limit=12,
        )
        name = _text(item.get("name"), 80) or f"步骤 {index}"
        description = _text(item.get("description"), 500) or f"分析{name}所需数据"
        steps.append(
            {
                "id": step_id,
                "name": name,
                "description": description,
                "datasetKeywords": keywords or [name],
                "allowReuse": bool(item.get("allowReuse", False)),
                "dependsOn": _strings(item.get("dependsOn"), limit=12, maximum=64),
                "runIf": item.get("runIf")
                if item.get("runIf") in {"all_success", "any_success", "always"}
                else "all_success",
                "retryCount": _integer(item.get("retryCount"), 0, 0, 3),
                "timeoutSeconds": _integer(item.get("timeoutSeconds"), 130, 5, 300),
                "onFailure": item.get("onFailure")
                if item.get("onFailure") in {"continue", "stop", "skip_dependents"}
                else "continue",
            }
        )
    if not steps:
        raise SkillAiDraftError("智能创建结果没有有效执行步骤")

    # Repair unknown/self/forward references.  The model may suggest natural
    # language labels instead of ids; only explicit, already-known ids survive.
    known_ids: set[str] = set()
    for step in steps:
        step["dependsOn"] = [
            dep for dep in step["dependsOn"] if dep in known_ids and dep != step["id"]
        ]
        known_ids.add(step["id"])

    orchestration = proposal.get("orchestration")
    orchestration = orchestration if isinstance(orchestration, dict) else {}
    has_dependencies = any(step["dependsOn"] for step in steps)
    return {
        "name": _text(proposal.get("name"), 80) or "智能创建 Skill",
        "description": _text(proposal.get("description"), 500)
        or "根据业务目标智能生成的可编辑 Skill 草稿",
        "category": _text(proposal.get("category"), 40) or "智能分析",
        "triggers": _strings(proposal.get("triggers"), limit=12) or ["智能分析"],
        "recommendedQuestions": _strings(
            proposal.get("recommendedQuestions") or proposal.get("recommended_questions"),
            limit=5,
            maximum=160,
        ),
        "steps": steps,
        "outputInstruction": _text(proposal.get("outputInstruction"), 1000)
        or "基于各步骤证据给出结论、关键发现、风险与建议。",
        "orchestration": {
            "mode": orchestration.get("mode")
            if orchestration.get("mode") in {"sequential", "dependency"}
            else ("dependency" if has_dependencies else "sequential"),
            "maxConcurrency": _integer(orchestration.get("maxConcurrency"), 1, 1, 6),
            "timeoutSeconds": _integer(orchestration.get("timeoutSeconds"), 600, 30, 1800),
            "failurePolicy": orchestration.get("failurePolicy")
            if orchestration.get("failurePolicy") in {"continue", "stop"}
            else "continue",
        },
        "visibility": "private",
        "tags": ["智能创建"],
    }


async def generate_skill_draft(
    *,
    requirement: str,
    datasets: List[Dict[str, Any]],
    llm_call_fn: Callable[[str, str], Awaitable[str]],
    max_steps: int = 6,
) -> Dict[str, Any]:
    requirement = _text(requirement, 4000)
    if not requirement:
        raise SkillAiDraftError("请描述要创建的 Skill 目标")
    context = [
        {
            "id": _text(item.get("id"), 128),
            "name": _text(item.get("name"), 160),
            "tableName": _text(item.get("tableName") or item.get("table_name"), 160),
            "description": _text(item.get("description"), 300),
        }
        for item in datasets[:80]
        if isinstance(item, dict)
    ]
    system_prompt = """你是企业数据分析 Skill 设计器。只返回一个 JSON 对象，不要 Markdown。
JSON 必须包含 name、description、category、triggers、recommendedQuestions、steps、outputInstruction、orchestration。
每个 steps 项包含 id(小写英文短横线)、name、description、datasetKeywords、allowReuse、dependsOn、runIf、retryCount、timeoutSeconds、onFailure。
runIf 仅可为 all_success/any_success/always；onFailure 仅可为 continue/stop/skip_dependents。
编排 mode 仅可为 sequential/dependency，failurePolicy 仅可为 continue/stop。步骤应可执行、职责单一，并尽量匹配给出的数据集。"""
    user_message = json.dumps(
        {
            "requirement": requirement,
            "maxSteps": max(1, min(int(max_steps), 12)),
            "availableDatasets": context,
        },
        ensure_ascii=False,
    )
    response = await llm_call_fn(system_prompt, user_message)
    draft = normalize_ai_draft(response, max_steps=max_steps)
    draft["dataContext"] = {
        "datasetCount": len(context),
        "dataSourceComplete": bool(context),
    }
    return draft
