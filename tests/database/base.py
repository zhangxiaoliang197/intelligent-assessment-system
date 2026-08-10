"""Shared harness for the database / data-source test suite.

Two URL bases are used throughout:

- ADMIN_URL  — the Spring Boot admin-service  (default http://localhost:10258)
- QA_URL     — the FastAPI qa-service         (default http://localhost:10253)

Both can be overridden with the ADMIN_URL / QA_URL environment variables or
the --admin-url / --qa-url flags of run_tests.py.
"""

from __future__ import annotations

import os
import unittest

import requests

ADMIN_URL = os.environ.get("ADMIN_URL", "http://localhost:10258").rstrip("/")
QA_URL = os.environ.get("QA_URL", "http://localhost:10253").rstrip("/")

_DEFAULT_TIMEOUT = 15


class BaseServiceTest(unittest.TestCase):
    """Base class for tests that hit the running services over HTTP."""

    admin = ADMIN_URL
    qa = QA_URL

    #: ids of temporary resources created by this test class, cleaned up in tearDownClass
    created_database_ids: list[str] = []
    created_dataset_ids: list[str] = []
    created_indicator_ids: list[str] = []

    # ------------------------------------------------------------------ HTTP

    def _request(self, method: str, url: str, *, json=None, expect: int | None = 200, timeout: int = _DEFAULT_TIMEOUT):
        resp = requests.request(method, url, json=json, timeout=timeout)
        if expect is not None and resp.status_code != expect:
            self.fail(
                f"{method} {url} -> HTTP {resp.status_code} (expected {expect}): {resp.text[:500]}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def admin_get(self, path, expect=200, **kw):
        return self._request("GET", self.admin + path, expect=expect, **kw)

    def admin_post(self, path, json=None, expect=200, **kw):
        return self._request("POST", self.admin + path, json=json, expect=expect, **kw)

    def admin_put(self, path, json=None, expect=200, **kw):
        return self._request("PUT", self.admin + path, json=json, expect=expect, **kw)

    def admin_delete(self, path, expect=200, **kw):
        return self._request("DELETE", self.admin + path, expect=expect, **kw)

    def qa_get(self, path, expect=200, **kw):
        return self._request("GET", self.qa + path, expect=expect, **kw)

    def qa_post(self, path, json=None, expect=200, **kw):
        return self._request("POST", self.qa + path, json=json, expect=expect, **kw)

    # ------------------------------------------------------------ assertions

    def assertSuccess(self, payload, message: str = "response missing success=true"):
        self.assertIsInstance(payload, dict, f"expected dict payload, got {payload!r}")
        self.assertTrue(payload.get("success"), f"{message}; payload={payload}")

    def assertApiError(self, payload, *needles, message: str = "expected error payload"):
        self.assertIsInstance(payload, dict, f"expected dict payload, got {payload!r}")
        self.assertFalse(payload.get("success", True), f"{message}; payload={payload}")
        msg = str(payload.get("message", ""))
        for needle in needles:
            self.assertIn(needle, msg, f"error message {msg!r} missing {needle!r}")

    # ------------------------------------------------------------- discovery

    @classmethod
    def list_databases(cls):
        payload = requests.get(f"{ADMIN_URL}/api/admin/database/list", timeout=_DEFAULT_TIMEOUT).json()
        return payload.get("databases", [])

    @classmethod
    def find_database(cls, **criteria):
        for db in cls.list_databases():
            if all(db.get(k) == v for k, v in criteria.items()):
                return db
        return None

    @classmethod
    def connected_mysql_id(cls) -> str:
        """Return the id of the first MySQL config whose status is 已连接, else ''."""
        for db in cls.list_databases():
            if db.get("type") == "MySQL" and db.get("status") in ("已连接", "connected", "active"):
                return db["id"]
        return ""

    @classmethod
    def any_connected_id(cls) -> str:
        for db in cls.list_databases():
            if db.get("status") in ("已连接", "connected", "active"):
                return db["id"]
        return ""

    # --------------------------------------------------------------- cleanup

    @classmethod
    def tearDownClass(cls):
        for db_id in cls.created_database_ids:
            try:
                requests.delete(f"{ADMIN_URL}/api/admin/database/{db_id}", timeout=_DEFAULT_TIMEOUT)
            except requests.RequestException:
                pass
        for ds_id in cls.created_dataset_ids:
            try:
                requests.delete(f"{ADMIN_URL}/api/admin/dataset/{ds_id}", timeout=_DEFAULT_TIMEOUT)
            except requests.RequestException:
                pass
        for ind_id in cls.created_indicator_ids:
            try:
                requests.delete(f"{ADMIN_URL}/api/admin/indicator/{ind_id}", timeout=_DEFAULT_TIMEOUT)
            except requests.RequestException:
                pass
        super().tearDownClass()


def require_connected_database(test_case: unittest.TestCase) -> str:
    """Skip a test class unless a reachable database config exists.

    Returns the connected database id. Call from setUpClass and store it.
    """
    db_id = BaseServiceTest.any_connected_id()
    if not db_id:
        raise unittest.SkipTest("没有可用的已连接数据库配置，跳过集成测试（请先在基础管理配置一个可连接的数据库）")
    return db_id
