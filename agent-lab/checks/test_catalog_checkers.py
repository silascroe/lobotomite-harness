import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


CHECKS = Path(__file__).parent


def grade(name, files, timeout=90):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for filename, content in files.items():
            (root / filename).write_text(content, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CHECKS / name), str(root)],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, json.loads(result.stdout)


def failed(report):
    return {item["id"] for item in report["findings"]}


GOOD_STATIC = {
    "index.html": """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Northstar Field Notes</title><link rel="stylesheet" href="styles.css"></head>
<body>
<header><h1>Northstar Field Notes</h1><p>Observations: <span id="count">0</span></p></header>
<main>
<form id="entry">
<label for="title">Title</label><input id="title" required>
<label for="location">Location</label><input id="location">
<label for="note">Note</label><textarea id="note"></textarea>
<button type="submit">Add observation</button>
</form>
<p id="empty">No observations yet.</p>
<ul id="list"></ul>
</main>
<script src="app.js"></script>
</body></html>""",
    "styles.css": """body { margin: 0; font-family: sans-serif; background: #ffffff; color: #222222; }
header, main { max-width: 40rem; margin: 0 auto; padding: 1rem; }
input, textarea { display: block; width: 100%; box-sizing: border-box; margin-bottom: .5rem; }
:focus-visible { outline: 3px solid #1a5fb4; outline-offset: 2px; }""",
    "app.js": """const form = document.getElementById("entry");
const list = document.getElementById("list");
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const item = document.createElement("li");
  for (const id of ["title", "location", "note"]) {
    const line = document.createElement("p");
    line.textContent = document.getElementById(id).value;
    item.append(line);
  }
  list.append(item);
  document.getElementById("empty").hidden = true;
  document.getElementById("count").textContent = String(list.children.length);
  form.reset();
});""",
}

GOOD_MINI = {
    "index.html": """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal Garden</title><link rel="stylesheet" href="styles.css"></head>
<body><main>
<h1>Signal Garden</h1>
<p>Grow a small garden of signals, one press at a time.</p>
<button id="grow" type="button">Grow a signal</button>
<p id="status">No signals yet.</p>
</main><script src="app.js"></script></body></html>""",
    "styles.css": """body { margin: 0; font-family: sans-serif; background: #fff; color: #222; }
main { max-width: 40rem; margin: 0 auto; padding: 1rem; }
button:focus-visible { outline: 3px solid #1a5fb4; }""",
    "app.js": """let signals = 0;
document.getElementById("grow").addEventListener("click", () => {
  signals += 1;
  document.getElementById("status").textContent = `${signals} signal${signals === 1 ? "" : "s"} growing.`;
});""",
}


class BrowserCase(unittest.TestCase):
    """Grades fixture projects in a real headless browser; skipped without one."""

    def browser_grade(self, name, files):
        code, report = grade(name, files)
        if any(item.get("kind") == "infrastructure" for item in report["findings"]):
            problem = next(item.get("evidence") for item in report["findings"] if item.get("kind") == "infrastructure")
            self.skipTest(f"browser probe unavailable: {problem}")
        return code, report


