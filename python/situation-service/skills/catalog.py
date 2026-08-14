"""态势图 Skill 目录。

目录采用只读 JSON，启动时完成严格校验；搜索、推荐和执行计划均为确定性逻辑，
即使 LLM 或下游数据源暂不可用，Skill 选择与编排上下文仍可稳定工作。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml
import hashlib

from .store import (
    SkillStoreConflict,
    SkillStoreError,
    SkillStoreNotFound,
    archive_custom_skill,
    create_custom_skill,
    get_custom_skill,
    list_custom_skills,
    list_skill_versions as store_list_skill_versions,
    publish_custom_skill,
    rollback_custom_skill,
    update_custom_skill,
)


_CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "situation_skills.json"
_MARKDOWN_OVERRIDE_ENV = "SITUATION_SKILL_MD_OVERRIDE_DIR"
_SKILL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CHART_TYPES = {
    "bar", "line", "pie", "radar", "gauge", "scatter", "heatmap",
    "relation", "sankey", "map",
}
_MAP_LAYER_TYPES = {"points", "routes", "areas", "heatmap", "coverage", "clusters", "flow"}
_REQUIRED_FIELDS = {
    "order", "id", "name", "description", "category", "triggers",
    "recommendedQuestions", "inputHints", "steps", "dataSources",
    "chartTypes", "mapLayerTypes", "focusMetrics", "analysisGoal",
}
_GENERIC_BIGRAMS = {"分析", "评估", "情况", "当前", "展示", "生成", "对比", "态势"}
_PARAMETER_TYPES = {"text", "number", "select", "multiselect"}
_RUNTIME_FIELDS = {
    "source", "isBuiltIn", "ownerId", "status", "revision", "version",
    "createdAt", "updatedAt", "score", "matchedTriggers", "recommendationReason",
}
_SELECT_OPTIONS = {
    "时间范围": ["近24小时", "近7天", "近30天", "近90天"],
    "参战方": ["全部", "红方", "蓝方"],
    "双方标识": ["红蓝双方", "仅红方", "仅蓝方"],
    "威胁等级": ["全部", "高", "中", "低"],
    "任务类型": ["全部", "火力打击", "侦察监视", "区域防御", "保障运输"],
    "损失类型": ["全部", "装备损失", "人员伤亡", "资源损耗"],
    "资源类型": ["全部", "弹药", "燃料", "备件", "物资"],
    "数据来源": ["全部", "业务数据", "指标", "知识库", "评估结果"],
}
_FIELD_ALIASES = {
    "区域": "region", "关注区域": "region", "关键区域": "region",
    "空间范围": "region", "任务范围": "region",
    "参战方": "side_name", "双方标识": "side_name", "单位": "unit_id",
    "参战单位": "unit_id", "军兵种": "force_type", "任务类型": "mission_type",
    "目标类型": "target_type", "威胁等级": "threat_level", "损失类型": "loss_type",
    "损耗类型": "loss_type", "资源类型": "resource_type", "弹药类型": "resource_type",
    "装备型号": "model", "武器型号": "model", "武器类型": "weapon_type",
    "指挥层级": "command_level", "防护类型": "defense_type",
    "侦察手段": "intelligence_source", "计划编号": "plan_no", "任务": "mission_no",
    "对象类型": "target_type", "数据来源": "_dataset",
}
_THRESHOLD_FIELDS = {
    "安全库存": "stock_count", "保障天数": "support_days",
    "超时阈值": "recovery_hours", "控制阈值": "defense_score",
    "预警阈值": "risk_score", "异常阈值": "risk_score",
    "响应阈值": "response_minutes", "战备阈值": "readiness_rate",
    "质量阈值": "confidence_score",
}
_ANALYSIS_CONTROL_PARAMETERS = {
    "成功判据", "代价口径", "对比维度", "评价维度", "效能口径", "协同环节",
    "排序指标", "方案 ID", "路线", "基准周期", "截止时间", "评估日期", "时间点",
    "时间容差", "预测周期",
}
_MARKDOWN_DEFINITION_FIELDS = _REQUIRED_FIELDS | {"featured", "parameters"}
# 自定义 Skill 定义负载额外允许 markdownBody（在线编辑正文随定义存储），
# 但 SKILL.md 的 YAML 头部校验（_read_markdown_override）仍不允许该字段。
_PAYLOAD_FIELDS = _MARKDOWN_DEFINITION_FIELDS | {"markdownBody"}
_PARAMETER_FIELDS = {
    "key", "label", "type", "required", "options", "default",
    "minimum", "maximum", "placeholder", "binding",
}
_BINDING_FIELDS = {"operator", "field"}
_BINDING_OPERATORS = {
    "equals", "contains", "numeric-threshold", "time-window", "limit",
    "map-radius", "analysis-control",
}

logger = logging.getLogger("situation-service.skill_catalog")


class SkillCatalogError(ValueError):
    """Skill 定义无效或执行参数不合法。"""


def _compact(value: Any) -> str:
    return re.sub(r"[\s_\-./，。！？、：:]+", "", str(value or "").strip().lower())


def _meaningful_bigrams(value: str) -> set[str]:
    normalized = _compact(value)
    return {
        normalized[index:index + 2]
        for index in range(max(0, len(normalized) - 1))
        if normalized[index:index + 2] not in _GENERIC_BIGRAMS
    }


def _validate_text(value: Any, field: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SkillCatalogError(f"{field} 必须是非空字符串")
    if len(value) > maximum:
        raise SkillCatalogError(f"{field} 超过 {maximum} 字符")


def _validate_string_list(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = 12,
    item_maximum: int = 200,
) -> None:
    if not isinstance(value, list) or len(value) < minimum or len(value) > maximum:
        raise SkillCatalogError(f"{field} 必须包含 {minimum}-{maximum} 项")
    for index, item in enumerate(value, start=1):
        _validate_text(item, f"{field}[{index}]", item_maximum)


def _validate_skill(skill: Any, seen: set[str]) -> None:
    if not isinstance(skill, dict):
        raise SkillCatalogError("Skill 条目必须是对象")
    missing = sorted(_REQUIRED_FIELDS - set(skill))
    if missing:
        raise SkillCatalogError(f"Skill 缺少字段: {', '.join(missing)}")

    skill_id = skill.get("id")
    if not isinstance(skill_id, str) or not _SKILL_ID_RE.fullmatch(skill_id):
        raise SkillCatalogError(f"Skill id 不合法: {skill_id}")
    if skill_id in seen:
        raise SkillCatalogError(f"Skill id 重复: {skill_id}")
    seen.add(skill_id)

    if not isinstance(skill.get("order"), int) or skill["order"] <= 0:
        raise SkillCatalogError(f"Skill {skill_id} order 必须是正整数")
    _validate_text(skill["name"], f"Skill {skill_id} name", 80)
    _validate_text(skill["description"], f"Skill {skill_id} description", 300)
    _validate_text(skill["category"], f"Skill {skill_id} category", 40)
    _validate_text(skill["analysisGoal"], f"Skill {skill_id} analysisGoal", 500)
    _validate_string_list(skill["triggers"], f"Skill {skill_id} triggers", maximum=10, item_maximum=40)
    _validate_string_list(
        skill["recommendedQuestions"],
        f"Skill {skill_id} recommendedQuestions",
        maximum=5,
        item_maximum=200,
    )
    _validate_string_list(skill["inputHints"], f"Skill {skill_id} inputHints", maximum=8, item_maximum=40)
    _validate_string_list(skill["steps"], f"Skill {skill_id} steps", minimum=2, maximum=8)
    _validate_string_list(skill["dataSources"], f"Skill {skill_id} dataSources", maximum=10, item_maximum=80)
    _validate_string_list(skill["chartTypes"], f"Skill {skill_id} chartTypes", maximum=5, item_maximum=20)
    _validate_string_list(
        skill["mapLayerTypes"], f"Skill {skill_id} mapLayerTypes", maximum=5, item_maximum=20
    )
    _validate_string_list(skill["focusMetrics"], f"Skill {skill_id} focusMetrics", maximum=5, item_maximum=60)

    invalid_charts = set(skill["chartTypes"]) - _CHART_TYPES
    invalid_layers = set(skill["mapLayerTypes"]) - _MAP_LAYER_TYPES
    if invalid_charts:
        raise SkillCatalogError(f"Skill {skill_id} 包含不支持的图表: {sorted(invalid_charts)}")
    if invalid_layers:
        raise SkillCatalogError(f"Skill {skill_id} 包含不支持的地图图层: {sorted(invalid_layers)}")
    if "parameters" in skill:
        if not isinstance(skill["parameters"], list) or len(skill["parameters"]) > 12:
            raise SkillCatalogError(f"Skill {skill_id} parameters 必须是最多 12 项的数组")
        parameter_keys: set[str] = set()
        for parameter in skill["parameters"]:
            if not isinstance(parameter, dict):
                raise SkillCatalogError(f"Skill {skill_id} parameter 必须是对象")
            key = str(parameter.get("key") or "").strip()
            label = str(parameter.get("label") or "").strip()
            parameter_type = str(parameter.get("type") or "text")
            if not key or not label or key in parameter_keys:
                raise SkillCatalogError(f"Skill {skill_id} parameter key/label 无效或重复")
            if parameter_type not in _PARAMETER_TYPES:
                raise SkillCatalogError(f"Skill {skill_id} parameter {key} 类型不支持")
            unexpected = sorted(set(parameter) - _PARAMETER_FIELDS)
            if unexpected:
                raise SkillCatalogError(
                    f"Skill {skill_id} parameter {key} 包含不支持字段: {', '.join(unexpected)}"
                )
            options = parameter.get("options")
            if options is not None:
                if parameter_type not in {"select", "multiselect"}:
                    raise SkillCatalogError(f"Skill {skill_id} parameter {key} 仅选择类型可配置 options")
                _validate_string_list(
                    options, f"Skill {skill_id} parameter {key} options",
                    maximum=30, item_maximum=100,
                )
            for bound in ("minimum", "maximum"):
                if parameter.get(bound) is not None and (
                    isinstance(parameter[bound], bool) or not isinstance(parameter[bound], (int, float))
                ):
                    raise SkillCatalogError(f"Skill {skill_id} parameter {key} {bound} 必须是数字")
            if (
                parameter.get("minimum") is not None
                and parameter.get("maximum") is not None
                and parameter["minimum"] > parameter["maximum"]
            ):
                raise SkillCatalogError(f"Skill {skill_id} parameter {key} 最小值不能大于最大值")
            binding = parameter.get("binding")
            if binding is not None:
                if not isinstance(binding, dict) or set(binding) - _BINDING_FIELDS:
                    raise SkillCatalogError(f"Skill {skill_id} parameter {key} binding 格式无效")
                if binding.get("operator") not in _BINDING_OPERATORS:
                    raise SkillCatalogError(f"Skill {skill_id} parameter {key} binding operator 不支持")
                if "field" in binding:
                    _validate_text(binding["field"], f"Skill {skill_id} parameter {key} binding field", 80)
            parameter_keys.add(key)


def get_markdown_override_directory() -> Path:
    """Return the persistent writable layer for edited built-in SKILL.md files."""

    configured = os.getenv(_MARKDOWN_OVERRIDE_ENV, "").strip()
    if configured:
        return Path(os.path.abspath(os.path.expanduser(configured)))
    return Path(__file__).resolve().parent.parent / "data" / "situation-skill-markdown-overrides"


def _read_markdown_override(path: Path, expected_skill_id: str) -> Dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillCatalogError(f"无法读取态势 Skill Markdown 覆盖文件: {exc}") from exc
    lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillCatalogError(f"态势 Skill Markdown 缺少 YAML 头部: {path}")
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise SkillCatalogError(f"态势 Skill Markdown YAML 头部未闭合: {path}") from exc
    try:
        definition = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as exc:
        raise SkillCatalogError(f"态势 Skill Markdown YAML 无效: {path}: {exc}") from exc
    if not isinstance(definition, dict):
        raise SkillCatalogError(f"态势 Skill Markdown YAML 必须是对象: {path}")
    if definition.get("id") != expected_skill_id:
        raise SkillCatalogError(f"态势 Skill Markdown id 与目录不一致: {path}")
    unexpected = sorted(set(definition) - _MARKDOWN_DEFINITION_FIELDS)
    if unexpected:
        raise SkillCatalogError(f"态势 Skill Markdown 包含不支持字段: {', '.join(unexpected)}")
    _validate_skill(definition, set())
    body = "\n".join(lines[closing_index + 1:]).strip()
    first_line = body.splitlines()[0].strip() if body else ""
    if first_line != f"# {definition['name']}":
        raise SkillCatalogError(f"态势 Skill Markdown 标题必须与 name 一致: {path}")
    return definition


def _parameter_definition(hint: str, index: int) -> Dict[str, Any]:
    """把简洁的输入提示扩展为前后端共享的结构化参数定义。"""
    normalized = str(hint).strip()
    options = _SELECT_OPTIONS.get(normalized)
    if options:
        return {
            "key": normalized,
            "label": normalized,
            "type": "select",
            "required": False,
            "options": options,
            "default": options[0],
            "placeholder": f"请选择{normalized}",
        }
    if any(keyword in normalized.lower() for keyword in ("top n", "阈值", "半径", "天数", "数量")):
        is_top_n = "top n" in normalized.lower()
        return {
            "key": normalized,
            "label": normalized,
            "type": "number",
            "required": False,
            "default": 10 if is_top_n else None,
            "minimum": 1 if is_top_n else 0,
            "maximum": 100 if is_top_n else 10000,
            "placeholder": f"请输入{normalized}",
        }
    return {
        "key": normalized or f"parameter-{index}",
        "label": normalized or f"参数 {index}",
        "type": "text",
        "required": False,
        "default": "",
        "placeholder": f"请输入{normalized}" if normalized else "请输入参数",
    }


def _parameter_binding(definition: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a parameter definition into a deterministic workflow operator."""
    explicit = definition.get("binding")
    if isinstance(explicit, dict) and explicit.get("operator"):
        return copy.deepcopy(explicit)
    key = str(definition.get("key") or "")
    lowered = key.lower()
    if any(token in lowered for token in ("top n", "数量", "条数")):
        return {"operator": "limit"}
    if key in _THRESHOLD_FIELDS or any(token in key for token in ("阈值", "下限")):
        return {"operator": "numeric-threshold", "field": _THRESHOLD_FIELDS.get(key, key)}
    if "半径" in key:
        # Radius controls map rendering; it must not accidentally filter a dataset whose
        # schema has no radius column.
        return {"operator": "map-radius"}
    if key in ("时间窗", "时间范围") or ("天数" in key and key != "保障天数"):
        return {"operator": "time-window", "field": key}
    if key in _ANALYSIS_CONTROL_PARAMETERS:
        return {"operator": "analysis-control"}
    operator = "contains" if any(token in key for token in ("区域", "范围")) else "equals"
    return {"operator": operator, "field": _FIELD_ALIASES.get(key, key)}


