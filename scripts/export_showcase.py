#!/usr/bin/env python3
"""Export recorded runs into the static, read-only showcase used by GitHub Pages.

The showcase is the real console (agent-lab/ui) in showcase mode, replaying
these recordings. Only the runs and chats named here are exported, and every
string is sanitized: local paths are replaced, model reasoning and raw model
output are dropped, long values are clipped, and only small text project files
are included for preview.

    python scripts/export_showcase.py                 # default curated set
    python scripts/export_showcase.py --run RUN_ID --chat CHAT_ID
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent-lab" / "ui"))
import server  # noqa: E402  (reuses the console's own read paths)

OUT = ROOT / "site" / "showcase"
DEFAULT_RUNS = [
    "matrix-20261011-201925-004-off",       # fails twice, repairs, passes
    "matrix-20261011-205901-001-deep",      # full static page, first-try pass
    "matrix-20261011-203757-001-standard",  # static page blocked on patch context
    "matrix-20261011-205901-003-standard",  # structured validation pass
    "matrix-20261011-205901-002-off",       # quick file round-trip
]
DEFAULT_CHATS = ["chat-20261011-221823"]
MAX_STRING = 2400
MAX_FILE_BYTES = 30000


def replacements() -> list[tuple[str, str]]:
    pairs = [(str(ROOT), "<agent-lab>"), (str(Path.home()), "~")]
    out: list[tuple[str, str]] = []
    for raw, label in pairs:
        for variant in {raw, raw.replace("\\", "/"), raw.replace("\\", "\\\\")}:
            out.append((variant, label))
    return sorted(out, key=lambda item: -len(item[0]))


REPLACEMENTS = replacements()


def clean(value: Any) -> Any:
    if isinstance(value, str):
        for raw, label in REPLACEMENTS:
            value = value.replace(raw, label)
        if len(value) > MAX_STRING:
            value = value[:MAX_STRING] + f"\n...[clipped for the showcase; {len(value)} characters]"
        return value
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key not in {"reasoning_content", "api_key", "authorization"}}
    return value


def clean_event(event: dict[str, Any]) -> dict[str, Any] | None:
    name = event.get("event")
    if name in {"session_rehydrated", "workspace_lock_acquired", "workspace_lock_released"}:
        return None
    data = dict(event.get("data") or {})
    if name == "model_response":
        data = {key: data.get(key) for key in ("turn", "step", "finish_reason", "usage", "reasoning_level", "provider") if key in data}
    if name == "invalid_model_action":
        data.pop("content", None)
    return clean({"timestamp": event.get("timestamp"), "event": name, "data": data})


def project_contents(project: Path, files: list[dict[str, Any]]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for item in files:
        path = (project / item["path"]).resolve()
        try:
            path.relative_to(project.resolve())
        except ValueError:
            continue
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            continue
        contents[item["path"]] = clean(data.decode("utf-8", errors="replace"))
    return contents


def export_run(run_id: str) -> dict[str, Any]:
    state = server.run_state(run_id)
    page = server.read_event_page(run_id, 0)
    events = list(page["events"])
    while not page["complete"]:
        page = server.read_event_page(run_id, page["next"])
        events.extend(page["events"])
    record = clean({key: value for key, value in state.items() if key not in {"events"}})
    record["events_full"] = [item for item in (clean_event(e) for e in events) if item]
    record["events"] = record["events_full"][-200:]
    record["file_contents"] = project_contents(server.run_project_dir(run_id), state.get("files", []))
    return record


def export_chat(session_id: str) -> dict[str, Any]:
    # Read the saved files directly. Rehydrating an InteractiveSession would
    # take a workspace lease and append events, and an exporter must not write.
    session_dir = server.resolve_inside(server.SESSION_DIR, server.validate_run_id(session_id))
    meta = server.read_json(session_dir / "session.json") or {}
    project = Path(meta.get("project") or session_dir / "project")
    events: list[dict[str, Any]] = []
    for line in (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    record = clean({key: value for key, value in meta.items() if key not in {"skill_overrides"}})
    record["session_id"] = session_id
    record["events"] = [item for item in (clean_event(e) for e in events) if item]
    record["files"] = clean(server.project_files_from(project))
    record["busy"] = False
    record["status"] = "ready"
    return record


def summary_row(record: dict[str, Any]) -> dict[str, Any]:
    summary = record.get("summary") or {}
    return {
        "run_id": record["run_id"],
        "status": record["status"],
        "summary": summary.get("summary", ""),
        "model": record.get("model", ""),
        "task_profile": record.get("task_profile", {}),
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "reasoning_level": (record.get("reasoning") or {}).get("level"),
        "first_pass_passed": summary.get("first_pass_passed"),
        "model_calls": record.get("model_calls"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", action="append", dest="runs", help="run id to include (repeatable)")
    parser.add_argument("--chat", action="append", dest="chats", help="chat session id to include (repeatable)")
    args = parser.parse_args()
    runs = args.runs or DEFAULT_RUNS
    chats = args.chats if args.chats is not None else DEFAULT_CHATS

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "runs").mkdir(parents=True)
    (OUT / "sessions").mkdir(parents=True)

    rows = []
    for run_id in runs:
        record = export_run(run_id)
        (OUT / "runs" / f"{run_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        rows.append(summary_row(record))
        print(f"run  {run_id}: {record['status']}, {len(record['events_full'])} events, {len(record['file_contents'])} files")
    for session_id in chats:
        record = export_chat(session_id)
        (OUT / "sessions" / f"{session_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        print(f"chat {session_id}: {len(record.get('conversation', []))} messages")

    config = server.read_json(server.CONFIG) or {}
    manifest = clean({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": rows,
        "sessions": chats,
        "tasks": server.task_catalog(),
        "reasoning_levels": server.reasoning_options(),
        "provider": server.public_provider({"provider": "local", "model": config.get("model", ""), "endpoint": "showcase recording"}),
        "skills": server.skill_catalog(),
    })
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    blob = "\n".join(p.read_text(encoding="utf-8") for p in OUT.rglob("*.json"))
    leaks = [raw for raw, _ in REPLACEMENTS if raw and raw in blob]
    if leaks or "reasoning_content" in blob:
        print("refusing: sanitization check failed", file=sys.stderr)
        shutil.rmtree(OUT)
        return 1
    size = sum(p.stat().st_size for p in OUT.rglob("*.json"))
    print(f"wrote {OUT.relative_to(ROOT)} ({size // 1024} KB), sanitization check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
