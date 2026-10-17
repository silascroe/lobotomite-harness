#!/usr/bin/env python3
"""Re-grade recorded runs with the current catalog checkers.

Each run's final project is graded again by the checker that the current
catalog names for its task, and the result is set beside the verdict the run
recorded at the time. Use it when a checker changes, to see what the old
numbers meant. Runs are read, never modified.

The checkers execute model-written code (a browser loads the page; Node
imports the module or runs the validator), as they do during a run.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "agent-lab" / "runs"
RESULTS = ROOT / "agent-lab" / "benchmarks" / "results"
CATALOG = ROOT / "agent-lab" / "tasks" / "catalog.json"


def recorded_runs(prefixes):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["tasks"]
    for run_dir in sorted(RUNS.iterdir()):
        if prefixes and not any(run_dir.name.startswith(prefix) for prefix in prefixes):
            continue
        try:
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        task = (summary.get("task_profile") or {}).get("name")
        project = run_dir / "project"
        if task not in catalog or not project.is_dir():
            continue
        evaluation = summary.get("evaluation") or {}
        yield {
            "run_id": run_dir.name,
            "task": task,
            "reasoning": (summary.get("reasoning") or {}).get("level"),
            "status": summary.get("status"),
            "recorded_passed": evaluation.get("passed") if evaluation.get("configured") else None,
            "evaluator": catalog[task]["gates"]["evaluator"],
            "project": project,
        }


def regrade(run):
    script = ROOT / run["evaluator"]
    try:
        completed = subprocess.run(
            [sys.executable, str(script), str(run["project"])], cwd=script.parent,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False,
        )
        report = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {**run, "project": str(run["project"]), "passed": None, "error": str(exc)[:200]}
    findings = report.get("findings", [])
    return {
        **run, "project": str(run["project"]), "passed": report.get("passed"),
        "failed": [item["id"] for item in findings if item.get("kind") != "infrastructure"],
        "infrastructure": [item["id"] for item in findings if item.get("kind") == "infrastructure"],
        "evidence": {item["id"]: item["evidence"] for item in findings if item.get("evidence")},
    }


def report_text(rows):
    lines = []
    by_task = defaultdict(list)
    for row in rows:
        by_task[row["task"]].append(row)
    lines.append("task | graded runs | recorded pass | current pass | passed then, fails now | failed then, passes now")
    for task, items in sorted(by_task.items()):
        graded = [row for row in items if row["recorded_passed"] is not None and row["passed"] is not None]
        lines.append(" | ".join(str(value) for value in (
            task, len(graded),
            sum(row["recorded_passed"] for row in graded), sum(row["passed"] for row in graded),
            sum(row["recorded_passed"] and not row["passed"] for row in graded),
            sum(row["passed"] and not row["recorded_passed"] for row in graded),
        )))
    failures = Counter(check for row in rows for check in row.get("failed", []))
    lines.append("")
    lines.append("most common current failures: " + ", ".join(f"{name} {count}" for name, count in failures.most_common(12)))
    flipped = [row for row in rows if row["recorded_passed"] and row["passed"] is False]
    if flipped:
        lines.append("")
        lines.append("recorded passes that fail now:")
        for row in flipped:
            lines.append(f"  {row['run_id']}: " + ", ".join(row["failed"]))
    broken = [row for row in rows if row["passed"] is None or row.get("infrastructure")]
    if broken:
        lines.append("")
        lines.append("could not grade: " + ", ".join(row["run_id"] for row in broken))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prefixes", nargs="*", help="only runs whose id starts with one of these")
    parser.add_argument("--workers", type=int, default=3, help="checkers to run at once (each may start a browser)")
    args = parser.parse_args()
    runs = list(recorded_runs(args.prefixes))
    if not runs:
        print("no recorded runs matched", file=sys.stderr)
        return 1
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        rows = list(pool.map(regrade, runs))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"regrade-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(report_text(rows))
    print(f"\nsaved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
