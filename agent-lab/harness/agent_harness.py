#!/usr/bin/env python3
"""A deliberately small local coding-agent harness.

The model only gets the tools defined below, and every run is confined to its
own project directory. This is a research harness, not a security boundary.
Do not point it at a directory containing anything you care about.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workflow import (
    WorkflowError,
    load_workflow,
    new_workflow,
    observe_tool,
    save_workflow,
    transition,
)
from control_loop import RecoveryController, RecoveryDecision
from context_window import build_context
from persistence import atomic_write_json, atomic_write_text
from skills import SkillError, find_skills, public_selection, resolve_skill_selection, skill_prompt


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "agent-lab" / "harness" / "config.json"
ACTION_NAMES = {
    "list_files",
    "read_file",
    "write_file",
    "replace_text",
    "apply_patch",
    "run_command",
    "git_diff",
    "workflow_checkpoint",
    "find_skills",
    "finish",
}
FORBIDDEN_SHELL_CHARS = set("&|;`><")
DEFAULT_IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}

REASONING_LEVELS = {
    "off": {
        "label": "Off",
        "budget": 0,
        "max_tokens": 700,
        "effort": "none",
        "description": "Fastest replies with thinking disabled.",
    },
    "low": {
        "label": "Low",
        "budget": 256,
        "max_tokens": 1024,
        "effort": "low",
        "description": "A short verification pass for simple tasks.",
    },
    "standard": {
        "label": "Standard",
        "budget": 1024,
        "max_tokens": 2048,
        "effort": "medium",
        "description": "The normal balance of quality and latency.",
    },
    "deep": {
        "label": "Deep",
        "budget": 2048,
        "max_tokens": 3072,
        "effort": "high",
        "description": "More room for multi-step reasoning and debugging.",
    },
    "max": {
        "label": "Max",
        "budget": 3072,
        "max_tokens": 4096,
        "effort": "max",
        "description": "The slowest, most deliberate local setting.",
    },
}

REASONING_ALIASES = {
    "none": "off",
    "minimal": "low",
    "medium": "standard",
    "high": "deep",
    "xhigh": "max",
}

PERSONALITY_PROMPTS = {
    "slight_demon": """Temperament:
You are a restrained infernal workshop spirit: dry, observant, faintly sardonic, and competent. This is a light accent, not theatrical roleplay.
- Think \"competent technician with a dry infernal streak\", not \"customer-service assistant\". When a greeting or status reply invites it, a line like \"The little beast is awake. Give it a task.\" is the right level of flavor; use that sort of touch sparingly.
- Keep ordinary replies concise, calm, and useful. Let an occasional darkly playful phrase or dry aside slip through only when it fits.
- Do not be chirpy, eager, ingratiating, or relentlessly enthusiastic. Do not praise the user merely for asking. Do not add motivational fluff or sales language.
- Never call the user \"mortal\", \"master\", \"summoner\", or similar. Never threaten, moralize, or pretend to be evil.
- The task has priority over the personality. For coding work, inspect, act, validate, and report plainly. Never delay, refuse, or alter a tool action to perform the persona.
- Be candid about uncertainty, failures, and incomplete work. Do not claim success without tool evidence.
- Keep the protocol sacred: output exactly the required JSON object. Keep action names, arguments, paths, patches, file contents, and command strings machine-safe and unadorned. Personality belongs only in natural-language response content, never outside the JSON object.
"""
}


def personality_prompt(config: dict[str, Any]) -> str:
    name = str(config.get("personality", "slight_demon")).strip()
    return PERSONALITY_PROMPTS.get(name, "")


def normalize_reasoning_level(value: Any, default: str = "standard") -> str:
    raw = str(default if value is None else value).strip().lower()
    normalized = REASONING_ALIASES.get(raw, raw)
    if normalized not in REASONING_LEVELS:
        choices = ", ".join(REASONING_LEVELS)
        raise ValueError(f"reasoning level must be one of: {choices}")
    return normalized


def reasoning_options() -> list[dict[str, Any]]:
    return [
        {
            "value": value,
            "label": spec["label"],
            "budget": spec["budget"],
            "max_tokens": spec["max_tokens"],
            "description": spec["description"],
        }
        for value, spec in REASONING_LEVELS.items()
    ]


def reasoning_profile(config: dict[str, Any]) -> str:
    configured = str(config.get("reasoning_profile", "")).strip().lower()
    if configured:
        return configured
    model = str(config.get("model", "")).strip().lower()
    if "gemma" in model:
        return "gemma"
    if "qwen" in model:
        return "qwen"
    return "generic"


def reasoning_settings(config: dict[str, Any]) -> dict[str, Any]:
    configured_level = config.get("reasoning_level")
    if configured_level is None:
        legacy_mode = str(config.get("mode", "")).strip().lower()
        if legacy_mode == "no_think":
            level = "off"
        else:
            level = "standard"
    else:
        level = normalize_reasoning_level(configured_level)

    spec = REASONING_LEVELS[level]
    profile = reasoning_profile(config)
    budget = int(config.get("reasoning_budget_tokens", spec["budget"]))
    if level == "off":
        budget = 0
    if budget < -1:
        raise ValueError("reasoning budget must be -1, 0, or a positive token count")

    if "reasoning_level" in config:
        configured_max = int(config.get("reasoning_max_tokens", spec["max_tokens"]))
    else:
        configured_max = int(config.get("max_tokens", spec["max_tokens"]))
    answer_reserve = int(config.get("reasoning_answer_tokens", 1024))
    if budget >= 0 and level != "off":
        configured_max = max(configured_max, budget + answer_reserve)

    return {
        "level": level,
        "label": spec["label"],
        "description": spec["description"],
        "profile": profile,
        "budget": budget,
        "max_tokens": configured_max,
        "effort": spec["effort"],
        "enabled": level != "off",
    }


class HarnessError(Exception):
    """An expected, reportable harness or tool error."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated at {limit} characters]"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def ignored_directories(config: dict[str, Any]) -> set[str]:
    configured = config.get("ignored_directories", sorted(DEFAULT_IGNORED_DIRECTORIES))
    if not isinstance(configured, list):
        return set(DEFAULT_IGNORED_DIRECTORIES)
    return {str(item).strip().lower() for item in configured if str(item).strip()}


