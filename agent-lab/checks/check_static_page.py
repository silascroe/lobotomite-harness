#!/usr/bin/env python3
"""Behavioral checker for the Northstar Field Notes static page.

The page is loaded in a real headless browser and used the way a person
would: fields are typed into, the submit control is clicked, Tab moves
focus, and the viewport shrinks to a phone. A pass means the page works,
not that the right words appear in its source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from browser_checks import focus_check, layout_check, load_checks, mark_unavailable, run_probe, short
from finding_messages import findings_for

BROWSER_CHECKS = [
    "runs_without_errors", "loads_styles_and_script", "local_assets", "product_heading_and_action",
    "semantic_structure", "labeled_fields", "empty_state", "submit_adds_card", "keeps_all_cards",
    "count_updates", "focus_visible", "responsive_layout", "readable_contrast",
]


def grade(obs):
    checks, evidence = load_checks(obs)
    structure = obs.get("structure", {})
    checks["product_heading_and_action"] = bool(structure.get("productHeading") and structure.get("addAction"))
    if not checks["product_heading_and_action"]:
        parts = []
        if not structure.get("productHeading"):
            parts.append("no visible h1/h2 names Northstar Field Notes (saw: " + short(structure.get("headings", [])) + ")")
        if not structure.get("addAction"):
            parts.append("no visible control is named Add observation")
        evidence["product_heading_and_action"] = short(parts)

    checks["semantic_structure"] = all(structure.get(key) for key in ("header", "main", "form"))
    if not checks["semantic_structure"]:
        evidence["semantic_structure"] = "missing " + ", ".join(key for key in ("header", "main", "form") if not structure.get(key))

    fields = obs.get("fields", {})
    unlabeled = [key for key in ("title", "location", "note") if not fields.get(key, {}).get("labeled")]
    checks["labeled_fields"] = not unlabeled
    if unlabeled:
        evidence["labeled_fields"] = "no labeled control for " + ", ".join(unlabeled)

    submissions = obs.get("submissions", [])
    first = submissions[0] if submissions else {}
    second = submissions[1] if len(submissions) > 1 else {}

    def submission_problem(record):
        if not record:
            return "no observation was submitted"
        if not record.get("attempted"):
            if not record.get("filled", {}).get("title") or not record.get("filled", {}).get("note"):
                return "could not find title and note fields to type into"
            return "found no submit control to click"
        if record.get("navigated"):
            return f"clicking {record.get('control')} reloaded the page instead of adding a card"
        card = record.get("card") or {}
        if not card.get("found"):
            return f"after clicking {record.get('control')}, the typed title never appeared on the page"
        if not card.get("complete"):
            return "the new card is missing the location or the note"
        if card.get("containsForm"):
            return "the observation text only appears inside the form"
        return None

    problem = submission_problem(first)
    checks["submit_adds_card"] = problem is None
    if problem:
        evidence["submit_adds_card"] = problem

    if problem is None:
        second_problem = submission_problem(second)
        if second_problem is None and not (obs.get("firstStillShown") or {}).get("complete"):
            second_problem = "the second observation replaced the first instead of adding a card"
    else:
        second_problem = "the first observation could not be added"
    checks["keeps_all_cards"] = second_problem is None
    if second_problem:
        evidence["keeps_all_cards"] = second_problem

    candidates = obs.get("emptyCandidates", [])
    after = (first.get("state") or {}).get("texts", {})
    if not candidates:
        checks["empty_state"] = False
        evidence["empty_state"] = "no empty-state message was visible before the first observation"
    elif checks["submit_adds_card"]:
        hidden = [item for item in candidates if after.get(item["path"]) != item["text"]]
        checks["empty_state"] = bool(hidden)
        if not hidden:
            evidence["empty_state"] = f"\"{candidates[0]['text'][:60]}\" stayed visible after an observation was added"
    else:
        checks["empty_state"] = True

    numbers_one = (first.get("state") or {}).get("numbers", {})
    numbers_two = (second.get("state") or {}).get("numbers", {})
    counted = [path for path, values in numbers_two.items() if 2 in values and 1 in numbers_one.get(path, [])]
    checks["count_updates"] = bool(counted)
    if not counted:
        evidence["count_updates"] = ("no visible number went from 1 to 2 as observations were added"
                                     if checks["keeps_all_cards"] else "needs two observations to be added first")

    checks["focus_visible"], detail = focus_check(obs)
    if detail:
        evidence["focus_visible"] = detail
    checks["responsive_layout"], detail = layout_check(obs)
    if detail:
        evidence["responsive_layout"] = detail
    failures = (obs.get("contrast") or {}).get("failures", [])
    checks["readable_contrast"] = not failures
    if failures:
        evidence["readable_contrast"] = short(f"{item['desc']} at {item['ratio']}:1" for item in failures)
    return checks, evidence


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_static_page.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    checks = {f"has_{name}": (root / name).is_file() for name in ("index.html", "styles.css", "app.js")}
    evidence, infrastructure = {}, []
    if checks["has_index.html"]:
        obs, problem, infra = run_probe("static-page", root)
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
