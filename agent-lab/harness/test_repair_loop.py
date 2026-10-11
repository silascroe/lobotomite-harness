import json
import unittest
from repair_loop import RepairLoop


def evaluation(ids):
    return {"passed": not ids, "findings": [{"id": key, "message": key, "artifacts": []} for key in ids]}


class RepairTests(unittest.TestCase):
    def test_progress_pass_and_no_reopening(self):
        loop = RepairLoop()
        self.assertEqual(loop.recheck(evaluation(["a", "b"]), "a" * 64, 18), "repair_episode_started")
        loop.reserve_turn(True)
        loop.recheck(evaluation(["b"]), "b" * 64, 19)
        self.assertTrue(loop.active)
        loop.recheck(evaluation(["b"]), "c" * 64, 20)
        self.assertTrue(loop.active)
        loop.recheck(evaluation([]), "c" * 64, 21)
        self.assertEqual(loop.state["status"], "passed")
        with self.assertRaises(ValueError):
            loop.recheck(evaluation(["a"]), "c" * 64, 22)

    def test_no_progress(self):
        loop = RepairLoop()
        loop.recheck(evaluation(["a"]), "a" * 64, 1)
        loop.recheck(evaluation(["a"]), "a" * 64, 2)
        self.assertEqual(loop.state["status"], "no_progress")

    def test_budget_survives_snapshot_and_cannot_exceed_six(self):
        loop = RepairLoop()
        loop.recheck(evaluation(["a"]), "a" * 64, 1, allowance=99)
        for _ in range(5):
            loop.reserve_turn(True)
        restored = RepairLoop(json.loads(json.dumps(loop.snapshot())))
        self.assertEqual(restored.remaining, 1)
        restored.reserve_turn(True)
        with self.assertRaises(ValueError):
            restored.reserve_turn(True)
        restored.finish("budget_exhausted", "exhausted")
        self.assertFalse(restored.active)

    def test_invalid_snapshot(self):
        for state in [{}, {"schema_version": 2}, []]:
            with self.assertRaises(ValueError):
                RepairLoop(state)
        loop = RepairLoop()
        loop.recheck(evaluation(["a"]), "a" * 64, 1)
        for key, value in [("extension_turns_used", -1), ("extension_limit", 7),
                           ("finding_fingerprint", "0" * 64), ("findings", []),
                           ("initial_finding_ids", []), ("status", "passed")]:
            state = loop.snapshot()
            state[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                RepairLoop(state)
