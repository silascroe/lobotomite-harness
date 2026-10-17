#!/usr/bin/env python3
"""Behavioral checker for the Signal Garden mini project; not a visual judge.

The page is loaded in a real headless browser; its primary button is clicked
with the mouse and, on a fresh load, activated from the keyboard, and the
checker watches whether a status element actually changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from browser_checks import focus_check, layout_check, load_checks, mark_unavailable, run_probe, short
from finding_messages import findings_for

BROWSER_CHECKS = [
    "runs_without_errors", "loads_styles_and_script", "local_assets", "signal_garden_heading", "description",
    "semantic_main", "action_updates_status", "keyboard_operable", "focus_visible",
    "responsive_layout",
]


def grade(obs):
    checks, evidence = load_checks(obs)
    structure = obs.get("structure", {})
    checks["signal_garden_heading"] = bool(structure.get("heading"))
    if not checks["signal_garden_heading"]:
        evidence["signal_garden_heading"] = "visible h1 text: " + (short(structure.get("headings", [])) or "none")
    checks["description"] = bool(structure.get("description"))
    if not checks["description"]:
        evidence["description"] = "no visible paragraph of at least 10 characters"
    checks["semantic_main"] = bool(structure.get("main"))

    action = obs.get("action")
    click = obs.get("click") or {}
    changed = click.get("changed", [])
    if not action:
        problem = "found no visible button to use"
    elif click.get("navigated"):
        problem = f"clicking {action['desc']} reloaded the page"
    elif not changed:
        problem = f"clicking {action['desc']} changed no visible text"
        if action.get("covered"):
            problem += f" (the click landed on {action['covered']}, which covers it)"
    else:
        problem = None
    checks["action_updates_status"] = problem is None
    if problem:
        evidence["action_updates_status"] = problem

    keyboard = obs.get("keyboard") or {}
    if not action:
        problem = "found no visible button to use"
    elif not keyboard.get("reached"):
        problem = f"Tab never reached {action['desc']}"
    elif keyboard.get("navigated"):
        problem = "pressing Enter on it reloaded the page"
    elif not keyboard.get("changed"):
        problem = f"pressing Enter on {action['desc']} changed no visible text"
    else:
        problem = None
    checks["keyboard_operable"] = problem is None
    if problem:
        evidence["keyboard_operable"] = problem

    checks["focus_visible"], detail = focus_check(obs)
    if detail:
        evidence["focus_visible"] = detail
    checks["responsive_layout"], detail = layout_check(obs)
    if detail:
        evidence["responsive_layout"] = detail
    return checks, evidence


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_mini_project.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    checks = {f"has_{name}": (root / name).is_file() for name in ("index.html", "styles.css", "app.js")}
    evidence, infrastructure = {}, []
    if checks["has_index.html"]:
        obs, problem, infra = run_probe("mini-project", root)
    else:
        obs, problem, infra = None, "index.html does not exist", False
    if obs is None:
        infrastructure = mark_unavailable(checks, BROWSER_CHECKS, problem, infra, evidence)
    else:
        graded, graded_evidence = grade(obs)
        checks.update(graded)
        evidence.update(graded_evidence)
    result = {"passed": all(checks.values()), "checks": checks,
              "findings": findings_for(checks, infrastructure, evidence)}
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
