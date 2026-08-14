import urllib.request
import urllib.error
import urllib.parse
import json
import ssl
import logging
import os

logger = logging.getLogger("indicator-service")

INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "").strip()


def _service_headers(url: str) -> dict:
    """Attach the shared service credential only to protected admin-service calls."""
    return (
        {"X-Service-Token": INTERNAL_SERVICE_TOKEN}
        if INTERNAL_SERVICE_TOKEN and "/api/admin/" in str(url)
        else {}
    )


def _create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url, timeout=10, headers=None):
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Content-Type", "application/json")
        for k, v in _service_headers(url).items():
            req.add_header(k, v)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"HTTP GET failed for {url}: {e}")
        return None


def http_post(url, data=None, timeout=10, headers=None):
    try:
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in _service_headers(url).items():
            req.add_header(k, v)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        ctx = _create_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"HTTP POST failed for {url}: {e}")
        return None


def http_post_stream(url, data=None, timeout=180):
    try:
        body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        ctx = _create_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            for line in resp:
                yield line.decode("utf-8")
    except Exception as e:
        logger.error(f"HTTP POST stream failed for {url}: {e}")
        yield json.dumps({"type": "error", "message": f"请求失败: {str(e)[:300]}"}, ensure_ascii=False) + "\n"


def fetch_available_databases(admin_service_url: str) -> list:
    try:
        data = http_get(f"{admin_service_url}/api/admin/database/list", timeout=5)
        if data and data.get("success"):
            return data.get("databases", [])
    except Exception as e:
        logger.warning(f"Failed to fetch databases: {e}")
    return []


def fetch_ontology_context(ontology_id: str = "", question: str = "", top_k: int = 20):
    """获取本体上下文（B 阶段数据联动，供 LLM prompt 注入）。

    仅归档本体参与下游数据联动：
    - ontology_id 为空 → 调 GET /ontology/archived/context（合并所有归档本体）
    - 非空 → 调 GET /ontology/{id}/context（取指定本体，未归档返回空）
    - 失败/超时返回 None（优雅降级，三服务 prompt 不含本体时正常工作）

    Returns:
        {"summary_text": str, "entities": list, "relations": list, "ontology": dict} 或 None
    """
    # 延迟导入避免循环依赖；ONTOLOGY_SERVICE_URL 在 config.py 中从环境变量读取
    from config import ONTOLOGY_SERVICE_URL
    try:
        params = urllib.parse.urlencode({"question": question, "top_k": top_k})
        if ontology_id:
            url = f"{ONTOLOGY_SERVICE_URL}/ontology/{ontology_id}/context?{params}"
        else:
            url = f"{ONTOLOGY_SERVICE_URL}/ontology/archived/context?{params}"
        data = http_get(url, timeout=8)
        if data and data.get("success") and data.get("data"):
            return data["data"]
    except Exception as e:
        logger.warning(f"fetch_ontology_context failed: {e}")
    return None


def create_stream_response(generator):
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        generator,
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
