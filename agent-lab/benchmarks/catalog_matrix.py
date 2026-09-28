#!/usr/bin/env python3
"""Run the catalog sequentially against one local model and save durable results."""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "agent-lab" / "tasks"
RUNS = ROOT / "agent-lab" / "runs"
RESULTS = ROOT / "agent-lab" / "benchmarks" / "results"


def build_command(root: Path, task_name: str, profile: dict, level: str, run_id: str) -> list[str]:
    return [
        sys.executable, str(root / "agent-lab/harness/agent_harness.py"),
        "--task-file", str(root / "agent-lab/tasks" / task_name),
        "--task-profile-json", json.dumps(profile, separators=(",", ":")),
        "--reasoning-level", level,
        "--run-id", run_id,
    ]


def summarize(task: str, level: str, run_id: str, returncode: int | None, summary: dict) -> dict:
    evaluation = summary.get("evaluation") or {}
    passed = returncode == 0 and summary.get("status") == "success" and evaluation.get("configured") is True and evaluation.get("passed") is True
    return {
        "task": task, "reasoning_level": level, "run_id": run_id,
        "passed": passed, "status": summary.get("status", "missing_summary"),
        "returncode": returncode, "failure_cause": "" if passed else str(summary.get("blocked_reason") or summary.get("summary") or "no summary"),
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "model_calls": summary.get("model_calls"), "tool_calls": summary.get("tool_calls"),
        "changed_files": summary.get("changed_files", []),
        "validation_passed": summary.get("validation_passed"),
        "evaluator_passed": evaluation.get("passed"),
        "review_status": (summary.get("review") or {}).get("status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*", help="catalog task filenames (default: all)")
    parser.add_argument("--levels", nargs="+", choices=("off", "standard", "deep"), default=["off", "standard", "deep"])
    parser.add_argument("--timeout", type=int, default=600, help="per-run wall timeout in seconds")
    args = parser.parse_args()
    catalog = json.loads((TASKS / "catalog.json").read_text(encoding="utf-8"))["tasks"]
    names = args.tasks or sorted(catalog)
    unknown = set(names) - set(catalog)
    if unknown:
        parser.error(f"unknown catalog tasks: {', '.join(sorted(unknown))}")
    batch_id = datetime.now().strftime("matrix-%Y%m%d-%H%M%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / f"{batch_id}.json"
    records = []
    for task in names:
        title = next((line.lstrip("# ").strip() for line in (TASKS / task).read_text(encoding="utf-8").splitlines() if line.startswith("#")), task)
        profile = {"name": task, "title": title, "description": catalog[task].get("description", ""), "gates": catalog[task]["gates"]}
        for level in args.levels:
            run_id = f"{batch_id}-{task[:3]}-{level}"
            print(f"START {task} {level} {run_id}", flush=True)
            command = build_command(ROOT, task, profile, level, run_id)
            log = RESULTS / f"{run_id}.log"
            try:
                with log.open("w", encoding="utf-8") as stream:
                    completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                returncode = None
            summary_file = RUNS / run_id / "summary.json"
            try:
                summary = json.loads(summary_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                summary = {"status": "timed_out" if returncode is None else "missing_summary", "summary": "run timed out" if returncode is None else "run produced no summary"}
            row = summarize(task, level, run_id, returncode, summary)
            records.append(row)
            output.write_text(json.dumps({"batch_id": batch_id, "model": "local", "results": records}, indent=2), encoding="utf-8")
            print(f"DONE {task} {level}: {row['status']} passed={row['passed']} calls={row['model_calls']}/{row['tool_calls']} seconds={row['elapsed_seconds']}", flush=True)
    print(f"RESULTS {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

