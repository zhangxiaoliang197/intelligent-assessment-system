"""交互页面产物 SQLite 持久化（独立轻库，零 Java 改动）。

表 ipage_page：保存生成任务状态、最终 HTML、数据包、规划与 SQL 日志，
供历史列表、修订（parentId）和服务重启后的结果回放使用。
表 ipage_session / ipage_message：对话式会话与消息，主对话框页与态势页
共享同一会话；页面通过 session_id 列挂到会话上。
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("ipage-service")

_lock = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.IPAGE_DB), exist_ok=True)
    conn = sqlite3.connect(config.IPAGE_DB, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """幂等建表。"""
    global _initialized
    with _lock:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ipage_page (
                    id            TEXT PRIMARY KEY,
                    title         TEXT NOT NULL DEFAULT '',
                    query         TEXT NOT NULL DEFAULT '',
                    user_id       TEXT NOT NULL DEFAULT '',
                    team_ids      TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'generating',
                    intent        TEXT NOT NULL DEFAULT '',
                    direct_answer TEXT NOT NULL DEFAULT '',
                    html          TEXT NOT NULL DEFAULT '',
                    data_bundle   TEXT NOT NULL DEFAULT '',
                    plan_json     TEXT NOT NULL DEFAULT '',
                    parent_id     TEXT NOT NULL DEFAULT '',
                    session_id    TEXT NOT NULL DEFAULT '',
                    sql_log       TEXT NOT NULL DEFAULT '',
                    error         TEXT NOT NULL DEFAULT '',
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ipage_user_time ON ipage_page(user_id, created_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ipage_session (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL DEFAULT '',
                    user_id     TEXT NOT NULL DEFAULT '',
                    team_ids    TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ipage_message (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL DEFAULT '',
                    role        TEXT NOT NULL DEFAULT 'user',
                    kind        TEXT NOT NULL DEFAULT 'text',
                    content     TEXT NOT NULL DEFAULT '',
                    page_id     TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ipage_message_session ON ipage_message(session_id, created_at)"
            )
            # ipage_page 增列 session_id（老库幂等迁移；新库由建表语句保证）
            try:
                conn.execute("ALTER TABLE ipage_page ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # 列已存在，忽略
            conn.commit()
            _migrate_legacy_pages(conn)
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def _migrate_legacy_pages(conn: sqlite3.Connection) -> None:
    """存量页面迁移：session_id 为空的历史页面聚合进"历史记录"会话，旧数据不丢。

    每个用户一个历史会话（id 稳定可重入）；已完成页面补写 user + ai 两条消息，
    失败页面补写错误文本，进行中（generating）的存量任务不进会话。
    """
    rows = conn.execute(
        """SELECT id, title, query, user_id, status, intent, direct_answer, error, created_at
           FROM ipage_page WHERE session_id = '' ORDER BY created_at ASC, rowid ASC"""
    ).fetchall()
    if not rows:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    by_user: Dict[str, List[sqlite3.Row]] = {}
    for row in rows:
        by_user.setdefault(row["user_id"] or "local-admin", []).append(row)
    for user_id, items in by_user.items():
        sid = "s_legacy_" + hashlib.md5(user_id.encode("utf-8")).hexdigest()[:8]
        conn.execute(
            "INSERT OR IGNORE INTO ipage_session (id, title, user_id, team_ids, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (sid, "历史记录", user_id, "", items[0]["created_at"] or now,
             items[-1]["created_at"] or now),
        )
        for row in items:
            status, intent = row["status"], row["intent"]
            if status == "generating":
                continue  # 重启前未完成的存量任务不再回填，避免半途产物混入对话
            conn.execute(
                "UPDATE ipage_page SET session_id = ? WHERE id = ?", (sid, row["id"]),
            )
            conn.execute(
                "INSERT INTO ipage_message (id, session_id, role, kind, content, page_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"m_{uuid.uuid4().hex[:12]}", sid, "user", "text",
                 row["query"] or row["title"] or "", "", row["created_at"] or now),
            )
            if status == "ready" and intent == "general":
                kind, content, page_id = "direct", row["direct_answer"] or row["title"] or "已完成", ""
            elif status == "ready":
                kind = "page_card"
                content = json.dumps({"pageId": row["id"], "title": row["title"]}, ensure_ascii=False)
                page_id = row["id"]
            else:
                kind, content, page_id = "error", row["error"] or "生成失败", row["id"]
            conn.execute(
                "INSERT INTO ipage_message (id, session_id, role, kind, content, page_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"m_{uuid.uuid4().hex[:12]}", sid, "ai", kind, content, page_id, row["created_at"] or now),
            )
        logger.info("存量交互页面已迁移至历史会话: user=%s pages=%s session=%s", user_id, len(items), sid)


def _loads(raw: str, default: Any) -> Any:
    """安全解析 SQLite 中的 JSON 文本列。"""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """数据库行 → 对外的驼峰字段字典。"""
    return {
        "pageId": row["id"],
        "title": row["title"],
        "query": row["query"],
        "userId": row["user_id"],
        "teamIds": [t for t in (row["team_ids"] or "").split(",") if t],
        "status": row["status"],
        "intent": row["intent"],
        "directAnswer": row["direct_answer"],
        "html": row["html"],
        "dataBundle": _loads(row["data_bundle"], {}),
        "plan": _loads(row["plan_json"], {}),
        "parentId": row["parent_id"],
        "sessionId": row["session_id"],
        "sqlLog": _loads(row["sql_log"], []),
        "error": row["error"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def upsert_page(page: Dict[str, Any]) -> bool:
    """新建或更新产物（按 id 全量覆盖可变字段）。"""
    init_db()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    existing = get_page(page.get("id", ""))
    created_at = (existing or {}).get("createdAt") or now
    team_ids = page.get("teamIds") or []
    if isinstance(team_ids, (list, tuple)):
        team_ids = ",".join(str(t) for t in team_ids)
    payload = (
        str(page.get("id") or ""),
        str(page.get("title") or "")[:200],
        str(page.get("query") or ""),
        str(page.get("userId") or ""),
        str(team_ids),
        str(page.get("status") or "generating"),
        str(page.get("intent") or ""),
        str(page.get("directAnswer") or ""),
        str(page.get("html") or ""),
        json.dumps(page.get("dataBundle") or {}, ensure_ascii=False, default=str),
        json.dumps(page.get("plan") or {}, ensure_ascii=False, default=str),
        str(page.get("parentId") or ""),
        str(page.get("sessionId") or ""),
        json.dumps(page.get("sqlLog") or [], ensure_ascii=False, default=str),
        str(page.get("error") or "")[:500],
        created_at,
        now,
    )
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO ipage_page
                (id, title, query, user_id, team_ids, status, intent, direct_answer,
                 html, data_bundle, plan_json, parent_id, session_id, sql_log, error,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )
            conn.commit()
            return True
        except sqlite3.Error as exc:
            logger.error("交互页面落库失败 id=%s: %s", page.get("id"), exc)
            return False
        finally:
            conn.close()


def get_page(page_id: str) -> Optional[Dict[str, Any]]:
    """按 id 读取单个产物；不存在返回 None。"""
    init_db()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM ipage_page WHERE id = ?", (page_id,)
            ).fetchone()
            if not row:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()


def list_pages(user_id: str, team_ids: List[str], page_no: int = 1, size: int = 20,
               role: str = "viewer") -> Dict[str, Any]:
    """分页列出当前用户可见的产物（本人 + 同团队；admin 全部）。"""
    init_db()
    page_no = max(1, page_no)
    size = max(1, min(size, 100))
    clauses: List[str] = []
    params: List[Any] = []
    if role != "admin":
        or_parts = ["user_id = ?"]
        params.append(user_id)
        for team in team_ids or []:
            or_parts.append("(',' || team_ids || ',') LIKE ?")
            params.append(f"%,{team},%")
        clauses.append("(" + " OR ".join(or_parts) + ")")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    with _lock:
        conn = _connect()
        try:
            total = conn.execute(
                f"SELECT COUNT(1) AS c FROM ipage_page{where}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"""SELECT id, title, query, user_id, status, intent, parent_id,
                           created_at, updated_at, LENGTH(html) AS html_length
                    FROM ipage_page{where}
                    ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                params + [size, (page_no - 1) * size],
            ).fetchall()
        finally:
            conn.close()

    items = [{
        "pageId": r["id"],
        "title": r["title"],
        "query": r["query"],
        "userId": r["user_id"],
        "status": r["status"],
        "intent": r["intent"],
        "parentId": r["parent_id"],
        "hasHtml": r["html_length"] > 0,
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    } for r in rows]
    return {"items": items, "total": total, "page": page_no, "size": size}


