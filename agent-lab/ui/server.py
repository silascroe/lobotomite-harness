#!/usr/bin/env python3
"""Local-only web console for the agent lab."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
UI_DIR = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "agent-lab" / "tasks"
RUNS_DIR = ROOT / "agent-lab" / "runs"
SESSION_DIR = ROOT / "agent-lab" / "chat-sessions"
PROJECTS_DIR = ROOT / "agent-lab" / "projects"
HARNESS = ROOT / "agent-lab" / "harness" / "agent_harness.py"
CONFIG = ROOT / "agent-lab" / "harness" / "config.json"
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,50}")
STATIC_CACHE_CONTROL = "no-store, max-age=0"

sys.path.insert(0, str(HARNESS.parent))
from agent_harness import (  # noqa: E402
    ACTION_NAMES,
    AgentHarness,
    HarnessError,
    RecoveryController,
    extract_json_object,
    json_text,
    iter_project_files,
    normalize_reasoning_level,
    recovery_instruction,
    reasoning_options,
)
from skills import (  # noqa: E402
    DEFAULT_SKILL_NAMES,
    SkillError,
    find_skills,
    list_skills,
    public_selection,
    public_skill,
    resolve_skill_selection,
)
from persistence import atomic_write_json  # noqa: E402
from job_state import (  # noqa: E402
    JobStateError,
    complete_job,
    fail_job,
    idle_job,
    mark_interrupted,
    mark_user_message_persisted,
    new_job,
    normalize_job,
    start_attempt,
    update_progress,
)
from workflow import load_workflow  # noqa: E402

PROCESS_LOCK = threading.Lock()
PROCESSES: dict[str, subprocess.Popen[str]] = {}
OUTPUTS: dict[str, list[str]] = {}
SESSION_LOCK = threading.Lock()
SESSIONS: dict[str, "InteractiveSession"] = {}

INTERACTIVE_SYSTEM_PROMPT = """You are a local interactive coding assistant.

The user is talking to you directly. Answer ordinary questions naturally with the respond action. When the user asks you to inspect, create, modify, or test files, use the tools below and then explain what happened with respond. You are working in the assigned project directory, which may be an existing user project, and can only affect that directory.

Rules:
- Use relative paths only. Never use '..', absolute paths, or paths outside the project.
- Every action must include all required fields; write_file, replace_text, read_file, and list_files always need a non-empty relative args.path. Never send a content-only write_file call.
- Do not claim a file was created or tested until a tool result proves it.
- There is no network access for this session. Do not install packages or fetch assets.
- Preserve existing project work unless the user explicitly asks you to replace it.
- Keep edits focused and ask the user when a request is ambiguous or materially risky.
- Every response must be exactly one JSON object and nothing else.

Response shapes:
{"action":"respond","args":{"content":"your natural-language reply"}}
{"action":"list_files","args":{"path":".","max_depth":3}}
{"action":"read_file","args":{"path":"relative/path","max_chars":12000}}
{"action":"write_file","args":{"path":"relative/path","content":"complete UTF-8 file contents"}}
{"action":"delete_file","args":{"path":"relative/path"}}
{"action":"replace_text","args":{"path":"relative/path","old_text":"exact text to find","new_text":"replacement text","expected_replacements":1}}
{"action":"apply_patch","args":{"patch":"*** Begin Patch\\n*** Update File: styles.css\\n@@\\n-old line\\n+new line\\n*** End Patch"}}
{"action":"run_command","args":{"command":"node --check app.js"}}
{"action":"git_diff","args":{"max_chars":12000}}
{"action":"find_skills","args":{"query":"browser testing","source":"local"}}
{"action":"workflow_checkpoint","args":{"phase":"plan","summary":"short operational status","next_action":"the next concrete step","artifacts":["docs/plan.md"]}}

Workflow guidance:
- Move the workflow forward with short checkpoints when the task meaningfully changes phase: inspect, design, plan, implement, verify, or review.
- Checkpoint summaries describe observable work only; never expose hidden chain-of-thought.
- Use relative artifact paths only. Successful tool calls also advance the workflow automatically.

Use respond when you are done with the user's current message. This is a continuing conversation, so do not use finish.
"""

INTERACTIVE_ACTIONS = {"respond"} | ACTION_NAMES


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_json_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        raise ApiError("run id must contain only letters, numbers, '-' or '_'")
    return value


def resolve_inside(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError("path is required")
    source = root / raw
    if source.exists() and source.is_symlink():
        raise ApiError("symlinks are not allowed")
    candidate = source.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ApiError("path must stay inside the allowed directory") from exc
    return candidate


def normalize_project_path(raw: Any, default: Path) -> Path:
    """Resolve a user-selected workspace without allowing a file as the root."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default.resolve()
    if not isinstance(raw, str):
        raise ApiError("project_path must be a filesystem path")
    if len(raw.strip()) > 1000:
        raise ApiError("project_path is too long")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    if candidate.is_symlink():
        raise ApiError("symlink project folders are not allowed")
    candidate = candidate.resolve()
    if candidate.exists() and not candidate.is_dir():
        raise ApiError("project_path must point to a directory")
    return candidate


