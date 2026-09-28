#!/usr/bin/env python3
"""Small external checker for the first benchmark task."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_static_page.py PROJECT_DIR", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    checks: dict[str, bool] = {}
    required = ["index.html", "styles.css", "app.js"]
    for name in required:
        checks[f"has_{name}"] = (root / name).is_file()
    if checks["has_index.html"]:
        html = (root / "index.html").read_text(encoding="utf-8", errors="replace")
        checks["has_semantic_sections"] = all(tag in html.lower() for tag in ("<header", "<main", "<form"))
        checks["links_css"] = "styles.css" in html
        checks["links_js"] = "app.js" in html
        checks["has_observation_fields"] = all(token in html.lower() for token in ("title", "location", "note"))
    else:
        checks.update({"has_semantic_sections": False, "links_css": False, "links_js": False, "has_observation_fields": False})
    if checks["has_styles.css"]:
        css = (root / "styles.css").read_text(encoding="utf-8", errors="replace")
        checks["has_responsive_css"] = "@media" in css
        checks["has_focus_style"] = ":focus" in css
    else:
        checks.update({"has_responsive_css": False, "has_focus_style": False})
    if checks["has_app.js"]:
        js = (root / "app.js").read_text(encoding="utf-8", errors="replace")
        checks["handles_submit"] = bool(re.search(r"addEventListener\s*\(\s*['\"]submit", js))
        checks["updates_count_or_cards"] = bool(re.search(r"(count|card|observation)", js, re.I))
    else:
        checks.update({"handles_submit": False, "updates_count_or_cards": False})
    result = {"passed": all(checks.values()), "checks": checks}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

