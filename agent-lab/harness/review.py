"""Durable, inspectable change-review packets for Agent Lab records."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Mapping


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(files: Mapping[str, bytes]) -> str:
    """Return a deterministic fingerprint for a project snapshot."""

    digest = hashlib.sha256()
    for name in sorted(files):
        data = files[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def changed_files(initial: Mapping[str, bytes], current: Mapping[str, bytes]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(set(initial) | set(current)):
        before = initial.get(path)
        after = current.get(path)
        if before == after:
            continue
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            status = "modified"
        records.append(
            {
                "path": path,
                "status": status,
                "before_bytes": len(before) if before is not None else 0,
                "after_bytes": len(after) if after is not None else 0,
            }
        )
    return records


def _clip_diff(value: str, max_diff_chars: int) -> tuple[str, bool]:
    limit = max(1, int(max_diff_chars))
    if len(value) <= limit:
        return value, False
    return value[:limit] + "\n[diff truncated]", True


def build_review_packet(
    initial: Mapping[str, bytes],
    current: Mapping[str, bytes],
    diff: str,
    *,
    validation: Mapping[str, object] | None = None,
    evaluation: Mapping[str, object] | None = None,
    workflow_evidence: Mapping[str, object] | None = None,
    max_diff_chars: int = 50000,
) -> dict[str, object]:
    clipped_diff, diff_truncated = _clip_diff(diff, max_diff_chars)
    return {
        "version": 1,
        "status": "current",
        "generated_at": iso_now(),
        "baseline_fingerprint": fingerprint(initial),
        "current_fingerprint": fingerprint(current),
        "changed_files": changed_files(initial, current),
        "diff": clipped_diff,
        "diff_truncated": diff_truncated,
        "validation": dict(validation or {}),
        "evaluation": dict(evaluation or {}),
        "workflow_evidence": dict(workflow_evidence or {}),
    }


def review_status(packet: Mapping[str, object] | None, current: Mapping[str, bytes]) -> str:
    if not isinstance(packet, Mapping):
        return "not_reviewed"
    return "current" if packet.get("current_fingerprint") == fingerprint(current) else "stale"

