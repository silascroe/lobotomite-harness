#!/usr/bin/env python3
"""Independent content checks for the file round-trip preset."""

import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_file_roundtrip.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    note = root / "agent-check.md"
    module = root / "agent-check.mjs"
    checks = {"has_note": note.is_file(), "has_module": module.is_file()}
    note_text = note.read_text(encoding="utf-8", errors="replace") if note.is_file() else ""
    js = module.read_text(encoding="utf-8", errors="replace") if module.is_file() else ""
    checks["note_title"] = bool(re.search(r"(?m)^#\s+\S", note_text))
    checks["note_purpose"] = bool(re.search(r"(?m)^(?!\s*(?:#|[-*]))\s*\S.{20,}$", note_text))
    checks["three_checklist_items"] = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+(?:\[[ xX]\]\s*)?\S", note_text)) >= 3
    checks["exports_ok_status"] = bool(re.search(r"\bexport\s+(?:const|let)\s+status\s*=\s*['\"]ok['\"]", js))
    try:
        checks["module_syntax"] = module.is_file() and subprocess.run(
            ["node", "--check", str(module)], capture_output=True, timeout=5, check=False
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        checks["module_syntax"] = False
    report = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

