from __future__ import annotations

from datetime import datetime
from typing import Any


JOB_STATUSES = {"idle", "running", "waiting_approval", "completed", "failed", "interrupted"}


class JobStateError(ValueError):
    """Raised when a persisted job cannot make the requested transition."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def idle_job() -> dict[str, Any]:
    return {
        "job_id": "",
        "status": "idle",
        "attempt": 0,
        "user_message": "",
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "current_step": 0,
        "last_action": "",
        "user_message_persisted": False,
        "error": "",
    }


def new_job(user_message: str, *, job_id: str, now: str | None = None) -> dict[str, Any]:
    message = str(user_message).strip()
    if not message:
        raise JobStateError("a job needs a user message")
    if not str(job_id).strip():
        raise JobStateError("a job needs an id")
    timestamp = now or _now()
    return {
        "job_id": str(job_id),
        "status": "running",
        "attempt": 1,
        "user_message": message,
        "started_at": timestamp,
        "updated_at": timestamp,
        "finished_at": None,
        "current_step": 0,
        "last_action": "started",
        "user_message_persisted": False,
        "error": "",
    }


def normalize_job(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return idle_job()
    status = value.get("status")
    job_id = value.get("job_id")
    message = value.get("user_message")
    try:
        attempt = int(value.get("attempt", 0))
        current_step = int(value.get("current_step", 0))
    except (TypeError, ValueError):
        return idle_job()
    if status not in JOB_STATUSES or attempt < 0 or current_step < 0:
        return idle_job()
    if status != "idle" and (not isinstance(job_id, str) or not job_id.strip() or not isinstance(message, str) or not message.strip()):
        return idle_job()
    return {
        "job_id": str(job_id or ""),
        "status": status,
        "attempt": attempt,
        "user_message": str(message or ""),
        "started_at": value.get("started_at") if isinstance(value.get("started_at"), str) else None,
        "updated_at": value.get("updated_at") if isinstance(value.get("updated_at"), str) else None,
        "finished_at": value.get("finished_at") if isinstance(value.get("finished_at"), str) else None,
        "current_step": current_step,
        "last_action": str(value.get("last_action") or ""),
        "user_message_persisted": bool(value.get("user_message_persisted", False)),
        "error": str(value.get("error") or ""),
    }


def mark_interrupted(job: dict[str, Any], *, now: str | None = None, reason: str = "") -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "running":
        return current
    timestamp = now or _now()
    current.update({
        "status": "interrupted",
        "updated_at": timestamp,
        "finished_at": timestamp,
        "last_action": "interrupted",
        "error": str(reason or "The worker stopped before the turn finished."),
    })
    return current


def mark_user_message_persisted(job: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "running":
        raise JobStateError(f"cannot persist a user message for a {current['status']} job")
    current.update({"user_message_persisted": True, "updated_at": now or _now()})
    return current


def start_attempt(job: dict[str, Any], *, job_id: str, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] not in {"interrupted", "failed"}:
        raise JobStateError(f"cannot retry a {current['status']} job")
    if not str(job_id).strip():
        raise JobStateError("a retry needs an id")
    timestamp = now or _now()
    current.update({
        "job_id": str(job_id),
        "status": "running",
        "attempt": current["attempt"] + 1,
        "started_at": timestamp,
        "updated_at": timestamp,
        "finished_at": None,
        "error": "",
    })
    return current


def update_progress(job: dict[str, Any], *, step: int, action: str, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "running":
        raise JobStateError(f"cannot update a {current['status']} job")
    if int(step) < 0 or not str(action).strip():
        raise JobStateError("job progress needs a non-negative step and action")
    current.update({
        "updated_at": now or _now(),
        "current_step": int(step),
        "last_action": str(action),
    })
    return current


def mark_waiting_approval(job: dict[str, Any], *, step: int, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "running":
        raise JobStateError(f"cannot await approval for a {current['status']} job")
    if int(step) < 0:
        raise JobStateError("approval step must be non-negative")
    current.update({
        "status": "waiting_approval",
        "updated_at": now or _now(),
        "current_step": int(step),
        "last_action": "approval_requested",
    })
    return current


def resume_approval(job: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "waiting_approval":
        raise JobStateError(f"cannot resume approval for a {current['status']} job")
    current.update({
        "status": "running",
        "updated_at": now or _now(),
        "finished_at": None,
        "last_action": "approval_resolved",
        "error": "",
    })
    return current


def complete_job(job: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "running":
        raise JobStateError(f"cannot complete a {current['status']} job")
    timestamp = now or _now()
    current.update({"status": "completed", "updated_at": timestamp, "finished_at": timestamp, "error": ""})
    return current


def fail_job(job: dict[str, Any], error: str, *, now: str | None = None) -> dict[str, Any]:
    current = normalize_job(job)
    if current["status"] != "running":
        raise JobStateError(f"cannot fail a {current['status']} job")
    timestamp = now or _now()
    current.update({"status": "failed", "updated_at": timestamp, "finished_at": timestamp, "error": str(error)})
    return current