def _enrich_skill(skill: Dict[str, Any], *, builtin: bool) -> Dict[str, Any]:
    item = copy.deepcopy(skill)
    item["parameters"] = item.get("parameters") or [
        _parameter_definition(hint, index)
        for index, hint in enumerate(item.get("inputHints", []), start=1)
    ]
    if builtin:
        item.update({
            "source": "builtin",
            "isBuiltIn": True,
            "ownerId": "system",
            "status": "published",
            "revision": 1,
            "version": 1,
        })
    return item


@lru_cache(maxsize=1)
def _builtin_skills() -> List[Dict[str, Any]]:
    return [_enrich_skill(skill, builtin=True) for skill in _load_catalog()["skills"]]


# 自定义 Skill 列表短缓存（TTL + 写操作失效），避免每个请求都开 SQLite 连接查询。
_CUSTOM_CACHE_LOCK = threading.Lock()
_CUSTOM_CACHE_TTL = 5.0
_custom_skills_cache: Dict[tuple, tuple[float, List[Dict[str, Any]]]] = {}


def _cached_custom_skills(user_id: str, include_archived: bool) -> List[Dict[str, Any]]:
    key = (user_id, include_archived)
    now = time.monotonic()
    with _CUSTOM_CACHE_LOCK:
        cached = _custom_skills_cache.get(key)
        if cached and cached[0] > now:
            return list(cached[1])
    try:
        custom = list_custom_skills(user_id, include_archived=include_archived)
    except SkillStoreError as exc:
        logger.warning("自定义态势 Skill 加载失败，回退内置目录: %s", exc)
        custom = []
    with _CUSTOM_CACHE_LOCK:
        _custom_skills_cache[key] = (now + _CUSTOM_CACHE_TTL, custom)
        # 防膨胀：只清理已过期 key，保留活跃 key
        if len(_custom_skills_cache) > 16:
            expired = [k for k, v in _custom_skills_cache.items() if v[0] <= now]
            for k in expired:
                _custom_skills_cache.pop(k, None)
    return custom


