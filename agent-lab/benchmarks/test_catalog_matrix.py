import json
import unittest
import tempfile
from pathlib import Path

from catalog_matrix import build_command, summarize, load_run_summary


class MatrixTest(unittest.TestCase):
    def test_timeout_preserves_active_repair_and_does_not_claim_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "progress.json").write_text(json.dumps({"first_pass_passed": False, "model_calls": 20,
                                                           "evaluation": {"configured": True, "passed": False}}))
            (root / "repair.json").write_text(json.dumps({"status": "active", "extension_turns_used": 2}))
            row = summarize("task", "deep", "run", None, load_run_summary(root, None))
            self.assertFalse(row["passed"])
            self.assertEqual(row["status"], "timed_out")
            self.assertEqual(row["repair_outcome"], "active")
            self.assertEqual(row["extension_turns_used"], 2)
            self.assertEqual(row["model_calls"], 20)
    def test_repaired_pass_is_not_first_pass(self):
        item = summarize("task", "off", "run", 0, {
            "status": "success", "evaluation": {"configured": True, "passed": True},
            "first_pass_passed": False,
            "repair_episode": {"status": "passed", "extension_turns_used": 3,
                               "initial_finding_ids": ["focus"], "final_finding_ids": []}})
        self.assertTrue(item["passed"])
        self.assertFalse(item["first_pass_passed"])
        self.assertTrue(item["repair_attempted"])
        self.assertEqual(item["extension_turns_used"], 3)
        self.assertEqual(item["repair_outcome"], "passed")
    def test_command_scopes_catalog_profile_and_reasoning(self):
        root = Path("C:/lab")
        profile = {"name": "002-file-roundtrip.md", "title": "File round-trip smoke test", "gates": {"evaluator": "agent-lab/checks/check_file_roundtrip.py"}}
        command = build_command(root, "002-file-roundtrip.md", profile, "deep", "matrix-002-deep")
        self.assertEqual(command[2:4], ["--task-file", str(root / "agent-lab/tasks/002-file-roundtrip.md")])
        self.assertEqual(command[command.index("--reasoning-level") + 1], "deep")
        self.assertEqual(command[command.index("--run-id") + 1], "matrix-002-deep")
        self.assertEqual(json.loads(command[command.index("--task-profile-json") + 1]), profile)

    def test_summary_does_not_confuse_process_exit_with_evaluator_success(self):
        item = summarize("002-file-roundtrip.md", "off", "matrix-002-off", 2, {
            "status": "blocked", "elapsed_seconds": 12.5, "model_calls": 4, "tool_calls": 3,
            "changed_files": ["agent-check.md"], "blocked_reason": "missing module",
            "evaluation": {"configured": True, "passed": False},
        })
        self.assertFalse(item["passed"])
        self.assertEqual(item["failure_cause"], "missing module")
        self.assertEqual(item["changed_files"], ["agent-check.md"])


if __name__ == "__main__":
    unittest.main()
