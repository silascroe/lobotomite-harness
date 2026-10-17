#!/usr/bin/env python3
"""Independent content checks for the file round-trip preset.

The module is imported by Node and its exported value is read, so any valid
way of exporting status = "ok" passes and a lookalike that is not exported
does not.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from finding_messages import findings_for

MARKER = "agent-lab-status:"
IMPORT_SCRIPT = (
    "import(process.argv[1]).then(m => process.stdout.write(%r + JSON.stringify(m.status ?? null)),"
    " e => { process.stderr.write(String(e && e.message || e)); process.exit(1); });" % MARKER
)


def imported_status(module: Path):
    """Return (value, problem, infrastructure) for the module's exported status."""
    try:
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", IMPORT_SCRIPT, module.as_uri()],
            cwd=module.parent, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"could not run Node: {exc}"[:200], True
    if completed.returncode != 0:
        return None, "importing it failed: " + (completed.stderr.strip().splitlines() or ["unknown error"])[0][:200], False
    output = completed.stdout
    if MARKER not in output:
        return None, "importing it produced no result", False
    try:
        return json.loads(output.split(MARKER, 1)[1]), None, False
    except ValueError:
        return None, "could not read the exported value", False


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_file_roundtrip.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    note = root / "agent-check.md"
    module = root / "agent-check.mjs"
    checks = {"has_note": note.is_file(), "has_module": module.is_file()}
    note_text = note.read_text(encoding="utf-8", errors="replace") if note.is_file() else ""
    checks["note_title"] = bool(re.search(r"(?m)^#\s+\S", note_text))
    checks["note_purpose"] = bool(re.search(r"(?m)^(?!\s*(?:#|[-*]))\s*\S.{20,}$", note_text))
    checks["three_checklist_items"] = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+(?:\[[ xX]\]\s*)?\S", note_text)) >= 3
    infrastructure, evidence = [], {}
    infra = False
    if module.is_file():
        value, problem, infra = imported_status(module)
        checks["exports_ok_status"] = problem is None and value == "ok"
        if problem:
            evidence["exports_ok_status"] = problem
        elif value != "ok":
            evidence["exports_ok_status"] = f"the module exports status = {json.dumps(value)}"
    else:
        checks["exports_ok_status"] = False
    if infra:
        infrastructure.append("exports_ok_status")
    try:
        checks["module_syntax"] = module.is_file() and subprocess.run(
            ["node", "--check", str(module)], capture_output=True, timeout=5, check=False
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        checks["module_syntax"] = False
        infrastructure.append("module_syntax")
    report = {"passed": all(checks.values()), "checks": checks,
              "findings": findings_for(checks, infrastructure, evidence)}
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
