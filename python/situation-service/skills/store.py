"""态势 Skill 的自定义定义、版本、收藏和使用记录持久化。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import config


class SkillStoreError(RuntimeError):
    """Skill 持久化不可用或操作冲突。"""


class SkillStoreConflict(SkillStoreError):
    """修订冲突或 ID 重复。"""


class SkillStoreNotFound(SkillStoreError):
    """记录不存在或当前用户不可见。"""


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect() -> sqlite3.Connection:
    global _SCHEMA_READY
    path = Path(config.SITUATION_SKILL_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=8, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    if not _SCHEMA_READY:
        with _SCHEMA_LOCK:
            if not _SCHEMA_READY:
                _ensure_schema(connection)
                _SCHEMA_READY = True
    return connection


@contextmanager
def _connection():
    """sqlite3.Connection 的上下文不会自动 close，这里统一确保句柄释放。"""
    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS situation_custom_skills (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            revision INTEGER NOT NULL DEFAULT 1,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_situation_skills_owner
            ON situation_custom_skills(owner_id, status);

        CREATE TABLE IF NOT EXISTS situation_skill_versions (
            skill_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            definition_json TEXT NOT NULL,
            status TEXT NOT NULL,
            change_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            PRIMARY KEY(skill_id, version),
            FOREIGN KEY(skill_id) REFERENCES situation_custom_skills(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS situation_skill_favorites (
            user_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, skill_id)
        );

        CREATE TABLE IF NOT EXISTS situation_skill_usage (
            report_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            query TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_situation_usage_user
            ON situation_skill_usage(user_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_situation_usage_skill
            ON situation_skill_usage(skill_id, status);
        """
    )


