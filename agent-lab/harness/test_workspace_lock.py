from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workspace_lock as MODULE


class WorkspaceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.lock_root = root / "locks"
        self.project = root / "project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_same_owner_in_same_process_is_idempotent(self) -> None:
        first = MODULE.acquire(self.lock_root, self.project, "session-a", "session")
        second = MODULE.acquire(self.lock_root, self.project, "session-a", "session")
        self.addCleanup(second.release)
        self.addCleanup(first.release)

        self.assertEqual(first.path, second.path)
        self.assertEqual(first.record["owner_id"], "session-a")
        self.assertEqual(MODULE.read_lock(self.lock_root, self.project)["kind"], "session")

    def test_live_second_owner_is_rejected_until_first_releases(self) -> None:
        first = MODULE.acquire(self.lock_root, self.project, "session-a", "session")
        self.addCleanup(first.release)

        with self.assertRaises(MODULE.WorkspaceBusyError) as raised:
            MODULE.acquire(self.lock_root, self.project, "run-b", "run")

        self.assertIn("session-a", str(raised.exception))
        first.release()
        second = MODULE.acquire(self.lock_root, self.project, "run-b", "run")
        self.addCleanup(second.release)
        self.assertEqual(second.record["owner_id"], "run-b")

    def test_dead_owner_is_reclaimed(self) -> None:
        MODULE.acquire(self.lock_root, self.project, "old-run", "run", pid=999999)

        with patch.object(MODULE, "process_alive", return_value=False):
            replacement = MODULE.acquire(self.lock_root, self.project, "new-run", "run")
        self.addCleanup(replacement.release)

        self.assertEqual(replacement.record["owner_id"], "new-run")


if __name__ == "__main__":
    unittest.main()