def _custom_skills_cache_clear() -> None:
    with _CUSTOM_CACHE_LOCK:
        _custom_skills_cache.clear()


def _all_skills(user_id: str = "", *, include_archived: bool = False) -> List[Dict[str, Any]]:
    skills = list(_builtin_skills())  # 浅拷贝列表，避免 extend 污染 lru_cache 缓存
    custom = _cached_custom_skills(user_id, include_archived)
    skills.extend(_enrich_skill(skill, builtin=False) for skill in custom)
    return skills


@lru_cache(maxsize=1)
def _load_catalog() -> Dict[str, Any]:
    try:
        document = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillCatalogError(f"无法加载态势图 Skill 目录: {exc}") from exc

    if not isinstance(document, dict) or not isinstance(document.get("skills"), list):
        raise SkillCatalogError("Skill 目录必须包含 skills 数组")
    seen: set[str] = set()
    override_root = get_markdown_override_directory()
    for index, baseline_skill in enumerate(document["skills"]):
        skill = baseline_skill
        override_path = override_root / str(baseline_skill.get("id") or "") / "SKILL.md"
        if override_path.is_file():
            skill = _read_markdown_override(override_path, str(baseline_skill.get("id") or ""))
            if skill.get("order") != baseline_skill.get("order"):
                raise SkillCatalogError(
                    f"在线编辑不能改变内置 Skill 顺序: {baseline_skill.get('id', '')}"
                )
            document["skills"][index] = skill
        _validate_skill(skill, seen)
    document["skills"].sort(key=lambda item: (item["order"], item["name"]))
    return document


