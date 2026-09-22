"""技能（生成剧本）目录：加载、静态校验与元数据查询。

技能以 ``SKILL.md`` 为单一真相，两级渐进披露：

- Level 1 元数据（YAML front matter）：参与语义匹配与前端技能选择器；
- Level 2 正文（四节）：命中后才注入 Planner / PageWriter。

**职责边界**：技能只承载「这类问题该怎么查、该怎么编排、该呈现什么」这类生成方法论；
领域语义（地图符号、阵营色、取值映射、状态角标）走数据源注解 `semantic_json`，
两者分层互补、不重叠。因此技能里**禁止**出现 datasetId、物理表名与硬编码数值阈值 ——
由本模块的静态校验在加载期拦下（零 LLM），避免技能库退化成"绑死某个数据源"的配置。

目录约定：``<IPAGE_SKILLS_DIR>/<skill-id>/SKILL.md``，目录名必须等于 front matter 的 ``id``
（与 qa-service 的 SKILL.md 约定一致）。
"""
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import yaml

import cache_registry
import config

logger = logging.getLogger("ipage-service")

SKILL_FILE_NAME = "SKILL.md"
SKILL_CACHE_NAME = "ipage_skills"

# ── 取值域（必须与运行时契约一致，见 agent/prompts.py 的 RUNTIME_API_GUIDE）──
ALLOWED_CHART_TYPES = ("bar", "line", "pie", "radar", "scatter")
ALLOWED_MAP_MODES = ("none", "points", "tracks", "circles")
ALLOWED_SECTION_KINDS = ("kpi", "chart", "map", "text", "table", "filters", "timeline")
ALLOWED_ENTITY_KINDS = ("air", "ground_facility", "base", "other")
ALLOWED_SUB_QUESTION_MODES = ("aggregate", "detail")

# 正文必备四节（缺节视为技能未写完，加载失败）
REQUIRED_BODY_SECTIONS = ("取数剧本", "区块剧本", "呈现偏好", "叙事要点")
# 匹配语料最少条数（太少则语义匹配不可靠）
MIN_TRIGGERS = 3

# ── 红线：写死数据源或数值的技能一律拒绝加载 ──
_REDLINE_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("数据集 ID", re.compile(r"\bds_[A-Za-z0-9_]+")),
    ("UUID 形态标识", re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("物理表名", re.compile(r"\bmock_[A-Za-z0-9_]+")),
    ("硬编码百分比", re.compile(r"\d+(?:\.\d+)?\s*%")),
    ("硬编码数值阈值", re.compile(r"(?:>=|<=|≥|≤|大于|小于|超过|不低于|不超过|至少|至多)\s*\d+")),
)

# 取数剧本行：- need: entityKind=air, mode=detail, geo=tracks, question=...
# 键值对只用 ASCII 逗号分隔，因此 question 描述内不要出现 ASCII 逗号。
_NEED_LINE_RE = re.compile(r"^-\s*need\s*:\s*(.+)$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Need:
    """取数剧本中的一条数据需求（实体语义槽位，不含 datasetId）。"""

    entity_kind: str
    mode: str
    geo: str
    question: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "entityKind": self.entity_kind,
            "mode": self.mode,
            "geo": self.geo,
            "question": self.question,
        }


@dataclass
class Skill:
    """一个技能（生成剧本）。"""

    id: str
    name: str
    description: str
    category: str = ""
    order: int = 100
    triggers: List[str] = field(default_factory=list)
    required_entity_kinds: List[str] = field(default_factory=list)
    recommended_chart_types: List[str] = field(default_factory=list)
    map_modes: List[str] = field(default_factory=list)
    playback: bool = False
    required_sections: List[str] = field(default_factory=list)
    focus_metrics: List[str] = field(default_factory=list)
    interactions: List[str] = field(default_factory=list)
    needs: List[Need] = field(default_factory=list)
    body_sections: Dict[str, str] = field(default_factory=dict)
    content_hash: str = ""
    path: str = ""

    @property
    def corpus(self) -> List[str]:
        """参与语义匹配的语料：名称 + 说明 + 触发问法。"""
        items = [self.name, self.description]
        items.extend(self.triggers)
        return [t for t in (str(x or "").strip() for x in items) if t]

    @property
    def version(self) -> str:
        """技能内容版本（SKILL.md 内容哈希前 12 位），用于产物可复现。"""
        return self.content_hash[:12]

    def to_meta(self) -> Dict[str, Any]:
        """下发给前端选择器的元数据（不含正文）。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "order": self.order,
            "triggerCount": len(self.triggers),
            "requiredEntityKinds": list(self.required_entity_kinds),
            "mapModes": list(self.map_modes),
            "playback": self.playback,
            "focusMetrics": list(self.focus_metrics),
            "version": self.version,
        }


def _sections_of(body: str) -> Dict[str, str]:
    """按 ``## 标题`` 切分正文，返回 {标题: 正文}。"""
    matches = list(_SECTION_RE.finditer(body))
    sections: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        sections[match.group(1).strip()] = body[start:end].strip()
    return sections