def delete_page(page_id: str) -> bool:
    """删除产物。"""
    init_db()
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute("DELETE FROM ipage_page WHERE id = ?", (page_id,))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            logger.error("交互页面删除失败 id=%s: %s", page_id, exc)
            return False
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────────
# 会话 / 消息（对话式交互：主对话框页与态势页共享同一会话）
# ──────────────────────────────────────────────────────────────────

def create_session(user_id: str, team_ids: List[str], title: str = "") -> Dict[str, Any]:
    """新建空会话，返回会话字典。"""
    init_db()
    sid = f"s_{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO ipage_session (id, title, user_id, team_ids, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (sid, str(title or "")[:100], user_id, ",".join(str(t) for t in team_ids or []), now, now),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.error("会话创建失败 user=%s: %s", user_id, exc)
            raise
        finally:
            conn.close()
    return {"sessionId": sid, "title": title or "", "userId": user_id,
            "teamIds": list(team_ids or []), "createdAt": now, "updatedAt": now}


def list_sessions(user_id: str, team_ids: List[str], page_no: int = 1, size: int = 20,
                  role: str = "viewer") -> Dict[str, Any]:
    """分页列出当前用户可见的会话（本人 + 同团队；admin 全部）。"""
    init_db()
    page_no = max(1, page_no)
    size = max(1, min(size, 100))
    clauses: List[str] = []
    params: List[Any] = []
    if role != "admin":
        or_parts = ["s.user_id = ?"]
        params.append(user_id)
        for team in team_ids or []:
            or_parts.append("(',' || s.team_ids || ',') LIKE ?")
            params.append(f"%,{team},%")
        clauses.append("(" + " OR ".join(or_parts) + ")")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    with _lock:
        conn = _connect()
        try:
            total = conn.execute(
                f"SELECT COUNT(1) AS c FROM ipage_session s{where}", params
            ).fetchone()["c"]
            rows = conn.execute(
                f"""SELECT s.id, s.title, s.user_id, s.created_at, s.updated_at,
                           (SELECT COUNT(1) FROM ipage_message m WHERE m.session_id = s.id) AS message_count,
                           (SELECT COUNT(1) FROM ipage_page p WHERE p.session_id = s.id AND p.html != '') AS page_count
                    FROM ipage_session s{where}
                    ORDER BY s.updated_at DESC LIMIT ? OFFSET ?""",
                params + [size, (page_no - 1) * size],
            ).fetchall()
        finally:
            conn.close()

    items = [{
        "sessionId": r["id"],
        "title": r["title"],
        "userId": r["user_id"],
        "messageCount": r["message_count"],
        "pageCount": r["page_count"],
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    } for r in rows]
    return {"items": items, "total": total, "page": page_no, "size": size}


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """读取会话详情：基本信息 + 全部消息 + 关联页面摘要；不存在返回 None。"""
    init_db()
    with _lock:
        conn = _connect()
        try:
            srow = conn.execute(
                "SELECT * FROM ipage_session WHERE id = ?", (session_id,)
            ).fetchone()
            if not srow:
                return None
            messages = [{
                "messageId": m["id"],
                "sessionId": m["session_id"],
                "role": m["role"],
                "kind": m["kind"],
                "content": m["content"],
                "pageId": m["page_id"],
                "createdAt": m["created_at"],
            } for m in conn.execute(
                "SELECT * FROM ipage_message WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()]
            pages = [{
                "pageId": p["id"],
                "title": p["title"],
                "query": p["query"],
                "status": p["status"],
                "intent": p["intent"],
                "createdAt": p["created_at"],
            } for p in conn.execute(
                """SELECT id, title, query, status, intent, created_at FROM ipage_page
                   WHERE session_id = ? AND status != 'generating' ORDER BY created_at ASC, rowid ASC""",
                (session_id,),
            ).fetchall()]
        finally:
            conn.close()
    return {
        "sessionId": srow["id"],
        "title": srow["title"],
        "userId": srow["user_id"],
        "teamIds": [t for t in (srow["team_ids"] or "").split(",") if t],
        "messages": messages,
        "pages": pages,
        "createdAt": srow["created_at"],
        "updatedAt": srow["updated_at"],
    }


def delete_session(session_id: str) -> bool:
    """删除会话及其全部消息（页面产物保留，仅解除挂载避免迁移复活）。"""
    init_db()
    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM ipage_message WHERE session_id = ?", (session_id,))
            cursor = conn.execute("DELETE FROM ipage_session WHERE id = ?", (session_id,))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            logger.error("会话删除失败 id=%s: %s", session_id, exc)
            return False
        finally:
            conn.close()


def append_message(session_id: str, role: str, kind: str, content: str,
                   page_id: str = "") -> Optional[Dict[str, Any]]:
    """向会话追加一条消息（user/ai），并刷新会话 updated_at。"""
    init_db()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    mid = f"m_{uuid.uuid4().hex[:12]}"
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO ipage_message (id, session_id, role, kind, content, page_id, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (mid, session_id, role, kind, content or "", page_id or "", now),
            )
            conn.execute(
                "UPDATE ipage_session SET updated_at = ? WHERE id = ?", (now, session_id),
            )
            conn.commit()
            return {"messageId": mid, "sessionId": session_id, "role": role, "kind": kind,
                    "content": content or "", "pageId": page_id or "", "createdAt": now}
        except sqlite3.Error as exc:
            logger.error("会话消息写入失败 session=%s: %s", session_id, exc)
            return None
        finally:
            conn.close()


def set_page_session(page_id: str, session_id: str) -> bool:
    """把页面挂到会话上（session_id 列回填）。"""
    init_db()
    with _lock:
        conn = _connect()
        try:
            cursor = conn.execute(
                "UPDATE ipage_page SET session_id = ? WHERE id = ?", (session_id or "", page_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            logger.error("页面会话挂载失败 page=%s session=%s: %s", page_id, session_id, exc)
            return False
        finally:
            conn.close()


def delete_messages_by_page(page_id: str) -> None:
    """页面被删除时同步移除其会话内的页面卡片消息，保持对话一致。"""
    init_db()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "DELETE FROM ipage_message WHERE page_id = ? AND kind = 'page_card'", (page_id,),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.error("会话卡片消息清理失败 page=%s: %s", page_id, exc)
        finally:
            conn.close()
