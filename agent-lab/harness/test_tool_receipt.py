from __future__ import annotations

import unittest

import tool_receipt as MODULE


class ToolReceiptTests(unittest.TestCase):
    def test_receipt_keeps_exact_arguments_but_public_view_is_small(self) -> None:
        receipt = MODULE.new_receipt(
            "write_file",
            {"path": "index.html", "content": "<main>private</main>\n"},
            turn=2,
            step=2,
        )

        public = MODULE.public_receipt(receipt)

        self.assertEqual(receipt["args"]["content"], "<main>private</main>\n")
        self.assertNotIn("args", public)
        self.assertEqual(public["summary"]["path"], "index.html")
        self.assertEqual(public["status"], "pending")

    def test_completed_receipt_can_be_settled_without_losing_result(self) -> None:
        receipt = MODULE.new_receipt("list_files", {"path": "."}, turn=1, step=1)
        completed = MODULE.complete_receipt(receipt, {"ok": True, "entries": []})
        settled = MODULE.settle_receipt(completed)

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["result"]["entries"], [])

    def test_unknown_receipt_is_explicitly_marked_for_inspection(self) -> None:
        receipt = MODULE.new_receipt("run_command", {"command": "npm test"}, turn=3, step=3)

        unknown = MODULE.mark_unknown(receipt)

        self.assertEqual(unknown["status"], "unknown")
        self.assertIn("inspect", unknown["recovery"].lower())


if __name__ == "__main__":
    unittest.main()