def project_catalog() -> list[dict[str, Any]]:
    """Return harness-owned projects; registry metadata stays outside each workspace."""
    if not PROJECTS_DIR.is_dir():
        return []
    projects: list[dict[str, Any]] = []
    for directory in PROJECTS_DIR.iterdir():
        if not directory.is_dir() or not RUN_ID_RE.fullmatch(directory.name):
            continue
        workspace = directory / "workspace"
        metadata = read_json(directory / "project.json") or {}
        if not workspace.is_dir():
            continue
        projects.append({
            "project_id": directory.name,
            "name": metadata.get("name") or directory.name.replace("-", " ").title(),
            "path": str(workspace.resolve()),
            "created_at": metadata.get("created_at", ""),
            "files": len(project_files_from(workspace)),
        })
    return sorted(projects, key=lambda item: (item["name"].lower(), item["project_id"]))


def create_project(raw_name: Any) -> dict[str, Any]:
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ApiError("project name is required")
    name = re.sub(r"\s+", " ", raw_name.strip())
    if len(name) > 80:
        raise ApiError("project name must be 80 characters or fewer")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    slug = slug[:45].rstrip("-") or "project"
    candidate = slug
    suffix = 2
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    while (PROJECTS_DIR / candidate).exists():
        candidate = f"{slug}-{suffix}"
        suffix += 1
    project_root = PROJECTS_DIR / candidate
    workspace = project_root / "workspace"
    workspace.mkdir(parents=True)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_write_json(project_root / "project.json", {"project_id": candidate, "name": name, "created_at": created_at})
    return {"project_id": candidate, "name": name, "path": str(workspace.resolve()), "created_at": created_at, "files": 0}


def run_project_dir(run_id: str) -> Path:
    run_dir = resolve_inside(RUNS_DIR, run_id)
    summary = read_json(run_dir / "summary.json") or {}
    workspace = read_json(run_dir / "workspace.json") or {}
    raw = summary.get("project") or workspace.get("project")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser().resolve()
    return run_dir / "project"


