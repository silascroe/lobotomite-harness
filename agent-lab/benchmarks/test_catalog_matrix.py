import json
import unittest
from pathlib import Path

from catalog_matrix import build_command, summarize


class MatrixTest(unittest.TestCase):
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

