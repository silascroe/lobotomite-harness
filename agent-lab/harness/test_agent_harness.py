from __future__ import annotations

import importlib.util
import json
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

    def test_json_recovery_preserves_literal_backslashes_and_balances_outer_object(self) -> None:
        malformed = r'{"action":"write_file","args":{"path":"styles.css","content":"\input { color: red; }"}'

        value = MODULE.extract_json_object(malformed)

        self.assertEqual(value["action"], "write_file")
        self.assertEqual(value["args"]["content"], r"\input { color: red; }")

    def test_personality_is_added_without_replacing_protocol(self) -> None:
        prompt = self.harness.system_content()
        self.assertIn("restrained infernal workshop spirit", prompt)
        self.assertIn("Every response must be exactly one JSON object", prompt)
        self.assertIn("Never call the user", prompt)
        self.assertIn('"action":"replace_text"', prompt)
        self.assertIn("*** Update File:", prompt)

    def test_model_context_compaction_is_request_only_and_logged(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "context-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="context task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "context_max_tokens": 180,
                "allow_commands": ["node"],
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        for index in range(10):
            harness.messages.extend(
                [
                    {"role": "user", "content": f"Request {index} " + ("x" * 100)},
                    {"role": "assistant", "content": f"Response {index} " + ("y" * 100)},
                ]
            )

        original_messages = list(harness.messages)
        request_messages = harness.model_messages()

        self.assertEqual(harness.messages, original_messages)
        self.assertTrue(harness.context_metadata["compacted"])
        self.assertLessEqual(harness.context_metadata["after_tokens"], 180)
        self.assertIn("context_compacted", (run_dir / "events.jsonl").read_text(encoding="utf-8"))
        self.assertLess(len(request_messages), len(original_messages))

    def test_selected_skills_are_injected_without_unused_skill_text(self) -> None:
        harness = MODULE.AgentHarness(
            task="build task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "skill_overrides": {"disabled": ["verify-before-finish"]},
            },
            run_dir=self.run_dir,
            project_dir=self.project_dir,
            template_dir=None,
        )

        prompt = harness.system_content()

        self.assertIn("[Skill: inspect-and-plan]", prompt)
        self.assertNotIn("[Skill: verify-before-finish]", prompt)
        self.assertEqual([item["name"] for item in harness.skill_metadata()["resolved"]], ["inspect-and-plan"])

    def test_find_skills_is_an_allowlisted_local_recommendation_action(self) -> None:
        result = self.harness.dispatch("find_skills", {"query": "verification"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["results"][0]["name"], "verify-before-finish")

        with self.assertRaises(MODULE.HarnessError):
            self.harness.dispatch("find_skills", {"query": "browser", "source": "remote"})

    def test_gated_finish_requires_inspect_plan_implement_and_verify_evidence(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "gated-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="gated task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["cmd"],
                "require_workflow_gates": True,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()

        self.assertIn("inspect", harness.missing_workflow_gates())
        self.assertIn("plan", harness.missing_workflow_gates())
        self.assertIn("implement", harness.missing_workflow_gates())
        self.assertIn("verify", harness.missing_workflow_gates())
        self.assertIn("workflow evidence missing", harness.finish_issue({"status": "success"}))

        with self.assertRaises(MODULE.HarnessError):
            harness.dispatch(
                "workflow_checkpoint",
                {
                    "phase": "plan",
                    "summary": "Plan before inspection should be rejected.",
                    "next_action": "Inspect first.",
                },
            )
        harness.dispatch("list_files", {"path": "."})
        harness.dispatch(
            "workflow_checkpoint",
            {
                "phase": "plan",
                "summary": "The project is empty and needs one page.",
                "next_action": "Write the page.",
            },
        )
        harness.dispatch("write_file", {"path": "index.html", "content": "<main>ok</main>\n"})
        harness.dispatch("run_command", {"command": "cmd /c exit 0"})
        harness.dispatch("git_diff", {})

        self.assertEqual(harness.missing_workflow_gates(), [])
        self.assertIsNone(harness.finish_issue({"status": "success"}))

    def test_new_mutation_invalidates_previous_verification_evidence(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "evidence-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="evidence task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["cmd"],
                "require_workflow_gates": True,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("list_files", {"path": "."})
        harness.dispatch(
            "workflow_checkpoint",
            {"phase": "plan", "summary": "Plan recorded.", "next_action": "Implement."},
        )
        harness.dispatch("write_file", {"path": "index.html", "content": "<main>one</main>\n"})
        harness.dispatch("run_command", {"command": "cmd /c exit 0"})
        self.assertNotIn("verify", harness.missing_workflow_gates())

        harness.dispatch("write_file", {"path": "index.html", "content": "<main>two</main>\n"})

        self.assertIn("verify", harness.missing_workflow_gates())

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

    def test_multi_file_patch_validates_every_file_before_writing_any_file(self) -> None:
        self.harness.write_file({"path": "first.txt", "content": "old\n"})
        patch = """*** Begin Patch
*** Update File: first.txt
@@
-old
+new
*** Update File: missing.txt
@@
-old
+new
*** End Patch"""

        with self.assertRaises(MODULE.HarnessError):
            self.harness.apply_patch({"patch": patch})

        self.assertEqual((self.project_dir / "first.txt").read_text(encoding="utf-8"), "old\n")
        self.assertFalse((self.project_dir / "missing.txt").exists())

    def test_apply_patch_explains_that_hunks_need_a_file_header(self) -> None:
        with self.assertRaises(MODULE.HarnessError) as raised:
            self.harness.apply_patch(
                {"patch": "*** Begin Patch\n\nbody without a target file\n*** End Patch"}
            )

        self.assertIn("file header", str(raised.exception))
        self.assertIn("*** Update File:", str(raised.exception))

    def test_replace_text_dispatches_an_exact_single_replacement(self) -> None:
        self.harness.dispatch("write_file", {"path": "hello.txt", "content": "hello\nhello\n"})

        result = self.harness.dispatch(
            "replace_text",
            {
                "path": "hello.txt",
                "old_text": "hello\n",
                "new_text": "goodbye\n",
                "expected_replacements": 2,
            },
        )

        self.assertEqual(result["replacements"], 2)
        self.assertEqual((self.project_dir / "hello.txt").read_text(encoding="utf-8"), "goodbye\ngoodbye\n")

    def test_replace_text_rejects_an_unexpected_match_count_without_mutating(self) -> None:
        self.harness.write_file({"path": "hello.txt", "content": "hello\nhello\n"})

        with self.assertRaises(MODULE.HarnessError):
            self.harness.replace_text(
                {
                    "path": "hello.txt",
                    "old_text": "hello\n",
                    "new_text": "goodbye\n",
                    "expected_replacements": 1,
                }
            )

        self.assertEqual((self.project_dir / "hello.txt").read_text(encoding="utf-8"), "hello\nhello\n")

    def test_replace_text_invalidates_previous_verification_evidence(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "replace-evidence-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="replace evidence task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["cmd"],
                "require_workflow_gates": True,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("list_files", {"path": "."})
        harness.dispatch(
            "workflow_checkpoint",
            {"phase": "plan", "summary": "Plan recorded.", "next_action": "Implement."},
        )
        harness.dispatch("write_file", {"path": "index.html", "content": "<main>one</main>\n"})
        harness.dispatch("run_command", {"command": "cmd /c exit 0"})
        self.assertNotIn("verify", harness.missing_workflow_gates())

        harness.dispatch(
            "replace_text",
            {"path": "index.html", "old_text": "one", "new_text": "two"},
        )

        self.assertIn("verify", harness.missing_workflow_gates())

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

    def test_late_plan_checkpoint_records_evidence_without_rewinding_phase(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "late-plan-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="late plan task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["cmd"],
                "require_workflow_gates": True,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("list_files", {"path": "."})
        harness.dispatch("write_file", {"path": "index.html", "content": "<main>ok</main>\n"})
        harness.dispatch("run_command", {"command": "cmd /c exit 0"})
        self.assertEqual(harness.workflow["phase"], "verify")
        self.assertFalse(harness.workflow_evidence["plan"])

        result = harness.dispatch(
            "workflow_checkpoint",
            {
                "phase": "plan",
                "summary": "The implementation was completed; the intended structure is now recorded.",
                "next_action": "Review the generated files.",
                "artifacts": ["docs/plan.md"],
            },
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["late"])
        self.assertEqual(result["workflow"]["phase"], "verify")
        self.assertTrue(harness.workflow_evidence["plan"])
        events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"event": "workflow_late_evidence"', events)

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

    def test_gated_success_requires_fresh_diff_review_after_verification(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "review-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="review task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["cmd"],
                "require_workflow_gates": True,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("list_files", {"path": "."})
        harness.dispatch(
            "workflow_checkpoint",
            {"phase": "plan", "summary": "Plan recorded.", "next_action": "Implement."},
        )
        harness.dispatch("write_file", {"path": "index.html", "content": "<main>one</main>\n"})
        harness.dispatch("run_command", {"command": "cmd /c exit 0"})

        self.assertIn("review", harness.missing_workflow_gates())
        self.assertIn("review", harness.finish_issue({"status": "success"}))

        harness.dispatch("git_diff", {})
        self.assertNotIn("review", harness.missing_workflow_gates())

        harness.dispatch("write_file", {"path": "index.html", "content": "<main>two</main>\n"})
        self.assertIn("review", harness.missing_workflow_gates())

    def _fake_run_harness(self, responses: list[str], *, gated: bool = False) -> MODULE.AgentHarness:
        root = Path(self.temp_dir.name)
        run_dir = root / f"fake-run-{len(list(root.iterdir()))}"
        project_dir = run_dir / "project"
        config = {
            "max_file_bytes": 60000,
            "max_total_project_bytes": 500000,
            "max_turns": 8,
            "required_files": [],
            "require_validation": False,
            "require_workflow_gates": gated,
        }
        harness = MODULE.AgentHarness(
            task="fake model task",
            config=config,
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        response_iter = iter(responses)

        def call_model() -> dict[str, object]:
            harness.model_calls += 1
            return {
                "content": next(response_iter),
                "reasoning_content": "",
                "finish_reason": "stop",
                "usage": {},
            }

        harness.call_model = call_model
        return harness

    def test_repeated_invalid_model_output_blocks_after_one_repair(self) -> None:
        harness = self._fake_run_harness(["not json", "not json", "not json"])

        result = harness.run()

        self.assertEqual(result, 2)
        self.assertEqual(harness.status, "blocked")
        self.assertEqual(harness.model_calls, 2)
        self.assertIn("recovery", MODULE.load_json(harness.run_dir / "summary.json"))
        self.assertIn("invalid_model_action", harness.finish_summary)
        self.assertNotIn("turn limit", harness.finish_summary)

    def test_repeated_ungated_finish_blocks_without_completing_workflow(self) -> None:
        finish = '{"action":"finish","args":{"status":"success","summary":"done"}}'
        harness = self._fake_run_harness([finish, finish, finish], gated=True)

        result = harness.run()

        self.assertEqual(result, 2)
        self.assertEqual(harness.status, "blocked")
        self.assertEqual(harness.model_calls, 2)
        self.assertNotEqual(harness.workflow["phase"], "complete")
        events = (harness.run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"event": "recovery_exhausted"', events)

    def test_duplicate_tool_action_is_not_dispatched_twice(self) -> None:
        read = '{"action":"list_files","args":{"path":"."}}'
        finish = '{"action":"finish","args":{"status":"success","summary":"done"}}'
        harness = self._fake_run_harness([read, read, finish])
        original_dispatch = harness.dispatch
        dispatched: list[str] = []

        def dispatch(action: str, args: dict[str, object]) -> dict[str, object]:
            dispatched.append(action)
            return original_dispatch(action, args)

        harness.dispatch = dispatch

        result = harness.run()

        self.assertEqual(result, 0)
        self.assertEqual(dispatched, ["list_files"])
        self.assertEqual(harness.status, "success")

    def test_run_persists_transcript_and_progress_before_the_next_model_call(self) -> None:
        read = '{"action":"list_files","args":{"path":"."}}'
        finish = '{"action":"finish","args":{"status":"success","summary":"done"}}'
        harness = self._fake_run_harness([read, finish])
        original_call = harness.call_model
        checkpoints: list[tuple[list[dict[str, str]], dict[str, object]]] = []

        def call_model() -> dict[str, object]:
            if harness.model_calls >= 1:
                transcript = json.loads((harness.run_dir / "transcript.json").read_text(encoding="utf-8"))
                progress = MODULE.load_json(harness.run_dir / "progress.json")
                checkpoints.append((transcript, progress))
            return original_call()

        harness.call_model = call_model

        self.assertEqual(harness.run(), 0)
        self.assertEqual(len(checkpoints), 1)
        transcript, progress = checkpoints[0]
        self.assertEqual(transcript[-1]["role"], "user")
        self.assertIn("list_files", transcript[-1]["content"])
        self.assertEqual(progress["status"], "running")
        self.assertEqual(progress["turn"], 1)


if __name__ == "__main__":
    unittest.main()
