"""Run the behavioral browser probe against a project and read its observations.

The project is served from a private loopback HTTP server for the duration of
one probe, because module scripts and stylesheet inspection do not work from
file:// URLs. The server refuses anything outside the project directory,
including symlinks that point elsewhere, and never lists directories.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

PROBE = Path(__file__).with_name("browser_probe.mjs")
PROBE_TIMEOUT_SECONDS = 45


class _ProjectHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        translated = Path(super().translate_path(path)).resolve()
        root = Path(self.directory).resolve()
        if translated != root and root not in translated.parents:
            return str(root / "__outside_project__")
        return str(translated)

    def list_directory(self, path):
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


@contextmanager
def serve(root: Path):
    handler = functools.partial(_ProjectHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def run_probe(scenario: str, root: Path, page: str = "index.html"):
    """Return (observations, problem, infrastructure).

    observations is None when the probe could not finish; problem then says
    why, and infrastructure says whether the fault is the environment's
    (no browser, no Node) rather than the project's.
    """
    with serve(root) as origin:
        try:
            completed = subprocess.run(
                ["node", str(PROBE), scenario, f"{origin}/{page}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=PROBE_TIMEOUT_SECONDS, check=False, env={**os.environ},
            )
        except FileNotFoundError:
            return None, "Node.js is not installed or not on PATH", True
        except subprocess.TimeoutExpired:
            return None, "the browser probe timed out", True
        except OSError as exc:
            return None, f"could not run the browser probe: {exc}", True
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        report = json.loads(lines[-1])
    except (IndexError, ValueError):
        detail = (completed.stderr or completed.stdout or "no output").strip()[:300]
        return None, f"the browser probe returned no report: {detail}", True
    if not report.get("ok"):
        return None, str(report.get("error") or "browser probe failed"), bool(report.get("infrastructure"))
    return report["observations"], None, False


def short(items, limit=3):
    items = [str(item) for item in items if item]
    text = "; ".join(items[:limit])
    return text + (f"; and {len(items) - limit} more" if len(items) > limit else "")


def load_checks(obs):
    """Checks every browser task shares: clean load, own assets, no remote requests."""
    load = obs.get("load", {})
    requests = load.get("requests", {})
    broken = [f"{path} returned {status}" for path, status in requests.items()
              if status >= 400 and path != "/favicon.ico"]
    checks, evidence = {}, {}
    exceptions = list(dict.fromkeys(load.get("exceptions", [])))
    checks["runs_without_errors"] = not exceptions and not broken
    if not checks["runs_without_errors"]:
        evidence["runs_without_errors"] = short(exceptions + broken)
    missing = [name for name in ("styles.css", "app.js") if requests.get(f"/{name}") != 200]
    checks["loads_styles_and_script"] = not missing
    if missing:
        evidence["loads_styles_and_script"] = "the page never loaded " + " or ".join(missing)
    remote = load.get("remote", [])
    checks["local_assets"] = not remote
    if remote:
        evidence["local_assets"] = "blocked requests to " + short(remote)
    return checks, evidence


def focus_check(obs):
    stops = obs.get("focus", [])
    if not stops:
        return False, "pressing Tab never focused a control"
    missing = [stop["desc"] for stop in stops if not stop.get("indicator")]
    if missing:
        return False, "no visible change when focused: " + short(missing)
    return True, None


def layout_check(obs):
    phone, desktop = obs.get("phone") or {}, obs.get("desktop") or {}
    problems = []
    if phone.get("width", 0) > 420:
        hint = "" if phone.get("viewportMeta") else " (no viewport meta tag)"
        problems.append(f"on a 375px phone the page lays out {phone['width']}px wide{hint}")
    elif phone.get("scrollWidth", 0) > phone.get("width", 0) + 1:
        problems.append(f"on a 375px phone the content is {phone['scrollWidth']}px wide and scrolls sideways")
    problems += [f"phone: {item}" for item in phone.get("offenders", [])]
    if desktop.get("scrollWidth", 0) > desktop.get("width", 0) + 1:
        problems.append(f"at 1280px the content is {desktop['scrollWidth']}px wide")
    problems += [f"desktop: {item}" for item in desktop.get("offenders", [])]
    return (not problems), (short(problems) if problems else None)


def mark_unavailable(checks, keys, problem, infrastructure, evidence):
    for key in keys:
        checks[key] = False
        evidence[key] = problem
    return list(keys) if infrastructure else []
