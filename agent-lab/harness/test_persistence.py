from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("persistence.py")
SPEC = importlib.util.spec_from_file_location("persistence_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AtomicPersistenceTests(unittest.TestCase):
    def test_atomic_json_replaces_the_document_without_leaving_a_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text('{"version": 1}\n', encoding="utf-8")

            MODULE.atomic_write_json(path, {"version": 2, "items": ["complete"]})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 2, "items": ["complete"]})
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_failed_replace_preserves_the_previous_document_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.json"
            path.write_text("previous\n", encoding="utf-8")

            with patch.object(MODULE.os, "replace", side_effect=OSError("simulated crash window")):
                with self.assertRaises(OSError):
                    MODULE.atomic_write_text(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "previous\n")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_brief_windows_sharing_lock_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tool-receipt.json"
            real_replace = MODULE.os.replace
            calls = []

            def locked_twice(source, destination):
                calls.append(source)
                if len(calls) <= 2:
                    raise PermissionError(5, "Access is denied")
                return real_replace(source, destination)

            with patch.object(MODULE.os, "replace", side_effect=locked_twice), patch.object(MODULE.time, "sleep"):
                MODULE.atomic_write_json(path, {"status": "pending"})

            self.assertEqual(len(calls), 3)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"status": "pending"})
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_persistent_lock_still_fails_without_touching_the_previous_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text("previous\n", encoding="utf-8")

            with patch.object(MODULE.os, "replace", side_effect=PermissionError(5, "Access is denied")), \
                    patch.object(MODULE.time, "sleep"):
                with self.assertRaises(PermissionError):
                    MODULE.atomic_write_text(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "previous\n")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
