import json
import unittest
from evaluation import EvaluationError, normalize_report


class EvaluationTests(unittest.TestCase):
    def test_legacy_and_generic_failure(self):
        result = normalize_report('{"passed":false,"checks":{"focus_style":false}}', 1)
        self.assertEqual(result["findings"][0]["id"], "focus_style")
        self.assertEqual(normalize_report('{"passed":false}', 1)["findings"][0]["id"], "evaluator_failed")
        self.assertEqual(normalize_report('{"passed":true}', 0)["findings"], [])

    def test_rich_report_and_bounds(self):
        report = {"passed": False, "findings": [{"id": "focus", "message": "x" * 2000,
                                                  "artifacts": ["styles.css"], "evidence": "y" * 2000}]}
        item = normalize_report(json.dumps(report), 1)["findings"][0]
        self.assertEqual(len(item["message"]), 600)
        self.assertEqual(len(item["evidence"]), 600)

    def test_invalid_reports_never_become_repairs(self):
        reports = [None, [], {}, {"passed": 1}, {"passed": True, "checks": {"x": False}},
                   {"passed": False, "checks": {"x": True}}, {"passed": False, "findings": "bad"},
                   {"passed": False, "findings": [{"id": "x", "message": "x", "kind": "infrastructure"}]}]
        for report in reports:
            with self.subTest(report=report), self.assertRaises(EvaluationError):
                normalize_report(json.dumps(report), 1)
        with self.assertRaises(EvaluationError):
            normalize_report("broken", 0)
        with self.assertRaises(EvaluationError):
            normalize_report('{"passed":false}', 0)

    def test_unsafe_hints_duplicate_and_invalid_kinds(self):
        for hint in ["../outside", "/root", "C:/secret", "a\\b", "", "."]:
            with self.subTest(hint=hint), self.assertRaises(EvaluationError):
                normalize_report(json.dumps({"passed": False, "findings": [
                    {"id": "x", "message": "x", "artifacts": [hint]}]}), 1)
        for findings in [[{"id": "x", "message": "x"}] * 2,
                         [{"id": "x", "message": "x", "kind": "other"}],
                         [{"id": "x", "message": "x", "kind": {}}]]:
            with self.assertRaises(EvaluationError):
                normalize_report(json.dumps({"passed": False, "findings": findings}), 1)