def clear_catalog_cache() -> None:
    """Invalidate built-in catalog data after an atomic Markdown override save."""

    _load_catalog.cache_clear()
    _builtin_skills.cache_clear()
    _custom_skills_cache_clear()


def list_skills(
    query: str = "",
    category: str = "",
    *,
    featured: Optional[bool] = None,
    limit: int = 100,
    user_id: str = "",
    include_archived: bool = False,
) -> List[Dict[str, Any]]:
    """按关键词、分类和精选状态列出 Skill。"""
    normalized_query = _compact(query)
    normalized_category = str(category or "").strip()
    result: List[Dict[str, Any]] = []
    for skill in _all_skills(user_id, include_archived=include_archived):
        if normalized_category and skill["category"] != normalized_category:
            continue
        if featured is not None and bool(skill.get("featured")) != featured:
            continue
        if normalized_query:
            search_fields: Iterable[str] = (
                skill["name"], skill["description"], skill["category"],
                *skill["triggers"], *skill["focusMetrics"], *skill["recommendedQuestions"],
            )
            if not any(normalized_query in _compact(field) or _compact(field) in normalized_query for field in search_fields):
                continue
        result.append(copy.deepcopy(skill))
    return result[: max(1, min(int(limit or 100), 100))]


def get_skill(
    skill_id: str,
    user_id: str = "",
    *,
    include_archived: bool = False,
) -> Optional[Dict[str, Any]]:
    normalized = str(skill_id or "").strip()
    for skill in _builtin_skills():
        if skill["id"] == normalized:
            return copy.deepcopy(skill)
    try:
        custom = get_custom_skill(normalized, user_id, include_archived=include_archived)
    except SkillStoreError as exc:
        logger.warning("读取自定义态势 Skill 失败: %s", exc)
        return None
    if custom:
        return _enrich_skill(custom, builtin=False)
    return None


