#!/usr/bin/env python3
"""Check both the report and the behavior of its generated validator.

The validator is copied into a scratch directory and run against the
project's own report and against broken variants of it; it must accept the
first and reject each of the others.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from finding_messages import findings_for


def run_validator(script: Path, report: dict, directory: Path):
    """Return (exit code or None, stdout) for one run against the given report."""
    (directory / "validate-report.mjs").write_bytes(script.read_bytes())
    (directory / "health-report.json").write_text(json.dumps(report), encoding="utf-8")
    try:
        completed = subprocess.run(
            ["node", "validate-report.mjs"], cwd=directory,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
        )
        return completed.returncode, completed.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_structured_validation.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    report_file = root / "health-report.json"
    validator = root / "validate-report.mjs"
    checks = {"has_report": report_file.is_file(), "has_validator": validator.is_file()}
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = None
    checks["valid_json_object"] = isinstance(report, dict)
    checks["status_ok"] = isinstance(report, dict) and report.get("status") == "ok"
    entries = report.get("checks") if isinstance(report, dict) else None
    checks["two_named_checks"] = isinstance(entries, list) and len(entries) >= 2 and all(
        isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
        for item in entries
    )
    checks["generated_for"] = isinstance(report, dict) and isinstance(report.get("generated_for"), str) and bool(report["generated_for"].strip())
    valid_report = all(checks.values())
    behaviors = {
        "validator_accepts_valid": (lambda r: r, True, "the project's own valid report"),
        "validator_rejects_bad_status": (lambda r: {**r, "status": "bad"}, False, 'status set to "bad"'),
        "validator_rejects_bad_shape": (lambda r: {**r, "checks": []}, False, "an empty checks array"),
        "validator_rejects_unnamed_check": (lambda r: {**r, "checks": [r["checks"][0], {"status": "ok"}]}, False,
                                            "a check without a name"),
        "validator_rejects_missing_generated_for": (lambda r: {k: v for k, v in r.items() if k != "generated_for"},
                                                    False, "generated_for removed"),
    }
    for key in behaviors:
        checks[key] = False
    checks["validator_prints_success"] = False
    infrastructure, evidence = [], {}
    if validator.is_file() and valid_report:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for key, (variant, accept, label) in behaviors.items():
                code, stdout = run_validator(validator, variant(report), work)
                if code is None:
                    infrastructure.append(key)
                    evidence[key] = "Node did not run the validator"
                    continue
                checks[key] = code == 0 if accept else code != 0
                if not checks[key]:
                    evidence[key] = f"with {label} it exited {code}"
                if key == "validator_accepts_valid":
                    checks["validator_prints_success"] = code == 0 and bool(stdout.strip())
                    if code == 0 and not stdout.strip():
                        evidence["validator_prints_success"] = "a valid report produced no output"
    elif validator.is_file():
        for key in list(behaviors) + ["validator_prints_success"]:
            evidence[key] = "the report itself must be valid before the validator can be exercised"
    result = {"passed": all(checks.values()), "checks": checks,
              "findings": findings_for(checks, infrastructure, evidence)}
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
