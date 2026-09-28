from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("approval.py")
SPEC = importlib.util.spec_from_file_location("approval_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ApprovalTests(unittest.TestCase):
    def test_mode_is_normalized_and_unknown_values_fail_closed_to_auto(self) -> None:
        self.assertEqual(MODULE.normalize_mode("confirm"), "confirm")
        self.assertEqual(MODULE.normalize_mode("wat"), "auto")
        self.assertEqual(MODULE.normalize_mode(None), "auto")

    def test_only_mutating_actions_need_confirmation(self) -> None:
        self.assertTrue(MODULE.requires_approval("write_file", "confirm"))
        self.assertTrue(MODULE.requires_approval("run_command", "confirm"))
        self.assertFalse(MODULE.requires_approval("read_file", "confirm"))
        self.assertFalse(MODULE.requires_approval("write_file", "auto"))

    def test_request_keeps_exact_action_but_public_view_redacts_arguments(self) -> None:
        request = MODULE.new_request(
            "write_file",
            {"path": "index.html", "content": "secret project content"},
            turn=4,
            step=4,
        )

        public = MODULE.public_request(request)
        self.assertEqual(request["args"]["content"], "secret project content")
        self.assertEqual(public["action"], "write_file")
        self.assertEqual(public["path"], "index.html")
        self.assertNotIn("args", public)

    def test_resolution_is_audit_friendly_and_idempotent(self) -> None:
        request = MODULE.new_request("run_command", {"command": "node --check app.js"}, turn=2, step=2)
        resolved = MODULE.resolve_request(request, "approve")

        self.assertEqual(resolved["status"], "approved")
        self.assertEqual(resolved["decision"], "approve")
        self.assertEqual(resolved["args"], request["args"])
        self.assertEqual(MODULE.resolve_request(resolved, "approve")["status"], "approved")


if __name__ == "__main__":
    unittest.main()

