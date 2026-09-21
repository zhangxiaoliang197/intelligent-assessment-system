"""admin-service HTTP 客户端（ipage-service 独立实现）。

仅依赖平台级能力，与 situation-service 无代码耦合：
- query_datasets_meta：数据集元数据 + 指标（/export/for-llm）
- fetch_dataset_structure：物理表结构（Text-to-SQL 用）
- execute_dataset_sql：执行 LLM 生成的只读 SELECT
- query_dataset_full：整表查询兜底
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

import config

logger = logging.getLogger("ipage-service")

_ACTOR: ContextVar[dict] = ContextVar("ipage_actor", default={})


@contextmanager
def actor_context(actor: Optional[dict] = None):
    """把终端用户身份绑定到当前任务的下游调用（数据集 ACL 由 admin 校验）。"""
    token = _ACTOR.set(dict(actor or {}))
    try:
        yield
    finally:
        _ACTOR.reset(token)


def _identity_headers() -> dict:
    actor = _ACTOR.get() or {}
    return {
        "X-Service-Token": config.INTERNAL_SERVICE_TOKEN,
        "X-User-Id": str(actor.get("userId") or ""),
        "X-Team-Ids": ",".join(str(item) for item in actor.get("teamIds") or []),
        "X-User-Role": str(actor.get("role") or "viewer"),
    }


def _request(method: str, url: str, body: dict = None, timeout: int = None) -> dict:
    """统一 JSON HTTP 调用；错误转为 {success:False, message} 可降级结果。"""
    timeout = timeout or config.HTTP_TIMEOUT
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for name, value in _identity_headers().items():
        if value:
            req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="ignore")
        logger.warning("%s %s 失败 HTTP %s: %s", method, url, exc.code, payload[:200])
        return {"success": False, "message": f"HTTP {exc.code}: {payload[:200]}"}
    except Exception as exc:
        logger.warning("%s %s 失败: %s", method, url, exc)
        return {"success": False, "message": str(exc)[:200]}


def query_datasets_meta(database_id: str = "") -> dict:
    """取数据集 schema + 指标定义（/export/for-llm），供 Planner 选择数据集。

    响应中另含 ``semanticSchema``（语义注解格式规范）与每个数据集的
    ``semanticJson``/字段级 ``semanticJson``，由 dimension_graph 解析与校验。

    注意：无字段注解的数据集会降级读物理表结构（列 COMMENT 兜底），不会跳过；
    仅当数据库配置缺失/读取失败/过滤后无可见字段时才不出现在结果中。
    """
    url = f"{config.ADMIN_SERVICE_URL}/api/admin/export/for-llm"
    if database_id:
        url += f"?databaseId={urllib.parse.quote(database_id)}"
    return _request("GET", url, timeout=config.HTTP_TIMEOUT)


def fetch_dataset_structure(dataset_id: str) -> dict:
    """读取数据集物理表结构，返回 {tableName, fields:[{column,type,comment}]}。"""
    safe_id = urllib.parse.quote(str(dataset_id), safe="")
    result = _request(
        "GET",
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{safe_id}/structure",
        timeout=config.HTTP_TIMEOUT,
    )
    if not isinstance(result, dict) or not result.get("success"):
        return {"tableName": "", "fields": []}
    columns = [c for c in (result.get("columns") or []) if isinstance(c, dict)]
    fields = [{
        "column": c.get("columnName", ""),
        "type": c.get("dataType", ""),
        "isPrimaryKey": bool(c.get("isPrimaryKey", False)),
        "comment": c.get("comment", ""),
    } for c in columns]
    return {"tableName": result.get("tableName", ""), "fields": fields}


def execute_dataset_sql(dataset_id: str, sql: str) -> dict:
    """执行 LLM 生成的只读 SQL（admin 侧强制只读与 ACL）。"""
    safe_id = urllib.parse.quote(str(dataset_id), safe="")
    return _request(
        "POST",
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{safe_id}/execute-query",
        {"sql": sql},
        timeout=config.SQL_QUERY_TIMEOUT,
    )


def query_dataset_full(dataset_id: str, row_limit: int = None) -> dict:
    """整表只读查询兜底（数据集预定义 SQL 或 SELECT *，admin 侧二次校验）。"""
    safe_id = urllib.parse.quote(str(dataset_id), safe="")
    limit = min(int(row_limit or config.IPAGE_DATA_ROW_LIMIT), 1000)
    return _request(
        "POST",
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{safe_id}/query",
        {"limit": limit},
        timeout=max(config.HTTP_TIMEOUT, 65),
    )