def catalog_summary(user_id: str = "") -> Dict[str, Any]:
    skills = _all_skills(user_id)
    counts: Dict[str, int] = {}
    for skill in skills:
        counts[skill["category"]] = counts.get(skill["category"], 0) + 1
    return {
        "version": _load_catalog().get("version", "1.0.0"),
        "total": len(skills),
        "categories": [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: item[0])
        ],
    }


def recommend_skills(
    query: str,
    limit: int = 3,
    *,
    user_id: str = "",
    favorite_ids: Optional[List[str]] = None,
    usage: Optional[Dict[str, Dict[str, int]]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """根据名称、触发词、描述与关注指标进行可解释的确定性推荐。"""
    normalized_query = _compact(query)
    query_bigrams = _meaningful_bigrams(normalized_query)
    ranked = []
    favorites = set(favorite_ids or [])
    usage = usage or {}
    context_text = _compact(" ".join(str(value) for value in (context or {}).values()))
    candidates = [skill for skill in _all_skills(user_id) if skill.get("status") == "published"]
    for skill in candidates:
        score = 0
        matched_triggers = []
        if normalized_query:
            name = _compact(skill["name"])
            if name and (name in normalized_query or normalized_query in name):
                score += 160
            for trigger in skill["triggers"]:
                compact_trigger = _compact(trigger)
                if compact_trigger and compact_trigger in normalized_query:
                    score += 110 + len(compact_trigger)
                    matched_triggers.append(trigger)
                elif compact_trigger:
                    overlap = query_bigrams & _meaningful_bigrams(compact_trigger)
                    if overlap:
                        score += 45 * len(overlap)
                        matched_triggers.append(trigger)
            for metric in skill["focusMetrics"]:
                compact_metric = _compact(metric)
                if compact_metric and compact_metric in normalized_query:
                    score += 35
                elif query_bigrams & _meaningful_bigrams(compact_metric):
                    score += 12
            for field in (skill["description"], skill["category"], *skill["recommendedQuestions"]):
                compact_field = _compact(field)
                if normalized_query in compact_field or (len(compact_field) >= 2 and compact_field in normalized_query):
                    score += 15

        # 用户偏好和当前态势上下文只做次级加权，不覆盖文本相关性。
        preference_reasons = []
        if skill["id"] in favorites:
            score += 24
            preference_reasons.append("已收藏")
        skill_usage = usage.get(skill["id"], {})
        if skill_usage.get("uses", 0):
            score += min(20, int(skill_usage["uses"]) * 3)
            preference_reasons.append(f"近期使用 {skill_usage['uses']} 次")
        if context_text:
            context_matches = sum(
                1 for trigger in skill["triggers"] if _compact(trigger) in context_text
            )
            if context_matches:
                score += min(30, context_matches * 10)
                preference_reasons.append("匹配当前态势上下文")

        # 无明确命中时仍提供精选 Skill，保证空输入和短输入下有可用入口。
        if score == 0 and not normalized_query and skill.get("featured"):
            score = 10
        if score:
            item = copy.deepcopy(skill)
            item["score"] = score
            item["matchedTriggers"] = matched_triggers
            text_reason = (
                f"命中关键词：{'、'.join(matched_triggers)}"
                if matched_triggers else "常用态势分析 Skill"
            )
            item["recommendationReason"] = "；".join([text_reason, *preference_reasons])
            ranked.append((score, skill["order"], item))

    requested_limit = max(1, min(int(limit or 3), 10))
    ranked_ids = {row[2]["id"] for row in ranked}
    # 精确匹配不足时用常用 Skill 补齐，界面始终有足够的后续选择。
    fallback = [skill for skill in candidates if skill.get("featured")]
    fallback.extend(skill for skill in candidates if not skill.get("featured"))
    for skill in fallback:
        if len(ranked) >= requested_limit or skill["id"] in ranked_ids:
            continue
        item = copy.deepcopy(skill)
        item.update(score=1, matchedTriggers=[], recommendationReason="常用态势分析 Skill")
        ranked.append((1, skill["order"], item))
        ranked_ids.add(skill["id"])

    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in ranked[:requested_limit]]


def validate_skill_parameters(
    skill: Dict[str, Any],
    parameters: Optional[Dict[str, Any]],
    *,
    apply_defaults: bool = True,
) -> Dict[str, Any]:
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict) or len(parameters) > 20:
        raise SkillCatalogError("Skill 参数必须是最多 20 项的对象")
    definitions = {definition["key"]: definition for definition in skill.get("parameters", [])}
    unknown = sorted(set(str(key) for key in parameters) - set(definitions))
    if unknown:
        raise SkillCatalogError(f"Skill 包含未定义参数: {', '.join(unknown)}")
    safe: Dict[str, Any] = {}
    for key, definition in definitions.items():
        has_value = key in parameters and parameters[key] not in (None, "", [])
        value = parameters.get(key)
        if not has_value and apply_defaults and definition.get("default") not in (None, "", []):
            value = definition["default"]
            has_value = True
        if not has_value:
            if definition.get("required"):
                raise SkillCatalogError(f"缺少必填参数：{definition['label']}")
            continue

        parameter_type = definition.get("type", "text")
        if parameter_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SkillCatalogError(f"参数「{definition['label']}」必须是数字")
            minimum = definition.get("minimum")
            maximum = definition.get("maximum")
            if minimum is not None and value < minimum:
                raise SkillCatalogError(f"参数「{definition['label']}」不能小于 {minimum}")
            if maximum is not None and value > maximum:
                raise SkillCatalogError(f"参数「{definition['label']}」不能大于 {maximum}")
        elif parameter_type == "select":
            if not isinstance(value, str):
                raise SkillCatalogError(f"参数「{definition['label']}」必须是字符串")
            options = definition.get("options") or []
            if options and value not in options:
                raise SkillCatalogError(f"参数「{definition['label']}」不在允许选项中")
        elif parameter_type == "multiselect":
            if not isinstance(value, list) or len(value) > 30:
                raise SkillCatalogError(f"参数「{definition['label']}」必须是最多 30 项的数组")
            options = definition.get("options") or []
            if options and any(item not in options for item in value):
                raise SkillCatalogError(f"参数「{definition['label']}」包含无效选项")
        else:
            if not isinstance(value, str) or len(value) > 500:
                raise SkillCatalogError(f"参数「{definition['label']}」必须是 500 字以内文本")
        safe[key] = value
    return safe


