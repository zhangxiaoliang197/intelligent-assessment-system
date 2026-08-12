"""Safe Markdown round-trip editing for evaluation Skills.

Built-in files use the image catalog as a baseline and persist edits in a
writable override layer.  Custom Skills are serialized to Markdown and saved
back through the governed SQLite catalog, preserving permissions and revision
history.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from .skill_catalog import (
    SkillCatalogError,
    SkillConflictError,
    SkillNotFoundError,
    SkillPermissionError,
    SkillStoreUnavailableError,
    _validate_skill,
    clear_catalog_cache,
    get_catalog_directory,
    get_markdown_override_directory,
    get_skill,
    load_catalog,
    update_custom_skill,
)
from .skill_governance import SkillActor, coerce_skill_actor


MAX_MARKDOWN_BYTES = 128 * 1024
_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FORBIDDEN_METADATA_KEYS = {
    "sql", "querytemplate", "tablename", "connectionstring",
    "password", "secret", "token", "apikey", "api-key",
}
_DEFINITION_FIELDS = (
    "id", "name", "description", "category", "triggers",
    "recommendedQuestions", "steps", "outputInstruction",
    "visualization", "orchestration",
)
_ALLOWED_METADATA_FIELDS = {*_DEFINITION_FIELDS, "order"}
_WRITE_LOCK = threading.RLock()


def _utc_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_content(content: Any) -> str:
    if not isinstance(content, str):
        raise SkillCatalogError("Skill Markdown content must be a string")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if not normalized.strip():
        raise SkillCatalogError("Skill Markdown content cannot be empty")
    if len(normalized.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise SkillCatalogError("Skill Markdown cannot exceed 128 KB")
    if "\x00" in normalized:
        raise SkillCatalogError("Skill Markdown contains unsupported control characters")
    return normalized.rstrip() + "\n"


def _parse_markdown(content: str, skill_id: str) -> Tuple[Dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillCatalogError("Skill Markdown must start with YAML front matter")
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise SkillCatalogError("Skill Markdown front matter is not closed") from exc
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as exc:
        raise SkillCatalogError(f"Skill Markdown front matter is not valid YAML: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SkillCatalogError("Skill Markdown front matter must be an object")
    if str(metadata.get("id") or "") != skill_id:
        raise SkillCatalogError("Markdown id must match the current Skill id")
    body = "\n".join(lines[closing_index + 1:]).strip()
    first_body_line = body.splitlines()[0].strip() if body else ""
    if first_body_line != f"# {metadata.get('name', '')}":
        raise SkillCatalogError("Markdown body must start with a heading matching the Skill name")
    _reject_unsafe_metadata(metadata)
    unexpected_fields = sorted(set(metadata) - _ALLOWED_METADATA_FIELDS)
    if unexpected_fields:
        raise SkillCatalogError(
            "Skill Markdown front matter contains unsupported fields: "
            + ", ".join(str(field) for field in unexpected_fields)
        )
    return metadata, body


def _reject_unsafe_metadata(value: Any, path: str = "front matter") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = re.sub(r"[_\s]+", "", str(key).strip().lower())
            if normalized_key in _FORBIDDEN_METADATA_KEYS:
                raise SkillCatalogError(f"{path} cannot contain field: {key}")
            _reject_unsafe_metadata(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe_metadata(nested, f"{path}[{index}]")


def _custom_markdown(skill: Dict[str, Any]) -> str:
    metadata = {
        field: copy.deepcopy(skill[field])
        for field in _DEFINITION_FIELDS
        if field in skill
    }
    body = str(skill.get("markdownBody") or "").strip()
    if not body:
        step_sections = []
        for index, step in enumerate(skill.get("steps", []), start=1):
            keywords = "、".join(f"`{item}`" for item in step.get("datasetKeywords", []))
            step_sections.append(
                f"### {index}. {step.get('name', '')}\n\n"
                f"{step.get('description', '')}\n\n"
                f"- 步骤 ID：`{step.get('id', '')}`\n"
                f"- 数据集关键词：{keywords}\n"
                f"- 操作：`{step.get('operation', 'dataset_query')}`"
            )
        body = (
            f"# {skill.get('name', '')}\n\n"
            f"{skill.get('description', '')}\n\n"
            "## 执行步骤\n\n"
            + "\n\n".join(step_sections)
            + f"\n\n## 输出要求\n\n{skill.get('outputInstruction', '')}"
        )
    front_matter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).strip()
    return f"---\n{front_matter}\n---\n\n{body.strip()}\n"


def _baseline_path(skill_id: str) -> Path:
    if not _SKILL_ID_PATTERN.fullmatch(skill_id):
        raise SkillNotFoundError("Skill id is invalid")
    root = Path(get_catalog_directory()).resolve()
    candidate = (root / skill_id / "SKILL.md").resolve()
    if root not in candidate.parents:
        raise SkillNotFoundError("Skill Markdown path is invalid")
    return candidate


def _override_path(skill_id: str) -> Path:
    root = Path(get_markdown_override_directory()).resolve()
    candidate = (root / skill_id / "SKILL.md").resolve()
    if root not in candidate.parents:
        raise SkillNotFoundError("Skill Markdown override path is invalid")
    return candidate


def _read_builtin_content(skill_id: str) -> Tuple[str, Path, bool]:
    override = _override_path(skill_id)
    source = override if override.is_file() else _baseline_path(skill_id)
    try:
        return source.read_text(encoding="utf-8"), source, source == override
    except FileNotFoundError as exc:
        raise SkillNotFoundError(f"Skill Markdown does not exist: {skill_id}") from exc
    except OSError as exc:
        raise SkillStoreUnavailableError(f"Unable to read Skill Markdown: {exc}") from exc


def get_skill_markdown(
    skill_id: str,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    skill = get_skill(skill_id, principal, include_archived=True)
    if not skill:
        raise SkillNotFoundError(f"Skill does not exist or is not visible: {skill_id}")
    if skill.get("source") == "builtin":
        content, source_path, overridden = _read_builtin_content(skill_id)
        relative_path = (
            f"data/skill-markdown-overrides/{skill_id}/SKILL.md"
            if overridden
            else f"config/skills/{skill_id}/SKILL.md"
        )
        try:
            last_modified = _utc_from_timestamp(source_path.stat().st_mtime)
        except OSError:
            last_modified = ""
        # SKILL.md 在线编辑对所有登录用户开放（仍受字段安全校验与顺序约束）。
        editable = True
        storage = "override" if overridden else "catalog"
    else:
        content = _custom_markdown(skill)
        relative_path = f"custom-skills/{skill_id}/SKILL.md"
        last_modified = str(skill.get("updatedAt") or skill.get("createdAt") or "")
        editable = True
        storage = "custom"
        overridden = False
    content = _normalize_content(content)
    return {
        "skillId": skill_id,
        "skillName": skill.get("name", skill_id),
        "source": skill.get("source", "builtin"),
        "content": content,
        "contentHash": _digest(content),
        "editable": editable,
        "storage": storage,
        "overridden": overridden,
        "relativePath": relative_path,
        "revision": int(skill.get("revision") or 1),
        "lastModified": last_modified,
    }


def _validate_builtin_candidate(skill_id: str, metadata: Dict[str, Any], body: str) -> None:
    order = metadata.get("order")
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        raise SkillCatalogError("Built-in Skill Markdown requires a positive integer order")
    candidate = copy.deepcopy(metadata)
    candidate.pop("order", None)
    _validate_skill(candidate, set())
    if not body or body.splitlines()[0].strip() != f"# {candidate['name']}":
        raise SkillCatalogError("Markdown body heading does not match the Skill name")

    current_content, _, _ = _read_builtin_content(skill_id)
    current_metadata, _ = _parse_markdown(_normalize_content(current_content), skill_id)
    if int(current_metadata.get("order") or 0) != order:
        raise SkillCatalogError("Online editing cannot change a built-in Skill order")
    for existing in load_catalog()["skills"]:
        if existing["id"] != skill_id and str(existing.get("name") or "").casefold() == str(
            candidate.get("name") or ""
        ).casefold():
            raise SkillConflictError(f"Skill name already exists: {candidate['name']}")


def _atomic_write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as exc:
        raise SkillStoreUnavailableError(f"Unable to save Skill Markdown: {exc}") from exc


def update_skill_markdown(
    skill_id: str,
    content: str,
    expected_hash: str,
    actor: SkillActor | Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    principal = coerce_skill_actor(actor)
    with _WRITE_LOCK:
        return _update_skill_markdown_locked(skill_id, content, expected_hash, principal)


def _update_skill_markdown_locked(
    skill_id: str,
    content: str,
    expected_hash: str,
    principal: SkillActor,
) -> Dict[str, Any]:
    current_document = get_skill_markdown(skill_id, principal)
    if not current_document["editable"]:
        raise SkillPermissionError("Current user cannot edit this Skill Markdown")
    if expected_hash != current_document["contentHash"]:
        raise SkillConflictError("Skill Markdown has changed; reload it before saving")

    normalized = _normalize_content(content)
    metadata, body = _parse_markdown(normalized, skill_id)
    if current_document["source"] == "builtin":
        _validate_builtin_candidate(skill_id, metadata, body)
        override_path = _override_path(skill_id)
        previous_override = None
        if override_path.is_file():
            try:
                previous_override = override_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise SkillStoreUnavailableError(
                    f"Unable to read the current Skill Markdown override: {exc}"
                ) from exc
        _atomic_write(override_path, normalized)
        clear_catalog_cache()
        # Loading the whole catalog after the atomic write guarantees that one
        # edit cannot silently break another built-in Skill.
        try:
            load_catalog()
        except SkillCatalogError:
            if previous_override is None:
                try:
                    override_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise SkillStoreUnavailableError(
                        f"Unable to roll back invalid Skill Markdown: {exc}"
                    ) from exc
            else:
                _atomic_write(override_path, previous_override)
            clear_catalog_cache()
            raise
    else:
        candidate = {
            field: copy.deepcopy(metadata[field])
            for field in _DEFINITION_FIELDS
            if field != "id" and field in metadata
        }
        candidate["markdownBody"] = body
        update_custom_skill(
            skill_id,
            candidate,
            int(current_document["revision"]),
            principal,
            action="markdown-update",
            change_note="在线编辑 SKILL.md",
            allow_any_editor=True,
        )
    return get_skill_markdown(skill_id, principal)