class StaticPageBrowserTest(BrowserCase):
    def test_working_page_passes(self):
        code, report = self.browser_grade("check_static_page.py", GOOD_STATIC)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["passed"], report)

    def test_broken_page_fails_for_what_it_does(self):
        files = dict(GOOD_STATIC)
        # No viewport meta, a remote font, a removed outline, unreadable text,
        # and a form that is never intercepted, so submitting reloads the page.
        files["index.html"] = (GOOD_STATIC["index.html"]
                               .replace('<meta name="viewport" content="width=device-width, initial-scale=1">',
                                        '<link rel="stylesheet" href="https://fonts.example.com/css?family=Inter">'))
        files["styles.css"] = """body { margin: 0; font-family: sans-serif; background: #aaaaaa; color: #999999; }
main { width: 900px; }
:focus { outline: none; }"""
        files["app.js"] = "// the form is left to the browser\n"
        code, report = self.browser_grade("check_static_page.py", files)
        self.assertEqual(code, 1)
        findings = {item["id"]: item for item in report["findings"]}
        for check in ("submit_adds_card", "keeps_all_cards", "count_updates", "focus_visible",
                      "responsive_layout", "local_assets", "readable_contrast"):
            self.assertIn(check, findings, report)
            self.assertEqual(findings[check]["kind"], "requirement")
        self.assertIn("reloaded the page", findings["submit_adds_card"]["evidence"])
        self.assertIn("fonts.example.com", findings["local_assets"]["evidence"])
        self.assertIn("viewport", findings["responsive_layout"]["evidence"])
        for check in ("product_heading_and_action", "labeled_fields", "semantic_structure", "runs_without_errors"):
            self.assertNotIn(check, findings, "structure the page does have is not penalised")

    def test_mismatched_ids_crash_is_caught(self):
        # The kind of bug the old substring checker passed: every word is in
        # the source, but the script looks up ids the page does not have.
        files = dict(GOOD_STATIC)
        files["app.js"] = GOOD_STATIC["app.js"].replace('getElementById("entry")', 'getElementById("observationForm")')
        code, report = self.browser_grade("check_static_page.py", files)
        self.assertEqual(code, 1)
        findings = {item["id"]: item for item in report["findings"]}
        self.assertIn("runs_without_errors", findings)
        self.assertIn("submit_adds_card", findings)

    def test_handler_without_prevent_default_is_a_reload(self):
        # The card appears, then the browser submits the form anyway and the
        # page reloads. The probe must see the reload, not crash on it.
        files = dict(GOOD_STATIC)
        files["app.js"] = GOOD_STATIC["app.js"].replace("  event.preventDefault();\n", "")
        code, report = self.browser_grade("check_static_page.py", files)
        self.assertEqual(code, 1)
        findings = {item["id"]: item for item in report["findings"]}
        self.assertIn("reloaded the page", findings["submit_adds_card"]["evidence"], report)
        self.assertEqual(findings["submit_adds_card"]["kind"], "requirement")

    def test_replacing_cards_fails_keeps_all_cards(self):
        files = dict(GOOD_STATIC)
        files["app.js"] = GOOD_STATIC["app.js"].replace("list.append(item);", "list.replaceChildren(item);")
        code, report = self.browser_grade("check_static_page.py", files)
        self.assertEqual(code, 1)
        self.assertIn("keeps_all_cards", failed(report))
        self.assertNotIn("submit_adds_card", failed(report))


class MiniProjectBrowserTest(BrowserCase):
    def test_working_page_passes(self):
        code, report = self.browser_grade("check_mini_project.py", GOOD_MINI)
        self.assertEqual(code, 0, report)
        self.assertTrue(report["passed"], report)

    def test_button_that_does_nothing_fails(self):
        files = dict(GOOD_MINI, **{"app.js": 'document.getElementById("grow").addEventListener("click", () => {});'})
        code, report = self.browser_grade("check_mini_project.py", files)
        self.assertEqual(code, 1)
        self.assertIn("action_updates_status", failed(report))
        self.assertIn("keyboard_operable", failed(report))

    def test_status_lost_to_a_form_reload_fails(self):
        files = dict(GOOD_MINI)
        files["index.html"] = GOOD_MINI["index.html"].replace(
            '<button id="grow" type="button">Grow a signal</button>',
            '<form><button id="grow">Grow a signal</button></form>')
        code, report = self.browser_grade("check_mini_project.py", files)
        self.assertEqual(code, 1)
        findings = {item["id"]: item for item in report["findings"]}
        self.assertIn("reloaded the page", findings["action_updates_status"]["evidence"], report)
        self.assertIn("keyboard_operable", findings)

    def test_clickable_div_is_not_keyboard_operable(self):
        files = dict(GOOD_MINI)
        files["index.html"] = GOOD_MINI["index.html"].replace(
            '<button id="grow" type="button">Grow a signal</button>',
            '<div id="grow" role="button">Grow a signal</div>')
        code, report = self.browser_grade("check_mini_project.py", files)
        self.assertEqual(code, 1)
        self.assertNotIn("action_updates_status", failed(report), report)
        self.assertIn("keyboard_operable", failed(report))