def _read_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    """解析 SKILL.md 的 YAML front matter，返回 (元数据, 正文)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("缺少 YAML front matter（文件首行必须是 ---）")
    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing is None:
        raise ValueError("YAML front matter 未闭合（缺少结束的 ---）")
    metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
    if not isinstance(metadata, dict):
        raise ValueError("YAML front matter 必须是键值对象")
    return metadata, "\n".join(lines[closing + 1:]).strip()


def _as_str_list(value: Any) -> List[str]:
    """把 front matter 字段规整成字符串列表（缺省为空列表）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _parse_needs(text: str) -> Tuple[List[Need], List[str]]:
    """解析「取数剧本」中的 need 行，返回 (需求列表, 错误列表)。"""
    needs: List[Need] = []
    errors: List[str] = []
    for raw in text.splitlines():
        match = _NEED_LINE_RE.match(raw.strip())
        if not match:
            continue
        spec: Dict[str, str] = {}
        for part in match.group(1).split(","):
            part = part.strip()
            if not part or "=" not in part:
                continue
            key, _, value = part.partition("=")
            spec[key.strip()] = value.strip()

        entity_kind = spec.get("entityKind", "")
        mode = spec.get("mode", "aggregate")
        geo = spec.get("geo", "none")
        question = spec.get("question", "")
        line_desc = match.group(1)[:60]

        # entityKind 可省略：省略表示「不限定实体语义，由规划阶段按目录选表」，
        # 用于事件/任务这类 annotation 的实体大类无法表达的取数需求。
        if entity_kind and entity_kind not in ALLOWED_ENTITY_KINDS:
            errors.append(
                f"取数剧本 entityKind={entity_kind} 非法"
                f"（可选 {'/'.join(ALLOWED_ENTITY_KINDS)}，或省略表示按目录选表）：{line_desc}")
            continue
        if mode not in ALLOWED_SUB_QUESTION_MODES:
            errors.append(f"取数剧本 mode={mode} 非法（可选 aggregate/detail）：{line_desc}")
            continue
        if geo not in ALLOWED_MAP_MODES:
            errors.append(f"取数剧本 geo={geo} 非法（可选 {'/'.join(ALLOWED_MAP_MODES)}）：{line_desc}")
            continue
        if not question:
            errors.append(f"取数剧本缺少 question：{line_desc}")
            continue
        if geo != "none" and mode != "detail":
            errors.append(f"取数剧本 geo={geo} 必须配 mode=detail（地图需要逐行明细）：{line_desc}")
            continue
        needs.append(Need(entity_kind=entity_kind, mode=mode, geo=geo, question=question))

    if not needs:
        errors.append("取数剧本没有任何有效的 need 行")
    return needs, errors


def _check_redlines(text: str) -> List[str]:
    """红线机检：写死数据源标识或数值阈值的技能一律拒绝。"""
    errors: List[str] = []
    for label, pattern in _REDLINE_PATTERNS:
        found = pattern.search(text)
        if found:
            errors.append(f"命中红线「{label}」：{found.group(0)[:40]}")
    return errors


def _validate_in_domain(values: List[str], allowed: Tuple[str, ...], label: str,
                        errors: List[str]) -> None:
    for value in values:
        if value not in allowed:
            errors.append(f"{label}={value} 非法（可选 {'/'.join(allowed)}）")


