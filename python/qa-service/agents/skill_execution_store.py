"""Durable runtime records for Skill executions, batches and schedules.

The catalog owns Skill definitions.  This module deliberately stores immutable
execution snapshots and scheduling references only, so catalog edits do not
rewrite history and runtime features can be exposed without coupling them to a
specific HTTP framework.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


_DB_PATH = os.environ.get(
    "EVALUATION_RUNTIME_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "skill_runtime.sqlite3",
    ),
)
_SCHEMA_LOCK = threading.RLock()


class SkillExecutionStoreError(RuntimeError):
    """Raised when the runtime database cannot complete an operation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _decode(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _ensure_schema(connection: sqlite3.Connection) -> None:
    with _SCHEMA_LOCK:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_executions (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL DEFAULT '',
                batch_id TEXT NOT NULL DEFAULT '',
                schedule_id TEXT NOT NULL DEFAULT '',
                skill_id TEXT NOT NULL,
                skill_name TEXT NOT NULL DEFAULT '',
                skill_revision INTEGER NOT NULL DEFAULT 0,
                actor_id TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL DEFAULT 'interactive',
                question TEXT NOT NULL DEFAULT '',
                database_id TEXT NOT NULL DEFAULT '',
                database_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                cancellation_requested_at TEXT,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 0,
                matched_steps INTEGER NOT NULL DEFAULT 0,
                completed_steps INTEGER NOT NULL DEFAULT 0,
                skipped_steps INTEGER NOT NULL DEFAULT 0,
                error_steps INTEGER NOT NULL DEFAULT 0,
                synthesis_status TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                skill_snapshot_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_skill_executions_started
                ON skill_executions(started_at DESC);
            CREATE INDEX IF NOT EXISTS ix_skill_executions_skill
                ON skill_executions(skill_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS ix_skill_executions_actor
                ON skill_executions(actor_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS ix_skill_executions_batch
                ON skill_executions(batch_id, started_at ASC);

            CREATE TABLE IF NOT EXISTS skill_execution_steps (
                run_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 0,
                step_id TEXT NOT NULL DEFAULT '',
                step_name TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                dataset_id TEXT NOT NULL DEFAULT '',
                dataset_name TEXT NOT NULL DEFAULT '',
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                event_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (run_id, step_key),
                FOREIGN KEY (run_id) REFERENCES skill_executions(run_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_skill_execution_steps_sequence
                ON skill_execution_steps(run_id, sequence, step_key);

            CREATE TABLE IF NOT EXISTS skill_batches (
                batch_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                actor_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                total_items INTEGER NOT NULL DEFAULT 0,
                completed_items INTEGER NOT NULL DEFAULT 0,
                failed_items INTEGER NOT NULL DEFAULT 0,
                cancelled_items INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                cancellation_requested_at TEXT,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_skill_batches_created
                ON skill_batches(created_at DESC);

            CREATE TABLE IF NOT EXISTS skill_batch_items (
                batch_id TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (batch_id, item_index),
                FOREIGN KEY (batch_id) REFERENCES skill_batches(batch_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS skill_schedules (
                schedule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                question TEXT NOT NULL,
                database_id TEXT NOT NULL,
                database_name TEXT NOT NULL DEFAULT '',
                cron_expression TEXT NOT NULL,
                timezone_name TEXT NOT NULL DEFAULT 'UTC',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                next_run_at TEXT NOT NULL,
                last_run_at TEXT,
                last_run_id TEXT NOT NULL DEFAULT '',
                last_status TEXT NOT NULL DEFAULT '',
                lease_until TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_skill_schedules_due
                ON skill_schedules(enabled, next_run_at);

            CREATE TABLE IF NOT EXISTS skill_quality_reports (
                report_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                skill_id TEXT NOT NULL,
                actor_id TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL DEFAULT 0,
                grade TEXT NOT NULL DEFAULT 'D',
                dimensions_json TEXT NOT NULL DEFAULT '{}',
                issues_json TEXT NOT NULL DEFAULT '[]',
                suggestions_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES skill_executions(run_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_skill_quality_skill
                ON skill_quality_reports(skill_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS ix_skill_quality_actor
                ON skill_quality_reports(actor_id, created_at DESC);
            """
        )
        connection.execute("PRAGMA user_version = 2")


def _connect() -> sqlite3.Connection:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(_DB_PATH)), exist_ok=True)
        connection = sqlite3.connect(_DB_PATH, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        _ensure_schema(connection)
        return connection
    except (OSError, sqlite3.DatabaseError) as exc:
        raise SkillExecutionStoreError(f"无法打开 Skill 运行记录库: {exc}") from exc


@contextmanager
def _connection():
    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def _execution_row(row: sqlite3.Row, *, include_result: bool = True) -> Dict[str, Any]:
    item = {
        "runId": row["run_id"],
        "sessionId": row["session_id"],
        "batchId": row["batch_id"],
        "scheduleId": row["schedule_id"],
        "skillId": row["skill_id"],
        "skillName": row["skill_name"],
        "skillRevision": int(row["skill_revision"]),
        "actorId": row["actor_id"],
        "trigger": row["trigger_type"],
        "question": row["question"],
        "databaseId": row["database_id"],
        "databaseName": row["database_name"],
        "status": row["status"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "updatedAt": row["updated_at"],
        "cancellationRequestedAt": row["cancellation_requested_at"],
        "durationMs": int(row["duration_ms"]),
        "totalSteps": int(row["total_steps"]),
        "matchedSteps": int(row["matched_steps"]),
        "completedSteps": int(row["completed_steps"]),
        "skippedSteps": int(row["skipped_steps"]),
        "errorSteps": int(row["error_steps"]),
        "synthesisStatus": row["synthesis_status"],
        "error": row["error"],
        "skill": _decode(row["skill_snapshot_json"], {}),
        "metadata": _decode(row["metadata_json"], {}),
    }
    if include_result:
        item["result"] = _decode(row["result_json"], {})
    return item


def create_execution(record: Dict[str, Any]) -> Dict[str, Any]:
    now = str(record.get("startedAt") or utc_now())
    skill = record.get("skill") if isinstance(record.get("skill"), dict) else {}
    values = (
        str(record["runId"]),
        str(record.get("sessionId") or ""),
        str(record.get("batchId") or ""),
        str(record.get("scheduleId") or ""),
        str(record.get("skillId") or skill.get("id") or ""),
        str(record.get("skillName") or skill.get("name") or ""),
        int(record.get("skillRevision") or skill.get("revision") or 0),
        str(record.get("actorId") or ""),
        str(record.get("trigger") or "interactive"),
        str(record.get("question") or "")[:20000],
        str(record.get("databaseId") or ""),
        str(record.get("databaseName") or ""),
        str(record.get("status") or "running"),
        now,
        now,
        int(record.get("totalSteps") or len(skill.get("steps", []))),
        _json(skill),
        _json(record.get("metadata") or {}),
    )
    try:
        with _connection() as connection:
            connection.execute(
                """
                INSERT INTO skill_executions (
                    run_id, session_id, batch_id, schedule_id, skill_id, skill_name,
                    skill_revision, actor_id, trigger_type, question, database_id,
                    database_name, status, started_at, updated_at, total_steps,
                    skill_snapshot_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return get_execution(str(record["runId"])) or {}
    except sqlite3.IntegrityError as exc:
        raise SkillExecutionStoreError(f"Skill 运行记录已存在: {record['runId']}") from exc
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法创建 Skill 运行记录: {exc}") from exc


def record_execution_step(run_id: str, event: Dict[str, Any]) -> None:
    step = event.get("step") if isinstance(event.get("step"), dict) else event
    step_key = str(step.get("step") or step.get("stepId") or step.get("sequence") or "unknown")
    now = utc_now()
    status = str(step.get("status") or "")
    started_at = now if status == "in_progress" else None
    finished_at = now if status in {"completed", "error", "skipped", "cancelled", "timed_out"} else None
    try:
        with _connection() as connection:
            connection.execute(
                """
                INSERT INTO skill_execution_steps (
                    run_id, step_key, sequence, step_id, step_name, phase, status,
                    dataset_id, dataset_name, started_at, finished_at, updated_at,
                    duration_ms, event_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, step_key) DO UPDATE SET
                    sequence = excluded.sequence,
                    step_id = excluded.step_id,
                    step_name = excluded.step_name,
                    phase = excluded.phase,
                    status = excluded.status,
                    dataset_id = excluded.dataset_id,
                    dataset_name = excluded.dataset_name,
                    started_at = COALESCE(skill_execution_steps.started_at, excluded.started_at),
                    finished_at = COALESCE(excluded.finished_at, skill_execution_steps.finished_at),
                    updated_at = excluded.updated_at,
                    duration_ms = excluded.duration_ms,
                    event_json = excluded.event_json,
                    result_json = CASE WHEN excluded.result_json = '{}'
                                       THEN skill_execution_steps.result_json
                                       ELSE excluded.result_json END
                """,
                (
                    run_id,
                    step_key,
                    int(step.get("sequence") or 0),
                    str(step.get("stepId") or step.get("step") or ""),
                    str(step.get("stepName") or step.get("description") or ""),
                    str(step.get("phase") or ""),
                    status,
                    str(step.get("datasetId") or ""),
                    str(step.get("datasetName") or ""),
                    started_at,
                    finished_at,
                    now,
                    int(step.get("durationMs") or 0),
                    _json(event),
                    _json(event.get("stepResult") or {}),
                ),
            )
            connection.execute(
                "UPDATE skill_executions SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法保存 Skill 步骤记录: {exc}") from exc


def finish_execution(
    run_id: str,
    *,
    status: str,
    result: Dict[str, Any] | None = None,
    error: str = "",
    finished_at: str | None = None,
) -> Dict[str, Any] | None:
    now = finished_at or utc_now()
    result = result or {}
    execution = result.get("skillExecution") if isinstance(result.get("skillExecution"), dict) else {}
    query_results = result.get("queryResults") if isinstance(result.get("queryResults"), list) else []
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT started_at FROM skill_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None
            try:
                started = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
                ended = datetime.fromisoformat(now.replace("Z", "+00:00"))
                measured_duration = max(0, int((ended - started).total_seconds() * 1000))
            except (TypeError, ValueError):
                measured_duration = 0
            duration_ms = int(execution.get("durationMs") or measured_duration)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE skill_executions SET
                    status = ?, finished_at = ?, updated_at = ?, duration_ms = ?,
                    matched_steps = ?, completed_steps = ?, skipped_steps = ?, error_steps = ?,
                    synthesis_status = ?, error = ?, result_json = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    now,
                    now,
                    duration_ms,
                    int(execution.get("matchedSteps") or 0),
                    int(execution.get("completedSteps") or 0),
                    int(execution.get("skippedSteps") or 0),
                    int(execution.get("errorSteps") or 0),
                    str(execution.get("synthesisStatus") or ""),
                    str(error or execution.get("error") or "")[:1000],
                    _json(result),
                    run_id,
                ),
            )
            for item in query_results:
                sequence = int(item.get("sequence") or 0)
                step_key = f"skill-dataset-{sequence}" if sequence else str(item.get("stepId") or "result")
                connection.execute(
                    """
                    UPDATE skill_execution_steps SET result_json = ?, updated_at = ?
                    WHERE run_id = ? AND step_key = ?
                    """,
                    (_json(item), now, run_id, step_key),
                )
            connection.commit()
        return get_execution(run_id)
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法完成 Skill 运行记录: {exc}") from exc


def request_execution_cancellation(run_id: str) -> bool:
    now = utc_now()
    try:
        with _connection() as connection:
            cursor = connection.execute(
                """
                UPDATE skill_executions
                SET cancellation_requested_at = ?, updated_at = ?,
                    status = CASE WHEN status IN ('queued', 'running')
                                  THEN 'cancellation_requested' ELSE status END
                WHERE run_id = ? AND finished_at IS NULL
                """,
                (now, now, run_id),
            )
        return cursor.rowcount > 0
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法记录取消请求: {exc}") from exc


def get_execution(run_id: str) -> Dict[str, Any] | None:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_executions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None
            steps = connection.execute(
                """
                SELECT * FROM skill_execution_steps
                WHERE run_id = ? ORDER BY sequence ASC, step_key ASC
                """,
                (run_id,),
            ).fetchall()
        item = _execution_row(row)
        item["steps"] = [
            {
                "stepKey": step["step_key"],
                "sequence": int(step["sequence"]),
                "stepId": step["step_id"],
                "stepName": step["step_name"],
                "phase": step["phase"],
                "status": step["status"],
                "datasetId": step["dataset_id"],
                "datasetName": step["dataset_name"],
                "startedAt": step["started_at"],
                "finishedAt": step["finished_at"],
                "updatedAt": step["updated_at"],
                "durationMs": int(step["duration_ms"]),
                "event": _decode(step["event_json"], {}),
                "result": _decode(step["result_json"], {}),
            }
            for step in steps
        ]
        return item
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法读取 Skill 运行记录: {exc}") from exc


def list_executions(
    *,
    skill_id: str = "",
    actor_id: str = "",
    status: str = "",
    batch_id: str = "",
    schedule_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    clauses: List[str] = []
    values: List[Any] = []
    for column, value in (
        ("skill_id", skill_id),
        ("actor_id", actor_id),
        ("status", status),
        ("batch_id", batch_id),
        ("schedule_id", schedule_id),
    ):
        if value:
            clauses.append(f"{column} = ?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    try:
        with _connection() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM skill_executions{where}", values
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM skill_executions{where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        return {
            "items": [_execution_row(row, include_result=False) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法列出 Skill 运行记录: {exc}") from exc


def upsert_quality_report(report: Dict[str, Any]) -> Dict[str, Any]:
    now = utc_now()
    try:
        with _connection() as connection:
            connection.execute(
                """
                INSERT INTO skill_quality_reports (
                    report_id, run_id, skill_id, actor_id, score, grade,
                    dimensions_json, issues_json, suggestions_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    score = excluded.score,
                    grade = excluded.grade,
                    dimensions_json = excluded.dimensions_json,
                    issues_json = excluded.issues_json,
                    suggestions_json = excluded.suggestions_json,
                    actor_id = excluded.actor_id,
                    skill_id = excluded.skill_id,
                    updated_at = excluded.updated_at
                """,
                (
                    str(report["reportId"]),
                    str(report["runId"]),
                    str(report.get("skillId") or ""),
                    str(report.get("actorId") or ""),
                    float(report.get("score") or 0),
                    str(report.get("grade") or "D"),
                    _json(report.get("dimensions") or {}),
                    _json(report.get("issues") or []),
                    _json(report.get("suggestions") or []),
                    str(report.get("createdAt") or now),
                    now,
                ),
            )
        return get_quality_report(str(report["runId"])) or {}
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法保存 Skill 质量报告: {exc}") from exc


def _quality_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "reportId": row["report_id"],
        "runId": row["run_id"],
        "skillId": row["skill_id"],
        "actorId": row["actor_id"],
        "score": round(float(row["score"]), 1),
        "grade": row["grade"],
        "dimensions": _decode(row["dimensions_json"], {}),
        "issues": _decode(row["issues_json"], []),
        "suggestions": _decode(row["suggestions_json"], []),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_quality_report(run_id: str) -> Dict[str, Any] | None:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_quality_reports WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _quality_row(row) if row else None
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法读取 Skill 质量报告: {exc}") from exc


def list_quality_reports(
    *, skill_id: str = "", actor_id: str = "", limit: int = 50
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    values: List[Any] = []
    if skill_id:
        clauses.append("skill_id = ?")
        values.append(skill_id)
    if actor_id:
        clauses.append("actor_id = ?")
        values.append(actor_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    try:
        with _connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM skill_quality_reports{where} ORDER BY created_at DESC LIMIT ?",
                [*values, max(1, min(int(limit), 200))],
            ).fetchall()
        return [_quality_row(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法列出 Skill 质量报告: {exc}") from exc


def create_batch(batch: Dict[str, Any], items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    now = str(batch.get("createdAt") or utc_now())
    materialized = list(items)
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO skill_batches (
                    batch_id, name, actor_id, status, total_items, created_at,
                    updated_at, request_json
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    str(batch["batchId"]),
                    str(batch.get("name") or ""),
                    str(batch.get("actorId") or ""),
                    len(materialized),
                    now,
                    now,
                    _json(batch.get("request") or {}),
                ),
            )
            for index, item in enumerate(materialized):
                connection.execute(
                    """
                    INSERT INTO skill_batch_items (
                        batch_id, item_index, status, created_at, updated_at, request_json
                    ) VALUES (?, ?, 'queued', ?, ?, ?)
                    """,
                    (str(batch["batchId"]), index, now, now, _json(item)),
                )
            connection.commit()
        return get_batch(str(batch["batchId"])) or {}
    except sqlite3.IntegrityError as exc:
        raise SkillExecutionStoreError(f"批量任务已存在: {batch['batchId']}") from exc
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法创建批量任务: {exc}") from exc


def update_batch_item(
    batch_id: str,
    item_index: int,
    *,
    status: str,
    run_id: str = "",
    result: Dict[str, Any] | None = None,
    error: str = "",
) -> None:
    now = utc_now()
    started_at = now if status == "running" else None
    finished_at = now if status in {"completed", "partial", "error", "cancelled"} else None
    try:
        with _connection() as connection:
            connection.execute(
                """
                UPDATE skill_batch_items SET
                    status = ?, run_id = CASE WHEN ? = '' THEN run_id ELSE ? END,
                    started_at = COALESCE(started_at, ?),
                    finished_at = COALESCE(?, finished_at), updated_at = ?,
                    result_json = ?, error = ?
                WHERE batch_id = ? AND item_index = ?
                """,
                (
                    status,
                    run_id,
                    run_id,
                    started_at,
                    finished_at,
                    now,
                    _json(result or {}),
                    str(error)[:1000],
                    batch_id,
                    int(item_index),
                ),
            )
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法更新批量任务明细: {exc}") from exc


def update_batch_status(
    batch_id: str,
    status: str,
    *,
    result: Dict[str, Any] | None = None,
    cancellation_requested: bool = False,
) -> Dict[str, Any] | None:
    now = utc_now()
    started_at = now if status == "running" else None
    finished_at = now if status in {"completed", "partial", "error", "cancelled"} else None
    try:
        with _connection() as connection:
            counts = {
                row["status"]: int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM skill_batch_items WHERE batch_id = ? GROUP BY status",
                    (batch_id,),
                ).fetchall()
            }
            connection.execute(
                """
                UPDATE skill_batches SET status = ?,
                    started_at = COALESCE(started_at, ?),
                    finished_at = COALESCE(?, finished_at), updated_at = ?,
                    cancellation_requested_at = CASE WHEN ? THEN ? ELSE cancellation_requested_at END,
                    completed_items = ?, failed_items = ?, cancelled_items = ?, result_json = ?
                WHERE batch_id = ?
                """,
                (
                    status,
                    started_at,
                    finished_at,
                    now,
                    1 if cancellation_requested else 0,
                    now,
                    counts.get("completed", 0) + counts.get("partial", 0),
                    counts.get("error", 0),
                    counts.get("cancelled", 0),
                    _json(result or {}),
                    batch_id,
                ),
            )
        return get_batch(batch_id)
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法更新批量任务: {exc}") from exc


def get_batch(batch_id: str) -> Dict[str, Any] | None:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if not row:
                return None
            items = connection.execute(
                "SELECT * FROM skill_batch_items WHERE batch_id = ? ORDER BY item_index",
                (batch_id,),
            ).fetchall()
        return {
            "batchId": row["batch_id"],
            "name": row["name"],
            "actorId": row["actor_id"],
            "status": row["status"],
            "totalItems": int(row["total_items"]),
            "completedItems": int(row["completed_items"]),
            "failedItems": int(row["failed_items"]),
            "cancelledItems": int(row["cancelled_items"]),
            "createdAt": row["created_at"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "updatedAt": row["updated_at"],
            "cancellationRequestedAt": row["cancellation_requested_at"],
            "request": _decode(row["request_json"], {}),
            "result": _decode(row["result_json"], {}),
            "items": [
                {
                    "index": int(item["item_index"]),
                    "runId": item["run_id"],
                    "status": item["status"],
                    "createdAt": item["created_at"],
                    "startedAt": item["started_at"],
                    "finishedAt": item["finished_at"],
                    "updatedAt": item["updated_at"],
                    "request": _decode(item["request_json"], {}),
                    "result": _decode(item["result_json"], {}),
                    "error": item["error"],
                }
                for item in items
            ],
        }
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法读取批量任务: {exc}") from exc


def list_batches(*, actor_id: str = "", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    where = " WHERE actor_id = ?" if actor_id else ""
    values: List[Any] = [actor_id] if actor_id else []
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    try:
        with _connection() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM skill_batches{where}", values
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT batch_id FROM skill_batches{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        return {
            "items": [get_batch(row["batch_id"]) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法列出批量任务: {exc}") from exc


def create_schedule(record: Dict[str, Any]) -> Dict[str, Any]:
    now = str(record.get("createdAt") or utc_now())
    try:
        with _connection() as connection:
            connection.execute(
                """
                INSERT INTO skill_schedules (
                    schedule_id, name, skill_id, question, database_id, database_name,
                    cron_expression, timezone_name, enabled, created_by, created_at,
                    updated_at, next_run_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["scheduleId"]),
                    str(record.get("name") or ""),
                    str(record.get("skillId") or ""),
                    str(record.get("question") or "")[:20000],
                    str(record.get("databaseId") or ""),
                    str(record.get("databaseName") or ""),
                    str(record.get("cron") or ""),
                    str(record.get("timezone") or "UTC"),
                    1 if record.get("enabled", True) else 0,
                    str(record.get("createdBy") or ""),
                    now,
                    now,
                    str(record["nextRunAt"]),
                    _json(record.get("payload") or {}),
                ),
            )
        return get_schedule(str(record["scheduleId"])) or {}
    except sqlite3.IntegrityError as exc:
        raise SkillExecutionStoreError(f"定时任务已存在: {record['scheduleId']}") from exc
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法创建定时任务: {exc}") from exc


def update_schedule_record(schedule_id: str, changes: Dict[str, Any]) -> Dict[str, Any] | None:
    allowed = {
        "name": "name",
        "skillId": "skill_id",
        "question": "question",
        "databaseId": "database_id",
        "databaseName": "database_name",
        "cron": "cron_expression",
        "timezone": "timezone_name",
        "enabled": "enabled",
        "nextRunAt": "next_run_at",
        "lastRunAt": "last_run_at",
        "lastRunId": "last_run_id",
        "lastStatus": "last_status",
        "leaseUntil": "lease_until",
        "payload": "payload_json",
    }
    assignments = []
    values: List[Any] = []
    for key, column in allowed.items():
        if key not in changes:
            continue
        value = changes[key]
        if key == "enabled":
            value = 1 if value else 0
        elif key == "payload":
            value = _json(value or {})
        assignments.append(f"{column} = ?")
        values.append(value)
    if not assignments:
        return get_schedule(schedule_id)
    assignments.append("updated_at = ?")
    values.append(utc_now())
    values.append(schedule_id)
    try:
        with _connection() as connection:
            connection.execute(
                f"UPDATE skill_schedules SET {', '.join(assignments)} WHERE schedule_id = ?",
                values,
            )
        return get_schedule(schedule_id)
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法更新定时任务: {exc}") from exc


def _schedule_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "scheduleId": row["schedule_id"],
        "name": row["name"],
        "skillId": row["skill_id"],
        "question": row["question"],
        "databaseId": row["database_id"],
        "databaseName": row["database_name"],
        "cron": row["cron_expression"],
        "timezone": row["timezone_name"],
        "enabled": bool(row["enabled"]),
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "nextRunAt": row["next_run_at"],
        "lastRunAt": row["last_run_at"],
        "lastRunId": row["last_run_id"],
        "lastStatus": row["last_status"],
        "leaseUntil": row["lease_until"],
        "payload": _decode(row["payload_json"], {}),
    }


def get_schedule(schedule_id: str) -> Dict[str, Any] | None:
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT * FROM skill_schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
        return _schedule_row(row) if row else None
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法读取定时任务: {exc}") from exc


def list_schedules(
    *, created_by: str = "", enabled: bool | None = None, limit: int = 100, offset: int = 0
) -> Dict[str, Any]:
    clauses: List[str] = []
    values: List[Any] = []
    if created_by:
        clauses.append("created_by = ?")
        values.append(created_by)
    if enabled is not None:
        clauses.append("enabled = ?")
        values.append(1 if enabled else 0)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    try:
        with _connection() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM skill_schedules{where}", values
            ).fetchone()[0])
            rows = connection.execute(
                f"SELECT * FROM skill_schedules{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        return {
            "items": [_schedule_row(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法列出定时任务: {exc}") from exc


def delete_schedule_record(schedule_id: str) -> bool:
    try:
        with _connection() as connection:
            cursor = connection.execute(
                "DELETE FROM skill_schedules WHERE schedule_id = ?", (schedule_id,)
            )
        return cursor.rowcount > 0
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法删除定时任务: {exc}") from exc


def claim_due_schedules(now: str, lease_until: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    try:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM skill_schedules
                WHERE enabled = 1 AND next_run_at <= ?
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY next_run_at ASC LIMIT ?
                """,
                (now, now, limit),
            ).fetchall()
            ids = [row["schedule_id"] for row in rows]
            for schedule_id in ids:
                connection.execute(
                    "UPDATE skill_schedules SET lease_until = ?, updated_at = ? WHERE schedule_id = ?",
                    (lease_until, now, schedule_id),
                )
            connection.commit()
        return [_schedule_row(row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise SkillExecutionStoreError(f"无法领取到期定时任务: {exc}") from exc