def _decode_skill(row: sqlite3.Row) -> Dict[str, Any]:
    definition = json.loads(row["definition_json"])
    definition.update({
        "source": "custom",
        "isBuiltIn": False,
        "ownerId": row["owner_id"],
        "status": row["status"],
        "revision": row["revision"],
        "version": row["version"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    })
    return definition


def list_custom_skills(user_id: str = "", include_archived: bool = False) -> List[Dict[str, Any]]:
    try:
        with _connection() as connection:
            clauses = ["(status = 'published' OR owner_id = ?)"]
            params: List[Any] = [user_id]
            if not include_archived:
                clauses.append("status <> 'archived'")
            rows = connection.execute(
                f"SELECT * FROM situation_custom_skills WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
                params,
            ).fetchall()
            return [_decode_skill(row) for row in rows]
    except (sqlite3.DatabaseError, OSError, json.JSONDecodeError) as exc:
        raise SkillStoreError(str(exc)) from exc


def get_custom_skill(
    skill_id: str,
    user_id: str = "",
    *,
    include_archived: bool = False,
) -> Optional[Dict[str, Any]]:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM situation_custom_skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if not row:
                return None
            if row["status"] != "published" and row["owner_id"] != user_id:
                return None
            if row["status"] == "archived" and not include_archived:
                return None
            return _decode_skill(row)
    except (sqlite3.DatabaseError, OSError, json.JSONDecodeError) as exc:
        raise SkillStoreError(str(exc)) from exc


def create_custom_skill(definition: Dict[str, Any], owner_id: str) -> Dict[str, Any]:
    now = _utc_now()
    skill_id = definition["id"]
    payload = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO situation_custom_skills
                   (id, owner_id, definition_json, status, revision, version, created_at, updated_at)
                   VALUES (?, ?, ?, 'draft', 1, 1, ?, ?)""",
                (skill_id, owner_id, payload, now, now),
            )
            connection.execute(
                """INSERT INTO situation_skill_versions
                   (skill_id, version, definition_json, status, change_note, created_at, created_by)
                   VALUES (?, 1, ?, 'draft', '创建草稿', ?, ?)""",
                (skill_id, payload, now, owner_id),
            )
            connection.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        raise SkillStoreConflict(f"Skill ID 已存在: {skill_id}") from exc
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc
    result = get_custom_skill(skill_id, owner_id)
    assert result is not None
    return result


def update_custom_skill(
    skill_id: str,
    definition: Dict[str, Any],
    owner_id: str,
    expected_revision: Optional[int] = None,
    *,
    allow_any_editor: bool = False,
    preserve_status: bool = False,
) -> Dict[str, Any]:
    now = _utc_now()
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM situation_custom_skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if not row or (row["owner_id"] != owner_id and not allow_any_editor):
                raise SkillStoreNotFound("自定义 Skill 不存在或无权编辑")
            if expected_revision is not None and row["revision"] != expected_revision:
                raise SkillStoreConflict(
                    f"Skill 已被更新，当前修订为 {row['revision']}，请刷新后重试"
                )
            # 在线 Markdown 编辑保留发布状态，避免一次小改动把共享 Skill 降级为草稿。
            status = row["status"] if preserve_status else (
                "draft" if row["status"] == "published" else row["status"]
            )
            if status == "archived":
                raise SkillStoreConflict("已归档 Skill 不能编辑")
            revision = row["revision"] + 1
            payload = json.dumps(definition, ensure_ascii=False, separators=(",", ":"))
            connection.execute(
                """UPDATE situation_custom_skills
                   SET definition_json = ?, status = ?, revision = ?, updated_at = ?
                   WHERE id = ?""",
                (payload, status, revision, now, skill_id),
            )
            connection.execute("COMMIT")
    except (SkillStoreNotFound, SkillStoreConflict):
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc
    result = get_custom_skill(skill_id, owner_id)
    assert result is not None
    return result


def publish_custom_skill(skill_id: str, owner_id: str, change_note: str = "") -> Dict[str, Any]:
    now = _utc_now()
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM situation_custom_skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if not row or row["owner_id"] != owner_id:
                raise SkillStoreNotFound("自定义 Skill 不存在或无权发布")
            if row["status"] == "archived":
                raise SkillStoreConflict("已归档 Skill 不能发布")
            published_version = connection.execute(
                "SELECT MAX(version) AS version FROM situation_skill_versions WHERE skill_id = ? AND status = 'published'",
                (skill_id,),
            ).fetchone()["version"]
            version = 1 if published_version is None else int(published_version) + 1
            revision = row["revision"] + 1
            connection.execute(
                """UPDATE situation_custom_skills
                   SET status = 'published', version = ?, revision = ?, updated_at = ? WHERE id = ?""",
                (version, revision, now, skill_id),
            )
            connection.execute(
                """INSERT OR REPLACE INTO situation_skill_versions
                   (skill_id, version, definition_json, status, change_note, created_at, created_by)
                   VALUES (?, ?, ?, 'published', ?, ?, ?)""",
                (skill_id, version, row["definition_json"], change_note[:300], now, owner_id),
            )
            connection.execute("COMMIT")
    except (SkillStoreNotFound, SkillStoreConflict):
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc
    result = get_custom_skill(skill_id, owner_id)
    assert result is not None
    return result


def archive_custom_skill(skill_id: str, owner_id: str) -> Dict[str, Any]:
    now = _utc_now()
    try:
        with _connection() as connection:
            cursor = connection.execute(
                """UPDATE situation_custom_skills SET status = 'archived', revision = revision + 1, updated_at = ?
                   WHERE id = ? AND owner_id = ? AND status <> 'archived'""",
                (now, skill_id, owner_id),
            )
            if cursor.rowcount != 1:
                raise SkillStoreNotFound("自定义 Skill 不存在或无权归档")
    except SkillStoreNotFound:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc
    result = get_custom_skill(skill_id, owner_id, include_archived=True)
    assert result is not None
    return result


def list_skill_versions(skill_id: str, owner_id: str) -> List[Dict[str, Any]]:
    current = get_custom_skill(skill_id, owner_id, include_archived=True)
    if not current or current["ownerId"] != owner_id:
        raise SkillStoreNotFound("自定义 Skill 不存在或无权查看版本")
    try:
        with _connection() as connection:
            rows = connection.execute(
                "SELECT * FROM situation_skill_versions WHERE skill_id = ? ORDER BY version DESC",
                (skill_id,),
            ).fetchall()
            return [{
                "skillId": row["skill_id"],
                "version": row["version"],
                "status": row["status"],
                "changeNote": row["change_note"],
                "createdAt": row["created_at"],
                "createdBy": row["created_by"],
            } for row in rows]
    except sqlite3.DatabaseError as exc:
        raise SkillStoreError(str(exc)) from exc


def rollback_custom_skill(skill_id: str, version: int, owner_id: str) -> Dict[str, Any]:
    now = _utc_now()
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM situation_custom_skills WHERE id = ? AND owner_id = ?",
                (skill_id, owner_id),
            ).fetchone()
            snapshot = connection.execute(
                "SELECT * FROM situation_skill_versions WHERE skill_id = ? AND version = ?",
                (skill_id, version),
            ).fetchone()
            if not current or not snapshot:
                raise SkillStoreNotFound("Skill 或目标版本不存在")
            connection.execute(
                """UPDATE situation_custom_skills
                   SET definition_json = ?, status = 'draft', version = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ?""",
                (snapshot["definition_json"], version, now, skill_id),
            )
            connection.execute("COMMIT")
    except SkillStoreNotFound:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc
    result = get_custom_skill(skill_id, owner_id)
    assert result is not None
    return result


def set_favorite(user_id: str, skill_id: str, favorite: bool) -> bool:
    try:
        with _connection() as connection:
            connection.execute(
                """INSERT INTO situation_skill_favorites(user_id, skill_id, favorite, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, skill_id) DO UPDATE SET favorite = excluded.favorite, updated_at = excluded.updated_at""",
                (user_id, skill_id, 1 if favorite else 0, _utc_now()),
            )
        return favorite
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc


def list_favorite_ids(user_id: str) -> List[str]:
    try:
        with _connection() as connection:
            rows = connection.execute(
                "SELECT skill_id FROM situation_skill_favorites WHERE user_id = ? AND favorite = 1 ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return [row["skill_id"] for row in rows]
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc


def start_usage(report_id: str, user_id: str, skill_id: str, query: str) -> None:
    try:
        with _connection() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO situation_skill_usage
                   (report_id, user_id, skill_id, query, status, duration_ms, started_at, finished_at)
                   VALUES (?, ?, ?, ?, 'running', 0, ?, '')""",
                (report_id, user_id, skill_id, query[:2000], _utc_now()),
            )
    except (sqlite3.DatabaseError, OSError) as exc:
        raise SkillStoreError(str(exc)) from exc


