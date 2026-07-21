"""Framework-neutral batch, comparison and polling scheduler services."""

from __future__ import annotations

import asyncio
import inspect
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.9+ is required by the service
    ZoneInfo = None
    ZoneInfoNotFoundError = KeyError

from .skill_execution_store import (
    claim_due_schedules as _claim_due_schedule_records,
    create_batch,
    create_schedule as _create_schedule_record,
    delete_schedule_record,
    get_batch,
    get_execution,
    get_schedule,
    list_batches,
    list_schedules,
    update_batch_item,
    update_batch_status,
    update_schedule_record,
)
from .skill_runner import cancel_skill_run, run_skill_workflow


_ACTIVE_BATCHES: Dict[str, threading.Event] = {}
_ACTIVE_BATCHES_LOCK = threading.RLock()
_MAX_BATCH_ITEMS = 100


def _utc_datetime(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timezone_for(name: str):
    normalized = (name or "UTC").strip()
    if normalized.upper() in {"UTC", "ETC/UTC", "Z"}:
        return timezone.utc
    # Windows installations without the optional tzdata wheel commonly lack
    # IANA files.  The product's default zone has no DST, so it is safe to keep
    # this explicit fallback while rejecting unknown names.
    if normalized in {"Asia/Shanghai", "PRC", "China Standard Time"}:
        return timezone(timedelta(hours=8), name="Asia/Shanghai")
    if normalized.startswith(("UTC+", "UTC-")):
        sign = 1 if normalized[3] == "+" else -1
        parts = normalized[4:].split(":", 1)
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) == 2 else 0
        if hours > 14 or minutes > 59:
            raise ValueError(f"无效时区偏移: {name}")
        return timezone(sign * timedelta(hours=hours, minutes=minutes), name=normalized)
    if ZoneInfo is not None:
        try:
            return ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    raise ValueError(f"不支持的时区: {name}")


def _cron_values(expression: str, minimum: int, maximum: int, *, weekday: bool = False) -> set[int]:
    values: set[int] = set()
    for raw_part in expression.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("Cron 字段包含空项")
        base, separator, raw_step = part.partition("/")
        step = int(raw_step) if separator else 1
        if step <= 0:
            raise ValueError("Cron 步长必须大于 0")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            start, end = int(raw_start), int(raw_end)
        else:
            start = end = int(base)
        if weekday and start == 7:
            start = 0
        if weekday and end == 7:
            end = 0
        if start < minimum or start > maximum or end < minimum or end > maximum:
            raise ValueError(f"Cron 字段值超出范围 {minimum}-{maximum}: {part}")
        if end < start:
            raise ValueError(f"Cron 范围起点大于终点: {part}")
        values.update(range(start, end + 1, step))
    return values


def validate_cron_expression(expression: str) -> Dict[str, set[int]]:
    """Validate the supported standard five-field cron grammar."""
    fields = str(expression or "").split()
    if len(fields) != 5:
        raise ValueError("Cron 必须包含 5 个字段：分 时 日 月 周")
    minute, hour, day, month, weekday = fields
    return {
        "minute": _cron_values(minute, 0, 59),
        "hour": _cron_values(hour, 0, 23),
        "day": _cron_values(day, 1, 31),
        "month": _cron_values(month, 1, 12),
        "weekday": _cron_values(weekday, 0, 6, weekday=True),
        "dayWildcard": {1} if day == "*" else set(),
        "weekdayWildcard": {1} if weekday == "*" else set(),
    }


