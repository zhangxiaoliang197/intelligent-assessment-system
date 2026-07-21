"""Evaluation Skill catalog, custom Skill persistence and dataset matching."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from .custom_skill_store import (
    CustomSkillStoreConflict,
    CustomSkillStoreError,
    CustomSkillStoreNotFound,
    create_record,
    create_share_record,
    delete_record,
    get_share_record,
    get_store_warning,
    get_version_record,
    list_favorite_records,
    list_records,
    list_share_records,
    list_version_records,
    revoke_share_record,
    set_favorite_record,
    update_record,
)
from .skill_governance import (
    SkillActor,
    SkillImportFormatError,
    coerce_skill_actor,
    export_skill_bundle,
    export_skill_definition,
    normalize_governance,
    parse_skill_import,
    skill_permissions,
)


logger = logging.getLogger("evaluation.skill_catalog")
_custom_catalog_warning = ""


_CATALOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "skills.json",
)
class SkillCatalogError(ValueError):
    """Raised when a Skill catalog or Skill definition is malformed."""


class SkillNotFoundError(SkillCatalogError):
    """Raised when a requested custom Skill does not exist."""


class SkillReadOnlyError(SkillCatalogError):
    """Raised when a caller tries to mutate a built-in Skill."""


class SkillConflictError(SkillCatalogError):
    """Raised when a custom Skill conflicts with an existing definition."""


class SkillStoreUnavailableError(SkillCatalogError):
    """Raised when custom Skill persistence is unavailable."""


class SkillPermissionError(SkillCatalogError):
    """Raised when an actor cannot perform an operation on a Skill."""


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _compact(value: Any) -> str:
    """Normalize separators so table names and natural-language names can match."""
    return re.sub(r"[\s_\-./]+", "", _text(value))


def _tokens(value: Any) -> List[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return [token.lower() for token in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", normalized) if token]


def _field_matches_keyword(field: Any, keyword: Any) -> bool:
    field_text = _text(field)
    keyword_text = _text(keyword)
    if not field_text or not keyword_text:
        return False
    field_compact = _compact(field_text)
    keyword_compact = _compact(keyword_text)
    if field_compact == keyword_compact:
        return True

    # English identifiers must match complete snake/camel/name tokens. This
    # prevents short words such as "order" matching "border_status" and
    # "unit" matching "ammunition_inventory".
    if re.fullmatch(r"[a-z0-9_\-\s./]+", keyword_text):
        keyword_tokens = _tokens(keyword_text)
        field_tokens = set(_tokens(field_text))
        return bool(keyword_tokens) and all(token in field_tokens for token in keyword_tokens)

    # Chinese semantic labels are not whitespace-delimited, so substring
    # matching is appropriate in the keyword -> field direction only.
    return keyword_compact in field_compact


def _validate_text(value: Any, field: str, *, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SkillCatalogError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise SkillCatalogError(f"{field} exceeds {maximum} characters")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise SkillCatalogError(f"{field} contains unsupported control characters")
    if re.search(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", value):
        raise SkillCatalogError(f"{field} contains unsupported invisible direction controls")


def _validate_string_list(
    values: Any,
    field: str,
    *,
    maximum_items: int,
    maximum_length: int,
    required: bool = False,
) -> None:
    if not isinstance(values, list):
        raise SkillCatalogError(f"{field} must be a list")
    if required and not values:
        raise SkillCatalogError(f"{field} must contain at least one item")
    if len(values) > maximum_items:
        raise SkillCatalogError(f"{field} exceeds {maximum_items} items")
    for index, value in enumerate(values, start=1):
        _validate_text(value, f"{field}[{index}]", maximum=maximum_length)


def _validate_skill(skill: Dict[str, Any], seen_ids: set[str]) -> None:
    required = ("id", "name", "description", "category", "steps", "outputInstruction")
    missing = [field for field in required if not skill.get(field)]
    if missing:
        raise SkillCatalogError(
            f"Skill {skill.get('id', '<unknown>')} missing fields: {', '.join(missing)}"
        )

    skill_id = skill["id"]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id):
        raise SkillCatalogError(f"Invalid Skill id: {skill_id}")
    if skill_id in seen_ids:
        raise SkillCatalogError(f"Duplicate Skill id: {skill_id}")
    seen_ids.add(skill_id)

    _validate_text(skill["name"], f"Skill {skill_id} name", maximum=80)
    _validate_text(skill["description"], f"Skill {skill_id} description", maximum=500)
    _validate_text(skill["category"], f"Skill {skill_id} category", maximum=40)
    _validate_text(
        skill["outputInstruction"],
        f"Skill {skill_id} outputInstruction",
        maximum=1200,
    )
    _validate_string_list(
        skill.get("triggers", []),
        f"Skill {skill_id} triggers",
        maximum_items=12,
        maximum_length=80,
    )
    _validate_string_list(
        skill.get("recommendedQuestions", []),
        f"Skill {skill_id} recommendedQuestions",
        maximum_items=5,
        maximum_length=300,
    )

    if not isinstance(skill["steps"], list) or not skill["steps"]:
        raise SkillCatalogError(f"Skill {skill_id} must contain at least one dataset step")
    if len(skill["steps"]) > 12:
        raise SkillCatalogError(f"Skill {skill_id} exceeds 12 dataset steps")

    step_ids: set[str] = set()
    dependency_map: Dict[str, List[str]] = {}
    for step in skill["steps"]:
        if not isinstance(step, dict):
            raise SkillCatalogError(f"Skill {skill_id} contains a non-object dataset step")
        if not all(step.get(field) for field in ("id", "name", "description", "datasetKeywords")):
            raise SkillCatalogError(f"Skill {skill_id} contains an incomplete dataset step")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", step["id"]):
            raise SkillCatalogError(f"Skill {skill_id} contains invalid step id {step['id']}")
        if step["id"] in step_ids:
            raise SkillCatalogError(f"Skill {skill_id} contains duplicate step id {step['id']}")
        step_ids.add(step["id"])
        _validate_text(step["name"], f"Skill {skill_id} step {step['id']} name", maximum=80)
        _validate_text(
            step["description"],
            f"Skill {skill_id} step {step['id']} description",
            maximum=500,
        )
        _validate_string_list(
            step["datasetKeywords"],
            f"Skill {skill_id} step {step['id']} datasetKeywords",
            maximum_items=12,
            maximum_length=80,
            required=True,
        )
        if "allowReuse" in step and not isinstance(step["allowReuse"], bool):
            raise SkillCatalogError(
                f"Skill {skill_id} step {step['id']} allowReuse must be a boolean"
            )
        if step.get("datasetId"):
            _validate_text(
                step["datasetId"],
                f"Skill {skill_id} step {step['id']} datasetId",
                maximum=128,
            )
        if step.get("datasetName"):
            _validate_text(
                step["datasetName"],
                f"Skill {skill_id} step {step['id']} datasetName",
                maximum=160,
            )
        depends_on = step.get("dependsOn", [])
        _validate_string_list(
            depends_on,
            f"Skill {skill_id} step {step['id']} dependsOn",
            maximum_items=12,
            maximum_length=64,
        )
        dependency_map[step["id"]] = list(depends_on)
        if step.get("runIf", "all_success") not in {"all_success", "any_success", "always"}:
            raise SkillCatalogError(f"Skill {skill_id} step {step['id']} has invalid runIf")
        if step.get("onFailure", "continue") not in {"continue", "stop", "skip_dependents"}:
            raise SkillCatalogError(f"Skill {skill_id} step {step['id']} has invalid onFailure")
        retry_count = step.get("retryCount", 0)
        timeout_seconds = step.get("timeoutSeconds", 130)
        if not isinstance(retry_count, int) or not 0 <= retry_count <= 3:
            raise SkillCatalogError(f"Skill {skill_id} step {step['id']} retryCount must be 0-3")
        if not isinstance(timeout_seconds, int) or not 5 <= timeout_seconds <= 300:
            raise SkillCatalogError(f"Skill {skill_id} step {step['id']} timeoutSeconds must be 5-300")

    for step_id, dependencies in dependency_map.items():
        unknown = [dependency for dependency in dependencies if dependency not in step_ids]
        if unknown:
            raise SkillCatalogError(
                f"Skill {skill_id} step {step_id} references unknown dependencies: {', '.join(unknown)}"
            )
        if step_id in dependencies:
            raise SkillCatalogError(f"Skill {skill_id} step {step_id} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise SkillCatalogError(f"Skill {skill_id} contains a dependency cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependency_map.get(step_id, []):
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in dependency_map:
        visit(step_id)

    orchestration = skill.get("orchestration", {})
    if not isinstance(orchestration, dict):
        raise SkillCatalogError(f"Skill {skill_id} orchestration must be an object")
    if orchestration.get("mode", "sequential") not in {"sequential", "dependency"}:
        raise SkillCatalogError(f"Skill {skill_id} orchestration mode is invalid")
    if orchestration.get("failurePolicy", "continue") not in {"continue", "stop"}:
        raise SkillCatalogError(f"Skill {skill_id} orchestration failurePolicy is invalid")
    max_concurrency = orchestration.get("maxConcurrency", 1)
    total_timeout = orchestration.get("timeoutSeconds", 600)
    if not isinstance(max_concurrency, int) or not 1 <= max_concurrency <= 6:
        raise SkillCatalogError(f"Skill {skill_id} maxConcurrency must be 1-6")
    if not isinstance(total_timeout, int) or not 30 <= total_timeout <= 1800:
        raise SkillCatalogError(f"Skill {skill_id} timeoutSeconds must be 30-1800")


@lru_cache(maxsize=1)
def _load_catalog_cached() -> Dict[str, Any]:
    try:
        with open(_CATALOG_FILE, "r", encoding="utf-8") as file:
            catalog = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillCatalogError(f"Unable to load Skill catalog: {exc}") from exc

    skills = catalog.get("skills")
    if not isinstance(skills, list) or not skills:
        raise SkillCatalogError("Skill catalog must contain a non-empty skills list")

    seen_ids: set[str] = set()
    for skill in skills:
        if not isinstance(skill, dict):
            raise SkillCatalogError("Every Skill must be an object")
        _validate_skill(skill, seen_ids)
    return catalog


def load_catalog() -> Dict[str, Any]:
    """Return a defensive copy of the validated built-in Skill catalog."""
    return copy.deepcopy(_load_catalog_cached())


def _decorate_skill(
    skill: Dict[str, Any],
    source: str,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    favorite: bool = False,
) -> Dict[str, Any]:
    item = copy.deepcopy(skill)
    built_in = source == "builtin"
    item.setdefault(
        "orchestration",
        {
            "mode": "sequential",
            "maxConcurrency": 1,
            "timeoutSeconds": 600,
            "failurePolicy": "continue",
        },
    )
    for step in item.get("steps", []):
        step.setdefault("dependsOn", [])
        step.setdefault("runIf", "all_success")
        step.setdefault("retryCount", 0)
        step.setdefault("timeoutSeconds", 130)
        step.setdefault("onFailure", "continue")
    item["source"] = source
    item["isBuiltIn"] = built_in
    if built_in:
        item.setdefault("revision", 1)
        item.setdefault("createdAt", "")
        item.setdefault("updatedAt", "")
        item.setdefault("ownerId", "system")
        item.setdefault("teamId", "")
        item.setdefault("visibility", "public")
        item.setdefault("status", "published")
        item.setdefault("tags", [])
        item.setdefault("isTemplate", False)
        item.setdefault("publishedVersion", 1)
        item.setdefault("version", 1)
        item.setdefault("currentVersion", item["version"])
    else:
        governance = normalize_governance(item, actor=actor, legacy_defaults=True)
        for field, value in governance.items():
            item.setdefault(field, value)
    permissions = skill_permissions(item, actor)
    item["permissions"] = permissions
    item["editable"] = permissions["editable"]
    item["deletable"] = permissions["deletable"]
    item["publishable"] = permissions["publishable"]
    item["shareable"] = permissions["shareable"]
    item["favorite"] = bool(favorite)
    item["executable"] = item.get("status") == "published" and not item.get("isTemplate")
    return item


def _favorite_ids(actor: SkillActor | Dict[str, Any] | None) -> set[str]:
    principal = coerce_skill_actor(actor)
    try:
        return set(list_favorite_records(principal.user_id))
    except CustomSkillStoreError as exc:
        logger.warning("Unable to load Skill favorites: %s", exc)
        return set()


def list_builtin_skills(
    actor: SkillActor | Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Return the immutable built-in catalog in its declared order."""
    favorites = _favorite_ids(actor)
    return [
        _decorate_skill(skill, "builtin", actor, favorite=skill["id"] in favorites)
        for skill in load_catalog()["skills"]
    ]