def finish_usage(report_id: str, status: str) -> None:
    now = _utc_now()
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT started_at FROM situation_skill_usage WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if not row:
                return
            started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            duration_ms = max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
            connection.execute(
                "UPDATE situation_skill_usage SET status = ?, duration_ms = ?, finished_at = ? WHERE report_id = ?",
                (status, duration_ms, now, report_id),
            )
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        raise SkillStoreError(str(exc)) from exc


def list_usage(user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    try:
        with _connection() as connection:
            rows = connection.execute(
                """SELECT report_id, skill_id, query, status, duration_ms, started_at, finished_at
                   FROM situation_skill_usage WHERE user_id = ? ORDER BY started_at DESC LIMIT ?""",
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
            return [{
                "reportId": row["report_id"],
                "skillId": row["skill_id"],
                "query": row["query"],
                "status": row["status"],
                "durationMs": row["duration_ms"],
                "startedAt": row["started_at"],
                "finishedAt": row["finished_at"],
            } for row in rows]
    except sqlite3.DatabaseError as exc:
        raise SkillStoreError(str(exc)) from exc


def usage_stats(user_id: str) -> Dict[str, Dict[str, int]]:
    try:
        with _connection() as connection:
            rows = connection.execute(
                """SELECT skill_id, COUNT(*) AS uses,
                          SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS successes
                   FROM situation_skill_usage WHERE user_id = ? GROUP BY skill_id""",
                (user_id,),
            ).fetchall()
            return {
                row["skill_id"]: {"uses": int(row["uses"]), "successes": int(row["successes"] or 0)}
                for row in rows
            }
    except sqlite3.DatabaseError as exc:
        raise SkillStoreError(str(exc)) from exc
