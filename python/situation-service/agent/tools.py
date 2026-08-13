"""LLM Agent 工具集（Phase 2 启用）。

数据工具（取真实数据，数据源无关）：
  query_datasets_meta  调 admin-service /export/for-llm，取全量数据集 schema + 指标定义
  query_admin_data     调 admin-service /dataset/{id}/data，执行数据集 SQL 取数据行
  query_knowledge      调 qa-service 知识检索
  get_indicators       调 indicator-service 指标列表
  get_evaluation       调 qa-service 评估结果
  fetch_external_data  外部实时数据源（预留）

产出工具（编排器内部构造 SSE 事件用，LLM 返回 JSON 后由编排器转事件）：
  render_chart / render_map_layer / write_narrative

所有工具为同步实现（urllib），编排器通过 asyncio.to_thread 调用以避免阻塞事件循环。
"""
import json
import logging
import urllib.parse
import urllib.request
import urllib.error

import config

logger = logging.getLogger("situation-service")


def _http_get(url: str, timeout: int = None) -> dict:
    """GET 请求并返回解析后的 JSON。失败返回 {success:False, message}。"""
    timeout = timeout or config.HTTP_TIMEOUT
    req = urllib.request.Request(url, method="GET")
    req.add_header("Content-Type", "application/json")
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


def _http_post(url: str, body: dict, timeout: int = None) -> dict:
    """POST 请求并返回解析后的 JSON。失败返回 {success:False, message}。

    态势图专用端点（如 SQL 执行）走 X-Service-Token 服务身份，而非管理员角色。
    """
    timeout = timeout or config.HTTP_TIMEOUT
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Service-Token", config.INTERNAL_SERVICE_TOKEN)
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
    """知识库检索（调 qa-service）。"""
    q = urllib.parse.quote(query)
    return _http_get(f"{config.QA_SERVICE_URL}/qa/search?q={q}&top_k={top_k}")


def get_indicators(database_id: str = "") -> dict:
    """取指标列表（调 admin-service /indicator/list）。

    Args:
        database_id: 数据源 ID。非空时仅返回该数据源下的指标（后端按 databaseId 过滤）。
    """
    url = f"{config.ADMIN_SERVICE_URL}/api/admin/indicator/list"
    if database_id:
        url += f"?databaseId={urllib.parse.quote(database_id)}"
    return _http_get(url)


def get_evaluation(evaluation_id: str) -> dict:
    """取评估结果（调 qa-service 暴露的 evaluation 端点）。"""
    return _http_get(f"{config.QA_SERVICE_URL}/evaluation/{evaluation_id}")


def fetch_external_data(adapter: str, params: dict = None) -> dict:
    """外部实时数据源适配器（预留，Q-03 待定规范）。"""
    logger.info("外部数据源适配器调用: adapter=%s（预留）", adapter)
    return {"success": False, "message": "外部数据源适配器尚未配置"}


# ── 产出工具（编排器构造 SSE 事件用，LLM 返回 JSON 后转事件）──
def render_chart(chart_id: str, chart_type: str, title: str, option: dict,
                 dataset_ref: str = "", explanation: str = "") -> dict:
    """产出单个图表（ECharts option）。"""
    return {"chartId": chart_id, "type": chart_type, "title": title,
            "option": option, "datasetRef": dataset_ref, "explanation": explanation}


def render_map_layer(layer_id: str, points: list = None, routes: list = None,
                     areas: list = None, circles: list = None,
                     layer_config: dict = None) -> dict:
    """产出地图图层（WGS84 坐标）。"""
    return {"layerId": layer_id, "points": points or [], "routes": routes or [],
            "areas": areas or [], "circles": circles or [],
            "layerConfig": layer_config or {}}


def write_narrative(intro: str, explanations: list) -> dict:
    """产出态势介绍 + 逐图说明（最后调用，非结论先行）。"""
    return {"intro": intro, "explanations": explanations}