def list_custom_skills(
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    include_archived: bool = False,
) -> List[Dict[str, Any]]:
    """Return persisted user-authored Skills ordered by most recent update."""
    global _custom_catalog_warning
    try:
        records = list_records()
    except CustomSkillStoreError as exc:
        _custom_catalog_warning = str(exc)
        logger.error("Custom Skill store is unavailable: %s", exc)
        return []

    store_warning = get_store_warning()
    _custom_catalog_warning = store_warning
    seen_ids = {skill["id"] for skill in load_catalog()["skills"]}
    favorites = _favorite_ids(actor)
    items = []
    valid_count = 0
    for record in records:
        try:
            if not str(record.get("id", "")).startswith("custom-"):
                raise SkillCatalogError(f"Invalid custom Skill id: {record.get('id', '')}")
            _validate_skill(record, seen_ids)
            valid_count += 1
            item = _decorate_skill(
                record,
                "custom",
                actor,
                favorite=record["id"] in favorites,
            )
            if not item["permissions"]["visible"]:
                continue
            if item.get("status") == "archived" and not include_archived:
                continue
            items.append(item)
        except SkillCatalogError as exc:
            _custom_catalog_warning = "；".join(
                part for part in (_custom_catalog_warning, str(exc)) if part
            )
            logger.error("Skipping malformed custom Skill: %s", exc)
    if valid_count == len(records) and not store_warning:
        _custom_catalog_warning = ""
    return items