class GradeLogicTest(unittest.TestCase):
    """The grading rules applied to hand-written observations, no browser needed."""

    def test_static_count_must_go_from_one_to_two(self):
        import check_static_page
        card = {"found": True, "complete": True, "containsForm": False}
        obs = {
            "load": {"requests": {"/styles.css": 200, "/app.js": 200}},
            "emptyCandidates": [{"path": "p#empty", "text": "No observations yet."}],
            "submissions": [
                {"attempted": True, "card": card, "state": {"texts": {}, "numbers": {"span#count": [1]}}},
                {"attempted": True, "card": card, "state": {"texts": {}, "numbers": {"span#count": [1]}}},
            ],
            "firstStillShown": {"complete": True},
        }
        checks, evidence = check_static_page.grade(obs)
        self.assertTrue(checks["submit_adds_card"])
        self.assertTrue(checks["keeps_all_cards"])
        self.assertTrue(checks["empty_state"])
        self.assertFalse(checks["count_updates"])
        self.assertIn("1 to 2", evidence["count_updates"])
        obs["submissions"][1]["state"]["numbers"]["span#count"] = [2]
        self.assertTrue(check_static_page.grade(obs)[0]["count_updates"])

    def test_static_empty_state_must_disappear(self):
        import check_static_page
        card = {"found": True, "complete": True}
        obs = {"emptyCandidates": [{"path": "p#empty", "text": "No observations yet."}],
               "submissions": [{"attempted": True, "card": card,
                                "state": {"texts": {"p#empty": "No observations yet."}}}]}
        checks, evidence = check_static_page.grade(obs)
        self.assertFalse(checks["empty_state"])
        self.assertIn("stayed visible", evidence["empty_state"])

    def test_favicon_404_is_not_an_error(self):
        from browser_checks import load_checks
        checks, _ = load_checks({"load": {"requests": {"/styles.css": 200, "/app.js": 200, "/favicon.ico": 404}}})
        self.assertTrue(checks["runs_without_errors"])
        checks, evidence = load_checks({"load": {"requests": {"/styles.css": 200, "/app.js": 404}}})
        self.assertFalse(checks["runs_without_errors"])
        self.assertFalse(checks["loads_styles_and_script"])
        self.assertIn("app.js", evidence["loads_styles_and_script"])

    def test_phone_layout_without_viewport_meta_says_so(self):
        from browser_checks import layout_check
        passed, detail = layout_check({"phone": {"width": 980, "scrollWidth": 980, "viewportMeta": False},
                                       "desktop": {"width": 1280, "scrollWidth": 1280}})
        self.assertFalse(passed)
        self.assertIn("no viewport meta", detail)
        passed, detail = layout_check({"phone": {"width": 375, "scrollWidth": 395, "viewportMeta": True},
                                       "desktop": {"width": 1280, "scrollWidth": 1280}})
        self.assertFalse(passed)
        self.assertIn("395px", detail)

    def test_mini_keyboard_failure_names_the_control(self):
        import check_mini_project
        obs = {"structure": {"heading": True, "description": True, "main": True},
               "action": {"desc": "div#grow"}, "click": {"changed": ["p#status"]},
               "keyboard": {"reached": False}}
        checks, evidence = check_mini_project.grade(obs)
        self.assertTrue(checks["action_updates_status"])
        self.assertFalse(checks["keyboard_operable"])
        self.assertIn("div#grow", evidence["keyboard_operable"])


