"""Small, durable operator-approval primitives for Agent Lab actions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


APPROVAL_MODES = {"auto", "confirm"}
APPROVAL_ACTIONS = {"write_file", "delete_file", "replace_text", "apply_patch", "run_command"}
APPROVAL_DECISIONS = {"approve", "deny"}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_mode(value: Any) -> str:
    mode = str(value or "auto").strip().lower()
    return mode if mode in APPROVAL_MODES else "auto"


def requires_approval(action: Any, mode: Any) -> bool:
    return normalize_mode(mode) == "confirm" and str(action or "").strip() in APPROVAL_ACTIONS


def action_summary(action: Any, args: Any) -> dict[str, Any]:
    name = str(action or "unknown").strip() or "unknown"
    value = args if isinstance(args, dict) else {}
    if name == "run_command":
        return {"action": name, "command": str(value.get("command") or "")[:500]}
    if name == "apply_patch":
        patch = str(value.get("patch") or "")
        return {"action": name, "patch_chars": len(patch)}
    return {
        "action": name,
        "path": str(value.get("path") or "")[:500],
        "content_bytes": len(str(value.get("content") or "").encode("utf-8")) if "content" in value else None,
    }


def new_request(action: Any, args: Any, *, turn: int | None = None, step: int | None = None) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "pending",
        "action": str(action or "").strip(),
        "args": dict(args) if isinstance(args, dict) else {},
        "summary": action_summary(action, args),
        "turn": turn,
        "step": step,
        "requested_at": iso_now(),
        "decided_at": None,
        "decision": None,
    }


def public_request(request: Any) -> dict[str, Any]:
    value = request if isinstance(request, dict) else {}
    summary = value.get("summary") if isinstance(value.get("summary"), dict) else action_summary(value.get("action"), value.get("args"))
    public = {
        "version": int(value.get("version", 1) or 1),
        "status": str(value.get("status") or "pending"),
        "action": str(value.get("action") or "unknown"),
        "summary": summary,
        "turn": value.get("turn"),
        "step": value.get("step"),
        "requested_at": value.get("requested_at"),
        "decided_at": value.get("decided_at"),
        "decision": value.get("decision"),
    }
    for key, item in summary.items():
        if key != "action":
            public[key] = item
    return public


def resolve_request(request: Any, decision: Any) -> dict[str, Any]:
    value = dict(request) if isinstance(request, dict) else {}
    choice = str(decision or "").strip().lower()
    if choice not in APPROVAL_DECISIONS:
        raise ValueError("approval decision must be approve or deny")
    if value.get("status") in {"approved", "denied"}:
        return value
    if value.get("status") != "pending":
        raise ValueError("approval request is not pending")
    value["status"] = "approved" if choice == "approve" else "denied"
    value["decision"] = choice
    value["decided_at"] = iso_now()
    return value

