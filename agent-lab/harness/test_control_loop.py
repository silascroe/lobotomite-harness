from __future__ import annotations

import json
import unittest

from control_loop import RecoveryController, action_fingerprint


class RecoveryControllerTests(unittest.TestCase):
    def test_action_fingerprint_ignores_argument_key_order(self) -> None:
        first = action_fingerprint("write_file", {"path": "index.html", "content": "ok"})
        second = action_fingerprint("write_file", {"content": "ok", "path": "index.html"})

        self.assertEqual(first, second)
        self.assertNotEqual(first, action_fingerprint("write_file", {"path": "index.html", "content": "changed"}))

    def test_same_failure_gets_one_retry_then_stops(self) -> None:
        controller = RecoveryController(max_retries_per_failure=1)

        retry = controller.record_failure("invalid_model_action", "Return one JSON object.")
        stop = controller.record_failure("invalid_model_action", "Return one JSON object.")

        self.assertTrue(retry.retry)
        self.assertFalse(retry.stop)
        self.assertEqual(retry.attempt, 1)
        self.assertFalse(stop.retry)
        self.assertTrue(stop.stop)
        self.assertEqual(stop.attempt, 2)

    def test_different_failure_gets_a_fresh_retry(self) -> None:
        controller = RecoveryController(max_retries_per_failure=1)
        controller.record_failure("tool_failure", "file missing")
        controller.record_failure("tool_failure", "file missing")

        retry = controller.record_failure("tool_failure", "permission denied")

        self.assertTrue(retry.retry)
        self.assertEqual(retry.attempt, 1)

    def test_consecutive_duplicate_action_is_reported_before_dispatch(self) -> None:
        controller = RecoveryController(max_duplicate_action_retries=1)
        args = {"path": "index.html"}

        self.assertIsNone(controller.observe_action("read_file", args))
        retry = controller.observe_action("read_file", args)
        stop = controller.observe_action("read_file", args)

        self.assertIsNotNone(retry)
        self.assertTrue(retry.retry)
        self.assertEqual(retry.attempt, 1)
        self.assertIsNotNone(stop)
        self.assertTrue(stop.stop)
        self.assertEqual(stop.attempt, 2)

    def test_different_action_resets_consecutive_duplicate_count(self) -> None:
        controller = RecoveryController(max_duplicate_action_retries=1)
        args = {"path": "index.html"}
        controller.observe_action("read_file", args)
        controller.observe_action("read_file", args)

        self.assertIsNone(controller.observe_action("list_files", {"path": "."}))
        self.assertIsNone(controller.observe_action("read_file", args))
        retry = controller.observe_action("read_file", args)

        self.assertTrue(retry.retry)
        self.assertEqual(retry.attempt, 1)

    def test_snapshot_round_trips_and_is_json_safe(self) -> None:
        controller = RecoveryController()
        controller.record_failure("finish_rejected", "workflow evidence missing: plan")
        controller.observe_action("read_file", {"path": "README.md"})
        snapshot = controller.snapshot()

        json.dumps(snapshot)
        restored = RecoveryController.from_snapshot(snapshot)

        self.assertEqual(restored.snapshot(), snapshot)

    def test_new_interactive_turn_clears_transient_recovery_state(self) -> None:
        controller = RecoveryController()
        controller.record_failure("invalid_model_action", "bad JSON")
        controller.observe_action("read_file", {"path": "README.md"})

        controller.reset_for_turn()

        retry = controller.record_failure("invalid_model_action", "bad JSON")
        self.assertTrue(retry.retry)
        self.assertIsNone(controller.observe_action("read_file", {"path": "README.md"}))


if __name__ == "__main__":
    unittest.main()