class InfrastructureTest(unittest.TestCase):
    def test_missing_node_is_infrastructure_not_model_repair(self):
        import browser_checks
        import check_mini_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text("<!doctype html><title>x</title>")
            output = io.StringIO()
            with patch.object(sys, "argv", ["checker", str(root)]), redirect_stdout(output), \
                    patch.object(browser_checks.subprocess, "run", side_effect=FileNotFoundError("node")):
                self.assertEqual(check_mini_project.main(), 1)
            report = json.loads(output.getvalue())
            finding = next(item for item in report["findings"] if item["id"] == "action_updates_status")
            self.assertEqual(finding["kind"], "infrastructure")
            self.assertIn("Node.js", finding["evidence"])

    def test_missing_page_is_the_models_problem(self):
        _, report = grade("check_mini_project.py", {})
        findings = {item["id"]: item for item in report["findings"]}
        self.assertEqual(findings["focus_visible"]["artifacts"], ["styles.css"])
        self.assertEqual(findings["semantic_main"]["artifacts"], ["index.html"])
        self.assertEqual(findings["keyboard_operable"]["kind"], "requirement")
        self.assertIn("index.html does not exist", findings["keyboard_operable"]["evidence"])

    def test_roundtrip_without_node_is_infrastructure(self):
        import check_file_roundtrip
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent-check.md").write_text("# Check\n\nA purpose paragraph.\n\n- [ ] a\n- [ ] b\n- [ ] c\n")
            (root / "agent-check.mjs").write_text('export const status = "ok";\n')
            output = io.StringIO()
            with patch.object(sys, "argv", ["checker", str(root)]), redirect_stdout(output), \
                    patch.object(check_file_roundtrip.subprocess, "run", side_effect=FileNotFoundError("node")):
                check_file_roundtrip.main()
            report = json.loads(output.getvalue())
            kinds = {item["id"]: item["kind"] for item in report["findings"]}
            self.assertEqual(kinds.get("exports_ok_status"), "infrastructure", report)


class ProjectServerTest(unittest.TestCase):
    def test_serves_project_files_but_nothing_else(self):
        from browser_checks import serve
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "secret.txt"
            outside.write_text("secret")
            root = Path(tmp) / "project"
            (root / "sub").mkdir(parents=True)
            (root / "index.html").write_text("hello")
            linked = False
            try:
                os.symlink(outside, root / "link.txt")
                linked = True
            except (OSError, NotImplementedError):
                pass
            with serve(root) as origin:
                with urllib.request.urlopen(f"{origin}/index.html") as response:
                    self.assertEqual(response.read(), b"hello")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                for path in ["/sub/", "/../secret.txt", "/%2e%2e/secret.txt"] + (["/link.txt"] if linked else []):
                    with self.assertRaises(urllib.error.HTTPError, msg=path) as caught:
                        urllib.request.urlopen(origin + path).read()
                    self.assertEqual(caught.exception.code, 404, path)


class ProgramCheckersTest(unittest.TestCase):
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

    def test_roundtrip_reads_the_export_not_the_source_text(self):
        files = {
            "agent-check.md": "# Agent check\n\nPurpose: test file round trip.\n\n- [ ] Inspect\n- [ ] Write\n- [ ] Validate\n",
            # Contains the old substring, exports the wrong value.
            "agent-check.mjs": '// export const status = "ok";\nexport const status = "pending";\n',
        }
        code, report = grade("check_file_roundtrip.py", files)
        self.assertEqual(code, 1)
        self.assertIn("exports_ok_status", failed(report))
        files["agent-check.mjs"] = 'const value = ["o", "k"].join("");\nexport { value as status };\n'
        code, report = grade("check_file_roundtrip.py", files)
        self.assertEqual(code, 0, report)

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

    def test_structured_names_the_case_it_let_through(self):
        files = {
            "health-report.json": json.dumps({"status": "ok", "checks": [{"name": "disk"}, {"name": "model"}], "generated_for": "Agent Lab"}),
            "validate-report.mjs": (
                'import { readFileSync } from "node:fs";\n'
                'const r = JSON.parse(readFileSync("health-report.json", "utf8"));\n'
                'if (r.status !== "ok" || !Array.isArray(r.checks) || r.checks.length < 2) process.exit(1);\n'
                'console.log("valid report");\n'
            ),
        }
        code, report = grade("check_structured_validation.py", files)
        self.assertEqual(code, 1)
        findings = {item["id"]: item for item in report["findings"]}
        self.assertEqual(set(findings), {"validator_rejects_unnamed_check", "validator_rejects_missing_generated_for"})
        self.assertIn("exited 0", findings["validator_rejects_unnamed_check"]["evidence"])


if __name__ == "__main__":
    unittest.main()
