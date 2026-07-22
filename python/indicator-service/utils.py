import urllib.request
import urllib.error
import json
import ssl
import logging

logger = logging.getLogger("indicator-service")


def _create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url, timeout=10, headers=None):
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Content-Type", "application/json")
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