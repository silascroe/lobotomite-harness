from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("agent_harness.py")
SPEC = importlib.util.spec_from_file_location("agent_harness_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HarnessUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.run_dir = root / "run"
        self.project_dir = self.run_dir / "project"
        self.run_dir.mkdir()
        self.project_dir.mkdir()
        self.harness = MODULE.AgentHarness(
            task="test task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["node"],
            },
            run_dir=self.run_dir,
            project_dir=self.project_dir,
            template_dir=None,
        )
        self.harness.initial_files = {}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_json_recovery_and_safe_paths(self) -> None:
        value = MODULE.extract_json_object("```json\n{\"action\": \"finish\", \"args\": {}}\n```")
        self.assertEqual(value["action"], "finish")
        with self.assertRaises(MODULE.HarnessError):
            self.harness.resolve_path("../outside")

    def test_personality_is_added_without_replacing_protocol(self) -> None:
        prompt = self.harness.system_content()
        self.assertIn("restrained infernal workshop spirit", prompt)
        self.assertIn("Every response must be exactly one JSON object", prompt)
        self.assertIn("Never call the user", prompt)

    def test_add_and_update_patch(self) -> None:
        added = self.harness.apply_patch(
            {
                "patch": "*** Begin Patch\n*** Add File: hello.txt\n+hello\n*** End Patch"
            }
        )
        self.assertEqual(added["changed"], ["hello.txt"])
        self.assertEqual((self.project_dir / "hello.txt").read_text(encoding="utf-8"), "hello\n")

        self.harness.apply_patch(
            {
                "patch": "*** Begin Patch\n*** Update File: hello.txt\n@@\n-hello\n+hello world\n*** End Patch"
            }
        )
        self.assertEqual((self.project_dir / "hello.txt").read_text(encoding="utf-8"), "hello world\n")

    def test_write_file_and_command_guards(self) -> None:
        result = self.harness.write_file({"path": "hello.js", "content": "console.log('ok');\n"})
        self.assertTrue(result["created"])
        self.assertEqual(self.harness.validate_command("node --check hello.js")[0], "node")
        with self.assertRaises(MODULE.HarnessError):
            self.harness.validate_command("node -e \"console.log('no')\"")
        with self.assertRaises(MODULE.HarnessError):
            self.harness.validate_command("node hello.js; whoami")

    def test_selected_workspace_can_be_existing_and_ignores_dependencies(self) -> None:
        root = Path(self.temp_dir.name)
        selected_run = root / "selected-run"
        selected_project = root / "real-project"
        selected_project.mkdir()
        (selected_project / "README.md").write_text("existing\n", encoding="utf-8")
        (selected_project / "node_modules").mkdir()
        (selected_project / "node_modules" / "noise.js").write_text("ignored\n", encoding="utf-8")

        harness = MODULE.AgentHarness(
            task="edit the existing project",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=selected_run,
            project_dir=selected_project,
            template_dir=None,
        )
        harness.prepare()

        self.assertEqual(harness.workspace_mode, "selected")
        self.assertEqual(sorted(harness.initial_files), ["README.md"])
        self.assertEqual(MODULE.load_json(selected_run / "workspace.json")["project"], str(selected_project))
        result = harness.write_file({"path": "src/main.py", "content": "print('ok')\n"})
        self.assertTrue(result["created"])

    def test_reasoning_levels_map_to_budget_and_model_profile(self) -> None:
        settings = MODULE.reasoning_settings(
            {
                "model": "Gemma-4-E4B-Q4_0",
                "reasoning_level": "deep",
                "reasoning_answer_tokens": 1024,
            }
        )
        self.assertEqual(settings["profile"], "gemma")
        self.assertEqual(settings["budget"], 2048)
        self.assertEqual(settings["max_tokens"], 3072)
        self.assertTrue(settings["enabled"])

        qwen = MODULE.AgentHarness(
            task="test task",
            config={"model": "Qwen3-8B-Q4_K_M", "reasoning_level": "off"},
            run_dir=self.run_dir,
            project_dir=self.project_dir,
            template_dir=None,
        )
        self.assertEqual(qwen.mode_suffix(), "/no_think")
        qwen.config["reasoning_level"] = "standard"
        self.assertEqual(qwen.mode_suffix(), "/think")

    def test_reasoning_level_aliases_and_invalid_values(self) -> None:
        self.assertEqual(MODULE.normalize_reasoning_level("medium"), "standard")
        self.assertEqual(MODULE.normalize_reasoning_level("xhigh"), "max")
        with self.assertRaises(ValueError):
            MODULE.normalize_reasoning_level("telepathic")

    def test_workflow_checkpoint_persists_and_rejects_unsafe_artifacts(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "workflow-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="workflow task",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()

        self.assertEqual(harness.workflow["phase"], "intake")
        result = harness.dispatch(
            "workflow_checkpoint",
            {
                "phase": "plan",
                "summary": "The work is decomposed.",
                "next_action": "Write the failing test.",
                "artifacts": ["docs/plan.md"],
            },
        )
        self.assertEqual(result["workflow"]["phase"], "plan")
        saved = MODULE.load_json(run_dir / "workflow.json")
        self.assertEqual(saved["phase"], "plan")
        events = [line for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if "workflow_phase" in line]
        self.assertGreaterEqual(len(events), 2)

        with self.assertRaises(MODULE.HarnessError):
            harness.dispatch(
                "workflow_checkpoint",
                {
                    "phase": "design",
                    "summary": "Backwards.",
                    "next_action": "Nope.",
                    "artifacts": ["../outside.txt"],
                },
            )
        self.assertEqual(harness.workflow["phase"], "plan")

    def test_failed_command_does_not_claim_verification(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "command-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="command task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["node"],
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("write_file", {"path": "broken.js", "content": "const = 1;\n"})
        result = harness.dispatch("run_command", {"command": "node --check broken.js"})
        self.assertNotEqual(result["exit_code"], 0)
        self.assertEqual(harness.workflow["phase"], "implement")


if __name__ == "__main__":
    unittest.main()