def next_cron_time(
    expression: str,
    timezone_name: str = "UTC",
    *,
    after: datetime | str | None = None,
) -> str:
    """Return the next UTC instant for a five-field cron expression."""
    parsed = validate_cron_expression(expression)
    target_zone = _timezone_for(timezone_name)
    candidate = _utc_datetime(after).astimezone(target_zone)
    candidate = candidate.replace(second=0, microsecond=0) + timedelta(minutes=1)
    day_wildcard = bool(parsed["dayWildcard"])
    weekday_wildcard = bool(parsed["weekdayWildcard"])
    # 370 days covers leap-year boundaries plus a small timezone margin.  A
    # yearly expression (for example 0 0 1 1 *) remains supported.
    for _ in range(370 * 24 * 60):
        cron_weekday = (candidate.weekday() + 1) % 7
        day_match = candidate.day in parsed["day"]
        weekday_match = cron_weekday in parsed["weekday"]
        if day_wildcard:
            calendar_match = weekday_match
        elif weekday_wildcard:
            calendar_match = day_match
        else:
            # Standard cron treats restricted day-of-month and day-of-week as OR.
            calendar_match = day_match or weekday_match
        if (
            candidate.minute in parsed["minute"]
            and candidate.hour in parsed["hour"]
            and candidate.month in parsed["month"]
            and calendar_match
        ):
            return _iso_utc(candidate)
        candidate += timedelta(minutes=1)
    raise ValueError("Cron 在未来 370 天内没有可执行时间")


async def _resolve_skill(skill_resolver: Callable[[str], Any], skill_id: str) -> Dict[str, Any] | None:
    skill = skill_resolver(skill_id)
    if inspect.isawaitable(skill):
        skill = await skill
    return skill if isinstance(skill, dict) else None


