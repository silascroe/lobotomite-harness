"""Native, inspectable skill discovery and selection for Agent Lab.

Skill files are instructions, not executable plugins. The registry only
loads the bundled catalog and a selected project's ``skills`` directory.
Remote discovery is deliberately opt-in and recommendation-only.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DEFAULT_SKILL_NAMES = ("inspect-and-plan", "verify-before-finish")


class SkillError(Exception):
    """An expected skill catalog or selection error."""


def _clean_text(value: Any, field: str, limit: int = 240) -> str:
    if not isinstance(value, str):
        raise SkillError(f"skill {field} must be text")
    result = value.strip()
    if not result:
        raise SkillError(f"skill {field} is required")
    if len(result) > limit:
        raise SkillError(f"skill {field} is too long")
    return result


def _validate_name(value: Any) -> str:
    name = _clean_text(value, "name", 64).lower()
    if not SKILL_NAME_RE.fullmatch(name):
        raise SkillError("skill names must use lowercase letters, numbers, and hyphens")
    return name


def _parse_skill(path: Path, source: str, *, quality: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SkillError("skill file does not exist")
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if len(lines) < 4 or lines[0].strip() != "---":
        raise SkillError("skill file must begin with frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise SkillError("skill frontmatter is not closed") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise SkillError("skill frontmatter must use key: value lines")
        metadata[key.strip().lower()] = value.strip()
    name = _validate_name(metadata.get("name"))
    description = _clean_text(metadata.get("description"), "description")
    content = "\n".join(lines[end + 1 :]).strip()
    if not content:
        raise SkillError("skill content is required")
    if len(content) > 30000:
        raise SkillError("skill content is too long")
    return {
        "name": name,
        "description": description,
        "source": source,
        "path": str(path),
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "quality": quality,
        "activatable": source in {"builtin", "project"},
    }


def _load_directory(directory: Path, source: str, quality: str) -> list[dict[str, Any]]:
    if not directory.is_dir() or directory.is_symlink():
        return []
    result: list[dict[str, Any]] = []
    for skill_file in sorted(directory.glob("*/SKILL.md")):
        try:
            item = _parse_skill(skill_file, source, quality=quality)
        except (OSError, SkillError):
            continue
        if skill_file.parent.name != item["name"]:
            continue
        result.append(item)
    return result


def list_skills(project_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Return trusted bundled skills followed by valid project-local skills."""
    result = _load_directory(
        BUILTIN_SKILLS_DIR,
        "builtin",
        "Trusted bundled instruction; authored for Agent Lab.",
    )
    names = {item["name"] for item in result}
    if project_dir is not None:
        project = Path(project_dir).expanduser().resolve()
        local = _load_directory(
            project / "skills",
            "project",
            "Project-local instruction; review before you activate it.",
        )
        for item in local:
            if item["name"] not in names:
                result.append(item)
                names.add(item["name"])
    return result


def _normalize_names(values: Any, field: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise SkillError(f"skill override {field} must be a list")
    result: list[str] = []
    for value in values:
        name = _validate_name(value)
        if name not in result:
            result.append(name)
    return result


def resolve_skill_selection(project_dir: Path | str | None = None, overrides: Any = None) -> dict[str, Any]:
    """Resolve deterministic defaults plus a per-task enabled/disabled override."""
    catalog = list_skills(project_dir)
    by_name = {item["name"]: item for item in catalog}
    defaults = list(DEFAULT_SKILL_NAMES)
    missing_defaults = [name for name in defaults if name not in by_name]
    if missing_defaults:
        raise SkillError("bundled default skills are missing: " + ", ".join(missing_defaults))
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise SkillError("skill overrides must be an object")
    enabled = _normalize_names(overrides.get("enabled", []), "enabled")
    disabled = _normalize_names(overrides.get("disabled", []), "disabled")
    unknown = [name for name in enabled + disabled if name not in by_name]
    if unknown:
        raise SkillError("unknown skill: " + ", ".join(dict.fromkeys(unknown)))
    disabled_set = set(disabled)
    selected_names: list[str] = []
    for name in defaults + enabled:
        if name not in disabled_set and name not in selected_names:
            selected_names.append(name)
    return {
        "defaults": defaults,
        "enabled": enabled,
        "disabled": disabled,
        "resolved": [by_name[name] for name in selected_names],
    }


def public_skill(item: dict[str, Any]) -> dict[str, Any]:
    """Remove prompt content and absolute paths from a catalog response."""
    return {
        key: item[key]
        for key in ("name", "description", "source", "content_hash", "quality", "activatable")
        if key in item
    }


def public_selection(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "defaults": list(selection.get("defaults", [])),
        "enabled": list(selection.get("enabled", [])),
        "disabled": list(selection.get("disabled", [])),
        "resolved": [public_skill(item) for item in selection.get("resolved", [])],
    }


def skill_prompt(selection: dict[str, Any]) -> str:
    """Render only selected skill bodies for injection into a model prompt."""
    resolved = selection.get("resolved", [])
    if not resolved:
        return ""
    sections = [
        "\nSelected Agent Lab skills. Follow these operational instructions; report observable evidence, not private reasoning:",
    ]
    for item in resolved:
        sections.append(f"\n[Skill: {item['name']}]\n{item['content']}\n[End skill: {item['name']}]")
    return "\n".join(sections)


def find_skills(
    query: str,
    project_dir: Path | str | None = None,
    *,
    source: str = "local",
    allow_remote: bool = False,
    runner: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Find recommendations without activating or installing anything."""
    text = _clean_text(query, "query", 200).lower()
    normalized_source = _clean_text(source, "source", 20).lower()
    if normalized_source == "local":
        terms = [term for term in re.split(r"\s+", text) if term]
        matches: list[tuple[tuple[int, int], dict[str, Any]]] = []
        for index, item in enumerate(list_skills(project_dir)):
            name = item["name"].lower()
            description = item["description"].lower()
            content = item["content"].lower()
            haystack = " ".join((name, description, content))
            if all(term in haystack for term in terms):
                field_score = sum(
                    0 if term in name else 1 if term in description else 2
                    for term in terms
                )
                matches.append(((field_score, index), public_skill(item)))
        return [item for _score, item in sorted(matches, key=lambda value: value[0])]
    if normalized_source != "remote":
        raise SkillError("skill discovery source must be local or remote")
    if not allow_remote:
        raise SkillError("remote discovery requires explicit opt-in")
    command_runner = runner or subprocess.run
    executable = "npx.cmd" if os.name == "nt" else "npx"
    try:
        completed = command_runner(
            [executable, "skills", "find", query],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SkillError(f"remote skill discovery is unavailable: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "remote search failed").strip()
        raise SkillError("remote skill discovery failed: " + detail[:600])
    results: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        label = line.strip().lstrip("-* ")
        if not label or label.lower().startswith(("search", "found", "install")):
            continue
        name = re.split(r"\s+", label, maxsplit=1)[0].strip("`:")
        if not name:
            continue
        results.append(
            {
                "name": name,
                "description": label,
                "source": "skills.sh",
                "content_hash": "",
                "quality": "Remote recommendation; inspect source and review before activation.",
                "activatable": False,
            }
        )
    return results

