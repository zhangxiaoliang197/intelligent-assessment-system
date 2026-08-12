# -*- coding: utf-8 -*-
"""执行验证：将 admin 中每个指标的 indicatorSpec 编译为 SQL 并在实库执行。"""
import json
import os
import sys
import urllib.request

ADMIN = os.environ.get("ADMIN_SERVICE_URL", "http://localhost:10258")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python", "qa-service"))

from agents.indicator_engine import compile_indicator_spec, _quote_style_for
from agents.tools import execute_sql_on_database, fetch_database_config


def api_get(path):
    with urllib.request.urlopen(f"{ADMIN}{path}", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    inds = api_get("/api/admin/indicator/list").get("indicators", [])
    dss = {d["id"]: d for d in api_get("/api/admin/dataset/list").get("datasets", [])}
    dbs = {d["id"]: d for d in api_get("/api/admin/database/list").get("databases", [])}
    results = []
    for ind in inds:
        name = ind["name"]
        spec_raw = ind.get("indicatorSpec") or ""
        if not spec_raw:
            results.append((name, "no_spec", "", 0))
            continue
        try:
            spec = json.loads(spec_raw)
        except json.JSONDecodeError:
            results.append((name, "bad_json", "", 0))
            continue
        ds = dss.get(ind.get("datasetId") or "")
        db = dbs.get((ds or {}).get("databaseId") or "", {})
        quote = _quote_style_for(db.get("type", ""))
        ok, plan = compile_indicator_spec(spec, check_schema=None, quote_style=quote)
        if not ok:
            results.append((name, "compile_fail", ";".join(plan["errors"]), 0))
            continue
        db_id = (ds or {}).get("databaseId") or ""
        res = execute_sql_on_database(db_id, plan["sql"])
        if not res.get("success"):
            results.append((name, "exec_fail", str(res.get("message", ""))[:160], 0))
            continue
        rows = res.get("rows") or res.get("data") or []
        first = rows[0] if rows else {}
        results.append((name, "ok", json.dumps(first, ensure_ascii=False)[:200], len(rows)))

    for name, status, detail, n in results:
        print(f"[{status}] {name} | {n} 行 | {detail}")
    print(f"\n合计 {len(results)}，成功 {sum(1 for r in results if r[1] == 'ok')}")


if __name__ == "__main__":
    main()