def _batch_item_summary(result: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    execution = result.get("skillExecution") if isinstance(result.get("skillExecution"), dict) else {}
    return {
        "runId": run_id,
        "status": execution.get("overallStatus", "error"),
        "finalAnswer": str(result.get("final_answer") or "")[:10000],
        "skillExecution": execution,
    }


async def run_skill_batch(
    *,
    items: Iterable[Dict[str, Any]],
    skill_resolver: Callable[[str], Any],
    llm_call_fn,
    actor_id: str = "",
    name: str = "",
    batch_id: str | None = None,
    max_concurrency: int = 2,
) -> Dict[str, Any]:
    """Persist and execute a bounded set of independent Skill evaluations."""
    batch_items = [dict(item) for item in items]
    if not batch_items:
        raise ValueError("批量评估至少需要 1 个任务")
    if len(batch_items) > _MAX_BATCH_ITEMS:
        raise ValueError(f"单次批量评估最多 {_MAX_BATCH_ITEMS} 个任务")
    effective_batch_id = str(batch_id or uuid.uuid4())
    max_concurrency = max(1, min(int(max_concurrency), 8))
    create_batch(
        {
            "batchId": effective_batch_id,
            "name": name or f"批量评估-{effective_batch_id[:8]}",
            "actorId": actor_id,
            "request": {"maxConcurrency": max_concurrency},
        },
        batch_items,
    )
    cancel_event = threading.Event()
    with _ACTIVE_BATCHES_LOCK:
        _ACTIVE_BATCHES[effective_batch_id] = cancel_event
    update_batch_status(effective_batch_id, "running")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def execute_item(index: int, item: Dict[str, Any]) -> None:
        async with semaphore:
            if cancel_event.is_set():
                update_batch_item(effective_batch_id, index, status="cancelled", error="批量任务已取消")
                return
            run_id = str(uuid.uuid4())
            update_batch_item(effective_batch_id, index, status="running", run_id=run_id)
            try:
                skill_id = str(item.get("skillId") or "")
                skill = await _resolve_skill(skill_resolver, skill_id)
                if not skill:
                    raise ValueError(f"Skill 不存在: {skill_id}")
                final_result: Dict[str, Any] = {}
                async for event in run_skill_workflow(
                    question=str(item.get("query") or item.get("question") or ""),
                    database_id=str(item.get("dataSourceId") or item.get("databaseId") or ""),
                    database_name=str(item.get("databaseName") or ""),
                    skill=skill,
                    llm_call_fn=llm_call_fn,
                    session_id=str(item.get("sessionId") or ""),
                    attachment_text=str(item.get("attachmentText") or ""),
                    run_id=run_id,
                    actor_id=actor_id,
                    trigger="batch",
                    batch_id=effective_batch_id,
                ):
                    if event.get("type") == "result" and isinstance(event.get("result"), dict):
                        final_result = event["result"]
                summary = _batch_item_summary(final_result, run_id)
                status = str(summary["status"])
                update_batch_item(
                    effective_batch_id,
                    index,
                    status=status if status in {"completed", "partial", "error", "cancelled"} else "error",
                    run_id=run_id,
                    result=summary,
                )
            except asyncio.CancelledError:
                cancel_skill_run(run_id, actor_id)
                update_batch_item(effective_batch_id, index, status="cancelled", run_id=run_id)
                raise
            except Exception as exc:
                update_batch_item(
                    effective_batch_id,
                    index,
                    status="error",
                    run_id=run_id,
                    error=str(exc)[:1000],
                )

    try:
        await asyncio.gather(*(execute_item(index, item) for index, item in enumerate(batch_items)))
        batch = get_batch(effective_batch_id) or {}
        statuses = [item.get("status") for item in batch.get("items", [])]
        if statuses and all(status == "completed" for status in statuses):
            final_status = "completed"
        elif statuses and all(status == "cancelled" for status in statuses):
            final_status = "cancelled"
        elif any(status in {"completed", "partial"} for status in statuses):
            final_status = "partial"
        elif cancel_event.is_set():
            final_status = "cancelled"
        else:
            final_status = "error"
        result = {
            "batchId": effective_batch_id,
            "status": final_status,
            "runIds": [item.get("runId") for item in batch.get("items", []) if item.get("runId")],
        }
        return update_batch_status(effective_batch_id, final_status, result=result) or result
    finally:
        with _ACTIVE_BATCHES_LOCK:
            _ACTIVE_BATCHES.pop(effective_batch_id, None)


def cancel_skill_batch(batch_id: str, requested_by: str = "") -> Dict[str, Any]:
    with _ACTIVE_BATCHES_LOCK:
        event = _ACTIVE_BATCHES.get(batch_id)
        if event:
            event.set()
    batch = get_batch(batch_id)
    if not batch:
        return {"batchId": batch_id, "status": "not_found", "accepted": False}
    if batch.get("finishedAt"):
        return {"batchId": batch_id, "status": "already_finished", "accepted": False}
    for item in batch.get("items", []):
        if item.get("status") == "running" and item.get("runId"):
            cancel_skill_run(item["runId"], requested_by)
    update_batch_status(batch_id, "cancellation_requested", cancellation_requested=True)
    return {
        "batchId": batch_id,
        "status": "cancellation_requested",
        "accepted": True,
        "requestedBy": requested_by,
    }


def get_skill_batch(batch_id: str) -> Dict[str, Any] | None:
    return get_batch(batch_id)


def list_skill_batches(**filters) -> Dict[str, Any]:
    return list_batches(**filters)


def _comparison_row(execution: Dict[str, Any]) -> Dict[str, Any]:
    result = execution.get("result") if isinstance(execution.get("result"), dict) else {}
    metrics = result.get("skillExecution") if isinstance(result.get("skillExecution"), dict) else {}
    total = int(metrics.get("totalSteps") or execution.get("totalSteps") or 0)
    completed = int(metrics.get("completedSteps") or execution.get("completedSteps") or 0)
    return {
        "runId": execution.get("runId", ""),
        "status": execution.get("status", ""),
        "skillId": execution.get("skillId", ""),
        "skillName": execution.get("skillName", ""),
        "databaseId": execution.get("databaseId", ""),
        "databaseName": execution.get("databaseName", ""),
        "trigger": execution.get("trigger", ""),
        "startedAt": execution.get("startedAt"),
        "durationMs": int(execution.get("durationMs") or 0),
        "totalSteps": total,
        "completedSteps": completed,
        "skippedSteps": int(metrics.get("skippedSteps") or execution.get("skippedSteps") or 0),
        "errorSteps": int(metrics.get("errorSteps") or execution.get("errorSteps") or 0),
        "completionRate": round(completed / total, 4) if total else 0,
        "finalAnswer": str(result.get("final_answer") or ""),
    }


def compare_skill_executions(
    run_ids: Iterable[str], *, baseline_run_id: str | None = None
) -> Dict[str, Any]:
    ids = list(dict.fromkeys(str(run_id) for run_id in run_ids if str(run_id)))
    if len(ids) < 2:
        raise ValueError("结果对比至少需要 2 条执行记录")
    if len(ids) > 20:
        raise ValueError("一次最多对比 20 条执行记录")
    executions = [get_execution(run_id) for run_id in ids]
    missing = [ids[index] for index, item in enumerate(executions) if not item]
    if missing:
        raise ValueError("执行记录不存在: " + "、".join(missing))
    rows = [_comparison_row(item or {}) for item in executions]
    baseline_id = str(baseline_run_id or ids[0])
    baseline = next((row for row in rows if row["runId"] == baseline_id), None)
    if not baseline:
        raise ValueError(f"基准执行不在对比集合中: {baseline_id}")

    baseline_execution = next(item for item in executions if item and item["runId"] == baseline_id)
    baseline_result = baseline_execution.get("result", {})
    baseline_steps = {
        str(item.get("stepId") or item.get("sequence")): item
        for item in baseline_result.get("queryResults", [])
    }
    differences = []
    for row, execution in zip(rows, executions):
        if row["runId"] == baseline_id:
            continue
        result = (execution or {}).get("result", {})
        current_steps = {
            str(item.get("stepId") or item.get("sequence")): item
            for item in result.get("queryResults", [])
        }
        step_differences = []
        for step_key in sorted(set(baseline_steps) | set(current_steps)):
            before = baseline_steps.get(step_key, {})
            after = current_steps.get(step_key, {})
            step_differences.append({
                "stepKey": step_key,
                "stepName": after.get("stepName") or before.get("stepName") or "",
                "baselineStatus": before.get("status", "missing"),
                "status": after.get("status", "missing"),
                "totalRowsDelta": int(after.get("totalRows") or 0) - int(before.get("totalRows") or 0),
                "durationDeltaMs": int(after.get("durationMs") or 0) - int(before.get("durationMs") or 0),
                "sqlChanged": str(after.get("sql") or "") != str(before.get("sql") or ""),
            })
        differences.append({
            "runId": row["runId"],
            "againstRunId": baseline_id,
            "statusChanged": row["status"] != baseline["status"],
            "durationDeltaMs": row["durationMs"] - baseline["durationMs"],
            "completedStepsDelta": row["completedSteps"] - baseline["completedSteps"],
            "errorStepsDelta": row["errorSteps"] - baseline["errorSteps"],
            "completionRateDelta": round(row["completionRate"] - baseline["completionRate"], 4),
            "answerChanged": row["finalAnswer"] != baseline["finalAnswer"],
            "stepDifferences": step_differences,
        })
    metric_names = ["durationMs", "completedSteps", "skippedSteps", "errorSteps", "completionRate"]
    return {
        "runIds": ids,
        "baselineRunId": baseline_id,
        "metrics": metric_names,
        "rows": rows,
        "differences": differences,
    }


def create_skill_schedule(payload: Dict[str, Any], *, created_by: str = "") -> Dict[str, Any]:
    required = ("skillId", "question", "databaseId", "cron")
    missing = [key for key in required if not str(payload.get(key) or "").strip()]
    if missing:
        raise ValueError("定时任务缺少必填字段: " + "、".join(missing))
    timezone_name = str(payload.get("timezone") or "Asia/Shanghai")
    cron = str(payload["cron"])
    now = _utc_datetime()
    schedule_id = str(payload.get("scheduleId") or uuid.uuid4())
    known = {
        "scheduleId", "name", "skillId", "question", "databaseId", "databaseName",
        "cron", "timezone", "enabled", "createdBy", "nextRunAt",
    }
    extra = {key: value for key, value in payload.items() if key not in known}
    return _create_schedule_record({
        "scheduleId": schedule_id,
        "name": str(payload.get("name") or f"定时评估-{schedule_id[:8]}"),
        "skillId": str(payload["skillId"]),
        "question": str(payload["question"]),
        "databaseId": str(payload["databaseId"]),
        "databaseName": str(payload.get("databaseName") or ""),
        "cron": cron,
        "timezone": timezone_name,
        "enabled": bool(payload.get("enabled", True)),
        "createdBy": created_by or str(payload.get("createdBy") or ""),
        "nextRunAt": str(payload.get("nextRunAt") or next_cron_time(cron, timezone_name, after=now)),
        "payload": extra,
    })


def update_skill_schedule(schedule_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    current = get_schedule(schedule_id)
    if not current:
        raise ValueError(f"定时任务不存在: {schedule_id}")
    merged = {**current, **changes}
    for key in ("skillId", "question", "databaseId", "cron"):
        if not str(merged.get(key) or "").strip():
            raise ValueError(f"定时任务字段不能为空: {key}")
    validate_cron_expression(str(merged["cron"]))
    _timezone_for(str(merged.get("timezone") or "UTC"))
    updates = dict(changes)
    if "cron" in changes or "timezone" in changes or (changes.get("enabled") and not current["enabled"]):
        updates["nextRunAt"] = next_cron_time(
            str(merged["cron"]), str(merged.get("timezone") or "UTC")
        )
    if "payload" in changes:
        updates["payload"] = changes["payload"]
    updated = update_schedule_record(schedule_id, updates)
    if not updated:
        raise ValueError(f"定时任务不存在: {schedule_id}")
    return updated


def get_skill_schedule(schedule_id: str) -> Dict[str, Any] | None:
    return get_schedule(schedule_id)


def list_skill_schedules(**filters) -> Dict[str, Any]:
    return list_schedules(**filters)


def delete_skill_schedule(schedule_id: str) -> bool:
    return delete_schedule_record(schedule_id)


def claim_due_skill_schedules(
    *, now: datetime | str | None = None, limit: int = 10, lease_seconds: int = 300
) -> List[Dict[str, Any]]:
    current = _utc_datetime(now)
    return _claim_due_schedule_records(
        _iso_utc(current),
        _iso_utc(current + timedelta(seconds=max(30, int(lease_seconds)))),
        limit=limit,
    )


async def poll_and_run_due_schedules(
    *,
    skill_resolver: Callable[[str], Any],
    llm_call_fn,
    now: datetime | str | None = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Claim due schedules once and execute them; safe for repeated polling."""
    claimed = claim_due_skill_schedules(now=now, limit=limit)
    outcomes = []
    for schedule in claimed:
        run_id = str(uuid.uuid4())
        status = "error"
        error = ""
        try:
            skill = await _resolve_skill(skill_resolver, schedule["skillId"])
            if not skill:
                raise ValueError(f"Skill 不存在: {schedule['skillId']}")
            final_result: Dict[str, Any] = {}
            async for event in run_skill_workflow(
                question=schedule["question"],
                database_id=schedule["databaseId"],
                database_name=schedule.get("databaseName", ""),
                skill=skill,
                llm_call_fn=llm_call_fn,
                run_id=run_id,
                actor_id=schedule.get("createdBy", ""),
                trigger="schedule",
                schedule_id=schedule["scheduleId"],
            ):
                if event.get("type") == "result" and isinstance(event.get("result"), dict):
                    final_result = event["result"]
            status = str(final_result.get("skillExecution", {}).get("overallStatus") or "error")
        except Exception as exc:
            error = str(exc)[:1000]
        executed_at = _utc_datetime()
        try:
            next_run_at = next_cron_time(
                schedule["cron"], schedule.get("timezone", "UTC"), after=executed_at
            )
        except ValueError:
            next_run_at = schedule["nextRunAt"]
        update_schedule_record(schedule["scheduleId"], {
            "lastRunAt": _iso_utc(executed_at),
            "lastRunId": run_id,
            "lastStatus": status,
            "nextRunAt": next_run_at,
            "leaseUntil": None,
        })
        outcomes.append({
            "scheduleId": schedule["scheduleId"],
            "runId": run_id,
            "status": status,
            "error": error,
            "nextRunAt": next_run_at,
        })
    return outcomes
