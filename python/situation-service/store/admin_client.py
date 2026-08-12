"""admin-service 客户端：态势产物持久化 CRUD（不直连 DB，ADR-11）。

通过 urllib 调 admin-service 的 /api/admin/situation/* 接口。
失败时返回 {success:False, message}，不抛异常阻断流程。
"""
import json
import logging
import urllib.request
import urllib.error

import config

logger = logging.getLogger("situation-service")


def _identity_headers(actor: dict = None) -> dict:
    actor = actor or {}
    return {
        "X-Service-Token": config.INTERNAL_SERVICE_TOKEN,
        "X-User-Id": str(actor.get("userId") or ""),
        "X-Team-Ids": ",".join(str(item) for item in actor.get("teamIds") or []),
        "X-User-Role": str(actor.get("role") or "viewer"),
    }


def _http(method: str, path: str, body: dict = None, timeout: int = None, actor: dict = None) -> dict:
    """调用 admin-service。返回解析后的 JSON。"""
    url = f"{config.ADMIN_SERVICE_URL}{path}"
    timeout = timeout or config.HTTP_TIMEOUT
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for name, value in _identity_headers(actor).items():
        if value:
            req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        logger.warning("admin %s %s 失败 HTTP %s: %s", method, url, e.code, msg[:200])
        return {"success": False, "message": f"HTTP {e.code}: {msg[:200]}"}
    except Exception as e:
        logger.warning("admin %s %s 失败: %s", method, url, e)
        return {"success": False, "message": str(e)[:200]}


def save_report(report: dict, actor: dict = None) -> dict:
    """生成完成后落库（POST 新建或 PUT 更新）。"""
    report_id = report.get("reportId", "")
    # 先尝试 PUT 更新，不存在则 POST 新建
    upd = _http("PUT", f"/api/admin/situation/reports/{report_id}", report, actor=actor)
    if upd.get("success"):
        return upd
    return _http("POST", "/api/admin/situation/reports", report, actor=actor)


def get_report(report_id: str, actor: dict = None) -> dict:
    return _http("GET", f"/api/admin/situation/reports/{report_id}", actor=actor)


def list_reports(user_id: str = "", team_ids: list = None, page: int = 1, size: int = 20, actor: dict = None) -> dict:
    params = f"page={page}&size={size}"
    if user_id:
        params += f"&userId={user_id}"
    if team_ids:
        params += f"&teamIds={','.join(team_ids)}"
    return _http("GET", f"/api/admin/situation/reports?{params}", actor=actor)


def delete_report(report_id: str, actor: dict = None) -> dict:
    return _http("DELETE", f"/api/admin/situation/reports/{report_id}", actor=actor)


def create_share(report_id: str, actor: dict = None) -> dict:
    return _http("POST", f"/api/admin/situation/reports/{report_id}/share", actor=actor)


def get_share(token: str) -> dict:
    return _http("GET", f"/api/admin/situation/share/{token}")


def list_datasets(actor: dict = None) -> dict:
    """读取已注册数据集，供 Skill 执行前检查匹配物理表。"""
    return _http("GET", "/api/admin/dataset/authorized-list", timeout=min(config.HTTP_TIMEOUT, 5), actor=actor)
