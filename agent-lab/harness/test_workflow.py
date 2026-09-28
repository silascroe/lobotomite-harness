from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("workflow.py")
SPEC = importlib.util.spec_from_file_location("workflow_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WorkflowTests(unittest.TestCase):
    def test_new_workflow_starts_at_intake(self) -> None:
        state = MODULE.new_workflow()

        self.assertEqual(state["phase"], "intake")
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["checkpoint_count"], 0)
        self.assertEqual(state["artifacts"], [])
        self.assertTrue(state["next_action"])
        self.assertTrue(state["updated_at"])

    def test_transition_allows_forward_progress_and_repair_loop(self) -> None:
        state = MODULE.new_workflow()
        state = MODULE.transition(state, "inspect", "The folder is understood.", "Draft the design.")
        state = MODULE.transition(state, "design", "The approach is clear.", "Write the implementation plan.")
        state = MODULE.transition(state, "plan", "The work is decomposed.", "Implement task one.")
        state = MODULE.transition(state, "implement", "The first change is written.", "Run validation.")
        state = MODULE.transition(state, "verify", "The check failed.", "Fix the implementation.")
        state = MODULE.transition(state, "implement", "The fix is written.", "Run validation again.")

        self.assertEqual(state["phase"], "implement")
        self.assertEqual(state["checkpoint_count"], 6)

    def test_invalid_transition_is_rejected(self) -> None:
        state = MODULE.transition(MODULE.new_workflow(), "inspect", "Inspected.", "Design it.")

        with self.assertRaises(MODULE.WorkflowError):
            MODULE.transition(state, "intake", "Backwards.", "Start again.")
        with self.assertRaises(MODULE.WorkflowError):
            MODULE.transition(state, "unknown", "Bad phase.", "Nope.")

    def test_blocked_and_complete_are_terminal_statuses(self) -> None:
        blocked = MODULE.transition(MODULE.new_workflow(), "blocked", "The model endpoint is offline.", "Start the local model.")
        self.assertEqual(blocked["status"], "blocked")

        complete = MODULE.transition(
            MODULE.transition(MODULE.new_workflow(), "review", "The diff was reviewed.", "Finish the run."),
            "complete",
            "The project is ready.",
            "Wait for the next request.",
        )
        self.assertEqual(complete["status"], "complete")

    def test_observe_tool_uses_successful_evidence_only(self) -> None:
        state = MODULE.new_workflow()
        state = MODULE.observe_tool(state, "list_files", {"ok": True})
        self.assertEqual(state["phase"], "inspect")
        state = MODULE.observe_tool(state, "write_file", {"ok": True, "path": "app.py"})
        self.assertEqual(state["phase"], "implement")
        failed = MODULE.observe_tool(state, "run_command", {"ok": False, "exit_code": 1})
        self.assertEqual(failed["phase"], "implement")
        verified = MODULE.observe_tool(state, "run_command", {"ok": True, "exit_code": 0})
        self.assertEqual(verified["phase"], "verify")
        reviewed = MODULE.observe_tool(verified, "git_diff", {"ok": True})
        self.assertEqual(reviewed["phase"], "review")
        finished = MODULE.observe_tool(reviewed, "finish", {"ok": True, "status": "success"})
        self.assertEqual(finished["phase"], "complete")

    def test_artifact_paths_are_relative_and_persistable(self) -> None:
        with self.assertRaises(MODULE.WorkflowError):
            MODULE.transition(MODULE.new_workflow(), "design", "Design.", "Next.", artifacts=["../secret.txt"])
        with self.assertRaises(MODULE.WorkflowError):
            MODULE.transition(MODULE.new_workflow(), "design", "Design.", "Next.", artifacts=["C:\\secret.txt"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            state = MODULE.transition(
                MODULE.new_workflow(),
                "design",
                "The design is recorded.",
                "Plan the implementation.",
                artifacts=["docs/design.md"],
            )
            MODULE.save_workflow(path, state)
            self.assertEqual(MODULE.load_workflow(path)["artifacts"], ["docs/design.md"])
            path.write_text("not json", encoding="utf-8")
            fallback = MODULE.load_workflow(path)
            self.assertEqual(fallback["phase"], "intake")

    def test_snapshot_is_json_serializable(self) -> None:
        state = MODULE.transition(MODULE.new_workflow(), "inspect", "Inspected.", "Design.")
        json.dumps(state)


if __name__ == "__main__":
    unittest.main()

