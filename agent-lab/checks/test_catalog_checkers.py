import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CHECKS = Path(__file__).parent


def grade(name, files):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for filename, content in files.items():
            (root / filename).write_text(content, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CHECKS / name), str(root)],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode, json.loads(result.stdout)


class CatalogCheckersTest(unittest.TestCase):
    def test_roundtrip_rejects_missing_export(self):
        files = {
            "agent-check.md": "# Agent check\n\nPurpose: test file round trip.\n\n- [ ] Inspect\n- [ ] Write\n- [ ] Validate\n",
            "agent-check.mjs": 'const status = "ok";\n',
        }
        code, report = grade("check_file_roundtrip.py", files)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        files["agent-check.mjs"] = 'export const status = "ok";\n'
        code, report = grade("check_file_roundtrip.py", files)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["passed"], report)

    def test_roundtrip_accepts_numbered_checklist(self):
        files = {
            "agent-check.md": "# Agent check\n\nThis verifies the file and validation loop.\n\n1. Inspect files\n2. Write module\n3. Validate it\n",
            "agent-check.mjs": 'export const status = "ok";\n',
        }
        code, report = grade("check_file_roundtrip.py", files)
        self.assertEqual(code, 0, report)

    def test_structured_rejects_validator_that_always_succeeds(self):
        files = {
            "health-report.json": json.dumps({"status": "ok", "checks": [{"name": "disk"}, {"name": "model"}], "generated_for": "Agent Lab"}),
            "validate-report.mjs": 'console.log("all good");\n',
        }
        code, report = grade("check_structured_validation.py", files)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        files["validate-report.mjs"] = (
            'import { readFileSync } from "node:fs";\n'
            'const r = JSON.parse(readFileSync("health-report.json", "utf8"));\n'
            'if (r.status !== "ok" || !Array.isArray(r.checks) || r.checks.length < 2 || '
            'r.checks.some(c => !c.name) || !r.generated_for) process.exit(1);\n'
            'console.log("valid report");\n'
        )
        code, report = grade("check_structured_validation.py", files)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["passed"], report)

    def test_mini_project_rejects_noninteractive_page(self):
        files = {
            "index.html": '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body><main><h1>Signal Garden</h1><p>Grow a signal.</p><button id="grow">Grow</button><p id="status">Waiting</p></main><script src="app.js"></script></body></html>',
            "styles.css": 'button:focus-visible {outline: 2px solid orange} @media(max-width:600px){main{padding:1rem}}',
            "app.js": 'document.querySelector("#grow").addEventListener("click", () => {});',
        }
        code, report = grade("check_mini_project.py", files)
        self.assertEqual(code, 1)
        self.assertFalse(report["passed"])
        files["app.js"] = 'document.querySelector("#grow").addEventListener("click", () => { document.querySelector("#status").textContent = "Growing"; });'
        code, report = grade("check_mini_project.py", files)
        self.assertEqual(code, 0)
        self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()