def get_custom_catalog_warning() -> str:
    """Return the most recent non-fatal custom catalog warning."""
    return _custom_catalog_warning


def list_skills(
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    include_archived: bool = False,
    statuses: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    template: Optional[bool] = None,
    favorites_only: bool = False,
) -> List[Dict[str, Any]]:
    """Return built-in and user-authored Skills as one executable catalog."""
    items = [
        *list_builtin_skills(actor),
        *list_custom_skills(actor, include_archived=include_archived),
    ]
    if statuses is not None:
        status_filter = {str(status).strip().lower() for status in statuses}
        items = [item for item in items if item.get("status") in status_filter]
    if tags is not None:
        tag_filter = {str(tag).strip().casefold() for tag in tags if str(tag).strip()}
        items = [
            item
            for item in items
            if tag_filter.intersection(
                str(tag).casefold() for tag in item.get("tags", [])
            )
        ]
    if template is not None:
        items = [item for item in items if bool(item.get("isTemplate")) is bool(template)]
    if favorites_only:
        items = [item for item in items if item.get("favorite")]
    return items


def get_skill(
    skill_id: str,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    include_archived: bool = False,
) -> Optional[Dict[str, Any]]:
    for skill in list_skills(actor, include_archived=include_archived):
        if skill["id"] == skill_id:
            return skill
    return None


def _clean_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _clean_string_list(values: Any) -> Any:
    if not isinstance(values, list):
        return values
    cleaned: List[Any] = []
    seen: set[str] = set()
    for value in values:
        normalized = _clean_text(value)
        if isinstance(normalized, str) and not normalized:
            continue
        key = normalized.casefold() if isinstance(normalized, str) else repr(normalized)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    return cleaned


