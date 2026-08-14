"""Safe SKILL.md round-trip support for situation-map Skills."""

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

from .catalog import (
    SkillCatalogError,
    _MARKDOWN_DEFINITION_FIELDS,
    _validate_skill,
    clear_catalog_cache,
    get_markdown_override_directory,
    get_skill,
    list_skills,
    update_skill_definition,
)


MAX_MARKDOWN_BYTES = 128 * 1024
_SKILL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FORBIDDEN_KEYS = {
    "sql", "querytemplate", "tablename", "connectionstring",
    "password", "secret", "token", "apikey", "api-key", "systemprompt",
}
_WRITE_LOCK = threading.RLock()


def _normalize_content(content: Any) -> str:
    if not isinstance(content, str):
        raise SkillCatalogError("Skill Markdown 必须是文本")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if not normalized.strip():
        raise SkillCatalogError("Skill Markdown 不能为空")
    if len(normalized.encode("utf-8")) > MAX_MARKDOWN_BYTES:
        raise SkillCatalogError("Skill Markdown 不能超过 128 KB")
    if "\x00" in normalized:
        raise SkillCatalogError("Skill Markdown 包含不支持的控制字符")
    return normalized.rstrip() + "\n"


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _reject_unsafe_fields(value: Any, path: str = "YAML") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = re.sub(r"[_\s]+", "", str(key).strip().lower())
            if normalized_key in _FORBIDDEN_KEYS:
                raise SkillCatalogError(f"{path} 不允许包含字段: {key}")
            _reject_unsafe_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe_fields(nested, f"{path}[{index}]")


