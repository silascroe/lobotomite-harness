from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("review.py")
SPEC = importlib.util.spec_from_file_location("review_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReviewPacketTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_changes_with_content(self) -> None:
        files = {"b.txt": b"two", "a.txt": b"one"}

        self.assertEqual(MODULE.fingerprint(files), MODULE.fingerprint(dict(reversed(list(files.items())))))
        self.assertNotEqual(MODULE.fingerprint(files), MODULE.fingerprint({**files, "a.txt": b"changed"}))

    def test_packet_describes_added_modified_and_deleted_files(self) -> None:
        packet = MODULE.build_review_packet(
            {"same.txt": b"same", "old.txt": b"old", "changed.txt": b"before"},
            {"same.txt": b"same", "new.txt": b"new", "changed.txt": b"after"},
            "diff",
            validation={"passed": True},
            evaluation={"passed": True},
            workflow_evidence={"review": True},
        )

        self.assertEqual(
            [(item["path"], item["status"]) for item in packet["changed_files"]],
            [("changed.txt", "modified"), ("new.txt", "added"), ("old.txt", "deleted")],
        )
        self.assertEqual(packet["diff"], "diff")
        self.assertEqual(packet["validation"], {"passed": True})
        self.assertEqual(packet["evaluation"], {"passed": True})

    def test_packet_marks_large_diffs_as_truncated(self) -> None:
        packet = MODULE.build_review_packet(
            {},
            {"notes.txt": b"new"},
            "123456789",
            max_diff_chars=5,
        )

        self.assertEqual(packet["diff"], "12345\n[diff truncated]")
        self.assertTrue(packet["diff_truncated"])

    def test_review_status_detects_changes_after_review(self) -> None:
        packet = MODULE.build_review_packet({}, {"notes.txt": b"new"}, "diff")

        self.assertEqual(MODULE.review_status(packet, {"notes.txt": b"new"}), "current")
        self.assertEqual(MODULE.review_status(packet, {"notes.txt": b"newer"}), "stale")
        self.assertEqual(MODULE.review_status(None, {"notes.txt": b"new"}), "not_reviewed")


if __name__ == "__main__":
    unittest.main()