def _make_step_id(raw_id: Any, name: Any, position: int, used_ids: set[str]) -> str:
    candidate = _text(raw_id)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", candidate):
        candidate = re.sub(r"[^a-z0-9]+", "-", _text(name)).strip("-")
    if not candidate:
        candidate = f"step-{position}"
    base = candidate[:55].rstrip("-") or f"step-{position}"
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base[:55]}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _normalize_custom_skill(
    payload: Dict[str, Any],
    *,
    skill_id: str,
    created_at: str = "",
    updated_at: str = "",
    revision: int = 1,
    governance_source: Optional[Dict[str, Any]] = None,
    actor: SkillActor | Dict[str, Any] | None = None,
    legacy_defaults: bool = False,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise SkillCatalogError("Skill definition must be an object")

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise SkillCatalogError("Skill steps must be a list")
    used_step_ids: set[str] = set()
    steps = []
    for position, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise SkillCatalogError(f"Skill step {position} must be an object")
        steps.append(
            {
                "id": _make_step_id(raw_step.get("id"), raw_step.get("name"), position, used_step_ids),
                "name": _clean_text(raw_step.get("name")),
                "description": _clean_text(raw_step.get("description")),
                "datasetKeywords": _clean_string_list(raw_step.get("datasetKeywords")),
                "allowReuse": raw_step.get("allowReuse", False),
                "datasetId": _clean_text(raw_step.get("datasetId")) or "",
                "datasetName": _clean_text(raw_step.get("datasetName")) or "",
                "dependsOn": _clean_string_list(raw_step.get("dependsOn", [])),
                "runIf": _clean_text(raw_step.get("runIf")) or "all_success",
                "retryCount": int(raw_step.get("retryCount", 0) or 0),
                "timeoutSeconds": int(raw_step.get("timeoutSeconds", 130) or 130),
                "onFailure": _clean_text(raw_step.get("onFailure")) or "continue",
            }
        )

    governance_input = dict(governance_source or {})
    for field in ("ownerId", "teamId", "visibility", "status", "tags", "isTemplate"):
        if field in payload:
            governance_input[field] = payload[field]
    try:
        governance = normalize_governance(
            governance_input,
            actor=actor,
            legacy_defaults=legacy_defaults,
        )
    except ValueError as exc:
        raise SkillCatalogError(str(exc)) from exc

    raw_orchestration = payload.get("orchestration")
    raw_orchestration = raw_orchestration if isinstance(raw_orchestration, dict) else {}
    skill = {
        "id": skill_id,
        "name": _clean_text(payload.get("name")),
        "description": _clean_text(payload.get("description")),
        "category": _clean_text(payload.get("category")),
        "triggers": _clean_string_list(payload.get("triggers", [])),
        "recommendedQuestions": _clean_string_list(payload.get("recommendedQuestions", [])),
        "steps": steps,
        "outputInstruction": _clean_text(payload.get("outputInstruction")),
        "orchestration": {
            "mode": _clean_text(raw_orchestration.get("mode")) or "sequential",
            "maxConcurrency": int(raw_orchestration.get("maxConcurrency", 1) or 1),
            "timeoutSeconds": int(raw_orchestration.get("timeoutSeconds", 600) or 600),
            "failurePolicy": _clean_text(raw_orchestration.get("failurePolicy")) or "continue",
        },
        "revision": revision,
        "createdAt": created_at,
        "updatedAt": updated_at,
        **governance,
    }
    _validate_skill(skill, set())
    return skill


def _ensure_unique_name(
    candidate: Dict[str, Any],
    custom_skills: List[Dict[str, Any]],
    *,
    exclude_id: str = "",
) -> None:
    name_key = _compact(candidate.get("name"))
    for existing in [*list_builtin_skills(), *custom_skills]:
        if existing.get("id") != exclude_id and _compact(existing.get("name")) == name_key:
            raise SkillConflictError(f"Skill 名称已存在: {candidate.get('name', '')}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_custom_skill(
    payload: Dict[str, Any],
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    payload = copy.deepcopy(payload)
    if not principal.is_admin and payload.get("ownerId") not in (None, "", principal.user_id):
        raise SkillPermissionError("不能为其他用户创建 Skill")
    requested_team = str(payload.get("teamId") or "").strip()
    if requested_team and not principal.is_admin and requested_team not in principal.team_ids:
        raise SkillPermissionError("不能将 Skill 分配到当前用户未加入的团队")
    custom_skills = list_custom_skills()
    existing_ids = {skill["id"] for skill in [*list_builtin_skills(), *custom_skills]}
    skill_id = ""
    while not skill_id or skill_id in existing_ids:
        skill_id = f"custom-{uuid.uuid4().hex[:16]}"
    now = _utc_now()
    skill = _normalize_custom_skill(
        payload,
        skill_id=skill_id,
        created_at=now,
        updated_at=now,
        revision=1,
        actor=principal,
        legacy_defaults=actor is None,
    )
    _ensure_unique_name(skill, custom_skills)
    try:
        record = create_record(skill, now, actor_id=principal.user_id)
    except CustomSkillStoreConflict as exc:
        raise SkillConflictError(str(exc)) from exc
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    _validate_skill(record, set())
    return _decorate_skill(record, "custom", principal)


def update_custom_skill(
    skill_id: str,
    payload: Dict[str, Any],
    expected_revision: int,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    action: str = "update",
    change_note: str = "",
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    payload = copy.deepcopy(payload)
    if any(skill["id"] == skill_id for skill in list_builtin_skills()):
        raise SkillReadOnlyError("内置 Skill 为系统能力，不能修改")
    custom_skills = list_custom_skills()
    current = next((skill for skill in custom_skills if skill["id"] == skill_id), None)
    if not current:
        if get_custom_catalog_warning():
            raise SkillStoreUnavailableError(get_custom_catalog_warning())
        raise SkillNotFoundError(f"自定义 Skill 不存在: {skill_id}")
    permissions = skill_permissions(current, principal)
    if not permissions["editable"]:
        raise SkillPermissionError("当前用户没有编辑此 Skill 的权限")
    requested_status = str(payload.get("status") or current.get("status") or "draft").lower()
    if (
        requested_status == "published"
        and current.get("status") != "published"
        and not permissions["publishable"]
    ):
        raise SkillPermissionError("当前用户没有发布此 Skill 的权限")
    if (
        requested_status == "archived"
        and current.get("status") != "archived"
        and not permissions["deletable"]
    ):
        raise SkillPermissionError("当前用户没有归档此 Skill 的权限")
    requested_owner = str(payload.get("ownerId") or current.get("ownerId") or "")
    if requested_owner != current.get("ownerId") and not principal.is_admin:
        raise SkillPermissionError("只有管理员可以转移 Skill 归属")
    requested_team = str(payload.get("teamId") or current.get("teamId") or "")
    if requested_team and not principal.is_admin and requested_team not in principal.team_ids:
        raise SkillPermissionError("不能将 Skill 分配到当前用户未加入的团队")
    candidate = _normalize_custom_skill(
        payload,
        skill_id=skill_id,
        created_at=current.get("createdAt", ""),
        updated_at=_utc_now(),
        revision=expected_revision + 1,
        governance_source=current,
        actor=principal,
    )
    _ensure_unique_name(candidate, custom_skills, exclude_id=skill_id)
    try:
        record = update_record(
            skill_id,
            candidate,
            expected_revision,
            candidate["updatedAt"],
            actor_id=principal.user_id,
            action=action,
            change_note=change_note,
        )
    except CustomSkillStoreNotFound as exc:
        raise SkillNotFoundError(str(exc)) from exc
    except CustomSkillStoreConflict as exc:
        raise SkillConflictError(str(exc)) from exc
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    _validate_skill(record, set())
    return _decorate_skill(record, "custom", principal)


def delete_custom_skill(
    skill_id: str,
    expected_revision: int,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    if any(skill["id"] == skill_id for skill in list_builtin_skills()):
        raise SkillReadOnlyError("内置 Skill 为系统能力，不能删除")
    current = next(
        (
            skill
            for skill in list_custom_skills(principal, include_archived=True)
            if skill["id"] == skill_id
        ),
        None,
    )
    if not current:
        # Administrators must still be able to remove a malformed row that the
        # defensive catalog loader intentionally skipped.
        if principal.is_admin and str(skill_id).startswith("custom-"):
            try:
                record = delete_record(
                    skill_id, expected_revision, actor_id=principal.user_id
                )
            except CustomSkillStoreNotFound as exc:
                raise SkillNotFoundError(str(exc)) from exc
            except CustomSkillStoreConflict as exc:
                raise SkillConflictError(str(exc)) from exc
            except CustomSkillStoreError as exc:
                raise SkillStoreUnavailableError(str(exc)) from exc
            return _decorate_skill(record, "custom", principal)
        if get_custom_catalog_warning():
            raise SkillStoreUnavailableError(get_custom_catalog_warning())
        raise SkillNotFoundError(f"自定义 Skill 不存在: {skill_id}")
    if not current["permissions"]["deletable"]:
        raise SkillPermissionError("当前用户没有删除此 Skill 的权限")
    try:
        record = delete_record(skill_id, expected_revision, actor_id=principal.user_id)
    except CustomSkillStoreNotFound as exc:
        raise SkillNotFoundError(str(exc)) from exc
    except CustomSkillStoreConflict as exc:
        raise SkillConflictError(str(exc)) from exc
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    return _decorate_skill(record, "custom", principal)


def update_skill_governance(
    skill_id: str,
    changes: Dict[str, Any],
    expected_revision: int,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Update ownership, visibility, lifecycle, tags, or template metadata."""

    allowed = {"ownerId", "teamId", "visibility", "status", "tags", "isTemplate"}
    unknown = set(changes) - allowed
    if unknown:
        raise SkillCatalogError(f"Unsupported governance fields: {', '.join(sorted(unknown))}")
    current = get_skill(skill_id, actor, include_archived=True)
    if not current:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    payload = copy.deepcopy(current)
    payload.update(copy.deepcopy(changes))
    action = "governance"
    if "status" in changes:
        action = str(changes["status"] or "governance")
    return update_custom_skill(
        skill_id,
        payload,
        expected_revision,
        actor,
        action=action,
    )


def list_skill_versions(
    skill_id: str,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    current = get_skill(skill_id, actor, include_archived=True)
    if not current:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if current.get("isBuiltIn"):
        snapshot = export_skill_definition(current)["skill"]
        return [
            {
                "skillId": skill_id,
                "version": 1,
                "revision": 1,
                "action": "builtin",
                "actorId": "system",
                "published": True,
                "createdAt": "",
                "snapshot": snapshot,
            }
        ]
    try:
        return list_version_records(skill_id)
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc


def get_skill_version(
    skill_id: str,
    version: int,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    current = get_skill(skill_id, actor, include_archived=True)
    if not current:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if current.get("isBuiltIn"):
        if int(version) != 1:
            raise SkillNotFoundError(f"Skill 历史版本不存在: {skill_id}@{version}")
        return list_skill_versions(skill_id, actor)[0]
    try:
        record = get_version_record(skill_id, int(version))
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    if not record:
        raise SkillNotFoundError(f"Skill 历史版本不存在: {skill_id}@{version}")
    return record


def publish_custom_skill(
    skill_id: str,
    expected_revision: int,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    change_note: str = "",
) -> Dict[str, Any]:
    current = get_skill(skill_id, actor, include_archived=True)
    if not current:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if current.get("isBuiltIn"):
        raise SkillReadOnlyError("内置 Skill 已由系统发布")
    if not current["permissions"]["publishable"]:
        raise SkillPermissionError("当前用户没有发布此 Skill 的权限")
    if current.get("isTemplate"):
        raise SkillCatalogError("模板不能直接发布为可执行 Skill，请先从模板创建副本")
    payload = copy.deepcopy(current)
    payload["status"] = "published"
    return update_custom_skill(
        skill_id,
        payload,
        expected_revision,
        actor,
        action="publish",
        change_note=change_note,
    )


def archive_custom_skill(
    skill_id: str,
    expected_revision: int,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    current = get_skill(skill_id, actor, include_archived=True)
    if not current:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if current.get("isBuiltIn"):
        raise SkillReadOnlyError("内置 Skill 不能归档")
    if not current["permissions"]["deletable"]:
        raise SkillPermissionError("当前用户没有归档此 Skill 的权限")
    payload = copy.deepcopy(current)
    payload["status"] = "archived"
    return update_custom_skill(
        skill_id,
        payload,
        expected_revision,
        actor,
        action="archive",
    )


def rollback_custom_skill(
    skill_id: str,
    version: int,
    expected_revision: int,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    change_note: str = "",
) -> Dict[str, Any]:
    current = get_skill(skill_id, actor, include_archived=True)
    if not current:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if current.get("isBuiltIn"):
        raise SkillReadOnlyError("内置 Skill 不能回滚")
    if not current["permissions"]["editable"]:
        raise SkillPermissionError("当前用户没有回滚此 Skill 的权限")
    historical = get_skill_version(skill_id, int(version), actor)
    payload = copy.deepcopy(historical["snapshot"])
    # A rollback restores definition and lifecycle, but never transfers the
    # current security owner as a side effect of historical data.
    payload["ownerId"] = current.get("ownerId")
    payload["teamId"] = current.get("teamId")
    payload["visibility"] = current.get("visibility")
    return update_custom_skill(
        skill_id,
        payload,
        expected_revision,
        actor,
        action=f"rollback:{int(version)}",
        change_note=change_note,
    )


def set_skill_favorite(
    skill_id: str,
    favorite: bool,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    if not get_skill(skill_id, principal, include_archived=True):
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    try:
        value = set_favorite_record(
            principal.user_id,
            skill_id,
            bool(favorite),
            _utc_now(),
        )
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    return {"skillId": skill_id, "userId": principal.user_id, "favorite": value}


def list_favorite_skill_ids(
    actor: SkillActor | Dict[str, Any] | None = None,
) -> List[str]:
    principal = coerce_skill_actor(actor)
    try:
        stored = list_favorite_records(principal.user_id)
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    visible = {
        skill["id"] for skill in list_skills(principal, include_archived=True)
    }
    return [skill_id for skill_id in stored if skill_id in visible]


def _next_copy_name(name: str) -> str:
    existing = {_compact(skill.get("name")) for skill in list_skills(include_archived=True)}
    base = str(name or "Skill").strip()[:72]
    candidate = f"{base} 副本"
    suffix = 2
    while _compact(candidate) in existing:
        candidate = f"{base[:68]} 副本 {suffix}"
        suffix += 1
    return candidate[:80]


def duplicate_skill(
    skill_id: str,
    overrides: Optional[Dict[str, Any]] = None,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    as_template: bool = False,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    source = get_skill(skill_id, principal, include_archived=False)
    if not source:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    payload = export_skill_definition(source, include_governance=False)["skill"]
    payload.update(copy.deepcopy(overrides or {}))
    payload.setdefault("name", _next_copy_name(source.get("name", "Skill")))
    if payload["name"] == source.get("name"):
        payload["name"] = _next_copy_name(payload["name"])
    payload["ownerId"] = principal.user_id
    payload.setdefault("teamId", "")
    payload.setdefault("visibility", "private")
    payload.setdefault("status", "draft")
    payload["isTemplate"] = bool(as_template or payload.get("isTemplate"))
    if payload["isTemplate"]:
        payload["status"] = "draft"
    return create_custom_skill(payload, principal)


def create_skill_from_template(
    template_id: str,
    overrides: Optional[Dict[str, Any]] = None,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    template = get_skill(template_id, actor)
    if not template or not template.get("isTemplate"):
        raise SkillNotFoundError(f"Skill 模板不存在或不可见: {template_id}")
    merged = dict(overrides or {})
    merged["isTemplate"] = False
    merged.setdefault("status", "draft")
    return duplicate_skill(template_id, merged, actor, as_template=False)


def list_skill_templates(
    actor: SkillActor | Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    return list_skills(actor, template=True)


def _parse_expiry(value: str) -> datetime:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("empty expiry")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def create_skill_share(
    skill_id: str,
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    expires_at: str = "",
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    skill = get_skill(skill_id, principal, include_archived=False)
    if not skill:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if not skill["permissions"]["shareable"]:
        raise SkillPermissionError("当前用户没有分享此 Skill 的权限")
    if expires_at:
        try:
            expiry = _parse_expiry(expires_at)
        except (TypeError, ValueError) as exc:
            raise SkillCatalogError("expiresAt must be an ISO-8601 timestamp") from exc
        if expiry <= datetime.now(timezone.utc):
            raise SkillCatalogError("expiresAt must be in the future")
        expires_at = expiry.isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        return create_share_record(
            secrets.token_urlsafe(24),
            skill_id,
            principal.user_id,
            _utc_now(),
            expires_at,
        )
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc


def list_skill_shares(
    skill_id: str,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    principal = coerce_skill_actor(actor)
    skill = get_skill(skill_id, principal, include_archived=True)
    if not skill:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    if not skill["permissions"]["shareable"]:
        raise SkillPermissionError("当前用户没有管理此 Skill 分享的权限")
    try:
        shares = list_share_records(skill_id)
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    if skill.get("isBuiltIn") and not principal.is_admin:
        shares = [share for share in shares if share["createdBy"] == principal.user_id]
    return shares


def resolve_skill_share(token: str) -> Dict[str, Any]:
    try:
        share = get_share_record(str(token or "").strip())
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    if not share or share.get("revokedAt"):
        raise SkillNotFoundError("Skill 分享不存在或已撤销")
    if share.get("expiresAt"):
        try:
            expired = _parse_expiry(share["expiresAt"]) <= datetime.now(timezone.utc)
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise SkillNotFoundError("Skill 分享已过期")
    # The random token is the authorization grant. Use the compatibility admin
    # view after validating it rather than applying the recipient's identity.
    skill = get_skill(share["skillId"], include_archived=False)
    if not skill:
        raise SkillNotFoundError("分享的 Skill 已不存在或已归档")
    shared_permissions = {
        "visible": True,
        "editable": False,
        "publishable": False,
        "deletable": False,
        "shareable": False,
    }
    skill["permissions"] = shared_permissions
    skill["editable"] = False
    skill["deletable"] = False
    skill["publishable"] = False
    skill["shareable"] = False
    skill["favorite"] = False
    skill["shared"] = True
    result = dict(share)
    result["skill"] = skill
    return result


def revoke_skill_share(
    token: str,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    try:
        share = get_share_record(str(token or "").strip())
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc
    if not share:
        raise SkillNotFoundError("Skill 分享不存在")
    skill = get_skill(share["skillId"], principal, include_archived=True)
    can_manage = principal.is_admin or share["createdBy"] == principal.user_id
    can_manage = can_manage or bool(skill and skill["permissions"]["shareable"])
    if not can_manage:
        raise SkillPermissionError("当前用户没有撤销此分享的权限")
    try:
        return revoke_share_record(share["token"], _utc_now())
    except CustomSkillStoreNotFound as exc:
        raise SkillNotFoundError(str(exc)) from exc
    except CustomSkillStoreError as exc:
        raise SkillStoreUnavailableError(str(exc)) from exc


def export_skill(
    skill_id: str,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    skill = get_skill(skill_id, actor, include_archived=True)
    if not skill:
        raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
    return export_skill_definition(skill)


def export_skill_catalog(
    skill_ids: Iterable[str],
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    skills = []
    for skill_id in skill_ids:
        skill = get_skill(str(skill_id), actor, include_archived=True)
        if not skill:
            raise SkillNotFoundError(f"Skill 不存在或不可见: {skill_id}")
        skills.append(skill)
    return export_skill_bundle(skills, exported_at=_utc_now())


def import_skill_definitions(
    document: str | Dict[str, Any] | List[Any],
    actor: SkillActor | Dict[str, Any] | None = None,
    *,
    conflict_policy: str = "rename",
) -> Dict[str, Any]:
    """Validate and persist a portable document.

    ``rename`` keeps every valid definition, ``skip`` records conflicts in the
    response, and ``error`` fails immediately. Each created Skill still uses
    the store's optimistic, process-safe uniqueness constraint.
    """

    policy = str(conflict_policy or "rename").strip().lower()
    if policy not in {"rename", "skip", "error"}:
        raise SkillCatalogError("conflictPolicy must be rename, skip, or error")
    try:
        definitions = parse_skill_import(document)
    except SkillImportFormatError as exc:
        raise SkillCatalogError(str(exc)) from exc

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for definition in definitions:
        candidate = copy.deepcopy(definition)
        try:
            created.append(create_custom_skill(candidate, actor))
        except SkillConflictError as exc:
            if policy == "error":
                raise
            if policy == "skip":
                skipped.append({"name": candidate.get("name", ""), "reason": str(exc)})
                continue
            candidate["name"] = _next_copy_name(str(candidate.get("name") or "Skill"))
            created.append(create_custom_skill(candidate, actor))
    return {"created": created, "skipped": skipped}


def _dataset_score(dataset: Dict[str, Any], keywords: Iterable[str]) -> tuple[int, str]:
    raw_name = dataset.get("name")
    raw_table = dataset.get("tableName")
    raw_description = dataset.get("description")
    name = _text(raw_name)
    table = _text(raw_table)
    description = _text(raw_description)
    name_compact = _compact(name)
    table_compact = _compact(table)
    description_compact = _compact(description)

    best_score = 0
    best_keyword = ""
    for raw_keyword in keywords:
        keyword = _text(raw_keyword)
        compact_keyword = _compact(keyword)
        if not compact_keyword:
            continue

        score = 0
        if table_compact and compact_keyword == table_compact:
            score = 120
        elif _field_matches_keyword(raw_table, raw_keyword):
            score = 80
        if name_compact and compact_keyword == name_compact:
            score = max(score, 100)
        elif _field_matches_keyword(raw_name, raw_keyword):
            score = max(score, 70)
        if description_compact and _field_matches_keyword(raw_description, raw_keyword):
            score = max(score, 35)

        if score > best_score:
            best_score = score
            best_keyword = raw_keyword
    return best_score, best_keyword


def resolve_skill_datasets(
    skill: Dict[str, Any], datasets: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Resolve each Skill step to one dataset while preserving declared order.

    A dataset is never guessed when no configured semantic keyword matches. This
    prevents a Skill from silently querying an unrelated table. A dataset is used
    at most once unless a step explicitly sets ``allowReuse``.
    """
    resolved: List[Dict[str, Any]] = []
    used_ids: set[str] = set()

    for sequence, step in enumerate(skill.get("steps", []), start=1):
        candidates = []
        configured_dataset_id = str(step.get("datasetId") or "").strip()
        for dataset in datasets:
            # A named dataset without a physical table cannot be executed by a
            # dataset_query stage and must not make a Skill appear available.
            if not _text(dataset.get("tableName")):
                continue
            dataset_key = str(dataset.get("id") or dataset.get("tableName") or dataset.get("name"))
            if dataset_key in used_ids and not step.get("allowReuse"):
                continue
            if configured_dataset_id:
                if str(dataset.get("id") or "") != configured_dataset_id:
                    continue
                score, keyword = 1000, configured_dataset_id
            else:
                score, keyword = _dataset_score(dataset, step.get("datasetKeywords", []))
            if score:
                candidates.append((score, _text(dataset.get("name")), dataset, keyword, dataset_key))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        if candidates:
            score, _, dataset, keyword, dataset_key = candidates[0]
            used_ids.add(dataset_key)
            match = {
                "sequence": sequence,
                "step": copy.deepcopy(step),
                "dataset": copy.deepcopy(dataset),
                "score": score,
                "matchedKeyword": keyword,
            }
        else:
            match = {
                "sequence": sequence,
                "step": copy.deepcopy(step),
                "dataset": None,
                "score": 0,
                "matchedKeyword": "",
            }
        resolved.append(match)
    return resolved


def skill_availability(skill: Dict[str, Any], datasets: List[Dict[str, Any]]) -> Dict[str, Any]:
    resolved = resolve_skill_datasets(skill, datasets)
    matched = [item for item in resolved if item["dataset"]]
    return {
        "matchedSteps": len(matched),
        "totalSteps": len(resolved),
        "available": bool(matched),
        "complete": len(matched) == len(resolved),
        "datasetPlan": [
            {
                "sequence": item["sequence"],
                "stepId": item["step"]["id"],
                "stepName": item["step"]["name"],
                "datasetId": item["dataset"].get("id", "") if item["dataset"] else "",
                "datasetName": item["dataset"].get("name", "") if item["dataset"] else "",
                "tableName": item["dataset"].get("tableName", "") if item["dataset"] else "",
                "matched": bool(item["dataset"]),
            }
            for item in resolved
        ],
    }


def recommend_skills(
    query: str,
    limit: int = 3,
    datasets: Optional[List[Dict[str, Any]]] = None,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Return deterministic recommendations enriched by data completeness.

    Text relevance remains the primary signal. When datasets are supplied, a
    complete executable plan receives a modest boost and every result explains
    its matched/total step count. Omitting datasets preserves the legacy score.
    """
    normalized_query = _compact(query)
    ranked = []
    candidates = list_skills(actor, statuses=["published"], template=False)
    for position, skill in enumerate(candidates):
        relevance_score = 0
        matched_triggers = []
        for trigger in skill.get("triggers", []):
            if _compact(trigger) and _compact(trigger) in normalized_query:
                relevance_score += 100 + len(_compact(trigger))
                matched_triggers.append(trigger)

        if _compact(skill["name"]) in normalized_query:
            relevance_score += 80
        for step in skill.get("steps", []):
            for keyword in step.get("datasetKeywords", []):
                compact_keyword = _compact(keyword)
                if len(compact_keyword) >= 2 and compact_keyword in normalized_query:
                    relevance_score += 8

        if relevance_score:
            item = copy.deepcopy(skill)
            score = relevance_score
            if datasets is not None:
                availability = skill_availability(skill, datasets)
                total = max(1, availability["totalSteps"])
                completeness = availability["matchedSteps"] / total
                availability_boost = round(completeness * 30)
                if availability["complete"]:
                    availability_boost += 15
                score += availability_boost
                item["availability"] = availability
                item["dataCompleteness"] = round(completeness, 4)
                item["availabilityScore"] = availability_boost
            item["score"] = score
            item["recommendationScore"] = score
            item["relevanceScore"] = relevance_score
            item["matchedTriggers"] = matched_triggers
            ranked.append((score, position, item))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[: max(1, min(limit, 10))]]
