"""Durable receipts that prevent a crashed worker from replaying a tool call."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from approval import action_summary


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_receipt(action: Any, args: Any, *, turn: int | None = None, step: int | None = None) -> dict[str, Any]:
    value = dict(args) if isinstance(args, dict) else {}
    return {
        "version": 1,
        "status": "pending",
        "action": str(action or "").strip(),
        "args": value,
        "summary": action_summary(action, value),
        "turn": turn,
        "step": step,
        "requested_at": iso_now(),
        "completed_at": None,
        "settled_at": None,
        "recovery": None,
        "result": None,
    }


def complete_receipt(receipt: Any, result: Any) -> dict[str, Any]:
    value = dict(receipt) if isinstance(receipt, dict) else {}
    value["status"] = "completed"
    value["completed_at"] = iso_now()
    value["result"] = dict(result) if isinstance(result, dict) else {"ok": False, "error": "tool result was not an object"}
    return value


def mark_unknown(receipt: Any) -> dict[str, Any]:
    value = dict(receipt) if isinstance(receipt, dict) else {}
    value["status"] = "unknown"
    value["recovery"] = (
        "The worker stopped after this tool call began, so its side effect is unknown. "
        "Inspect the project before attempting the action again."
    )
    return value


def settle_receipt(receipt: Any) -> dict[str, Any]:
    value = dict(receipt) if isinstance(receipt, dict) else {}
    value["status"] = "settled"
    value["settled_at"] = iso_now()
    return value


def public_receipt(receipt: Any) -> dict[str, Any]:
    value = receipt if isinstance(receipt, dict) else {}
    return {
        "version": int(value.get("version", 1) or 1),
        "status": str(value.get("status") or "none"),
        "action": str(value.get("action") or "unknown"),
        "summary": value.get("summary") if isinstance(value.get("summary"), dict) else action_summary(value.get("action"), value.get("args")),
        "turn": value.get("turn"),
        "step": value.get("step"),
        "requested_at": value.get("requested_at"),
        "completed_at": value.get("completed_at"),
        "settled_at": value.get("settled_at"),
        "recovery": value.get("recovery"),
    }