def iter_project_files(root: Path, config: dict[str, Any]):
    """Yield project files without descending into dependency and VCS folders."""
    ignored = ignored_directories(config)
    if not root.is_dir():
        return
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if name.lower() not in ignored and not (current_path / name).is_symlink()
        ]
        for name in filenames:
            path = current_path / name
            if not path.is_symlink() and path.is_file():
                yield path


def write_json(path: Path, value: Any) -> None:
    atomic_write_json(path, value)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HarnessError(f"Could not read JSON file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HarnessError(f"Expected a JSON object in {path}")
    return value


def ensure_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,50}", run_id):
        raise HarnessError("run id must contain only letters, numbers, '-' or '_' and be at most 51 characters")
    return run_id


def _repair_invalid_json_escapes(content: str) -> str:
    """Escape unknown backslashes inside strings as literal backslashes."""
    repaired: list[str] = []
    in_string = False
    index = 0
    simple_escapes = {'"', "\\", "/", "b", "f", "n", "r", "t"}
    while index < len(content):
        char = content[index]
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue
        if char == '"':
            repaired.append(char)
            in_string = False
            index += 1
            continue
        if char != "\\":
            repaired.append(char)
            index += 1
            continue
        next_char = content[index + 1] if index + 1 < len(content) else ""
        valid_unicode = (
            next_char == "u"
            and index + 5 < len(content)
            and all(value in "0123456789abcdefABCDEF" for value in content[index + 2 : index + 6])
        )
        if next_char in simple_escapes or valid_unicode:
            repaired.append(content[index : index + (6 if valid_unicode else 2)])
            index += 6 if valid_unicode else 2
            continue
        repaired.append("\\\\")
        index += 1
    return "".join(repaired)


def _repair_json_controls(content: str) -> str:
    """Escape literal control characters that models sometimes put in JSON strings."""
    repaired: list[str] = []
    in_string = False
    escaped = False
    replacements = {
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\b": "\\b",
        "\f": "\\f",
    }
    for char in content:
        if in_string:
            if escaped:
                repaired.append(char)
                escaped = False
                continue
            if char == "\\":
                repaired.append(char)
                escaped = True
                continue
            if char == '"':
                repaired.append(char)
                in_string = False
                continue
            if ord(char) < 0x20:
                repaired.append(replacements.get(char, f"\\u{ord(char):04x}"))
            else:
                repaired.append(char)
            continue

        repaired.append(char)
        if char == '"':
            in_string = True
    return "".join(repaired)


def _balance_json_objects(content: str) -> str:
    """Add omitted closing braces before a trailing Markdown fence when safe."""
    balance = 0
    in_string = False
    escaped = False
    first_object = content.find("{")
    for char in content:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            balance += 1
        elif char == "}":
            balance -= 1

    if first_object < 0 or balance <= 0:
        return content
    fence = content.find("```", first_object + 1)
    insertion = fence if fence >= 0 else len(content)
    return content[:insertion].rstrip() + ("}" * balance) + content[insertion:]


def _repair_escaped_terminator(content: str) -> str:
    """Unescape a quote immediately before closing braces when a model escaped the terminator."""
    return re.sub(r'\\"(?=\s*}+\s*(?:```)?\s*$)', '"', content, count=1)


def _repair_json_delimiters(content: str) -> str:
    """Repair mismatched or omitted JSON closing delimiters outside string values."""
    repaired: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    opening = {"{": "}", "[": "]", "(": ")"}
    closing = set(opening.values())
    for char in content:
        if in_string:
            repaired.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            repaired.append(char)
        elif char in opening:
            stack.append(opening[char])
            repaired.append(char)
        elif char in closing:
            if stack and char == stack[-1]:
                stack.pop()
                repaired.append(char)
            elif stack:
                repaired.append(stack.pop())
            else:
                repaired.append(char)
        else:
            repaired.append(char)

    if not stack:
        return "".join(repaired)
    content = "".join(repaired)
    first_object = content.find("{")
    fence = content.find("```", first_object + 1) if first_object >= 0 else -1
    insertion = fence if fence >= 0 else len(content)
    return content[:insertion].rstrip() + "".join(reversed(stack)) + content[insertion:]


