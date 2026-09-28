from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_action_payload_validation_rejects_missing_wrong_and_unknown_args(self) -> None:
        with self.assertRaisesRegex(MODULE.HarnessError, "missing required fields: content, path"):
            MODULE.validate_action_payload({"action": "write_file", "args": {}})
        with self.assertRaisesRegex(MODULE.HarnessError, "max_depth must be an integer"):
            MODULE.validate_action_payload({"action": "list_files", "args": {"max_depth": True}})
        with self.assertRaisesRegex(MODULE.HarnessError, "unknown fields: typo"):
            MODULE.validate_action_payload({"action": "git_diff", "args": {"typo": 1}})

    def test_action_payload_validation_accepts_complete_and_optional_forms(self) -> None:
        action, args = MODULE.validate_action_payload({
            "action": "workflow_checkpoint", "args": {"phase": "plan", "summary": "Create files."}
        })
        self.assertEqual(action, "workflow_checkpoint")
        self.assertEqual(args, {"phase": "plan", "summary": "Create files."})

    def test_invalid_workflow_phase_reports_the_allowed_phases(self) -> None:
        with self.assertRaisesRegex(
            MODULE.HarnessError,
            "phase must be one of: blocked, complete, design, implement, inspect, intake, plan, review, verify",
        ):
            MODULE.validate_action_payload({
                "action": "workflow_checkpoint",
                "args": {"phase": "inspect-and-plan", "summary": "Plan work."},
            })

    def test_local_model_request_uses_llama_json_schema_for_action_envelope(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "structured-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="schema task",
            config={
                "provider": "local", "constrain_local_actions": True,
                "endpoint": "http://model.invalid/v1/chat/completions",
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"action\\":\\"finish\\",\\"args\\":{}}"}}]}'

        captured = {}
        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch.object(MODULE.urllib.request, "urlopen", side_effect=fake_urlopen):
            harness.call_model()
        schema = captured["payload"]["response_format"]["schema"]
        self.assertEqual(captured["payload"]["response_format"]["type"], "json_object")
        self.assertEqual(schema["properties"]["action"]["enum"], sorted(MODULE.ACTION_NAMES))
        self.assertEqual(schema["required"], ["action", "args"])
        self.assertFalse(schema["additionalProperties"])
        harness.release_workspace_lease()

    def test_task_profile_replaces_global_static_page_gates(self) -> None:
        config = {
            "required_files": ["index.html", "styles.css", "app.js"],
            "require_validation": True,
            "require_workflow_gates": True,
            "evaluator": "agent-lab/checks/check_static_page.py",
        }

        result = MODULE.apply_task_profile(
            config,
            {
                "name": "002-file-roundtrip.md",
                "title": "File round-trip smoke test",
                "description": "Fast tool-chain smoke test.",
                "gates": {
                    "required_files": ["agent-check.md", "agent-check.mjs"],
                    "require_validation": True,
                    "require_workflow_gates": True,
                },
            },
        )

        self.assertEqual(result["required_files"], ["agent-check.md", "agent-check.mjs"])
        self.assertTrue(result["require_validation"])
        self.assertTrue(result["require_workflow_gates"])
        self.assertNotIn("evaluator", result)
        self.assertEqual(result["task_profile"]["name"], "002-file-roundtrip.md")
        self.assertEqual(config["required_files"], ["index.html", "styles.css", "app.js"])

    def test_json_recovery_preserves_literal_backslashes_and_balances_outer_object(self) -> None:
        malformed = r'{"action":"write_file","args":{"path":"styles.css","content":"\input { color: red; }"}'

        value = MODULE.extract_json_object(malformed)

        self.assertEqual(value["action"], "write_file")
        self.assertEqual(value["args"]["content"], r"\input { color: red; }")

    def test_json_recovery_removes_a_stray_quote_before_the_outer_close(self) -> None:
        malformed = r'{"action":"write_file","args":{"path":"styles.css","content":"body {}\n"}"}'

        value = MODULE.extract_json_object(malformed)

        self.assertEqual(value["action"], "write_file")
        self.assertEqual(value["args"]["path"], "styles.css")
        self.assertEqual(value["args"]["content"], "body {}\n")

    def test_json_recovery_does_not_promote_a_nested_args_object_to_an_action(self) -> None:
        with self.assertRaises(MODULE.HarnessError):
            MODULE.extract_json_object('{"args":{"path":"styles.css"}}')

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

    def test_run_model_response_keeps_raw_reasoning_for_inspection(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "reasoning-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="reasoning task",
            config={
                "endpoint": "http://model.invalid/v1/chat/completions",
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"action":"finish","args":{"status":"success"}}',
                                    "reasoning_content": "PRIVATE-REASONING-MUST-NOT-LEAK",
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        with patch.object(MODULE.urllib.request, "urlopen", return_value=FakeResponse()):
            result = harness.call_model()

        self.assertEqual(result["reasoning_content"], "PRIVATE-REASONING-MUST-NOT-LEAK")
        self.assertTrue(result["reasoning_present"])

    def test_remote_provider_uses_ephemeral_auth_without_persisting_the_key(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "remote-provider-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="remote provider task",
            config={
                "provider": "openai_compatible",
                "endpoint": "https://api.example.test/v1/chat/completions",
                "model": "beefy-model",
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
            runtime_api_key="secret-key-that-must-not-persist",
        )
        harness.prepare()

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"action":"finish","args":{"status":"success"}}',
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        captured: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: int) -> FakeResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        with patch.object(MODULE.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = harness.call_model()

        request = captured["request"]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key-that-must-not-persist")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "beefy-model")
        self.assertNotIn("api_key", payload)
        self.assertNotIn("response_format", payload)
        self.assertEqual(result["provider"], "openai_compatible")
        persisted_config = (run_dir / "config.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-key-that-must-not-persist", persisted_config)
        harness.release_workspace_lease()

    def test_interrupted_run_can_restore_snapshot_transcript_and_progress(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "resume-run"
        project_dir = root / "resume-project"
        project_dir.mkdir()
        (project_dir / "baseline.txt").write_bytes(b"original\n")
        harness = MODULE.AgentHarness(
            task="resume this task",
            config={
                "endpoint": "http://model.invalid/v1/chat/completions",
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.messages.append({"role": "assistant", "content": "saved response"})
        harness.save_transcript()
        harness.workflow_evidence["inspect"] = True
        harness.save_progress(turn=3, checkpoint="tool_result")

        restored = MODULE.AgentHarness.resume_from_run(run_dir)

        self.assertEqual(restored.task, "resume this task")
        self.assertEqual(restored.initial_files["baseline.txt"], b"original\n")
        self.assertEqual(restored.messages[-1]["content"], "saved response")
        self.assertEqual(restored.current_turn, 3)
        self.assertEqual(restored.checkpoint, "tool_result")
        self.assertTrue(restored.workflow_evidence["inspect"])
        self.assertTrue((run_dir / "initial-project" / "baseline.txt").is_file())

    def test_resume_processes_a_saved_model_response_without_calling_model_again(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "pending-response-run"
        project_dir = root / "pending-response-project"
        project_dir.mkdir()
        harness = MODULE.AgentHarness(
            task="resume the saved response",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.status = "running"
        harness.current_turn = 1
        harness.messages.append(
            {"role": "assistant", "content": '{"action":"finish","args":{"status":"success","summary":"recovered"}}'}
        )
        harness.save_transcript()
        harness.save_progress(turn=1, checkpoint="model_response")

        restored = MODULE.AgentHarness.resume_from_run(run_dir)
        restored.call_model = lambda: (_ for _ in ()).throw(AssertionError("model should not be called"))

        result = restored.run(resume=True)

        self.assertEqual(result, 0)
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["summary"], "recovered")

    def test_resume_replays_a_completed_tool_receipt_without_dispatching_again(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "receipt-resume-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="resume a completed tool call",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "max_turns": 4,
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.status = "running"
        harness.current_turn = 1
        harness.tool_calls = 1
        harness.begin_tool_receipt("write_file", {"path": "index.html", "content": "<main>done</main>\n"}, turn=1, step=1)
        harness.complete_tool_receipt({"ok": True, "path": "index.html", "changed": True})
        harness.save_transcript()
        harness.save_progress(turn=1, checkpoint="tool_result")

        restored = MODULE.AgentHarness.resume_from_run(run_dir)
        self.assertTrue(restored.tool_receipt_recovery_needed)
        restored.call_model = lambda: {
            "content": '{"action":"finish","args":{"status":"success","summary":"recovered"}}',
            "reasoning_content": "",
            "finish_reason": "stop",
            "usage": {},
        }
        restored.dispatch = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("tool must not replay"))

        self.assertEqual(restored.run(resume=True), 0)
        receipt = MODULE.load_json(run_dir / "tool-receipt.json")
        transcript = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "settled")
        self.assertTrue(any("previous worker completed this tool call" in item.get("content", "") for item in transcript if item.get("role") == "user"))
        self.assertEqual(restored.tool_calls, 1)

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

    def test_explicit_plan_checkpoint_can_default_only_missing_next_action(self) -> None:
        root = Path(self.temp_dir.name)
        harness = MODULE.AgentHarness(
            task="checkpoint task",
            config={"require_workflow_gates": True},
            run_dir=root / "checkpoint-run",
            project_dir=root / "checkpoint-run" / "project",
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("list_files", {"path": "."})

        result = harness.dispatch(
            "workflow_checkpoint", {"phase": "plan", "summary": "Create and validate both files."}
        )

        self.assertTrue(result["ok"])
        self.assertTrue(harness.workflow_evidence["plan"])
        self.assertTrue(harness.workflow["next_action"])
        with self.assertRaises(MODULE.HarnessError):
            harness.dispatch("workflow_checkpoint", {"phase": "plan", "next_action": "Write files."})

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

    def test_update_patch_accepts_a_context_line_without_a_leading_space(self) -> None:
        self.harness.write_file({"path": "script.js", "content": "const a = 1;\nconst b = 2;\n"})

        result = self.harness.apply_patch(
            {
                "patch": """*** Begin Patch
*** Update File: script.js
@@
-const a = 1;
+const a = 3;
const b = 2;
*** End Patch"""
            }
        )

        self.assertEqual(result["changed"], ["script.js"])
        self.assertEqual(
            (self.project_dir / "script.js").read_text(encoding="utf-8"),
            "const a = 3;\nconst b = 2;\n",
        )

    def test_addition_only_hunk_can_ignore_stale_unprefixed_context(self) -> None:
        self.harness.write_file({"path": "styles.css", "content": "one\nanchor\ntwo\n"})

        result = self.harness.apply_patch(
            {
                "patch": """*** Begin Patch
*** Update File: styles.css
@@ -2,4 +2,6 @@
+inserted one
stale context from an older read
+inserted two
"""
            }
        )

        self.assertEqual(result["changed"], ["styles.css"])
        self.assertEqual(
            (self.project_dir / "styles.css").read_text(encoding="utf-8"),
            "one\ninserted one\ninserted two\nanchor\ntwo\n",
        )

    def test_replacement_hunk_still_rejects_stale_context(self) -> None:
        self.harness.write_file({"path": "styles.css", "content": "one\nanchor\ntwo\n"})

        with self.assertRaises(MODULE.HarnessError):
            self.harness.apply_patch(
                {
                    "patch": """*** Begin Patch
*** Update File: styles.css
@@
-stale old line
+new line
*** End Patch"""
                }
            )

        self.assertEqual((self.project_dir / "styles.css").read_text(encoding="utf-8"), "one\nanchor\ntwo\n")

    def test_update_patch_accepts_end_of_input_as_an_implicit_end_marker(self) -> None:
        self.harness.write_file({"path": "script.js", "content": "const a = 1;\n"})

        result = self.harness.apply_patch(
            {
                "patch": """*** Begin Patch
*** Update File: script.js
@@
-const a = 1;
+const a = 2;
"""
            }
        )

        self.assertEqual(result["changed"], ["script.js"])
        self.assertEqual((self.project_dir / "script.js").read_text(encoding="utf-8"), "const a = 2;\n")

    def test_patch_context_failure_gives_specific_recovery_guidance(self) -> None:
        instruction = MODULE.recovery_instruction(
            "apply_patch",
            {"ok": False, "error": "could not find update-patch context in target file"},
        )

        self.assertIn("read_file", instruction)
        self.assertIn("replace_text", instruction)
        self.assertIn("do not repeat", instruction.lower())

    def test_missing_patch_header_recommends_complete_patch_or_file_write(self) -> None:
        instruction = MODULE.recovery_instruction(
            "apply_patch", {"ok": False, "error": "patch must start with *** Begin Patch"}
        )
        self.assertIn("*** Begin Patch", instruction)
        self.assertIn("write_file", instruction)

    def test_backward_checkpoint_recovery_names_forward_phase(self) -> None:
        instruction = MODULE.recovery_instruction(
            "workflow_checkpoint", {"ok": False, "error": "cannot transition from implement to inspect"}
        )
        self.assertIn("implement", instruction)
        self.assertIn("do not", instruction.lower())

    def test_missing_checkpoint_field_recovery_names_required_args(self) -> None:
        instruction = MODULE.recovery_instruction(
            "workflow_checkpoint", {"ok": False, "error": "next_action must be a string"}
        )
        self.assertIn("args.next_action", instruction)
        self.assertIn("args.summary", instruction)

    def test_missing_write_path_gives_field_specific_recovery_guidance(self) -> None:
        instruction = MODULE.recovery_instruction(
            "write_file",
            {"ok": False, "error": "path must be a non-empty relative string"},
        )

        self.assertIn("args.path", instruction)
        self.assertIn("relative", instruction.lower())
        self.assertIn("write_file", instruction)

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

    def test_delete_file_keeps_a_reversible_run_backup_and_records_a_deletion(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "delete-run"
        project_dir = root / "delete-project"
        project_dir.mkdir()
        target = project_dir / "obsolete.txt"
        target.write_text("remove me\n", encoding="utf-8")
        harness = MODULE.AgentHarness(
            task="remove an obsolete file",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()

        result = harness.dispatch("delete_file", {"path": "obsolete.txt"})

        self.assertFalse(target.exists())
        backup = run_dir / "deleted-files" / "obsolete.txt"
        self.assertEqual(backup.read_text(encoding="utf-8"), "remove me\n")
        self.assertEqual(result["backup"], "deleted-files/obsolete.txt")
        self.assertIn("obsolete.txt", harness.git_diff({})["changed_files"])

    def test_delete_file_cannot_remove_a_directory(self) -> None:
        directory = self.project_dir / "folder"
        directory.mkdir()
        with self.assertRaises(MODULE.HarnessError):
            self.harness.delete_file({"path": "folder"})

    def test_missing_python_launcher_falls_back_to_the_harness_interpreter(self) -> None:
        harness = MODULE.AgentHarness(
            task="run a Python check",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "allow_commands": ["python"],
            },
            run_dir=self.run_dir / "python-runtime-run",
            project_dir=self.run_dir / "python-runtime-run" / "project",
            template_dir=None,
        )
        completed = MODULE.subprocess.CompletedProcess(
            args=["python", "-m", "unittest"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with patch.object(MODULE.shutil, "which", return_value=None), patch.object(
            MODULE.subprocess, "run", return_value=completed
        ) as run:
            result = harness.run_command({"command": "python -m unittest"})

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_args.args[0][0], MODULE.sys.executable)

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

    def test_live_workspace_lease_rejects_a_second_run_until_released(self) -> None:
        root = Path(self.temp_dir.name)
        project = root / "shared-project"
        project.mkdir()
        first = MODULE.AgentHarness(
            task="first run",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=root / "first-run",
            project_dir=project,
            template_dir=None,
        )
        first.prepare()
        second = MODULE.AgentHarness(
            task="second run",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=root / "second-run",
            project_dir=project,
            template_dir=None,
        )

        with self.assertRaises(MODULE.WorkspaceBusyError):
            second.prepare()

        first.release_workspace_lease()
        second.prepare()
        second.release_workspace_lease()

    def test_terminal_summary_releases_workspace_lease(self) -> None:
        root = Path(self.temp_dir.name)
        project = root / "terminal-project"
        project.mkdir()
        harness = MODULE.AgentHarness(
            task="terminal run",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=root / "terminal-run",
            project_dir=project,
            template_dir=None,
        )
        harness.prepare()
        harness.status = "success"
        harness.save_summary()

        self.assertIsNone(MODULE.read_lock(MODULE.WORKSPACE_LOCK_ROOT, project))

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

    def test_local_structured_actions_reserve_output_without_enabling_reasoning(self) -> None:
        settings = MODULE.reasoning_settings(
            {
                "provider": "local",
                "model": "Gemma-4-E2B-Q4_0",
                "reasoning_level": "off",
                "constrain_local_actions": True,
                "action_output_tokens": 2048,
            }
        )

        self.assertEqual(settings["budget"], 0)
        self.assertEqual(settings["max_tokens"], 2048)
        self.assertFalse(settings["enabled"])

    def test_local_action_output_reserve_does_not_change_remote_provider_budget(self) -> None:
        settings = MODULE.reasoning_settings(
            {
                "provider": MODULE.OPENAI_COMPATIBLE_PROVIDER,
                "model": "Gemma-4-E2B-Q4_0",
                "reasoning_level": "off",
                "constrain_local_actions": True,
                "action_output_tokens": 2048,
            }
        )

        self.assertEqual(settings["max_tokens"], 700)
        self.assertEqual(settings["budget"], 0)

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

    def test_confirm_mode_persists_exact_action_and_requires_an_explicit_grant(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "approval-dispatch-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="approval task",
            config={
                "max_file_bytes": 60000,
                "max_total_project_bytes": 500000,
                "approval_mode": "confirm",
            },
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        request = harness.request_approval("write_file", {"path": "index.html", "content": "<main>ok</main>\n"}, turn=1)

        self.assertEqual(request["status"], "pending")
        self.assertEqual(MODULE.load_json(run_dir / "approval.json")["args"]["content"], "<main>ok</main>\n")
        with self.assertRaises(MODULE.HarnessError):
            harness.dispatch("write_file", request["args"])

        harness.resolve_approval("approve")
        result = harness.dispatch("write_file", request["args"], approved=True)
        self.assertTrue(result["ok"])
        self.assertEqual(harness.approval_view()["status"], "approved")

    def test_confirm_mode_pauses_and_resumes_the_same_action_without_a_second_model_call(self) -> None:
        write = '{"action":"write_file","args":{"path":"index.html","content":"<main>approved</main>\\n"}}'
        finish = '{"action":"finish","args":{"status":"success","summary":"done"}}'
        harness = self._fake_run_harness([write, finish])
        harness.approval_mode = "confirm"
        harness.config["approval_mode"] = "confirm"

        self.assertEqual(harness.run(), 3)
        self.assertEqual(harness.status, "waiting_approval")
        self.assertFalse((harness.project_dir / "index.html").exists())
        self.assertEqual(MODULE.load_json(harness.run_dir / "approval.json")["status"], "pending")

        resumed = MODULE.AgentHarness.resume_from_run(harness.run_dir)
        responses = iter([finish])

        def call_model() -> dict[str, object]:
            resumed.model_calls += 1
            return {"content": next(responses), "reasoning_content": "", "finish_reason": "stop", "usage": {}}

        resumed.call_model = call_model
        self.assertEqual(resumed.run(resume=True, approval_decision="approve"), 0)
        self.assertTrue((resumed.project_dir / "index.html").is_file())
        self.assertEqual(resumed.approval_view()["status"], "approved")
        self.assertEqual(resumed.model_calls, 2)

    def test_git_diff_persists_a_review_packet_with_current_change_evidence(self) -> None:
        root = Path(self.temp_dir.name)
        run_dir = root / "review-packet-run"
        project_dir = run_dir / "project"
        harness = MODULE.AgentHarness(
            task="review packet task",
            config={"max_file_bytes": 60000, "max_total_project_bytes": 500000},
            run_dir=run_dir,
            project_dir=project_dir,
            template_dir=None,
        )
        harness.prepare()
        harness.dispatch("write_file", {"path": "index.html", "content": "<main>new</main>\n"})

        result = harness.dispatch("git_diff", {})
        packet = MODULE.load_json(run_dir / "review.json")

        self.assertEqual(result["changed_files"], ["index.html"])
        self.assertEqual(packet["status"], "current")
        self.assertEqual(packet["changed_files"][0]["path"], "index.html")
        self.assertEqual(packet["changed_files"][0]["status"], "added")
        self.assertEqual(packet["diff"], result["diff"])

    def test_evaluator_rejection_names_failed_checks_instead_of_dumping_the_whole_report(self) -> None:
        self.harness.run_evaluator = lambda: {
            "configured": True,
            "passed": False,
            "stdout": json.dumps(
                {
                    "passed": False,
                    "checks": {"has_focus_style": False, "handles_submit": True},
                }
            ),
            "stderr": "",
        }

        issue = self.harness.finish_issue({"status": "success"})

        self.assertIsNotNone(issue)
        self.assertIn("has_focus_style", issue)
        self.assertNotIn('"checks"', issue)

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