def task_catalog() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    if not TASKS_DIR.is_dir():
        return tasks
    for path in sorted(TASKS_DIR.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = next((line.lstrip("# ").strip() for line in content.splitlines() if line.startswith("#")), path.stem)
        tasks.append({"name": path.name, "title": title, "content": content})
    return tasks


def skill_catalog(raw_project_path: Any = None) -> dict[str, Any]:
    project_path = None
    if isinstance(raw_project_path, str) and raw_project_path.strip():
        project_path = normalize_project_path(raw_project_path, ROOT / "agent-lab" / "scratch")
    return {
        "defaults": list(DEFAULT_SKILL_NAMES),
        "skills": [public_skill(item) for item in list_skills(project_path)],
    }


def discover_skills(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query")
    source = str(payload.get("source", "local")).strip().lower()
    if source == "remote" and payload.get("confirm_remote") is not True:
        raise ApiError("remote discovery requires explicit confirmation")
    raw_project_path = payload.get("project_path")
    project_path = None
    if isinstance(raw_project_path, str) and raw_project_path.strip():
        project_path = normalize_project_path(raw_project_path, ROOT / "agent-lab" / "scratch")
    try:
        results = find_skills(
            query,
            project_path,
            source=source,
            allow_remote=source == "remote" and payload.get("confirm_remote") is True,
        )
    except SkillError as exc:
        raise ApiError(str(exc), 400) from exc
    return {"query": query, "source": source, "results": results}


def read_events(run_id: str) -> list[dict[str, Any]]:
    run_dir = resolve_inside(RUNS_DIR, run_id)
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines[-200:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def project_files(run_id: str) -> list[dict[str, Any]]:
    return project_files_from(run_project_dir(run_id))


def read_run_output(run_id: str) -> list[str]:
    path = resolve_inside(RUNS_DIR, run_id) / "output.log"
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
    except OSError:
        return []


def run_state(run_id: str) -> dict[str, Any]:
    run_dir = resolve_inside(RUNS_DIR, run_id)
    project = run_project_dir(run_id)
    summary = read_json(run_dir / "summary.json") or {}
    progress = read_json(run_dir / "progress.json") or {}
    workflow = load_workflow(run_dir / "workflow.json")
    with PROCESS_LOCK:
        process = PROCESSES.get(run_id)
        output = list(OUTPUTS.get(run_id, []))
    if not output:
        output = read_run_output(run_id)
    if summary.get("status"):
        status = summary["status"]
    elif process is not None and process.poll() is None:
        status = "running"
    elif progress.get("status") == "running":
        status = "interrupted"
    elif progress.get("status") in {"success", "blocked", "error"}:
        status = progress["status"]
    elif process is not None:
        status = "error" if process.returncode else "complete"
    else:
        status = "aborted"
    return {
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "progress": progress,
        "output": output[-200:],
        "events": read_events(run_id),
        "files": project_files(run_id),
        "project": str(project),
        "workspace_mode": summary.get("workspace_mode") or ("managed" if project == (run_dir / "project").resolve() else "selected"),
        "workflow": workflow,
        "skills": summary.get("skills", {}),
        "model": summary.get("model", ""),
        "model_calls": summary.get("model_calls", progress.get("model_calls", 0)),
        "tool_calls": summary.get("tool_calls", progress.get("tool_calls", 0)),
        "context": summary.get("context", progress.get("context", {})),
    }


def run_summaries() -> list[dict[str, Any]]:
    if not RUNS_DIR.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for directory in RUNS_DIR.iterdir():
        if not directory.is_dir() or not RUN_ID_RE.fullmatch(directory.name):
            continue
        state = run_state(directory.name)
        summary = state["summary"]
        result.append(
            {
                "run_id": directory.name,
                "status": state["status"],
                "summary": summary.get("summary", ""),
                "model": summary.get("model", ""),
                "project": state.get("project", summary.get("project", "")),
                "workspace_mode": state.get("workspace_mode", summary.get("workspace_mode", "")),
                "changed_files": summary.get("changed_files", []),
                "workflow": state.get("workflow", {}),
                "skills": state.get("skills", summary.get("skills", {})),
                "elapsed_seconds": summary.get("elapsed_seconds"),
                "updated": directory.stat().st_mtime,
            }
        )
    return sorted(result, key=lambda item: item["updated"], reverse=True)[:30]


def capture_process(run_id: str, process: subprocess.Popen[str]) -> None:
    if process.stdout is not None:
        output_path = resolve_inside(RUNS_DIR, run_id) / "output.log"
        output_file = None
        try:
            for line in process.stdout:
                clean_line = line.rstrip("\r\n")
                if output_file is None:
                    try:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_file = output_path.open("a", encoding="utf-8", newline="")
                    except OSError:
                        output_file = None
                if output_file is not None:
                    output_file.write(clean_line + "\n")
                    output_file.flush()
                with PROCESS_LOCK:
                    OUTPUTS.setdefault(run_id, []).append(clean_line)
                    OUTPUTS[run_id] = OUTPUTS[run_id][-300:]
        finally:
            if output_file is not None:
                output_file.close()
    process.wait()


def read_events_from(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines[-200:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def project_files_from(project: Path) -> list[dict[str, Any]]:
    if not project.is_dir():
        return []
    config = read_json(CONFIG) or {}
    files: list[dict[str, Any]] = []
    for path in iter_project_files(project, config):
        files.append({"path": path.relative_to(project).as_posix(), "bytes": path.stat().st_size})
    return sorted(files, key=lambda item: item["path"])


class InteractiveSession:
    def __init__(
        self,
        session_id: str,
        reasoning_level: str | None = None,
        project_path: Any = None,
        skill_overrides: Any = None,
        *,
        resume: bool = False,
    ) -> None:
        self.session_id = session_id
        self.run_dir = SESSION_DIR / session_id
        persisted = read_json(self.run_dir / "session.json") if resume else {}
        if resume and persisted is None:
            raise HarnessError("session metadata is missing or invalid")
        config = read_json(self.run_dir / "config.json") if resume else read_json(CONFIG)
        if config is None:
            config = read_json(CONFIG)
        if config is None:
            raise ApiError("could not read harness config", 500)
        config = dict(config)
        if resume and reasoning_level is None:
            persisted_reasoning = persisted.get("reasoning") if isinstance(persisted, dict) else None
            if isinstance(persisted_reasoning, dict) and persisted_reasoning.get("level"):
                config["reasoning_level"] = persisted_reasoning["level"]
        if reasoning_level is not None:
            try:
                config["reasoning_level"] = normalize_reasoning_level(reasoning_level)
            except ValueError as exc:
                raise ApiError(str(exc)) from exc
        if resume and skill_overrides is None and isinstance(persisted, dict):
            skill_overrides = persisted.get("skill_overrides")
        if resume and skill_overrides is None:
            skill_overrides = config.get("skill_overrides")
        if skill_overrides is not None:
            config["skill_overrides"] = skill_overrides
        config["required_files"] = []
        config["require_validation"] = False
        config["require_workflow_gates"] = False
        config["allow_remote_skill_search"] = False
        config.pop("evaluator", None)
        config["max_turns"] = 12
        persisted_project = project_path
        if resume and persisted_project is None and isinstance(persisted, dict):
            persisted_project = persisted.get("project")
            if not persisted_project:
                workspace = read_json(self.run_dir / "workspace.json") or {}
                persisted_project = workspace.get("project")
        self.project_dir = normalize_project_path(persisted_project, self.run_dir / "project")
        self.lock = threading.Lock()
        self.busy = False
        self.status = "ready"
        self.last_error = ""
        self.job = normalize_job(persisted.get("job")) if resume and isinstance(persisted, dict) else idle_job()
        self.worker_thread: threading.Thread | None = None
        self.conversation: list[dict[str, str]] = self._conversation_from(persisted.get("conversation", [])) if resume and isinstance(persisted, dict) else []
        self.harness = AgentHarness(
            task="This is an ongoing interactive session. The user will send messages one at a time.",
            config=config,
            run_dir=self.run_dir,
            project_dir=self.project_dir,
            template_dir=None,
            system_prompt=INTERACTIVE_SYSTEM_PROMPT,
        )
        if resume:
            self._restore_from_disk(persisted or {})
        else:
            self.harness.prepare()
            self.harness.messages = [{"role": "system", "content": self.harness.system_content()}]
            self.harness.logger.event(
                "session_ready",
                session_id=session_id,
                project=str(self.project_dir),
                mode=self.harness.workspace_mode,
            )
            self.save_meta()

    @staticmethod
    def _conversation_from(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        return [
            {"role": item["role"], "content": item["content"]}
            for item in value
            if isinstance(item, dict)
            and item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
        ]

    def _restore_from_disk(self, persisted: dict[str, Any]) -> None:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        transcript = read_json_value(self.run_dir / "transcript.json")
        messages = [
            {"role": item["role"], "content": item["content"]}
            for item in transcript
            if isinstance(item, dict)
            and item.get("role") in {"system", "user", "assistant"}
            and isinstance(item.get("content"), str)
        ] if isinstance(transcript, list) else []
        if not messages or messages[0]["role"] != "system":
            messages.insert(0, {"role": "system", "content": self.harness.system_content()})
        self.harness.messages = messages
        persisted_context = persisted.get("context")
        if isinstance(persisted_context, dict):
            self.harness.context_metadata = dict(persisted_context)
        self.harness.workflow = load_workflow(self.run_dir / "workflow.json")
        self.harness.recovery = RecoveryController.from_snapshot(persisted.get("recovery"))
        self.harness.initial_files = self.harness.snapshot_files()
        for name in ("model_calls", "tool_calls"):
            try:
                setattr(self.harness, name, max(0, int(persisted.get(name, 0))))
            except (TypeError, ValueError):
                setattr(self.harness, name, 0)
        if self.job["status"] != "idle" and not self.job["user_message_persisted"]:
            expected_user_content = self.harness.user_content(self.job["user_message"])
            self.job["user_message_persisted"] = any(
                item.get("role") == "user" and item.get("content") == expected_user_content
                for item in self.harness.messages
            )
        legacy_busy = bool(persisted.get("busy")) and bool(self.conversation) and self.conversation[-1].get("role") == "user"
        if self.job["status"] == "running":
            self.job = mark_interrupted(self.job, reason="The server stopped before this turn finished.")
            self.status = "interrupted"
            self.last_error = self.job["error"]
            self.harness.logger.event("job_interrupted", job=self.job, reason=self.job["error"])
        elif legacy_busy:
            message = self.conversation[-1]["content"]
            legacy_job = new_job(message, job_id=f"{self.session_id}-attempt-1")
            if any(
                item.get("role") == "user" and item.get("content") == self.harness.user_content(message)
                for item in self.harness.messages
            ):
                legacy_job = mark_user_message_persisted(legacy_job)
            self.job = mark_interrupted(legacy_job, reason="The server stopped before this turn finished.")
            self.status = "interrupted"
            self.last_error = self.job["error"]
            self.harness.logger.event("job_interrupted", job=self.job, reason=self.job["error"])
        elif self.job["status"] == "interrupted":
            self.status = "interrupted"
            self.last_error = self.job["error"]
        elif self.job["status"] == "failed":
            self.status = "error"
            self.last_error = self.job["error"]
        else:
            self.status = "ready"
            self.last_error = ""
        self.busy = False
        self.harness.logger.event(
            "session_rehydrated",
            session_id=self.session_id,
            project=str(self.project_dir),
            mode=self.harness.workspace_mode,
            workflow=self.harness.workflow,
        )
        self.save_meta()

    @classmethod
    def from_disk(cls, session_id: str) -> "InteractiveSession":
        validate_run_id(session_id)
        return cls(session_id, resume=True)

    def save_meta(self) -> None:
        with self.lock:
            value = {
                "session_id": self.session_id,
                "status": self.status,
                "busy": self.busy,
                "last_error": self.last_error,
                "model": self.harness.config.get("model"),
                "reasoning": self.harness.reasoning_metadata(),
                "context": dict(self.harness.context_metadata),
                "model_calls": self.harness.model_calls,
                "tool_calls": self.harness.tool_calls,
                "project": str(self.project_dir),
                "workspace_mode": self.harness.workspace_mode,
                "workflow": self.harness.workflow,
                "recovery": self.harness.recovery.snapshot(),
                "skills": self.harness.skill_metadata(),
                "skill_overrides": self.harness.config.get("skill_overrides", {}),
                "job": self.job,
                "conversation": self.conversation,
            }
        atomic_write_json(self.run_dir / "session.json", value)
        self.harness.save_transcript()

    def state(self) -> dict[str, Any]:
        with self.lock:
            conversation = list(self.conversation)
            status = self.status
            busy = self.busy
            last_error = self.last_error
        return {
            "session_id": self.session_id,
            "status": status,
            "busy": busy,
            "last_error": last_error,
            "job": self.job,
            "model": self.harness.config.get("model"),
            "reasoning": self.harness.reasoning_metadata(),
            "context": dict(self.harness.context_metadata),
            "model_calls": self.harness.model_calls,
            "tool_calls": self.harness.tool_calls,
            "project": str(self.project_dir),
            "workspace_mode": self.harness.workspace_mode,
            "workflow": self.harness.workflow,
            "recovery": self.harness.recovery.snapshot(),
            "skills": self.harness.skill_metadata(),
            "conversation": conversation,
            "events": read_events_from(self.run_dir),
            "files": project_files_from(self.project_dir),
        }

    def send(self, content: str) -> None:
        content = content.strip()
        if not content:
            raise ApiError("message cannot be empty")
        if len(content) > 20000:
            raise ApiError("message is too long")
        with self.lock:
            if self.busy:
                raise ApiError("the model is still working on the previous message", 409)
            if self.job["status"] in {"interrupted", "failed"}:
                raise ApiError("this turn was interrupted; retry it before sending a new message", 409)
            self.harness.recovery.reset_for_turn()
            self.busy = True
            self.status = "thinking"
            self.last_error = ""
            self.job = new_job(content, job_id=f"{self.session_id}-attempt-1")
            self.conversation.append({"role": "user", "content": content})
        self.save_meta()
        self._start_worker(content, self.job["job_id"])

    def _start_worker(self, content: str, job_id: str, append_user: bool = True) -> None:
        worker = threading.Thread(
            target=self.process,
            args=(content, job_id, append_user),
            daemon=True,
            name=f"agent-lab-{self.session_id}-{job_id}",
        )
        with self.lock:
            self.worker_thread = worker
        worker.start()

    def retry(self) -> None:
        with self.lock:
            if self.busy:
                raise ApiError("the model is still working on the previous message", 409)
            next_attempt = int(self.job.get("attempt", 0)) + 1
            job_id = f"{self.job.get('job_id') or self.session_id}-attempt-{next_attempt}"
            try:
                self.job = start_attempt(self.job, job_id=job_id)
            except JobStateError as exc:
                raise ApiError(str(exc), 409) from exc
            self.harness.recovery.reset_for_turn()
            content = self.job["user_message"]
            if not self.job["user_message_persisted"]:
                self.harness.messages.append({"role": "user", "content": self.harness.user_content(content)})
                self.job = mark_user_message_persisted(self.job)
            self.busy = True
            self.status = "thinking"
            self.last_error = ""
            self.harness.logger.event("job_retry_requested", job=self.job)
        self.save_meta()
        self._start_worker(content, self.job["job_id"], append_user=False)

    def _worker_is_current(self, job_id: str) -> bool:
        with self.lock:
            return self.job.get("job_id") == job_id and self.job.get("status") == "running"

    def _checkpoint_worker(self, job_id: str, step: int, action: str) -> bool:
        with self.lock:
            if self.job.get("job_id") != job_id or self.job.get("status") != "running":
                return False
            self.job = update_progress(self.job, step=step, action=action)
            self.harness.logger.event(
                "job_progress",
                job_id=job_id,
                attempt=self.job["attempt"],
                step=step,
                action=action,
            )
        self.save_meta()
        return True

    def _finish_worker(self, job_id: str, error: str | None) -> None:
        with self.lock:
            if self.job.get("job_id") != job_id or self.job.get("status") != "running":
                return
            if error:
                self.job = fail_job(self.job, error)
                self.status = "error"
                self.last_error = error
            else:
                self.job = complete_job(self.job)
                self.status = "ready"
                self.last_error = ""
            self.busy = False
            self.worker_thread = None
        self.save_meta()

    def set_reasoning_level(self, value: Any) -> None:
        try:
            normalized = normalize_reasoning_level(value)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        with self.lock:
            if self.busy:
                raise ApiError("wait for the current message to finish before changing reasoning", 409)
            self.harness.config["reasoning_level"] = normalized
            self.harness.logger.event("settings_updated", reasoning_level=normalized)
        self.save_meta()

    def add_assistant_message(self, content: str) -> None:
        with self.lock:
            self.conversation.append({"role": "assistant", "content": content})

    def process(self, content: str, job_id: str, append_user: bool = True) -> None:
        failure: str | None = None
        try:
            if not self._worker_is_current(job_id):
                return
            if append_user:
                self.harness.messages.append({"role": "user", "content": self.harness.user_content(content)})
                with self.lock:
                    if self.job.get("job_id") == job_id and self.job.get("status") == "running":
                        self.job = mark_user_message_persisted(self.job)
                self.save_meta()
            max_steps = int(self.harness.config.get("max_turns", 12))
            correction = ""
            for step in range(1, max_steps + 1):
                if not self._checkpoint_worker(job_id, step, "model_call"):
                    return
                if correction:
                    self.harness.messages.append({"role": "user", "content": self.harness.user_content(correction)})
                response = self.harness.call_model()
                if not self._worker_is_current(job_id):
                    return
                self.harness.logger.event("model_response", step=step, **response)
                raw_content = response.get("content", "")
                self.harness.messages.append({"role": "assistant", "content": raw_content})
                self._checkpoint_worker(job_id, step, "model_response")
                try:
                    parsed = extract_json_object(raw_content)
                    action = parsed.get("action")
                    args = parsed.get("args", {})
                    if not isinstance(args, dict):
                        raise HarnessError("args must be a JSON object")
                    if action not in INTERACTIVE_ACTIONS:
                        raise HarnessError("unknown interactive action")
                except (HarnessError, AttributeError) as exc:
                    error = str(exc)
                    self.harness.logger.event("invalid_model_action", step=step, error=error, content=raw_content)
                    decision = self.harness.recovery.record_failure("invalid_model_action", error)
                    if decision.stop:
                        self.harness.recovery_event("recovery_exhausted", decision, step=step)
                        self.add_assistant_message(
                            f"I stopped after one repair attempt because {decision.detail}. "
                            "Send the message again if you want a fresh attempt."
                        )
                        self.harness.logger.event("assistant_message", content=self.conversation[-1]["content"])
                        self._checkpoint_worker(job_id, step, "recovery_exhausted")
                        break
                    self.harness.recovery_event("recovery_retry", decision, step=step)
                    correction = (
                        f"Your response was invalid: {error}. This is repair attempt {decision.attempt} "
                        f"of {decision.limit}. Return one complete JSON object using the documented action shapes. "
                        "Do not use Markdown fences, do not apologize, and balance every brace."
                    )
                    self._checkpoint_worker(job_id, step, "recovery_retry")
                    continue

                correction = ""
                if action in {"respond", "finish"}:
                    reply = str(args.get("content") or args.get("summary") or "")
                    if not reply:
                        reply = "I completed that turn, but I have no useful summary to report."
                    self.add_assistant_message(reply)
                    self.harness.logger.event("assistant_message", content=reply)
                    break

                duplicate = self.harness.recovery.observe_action(action, args)
                if duplicate is not None:
                    self.harness.recovery_event("recovery_duplicate_action", duplicate, step=step)
                    if duplicate.stop:
                        self.harness.recovery_event("recovery_exhausted", duplicate, step=step)
                        self.add_assistant_message(
                            f"I stopped after one repair attempt because {duplicate.detail}. "
                            "Send the message again if you want a fresh attempt."
                        )
                        self.harness.logger.event("assistant_message", content=self.conversation[-1]["content"])
                        self._checkpoint_worker(job_id, step, "recovery_exhausted")
                        break
                    self.harness.recovery_event("recovery_retry", duplicate, step=step)
                    result = {
                        "ok": False,
                        "error": (
                            f"duplicate action blocked before dispatch: {duplicate.detail}. "
                            f"Choose a different action; repair attempt {duplicate.attempt} of {duplicate.limit}."
                        ),
                        "recovery": duplicate.as_dict(),
                    }
                    self.harness.had_tool_error = True
                    self.harness.logger.event("tool_result", step=step, action=action, args=args, result=result)
                    observation = {
                        "tool": action,
                        "result": result,
                        "instruction": "Choose a different action and continue the user's request, then use respond.",
                    }
                    self.harness.messages.append(
                        {"role": "user", "content": self.harness.user_content(json_text(observation))}
                    )
                    self._checkpoint_worker(job_id, step, "tool_result")
                    continue

                self.harness.tool_calls += 1
                try:
                    result = self.harness.dispatch(action, args)
                except HarnessError as exc:
                    result = {"ok": False, "error": str(exc)}
                if result.get("ok") is False:
                    self.harness.had_tool_error = True
                    detail = f"{action}: {result.get('error') or result.get('stderr') or 'tool returned a failure'}"
                    decision = self.harness.recovery.record_failure("tool_failure", detail)
                    if decision.stop:
                        self.harness.recovery_event("recovery_exhausted", decision, step=step)
                        self.add_assistant_message(
                            f"I stopped after one repair attempt because {decision.detail}. "
                            "Send the message again if you want a fresh attempt."
                        )
                        self.harness.logger.event("assistant_message", content=self.conversation[-1]["content"])
                        self._checkpoint_worker(job_id, step, "recovery_exhausted")
                        break
                    self.harness.recovery_event("recovery_retry", decision, step=step)
                self.harness.logger.event("tool_result", step=step, action=action, args=args, result=result)
                observation = {
                    "tool": action,
                    "result": result,
                    "instruction": (
                        "Continue the user's request, then use respond."
                        if result.get("ok") is not False
                        else recovery_instruction(action, result, interactive=True)
                    ),
                }
                self.harness.messages.append({"role": "user", "content": self.harness.user_content(json_text(observation))})
                self._checkpoint_worker(job_id, step, "tool_result")
            else:
                self.add_assistant_message("I hit the action limit for this message. Tell me whether you want me to continue.")
                self.harness.logger.event("interactive_step_limit", max_steps=max_steps)
        except Exception as exc:
            failure = str(exc)
            if self._worker_is_current(job_id):
                self.add_assistant_message(f"The local session hit an error: {exc}")
                self.harness.logger.event("harness_error", error=str(exc))
        finally:
            self._finish_worker(job_id, failure)


def choose_session_id() -> str:
    base = datetime.now().strftime("chat-%Y%m%d-%H%M%S")
    candidate = base
    suffix = 2
    while (SESSION_DIR / candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def restore_sessions() -> list[str]:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    for directory in sorted(SESSION_DIR.iterdir(), key=lambda item: item.name):
        if not directory.is_dir() or not RUN_ID_RE.fullmatch(directory.name):
            continue
        if not (directory / "session.json").is_file():
            continue
        try:
            session = InteractiveSession.from_disk(directory.name)
        except Exception:
            continue
        with SESSION_LOCK:
            SESSIONS[session.session_id] = session
        restored.append(session.session_id)
    return restored


def create_session(reasoning_level: Any = None, project_path: Any = None, skill_overrides: Any = None) -> InteractiveSession:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    try:
        session = InteractiveSession(
            choose_session_id(),
            reasoning_level=reasoning_level,
            project_path=project_path,
            skill_overrides=skill_overrides,
        )
    except HarnessError as exc:
        raise ApiError(str(exc), 413) from exc
    with SESSION_LOCK:
        SESSIONS[session.session_id] = session
    return session


def choose_run_id(requested: Any) -> str:
    if requested:
        run_id = validate_run_id(requested)
    else:
        run_id = datetime.now().strftime("run-ui-%Y%m%d-%H%M%S")
    candidate = run_id
    suffix = 2
    while (RUNS_DIR / candidate).exists():
        candidate = f"{run_id}-{suffix}"
        suffix += 1
    return candidate


def start_run(payload: dict[str, Any]) -> dict[str, Any]:
    task_text = payload.get("task_text")
    if not isinstance(task_text, str) or not task_text.strip():
        raise ApiError("task_text is required")
    if len(task_text) > 20000:
        raise ApiError("task is too long")
    run_id = choose_run_id(payload.get("run_id"))
    gated = bool(payload.get("gated", False))
    reasoning_level = payload.get("reasoning_level")
    if reasoning_level is not None:
        try:
            reasoning_level = normalize_reasoning_level(reasoning_level)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    project_path = normalize_project_path(payload.get("project_path"), RUNS_DIR / run_id / "project")
    skill_overrides = payload.get("skill_overrides")
    try:
        skill_selection = resolve_skill_selection(project_path, skill_overrides)
    except SkillError as exc:
        raise ApiError(str(exc)) from exc
    command = [
        sys.executable,
        str(HARNESS),
        "--task-text",
        task_text,
        "--config",
        str(CONFIG),
        "--run-id",
        run_id,
        "--project-dir",
        str(project_path),
    ]
    if not gated:
        command.append("--no-gates")
    if reasoning_level is not None:
        command.extend(["--reasoning-level", reasoning_level])
    if skill_overrides is not None:
        command.extend(["--skill-overrides-json", json.dumps(skill_overrides, ensure_ascii=False)])
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise ApiError(f"could not start harness: {exc}", 500) from exc
    with PROCESS_LOCK:
        PROCESSES[run_id] = process
        OUTPUTS[run_id] = read_run_output(run_id)
    threading.Thread(target=capture_process, args=(run_id, process), daemon=True).start()
    return {
        "run_id": run_id,
        "status": "running",
        "project": str(project_path),
        "skills": public_selection(skill_selection),
    }


def resume_run(run_id: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    state = run_state(run_id)
    if state["status"] != "interrupted":
        raise ApiError("only interrupted runs can be resumed", 409)
    with PROCESS_LOCK:
        existing = PROCESSES.get(run_id)
        if existing is not None and existing.poll() is None:
            raise ApiError("run is already active", 409)
    command = [sys.executable, str(HARNESS), "--resume-run", run_id]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise ApiError(f"could not resume harness: {exc}", 500) from exc
    with PROCESS_LOCK:
        PROCESSES[run_id] = process
        OUTPUTS[run_id] = read_run_output(run_id)
    threading.Thread(target=capture_process, args=(run_id, process), daemon=True).start()
    return {
        "run_id": run_id,
        "status": "running",
        "project": state.get("project", ""),
        "resumed": True,
    }


def stop_run(run_id: str) -> dict[str, Any]:
    run_id = validate_run_id(run_id)
    with PROCESS_LOCK:
        process = PROCESSES.get(run_id)
    if process is None or process.poll() is not None:
        state = run_state(run_id)
        if state["status"] == "running":
            raise ApiError("run is active but is not controlled by this server", 409)
        return {"run_id": run_id, "status": state["status"], "stopped": False}
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except OSError as exc:
        raise ApiError(f"could not stop harness: {exc}", 500) from exc
    return {"run_id": run_id, "status": "interrupted", "stopped": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentLab/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, value: Any, status: int = 200) -> None:
        data = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status)

    def send_static(self, filename: str) -> None:
        path = resolve_inside(UI_DIR, filename)
        if not path.is_file():
            raise ApiError("not found", 404)
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", STATIC_CACHE_CONTROL)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        try:
            if path in {"/", "/index.html"}:
                return self.send_static("index.html")
            if path in {"/app.js", "/styles.css", "/favicon.svg"}:
                return self.send_static(path.lstrip("/"))
            if path == "/api/health":
                return self.send_json({"status": "ok", "local_only": True})
            if path == "/api/reasoning-levels":
                return self.send_json({"levels": reasoning_options()})
            if path == "/api/skills":
                query = urllib.parse.parse_qs(parsed.query)
                project_path = query.get("project_path", [None])[0]
                return self.send_json(skill_catalog(project_path))
            if path == "/api/tasks":
                return self.send_json({"tasks": task_catalog()})
            if path == "/api/projects":
                return self.send_json({"projects": project_catalog()})
            if path == "/api/sessions":
                with SESSION_LOCK:
                    sessions = [session.state() for session in SESSIONS.values()]
                return self.send_json({"sessions": sorted(sessions, key=lambda item: item["session_id"], reverse=True)})
            if path == "/api/runs":
                return self.send_json({"runs": run_summaries()})
            if path.startswith("/api/sessions/"):
                remainder = path[len("/api/sessions/") :]
                pieces = remainder.split("/", 2)
                session_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                with SESSION_LOCK:
                    session = SESSIONS.get(session_id)
                if session is None:
                    raise ApiError("session not found", 404)
                if len(pieces) == 1:
                    return self.send_json(session.state())
                if pieces[1] == "file" and len(pieces) == 3:
                    project = session.project_dir
                    file_path = resolve_inside(project, urllib.parse.unquote(pieces[2]))
                    if not file_path.is_file():
                        raise ApiError("file not found", 404)
                    data = file_path.read_bytes()
                    if b"\x00" in data[:4096]:
                        return self.send_json({"path": file_path.relative_to(project).as_posix(), "binary": True, "bytes": len(data)})
                    return self.send_json({"path": file_path.relative_to(project).as_posix(), "content": data[:30000].decode("utf-8", errors="replace"), "truncated": len(data) > 30000})
            if path.startswith("/api/runs/"):
                remainder = path[len("/api/runs/") :]
                pieces = remainder.split("/", 2)
                run_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                if len(pieces) == 1:
                    return self.send_json(run_state(run_id))
                if pieces[1] == "file" and len(pieces) == 3:
                    project = run_project_dir(run_id)
                    file_path = resolve_inside(project, urllib.parse.unquote(pieces[2]))
                    if not file_path.is_file():
                        raise ApiError("file not found", 404)
                    data = file_path.read_bytes()
                    if b"\x00" in data[:4096]:
                        return self.send_json({"path": file_path.relative_to(project).as_posix(), "binary": True, "bytes": len(data)})
                    return self.send_json({"path": file_path.relative_to(project).as_posix(), "content": data[:30000].decode("utf-8", errors="replace"), "truncated": len(data) > 30000})
            raise ApiError("not found", 404)
        except ApiError as exc:
            self.send_error_json(str(exc), exc.status)
        except OSError as exc:
            self.send_error_json(str(exc), 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 100000:
                raise ApiError("request body is missing or too large")
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ApiError("request body must be a JSON object")
            if parsed.path == "/api/runs":
                return self.send_json(start_run(payload), 202)
            if parsed.path.startswith("/api/runs/"):
                remainder = parsed.path[len("/api/runs/") :]
                pieces = remainder.split("/", 2)
                if len(pieces) == 2 and pieces[1] == "stop":
                    run_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                    return self.send_json(stop_run(run_id), 202)
                if len(pieces) == 2 and pieces[1] == "resume":
                    run_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                    return self.send_json(resume_run(run_id), 202)
            if parsed.path == "/api/projects":
                return self.send_json(create_project(payload.get("name")), 201)
            if parsed.path == "/api/skills/discover":
                return self.send_json(discover_skills(payload))
            if parsed.path == "/api/sessions":
                session = create_session(
                    payload.get("reasoning_level"),
                    payload.get("project_path"),
                    payload.get("skill_overrides"),
                )
                return self.send_json(session.state(), 201)
            if parsed.path.startswith("/api/sessions/"):
                remainder = parsed.path[len("/api/sessions/") :]
                pieces = remainder.split("/", 2)
                if len(pieces) == 2 and pieces[1] == "settings":
                    session_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                    with SESSION_LOCK:
                        session = SESSIONS.get(session_id)
                    if session is None:
                        raise ApiError("session not found", 404)
                    session.set_reasoning_level(payload.get("reasoning_level"))
                    return self.send_json(session.state())
                if len(pieces) == 2 and pieces[1] == "retry":
                    session_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                    with SESSION_LOCK:
                        session = SESSIONS.get(session_id)
                    if session is None:
                        raise ApiError("session not found", 404)
                    session.retry()
                    return self.send_json(session.state(), 202)
                if len(pieces) == 2 and pieces[1] == "messages":
                    session_id = validate_run_id(urllib.parse.unquote(pieces[0]))
                    with SESSION_LOCK:
                        session = SESSIONS.get(session_id)
                    if session is None:
                        raise ApiError("session not found", 404)
                    content = payload.get("content")
                    if not isinstance(content, str):
                        raise ApiError("content is required")
                    session.send(content)
                    return self.send_json({"status": "thinking", "session_id": session_id}, 202)
            raise ApiError("not found", 404)
        except ApiError as exc:
            self.send_error_json(str(exc), exc.status)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.send_error_json(f"invalid JSON body: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Agent Lab web console")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        raise SystemExit("port must be between 1024 and 65535")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    restore_sessions()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Agent Lab UI listening at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
