"""LLM Agent 工具集（Phase 2 启用）。

每个工具对应一个数据/产出接口，供 tool-calling 循环派发。
Phase 1 仅提供桩实现与下游调用封装，不被 mock 编排器使用。

工具清单（与 docs/situation-map/03 §2 一致）：
  query_knowledge / get_indicators / get_evaluation / query_admin_data
  fetch_external_data（预留）
  render_chart / render_map_layer / write_narrative（产出工具）
"""
import json
import logging
import re
import urllib.parse
import urllib.request
import urllib.error
from contextvars import ContextVar
from contextlib import contextmanager

import config

logger = logging.getLogger("situation-service")

_ACTOR: ContextVar[dict] = ContextVar("situation_actor", default={})


@contextmanager
def actor_context(actor: dict = None):
    """Bind the end-user identity to downstream calls made by the current task."""
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


def _add_identity_headers(req: urllib.request.Request) -> None:
    for name, value in _identity_headers().items():
        if value:
            req.add_header(name, value)


def _http_get(url: str, timeout: int = None) -> dict:
    """GET 请求并返回解析后的 JSON。失败返回 {success:False, message}。"""
    timeout = timeout or config.HTTP_TIMEOUT
    req = urllib.request.Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
    _add_identity_headers(req)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        logger.warning("GET %s 失败 HTTP %s: %s", url, e.code, body[:200])
        return {"success": False, "message": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        logger.warning("GET %s 失败: %s", url, e)
        return {"success": False, "message": str(e)[:200]}


def _http_json(method: str, url: str, body: dict = None, timeout: int = None) -> dict:
    """调用 JSON HTTP 接口；网络或协议错误转成可降级的结果。"""
    timeout = timeout or config.HTTP_TIMEOUT
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    _add_identity_headers(req)
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


def _http_post(url: str, body: dict, timeout: int = None) -> dict:
    """POST 请求并返回解析后的 JSON。失败返回 {success:False, message}。

    态势图专用端点（如 SQL 执行）走 X-Service-Token 服务身份，而非管理员角色。
    """
    timeout = timeout or config.HTTP_TIMEOUT
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    _add_identity_headers(req)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        logger.warning("POST %s 失败 HTTP %s: %s", url, e.code, err_body[:200])
        return {"success": False, "message": f"HTTP {e.code}: {err_body[:200]}"}
    except Exception as e:
        logger.warning("POST %s 失败: %s", url, e)
        return {"success": False, "message": str(e)[:200]}


def query_datasets_meta(database_id: str = "") -> dict:
    """取数据集 schema + 指标定义（调 admin-service /export/for-llm）。

    Args:
        database_id: 数据源 ID。非空时仅返回该数据源下的数据集与指标（后端按 databaseId 过滤）；
                     为空时返回全量（向后兼容）。

    返回 {schemas:[...], indicators:[...]}，供 LLM 规划要查哪些数据。
    数据源无关：LLM 据此发现可用数据集，不硬编码任何表名/字段。
    """
    url = f"{config.ADMIN_SERVICE_URL}/api/admin/export/for-llm"
    if database_id:
        url += f"?databaseId={urllib.parse.quote(database_id)}"
    return _http_get(url, timeout=config.HTTP_TIMEOUT)


def query_admin_data(dataset_id: str, limit: int = 200) -> dict:
    """执行数据集查询，返回数据行（调 admin-service /dataset/{id}/data）。

    通用能力：执行数据集定义的 sql_text（或回退 SELECT * FROM tableName），
    返回 {columns, rows, total}。数据集自带 databaseId，执行时自动连对应数据源。
    """
    return _http_get(
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{dataset_id}/data?limit={limit}",
        timeout=config.HTTP_TIMEOUT,
    )


def execute_dataset_sql(dataset_id: str, sql: str) -> dict:
    """在数据集关联的数据库上执行 LLM 生成的只读 SQL（态势图专用端点）。

    复用评估分析的 Text-to-SQL 执行能力：SQL 由 LLM 按该数据集的表结构生成，
    可含 WHERE 过滤、聚合、GROUP BY、排序与 LIMIT，解决原 /dataset/{id}/data
    只能按数据集预定义 sql_text 或整表拉取、无法针对问题精确取数的问题。

    返回 {success, columns, rows, rowCount, ...}。失败返回 {success:False, message}。
    """
    return _http_post(
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{dataset_id}/execute-query",
        {"sql": sql},
        timeout=config.SQL_QUERY_TIMEOUT,
    )


def query_knowledge(query: str, top_k: int = 5) -> dict:
    """调用知识库的真实混合检索接口。

    知识库首次请求会加载向量模型（sentence-transformers），冷启动可能超过默认
    HTTP_TIMEOUT，因此单独放宽超时，避免首次提问被误判为超时失败。
    """
    return _http_json(
        "POST",
        f"{config.KNOWLEDGE_SERVICE_URL}/knowledge/search",
        {"query": query, "top_k": max(1, min(int(top_k), 20))},
        timeout=max(config.HTTP_TIMEOUT, 60),
    )


def get_indicators(indicator_ids: list = None) -> dict:
    """读取真实指标目录，并按上下文中的指标 ID 过滤。"""
    result = _http_get(f"{config.INDICATOR_SERVICE_URL}/indicator/list")
    if indicator_ids and isinstance(result.get("indicators"), list):
        wanted = {str(item) for item in indicator_ids}
        result["indicators"] = [
            item for item in result["indicators"]
            if str(item.get("id", "")) in wanted or str(item.get("name", "")) in wanted
        ]
    return result


def get_evaluation(evaluation_id: str) -> dict:
    """读取评估分析会话快照。"""
    safe_id = urllib.parse.quote(str(evaluation_id), safe="")
    return _http_get(f"{config.QA_SERVICE_URL}/evaluation/session/{safe_id}")


def get_dataset_meta(dataset_id: str) -> dict:
    """读取已注册数据集元数据（不含字段结构，字段结构请用 fetch_dataset_structure）。"""
    safe_id = urllib.parse.quote(str(dataset_id), safe="")
    return _http_get(f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{safe_id}")


def fetch_dataset_structure(dataset_id: str) -> dict:
    """读取数据集物理表结构，构建 Text-to-SQL 所需的 schema（含 fields 元数据）。

    返回 {tableName, columns, fields, count}，fields 每项含 column/type/comment/isPrimaryKey。
    与评估分析读取表结构的思路一致，供 LLM 生成精确的 WHERE/聚合/GROUP BY。
    """
    safe_id = urllib.parse.quote(str(dataset_id), safe="")
    result = _http_get(
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{safe_id}/structure",
        timeout=config.HTTP_TIMEOUT,
    )
    if not isinstance(result, dict) or not result.get("success"):
        return {"tableName": "", "columns": [], "fields": [], "count": 0}
    columns = [c for c in (result.get("columns") or []) if isinstance(c, dict)]
    fields = [{
        "column": c.get("columnName", ""),
        "type": c.get("dataType", ""),
        "isPrimaryKey": bool(c.get("isPrimaryKey", False)),
        "comment": c.get("comment", ""),
    } for c in columns]
    return {
        "tableName": result.get("tableName", ""),
        "columns": columns,
        "fields": fields,
        "count": len(fields),
    }


def list_admin_datasets() -> dict:
    """读取当前执行身份获授权的真实数据集。"""
    return _http_get(f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/authorized-list")


def query_admin_dataset(dataset: dict, row_limit: int = None) -> dict:
    """在注册数据集上执行只读查询并返回真实记录。

    优先使用管理员保存的数据集 SQL；未配置时只允许从安全的物理表标识符构造
    ``SELECT *``。最终行数同时受 admin-service 的只读校验和硬上限保护。
    """
    dataset_id = str(dataset.get("id") or "").strip()
    table_name = str(dataset.get("tableName") or "").strip()
    if not dataset_id:
        return {"success": False, "message": "数据集 ID 为空"}
    safe_id = urllib.parse.quote(dataset_id, safe="")
    # 只调用服务端拥有的查询模板。Skill 和浏览器都不能再提交 SQL；admin-service
    # 会二次验证服务身份、用户的数据集 ACL、物理表绑定与允许列。
    result = _http_json(
        "POST",
        f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{safe_id}/query",
        {"limit": min(int(row_limit or config.SITUATION_DATA_ROW_LIMIT), 1000)},
        timeout=max(config.HTTP_TIMEOUT, 65),
    )
    limit = row_limit or config.SITUATION_DATA_ROW_LIMIT
    if isinstance(result.get("rows"), list):
        result["rows"] = result["rows"][:limit]
        result["rowCount"] = len(result["rows"])
    result["dataset"] = {
        "id": dataset_id,
        "name": dataset.get("name", ""),
        "tableName": table_name,
        "description": dataset.get("description", ""),
        "schemaVersion": dataset.get("schemaVersion", 1),
        "sensitiveColumns": dataset.get("sensitiveColumns") or [],
    }
    return result


def fetch_external_data(adapter: str, params: dict = None) -> dict:
    """外部实时数据源适配器（预留，Q-03 待定规范）。Phase 2+ 启用。"""
    logger.info("外部数据源适配器调用: adapter=%s（预留）", adapter)
    return {"success": False, "message": "外部数据源适配器尚未配置"}


# ── 产出工具（Phase 2 由编排器调用，同时通过 SSE 推送事件）──
def render_chart(chart_id: str, chart_type: str, title: str, option: dict, dataset_ref: str = "") -> dict:
    """产出单个图表（ECharts option）。Phase 2 由编排器派发。"""
    return {"chartId": chart_id, "type": chart_type, "title": title,
            "option": option, "datasetRef": dataset_ref}


def render_map_layer(layer_id: str, points: list = None, routes: list = None,
                     areas: list = None, layer_config: dict = None) -> dict:
    """产出地图图层（WGS84 坐标）。Phase 2 由编排器派发。"""
    return {"layerId": layer_id, "points": points or [], "routes": routes or [],
            "areas": areas or [], "layerConfig": layer_config or {}}


def write_narrative(intro: str, map_explanation: str = "") -> dict:
    """产出态势介绍 + 地图说明（逐图说明已随图表 explanation 字段生成）。"""
    return {"intro": intro, "mapExplanation": map_explanation}