def _parse_skill(skill_dir: str, dir_name: str) -> Tuple[Optional[Skill], List[str]]:
    """读取并校验单个技能目录，返回 (技能对象, 错误列表)。"""
    path = os.path.join(skill_dir, SKILL_FILE_NAME)
    errors: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        return None, [f"读取失败: {exc}"]

    try:
        metadata, body = _read_front_matter(text)
    except Exception as exc:
        return None, [f"front matter 解析失败: {exc}"]

    skill_id = str(metadata.get("id") or "").strip()
    name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    triggers = _as_str_list(metadata.get("triggers"))

    if skill_id != dir_name:
        errors.append(f"front matter id={skill_id or '空'} 与目录名 {dir_name} 不一致")
    if not skill_id:
        errors.append("front matter 缺少 id")
    if not name:
        errors.append("front matter 缺少 name")
    if not description:
        errors.append("front matter 缺少 description")
    if len(triggers) < MIN_TRIGGERS:
        errors.append(f"triggers 至少需要 {MIN_TRIGGERS} 条（当前 {len(triggers)} 条）")

    sections = _sections_of(body)
    for required in REQUIRED_BODY_SECTIONS:
        if required not in sections:
            errors.append(f"正文缺少必备章节「## {required}」")

    needs: List[Need] = []
    if "取数剧本" in sections:
        needs, need_errors = _parse_needs(sections["取数剧本"])
        errors.extend(need_errors)

    errors.extend(_check_redlines(text))

    required_entity_kinds = _as_str_list(metadata.get("requiredEntityKinds"))
    chart_types = _as_str_list(metadata.get("recommendedChartTypes"))
    map_modes = _as_str_list(metadata.get("mapModes"))
    required_sections = _as_str_list(metadata.get("requiredSections"))
    _validate_in_domain(required_entity_kinds, ALLOWED_ENTITY_KINDS, "requiredEntityKinds", errors)
    _validate_in_domain(chart_types, ALLOWED_CHART_TYPES, "recommendedChartTypes", errors)
    _validate_in_domain(map_modes, ALLOWED_MAP_MODES, "mapModes", errors)
    _validate_in_domain(required_sections, ALLOWED_SECTION_KINDS, "requiredSections", errors)

    try:
        order = int(metadata.get("order", 100))
    except (TypeError, ValueError):
        errors.append("order 必须是整数")
        order = 100

    if errors:
        return None, errors

    skill = Skill(
        id=skill_id,
        name=name,
        description=description,
        category=str(metadata.get("category") or "").strip(),
        order=order,
        triggers=triggers,
        required_entity_kinds=required_entity_kinds,
        recommended_chart_types=chart_types,
        map_modes=map_modes,
        playback=bool(metadata.get("playback", False)),
        required_sections=required_sections,
        focus_metrics=_as_str_list(metadata.get("focusMetrics")),
        interactions=_as_str_list(metadata.get("interactions")),
        needs=needs,
        body_sections=sections,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        path=path,
    )
    return skill, []


def _skill_dirs() -> List[Tuple[str, str]]:
    """列出 (目录绝对路径, 目录名)，按目录名排序保证加载顺序确定。"""
    root = config.IPAGE_SKILLS_DIR
    if not os.path.isdir(root):
        return []
    items: List[Tuple[str, str]] = []
    for dir_name in sorted(os.listdir(root)):
        path = os.path.join(root, dir_name)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, SKILL_FILE_NAME)):
            items.append((path, dir_name))
    return items


def _compute_fingerprint() -> str:
    """技能目录指纹：目录与每个 SKILL.md 的修改时间 + 大小。"""
    parts = [os.path.abspath(config.IPAGE_SKILLS_DIR)]
    for path, _ in _skill_dirs():
        file_path = os.path.join(path, SKILL_FILE_NAME)
        try:
            stat = os.stat(file_path)
        except OSError:
            continue
        parts.append(f"{file_path}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# 模块级缓存：{"fingerprint": str, "skills": List[Skill]}，技能文件变更自动重算
_CACHE: Dict[str, Any] = {}


def _load_from_disk() -> List[Skill]:
    """全量加载技能目录；单个技能校验失败只告警并跳过，不影响其余技能。"""
    skills: List[Skill] = []
    for path, dir_name in _skill_dirs():
        skill, errors = _parse_skill(path, dir_name)
        if skill is None:
            logger.warning("技能 %s 加载失败（已跳过）: %s", dir_name, "；".join(errors[:6]))
            continue
        skills.append(skill)
    skills.sort(key=lambda s: (s.order, s.name))
    if skills:
        logger.info("技能目录加载完成：共 %s 个（%s）",
                    len(skills), ", ".join(s.id for s in skills))
    return skills


def _ensure_cache() -> None:
    """按目录指纹惰性重建缓存。"""
    fingerprint = _compute_fingerprint()
    if _CACHE.get("fingerprint") == fingerprint and "skills" in _CACHE:
        return
    skills = _load_from_disk()
    _CACHE["fingerprint"] = fingerprint
    _CACHE["skills"] = skills


def load_skills() -> List[Skill]:
    """返回全部可用技能（按 order、name 排序）。"""
    _ensure_cache()
    return list(_CACHE.get("skills") or [])


def get_skill(skill_id: str) -> Optional[Skill]:
    """按 id 取技能；不存在返回 None。"""
    target = str(skill_id or "").strip()
    if not target:
        return None
    for skill in load_skills():
        if skill.id == target:
            return skill
    return None


def clear_cache() -> int:
    """清空技能目录缓存，返回被清理的技能条目数（供 cache_registry 调用）。"""
    skills = _CACHE.get("skills") or []
    _CACHE.clear()
    return len(skills)


cache_registry.register_cache(SKILL_CACHE_NAME, lambda _database_id, _tables: clear_cache())
