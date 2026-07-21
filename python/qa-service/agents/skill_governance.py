"""Access policy and portable import/export helpers for evaluation Skills.

The module deliberately has no dependency on :mod:`skill_catalog` or the
SQLite store.  Policy decisions and document parsing can therefore be unit
tested and reused by HTTP, CLI and background-job entry points.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence


VISIBILITIES = frozenset({"private", "team", "public"})
SKILL_STATUSES = frozenset({"draft", "published", "archived"})
ADMIN_ROLES = frozenset({"admin", "system-admin", "super-admin"})
TEAM_EDIT_ROLES = frozenset({"editor", "publisher", "team-admin", "team-owner"})
TEAM_PUBLISH_ROLES = frozenset({"publisher", "team-admin", "team-owner"})
TEAM_DELETE_ROLES = frozenset({"team-admin", "team-owner"})


class SkillImportFormatError(ValueError):
    """Raised when a portable Skill document has an unsupported shape."""


@dataclass(frozen=True)
class SkillActor:
    """Authenticated principal used by catalog access checks.

    ``local-admin`` is intentional: callers that have not adopted identity
    headers retain the pre-governance, single-user behaviour.
    """

    user_id: str = "local-admin"
    role: str = "admin"
    team_ids: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return _role_key(self.role) in ADMIN_ROLES


def _role_key(value: Any) -> str:
    return re.sub(r"[_\s]+", "-", str(value or "").strip().lower())


def _clean_team_ids(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
        return ()
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        team_id = str(value or "").strip()
        if team_id and team_id not in seen:
            cleaned.append(team_id)
            seen.add(team_id)
    return tuple(cleaned)


def coerce_skill_actor(actor: SkillActor | Mapping[str, Any] | None = None) -> SkillActor:
    """Return a normalized actor while keeping legacy callers privileged."""

    if actor is None:
        return SkillActor()
    if isinstance(actor, SkillActor):
        return SkillActor(
            user_id=str(actor.user_id or "anonymous").strip() or "anonymous",
            role=_role_key(actor.role) or "viewer",
            team_ids=_clean_team_ids(actor.team_ids),
        )
    if not isinstance(actor, Mapping):
        raise TypeError("actor must be a SkillActor, mapping, or None")
    return SkillActor(
        user_id=str(
            actor.get("user_id")
            or actor.get("userId")
            or actor.get("id")
            or "anonymous"
        ).strip()
        or "anonymous",
        role=_role_key(actor.get("role")) or "viewer",
        team_ids=_clean_team_ids(actor.get("team_ids", actor.get("teamIds"))),
    )


def normalize_governance(
    values: Mapping[str, Any] | None,
    *,
    actor: SkillActor | Mapping[str, Any] | None = None,
    legacy_defaults: bool = False,
) -> Dict[str, Any]:
    """Normalize governance fields without mutating the supplied mapping."""

    source = values or {}
    principal = coerce_skill_actor(actor)
    owner_id = str(source.get("ownerId") or source.get("owner_id") or principal.user_id).strip()
    team_id = str(source.get("teamId") or source.get("team_id") or "").strip()
    visibility = str(
        source.get("visibility") or ("public" if legacy_defaults else "private")
    ).strip().lower()
    status = str(
        source.get("status") or ("published" if legacy_defaults else "draft")
    ).strip().lower()
    if visibility not in VISIBILITIES:
        raise ValueError("visibility must be private, team, or public")
    if status not in SKILL_STATUSES:
        raise ValueError("status must be draft, published, or archived")
    if not owner_id or len(owner_id) > 128:
        raise ValueError("ownerId must contain 1 to 128 characters")
    if len(team_id) > 128:
        raise ValueError("teamId must not exceed 128 characters")
    if re.search(r"[\x00-\x1f\x7f]", owner_id + team_id):
        raise ValueError("ownerId and teamId must not contain control characters")
    if visibility == "team" and not team_id:
        raise ValueError("teamId is required when visibility is team")

    raw_tags = source.get("tags", [])
    if raw_tags is None:
        raw_tags = []
    if not isinstance(raw_tags, Sequence) or isinstance(raw_tags, (str, bytes)):
        raise ValueError("tags must be a list")
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            raise ValueError("each tag must be a string")
        tag = raw_tag.strip()
        key = tag.casefold()
        if not tag or key in seen:
            continue
        if len(tag) > 40:
            raise ValueError("each tag must not exceed 40 characters")
        if re.search(r"[\x00-\x1f\x7f]", tag):
            raise ValueError("tags must not contain control characters")
        tags.append(tag)
        seen.add(key)
    if len(tags) > 20:
        raise ValueError("tags must not exceed 20 items")

    raw_template = source.get("isTemplate", source.get("is_template", False))
    if not isinstance(raw_template, bool):
        raise ValueError("isTemplate must be a boolean")

    return {
        "ownerId": owner_id or principal.user_id,
        "teamId": team_id,
        "visibility": visibility,
        "status": status,
        "tags": tags,
        "isTemplate": raw_template,
    }


def skill_permissions(
    skill: Mapping[str, Any],
    actor: SkillActor | Mapping[str, Any] | None = None,
) -> Dict[str, bool]:
    """Compute view and mutation permissions for one decorated or raw Skill."""

    principal = coerce_skill_actor(actor)
    built_in = bool(skill.get("isBuiltIn")) or skill.get("source") == "builtin"
    if built_in:
        return {
            "visible": True,
            "editable": False,
            "publishable": False,
            "deletable": False,
            "shareable": True,
        }

    owner = str(skill.get("ownerId") or "local-admin") == principal.user_id
    team_id = str(skill.get("teamId") or "")
    in_team = bool(team_id) and team_id in principal.team_ids
    role = _role_key(principal.role)
    status = str(skill.get("status") or "published").lower()
    visibility = str(skill.get("visibility") or "public").lower()

    if principal.is_admin:
        visible = editable = publishable = deletable = shareable = True
    else:
        visible = owner
        if status != "archived":
            visible = visible or (visibility == "team" and in_team)
            visible = visible or (visibility == "public" and status == "published")
        elif in_team and role in TEAM_DELETE_ROLES:
            visible = True

        editable = owner or (in_team and role in TEAM_EDIT_ROLES)
        publishable = owner or (in_team and role in TEAM_PUBLISH_ROLES)
        deletable = owner or (in_team and role in TEAM_DELETE_ROLES)
        shareable = owner or (in_team and role in TEAM_PUBLISH_ROLES)

    return {
        "visible": bool(visible),
        "editable": bool(editable),
        "publishable": bool(publishable),
        "deletable": bool(deletable),
        "shareable": bool(shareable),
    }


_PORTABLE_FIELDS = (
    "name",
    "description",
    "category",
    "triggers",
    "recommendedQuestions",
    "steps",
    "outputInstruction",
    "orchestration",
    "teamId",
    "visibility",
    "status",
    "tags",
    "isTemplate",
)


def export_skill_definition(
    skill: Mapping[str, Any], *, include_governance: bool = True
) -> Dict[str, Any]:
    """Return a portable definition with IDs and revision metadata removed."""

    allowed = _PORTABLE_FIELDS if include_governance else _PORTABLE_FIELDS[:8]
    definition = {
        field: copy.deepcopy(skill[field])
        for field in allowed
        if field in skill
    }
    return {"schemaVersion": 1, "kind": "evaluation-skill", "skill": definition}


def export_skill_bundle(
    skills: Iterable[Mapping[str, Any]], *, exported_at: str = ""
) -> Dict[str, Any]:
    """Return a stable multi-Skill exchange document."""

    document: Dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "evaluation-skill-bundle",
        "skills": [export_skill_definition(skill)["skill"] for skill in skills],
    }
    if exported_at:
        document["exportedAt"] = exported_at
    return document


def parse_skill_import(document: str | Mapping[str, Any] | Sequence[Any]) -> list[Dict[str, Any]]:
    """Parse a portable Skill/bundle document into detached definitions."""

    value: Any = document
    if isinstance(document, str):
        try:
            value = json.loads(document)
        except json.JSONDecodeError as exc:
            raise SkillImportFormatError(f"Skill import is not valid JSON: {exc.msg}") from exc

    if isinstance(value, Mapping):
        if int(value.get("schemaVersion", 1)) != 1:
            raise SkillImportFormatError("Unsupported Skill import schemaVersion")
        if isinstance(value.get("skill"), Mapping):
            candidates: Any = [value["skill"]]
        elif isinstance(value.get("skills"), list):
            candidates = value["skills"]
        elif all(field in value for field in ("name", "steps", "outputInstruction")):
            candidates = [value]
        else:
            raise SkillImportFormatError("Skill import must contain skill or skills")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        candidates = value
    else:
        raise SkillImportFormatError("Skill import must be an object, list, or JSON string")

    if not candidates:
        raise SkillImportFormatError("Skill import does not contain any definitions")
    if len(candidates) > 100:
        raise SkillImportFormatError("Skill import cannot contain more than 100 definitions")

    results: list[Dict[str, Any]] = []
    for position, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, Mapping):
            raise SkillImportFormatError(f"Skill import item {position} must be an object")
        definition = {
            field: copy.deepcopy(candidate[field])
            for field in _PORTABLE_FIELDS
            if field in candidate
        }
        results.append(definition)
    return results
