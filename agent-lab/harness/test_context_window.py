from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("context_window.py")
SPEC = importlib.util.spec_from_file_location("context_window_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ContextWindowTests(unittest.TestCase):
    def test_small_transcript_is_returned_without_compaction(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Inspect the project."},
        ]

        result = MODULE.build_context(messages, max_tokens=1000)

        self.assertFalse(result.compacted)
        self.assertEqual(result.messages, messages)
        self.assertEqual(result.dropped_messages, 0)

    def test_large_transcript_keeps_system_summary_and_recent_turns(self) -> None:
        messages = [{"role": "system", "content": "system instructions"}]
        for index in range(12):
            messages.extend(
                [
                    {"role": "user", "content": f"Older request {index} " + ("x" * 80)},
                    {"role": "assistant", "content": f"Older response {index} " + ("y" * 80)},
                ]
            )
        messages.extend(
            [
                {"role": "user", "content": "Latest request"},
                {"role": "assistant", "content": "Latest response"},
            ]
        )

        result = MODULE.build_context(messages, max_tokens=180, recent_messages=4)
        contents = "\n".join(item["content"] for item in result.messages)

        self.assertTrue(result.compacted)
        self.assertEqual(result.messages[0], messages[0])
        self.assertIn("Earlier observable context", contents)
        self.assertIn("Latest request", contents)
        self.assertIn("Latest response", contents)
        self.assertLessEqual(result.after_tokens, 180)
        self.assertGreater(result.dropped_messages, 0)

    def test_large_tool_payload_is_summarized_without_leaking_file_contents(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": '{"action":"write_file","args":{"path":"index.html","content":"SECRET-FILE-CONTENT"}}',
            },
            {
                "role": "user",
                "content": '{"tool":"write_file","result":{"ok":true,"path":"index.html","bytes":18}}',
            },
            {"role": "user", "content": "Continue the task."},
        ]

        result = MODULE.build_context(messages, max_tokens=45, recent_messages=1)
        contents = "\n".join(item["content"] for item in result.messages)

        self.assertTrue(result.compacted)
        self.assertIn("write_file", contents)
        self.assertIn("index.html", contents)
        self.assertNotIn("SECRET-FILE-CONTENT", contents)

    def test_context_budget_must_leave_room_for_a_message(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.build_context([{"role": "system", "content": "system"}], max_tokens=0)


if __name__ == "__main__":
    unittest.main()

