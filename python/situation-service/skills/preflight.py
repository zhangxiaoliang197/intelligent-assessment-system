"""态势 Skill 执行前检查：定义、参数、发布状态与数据源可用性。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

import config
from store import admin_client

from .catalog import SkillCatalogError, get_skill, validate_skill_parameters


_CACHE_LOCK = threading.Lock()
_SOURCE_CACHE: Dict[str, Any] = {"expires": 0.0, "tables": set(), "adminReady": False}


def _dataset_snapshot() -> Dict[str, Any]:
    now = time.monotonic()
    with _CACHE_LOCK:
        if _SOURCE_CACHE["expires"] > now:
            return dict(_SOURCE_CACHE)
    response = admin_client.list_datasets()
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
        "adminReady": bool(response.get("success")) if isinstance(response, dict) else False,
    }
    with _CACHE_LOCK:
        _SOURCE_CACHE.update(snapshot)
    return snapshot


def _probe_health(base_url: str) -> bool:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            if response.status >= 400:
                return False
            body = json.loads(response.read().decode("utf-8"))
            return str(body.get("status") or "healthy").lower() in {"healthy", "ok"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def _source_check(source: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    if source.startswith("t_"):
        matched = source in snapshot["tables"]
        return {
            "source": source,
            "status": "passed" if matched else "error",
            "message": "已匹配注册数据集" if matched else "未找到对应物理数据集",
        }
    if source == "admin":
        ready = bool(snapshot["adminReady"])
        return {
            "source": source,
            "status": "passed" if ready else "error",
            "message": "管理数据服务可用" if ready else "管理数据服务不可用",
        }
    service_urls = {
        "knowledge": config.KNOWLEDGE_SERVICE_URL,
        "indicator": config.INDICATOR_SERVICE_URL,
        "evaluation": config.QA_SERVICE_URL,
    }
    if source in service_urls:
        ready = _probe_health(service_urls[source])
        return {
            "source": source,
            # 外围服务不可用给出警告；物理数据仍可支持降级执行。
            "status": "passed" if ready else "warning",
            "message": "服务连接正常" if ready else "服务当前不可达，将降级使用其他数据源",
        }
    return {
        "source": source,
        "status": "warning",
        "message": "未配置专用连通性检查器",
    }


def preflight_skill(
    skill_id: str,
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    *,
    user_id: str = "",
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

    snapshot = _dataset_snapshot()
    source_checks = [_source_check(source, snapshot) for source in skill["dataSources"]]
    for item in source_checks:
        checks.append({
            "key": f"source:{item['source']}",
            "label": "数据源",
            "status": item["status"],
            "message": f"{item['source']}：{item['message']}",
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
        "dataSources": source_checks,
    }
