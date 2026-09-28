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
import shutil
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
from persistence import atomic_write_bytes, atomic_write_json, atomic_write_text
from approval import (
    normalize_mode,
    new_request,
    public_request,
    requires_approval,
    resolve_request,
)
from review import build_review_packet, fingerprint, review_status
from skills import SkillError, find_skills, public_selection, resolve_skill_selection, skill_prompt
from workspace_lock import WorkspaceBusyError, WorkspaceLease, acquire as acquire_workspace_lease, read_lock
from tool_receipt import complete_receipt, mark_unknown, new_receipt, public_receipt, settle_receipt
from provider import OPENAI_COMPATIBLE_PROVIDER, normalize_provider_config, public_provider


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "agent-lab" / "harness" / "config.json"
WORKSPACE_LOCK_ROOT = ROOT / "agent-lab" / ".workspace-locks"
ACTION_NAMES = {
    "list_files",
    "read_file",
    "write_file",
    "delete_file",
    "replace_text",
    "apply_patch",
    "run_command",
    "git_diff",
    "workflow_checkpoint",
    "find_skills",
    "finish",
}
ACTION_ARGUMENTS = {
    "list_files": ({}, {"path": str, "max_depth": int}),
    "read_file": ({"path": str}, {"max_chars": int}),
    "write_file": ({"path": str, "content": str}, {}),
    "delete_file": ({"path": str}, {}),
    "replace_text": ({"path": str, "old_text": str, "new_text": str}, {"expected_replacements": int}),
    "apply_patch": ({"patch": str}, {}),
    "run_command": ({"command": str}, {}),
    "git_diff": ({}, {"max_chars": int}),
    "workflow_checkpoint": ({"phase": str, "summary": str}, {"next_action": str, "artifacts": list}),
    "find_skills": ({}, {"query": str, "source": str}),
    "finish": ({}, {"status": str, "summary": str}),
}
ACTION_REQUIRED_NONEMPTY = {"path", "old_text", "patch", "command", "phase", "summary", "next_action"}
WORKFLOW_PHASES = {
    "intake", "inspect", "design", "plan", "implement", "verify", "review", "complete", "blocked"
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
    if (
        str(config.get("provider", "local")) != OPENAI_COMPATIBLE_PROVIDER
        and bool(config.get("constrain_local_actions", False))
    ):
        action_output_tokens = int(config.get("action_output_tokens", 2048))
        if action_output_tokens < 1:
            raise ValueError("action output token reserve must be a positive integer")
        configured_max = max(configured_max, action_output_tokens)

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


def apply_task_profile(config: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Apply a catalog profile without inheriting unrelated global gates."""
    if not isinstance(profile, dict):
        raise HarnessError("task profile must be a JSON object")
    gates = profile.get("gates")
    if not isinstance(gates, dict):
        raise HarnessError("task profile gates must be a JSON object")
    required_files = gates.get("required_files", [])
    if not isinstance(required_files, list) or not all(isinstance(item, str) and item.strip() for item in required_files):
        raise HarnessError("task profile required_files must be a list of non-empty strings")
    for key in ("require_validation", "require_workflow_gates"):
        if key in gates and not isinstance(gates[key], bool):
            raise HarnessError(f"task profile {key} must be boolean")
    evaluator = gates.get("evaluator")
    if evaluator is not None and (not isinstance(evaluator, str) or not evaluator.strip()):
        raise HarnessError("task profile evaluator must be a non-empty string when provided")

    result = dict(config)
    result["required_files"] = list(required_files)
    result["require_validation"] = bool(gates.get("require_validation", False))
    result["require_workflow_gates"] = bool(gates.get("require_workflow_gates", False))
    if evaluator:
        result["evaluator"] = evaluator
    else:
        result.pop("evaluator", None)
    result["task_profile"] = {
        "name": str(profile.get("name") or ""),
        "title": str(profile.get("title") or ""),
        "description": str(profile.get("description") or ""),
        "gates": {
            "required_files": list(required_files),
            "require_validation": result["require_validation"],
            "require_workflow_gates": result["require_workflow_gates"],
            **({"evaluator": evaluator} if evaluator else {}),
        },
    }
    return result


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated at {limit} characters]"


def recovery_instruction(action: str, result: dict[str, Any], *, interactive: bool = False) -> str:
    """Give the model a concrete next move after a failed tool call."""
    detail = str(result.get("error") or result.get("stderr") or "tool returned a failure")
    lowered = detail.lower()
    suffix = "then use respond." if interactive else "then continue the task."

    if action == "apply_patch" and any(term in lowered for term in ("context", "hunk", "match")):
        return (
            "The apply_patch hunk did not match the current file. Read the target file again with read_file, "
            "then use replace_text or write_file with the exact current content; do not repeat the same stale patch, "
            f"{suffix}"
        )
    if action == "apply_patch" and any(term in lowered for term in ("end patch", "end marker", "incomplete")):
        return (
            "The patch body was incomplete. Read the target file, then retry with a complete patch ending in "
            f"*** End Patch, or use replace_text/write_file; {suffix}"
        )
    if action == "apply_patch" and "begin patch" in lowered:
        return (
            "The patch was not in the required format. Send the full patch beginning with *** Begin Patch, "
            f"or use write_file with the complete current file content; {suffix}"
        )
    if action == "workflow_checkpoint" and "cannot transition from" in lowered:
        return (
            f"The workflow phase already advanced ({detail}). Do not move backward; continue from the current "
            "phase. If the plan evidence is missing, send a complete workflow_checkpoint with phase plan, "
            f"args.summary and args.next_action; {suffix}"
        )
    if action == "workflow_checkpoint" and any(field in lowered for field in ("next_action", "summary")):
        return (
            "The checkpoint needs args.phase, a non-empty args.summary, and a non-empty string "
            f"args.next_action. Retry the complete action before calling finish; {suffix}"
        )
    if action in {"write_file", "delete_file", "replace_text", "read_file", "list_files"} and "path" in lowered:
        return (
            f"The {action} call is missing a valid args.path. Retry with args.path set to a non-empty relative "
            f"project path and include all other required fields; {suffix}"
        )
    return f"Repair the {action} failure or choose a different action; {suffix}"


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
    repaired = re.sub(r'\\"(?=\s*}+\s*(?:```)?\s*$)', '"', content, count=1)
    return re.sub(r'("\s*}\s*)"\s*}$', r'\1}', repaired, count=1)


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
            if isinstance(value, dict) and "action" in value:
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
    if value is not None and "action" in value:
        return value
    raise HarnessError("model response must be a JSON action object")


def local_action_response_schema() -> dict[str, Any]:
    """A small schema supported by the bundled llama.cpp response_format API."""
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(ACTION_NAMES)},
            "args": {"type": "object"},
            "message": {"type": "string"},
        },
        "required": ["action", "args"],
        "additionalProperties": False,
    }


def validate_action_payload(payload: Any) -> tuple[str, dict[str, Any]]:
    """Reject malformed action arguments before they can reach a tool."""
    if not isinstance(payload, dict):
        raise HarnessError("model response must be a JSON action object")
    unexpected = set(payload) - {"action", "args", "message"}
    if unexpected:
        raise HarnessError("unknown action fields: " + ", ".join(sorted(map(str, unexpected))))
    action = payload.get("action")
    if not isinstance(action, str) or action not in ACTION_NAMES:
        raise HarnessError("action must be one of " + ", ".join(sorted(ACTION_NAMES)))
    if "args" not in payload or not isinstance(payload["args"], dict):
        raise HarnessError("args must be a JSON object")
    if "message" in payload and not isinstance(payload["message"], str):
        raise HarnessError("message must be a string when provided")
    args = payload["args"]
    required, optional = ACTION_ARGUMENTS[action]
    missing = [key for key in required if key not in args]
    if missing:
        raise HarnessError(f"{action} args missing required fields: " + ", ".join(sorted(missing)))
    unexpected_args = set(args) - set(required) - set(optional)
    if unexpected_args:
        raise HarnessError(f"{action} args contain unknown fields: " + ", ".join(sorted(map(str, unexpected_args))))
    for key, value in args.items():
        expected = required.get(key, optional.get(key))
        valid = isinstance(value, expected) and not (expected is int and isinstance(value, bool))
        if expected is list:
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        if not valid:
            label = "list of strings" if expected is list else {str: "a string", int: "an integer"}.get(expected, "a valid value")
            raise HarnessError(f"{action} args.{key} must be {label}")
        if key in ACTION_REQUIRED_NONEMPTY and not value.strip():
            raise HarnessError(f"{action} args.{key} must not be empty")
    if action == "workflow_checkpoint" and args["phase"] not in WORKFLOW_PHASES:
        raise HarnessError(
            "workflow_checkpoint args.phase must be one of: " + ", ".join(sorted(WORKFLOW_PHASES))
        )
    if action == "find_skills" and args.get("source", "local") not in {"local", "remote"}:
        raise HarnessError("find_skills args.source must be local or remote")
    if action == "finish" and args.get("status", "success") not in {"success", "blocked"}:
        raise HarnessError("finish args.status must be success or blocked")
    return action, args


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
- Use delete_file only when the task requires removing a file; it creates a reversible backup inside the run record first.
- Every action must include all required fields; write_file, replace_text, read_file, and list_files always need a non-empty relative args.path. Never send a content-only write_file call.
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
{"action":"delete_file","args":{"path":"relative/path"}}
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
        workspace_kind: str = "run",
        runtime_api_key: str | None = None,
    ) -> None:
        self.task = task
        try:
            self.config = normalize_provider_config(config)
        except ValueError as exc:
            raise HarnessError(str(exc)) from exc
        self.run_dir = run_dir
        self.project_dir = project_dir
        self.template_dir = template_dir
        self.workspace_kind = str(workspace_kind or "run")
        self.runtime_api_key = str(runtime_api_key or "").strip() or None
        self.workspace_lease: WorkspaceLease | None = None
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
        self.checkpoint = "not_started"
        self.resume_count = 0
        self.validation_passed = False
        self.had_tool_error = False
        self.evaluation: dict[str, Any] | None = None
        self.last_validation: dict[str, Any] = {}
        self.review_packet: dict[str, Any] | None = None
        self.approval_mode = normalize_mode(self.config.get("approval_mode", "auto"))
        self.config["approval_mode"] = self.approval_mode
        self.approval_record: dict[str, Any] | None = None
        self.pending_approval: dict[str, Any] | None = None
        self.approval_grant: dict[str, Any] | None = None
        self.tool_receipt: dict[str, Any] | None = None
        self.tool_receipt_recovery_needed = False
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
    def workspace_owner_id(self) -> str:
        return f"{self.workspace_kind}:{self.run_dir.name}"

    def acquire_workspace_lease(self) -> None:
        if self.workspace_lease is not None:
            return
        self.workspace_lease = acquire_workspace_lease(
            WORKSPACE_LOCK_ROOT,
            self.project_dir,
            self.workspace_owner_id,
            self.workspace_kind,
        )
        if self.run_dir.exists():
            self.logger.event("workspace_lock_acquired", workspace=self.workspace_lease.public())

    def release_workspace_lease(self) -> None:
        if self.workspace_lease is None:
            return
        self.workspace_lease.release()
        self.logger.event("workspace_lock_released", workspace=self.workspace_lease.public())
        self.workspace_lease = None

    def workspace_lock_view(self) -> dict[str, Any]:
        return self.workspace_lease.public() if self.workspace_lease is not None else {"status": "none"}

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

    def provider_metadata(self) -> dict[str, Any]:
        configured_key = self.runtime_api_key or os.environ.get("AGENT_LAB_API_KEY", "")
        return public_provider(self.config, has_api_key=bool(configured_key))

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
        project_was_present = self.project_dir.exists()
        if project_was_present and not self.project_dir.is_dir():
            raise HarnessError(f"project path is not a directory: {self.project_dir}")
        try:
            self.acquire_workspace_lease()
        except WorkspaceBusyError:
            raise
        self.run_dir.mkdir(parents=True)
        self.logger.event("workspace_lock_acquired", workspace=self.workspace_lease.public())
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
        self.save_initial_snapshot()
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
        self.save_transcript()

    @property
    def initial_snapshot_dir(self) -> Path:
        return self.run_dir / "initial-project"

    def save_initial_snapshot(self) -> None:
        snapshot_dir = self.initial_snapshot_dir
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, dict[str, int]] = {}
        for relative_path, data in sorted(self.initial_files.items()):
            destination = snapshot_dir / Path(relative_path)
            atomic_write_bytes(destination, data)
            manifest[relative_path] = {"bytes": len(data)}
        write_json(self.run_dir / "initial-snapshot.json", {"version": 1, "files": manifest})

    def load_initial_snapshot(self) -> dict[str, bytes]:
        manifest = load_json(self.run_dir / "initial-snapshot.json")
        raw_files = manifest.get("files")
        if not isinstance(raw_files, dict):
            raise HarnessError("run initial snapshot is missing its file manifest")
        snapshot_root = self.initial_snapshot_dir.resolve()
        files: dict[str, bytes] = {}
        total = 0
        for raw_name, metadata in raw_files.items():
            relative_path = str(raw_name).replace("\\", "/")
            candidate = (snapshot_root / relative_path).resolve()
            try:
                candidate.relative_to(snapshot_root)
            except ValueError as exc:
                raise HarnessError("run initial snapshot contains an unsafe path") from exc
            if not candidate.is_file():
                raise HarnessError(f"run initial snapshot is missing: {relative_path}")
            data = candidate.read_bytes()
            expected_bytes = metadata.get("bytes") if isinstance(metadata, dict) else None
            if isinstance(expected_bytes, int) and len(data) != expected_bytes:
                raise HarnessError(f"run initial snapshot is truncated: {relative_path}")
            total += len(data)
            if total > int(self.config.get("max_total_project_bytes", 500000)):
                raise HarnessError("run initial snapshot exceeds max_total_project_bytes")
            files[relative_path] = data
        return files

    @classmethod
    def resume_from_run(cls, run_dir: Path) -> "AgentHarness":
        run_dir = Path(run_dir).resolve()
        if not run_dir.is_dir():
            raise HarnessError(f"run directory does not exist: {run_dir}")
        config = load_json(run_dir / "config.json")
        workspace = load_json(run_dir / "workspace.json")
        project_raw = workspace.get("project")
        if not isinstance(project_raw, str) or not project_raw.strip():
            raise HarnessError("run workspace does not identify a project directory")
        task_path = run_dir / "task.md"
        if not task_path.is_file():
            raise HarnessError("run task is missing")
        task = task_path.read_text(encoding="utf-8")
        project_dir = Path(project_raw).expanduser().resolve()
        harness = cls(task, config, run_dir, project_dir, template_dir=None)

        try:
            transcript = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HarnessError("run transcript is missing or invalid") from exc
        if not isinstance(transcript, list) or not transcript:
            raise HarnessError("run transcript is empty or invalid")
        harness.messages = [
            item
            for item in transcript
            if isinstance(item, dict)
            and item.get("role") in {"system", "user", "assistant"}
            and isinstance(item.get("content"), str)
        ]
        if not harness.messages:
            raise HarnessError("run transcript has no usable messages")

        progress = load_json(run_dir / "progress.json")
        summary = load_json(run_dir / "summary.json") if (run_dir / "summary.json").is_file() else {}
        persisted_status = summary.get("status") or progress.get("status")
        if persisted_status in {"success", "complete", "blocked", "error"}:
            raise HarnessError(f"cannot resume a terminal run with status {persisted_status}")
        harness.initial_files = harness.load_initial_snapshot()
        harness.workflow = load_workflow(run_dir / "workflow.json")
        evidence = progress.get("workflow_evidence") or summary.get("workflow_evidence") or {}
        for name in harness.workflow_evidence:
            harness.workflow_evidence[name] = bool(evidence.get(name, False))
        harness.current_turn = int(progress.get("turn", 0) or 0)
        harness.model_calls = int(progress.get("model_calls", 0) or 0)
        harness.tool_calls = int(progress.get("tool_calls", 0) or 0)
        harness.checkpoint = str(progress.get("checkpoint") or "unknown")
        harness.resume_count = int(progress.get("resume_count", 0) or 0) + 1
        harness.validation_passed = bool(progress.get("validation_passed", False))
        harness.had_tool_error = bool(progress.get("had_tool_error", False))
        harness.evaluation = progress.get("evaluation") if isinstance(progress.get("evaluation"), dict) else None
        harness.last_validation = (
            progress.get("last_validation")
            if isinstance(progress.get("last_validation"), dict)
            else summary.get("last_validation") if isinstance(summary.get("last_validation"), dict) else {}
        )
        review_path = run_dir / "review.json"
        harness.review_packet = load_json(review_path) if review_path.is_file() else None
        approval_path = run_dir / "approval.json"
        harness.approval_record = load_json(approval_path) if approval_path.is_file() else None
        if harness.approval_record and harness.approval_record.get("status") == "pending":
            harness.pending_approval = harness.approval_record
        receipt_path = run_dir / "tool-receipt.json"
        harness.tool_receipt = load_json(receipt_path) if receipt_path.is_file() else None
        harness.tool_receipt_recovery_needed = bool(
            harness.tool_receipt
            and harness.tool_receipt.get("status") in {"pending", "completed", "unknown"}
        )
        harness.finish_summary = str(progress.get("summary") or "")
        harness.blocked_reason = str(progress.get("blocked_reason") or "")
        harness.recovery = RecoveryController.from_snapshot(progress.get("recovery") or summary.get("recovery"))
        harness.status = "interrupted"
        if persisted_status == "waiting_approval" and harness.pending_approval:
            harness.status = "waiting_approval"
        try:
            harness.acquire_workspace_lease()
        except WorkspaceBusyError:
            raise
        return harness

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

    def delete_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self.resolve_path(args.get("path"), allow_project_root=False)
        if not path.is_file():
            raise HarnessError(f"cannot delete missing file: {args.get('path')}")
        if path.is_symlink():
            raise HarnessError("symlinks are not allowed")
        backup_root = (self.run_dir / "deleted-files").resolve()
        try:
            backup_root.relative_to(self.project_dir.resolve())
        except ValueError:
            pass
        else:
            raise HarnessError("cannot create a reversible delete backup inside the project")
        relative_path = relative_name(path, self.project_dir)
        backup = backup_root / Path(relative_path)
        if backup.exists():
            raise HarnessError(f"a delete backup already exists for: {relative_path}")
        data = path.read_bytes()
        atomic_write_bytes(backup, data)
        try:
            path.unlink()
        except OSError:
            try:
                backup.unlink()
            except OSError:
                pass
            raise
        return {
            "ok": True,
            "path": relative_path,
            "bytes": len(data),
            "deleted": True,
            "backup": (Path("deleted-files") / Path(relative_path)).as_posix(),
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
                # Small local models often omit the conventional context
                # prefix. Treat a plain line as context, but keep additions
                # and removals strict so an accidental edit cannot disappear.
                current_body.append(" " + line)
        if current_body:
            hunks.append((current_header, current_body))
        if not hunks:
            raise HarnessError("update patch contained no hunks")

        result = list(original_lines)
        cursor = 0
        for header, body in hunks:
            old_block = [line[1:] for line in body if line[0] in (" ", "-")]
            new_block = [line[1:] for line in body if line[0] in (" ", "+")]
            addition_block = [line[1:] for line in body if line.startswith("+")]
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
                    if addition_block and not any(line.startswith("-") for line in body):
                        match = re.search(r"-([0-9]+)", header)
                        if not match:
                            raise HarnessError("could not find update-patch context in the target file")
                        position = min(max(0, int(match.group(1)) - 1), len(result))
                        old_block = []
                        new_block = addition_block
                    else:
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

        implicit_end = not found_end
        if implicit_end and not pending:
            raise HarnessError("patch must include at least one file operation")

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
        return {"ok": True, "changed": changed, "implicit_end": implicit_end}

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
        executable = Path(tokens[0]).name.lower()
        execution_tokens = list(tokens)
        if executable in {"python", "python.exe", "py", "py.exe"} and shutil.which(tokens[0]) is None:
            execution_tokens[0] = sys.executable
        timeout = int(self.config.get("command_timeout_seconds", 20))
        try:
            completed = subprocess.run(
                execution_tokens,
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
        packet = build_review_packet(
            self.initial_files,
            current,
            diff,
            validation=self.last_validation,
            evaluation=self.evaluation,
            workflow_evidence={**self.workflow_evidence, "review": True},
            max_diff_chars=int(self.config.get("max_review_diff_chars", 50000)),
        )
        self.review_packet = packet
        atomic_write_json(self.run_dir / "review.json", packet)
        self.logger.event(
            "review_packet",
            status="current",
            changed_files=packet["changed_files"],
            current_fingerprint=packet["current_fingerprint"],
            diff_truncated=packet["diff_truncated"],
        )
        return {
            "ok": True,
            "diff": clip(diff, min(limit, self.output_limit)),
            "changed_files": [item["path"] for item in packet["changed_files"]],
            "review": {
                "status": "current",
                "file": "review.json",
                "changed_files": packet["changed_files"],
                "current_fingerprint": packet["current_fingerprint"],
                "diff_truncated": packet["diff_truncated"],
            },
        }

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
                args.get("next_action", "Continue with the next concrete task step." if requested_phase == "plan" else None),
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
        if action == "run_command":
            self.last_validation = {
                "command": result.get("command"),
                "exit_code": result.get("exit_code"),
                "passed": result.get("ok") is True and result.get("exit_code") == 0,
                "timed_out": bool(result.get("timed_out", False)),
            }
        if isinstance(result, dict) and result.get("ok"):
            if action in {"list_files", "read_file"}:
                self.workflow_evidence["inspect"] = True
            elif action in {"write_file", "delete_file", "replace_text", "apply_patch"}:
                self.workflow_evidence["implement"] = True
                self.workflow_evidence["verify"] = False
                self.workflow_evidence["review"] = False
                self.validation_passed = False
            elif action == "run_command" and result.get("exit_code") == 0 and self.workflow_evidence["implement"]:
                self.workflow_evidence["verify"] = True
            if action == "git_diff":
                self.workflow_evidence["review"] = True
        next_state = observe_tool(self.workflow, action, result)
        if next_state == self.workflow:
            return
        self.workflow = save_workflow(self.run_dir / "workflow.json", next_state)
        self.logger.event("workflow_phase", source="automatic", action=action, state=self.workflow)

    def approval_view(self) -> dict[str, Any]:
        if self.pending_approval is not None:
            return public_request(self.pending_approval)
        if self.approval_record is not None:
            return public_request(self.approval_record)
        return {"status": "none"}

    def tool_receipt_view(self) -> dict[str, Any]:
        if self.tool_receipt is None:
            return {"status": "none"}
        return public_receipt(self.tool_receipt)

    def begin_tool_receipt(
        self,
        action: str,
        args: dict[str, Any],
        *,
        turn: int | None = None,
        step: int | None = None,
    ) -> None:
        self.tool_receipt = new_receipt(action, args, turn=turn, step=step)
        self.tool_receipt_recovery_needed = False
        atomic_write_json(self.run_dir / "tool-receipt.json", self.tool_receipt)
        self.logger.event("tool_call_started", receipt=public_receipt(self.tool_receipt))

    def complete_tool_receipt(self, result: dict[str, Any]) -> None:
        if self.tool_receipt is None or self.tool_receipt.get("status") != "pending":
            return
        self.tool_receipt = complete_receipt(self.tool_receipt, result)
        atomic_write_json(self.run_dir / "tool-receipt.json", self.tool_receipt)
        self.logger.event("tool_call_completed", receipt=public_receipt(self.tool_receipt))

    def settle_tool_receipt(self) -> None:
        if self.tool_receipt is None or self.tool_receipt.get("status") not in {"completed", "unknown"}:
            return
        self.tool_receipt = settle_receipt(self.tool_receipt)
        self.tool_receipt_recovery_needed = False
        atomic_write_json(self.run_dir / "tool-receipt.json", self.tool_receipt)
        self.logger.event("tool_call_settled", receipt=public_receipt(self.tool_receipt))

    def recover_tool_receipt(self, *, force: bool = False) -> dict[str, Any] | None:
        if not force and not self.tool_receipt_recovery_needed:
            return None
        receipt = self.tool_receipt
        if receipt is None or receipt.get("status") not in {"pending", "completed", "unknown"}:
            self.tool_receipt_recovery_needed = False
            return None
        action = str(receipt.get("action") or "unknown")
        if receipt.get("status") == "completed" and isinstance(receipt.get("result"), dict):
            result = dict(receipt["result"])
            instruction = "The previous worker completed this tool call before stopping. Continue from its result; do not repeat the action."
            event = "tool_result_replayed"
        else:
            if receipt.get("status") == "pending":
                self.tool_receipt = mark_unknown(receipt)
                atomic_write_json(self.run_dir / "tool-receipt.json", self.tool_receipt)
            result = {
                "ok": False,
                "error": self.tool_receipt.get("recovery")
                or "The previous tool outcome is unknown. Inspect the project before attempting the action again.",
                "outcome_unknown": True,
            }
            instruction = "The previous tool outcome is unknown. Inspect the project before attempting that action again; do not repeat it blindly."
            event = "tool_outcome_unknown"
        self.tool_receipt_recovery_needed = False
        self.logger.event(event, receipt=public_receipt(self.tool_receipt))
        return {"tool": action, "result": result, "instruction": instruction}

    def request_approval(
        self,
        action: str,
        args: dict[str, Any],
        *,
        turn: int | None = None,
        step: int | None = None,
    ) -> dict[str, Any]:
        if not self.requires_approval(action):
            raise HarnessError("approval is not enabled for this action")
        if self.pending_approval is not None:
            raise HarnessError("another approval request is already pending")
        request = new_request(action, args, turn=turn, step=step)
        self.approval_record = request
        self.pending_approval = request
        atomic_write_json(self.run_dir / "approval.json", request)
        self.logger.event("approval_requested", **public_request(request))
        return request

    def requires_approval(self, action: str) -> bool:
        return requires_approval(action, self.approval_mode)

    def resolve_approval(self, decision: str) -> dict[str, Any]:
        if self.pending_approval is None:
            raise HarnessError("there is no pending approval request")
        resolved = resolve_request(self.pending_approval, decision)
        self.approval_record = resolved
        self.pending_approval = None
        self.approval_grant = resolved if resolved.get("status") == "approved" else None
        atomic_write_json(self.run_dir / "approval.json", resolved)
        self.logger.event("approval_resolved", **public_request(resolved))
        return resolved

    def dispatch(self, action: str, args: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        if self.requires_approval(action):
            if not approved or self.approval_grant is None:
                raise HarnessError(f"{action} requires operator approval before dispatch")
            if self.approval_grant.get("action") != action or self.approval_grant.get("args") != args:
                raise HarnessError("approved action does not match the pending request")
            self.approval_grant = None
        result: dict[str, Any]
        if action == "list_files":
            result = self.list_files(args)
        elif action == "read_file":
            result = self.read_file(args)
        elif action == "write_file":
            result = self.write_file(args)
        elif action == "delete_file":
            result = self.delete_file(args)
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

    def evaluator_failure_detail(self, evaluation: dict[str, Any]) -> str:
        raw = str(evaluation.get("stdout") or evaluation.get("stderr") or "no evaluator output")
        try:
            report = json.loads(raw)
        except json.JSONDecodeError:
            return clip(raw, 800)
        checks = report.get("checks") if isinstance(report, dict) else None
        if isinstance(checks, dict):
            failed = [str(name) for name, passed in checks.items() if passed is False]
            if failed:
                return "failed checks: " + ", ".join(failed[:20])
        return clip(str(report.get("message") if isinstance(report, dict) else raw), 800)

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
            return "success is not accepted yet; external evaluator " + self.evaluator_failure_detail(evaluation)
        return None

    def call_model(self) -> dict[str, Any]:
        endpoint = str(self.config.get("endpoint", "")).strip()
        if not endpoint:
            raise HarnessError("config endpoint is empty")
        provider = str(self.config.get("provider", "local"))
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
        headers = {"Content-Type": "application/json"}
        if provider == OPENAI_COMPATIBLE_PROVIDER:
            api_key = self.runtime_api_key or os.environ.get("AGENT_LAB_API_KEY", "").strip()
            if not api_key:
                raise HarnessError("the remote provider is selected but no API key is configured")
            headers["Authorization"] = f"Bearer {api_key}"
            payload.pop("reasoning_budget_tokens", None)
            payload.pop("chat_template_kwargs", None)
            if reasoning["profile"] == "gemma" and reasoning["enabled"]:
                payload.pop("reasoning_format", None)
            if bool(self.config.get("reasoning_effort_supported", False)):
                payload["reasoning_effort"] = reasoning["effort"]
        else:
            if reasoning["profile"] == "gemma" and reasoning["enabled"]:
                payload["reasoning_format"] = "deepseek"
            if bool(self.config.get("reasoning_effort_supported", False)):
                payload["reasoning_effort"] = reasoning["effort"]
            if bool(self.config.get("constrain_local_actions", False)):
                payload["response_format"] = {
                    "type": "json_object",
                    "schema": local_action_response_schema(),
                }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            api_key = self.runtime_api_key or os.environ.get("AGENT_LAB_API_KEY", "").strip()
            if api_key:
                detail = detail.replace(api_key, "[redacted]")
            raise HarnessError(f"model endpoint returned HTTP {exc.code}: {clip(detail, 1000)}") from exc
        except urllib.error.URLError as exc:
            raise HarnessError(f"could not reach model endpoint {endpoint}: {exc.reason}") from exc
        try:
            response_data = json.loads(raw)
            message = response_data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise HarnessError(f"model endpoint returned an unexpected response: {clip(raw, 1000)}") from exc

        def response_text(value: Any) -> str:
            if isinstance(value, list):
                return "".join(
                    str(item.get("text") or "") if isinstance(item, dict) else str(item)
                    for item in value
                )
            return str(value or "")

        content = response_text(message.get("content"))
        reasoning_content = response_text(message.get("reasoning_content"))
        result = {
            "content": content,
            "provider": provider,
            "reasoning_present": bool(reasoning_content),
            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
            "usage": response_data.get("usage", {}),
            "reasoning_level": reasoning["level"],
            "reasoning_budget_tokens": reasoning["budget"],
        }
        if self.workspace_kind == "run":
            result["reasoning_content"] = reasoning_content
        self.model_calls += 1
        return result

    def print_tool_result(self, action: str, result: dict[str, Any]) -> None:
        if action == "list_files":
            entries = result.get("entries", [])
            print(f"  {action}: {len(entries)} entries")
        elif action in {"write_file", "delete_file", "replace_text", "apply_patch"}:
            print(f"  {action}: {result.get('changed', result.get('path', 'done'))}")
        elif action == "run_command":
            print(f"  {action}: exit {result.get('exit_code', 'error')}")
        else:
            print(f"  {action}: ok")

    def save_transcript(self) -> None:
        write_json(self.run_dir / "transcript.json", self.messages)

    def save_progress(self, *, turn: int | None = None, checkpoint: str | None = None) -> None:
        if turn is not None:
            self.current_turn = max(0, int(turn))
        if checkpoint is not None:
            self.checkpoint = str(checkpoint)
        status = self.status if self.status != "not_started" else "running"
        write_json(
            self.run_dir / "progress.json",
            {
                "status": status,
                "turn": self.current_turn,
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "checkpoint": self.checkpoint,
                "resume_count": self.resume_count,
                "validation_passed": self.validation_passed,
                "had_tool_error": self.had_tool_error,
                "evaluation": self.evaluation,
                "last_validation": self.last_validation,
                "review": {
                    "status": review_status(self.review_packet, self.snapshot_files()) if self.review_packet else "not_reviewed",
                    "reviewed_fingerprint": self.review_packet.get("current_fingerprint") if self.review_packet else None,
                },
                "approval": self.approval_view(),
                "tool_receipt": self.tool_receipt_view(),
                "workspace_lock": self.workspace_lock_view(),
                "provider": self.provider_metadata(),
                "task_profile": self.config.get("task_profile", {}),
                "recovery": self.recovery.snapshot(),
                "blocked_reason": self.blocked_reason,
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
        self.checkpoint = "terminal"
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
            "checkpoint": self.checkpoint,
            "resume_count": self.resume_count,
            "validation_passed": self.validation_passed,
            "last_validation": self.last_validation,
            "evaluation": self.evaluation,
            "changed_files": changed,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 2),
            "project": str(self.project_dir),
            "workspace_mode": self.workspace_mode,
            "approval_mode": self.approval_mode,
            "reasoning": self.reasoning_metadata(),
            "context": dict(self.context_metadata),
            "workflow": self.workflow,
            "workflow_evidence": dict(self.workflow_evidence),
            "review": {
                "status": review_status(self.review_packet, current) if self.review_packet else "not_reviewed",
                "current_fingerprint": fingerprint(current),
                "reviewed_fingerprint": self.review_packet.get("current_fingerprint") if self.review_packet else None,
                "changed_files": self.review_packet.get("changed_files", []) if self.review_packet else [],
                "generated_at": self.review_packet.get("generated_at") if self.review_packet else None,
                "diff_truncated": bool(self.review_packet.get("diff_truncated", False)) if self.review_packet else False,
            },
            "approval": self.approval_view(),
            "tool_receipt": self.tool_receipt_view(),
            "workspace_lock": self.workspace_lock_view(),
            "provider": self.provider_metadata(),
            "task_profile": self.config.get("task_profile", {}),
            "skills": self.skill_metadata(),
            "recovery": self.recovery.snapshot(),
            "blocked_reason": self.blocked_reason,
        }
        write_json(self.run_dir / "summary.json", summary)
        self.save_progress()
        if self.status in {"success", "complete", "blocked", "error"}:
            self.release_workspace_lease()

    def run(self, *, resume: bool = False, approval_decision: str | None = None) -> int:
        max_turns = int(self.config.get("max_turns", 18))
        pending_response: str | None = None
        pending_turn: int | None = None
        forced_action: tuple[str, dict[str, Any], str] | None = None
        if resume:
            self.status = "running"
            self.finish_summary = ""
            if approval_decision is not None and self.pending_approval is None:
                raise HarnessError("there is no pending approval request")
            if self.pending_approval is not None:
                if approval_decision not in {"approve", "deny"}:
                    self.status = "waiting_approval"
                    self.checkpoint = "approval_wait"
                    self.save_summary()
                    return 3
                pending = self.pending_approval
                forced_action = (
                    str(pending.get("action") or ""),
                    dict(pending.get("args") or {}),
                    approval_decision,
                )
                pending_turn = int(pending.get("turn") or self.current_turn or 1)
                self.resolve_approval(approval_decision)
                start_turn = pending_turn
                end_turn = start_turn + max_turns
                correction = ""
                self.logger.event(
                    "run_resumed_for_approval",
                    turn=pending_turn,
                    decision=approval_decision,
                    resume_count=self.resume_count,
                )
                self.save_progress(turn=pending_turn, checkpoint="approval_resume")
            else:
                recovery_observation = None
                if self.tool_receipt_recovery_needed:
                    recovery_observation = self.recover_tool_receipt(force=True)
                if recovery_observation is not None:
                    self.messages.append(
                        {"role": "user", "content": self.user_content(json_text(recovery_observation))}
                    )
                    recovery_turn = int(self.tool_receipt.get("turn") or self.current_turn or 1)
                    self.save_transcript()
                    self.save_progress(turn=recovery_turn, checkpoint="tool_recovery")
                    self.settle_tool_receipt()
                    self.save_progress(turn=recovery_turn, checkpoint="tool_recovery_settled")
                    start_turn = recovery_turn + 1
                    end_turn = start_turn + max_turns
                    correction = ""
                    self.logger.event("run_resumed_from_tool_receipt", turn=recovery_turn, resume_count=self.resume_count)
                    recovery_observation = None
                else:
                    last_message = self.messages[-1] if self.messages else {}
                    if self.checkpoint == "model_response" and last_message.get("role") == "assistant":
                        pending_response = last_message.get("content")
                        pending_turn = self.current_turn
                    elif self.checkpoint == "model_call" and last_message.get("role") == "assistant":
                        pending_response = last_message.get("content")
                        pending_turn = self.current_turn + 1
                    start_turn = pending_turn if pending_turn is not None else self.current_turn + 1
                    end_turn = start_turn + max_turns
                    self.logger.event(
                        "run_resumed",
                        turn=self.current_turn,
                        checkpoint=self.checkpoint,
                        resume_count=self.resume_count,
                    )
                    correction = "" if pending_response is not None else "The previous worker stopped. Continue from the last saved transcript and tool result."
                    if pending_response is None:
                        self.save_progress(checkpoint="resume")
        else:
            if approval_decision is not None:
                raise HarnessError("approval decisions only apply when resuming a run")
            self.prepare()
            self.status = "running"
            self.save_transcript()
            self.save_progress(turn=0, checkpoint="prepared")
            start_turn = 1
            end_turn = max_turns + 1
            correction = ""
        try:
            for turn in range(start_turn, end_turn):
                if correction:
                    self.messages.append({"role": "user", "content": self.user_content(correction)})
                    self.save_transcript()
                display_limit = max_turns if not resume else end_turn - 1
                approval_resolution: str | None = None
                if forced_action is not None and turn == pending_turn:
                    action, args, approval_resolution = forced_action
                    forced_action = None
                    content = json_text({"action": action, "args": args})
                    self.current_turn = turn
                    print(f"turn {turn}/{display_limit}: resuming {approval_resolution}d action")
                elif pending_response is not None and turn == pending_turn:
                    print(f"turn {turn}/{display_limit}: resuming saved model response")
                    content = pending_response
                    pending_response = None
                    self.current_turn = turn
                else:
                    self.save_progress(checkpoint="model_call")
                    print(f"turn {turn}/{display_limit}: asking model")
                    response = self.call_model()
                    self.current_turn = turn
                    content = response["content"]
                    self.logger.event("model_response", turn=turn, **response)
                    self.messages.append({"role": "assistant", "content": content})
                    self.save_transcript()
                    self.save_progress(turn=turn, checkpoint="model_response")
                action = None
                try:
                    parsed = extract_json_object(content)
                    action = parsed.get("action") if isinstance(parsed, dict) else None
                    action, args = validate_action_payload(parsed)
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
                    if isinstance(action, str) and action in ACTION_ARGUMENTS:
                        required_fields = sorted(ACTION_ARGUMENTS[action][0])
                        allowed_fields = sorted(set(ACTION_ARGUMENTS[action][0]) | set(ACTION_ARGUMENTS[action][1]))
                        correction = (
                            f"{error}. Repair attempt {decision.attempt} of {decision.limit}. Return one corrected "
                            f"JSON action for {action}; required args fields: {required_fields}; allowed args fields: "
                            f"{allowed_fields}. Keep args as an object, remove unknown fields, and correct each field's "
                            "type. Retry this tool action once only after its arguments pass validation."
                        )
                    else:
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
                            + (
                                'Call workflow_checkpoint with args {"phase":"plan","summary":"short plan",'
                                '"next_action":"next concrete step"} before trying finish again. '
                                if "workflow evidence missing: plan" in issue else ""
                            )
                            + "Continue using the tools, then try finish again."
                        )
                        print(f"  finish rejected: {issue} (repair attempt {decision.attempt}/{decision.limit})")
                        continue
                    self.status = str(args.get("status", "success"))
                    if self.status not in {"success", "blocked"}:
                        self.status = "success"
                    self.finish_summary = str(args.get("summary", ""))
                    self.checkpoint = "terminal"
                    self.workflow = observe_tool(self.workflow, "finish", {"ok": True, "status": self.status})
                    save_workflow(self.run_dir / "workflow.json", self.workflow)
                    self.logger.event("workflow_phase", source="automatic", action="finish", state=self.workflow)
                    self.logger.event("finish", turn=turn, status=self.status, summary=self.finish_summary)
                    print(f"  finished: {self.status} — {self.finish_summary}")
                    self.save_transcript()
                    self.save_summary()
                    return 0 if self.status == "success" else 2

                duplicate = None if approval_resolution is not None else self.recovery.observe_action(action, args)
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
                    self.save_transcript()
                    self.save_progress(turn=turn, checkpoint="tool_result")
                    continue

                if approval_resolution is None and self.requires_approval(action):
                    self.request_approval(action, args, turn=turn)
                    self.status = "waiting_approval"
                    self.checkpoint = "approval_wait"
                    print(f"  waiting for approval: {action}")
                    self.save_transcript()
                    self.save_summary()
                    return 3

                if approval_resolution == "deny":
                    result = {
                        "ok": False,
                        "approval": "denied",
                        "error": "operator denied this action; choose a different approach or explain the blocker",
                    }
                else:
                    self.begin_tool_receipt(action, args, turn=turn, step=turn)
                    self.tool_calls += 1
                    try:
                        if approval_resolution == "approve":
                            result = self.dispatch(action, args, approved=True)
                        else:
                            result = self.dispatch(action, args)
                    except HarnessError as exc:
                        result = {"ok": False, "error": str(exc)}
                    self.complete_tool_receipt(result)
                if result.get("ok") is False and result.get("approval") != "denied":
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
                        else recovery_instruction(action, result)
                    ),
                }
                self.messages.append({"role": "user", "content": self.user_content(json_text(observation))})
                self.save_transcript()
                self.save_progress(turn=turn, checkpoint="tool_result")
                self.settle_tool_receipt()
                self.save_progress(turn=turn, checkpoint="tool_result_settled")

            self.status = "blocked"
            self.checkpoint = "terminal"
            self.finish_summary = f"reached the {max_turns}-turn limit without a finish action"
            self.logger.event("turn_limit", max_turns=max_turns, resumed=resume)
            print(f"  stopped: {self.finish_summary}")
            self.save_transcript()
            self.save_summary()
            return 2
        except Exception as exc:
            self.status = "error"
            self.checkpoint = "terminal"
            self.finish_summary = str(exc)
            self.logger.event("harness_error", error=str(exc))
            self.save_transcript()
            self.save_summary()
            raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local model as a constrained coding agent")
    task_source = parser.add_mutually_exclusive_group(required=False)
    task_source.add_argument("--task-file", type=Path)
    task_source.add_argument("--task-text")
    parser.add_argument("--resume-run", type=ensure_run_id, help="resume an interrupted run by its persisted run id")
    parser.add_argument("--approval-decision", choices=("approve", "deny"), help="resolve a pending operator approval while resuming")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--run-id", type=ensure_run_id)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--project-dir", type=Path, help="use this existing or newly created directory as the project workspace")
    parser.add_argument("--provider", choices=("local", "openai_compatible"), help="model provider")
    parser.add_argument("--endpoint", help="override the model chat-completions endpoint")
    parser.add_argument("--model", help="override the model name")
    parser.add_argument("--reasoning-level", choices=tuple(REASONING_LEVELS), help="override the configured reasoning level")
    parser.add_argument("--approval-mode", choices=("auto", "confirm"), help="whether mutating tools need operator approval")
    parser.add_argument("--skill-overrides-json", help="JSON object containing per-task enabled and disabled skill names")
    parser.add_argument("--task-profile-json", help="JSON catalog profile containing task identity and completion gates")
    parser.add_argument("--no-gates", action="store_true", help="disable task-specific completion requirements and evaluator")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.resume_run:
        if any(value is not None for value in (args.task_file, args.task_text, args.template, args.project_dir, args.run_id)):
            raise SystemExit("--resume-run cannot be combined with a new task, template, project, or run id")
        run_dir = ROOT / "agent-lab" / "runs" / args.resume_run
        try:
            harness = AgentHarness.resume_from_run(run_dir)
        except (HarnessError, WorkspaceBusyError) as exc:
            print(f"harness error: {exc}", file=sys.stderr)
            return 1
        print(f"resuming run: {args.resume_run}")
        print(f"project: {harness.project_dir}")
        try:
            return harness.run(resume=True, approval_decision=args.approval_decision)
        except (HarnessError, WorkspaceBusyError) as exc:
            print(f"harness error: {exc}", file=sys.stderr)
            return 1
    if args.task_file is None and args.task_text is None:
        raise SystemExit("one of --task-file, --task-text, or --resume-run is required")
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
    if args.approval_mode is not None:
        config = dict(config)
        config["approval_mode"] = args.approval_mode
    if args.provider is not None:
        config = dict(config)
        config["provider"] = args.provider
    if args.endpoint is not None:
        config = dict(config)
        config["endpoint"] = args.endpoint
    if args.model is not None:
        config = dict(config)
        config["model"] = args.model
    if args.skill_overrides_json is not None:
        try:
            skill_overrides = json.loads(args.skill_overrides_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid skill overrides JSON: {exc}") from exc
        config = dict(config)
        config["skill_overrides"] = skill_overrides
    if args.task_profile_json is not None:
        try:
            task_profile = json.loads(args.task_profile_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid task profile JSON: {exc}") from exc
        config = apply_task_profile(config, task_profile)
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
    except (HarnessError, WorkspaceBusyError) as exc:
        print(f"harness error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

