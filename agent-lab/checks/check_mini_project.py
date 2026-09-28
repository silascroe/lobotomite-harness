#!/usr/bin/env python3
"""Structural smoke check for the Signal Garden mini project; not a visual judge."""

import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_mini_project.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    files = {name: root / name for name in ("index.html", "styles.css", "app.js")}
    checks = {f"has_{name}": path.is_file() for name, path in files.items()}
    html = files["index.html"].read_text(encoding="utf-8", errors="replace") if checks["has_index.html"] else ""
    css = files["styles.css"].read_text(encoding="utf-8", errors="replace") if checks["has_styles.css"] else ""
    js = files["app.js"].read_text(encoding="utf-8", errors="replace") if checks["has_app.js"] else ""
    checks["signal_garden_heading"] = bool(re.search(r"<h1\b[^>]*>[^<]*Signal Garden", html, re.I))
    checks["semantic_main"] = bool(re.search(r"<main\b", html, re.I))
    checks["description"] = bool(re.search(r"<p\b[^>]*>[^<]{10,}", html, re.I))
    checks["button_and_status"] = bool(re.search(r"<button\b", html, re.I)) and bool(re.search(r"(?:\b(?:id|role)=[\"'][^\"']*status|\baria-live=[\"'])", html, re.I))
    checks["local_assets"] = "styles.css" in html and "app.js" in html and not bool(re.search(r"https?://|<link[^>]+(?:fonts|cdn)", html, re.I))
    checks["responsive_css"] = "@media" in css
    checks["focus_style"] = bool(re.search(r":focus(?:-visible)?\b", css))
    checks["click_handler"] = bool(re.search(r"addEventListener\s*\(\s*['\"]click", js))
    checks["updates_status"] = bool(re.search(r"(?:textContent|innerText|innerHTML|setAttribute)\s*(?:=|\()", js)) and bool(re.search(r"(?:getElementById|querySelector)\s*\(", js))
    try:
        checks["script_syntax"] = files["app.js"].is_file() and subprocess.run(
            ["node", "--check", str(files["app.js"])], capture_output=True, timeout=5, check=False
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        checks["script_syntax"] = False
    result = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

