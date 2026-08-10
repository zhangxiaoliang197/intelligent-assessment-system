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


def query_knowledge(query: str, top_k: int = 5) -> dict:
    """知识库检索（调 qa-service）。Phase 2 启用。"""
    return _http_get(f"{config.QA_SERVICE_URL}/qa/search?q={query}&top_k={top_k}")


def get_indicators(indicator_ids: list = None) -> dict:
    """取指标数据（调 indicator-service）。Phase 2 启用。"""
    return _http_get(f"{config.INDICATOR_SERVICE_URL}/indicator/list")


def get_evaluation(evaluation_id: str) -> dict:
    """取评估结果（调 qa-service 暴露的 evaluation 端点）。Phase 2 启用。"""
    return _http_get(f"{config.QA_SERVICE_URL}/evaluation/{evaluation_id}")


def query_admin_data(dataset_id: str) -> dict:
    """取数据源/字段/原始记录（调 admin-service）。Phase 2 启用。"""
    return _http_get(f"{config.ADMIN_SERVICE_URL}/api/admin/dataset/{dataset_id}")


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


def write_narrative(intro: str, explanations: list) -> dict:
    """产出态势介绍 + 逐图说明（最后调用，非结论先行）。"""
    return {"intro": intro, "explanations": explanations}
