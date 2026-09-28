"""Bounded, durable recovery policy for Agent Lab model loops.

The controller does not execute tools or manufacture evidence. It only answers
one narrow question for the caller: is this the one allowed repair turn, or has
the same condition proved that the loop is stuck?
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


MAX_DETAIL_CHARS = 500


def _clean_text(value: Any, *, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:MAX_DETAIL_CHARS] or fallback


def _clean_category(value: Any) -> str:
    category = _clean_text(value, fallback="unknown")
    category = re.sub(r"[^a-z0-9_.-]+", "_", category.lower()).strip("_.-")
    return category or "unknown"


def action_fingerprint(action: Any, args: Any) -> str:
    """Return a stable short fingerprint for an action and its JSON arguments."""
    try:
        canonical = json.dumps(
            {"action": str(action), "args": args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        canonical = repr((str(action), args))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class RecoveryDecision:
    """The controller's answer for one repeated condition."""

    disposition: str
    category: str
    detail: str
    key: str
    attempt: int
    limit: int

    @property
    def retry(self) -> bool:
        return self.disposition == "retry"

    @property
    def stop(self) -> bool:
        return self.disposition == "stop"

    def as_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "category": self.category,
            "detail": self.detail,
            "key": self.key,
            "attempt": self.attempt,
            "limit": self.limit,
        }


class RecoveryController:
    """Track bounded repair opportunities without owning model-loop behavior."""

    def __init__(
        self,
        *,
        max_retries_per_failure: int = 1,
        max_duplicate_action_retries: int = 1,
    ) -> None:
        self.max_retries_per_failure = self._validate_limit(max_retries_per_failure, "max_retries_per_failure")
        self.max_duplicate_action_retries = self._validate_limit(
            max_duplicate_action_retries,
            "max_duplicate_action_retries",
        )
        self._failure_attempts: dict[str, dict[str, Any]] = {}
        self._last_action: dict[str, Any] | None = None

    @staticmethod
    def _validate_limit(value: Any, name: str) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a non-negative integer") from exc
        if limit < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return limit

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "RecoveryController":
        raw = config.get("recovery", {}) if isinstance(config, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            max_retries_per_failure=raw.get("max_retries_per_failure", 1),
            max_duplicate_action_retries=raw.get("max_duplicate_action_retries", 1),
        )

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> "RecoveryController":
        if not isinstance(snapshot, dict):
            return cls()
        controller = cls(
            max_retries_per_failure=snapshot.get("max_retries_per_failure", 1),
            max_duplicate_action_retries=snapshot.get("max_duplicate_action_retries", 1),
        )
        raw_failures = snapshot.get("failures", [])
        if isinstance(raw_failures, list):
            for value in raw_failures:
                if not isinstance(value, dict):
                    continue
                key = _clean_text(value.get("key"), fallback="")
                category = _clean_category(value.get("category"))
                detail = _clean_text(value.get("detail"), fallback="unspecified failure")
                if not key:
                    continue
                try:
                    attempts = int(value.get("attempts", 0))
                except (TypeError, ValueError):
                    continue
                if attempts > 0:
                    controller._failure_attempts[key] = {
                        "category": category,
                        "detail": detail,
                        "attempts": attempts,
                    }
        raw_action = snapshot.get("last_action")
        if isinstance(raw_action, dict) and raw_action.get("fingerprint"):
            try:
                repeat_count = int(raw_action.get("repeat_count", 0))
            except (TypeError, ValueError):
                repeat_count = 0
            controller._last_action = {
                "action": _clean_text(raw_action.get("action"), fallback="unknown"),
                "fingerprint": _clean_text(raw_action.get("fingerprint"), fallback=""),
                "repeat_count": max(0, repeat_count),
            }
        return controller

    def reset_for_turn(self) -> None:
        """Start a fresh user/model turn without changing the configured policy."""
        self._failure_attempts.clear()
        self._last_action = None

    def _decision(
        self,
        *,
        category: str,
        detail: str,
        key: str,
        attempt: int,
        limit: int,
    ) -> RecoveryDecision:
        return RecoveryDecision(
            disposition="retry" if attempt <= limit else "stop",
            category=category,
            detail=detail,
            key=key,
            attempt=attempt,
            limit=limit,
        )

    def record_failure(self, category: Any, detail: Any) -> RecoveryDecision:
        """Record a repeated failure and grant at most the configured retries."""
        clean_category = _clean_category(category)
        clean_detail = _clean_text(detail, fallback="unspecified failure")
        key = f"{clean_category}:{clean_detail}"
        prior = self._failure_attempts.get(key)
        attempts = int(prior.get("attempts", 0)) + 1 if prior else 1
        self._failure_attempts[key] = {
            "category": clean_category,
            "detail": clean_detail,
            "attempts": attempts,
        }
        return self._decision(
            category=clean_category,
            detail=clean_detail,
            key=key,
            attempt=attempts,
            limit=self.max_retries_per_failure,
        )

    def observe_action(self, action: Any, args: Any) -> RecoveryDecision | None:
        """Return a decision only when the same action is attempted consecutively."""
        clean_action = _clean_text(action, fallback="unknown")
        fingerprint = action_fingerprint(clean_action, args)
        previous = self._last_action
        if previous is not None and previous.get("fingerprint") == fingerprint:
            repeat_count = int(previous.get("repeat_count", 0)) + 1
        else:
            repeat_count = 0
        self._last_action = {
            "action": clean_action,
            "fingerprint": fingerprint,
            "repeat_count": repeat_count,
        }
        if repeat_count == 0:
            return None
        detail = f"the model repeated {clean_action} with the same arguments"
        return self._decision(
            category="duplicate_action",
            detail=detail,
            key=f"duplicate_action:{fingerprint}",
            attempt=repeat_count,
            limit=self.max_duplicate_action_retries,
        )

    def snapshot(self) -> dict[str, Any]:
        failures = [
            {
                "key": key,
                "category": value["category"],
                "detail": value["detail"],
                "attempts": value["attempts"],
            }
            for key, value in sorted(self._failure_attempts.items())
        ]
        last_action = None
        if self._last_action is not None:
            last_action = dict(self._last_action)
        return {
            "max_retries_per_failure": self.max_retries_per_failure,
            "max_duplicate_action_retries": self.max_duplicate_action_retries,
            "failures": failures,
            "last_action": last_action,
        }

