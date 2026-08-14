"""态势 Skill 执行前检查：定义、参数、发布状态与已授权数据集。

不再检查固定 dataSources 列表的连通性：V2 Agent 架构下，LLM 基于前端选定的
数据源下所有已授权数据集 schema 动态决策，无需在执行前逐一探活外部服务。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from store import admin_client

from .catalog import SkillCatalogError, get_skill, validate_skill_parameters


_CACHE_LOCK = threading.Lock()
_SOURCE_CACHE: Dict[str, Dict[str, Any]] = {}


def _actor_cache_key(actor: Dict[str, Any] = None) -> str:
    actor = actor or {}
    teams = sorted(str(item) for item in actor.get("teamIds") or [])
    return "|".join([
        str(actor.get("userId") or ""), ",".join(teams), str(actor.get("role") or "viewer"),
    ])


def _dataset_snapshot(actor: Dict[str, Any] = None) -> Dict[str, Any]:
    now = time.monotonic()
    cache_key = _actor_cache_key(actor)
    with _CACHE_LOCK:
        cached = _SOURCE_CACHE.get(cache_key)
        if cached and cached["expires"] > now:
            return dict(cached)
    response = admin_client.list_datasets(actor)
    datasets = response.get("datasets") if isinstance(response, dict) else []
    if not isinstance(datasets, list) and isinstance(response, dict):
        wrapped = response.get("data")
        if isinstance(wrapped, list):
            datasets = wrapped
        elif isinstance(wrapped, dict):
            datasets = wrapped.get("datasets", [])
    if not isinstance(datasets, list):
        datasets = []
    tables = {
        str(dataset.get("tableName") or "").strip()
        for dataset in datasets
        if isinstance(dataset, dict) and dataset.get("tableName")
    }
    snapshot = {
        "expires": now + 15.0,
        "tables": tables,
        "datasets": datasets,
        "adminReady": bool(response.get("success")) if isinstance(response, dict) else False,
    }
    with _CACHE_LOCK:
        _SOURCE_CACHE[cache_key] = snapshot
    return snapshot


def preflight_skill(
    skill_id: str,
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    user_id: str = "",
    team_ids: Optional[List[str]] = None,
    role: str = "viewer",
    data_source_id: str = "",
) -> Dict[str, Any]:
    skill = get_skill(skill_id, user_id)
    if not skill:
        raise SkillCatalogError(f"态势图 Skill 不存在: {skill_id}")

    checks: List[Dict[str, Any]] = []
    if skill.get("status") == "published":
        checks.append({"key": "publication", "label": "发布状态", "status": "passed", "message": "Skill 已发布"})
    else:
        checks.append({"key": "publication", "label": "发布状态", "status": "error", "message": "Skill 尚未发布"})

    try:
        resolved_parameters = validate_skill_parameters(skill, parameters)
        checks.append({"key": "parameters", "label": "参数配置", "status": "passed", "message": "参数校验通过"})
    except SkillCatalogError as exc:
        resolved_parameters = {}
        checks.append({"key": "parameters", "label": "参数配置", "status": "error", "message": str(exc)})

    normalized_query = str(query or "").strip()
    if normalized_query:
        checks.append({"key": "query", "label": "分析问题", "status": "passed", "message": "问题已填写"})
    else:
        checks.append({
            "key": "query",
            "label": "分析问题",
            "status": "warning",
            "message": f"未填写问题，将使用推荐问题：{skill['recommendedQuestions'][0]}",
        })

    snapshot = _dataset_snapshot({"userId": user_id, "teamIds": team_ids or [], "role": role})
    selected_database = str(data_source_id or "").strip()
    if selected_database:
        selected_datasets = [
            item for item in snapshot.get("datasets", [])
            if str(item.get("databaseId") or item.get("dataSourceId") or "").strip() == selected_database
        ]
        snapshot = {
            **snapshot,
            "datasets": selected_datasets,
            "tables": {
                str(item.get("tableName") or "").strip()
                for item in selected_datasets if item.get("tableName")
            },
        }
        checks.append({
            "key": "database",
            "label": "选定数据源",
            "status": "passed" if selected_datasets else "error",
            "message": (
                f"选定数据源包含 {len(selected_datasets)} 个已授权数据集"
                if selected_datasets else "选定数据源没有当前用户可访问的数据集"
            ),
        })
    else:
        # 未指定数据源时，校验当前用户是否有任意已授权数据集。
        any_authorized = bool(snapshot.get("datasets"))
        checks.append({
            "key": "database",
            "label": "数据集授权",
            "status": "passed" if any_authorized else "warning",
            "message": (
                f"当前用户共有 {len(snapshot.get('datasets') or [])} 个已授权数据集可用"
                if any_authorized else "当前用户没有任何已授权数据集，LLM 将无法生成方案"
            ),
        })

    errors = [check["message"] for check in checks if check["status"] == "error"]
    warnings = [check["message"] for check in checks if check["status"] == "warning"]
    return {
        "skillId": skill["id"],
        "skillName": skill["name"],
        "ready": not errors,
        "complete": not errors and not warnings,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "parameters": resolved_parameters,
        "parameterDefinitions": skill.get("parameters", []),
        "executionPlan": [
            {"sequence": index, "name": step}
            for index, step in enumerate(skill["steps"], start=1)
        ],
    }
