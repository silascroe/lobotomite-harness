"""Strict, bounded normalization of untrusted external checker reports."""
import json
import re
from pathlib import PurePosixPath


class EvaluationError(ValueError):
    pass


def normalize_report(raw: str, exit_code: int) -> dict:
    try:
        report = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise EvaluationError("evaluator returned invalid JSON") from exc
    if not isinstance(report, dict) or type(report.get("passed")) is not bool:
        raise EvaluationError("evaluator report requires boolean passed")
    checks = report.get("checks", {})
    if not isinstance(checks, dict) or len(checks) > 100 or any(
        not isinstance(key, str) or not key or len(key) > 160 or type(value) is not bool
        for key, value in checks.items()
    ):
        raise EvaluationError("evaluator checks must be bounded string-to-boolean entries")
    supplied = report.get("findings", [])
    if not isinstance(supplied, list) or len(supplied) > 100:
        raise EvaluationError("evaluator findings must be a bounded array")
    findings = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise EvaluationError("invalid evaluator finding")
        key, message = item.get("id"), item.get("message")
        if not isinstance(key, str) or not key or len(key) > 160 or key in findings:
            raise EvaluationError("invalid or duplicate evaluator finding ID")
        if not isinstance(message, str) or not message.strip():
            raise EvaluationError("finding requires a message")
        kind = item.get("kind", "requirement")
        if not isinstance(kind, str) or kind not in {"requirement", "infrastructure"}:
            raise EvaluationError("invalid finding kind")
        hints = item.get("artifacts", [])
        if not isinstance(hints, list) or len(hints) > 20:
            raise EvaluationError("invalid artifact hints")
        for hint in hints:
            if (not isinstance(hint, str) or not hint.strip() or len(hint) > 240
                    or any(ord(ch) < 32 for ch in hint)
                    or ":" in hint or "\\" in hint or PurePosixPath(hint).is_absolute()
                    or ".." in PurePosixPath(hint).parts or hint == "."):
                raise EvaluationError("unsafe artifact hint")
        evidence = item.get("evidence", "")
        if not isinstance(evidence, str):
            raise EvaluationError("invalid finding evidence")
        findings[key] = {"id": key, "message": message[:600], "artifacts": hints,
                         "evidence": evidence[:600], "kind": kind}
    if report["passed"] and (any(not value for value in checks.values()) or findings):
        raise EvaluationError("contradictory evaluator pass report")
    if any(checks.get(key) is True for key in findings):
        raise EvaluationError("finding contradicts a passing check")
    if not report["passed"] and checks and all(checks.values()) and not findings:
        raise EvaluationError("failure contradicts passing checks")
    if exit_code not in (0, 1) or (exit_code == 0) != report["passed"]:
        raise EvaluationError("evaluator exit code contradicts report or indicates infrastructure failure")
    for key, value in checks.items():
        if not value and key not in findings:
            findings[key] = {"id": key, "message": "Requirement failed: " + re.sub(r"[_-]", " ", key),
                             "artifacts": [], "kind": "requirement"}
    if not report["passed"] and not findings:
        findings["evaluator_failed"] = {"id": "evaluator_failed", "message": "The external evaluator rejected the project.",
                                         "artifacts": [], "kind": "requirement"}
    if any(item["kind"] == "infrastructure" for item in findings.values()):
        raise EvaluationError("evaluator reported an infrastructure failure")
    return {"schema_version": 1, "passed": report["passed"], "checks": checks,
            "findings": sorted(findings.values(), key=lambda item: item["id"])}
