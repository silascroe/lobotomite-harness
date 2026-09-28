#!/usr/bin/env python3
"""Check both the report and the behavior of its generated validator."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run_validator(script: Path, report: dict, directory: Path) -> int | None:
    (directory / "validate-report.mjs").write_bytes(script.read_bytes())
    (directory / "health-report.json").write_text(json.dumps(report), encoding="utf-8")
    try:
        completed = subprocess.run(
            ["node", "validate-report.mjs"], cwd=directory,
            capture_output=True, timeout=5, check=False,
        )
        return completed.returncode
    except (OSError, subprocess.TimeoutExpired):
        return None


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
    checks["validator_accepts_valid"] = False
    checks["validator_rejects_bad_status"] = False
    checks["validator_rejects_bad_shape"] = False
    if validator.is_file() and valid_report:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            checks["validator_accepts_valid"] = run_validator(validator, report, work) == 0
            checks["validator_rejects_bad_status"] = run_validator(validator, {**report, "status": "bad"}, work) not in (0, None)
            checks["validator_rejects_bad_shape"] = run_validator(validator, {**report, "checks": []}, work) not in (0, None)
    result = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

