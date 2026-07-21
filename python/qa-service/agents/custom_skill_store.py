"""SQLite persistence for user-authored evaluation Skills.

The store is intentionally unaware of the Skill schema. Validation and
normalization stay in ``skill_catalog`` while this module provides durable,
multi-thread/process-safe CRUD with optimistic revisions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from typing import Any, Dict, List, Optional


logger = logging.getLogger("evaluation.custom_skill_store")
_last_store_warning = ""


_DB_PATH = os.environ.get(
    "EVALUATION_SKILL_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "custom_skills.sqlite3",
    ),
)


class CustomSkillStoreError(RuntimeError):
    """Base error for custom Skill persistence."""


class CustomSkillStoreNotFound(CustomSkillStoreError):
    """Raised when a custom Skill no longer exists."""


class CustomSkillStoreConflict(CustomSkillStoreError):
    """Raised when optimistic revision checks fail."""


def _name_key(skill: Dict[str, Any]) -> str:
    name = unicodedata.normalize("NFKC", str(skill.get("name") or "")).strip().casefold()
    return re.sub(r"[\s_\-./]+", "", name)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_skills (
            id TEXT PRIMARY KEY,
            name_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            owner_id TEXT NOT NULL DEFAULT 'local-admin',
            team_id TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'public',
            status TEXT NOT NULL DEFAULT 'published',
            tags_json TEXT NOT NULL DEFAULT '[]',
            is_template INTEGER NOT NULL DEFAULT 0,
            published_version INTEGER,
            current_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(custom_skills)").fetchall()
    }
    if "name_key" not in columns:
        try:
            connection.execute("ALTER TABLE custom_skills ADD COLUMN name_key TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise
        rows = connection.execute("SELECT id, payload_json FROM custom_skills ORDER BY id").fetchall()
        seen: set[str] = set()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            base_key = _name_key(payload) or f"invalid-{row['id']}"
            key = base_key if base_key not in seen else f"{base_key}-{row['id']}"
            seen.add(key)
            connection.execute(
                "UPDATE custom_skills SET name_key = ? WHERE id = ?", (key, row["id"])
            )
    governance_columns = {
        "owner_id": "TEXT NOT NULL DEFAULT 'local-admin'",
        "team_id": "TEXT NOT NULL DEFAULT ''",
        "visibility": "TEXT NOT NULL DEFAULT 'public'",
        "status": "TEXT NOT NULL DEFAULT 'published'",
        "tags_json": "TEXT NOT NULL DEFAULT '[]'",
        "is_template": "INTEGER NOT NULL DEFAULT 0",
        "published_version": "INTEGER",
        "current_version": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, declaration in governance_columns.items():
        if column in columns:
            continue
        try:
            connection.execute(
                f"ALTER TABLE custom_skills ADD COLUMN {column} {declaration}"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

    # Copy governance data already present in JSON into the new queryable
    # columns. Rows created by the pre-governance release intentionally retain
    # its globally shared semantics (local-admin/public/published).
    rows = connection.execute(
        "SELECT id, payload_json, owner_id, team_id, visibility, status, tags_json, is_template "
        "FROM custom_skills"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        owner_id = str(payload.get("ownerId") or row["owner_id"] or "local-admin")
        team_id = str(payload.get("teamId") or row["team_id"] or "")
        visibility = str(payload.get("visibility") or row["visibility"] or "public")
        status = str(payload.get("status") or row["status"] or "published")
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        is_template = int(bool(payload.get("isTemplate", row["is_template"])))
        connection.execute(
            """
            UPDATE custom_skills
            SET owner_id = ?, team_id = ?, visibility = ?, status = ?,
                tags_json = ?, is_template = ?
            WHERE id = ?
            """,
            (
                owner_id,
                team_id,
                visibility,
                status,
                json.dumps(tags, ensure_ascii=False, separators=(",", ":")),
                is_template,
                row["id"],
            ),
        )

    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_custom_skills_name_key ON custom_skills(name_key)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_versions (
            skill_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            action TEXT NOT NULL,
            change_note TEXT NOT NULL DEFAULT '',
            actor_id TEXT NOT NULL,
            is_published INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (skill_id, version)
        )
        """
    )
    version_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(skill_versions)").fetchall()
    }
    if "change_note" not in version_columns:
        connection.execute(
            "ALTER TABLE skill_versions ADD COLUMN change_note TEXT NOT NULL DEFAULT ''"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_skill_versions_skill ON skill_versions(skill_id, version DESC)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_favorites (
            user_id TEXT NOT NULL,
            skill_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, skill_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_skill_favorites_skill ON skill_favorites(skill_id)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_shares (
            token TEXT PRIMARY KEY,
            skill_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT '',
            revoked_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_skill_shares_skill ON skill_shares(skill_id, created_at DESC)"
    )

    # A baseline snapshot makes legacy records immediately rollback-capable.
    connection.execute(
        """
        INSERT OR IGNORE INTO skill_versions
            (skill_id, version, revision, payload_json, action, actor_id,
             is_published, created_at)
        SELECT id, 1, revision, payload_json, 'migrate', 'local-admin',
               CASE WHEN status = 'published' THEN 1 ELSE 0 END, created_at
        FROM custom_skills
        """
    )
    connection.execute(
        """
        UPDATE custom_skills
        SET published_version = COALESCE(
            published_version,
            CASE WHEN status = 'published' THEN 1 ELSE NULL END
        )
        """
    )
    connection.execute(
        """
        UPDATE custom_skills
        SET current_version = COALESCE(
            (SELECT MAX(version) FROM skill_versions WHERE skill_id = custom_skills.id),
            1
        )
        """
    )
    connection.execute("PRAGMA user_version = 5")


def _connect() -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(_DB_PATH))
    try:
        os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(_DB_PATH, timeout=5, isolation_level=None)
    except OSError as exc:
        raise CustomSkillStoreError(f"无法打开自定义 Skill 库: {exc}") from exc
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        _ensure_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def get_store_warning() -> str:
    return _last_store_warning


@contextmanager
def _connection():
    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def _decode_row(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise CustomSkillStoreError(f"自定义 Skill {row['id']} 的持久化数据已损坏") from exc
    if not isinstance(payload, dict):
        raise CustomSkillStoreError(f"自定义 Skill {row['id']} 的持久化数据格式无效")
    payload["id"] = row["id"]
    payload["revision"] = int(row["revision"])
    payload["createdAt"] = row["created_at"]
    payload["updatedAt"] = row["updated_at"]
    row_keys = set(row.keys())
    if "owner_id" in row_keys:
        payload["ownerId"] = row["owner_id"] or "local-admin"
        payload["teamId"] = row["team_id"] or ""
        payload["visibility"] = row["visibility"] or "public"
        payload["status"] = row["status"] or "published"
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            tags = []
        payload["tags"] = tags if isinstance(tags, list) else []
        payload["isTemplate"] = bool(row["is_template"])
        payload["publishedVersion"] = (
            int(row["published_version"])
            if row["published_version"] is not None
            else None
        )
        payload["version"] = int(row["current_version"] or 1)
        payload["currentVersion"] = payload["version"]
    return payload


def _governance_columns(payload: Dict[str, Any]) -> tuple[str, str, str, str, str, int]:
    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return (
        str(payload.get("ownerId") or "local-admin"),
        str(payload.get("teamId") or ""),
        str(payload.get("visibility") or "public"),
        str(payload.get("status") or "published"),
        json.dumps(tags, ensure_ascii=False, separators=(",", ":")),
        int(bool(payload.get("isTemplate", False))),
    )


def _insert_version(
    connection: sqlite3.Connection,
    record: Dict[str, Any],
    *,
    action: str,
    change_note: str = "",
    actor_id: str,
    created_at: str,
) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS next_version "
        "FROM skill_versions WHERE skill_id = ?",
        (record["id"],),
    ).fetchone()
    version = int(row["next_version"])
    payload = dict(record)
    payload.pop("id", None)
    connection.execute(
        """
        INSERT INTO skill_versions
            (skill_id, version, revision, payload_json, action, change_note,
             actor_id, is_published, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["id"],
            version,
            int(record.get("revision") or 1),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            str(action or "update")[:64],
            str(change_note or "")[:500],
            str(actor_id or "local-admin")[:160],
            int(record.get("status") == "published"),
            created_at,
        ),
    )
    return version


def _decode_version_row(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        snapshot = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise CustomSkillStoreError(
            f"Skill {row['skill_id']} 版本 {row['version']} 的数据已损坏"
        ) from exc
    if not isinstance(snapshot, dict):
        raise CustomSkillStoreError(
            f"Skill {row['skill_id']} 版本 {row['version']} 的格式无效"
        )
    return {
        "skillId": row["skill_id"],
        "version": int(row["version"]),
        "revision": int(row["revision"]),
        "action": row["action"],
        "changeNote": row["change_note"] or "",
        "actorId": row["actor_id"],
        "published": bool(row["is_published"]),
        "createdAt": row["created_at"],
        "snapshot": snapshot,
    }


def list_records() -> List[Dict[str, Any]]:
    global _last_store_warning
    try:
        with _connection() as connection:
            rows = connection.execute(
                "SELECT * FROM custom_skills ORDER BY updated_at DESC, id ASC"
            ).fetchall()
        records = []
        warnings = []
        for row in rows:
            try:
                records.append(_decode_row(row))
            except CustomSkillStoreError as exc:
                # One malformed row must not hide the 15 immutable built-ins or
                # otherwise healthy custom Skills.
                logger.error("Skipping malformed custom Skill row: %s", exc)
                warnings.append(str(exc))
        _last_store_warning = "；".join(warnings)
        return records
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        _last_store_warning = f"无法读取自定义 Skill 库: {exc}"
        raise CustomSkillStoreError(f"无法读取自定义 Skill 库: {exc}") from exc


def get_record(skill_id: str) -> Dict[str, Any] | None:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM custom_skills WHERE id = ?", (skill_id,)
            ).fetchone()
        return _decode_row(row) if row else None
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法读取自定义 Skill: {exc}") from exc


def create_record(
    skill: Dict[str, Any],
    now: str,
    *,
    actor_id: str = "local-admin",
    action: str = "create",
    change_note: str = "",
) -> Dict[str, Any]:
    payload = dict(skill)
    skill_id = str(payload.pop("id"))
    name_key = _name_key(payload)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    owner_id, team_id, visibility, status, tags_json, is_template = _governance_columns(
        payload
    )
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO custom_skills
                    (id, name_key, payload_json, revision, created_at, updated_at,
                     owner_id, team_id, visibility, status, tags_json, is_template)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    name_key,
                    payload_json,
                    now,
                    now,
                    owner_id,
                    team_id,
                    visibility,
                    status,
                    tags_json,
                    is_template,
                ),
            )
            row = connection.execute(
                "SELECT * FROM custom_skills WHERE id = ?", (skill_id,)
            ).fetchone()
            record = _decode_row(row)
            version = _insert_version(
                connection,
                record,
                action=action,
                change_note=change_note,
                actor_id=actor_id,
                created_at=now,
            )
            if record.get("status") == "published":
                connection.execute(
                    "UPDATE custom_skills SET published_version = ? WHERE id = ?",
                    (version, skill_id),
                )
                record["publishedVersion"] = version
            connection.execute(
                "UPDATE custom_skills SET current_version = ? WHERE id = ?",
                (version, skill_id),
            )
            record["version"] = version
            record["currentVersion"] = version
            connection.commit()
    except sqlite3.IntegrityError as exc:
        raise CustomSkillStoreConflict("Skill 名称或 ID 已存在") from exc
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法保存自定义 Skill: {exc}") from exc
    return record


def update_record(
    skill_id: str,
    skill: Dict[str, Any],
    expected_revision: int,
    now: str,
    *,
    actor_id: str = "local-admin",
    action: str = "update",
    change_note: str = "",
) -> Dict[str, Any]:
    payload = dict(skill)
    payload.pop("id", None)
    name_key = _name_key(payload)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    owner_id, team_id, visibility, status, tags_json, is_template = _governance_columns(
        payload
    )
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE custom_skills
                SET name_key = ?, payload_json = ?, revision = revision + 1, updated_at = ?,
                    owner_id = ?, team_id = ?, visibility = ?, status = ?,
                    tags_json = ?, is_template = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    name_key,
                    payload_json,
                    now,
                    owner_id,
                    team_id,
                    visibility,
                    status,
                    tags_json,
                    is_template,
                    skill_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount == 0:
                exists = connection.execute(
                    "SELECT revision FROM custom_skills WHERE id = ?", (skill_id,)
                ).fetchone()
                connection.rollback()
                if not exists:
                    raise CustomSkillStoreNotFound(f"自定义 Skill 不存在: {skill_id}")
                raise CustomSkillStoreConflict(
                    f"Skill 已被其他操作更新，请刷新后重试（当前版本 {exists['revision']}）"
                )
            row = connection.execute(
                "SELECT * FROM custom_skills WHERE id = ?", (skill_id,)
            ).fetchone()
            record = _decode_row(row)
            version = _insert_version(
                connection,
                record,
                action=action,
                change_note=change_note,
                actor_id=actor_id,
                created_at=now,
            )
            if record.get("status") == "published":
                connection.execute(
                    "UPDATE custom_skills SET published_version = ? WHERE id = ?",
                    (version, skill_id),
                )
                record["publishedVersion"] = version
            connection.execute(
                "UPDATE custom_skills SET current_version = ? WHERE id = ?",
                (version, skill_id),
            )
            record["version"] = version
            record["currentVersion"] = version
            connection.commit()
    except (CustomSkillStoreNotFound, CustomSkillStoreConflict):
        raise
    except sqlite3.IntegrityError as exc:
        raise CustomSkillStoreConflict("Skill 名称已存在") from exc
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法更新自定义 Skill: {exc}") from exc
    return record


def delete_record(
    skill_id: str,
    expected_revision: int,
    *,
    actor_id: str = "local-admin",
) -> Dict[str, Any]:
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM custom_skills WHERE id = ?", (skill_id,)
            ).fetchone()
            if not row:
                connection.rollback()
                raise CustomSkillStoreNotFound(f"自定义 Skill 不存在: {skill_id}")
            if int(row["revision"]) != expected_revision:
                connection.rollback()
                raise CustomSkillStoreConflict(
                    f"Skill 已被其他操作更新，请刷新后重试（当前版本 {row['revision']}）"
                )
            try:
                record = _decode_row(row)
            except CustomSkillStoreError:
                record = {
                    "id": row["id"],
                    "revision": int(row["revision"]),
                    "createdAt": row["created_at"],
                    "updatedAt": row["updated_at"],
                }
            if "name" in record:
                _insert_version(
                    connection,
                    record,
                    action="delete",
                    actor_id=actor_id,
                    created_at=record.get("updatedAt") or row["updated_at"],
                )
            connection.execute("DELETE FROM skill_favorites WHERE skill_id = ?", (skill_id,))
            connection.execute("DELETE FROM skill_shares WHERE skill_id = ?", (skill_id,))
            connection.execute("DELETE FROM custom_skills WHERE id = ?", (skill_id,))
            connection.commit()
        return record
    except (CustomSkillStoreNotFound, CustomSkillStoreConflict):
        raise
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法删除自定义 Skill: {exc}") from exc


def list_version_records(skill_id: str) -> List[Dict[str, Any]]:
    """Return newest-first immutable snapshots for one Skill."""

    try:
        with _connection() as connection:
            rows = connection.execute(
                "SELECT * FROM skill_versions WHERE skill_id = ? ORDER BY version DESC",
                (skill_id,),
            ).fetchall()
        return [_decode_version_row(row) for row in rows]
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法读取 Skill 版本历史: {exc}") from exc


def get_version_record(skill_id: str, version: int) -> Optional[Dict[str, Any]]:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_versions WHERE skill_id = ? AND version = ?",
                (skill_id, int(version)),
            ).fetchone()
        return _decode_version_row(row) if row else None
    except CustomSkillStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法读取 Skill 历史版本: {exc}") from exc


def set_favorite_record(user_id: str, skill_id: str, favorite: bool, now: str) -> bool:
    """Idempotently add or remove a user's favorite marker."""

    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if favorite:
                connection.execute(
                    """
                    INSERT INTO skill_favorites (user_id, skill_id, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, skill_id) DO UPDATE SET created_at = excluded.created_at
                    """,
                    (user_id, skill_id, now),
                )
            else:
                connection.execute(
                    "DELETE FROM skill_favorites WHERE user_id = ? AND skill_id = ?",
                    (user_id, skill_id),
                )
            connection.commit()
        return bool(favorite)
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法更新 Skill 收藏状态: {exc}") from exc


def list_favorite_records(user_id: str) -> List[str]:
    try:
        with _connection() as connection:
            rows = connection.execute(
                "SELECT skill_id FROM skill_favorites WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [str(row["skill_id"]) for row in rows]
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法读取 Skill 收藏: {exc}") from exc


def create_share_record(
    token: str,
    skill_id: str,
    created_by: str,
    now: str,
    expires_at: str = "",
) -> Dict[str, Any]:
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO skill_shares
                    (token, skill_id, created_by, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, '')
                """,
                (token, skill_id, created_by, now, expires_at or ""),
            )
            row = connection.execute(
                "SELECT * FROM skill_shares WHERE token = ?", (token,)
            ).fetchone()
            connection.commit()
        return _decode_share_row(row)
    except sqlite3.IntegrityError as exc:
        raise CustomSkillStoreConflict("Skill 分享令牌已存在") from exc
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法创建 Skill 分享: {exc}") from exc


def _decode_share_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "token": row["token"],
        "skillId": row["skill_id"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "expiresAt": row["expires_at"] or "",
        "revokedAt": row["revoked_at"] or "",
        "active": not bool(row["revoked_at"]),
    }


def get_share_record(token: str) -> Optional[Dict[str, Any]]:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_shares WHERE token = ?", (token,)
            ).fetchone()
        return _decode_share_row(row) if row else None
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法读取 Skill 分享: {exc}") from exc


def list_share_records(skill_id: str) -> List[Dict[str, Any]]:
    try:
        with _connection() as connection:
            rows = connection.execute(
                "SELECT * FROM skill_shares WHERE skill_id = ? ORDER BY created_at DESC",
                (skill_id,),
            ).fetchall()
        return [_decode_share_row(row) for row in rows]
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法读取 Skill 分享列表: {exc}") from exc


def revoke_share_record(token: str, now: str) -> Dict[str, Any]:
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE skill_shares SET revoked_at = ? WHERE token = ? AND revoked_at = ''",
                (now, token),
            )
            row = connection.execute(
                "SELECT * FROM skill_shares WHERE token = ?", (token,)
            ).fetchone()
            if not row:
                connection.rollback()
                raise CustomSkillStoreNotFound("Skill 分享不存在")
            # Revocation is idempotent; retain the first timestamp.
            if cursor.rowcount == 0:
                connection.rollback()
                return _decode_share_row(row)
            connection.commit()
        return _decode_share_row(row)
    except CustomSkillStoreNotFound:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise CustomSkillStoreError(f"无法撤销 Skill 分享: {exc}") from exc