def build_skill_context(
    skill_id: str,
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    user_id: str = "",
    allow_draft: bool = False,
) -> Dict[str, Any]:
    """构造供生成编排器使用的、可审计的 Skill 执行上下文。"""
    skill = get_skill(skill_id, user_id)
    if not skill:
        raise SkillCatalogError(f"态势图 Skill 不存在: {skill_id}")
    if not allow_draft and skill.get("status") != "published":
        raise SkillCatalogError("自定义 Skill 尚未发布，不能用于生成")
    normalized_query = str(query or "").strip()
    if not normalized_query:
        normalized_query = skill["recommendedQuestions"][0]
    if len(normalized_query) > 2000:
        raise SkillCatalogError("问题不能超过 2000 字符")
    safe_parameters = validate_skill_parameters(skill, parameters)
    parameter_text = ""
    if safe_parameters:
        parameter_text = "；参数：" + "，".join(f"{key}={value}" for key, value in safe_parameters.items())

    instruction = (
        f"使用「{skill['name']}」分析用户问题：{normalized_query}{parameter_text}。"
        f"分析目标：{skill['analysisGoal']}"
        f"依次执行：{'；'.join(skill['steps'])}。"
        f"优先使用数据源：{'、'.join(skill['dataSources'])}；"
        f"优先输出图表：{'、'.join(skill['chartTypes'])}；"
        f"地图图层：{'、'.join(skill['mapLayerTypes'])}。"
    )
    return {
        "skillId": skill["id"],
        "skillName": skill["name"],
        "category": skill["category"],
        "query": normalized_query,
        "parameters": safe_parameters,
        "instruction": instruction,
        "executionPlan": [
            {"sequence": index, "name": step}
            for index, step in enumerate(skill["steps"], start=1)
        ],
        "dataSources": skill["dataSources"],
        "chartTypes": skill["chartTypes"],
        "mapLayerTypes": skill["mapLayerTypes"],
        "focusMetrics": skill["focusMetrics"],
        "analysisGoal": skill["analysisGoal"],
        "workflow": [
            {
                "sequence": index,
                "name": step,
                "operator": (
                    "collect" if index == 1 else
                    "filter" if index == 2 and safe_parameters else
                    "visualize" if index == len(skill["steps"]) else
                    "transform"
                ),
            }
            for index, step in enumerate(skill["steps"], start=1)
        ],
        "parameterBindings": {
            definition["key"]: _parameter_binding(definition)
            for definition in skill.get("parameters", [])
        },
        "revision": int(skill.get("revision") or 1),
        "version": int(skill.get("version") or 1),
        "contentHash": hashlib.sha256(
            json.dumps(skill, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest(),
    }


def _custom_definition(payload: Dict[str, Any], *, skill_id: str = "") -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise SkillCatalogError("Skill 定义必须是对象")
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) > 128 * 1024:
        raise SkillCatalogError("Skill 定义不能超过 128 KB")
    unexpected = sorted(set(payload) - _PAYLOAD_FIELDS - _RUNTIME_FIELDS)
    if unexpected:
        raise SkillCatalogError(f"Skill 定义包含不支持字段: {', '.join(unexpected)}")
    definition = {
        key: copy.deepcopy(value)
        for key, value in payload.items()
        if key in _PAYLOAD_FIELDS
    }
    name = str(definition.get("name") or "").strip()
    if not skill_id:
        requested = str(definition.get("id") or "").strip().lower()
        base = re.sub(r"[^a-z0-9]+", "-", requested or name.lower()).strip("-")
        if not base:
            base = "situation-skill"
        skill_id = f"{base[:48]}-{uuid.uuid4().hex[:7]}"
    definition.update({
        "id": skill_id,
        "order": int(definition.get("order") or 1000),
        "featured": bool(definition.get("featured", False)),
    })
    # 编辑器可只维护输入提示，参数定义由目录统一生成。
    if not definition.get("parameters"):
        definition.pop("parameters", None)
    _validate_skill(definition, set())
    return definition


def create_skill_definition(payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    definition = _custom_definition(payload)
    if any(skill["id"] == definition["id"] for skill in _builtin_skills()):
        raise SkillCatalogError("不能覆盖内置 Skill")
    try:
        result = _enrich_skill(create_custom_skill(definition, user_id), builtin=False)
        _custom_skills_cache_clear()
        return result
    except (SkillStoreConflict, SkillStoreError) as exc:
        raise SkillCatalogError(str(exc)) from exc


def update_skill_definition(
    skill_id: str,
    payload: Dict[str, Any],
    user_id: str,
    expected_revision: Optional[int] = None,
    *,
    allow_any_editor: bool = False,
    preserve_status: bool = False,
) -> Dict[str, Any]:
    if any(skill["id"] == skill_id for skill in _builtin_skills()):
        raise SkillCatalogError("内置 Skill 只读，可先复制为自定义 Skill")
    retained_payload = copy.deepcopy(payload)
    try:
        current = get_custom_skill(skill_id, user_id, include_archived=True)
    except SkillStoreError as exc:
        raise SkillCatalogError(str(exc)) from exc
    if current and "markdownBody" not in retained_payload and current.get("markdownBody"):
        retained_payload["markdownBody"] = current["markdownBody"]
    definition = _custom_definition(retained_payload, skill_id=skill_id)
    try:
        result = _enrich_skill(
            update_custom_skill(
                skill_id,
                definition,
                user_id,
                expected_revision,
                allow_any_editor=allow_any_editor,
                preserve_status=preserve_status,
            ),
            builtin=False,
        )
        _custom_skills_cache_clear()
        return result
    except (SkillStoreConflict, SkillStoreNotFound, SkillStoreError) as exc:
        raise SkillCatalogError(str(exc)) from exc


def publish_skill_definition(skill_id: str, user_id: str, change_note: str = "") -> Dict[str, Any]:
    try:
        current = get_custom_skill(skill_id, user_id)
        if not current:
            raise SkillStoreNotFound("自定义 Skill 不存在")
        _validate_skill(current, set())
        result = _enrich_skill(
            publish_custom_skill(skill_id, user_id, change_note),
            builtin=False,
        )
        _custom_skills_cache_clear()
        return result
    except (SkillStoreConflict, SkillStoreNotFound, SkillStoreError) as exc:
        raise SkillCatalogError(str(exc)) from exc


def archive_skill_definition(skill_id: str, user_id: str) -> Dict[str, Any]:
    if any(skill["id"] == skill_id for skill in _builtin_skills()):
        raise SkillCatalogError("内置 Skill 不能归档")
    try:
        result = _enrich_skill(archive_custom_skill(skill_id, user_id), builtin=False)
        _custom_skills_cache_clear()
        return result
    except (SkillStoreNotFound, SkillStoreError) as exc:
        raise SkillCatalogError(str(exc)) from exc


def list_skill_versions(skill_id: str, user_id: str) -> List[Dict[str, Any]]:
    try:
        return store_list_skill_versions(skill_id, user_id)
    except (SkillStoreNotFound, SkillStoreError) as exc:
        raise SkillCatalogError(str(exc)) from exc


def rollback_skill_definition(skill_id: str, version: int, user_id: str) -> Dict[str, Any]:
    try:
        result = _enrich_skill(rollback_custom_skill(skill_id, version, user_id), builtin=False)
        _custom_skills_cache_clear()
        return result
    except (SkillStoreNotFound, SkillStoreError) as exc:
        raise SkillCatalogError(str(exc)) from exc