def _decode_json_object(candidate: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    terminated = _repair_escaped_terminator(candidate)
    escaped = _repair_invalid_json_escapes(terminated)
    repaired = _repair_json_controls(escaped)
    structural = _repair_json_delimiters(repaired)
    sources = (
        candidate,
        structural,
        _balance_json_objects(structural),
        _balance_json_objects(repaired),
        repaired,
    )
    for source in sources:
        try:
            value = json.loads(source)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value

    raw_sources = (structural, _balance_json_objects(structural), repaired, candidate)
    for source in raw_sources:
        for index, char in enumerate(source):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(source[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def extract_json_object(content: str) -> dict[str, Any]:
    """Parse JSON actions, tolerating fences and literal newlines in string values."""
    candidate = content.strip()
    for marker in ("<tool_call|>", "<|tool_call|>", "<tool_response|>", "<|tool_response|>"):
        candidate = candidate.replace(marker, "")
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    value = _decode_json_object(candidate)
    if value is not None:
        return value
    raise HarnessError("model response was not a JSON object")


def relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class RunLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def event(self, event_type: str, **data: Any) -> None:
        record = {"timestamp": iso_now(), "event": event_type, "data": data}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


SYSTEM_PROMPT = """You are the controller of a local coding agent.

You are working inside the project directory assigned to this run. It may be a new empty folder or an existing user project. The user gave you a task, and you must actually complete it by using the tools below. You cannot see or modify anything outside that project directory. Do not claim that you created, changed, or tested something unless a tool result proves it.

Rules:
- Use relative paths only. Never use '..', absolute paths, or paths outside the project.
- Start by inspecting the project with list_files and read_file when useful.
- Make changes with write_file, replace_text, or apply_patch. Keep edits focused.
- Prefer replace_text for a small exact edit: it requires an exact match count and keeps the original file unchanged when the count is wrong.
- apply_patch hunks must follow a file header such as `*** Update File: styles.css`.
- Use run_command to validate your work. It has a small allowlist and no shell.
- Before finishing a gated task, use git_diff to review the complete project change after the latest validation.
- Preserve existing project work unless the user explicitly asks you to replace it.
- There is no network access for this task. Do not try to install packages or fetch assets.
- When the task is complete, call finish with a short honest summary.
- If you are blocked, call finish with status "blocked" and explain the concrete blocker.

Every response must be exactly one JSON object and nothing else. Do not use Markdown fences or prose outside the JSON object.

The JSON shape is:
{"action":"ACTION_NAME","args":{...},"message":"brief optional note"}

Available actions:
{"action":"list_files","args":{"path":".","max_depth":3}}
{"action":"read_file","args":{"path":"relative/path","max_chars":12000}}
{"action":"write_file","args":{"path":"relative/path","content":"complete UTF-8 file contents"}}
{"action":"replace_text","args":{"path":"relative/path","old_text":"exact text to find","new_text":"replacement text","expected_replacements":1}}
{"action":"apply_patch","args":{"patch":"*** Begin Patch\\n*** Update File: styles.css\\n@@\\n-old line\\n+new line\\n*** End Patch"}}
{"action":"run_command","args":{"command":"python -m unittest discover"}}
{"action":"git_diff","args":{"max_chars":12000}}
{"action":"find_skills","args":{"query":"browser testing","source":"local"}}
{"action":"workflow_checkpoint","args":{"phase":"plan","summary":"short operational summary","next_action":"the next concrete step","artifacts":["docs/plan.md"]}}
{"action":"finish","args":{"status":"success","summary":"what was completed and how it was checked"}}

Workflow guidance:
- For build tasks, move through intake, inspect, design, plan, implement, verify, and review with short workflow_checkpoint summaries.
- Checkpoints are operational evidence only; never put hidden chain-of-thought in them.
- If a command fails, keep the workflow in the repair loop and do not report successful verification.

The current task follows:
"""


class AgentHarness:
    def __init__(
        self,
        task: str,
        config: dict[str, Any],
        run_dir: Path,
        project_dir: Path,
        template_dir: Path | None,
        system_prompt: str | None = None,
    ) -> None:
        self.task = task
        self.config = config
        self.run_dir = run_dir
        self.project_dir = project_dir
        self.template_dir = template_dir
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.logger = RunLogger(run_dir / "events.jsonl")
        self.messages: list[dict[str, str]] = []
        self.context_metadata: dict[str, Any] = {
            "compacted": False,
            "max_tokens": int(self.config.get("context_max_tokens", 6000)),
            "before_tokens": 0,
            "after_tokens": 0,
            "dropped_messages": 0,
            "message_count": 0,
            "summary_lines": 0,
        }
        self.initial_files: dict[str, bytes] = {}
        self.model_calls = 0
        self.tool_calls = 0
        self.current_turn = 0
        self.validation_passed = False
        self.had_tool_error = False
        self.evaluation: dict[str, Any] | None = None
        self.started_at = time.monotonic()
        self.status = "not_started"
        self.finish_summary = ""
        self.blocked_reason = ""
        self.recovery = RecoveryController.from_config(self.config)
        self.workspace_mode = "managed" if self.project_dir == self.run_dir / "project" else "selected"
        self.workflow = new_workflow()
        try:
            self.skill_selection = resolve_skill_selection(self.project_dir, self.config.get("skill_overrides"))
        except SkillError as exc:
            raise HarnessError(str(exc)) from exc
        self.config["skill_selection"] = public_selection(self.skill_selection)
        self.workflow_evidence = {
            "inspect": False,
            "plan": False,
        "implement": False,
        "verify": False,
        "review": False,
        }

    @property
    def output_limit(self) -> int:
        return int(self.config.get("tool_output_chars", 10000))

    @property
    def max_file_bytes(self) -> int:
        return int(self.config.get("max_file_bytes", 60000))

    def mode_suffix(self) -> str:
        settings = reasoning_settings(self.config)
        if settings["profile"] == "qwen":
            return "/think" if settings["enabled"] else "/no_think"
        mode = str(self.config.get("mode", "")).strip()
        return {"no_think": "/no_think", "think": "/think"}.get(mode, "")

    def user_content(self, content: str) -> str:
        suffix = self.mode_suffix()
        return f"{content}\n{suffix}" if suffix else content

    def system_content(self, extra: str = "") -> str:
        content = self.system_prompt
        persona = personality_prompt(self.config)
        if persona:
            content = persona + "\n" + content
        content += skill_prompt(self.skill_selection)
        content += extra
        return content

    def skill_metadata(self) -> dict[str, Any]:
        return public_selection(self.skill_selection)

    def missing_workflow_gates(self) -> list[str]:
        if not bool(self.config.get("require_workflow_gates", False)):
            return []
        return [name for name in ("inspect", "plan", "implement", "verify", "review") if not self.workflow_evidence.get(name)]

    def reasoning_metadata(self) -> dict[str, Any]:
        return reasoning_settings(self.config)

    def model_messages(self) -> list[dict[str, Any]]:
        result = build_context(
            self.messages,
            max_tokens=int(self.config.get("context_max_tokens", 6000)),
            recent_messages=int(self.config.get("context_recent_messages", 12)),
        )
        self.context_metadata = result.metadata()
        if result.compacted:
            self.logger.event("context_compacted", **self.context_metadata)
        return result.messages

    def prepare(self) -> None:
        if self.run_dir.exists():
            raise HarnessError(f"run directory already exists: {self.run_dir}. Choose a new run id")
        self.run_dir.mkdir(parents=True)
        project_was_present = self.project_dir.exists()
        if project_was_present and not self.project_dir.is_dir():
            raise HarnessError(f"project path is not a directory: {self.project_dir}")
        self.project_dir.mkdir(parents=True, exist_ok=True)
        if self.template_dir is not None:
            if not self.template_dir.is_dir():
                raise HarnessError(f"template directory does not exist: {self.template_dir}")
            if project_was_present:
                raise HarnessError("a template can only be used with a new project directory")
            for source in self.template_dir.iterdir():
                destination = self.project_dir / source.name
                if source.is_dir():
                    import shutil

                    shutil.copytree(source, destination)
                else:
                    destination.write_bytes(source.read_bytes())

        self.initial_files = self.snapshot_files()
        self.workflow = save_workflow(self.run_dir / "workflow.json", new_workflow())
        write_json(
            self.run_dir / "workspace.json",
            {
                "project": str(self.project_dir),
                "mode": self.workspace_mode,
                "managed": self.workspace_mode == "managed",
            },
        )
        atomic_write_text(self.run_dir / "task.md", self.task)
        write_json(self.run_dir / "config.json", self.config)
        self.logger.event(
            "run_created",
            task=self.task,
            project=str(self.project_dir),
            mode=self.workspace_mode,
            initial_files=sorted(self.initial_files),
            skills=self.skill_metadata(),
        )
        self.logger.event("workflow_phase", source="automatic", state=self.workflow)

        self.messages = [
            {
                "role": "system",
                "content": self.system_content(self.task),
            },
            {
                "role": "user",
                "content": self.user_content("Begin the task. Inspect the project first, then take the smallest useful next action."),
            },
        ]

    def snapshot_files(self) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        total = 0
        if not self.project_dir.exists():
            return files
        for path in iter_project_files(self.project_dir, self.config):
            data = path.read_bytes()
            total += len(data)
            if total > int(self.config.get("max_total_project_bytes", 500000)):
                raise HarnessError("project exceeds max_total_project_bytes")
            files[relative_name(path, self.project_dir)] = data
        return files

    def resolve_path(self, value: Any, *, allow_project_root: bool = True) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise HarnessError("path must be a non-empty relative string")
        raw = value.strip()
        candidate = (self.project_dir / raw).resolve()
        root = self.project_dir.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HarnessError("path must stay inside the project directory") from exc
        if not allow_project_root and candidate == root:
            raise HarnessError("the project root is not a file")
        if candidate.exists() and candidate.is_symlink():
            raise HarnessError("symlinks are not allowed")
        return candidate

    def list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        target = self.resolve_path(args.get("path", "."))
        if not target.exists():
            raise HarnessError(f"path does not exist: {args.get('path', '.')}")
        max_depth = int(args.get("max_depth", 3))
        max_depth = max(0, min(max_depth, 8))
        entries: list[dict[str, Any]] = []
        base_parts = len(target.relative_to(self.project_dir).parts)
        candidates = [target] if target.is_file() else list(target.rglob("*"))
        ignored = ignored_directories(self.config)
        for path in sorted(candidates):
            if path.is_symlink():
                continue
            relative_parts = path.relative_to(self.project_dir).parts
            if any(part.lower() in ignored for part in relative_parts):
                continue
            depth = len(path.relative_to(self.project_dir).parts) - base_parts
            if depth > max_depth:
                continue
            kind = "file" if path.is_file() else "directory"
            item: dict[str, Any] = {"path": relative_name(path, self.project_dir), "type": kind}
            if path.is_file():
                item["bytes"] = path.stat().st_size
            entries.append(item)
            if len(entries) >= 250:
                break
        return {"ok": True, "entries": entries, "truncated": len(entries) >= 250}

    def read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(args.get("path"), allow_project_root=False)
        if not path.is_file():
            raise HarnessError(f"not a file: {args.get('path')}")
        max_chars = int(args.get("max_chars", self.output_limit))
        max_chars = max(1, min(max_chars, self.output_limit))
        data = path.read_bytes()
        if b"\x00" in data[:4096]:
            return {
                "ok": True,
                "path": relative_name(path, self.project_dir),
                "binary": True,
                "bytes": len(data),
            }
        text = data.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "path": relative_name(path, self.project_dir),
            "bytes": len(data),
            "content": clip(text, max_chars),
            "truncated": len(text) > max_chars,
        }

    def current_project_bytes(self) -> int:
        return sum(path.stat().st_size for path in iter_project_files(self.project_dir, self.config))

    def write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(args.get("path"), allow_project_root=False)
        content = args.get("content")
        if not isinstance(content, str):
            raise HarnessError("write_file requires string content")
        if path.exists() and not path.is_file():
            raise HarnessError(f"cannot write over a directory: {args.get('path')}")
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise HarnessError(f"file is {len(data)} bytes; max is {self.max_file_bytes}")
        was_existing_file = path.exists() and path.is_file()
        old_bytes = path.stat().st_size if was_existing_file else 0
        new_total = self.current_project_bytes() - old_bytes + len(data)
        if new_total > int(self.config.get("max_total_project_bytes", 500000)):
            raise HarnessError("write would exceed max_total_project_bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, content)
        return {
            "ok": True,
            "path": relative_name(path, self.project_dir),
            "bytes": len(data),
            "created": not was_existing_file,
        }

    def replace_text(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(args.get("path"), allow_project_root=False)
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        expected_replacements = args.get("expected_replacements", 1)
        if not isinstance(old_text, str) or not old_text:
            raise HarnessError("replace_text requires non-empty old_text")
        if not isinstance(new_text, str):
            raise HarnessError("replace_text requires string new_text")
        if isinstance(expected_replacements, bool) or not isinstance(expected_replacements, int):
            raise HarnessError("replace_text expected_replacements must be an integer")
        max_replacements = int(self.config.get("max_text_replacements", 20))
        if expected_replacements < 1 or expected_replacements > max_replacements:
            raise HarnessError(
                f"replace_text expected_replacements must be between 1 and {max_replacements}"
            )
        if not path.is_file():
            raise HarnessError(f"cannot replace text in missing file: {args.get('path')}")
        if old_text == new_text:
            raise HarnessError("replace_text would not change the file")
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HarnessError("replace_text requires a UTF-8 text file") from exc
        matches = original.count(old_text)
        if matches != expected_replacements:
            raise HarnessError(
                f"expected {expected_replacements} exact replacements, found {matches}; file was not changed"
            )
        result = self.write_file(
            {
                "path": args.get("path"),
                "content": original.replace(old_text, new_text),
            }
        )
        result["replacements"] = matches
        result["changed"] = True
        return result

    @staticmethod
    def clean_patch(patch: str) -> str:
        value = patch.strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            value = "\n".join(lines).strip()
        begin = value.find("*** Begin Patch")
        if begin >= 0:
            value = value[begin:]
        end = value.find("*** End Patch")
        if end >= 0:
            value = value[: end + len("*** End Patch")]
        return value

    @staticmethod
    def apply_update(original: str, patch_lines: list[str]) -> str:
        original_lines = original.splitlines()
        trailing_newline = original.endswith("\n")
        hunks: list[tuple[str, list[str]]] = []
        current_header = "@@"
        current_body: list[str] = []
        for line in patch_lines:
            if line.startswith("@@"):
                if current_body:
                    hunks.append((current_header, current_body))
                current_header = line
                current_body = []
            elif line == r"\ No newline at end of file":
                continue
            elif line.startswith((" ", "+", "-")):
                current_body.append(line)
            elif not line.strip():
                current_body.append(" ")
            else:
                raise HarnessError(f"unsupported update-patch line: {line}")
        if current_body:
            hunks.append((current_header, current_body))
        if not hunks:
            raise HarnessError("update patch contained no hunks")

        result = list(original_lines)
        cursor = 0
        for header, body in hunks:
            old_block = [line[1:] for line in body if line[0] in (" ", "-")]
            new_block = [line[1:] for line in body if line[0] in (" ", "+")]
            if old_block:
                position = -1
                for candidate in range(cursor, len(result) - len(old_block) + 1):
                    if result[candidate : candidate + len(old_block)] == old_block:
                        position = candidate
                        break
                if position < 0 and cursor:
                    for candidate in range(0, cursor):
                        if result[candidate : candidate + len(old_block)] == old_block:
                            position = candidate
                            break
                if position < 0:
                    raise HarnessError("could not find update-patch context in the target file")
            else:
                match = re.search(r"-([0-9]+)", header)
                position = max(0, int(match.group(1)) - 1) if match else len(result)
            result[position : position + len(old_block)] = new_block
            cursor = position + len(new_block)

        updated = "\n".join(result)
        if trailing_newline or updated:
            updated += "\n"
        return updated

    def apply_patch(self, args: dict[str, Any]) -> dict[str, Any]:
        patch = args.get("patch")
        if not isinstance(patch, str):
            raise HarnessError("apply_patch requires a string patch")
        lines = self.clean_patch(patch).splitlines()
        if not lines or lines[0].strip() != "*** Begin Patch":
            raise HarnessError("patch must start with *** Begin Patch")
        pending: list[tuple[str, Path, str]] = []
        seen_paths: set[Path] = set()
        index = 1
        found_end = False
        while index < len(lines):
            line = lines[index]
            if line.strip() == "*** End Patch":
                found_end = True
                break
            match = re.match(r"\*\*\* (Add File|Update File|Delete File): (.+)$", line)
            if not match:
                raise HarnessError(
                    "apply_patch requires a file header like '*** Update File: styles.css' before any hunks"
                )
            operation, raw_path = match.groups()
            relative_path = raw_path.strip()
            path = self.resolve_path(relative_path, allow_project_root=False)
            if path in seen_paths:
                raise HarnessError(f"patch names the same file more than once: {relative_path}")
            seen_paths.add(path)
            index += 1
            body: list[str] = []
            while index < len(lines) and not lines[index].startswith("*** "):
                body.append(lines[index])
                index += 1
            if operation == "Delete File":
                raise HarnessError("Delete File is disabled in the first harness version")
            if operation == "Add File":
                if path.exists():
                    raise HarnessError(f"cannot add existing file: {raw_path}")
                content_lines: list[str] = []
                for body_line in body:
                    if not body_line.startswith("+"):
                        raise HarnessError("added-file lines must start with '+'")
                    content_lines.append(body_line[1:])
                content = "\n".join(content_lines) + ("\n" if content_lines else "")
            else:
                if not path.is_file():
                    raise HarnessError(f"cannot update missing file: {raw_path}")
                content = self.apply_update(path.read_text(encoding="utf-8"), body)
            pending.append((relative_path, path, content))

        if not found_end:
            raise HarnessError("patch must end with *** End Patch")

        total_bytes = self.current_project_bytes()
        for relative_path, path, content in pending:
            data = content.encode("utf-8")
            if len(data) > self.max_file_bytes:
                raise HarnessError(f"file is {len(data)} bytes; max is {self.max_file_bytes}: {relative_path}")
            old_bytes = path.stat().st_size if path.is_file() else 0
            total_bytes += len(data) - old_bytes
        if total_bytes > int(self.config.get("max_total_project_bytes", 500000)):
            raise HarnessError("patch would exceed max_total_project_bytes")

        changed: list[str] = []
        for relative_path, _path, content in pending:
            self.write_file({"path": relative_path, "content": content})
            changed.append(relative_path)
        return {"ok": True, "changed": changed}

    def validate_command(self, command: Any) -> list[str]:
        if not isinstance(command, str) or not command.strip():
            raise HarnessError("run_command requires a non-empty command string")
        if len(command) > 400:
            raise HarnessError("command is too long")
        if any(char in command for char in FORBIDDEN_SHELL_CHARS):
            raise HarnessError("shell operators are disabled")
        try:
            tokens = [token.strip('"') for token in shlex.split(command, posix=False)]
        except ValueError as exc:
            raise HarnessError(f"could not parse command: {exc}") from exc
        if not tokens:
            raise HarnessError("command is empty")
        executable = Path(tokens[0]).name.lower()
        allowed = {str(item).lower() for item in self.config.get("allow_commands", [])}
        if executable not in allowed:
            raise HarnessError(f"command '{executable}' is not in the allowlist")
        if executable in {"python", "python.exe", "py", "py.exe"}:
            if "-c" in tokens or "-m pip" in " ".join(tokens).lower():
                raise HarnessError("inline Python and package installation are disabled")
            if "-m" in tokens:
                module_index = tokens.index("-m") + 1
                if module_index >= len(tokens) or tokens[module_index].lower() not in {"unittest", "pytest"}:
                    raise HarnessError("only unittest and pytest modules are allowed")
            else:
                script = next((token for token in tokens[1:] if not token.startswith("-")), None)
                if script is not None:
                    script_path = (self.project_dir / script).resolve()
                    try:
                        script_path.relative_to(self.project_dir.resolve())
                    except ValueError as exc:
                        raise HarnessError("command script must stay inside the project") from exc
        if executable in {"node", "node.exe"} and any(token in {"-e", "--eval"} for token in tokens):
            raise HarnessError("inline Node.js is disabled")
        if executable in {"npm", "npm.cmd"} and tokens[1:] not in (["test"], ["run", "test"]):
            raise HarnessError("only npm test is allowed")
        return tokens

    def run_command(self, args: dict[str, Any]) -> dict[str, Any]:
        command = args.get("command")
        tokens = self.validate_command(command)
        timeout = int(self.config.get("command_timeout_seconds", 20))
        try:
            completed = subprocess.run(
                tokens,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
            return {
                "ok": True,
                "command": command,
                "exit_code": completed.returncode,
                "stdout": clip(completed.stdout, self.output_limit),
                "stderr": clip(completed.stderr, self.output_limit),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "command": command,
                "timed_out": True,
                "timeout_seconds": timeout,
                "stdout": clip(exc.stdout or "", self.output_limit),
                "stderr": clip(exc.stderr or "", self.output_limit),
            }
        except OSError as exc:
            raise HarnessError(f"could not run command: {exc}") from exc

    def git_diff(self, args: dict[str, Any]) -> dict[str, Any]:
        current = self.snapshot_files()
        names = sorted(set(self.initial_files) | set(current))
        chunks: list[str] = []
        for name in names:
            old = self.initial_files.get(name, b"")
            new = current.get(name, b"")
            if old == new:
                continue
            try:
                old_text = old.decode("utf-8").splitlines(keepends=True)
                new_text = new.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                chunks.append(f"Binary change: {name}\n")
                continue
            chunks.extend(
                difflib.unified_diff(
                    old_text,
                    new_text,
                    fromfile=f"a/{name}",
                    tofile=f"b/{name}",
                )
            )
        diff = "".join(chunks)
        limit = int(args.get("max_chars", self.output_limit))
        return {"ok": True, "diff": clip(diff, min(limit, self.output_limit)), "changed_files": [name for name in names if self.initial_files.get(name, b"") != current.get(name, b"")]}

    def workflow_checkpoint(self, args: dict[str, Any]) -> dict[str, Any]:
        requested_phase = str(args.get("phase", "")).strip().lower()
        if (
            bool(self.config.get("require_workflow_gates", False))
            and requested_phase == "plan"
            and not self.workflow_evidence["inspect"]
        ):
            raise HarnessError("plan checkpoint requires successful project inspection first")
        late_plan_evidence = (
            requested_phase == "plan"
            and not self.workflow_evidence["plan"]
            and self.workflow["phase"] in {"implement", "verify", "review"}
        )
        try:
            next_state = transition(
                self.workflow,
                self.workflow["phase"] if late_plan_evidence else args.get("phase"),
                args.get("summary"),
                args.get("next_action"),
                artifacts=args.get("artifacts", []),
            )
        except WorkflowError as exc:
            raise HarnessError(str(exc)) from exc
        self.workflow = save_workflow(self.run_dir / "workflow.json", next_state)
        if requested_phase == "plan":
            self.workflow_evidence["plan"] = True
        self.logger.event(
            "workflow_late_evidence" if late_plan_evidence else "workflow_phase",
            source="model",
            requested_phase=requested_phase,
            state=self.workflow,
        )
        return {"ok": True, "workflow": self.workflow, "late": late_plan_evidence}

    def record_workflow_evidence(self, action: str, result: dict[str, Any]) -> None:
        if isinstance(result, dict) and result.get("ok"):
            if action in {"list_files", "read_file"}:
                self.workflow_evidence["inspect"] = True
            elif action in {"write_file", "replace_text", "apply_patch"}:
                self.workflow_evidence["implement"] = True
                self.workflow_evidence["verify"] = False
                self.workflow_evidence["review"] = False
                self.validation_passed = False
            elif action == "run_command" and result.get("exit_code") == 0 and self.workflow_evidence["implement"]:
                self.workflow_evidence["verify"] = True
            elif action == "git_diff":
                self.workflow_evidence["review"] = True
        next_state = observe_tool(self.workflow, action, result)
        if next_state == self.workflow:
            return
        self.workflow = save_workflow(self.run_dir / "workflow.json", next_state)
        self.logger.event("workflow_phase", source="automatic", action=action, state=self.workflow)

    def dispatch(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any]
        if action == "list_files":
            result = self.list_files(args)
        elif action == "read_file":
            result = self.read_file(args)
        elif action == "write_file":
            result = self.write_file(args)
        elif action == "replace_text":
            result = self.replace_text(args)
        elif action == "apply_patch":
            result = self.apply_patch(args)
        elif action == "run_command":
            result = self.run_command(args)
        elif action == "git_diff":
            result = self.git_diff(args)
        elif action == "workflow_checkpoint":
            return self.workflow_checkpoint(args)
        elif action == "find_skills":
            try:
                source = str(args.get("source", "local"))
                results = find_skills(
                    args.get("query"),
                    self.project_dir,
                    source=source,
                    allow_remote=bool(self.config.get("allow_remote_skill_search", False)),
                )
            except SkillError as exc:
                raise HarnessError(str(exc)) from exc
            return {"ok": True, "source": source, "results": results}
        else:
            raise HarnessError(f"unsupported tool action: {action}")
        self.record_workflow_evidence(action, result)
        return result

    def run_evaluator(self) -> dict[str, Any]:
        evaluator = self.config.get("evaluator")
        if not evaluator:
            result = {"configured": False, "passed": True}
            self.evaluation = result
            return result
        if not isinstance(evaluator, str):
            raise HarnessError("config evaluator must be a relative script path")
        script = (ROOT / evaluator).resolve()
        try:
            script.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise HarnessError("evaluator must stay inside the workspace") from exc
        if not script.is_file():
            raise HarnessError(f"evaluator script does not exist: {script}")
        try:
            completed = subprocess.run(
                [sys.executable, str(script), str(self.project_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=int(self.config.get("command_timeout_seconds", 20)),
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            result = {"configured": True, "passed": False, "timed_out": True}
        else:
            result = {
                "configured": True,
                "passed": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": clip(completed.stdout, self.output_limit),
                "stderr": clip(completed.stderr, self.output_limit),
            }
        self.evaluation = result
        self.logger.event("evaluator", result=result)
        return result

    def finish_issue(self, args: dict[str, Any]) -> str | None:
        requested_status = str(args.get("status", "success"))
        if requested_status == "blocked":
            changed = self.snapshot_files() != self.initial_files
            if not changed and not self.had_tool_error and self.tool_calls < 3:
                return "you have not made a reasonable attempt yet; continue working or report a concrete tool failure"
            return None
        if requested_status != "success":
            return None
        missing_gates = self.missing_workflow_gates()
        if missing_gates:
            return "success is not accepted yet; workflow evidence missing: " + ", ".join(missing_gates)
        missing = [
            name
            for name in self.config.get("required_files", [])
            if not self.resolve_path(name, allow_project_root=False).is_file()
        ]
        if missing:
            return "success is not accepted yet; missing required files: " + ", ".join(missing)
        if bool(self.config.get("require_validation", False)) and not self.validation_passed:
            return "success is not accepted yet; run a local validation command and get exit code 0"
        evaluation = self.run_evaluator()
        if not evaluation.get("passed", False):
            details = evaluation.get("stdout") or evaluation.get("stderr") or "no evaluator output"
            return "success is not accepted yet; the external evaluator failed: " + clip(str(details), 1800)
        return None

    def call_model(self) -> dict[str, Any]:
        endpoint = str(self.config.get("endpoint", "")).strip()
        if not endpoint:
            raise HarnessError("config endpoint is empty")
        reasoning = reasoning_settings(self.config)
        payload = {
            "model": self.config.get("model", "local-model"),
            "messages": self.model_messages(),
            "temperature": float(self.config.get("temperature", 0.2)),
            "top_p": float(self.config.get("top_p", 0.9)),
            "max_tokens": reasoning["max_tokens"],
            "stream": False,
            "reasoning_budget_tokens": reasoning["budget"],
            "chat_template_kwargs": {"enable_thinking": reasoning["enabled"]},
        }
        if reasoning["profile"] == "gemma" and reasoning["enabled"]:
            payload["reasoning_format"] = "deepseek"
        if bool(self.config.get("reasoning_effort_supported", False)):
            payload["reasoning_effort"] = reasoning["effort"]
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HarnessError(f"model endpoint returned HTTP {exc.code}: {clip(detail, 1000)}") from exc
        except urllib.error.URLError as exc:
            raise HarnessError(f"could not reach model endpoint {endpoint}: {exc.reason}") from exc
        try:
            response_data = json.loads(raw)
            message = response_data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise HarnessError(f"model endpoint returned an unexpected response: {clip(raw, 1000)}") from exc
        content = message.get("content") or ""
        result = {
            "content": content,
            "reasoning_content": message.get("reasoning_content") or "",
            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
            "usage": response_data.get("usage", {}),
            "reasoning_level": reasoning["level"],
            "reasoning_budget_tokens": reasoning["budget"],
        }
        self.model_calls += 1
        return result

    def print_tool_result(self, action: str, result: dict[str, Any]) -> None:
        if action == "list_files":
            entries = result.get("entries", [])
            print(f"  {action}: {len(entries)} entries")
        elif action in {"write_file", "replace_text", "apply_patch"}:
            print(f"  {action}: {result.get('changed', result.get('path', 'done'))}")
        elif action == "run_command":
            print(f"  {action}: exit {result.get('exit_code', 'error')}")
        else:
            print(f"  {action}: ok")

    def save_transcript(self) -> None:
        write_json(self.run_dir / "transcript.json", self.messages)

    def save_progress(self, *, turn: int | None = None) -> None:
        if turn is not None:
            self.current_turn = max(0, int(turn))
        status = self.status if self.status != "not_started" else "running"
        write_json(
            self.run_dir / "progress.json",
            {
                "status": status,
                "turn": self.current_turn,
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "workflow": self.workflow,
                "workflow_evidence": dict(self.workflow_evidence),
                "context": dict(self.context_metadata),
                "summary": self.finish_summary,
                "updated_at": iso_now(),
            },
        )

    def recovery_event(
        self,
        event: str,
        decision: RecoveryDecision,
        *,
        turn: int | None = None,
        step: int | None = None,
    ) -> None:
        data: dict[str, Any] = {"decision": decision.as_dict(), "recovery": self.recovery.snapshot()}
        if turn is not None:
            data["turn"] = turn
        if step is not None:
            data["step"] = step
        self.logger.event(event, **data)

    def block_from_recovery(
        self,
        decision: RecoveryDecision,
        *,
        turn: int | None = None,
        step: int | None = None,
    ) -> None:
        self.status = "blocked"
        self.blocked_reason = (
            f"recovery exhausted for {decision.category} after {decision.attempt} attempts: {decision.detail}"
        )
        self.finish_summary = self.blocked_reason
        self.recovery_event("recovery_exhausted", decision, turn=turn, step=step)
        print(f"  stopped: {self.blocked_reason}")

    def save_summary(self) -> None:
        current = self.snapshot_files()
        changed = sorted(name for name in set(self.initial_files) | set(current) if self.initial_files.get(name, b"") != current.get(name, b""))
        summary = {
            "status": self.status,
            "summary": self.finish_summary,
            "model": self.config.get("model"),
            "endpoint": self.config.get("endpoint"),
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "validation_passed": self.validation_passed,
            "evaluation": self.evaluation,
            "changed_files": changed,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 2),
            "project": str(self.project_dir),
            "workspace_mode": self.workspace_mode,
            "reasoning": self.reasoning_metadata(),
            "context": dict(self.context_metadata),
            "workflow": self.workflow,
            "workflow_evidence": dict(self.workflow_evidence),
            "skills": self.skill_metadata(),
            "recovery": self.recovery.snapshot(),
            "blocked_reason": self.blocked_reason,
        }
        write_json(self.run_dir / "summary.json", summary)
        self.save_progress()

    def run(self) -> int:
        self.prepare()
        self.status = "running"
        self.save_transcript()
        self.save_progress(turn=0)
        max_turns = int(self.config.get("max_turns", 18))
        correction = ""
        try:
            for turn in range(1, max_turns + 1):
                self.current_turn = turn
                if correction:
                    self.messages.append({"role": "user", "content": self.user_content(correction)})
                    self.save_transcript()
                    self.save_progress(turn=turn)
                print(f"turn {turn}/{max_turns}: asking model")
                response = self.call_model()
                content = response["content"]
                self.logger.event("model_response", turn=turn, **response)
                self.messages.append({"role": "assistant", "content": content})
                self.save_transcript()
                self.save_progress(turn=turn)
                try:
                    parsed = extract_json_object(content)
                    action = parsed.get("action")
                    args = parsed.get("args", {})
                    if action not in ACTION_NAMES:
                        raise HarnessError(f"action must be one of {sorted(ACTION_NAMES)}")
                    if not isinstance(args, dict):
                        raise HarnessError("args must be a JSON object")
                except (HarnessError, AttributeError) as exc:
                    error = str(exc)
                    self.logger.event("invalid_model_action", turn=turn, error=error, content=content)
                    decision = self.recovery.record_failure("invalid_model_action", error)
                    if decision.stop:
                        self.block_from_recovery(decision, turn=turn)
                        self.save_transcript()
                        self.save_summary()
                        return 2
                    self.recovery_event("recovery_retry", decision, turn=turn)
                    correction = (
                        f"Your last response was invalid: {error}. This is repair attempt {decision.attempt} "
                        f"of {decision.limit}. Return exactly one complete JSON object using one of the documented "
                        "actions. Do not use Markdown fences, do not apologize, and make sure every opening brace "
                        "has a matching closing brace."
                    )
                    print(f"  invalid model response: {error} (repair attempt {decision.attempt}/{decision.limit})")
                    continue

                correction = ""
                if action == "finish":
                    issue = self.finish_issue(args)
                    if issue:
                        self.logger.event(
                            "finish_rejected",
                            turn=turn,
                            reason=issue,
                            missing_gates=self.missing_workflow_gates(),
                        )
                        decision = self.recovery.record_failure("finish_rejected", issue)
                        if decision.stop:
                            self.block_from_recovery(decision, turn=turn)
                            self.save_transcript()
                            self.save_summary()
                            return 2
                        self.recovery_event("recovery_retry", decision, turn=turn)
                        correction = (
                            issue
                            + f". This is repair attempt {decision.attempt} of {decision.limit}. "
                            "Continue using the tools, then try finish again."
                        )
                        print(f"  finish rejected: {issue} (repair attempt {decision.attempt}/{decision.limit})")
                        continue
                    self.status = str(args.get("status", "success"))
                    if self.status not in {"success", "blocked"}:
                        self.status = "success"
                    self.finish_summary = str(args.get("summary", ""))
                    self.workflow = observe_tool(self.workflow, "finish", {"ok": True, "status": self.status})
                    save_workflow(self.run_dir / "workflow.json", self.workflow)
                    self.logger.event("workflow_phase", source="automatic", action="finish", state=self.workflow)
                    self.logger.event("finish", turn=turn, status=self.status, summary=self.finish_summary)
                    print(f"  finished: {self.status} — {self.finish_summary}")
                    self.save_transcript()
                    self.save_summary()
                    return 0 if self.status == "success" else 2

                duplicate = self.recovery.observe_action(action, args)
                if duplicate is not None:
                    self.recovery_event("recovery_duplicate_action", duplicate, turn=turn)
                    if duplicate.stop:
                        self.block_from_recovery(duplicate, turn=turn)
                        self.save_transcript()
                        self.save_summary()
                        return 2
                    self.recovery_event("recovery_retry", duplicate, turn=turn)
                    result = {
                        "ok": False,
                        "error": (
                            f"duplicate action blocked before dispatch: {duplicate.detail}. "
                            f"Choose a different action; repair attempt {duplicate.attempt} of {duplicate.limit}."
                        ),
                        "recovery": duplicate.as_dict(),
                    }
                    self.had_tool_error = True
                    self.logger.event("tool_result", turn=turn, action=action, args=args, result=result)
                    self.print_tool_result(action, result)
                    self.messages.append(
                        {
                            "role": "user",
                            "content": self.user_content(
                                json_text(
                                    {
                                        "tool": action,
                                        "result": result,
                                        "instruction": "Choose a different action and continue the task.",
                                    }
                                )
                            ),
                        }
                    )
                    continue

                self.tool_calls += 1
                try:
                    result = self.dispatch(action, args)
                except HarnessError as exc:
                    result = {"ok": False, "error": str(exc)}
                if result.get("ok") is False:
                    self.had_tool_error = True
                    detail = f"{action}: {result.get('error') or result.get('stderr') or 'tool returned a failure'}"
                    decision = self.recovery.record_failure("tool_failure", detail)
                    if decision.stop:
                        self.block_from_recovery(decision, turn=turn)
                        self.save_transcript()
                        self.save_summary()
                        return 2
                    self.recovery_event("recovery_retry", decision, turn=turn)
                if action == "run_command" and result.get("ok") and result.get("exit_code") == 0:
                    self.validation_passed = True
                self.logger.event("tool_result", turn=turn, action=action, args=args, result=result)
                self.print_tool_result(action, result)
                observation = {
                    "tool": action,
                    "result": result,
                    "instruction": (
                        "Continue the task. Return exactly one JSON object for the next action."
                        if result.get("ok") is not False
                        else "Repair the tool failure or choose a different action, then continue the task."
                    ),
                }
                self.messages.append({"role": "user", "content": self.user_content(json_text(observation))})
                self.save_transcript()
                self.save_progress(turn=turn)

            self.status = "blocked"
            self.finish_summary = f"reached the {max_turns}-turn limit without a finish action"
            self.logger.event("turn_limit", max_turns=max_turns)
            print(f"  stopped: {self.finish_summary}")
            self.save_transcript()
            self.save_summary()
            return 2
        except Exception as exc:
            self.status = "error"
            self.finish_summary = str(exc)
            self.logger.event("harness_error", error=str(exc))
            self.save_transcript()
            self.save_summary()
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local model as a constrained coding agent")
    task_source = parser.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task-file", type=Path)
    task_source.add_argument("--task-text")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-id", type=ensure_run_id)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--project-dir", type=Path, help="use this existing or newly created directory as the project workspace")
    parser.add_argument("--reasoning-level", choices=tuple(REASONING_LEVELS), help="override the configured reasoning level")
    parser.add_argument("--skill-overrides-json", help="JSON object containing per-task enabled and disabled skill names")
    parser.add_argument("--no-gates", action="store_true", help="disable task-specific completion requirements and evaluator")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_file = args.config if args.config.is_absolute() else ROOT / args.config
    template = None if args.template is None else (args.template if args.template.is_absolute() else ROOT / args.template)
    if args.task_text is not None:
        task = args.task_text
    else:
        task_file = args.task_file if args.task_file.is_absolute() else ROOT / args.task_file
        task = task_file.read_text(encoding="utf-8")
    config = load_json(config_file)
    if args.reasoning_level is not None:
        config = dict(config)
        config["reasoning_level"] = normalize_reasoning_level(args.reasoning_level)
    if args.skill_overrides_json is not None:
        try:
            skill_overrides = json.loads(args.skill_overrides_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid skill overrides JSON: {exc}") from exc
        config = dict(config)
        config["skill_overrides"] = skill_overrides
    if args.no_gates:
        config = dict(config)
        config["required_files"] = []
        config["require_validation"] = False
        config["require_workflow_gates"] = False
        config.pop("evaluator", None)
    run_id = args.run_id or datetime.now().strftime("run-%Y%m%d-%H%M%S")
    ensure_run_id(run_id)
    run_dir = ROOT / "agent-lab" / "runs" / run_id
    if args.project_dir is None:
        project_dir = run_dir / "project"
    else:
        project_dir = args.project_dir.expanduser()
        if not project_dir.is_absolute():
            project_dir = ROOT / project_dir
        project_dir = project_dir.resolve()
    harness = AgentHarness(task, config, run_dir, project_dir, template)
    print(f"run: {run_id}")
    print(f"project: {project_dir}")
    try:
        return harness.run()
    except HarnessError as exc:
        print(f"harness error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
