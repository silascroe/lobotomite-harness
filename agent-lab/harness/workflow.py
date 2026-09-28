"""Small, durable workflow state for Agent Lab runs and sessions.

This module is intentionally independent from the model client, HTTP server,
and UI. It records operational state and evidence, not hidden model reasoning.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persistence import atomic_write_json


PHASES = (
    "intake",
    "inspect",
    "design",
    "plan",
    "implement",
    "verify",
    "review",
    "complete",
    "blocked",
)
PHASE_ORDER = {phase: index for index, phase in enumerate(PHASES[:-2])}
ACTIVE_STATUSES = {"active", "complete", "blocked"}
ARTIFACT_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class WorkflowError(Exception):
    """An expected workflow validation error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_text(value: Any, name: str, *, required: bool = True, limit: int = 500) -> str:
    if not isinstance(value, str):
        if required:
            raise WorkflowError(f"{name} must be a string")
        return ""
    result = value.strip()
    if required and not result:
        raise WorkflowError(f"{name} is required")
    if len(result) > limit:
        raise WorkflowError(f"{name} is too long")
    return result


def validate_phase(value: Any) -> str:
    phase = _validate_text(value, "phase").lower()
    if phase not in PHASES:
        raise WorkflowError("phase must be one of: " + ", ".join(PHASES))
    return phase


def validate_artifacts(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise WorkflowError("artifacts must be a list of relative paths")
    result: list[str] = []
    for value in values:
        path = _validate_text(value, "artifact path", limit=240).replace("\\", "/")
        if (
            not path
            or path.startswith("/")
            or re.match(r"^[A-Za-z]:", path)
            or path.startswith("../")
            or "/../" in path
            or path == ".."
            or "//" in path
            or not ARTIFACT_RE.fullmatch(path)
        ):
            raise WorkflowError("artifact paths must be relative project paths")
        if path not in result:
            result.append(path)
    return result


def _status_for_phase(phase: str) -> str:
    if phase == "complete":
        return "complete"
    if phase == "blocked":
        return "blocked"
    return "active"


def new_workflow() -> dict[str, Any]:
    return {
        "phase": "intake",
        "status": "active",
        "summary": "Request received.",
        "next_action": "Understand the request and inspect the project.",
        "artifacts": [],
        "checkpoint_count": 0,
        "updated_at": _now(),
    }


def _normalize_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowError("workflow snapshot must be an object")
    phase = validate_phase(value.get("phase"))
    status = _validate_text(value.get("status"), "status").lower()
    if status not in ACTIVE_STATUSES or status != _status_for_phase(phase):
        raise WorkflowError("workflow status does not match phase")
    summary = _validate_text(value.get("summary"), "summary")
    next_action = _validate_text(value.get("next_action"), "next_action")
    artifacts = validate_artifacts(value.get("artifacts", []))
    try:
        checkpoint_count = int(value.get("checkpoint_count", 0))
    except (TypeError, ValueError) as exc:
        raise WorkflowError("checkpoint_count must be an integer") from exc
    if checkpoint_count < 0:
        raise WorkflowError("checkpoint_count cannot be negative")
    updated_at = _validate_text(value.get("updated_at"), "updated_at")
    return {
        "phase": phase,
        "status": status,
        "summary": summary,
        "next_action": next_action,
        "artifacts": artifacts,
        "checkpoint_count": checkpoint_count,
        "updated_at": updated_at,
    }


def _can_transition(current: str, target: str) -> bool:
    if current == target:
        return True
    if target == "blocked":
        return current != "complete"
    if current == "blocked":
        return target == "intake"
    if current == "complete":
        return target == "intake"
    if target == "complete":
        return True
    if current == "verify" and target == "implement":
        return True
    if current == "review" and target == "implement":
        return True
    return PHASE_ORDER[target] > PHASE_ORDER[current]


def transition(
    state: dict[str, Any],
    phase: str,
    summary: str,
    next_action: str,
    *,
    artifacts: Any = None,
) -> dict[str, Any]:
    current = _normalize_snapshot(state)
    target = validate_phase(phase)
    summary_text = _validate_text(summary, "summary")
    next_text = _validate_text(next_action, "next_action")
    additions = validate_artifacts(artifacts)
    if not _can_transition(current["phase"], target):
        raise WorkflowError(f"cannot transition from {current['phase']} to {target}")
    merged_artifacts = list(current["artifacts"])
    for artifact in additions:
        if artifact not in merged_artifacts:
            merged_artifacts.append(artifact)
    return {
        "phase": target,
        "status": _status_for_phase(target),
        "summary": summary_text,
        "next_action": next_text,
        "artifacts": merged_artifacts,
        "checkpoint_count": current["checkpoint_count"] + 1,
        "updated_at": _now(),
    }


def _automatic_target(state: dict[str, Any], action: str, result: dict[str, Any]) -> tuple[str, str, str] | None:
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    current = state["phase"]
    if action in {"list_files", "read_file"} and current == "intake":
        return "inspect", "The project has been inspected.", "Clarify the design or plan the smallest useful change."
    if action in {"write_file", "apply_patch"} and current not in {"complete", "blocked"}:
        if current in {"intake", "inspect", "design", "plan", "verify", "review"}:
            return "implement", "A project change has been written.", "Run a focused validation command."
    if action == "run_command" and result.get("exit_code") == 0 and current in {"intake", "inspect", "design", "plan", "implement"}:
        return "verify", "A validation command completed successfully.", "Inspect the result and review the changed files."
    if action == "git_diff" and current in {"intake", "inspect", "design", "plan", "implement", "verify"}:
        return "review", "The current project diff is available for review.", "Review the changes and finish honestly."
    if action == "finish":
        requested = str(result.get("status", "")).strip().lower()
        if requested == "success":
            return "complete", "The run reported a successful completion.", "Wait for the next request."
        if requested == "blocked":
            return "blocked", "The run reported a concrete blocker.", "Resolve the blocker and start the workflow again."
    return None


def observe_tool(state: dict[str, Any], action: str, result: dict[str, Any]) -> dict[str, Any]:
    current = _normalize_snapshot(state)
    target = _automatic_target(current, str(action), result)
    if target is None:
        return current
    phase, summary, next_action = target
    try:
        return transition(current, phase, summary, next_action)
    except WorkflowError:
        return current


def save_workflow(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_snapshot(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, normalized)
    return normalized


def load_workflow(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return new_workflow()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_snapshot(value)
    except (OSError, json.JSONDecodeError, WorkflowError):
        return new_workflow()

