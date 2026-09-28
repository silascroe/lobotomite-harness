"""Durable, process-aware leases for project folders used by Agent Lab."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOCK_VERSION = 1


class WorkspaceBusyError(RuntimeError):
    """Raised when another live Agent Lab worker owns a project folder."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_project(project_dir: Path) -> Path:
    return Path(project_dir).expanduser().resolve()


def lock_path(lock_root: Path, project_dir: Path) -> Path:
    project = str(normalize_project(project_dir)).casefold().encode("utf-8")
    digest = hashlib.sha256(project).hexdigest()
    return Path(lock_root) / f"{digest}.json"


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_lock(lock_root: Path, project_dir: Path) -> dict[str, Any] | None:
    path = lock_path(lock_root, project_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceBusyError(f"workspace lock is unreadable: {path.name}") from exc
    if not isinstance(value, dict) or value.get("version") != LOCK_VERSION:
        raise WorkspaceBusyError(f"workspace lock is invalid: {path.name}")
    return value


@dataclass
class WorkspaceLease:
    path: Path
    record: dict[str, Any]

    def release(self) -> None:
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(current, dict) and current.get("owner_id") == self.record.get("owner_id"):
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def public(self) -> dict[str, Any]:
        return {
            "status": "held",
            "kind": self.record.get("kind", "worker"),
            "owner_id": self.record.get("owner_id", ""),
            "pid": self.record.get("pid"),
            "project": self.record.get("project", ""),
        }


def acquire(
    lock_root: Path,
    project_dir: Path,
    owner_id: str,
    kind: str,
    *,
    pid: int | None = None,
) -> WorkspaceLease:
    """Acquire a project lease, reclaiming only locks whose process is gone."""

    project = normalize_project(project_dir)
    path = lock_path(lock_root, project)
    Path(lock_root).mkdir(parents=True, exist_ok=True)
    record = {
        "version": LOCK_VERSION,
        "owner_id": str(owner_id),
        "kind": str(kind),
        "pid": int(os.getpid() if pid is None else pid),
        "project": str(project),
        "acquired_at": iso_now(),
        "heartbeat": time.time(),
    }

    for _ in range(3):
        try:
            descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = read_lock(lock_root, project)
            if existing is None:
                continue
            existing_pid = int(existing.get("pid", 0) or 0)
            same_owner = existing.get("owner_id") == record["owner_id"]
            same_process = existing_pid == record["pid"]
            if same_owner and same_process:
                return WorkspaceLease(path, existing)
            if process_alive(existing_pid):
                owner = existing.get("owner_id") or "another worker"
                kind_label = existing.get("kind") or "worker"
                raise WorkspaceBusyError(f"workspace is busy with {kind_label} {owner}")
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return WorkspaceLease(path, record)
    raise WorkspaceBusyError("workspace lock could not be acquired")