def _parse_markdown(content: str, skill_id: str) -> Tuple[Dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillCatalogError("Skill Markdown 必须以 YAML 头部开始")
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise SkillCatalogError("Skill Markdown YAML 头部未闭合") from exc
    try:
        metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as exc:
        raise SkillCatalogError(f"Skill Markdown YAML 格式无效: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SkillCatalogError("Skill Markdown YAML 必须是对象")
    if metadata.get("id") != skill_id:
        raise SkillCatalogError("Markdown id 必须与当前 Skill id 一致")
    _reject_unsafe_fields(metadata)
    unexpected = sorted(set(metadata) - _MARKDOWN_DEFINITION_FIELDS)
    if unexpected:
        raise SkillCatalogError(f"Skill Markdown 包含不支持字段: {', '.join(unexpected)}")
    _validate_skill(metadata, set())
    body = "\n".join(lines[closing_index + 1:]).strip()
    first_line = body.splitlines()[0].strip() if body else ""
    if first_line != f"# {metadata['name']}":
        raise SkillCatalogError("Markdown 正文一级标题必须与 Skill name 一致")
    return metadata, body


def _default_body(skill: Dict[str, Any]) -> str:
    steps = "\n".join(
        f"{index}. {step}" for index, step in enumerate(skill.get("steps", []), start=1)
    )
    return (
        f"# {skill.get('name', '')}\n\n"
        f"{skill.get('description', '')}\n\n"
        f"## 分析目标\n\n{skill.get('analysisGoal', '')}\n\n"
        f"## 执行步骤\n\n{steps}\n\n"
        "## 数据与输出\n\n"
        f"- 数据源：{'、'.join(skill.get('dataSources', []))}\n"
        f"- 重点指标：{'、'.join(skill.get('focusMetrics', []))}\n"
        f"- 图表类型：{'、'.join(skill.get('chartTypes', []))}\n"
        f"- 地图图层：{'、'.join(skill.get('mapLayerTypes', []))}"
    )


def _serialize_markdown(skill: Dict[str, Any]) -> str:
    metadata = {
        key: copy.deepcopy(skill[key])
        for key in skill
        if key in _MARKDOWN_DEFINITION_FIELDS
    }
    body = str(skill.get("markdownBody") or "").strip() or _default_body(skill)
    front_matter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).strip()
    return _normalize_content(f"---\n{front_matter}\n---\n\n{body}\n")


def _override_path(skill_id: str) -> Path:
    if not _SKILL_ID_RE.fullmatch(skill_id):
        raise SkillCatalogError("Skill id 不合法")
    root = get_markdown_override_directory().resolve()
    candidate = (root / skill_id / "SKILL.md").resolve()
    if root not in candidate.parents:
        raise SkillCatalogError("Skill Markdown 路径不合法")
    return candidate


def _atomic_write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as exc:
        raise SkillCatalogError(f"无法保存 Skill Markdown: {exc}") from exc


def _timestamp(path: Path) -> str:
    try:
        value = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return ""
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def get_skill_markdown(
    skill_id: str,
    user_id: str,
    *,
    is_admin: bool = False,
) -> Dict[str, Any]:
    skill = get_skill(skill_id, user_id, include_archived=True)
    if not skill:
        raise SkillCatalogError("态势图 Skill 不存在或当前用户无权查看")
    if skill.get("isBuiltIn"):
        override = _override_path(skill_id)
        if override.is_file():
            try:
                content = _normalize_content(override.read_text(encoding="utf-8"))
            except OSError as exc:
                raise SkillCatalogError(f"无法读取 Skill Markdown: {exc}") from exc
            storage = "override"
            overridden = True
            relative_path = f"data/situation-skill-markdown-overrides/{skill_id}/SKILL.md"
            last_modified = _timestamp(override)
        else:
            content = _serialize_markdown(skill)
            storage = "catalog"
            overridden = False
            relative_path = f"config/situation_skills.json#{skill_id}"
            last_modified = ""
        editable = is_admin and bool(user_id)
    else:
        content = _serialize_markdown(skill)
        storage = "custom"
        overridden = False
        relative_path = f"custom-skills/{skill_id}/SKILL.md"
        last_modified = str(skill.get("updatedAt") or skill.get("createdAt") or "")
        editable = skill.get("status") != "archived" and (
            (is_admin and bool(user_id)) or str(skill.get("ownerId") or "") == user_id
        )
    return {
        "skillId": skill_id,
        "skillName": skill.get("name", skill_id),
        "source": "builtin" if skill.get("isBuiltIn") else "custom",
        "content": content,
        "contentHash": _digest(content),
        "editable": bool(editable),
        "storage": storage,
        "overridden": overridden,
        "relativePath": relative_path,
        "revision": int(skill.get("revision") or 1),
        "lastModified": last_modified,
    }


def update_skill_markdown(
    skill_id: str,
    content: str,
    expected_hash: str,
    user_id: str,
    *,
    is_admin: bool = False,
) -> Dict[str, Any]:
    with _WRITE_LOCK:
        current_document = get_skill_markdown(skill_id, user_id, is_admin=is_admin)
        if not current_document["editable"]:
            raise SkillCatalogError("当前用户没有编辑此 Skill Markdown 的权限")
        if expected_hash != current_document["contentHash"]:
            raise SkillCatalogError("Skill Markdown 已被更新，请刷新后重试")
        normalized = _normalize_content(content)
        metadata, body = _parse_markdown(normalized, skill_id)

        if current_document["source"] == "builtin":
            current_skill = get_skill(skill_id, user_id)
            assert current_skill is not None
            if int(metadata.get("order") or 0) != int(current_skill.get("order") or 0):
                raise SkillCatalogError("在线编辑不能改变内置 Skill 顺序")
            duplicate = next(
                (
                    item for item in list_skills(limit=100, user_id=user_id, include_archived=True)
                    if item["id"] != skill_id
                    and str(item.get("name") or "").casefold() == str(metadata.get("name") or "").casefold()
                ),
                None,
            )
            if duplicate:
                raise SkillCatalogError(f"Skill 名称已存在: {metadata['name']}")
            override = _override_path(skill_id)
            previous = None
            if override.is_file():
                try:
                    previous = override.read_text(encoding="utf-8")
                except OSError as exc:
                    raise SkillCatalogError(f"无法读取当前 Markdown 覆盖文件: {exc}") from exc
            _atomic_write(override, normalized)
            clear_catalog_cache()
            try:
                get_skill(skill_id, user_id)
            except SkillCatalogError:
                if previous is None:
                    try:
                        override.unlink(missing_ok=True)
                    except OSError as exc:
                        raise SkillCatalogError(f"无法回滚无效 Markdown: {exc}") from exc
                else:
                    _atomic_write(override, previous)
                clear_catalog_cache()
                raise
        else:
            candidate = copy.deepcopy(metadata)
            candidate["markdownBody"] = body
            update_skill_definition(
                skill_id,
                candidate,
                user_id,
                expected_revision=int(current_document["revision"]),
                allow_any_editor=is_admin,
                # Editing an already published definition creates a draft revision. The
                # changed execution contract becomes public only after explicit publish.
                preserve_status=False,
            )
        return get_skill_markdown(skill_id, user_id, is_admin=is_admin)
