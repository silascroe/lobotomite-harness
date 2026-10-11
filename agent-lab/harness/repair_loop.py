"""One durable repair episode; no tools or filesystem policy live here."""
import copy
import hashlib
import json
import uuid
from evaluation import normalize_report

TERMINAL = {"passed", "blocked", "no_progress", "budget_exhausted"}


class RepairLoop:
    def __init__(self, snapshot=None):
        self.state = None
        if snapshot is not None:
            self._validate(snapshot)
            self.state = copy.deepcopy(snapshot)

    @staticmethod
    def _validate(state):
        if (not isinstance(state, dict) or type(state.get("schema_version")) is not int or state.get("schema_version") != 1
                or not isinstance(state.get("status"), str) or state["status"] not in TERMINAL | {"active"}
                or not isinstance(state.get("episode_id"), str) or not state["episode_id"]):
            raise ValueError("invalid repair snapshot")
        for key in ("trigger_turn", "repair_episode_turns", "extension_turns_used", "extension_limit"):
            if type(state.get(key)) is not int or state[key] < 0:
                raise ValueError("invalid repair budget snapshot")
        if not 0 <= state["extension_turns_used"] <= state["extension_limit"] <= 6:
            raise ValueError("invalid repair extension allowance")
        if state["repair_episode_turns"] < state["extension_turns_used"]:
            raise ValueError("invalid repair turn counters")
        for key in ("initial_finding_ids", "final_finding_ids"):
            if (not isinstance(state.get(key), list) or len(state[key]) > 100
                    or any(not isinstance(v, str) or not v or len(v) > 160 for v in state[key])
                    or state[key] != sorted(set(state[key]))):
                raise ValueError("invalid repair findings snapshot")
        if not isinstance(state.get("findings"), list):
            raise ValueError("invalid repair findings snapshot")
        if (type(state.get("latest_evaluator_passed")) is not bool
                or not isinstance(state.get("outcome"), str) or len(state["outcome"]) > 800):
            raise ValueError("invalid repair outcome snapshot")
        normalized = normalize_report(json.dumps({"passed": state["latest_evaluator_passed"],
                                                  "findings": state["findings"]}),
                                      0 if state["latest_evaluator_passed"] else 1)
        if sorted(item["id"] for item in normalized["findings"]) != state["final_finding_ids"]:
            raise ValueError("inconsistent repair findings snapshot")
        for key in ("project_fingerprint", "finding_fingerprint"):
            if (not isinstance(state.get(key), str) or len(state[key]) != 64
                    or any(ch not in "0123456789abcdef" for ch in state[key])):
                raise ValueError("invalid repair fingerprint")
        if not state["initial_finding_ids"] or state["trigger_turn"] < 1 or state["repair_episode_turns"] < 1:
            raise ValueError("invalid repair trigger snapshot")
        digest = hashlib.sha256(json.dumps(state["final_finding_ids"]).encode()).hexdigest()
        if digest != state["finding_fingerprint"]:
            raise ValueError("inconsistent repair fingerprint")
        if (state["status"] == "passed") != state["latest_evaluator_passed"]:
            raise ValueError("inconsistent repair outcome")

    @property
    def active(self):
        return self.state is not None and self.state["status"] == "active"

    @property
    def remaining(self):
        return self.state["extension_limit"] - self.state["extension_turns_used"] if self.active else 0

    def snapshot(self):
        return copy.deepcopy(self.state)

    def view(self):
        if self.state is None:
            return None
        return {key: copy.deepcopy(value) for key, value in self.state.items() if key != "findings"}

    def recheck(self, evaluation, project_fingerprint, turn, allowance=6):
        findings = evaluation["findings"]
        ids = sorted(item["id"] for item in findings)
        digest = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
        if self.state is None:
            if evaluation["passed"]:
                return None
            self.state = {"schema_version": 1, "episode_id": uuid.uuid4().hex, "status": "active",
                          "trigger_turn": turn, "initial_finding_ids": ids, "final_finding_ids": ids,
                          "findings": findings, "project_fingerprint": project_fingerprint,
                          "finding_fingerprint": digest, "extension_limit": max(0, min(6, int(allowance))),
                          "repair_episode_turns": 1, "extension_turns_used": 0, "outcome": "",
                          "latest_evaluator_passed": False}
            return "repair_episode_started"
        if not self.active:
            raise ValueError("a terminal repair episode cannot reopen")
        unchanged = digest == self.state["finding_fingerprint"] and project_fingerprint == self.state["project_fingerprint"]
        self.state.update(findings=findings, final_finding_ids=ids, project_fingerprint=project_fingerprint,
                          finding_fingerprint=digest, latest_evaluator_passed=evaluation["passed"],
                          progress_changed=not unchanged)
        if evaluation["passed"]:
            self.finish("passed", "external evaluator passed")
        elif unchanged:
            self.finish("no_progress", "same findings against an unchanged project")
        return "repair_rechecked"

    def reserve_turn(self, extension=False):
        if not self.active:
            return
        if extension and not self.remaining:
            raise ValueError("repair extension exhausted")
        self.state["repair_episode_turns"] += 1
        self.state["extension_turns_used"] += int(extension)

    def finish(self, status, reason):
        if self.active:
            if status not in TERMINAL:
                raise ValueError("invalid repair outcome")
            self.state.update(status=status, outcome=reason[:800])
