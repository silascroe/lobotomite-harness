from __future__ import annotations

import io
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HARNESS_DIR = Path(__file__).resolve().parents[1] / "harness"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))
SERVER_PATH = Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("server_under_test", SERVER_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ServerWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        MODULE.SESSIONS.clear()
        MODULE.PROCESSES.clear()
        MODULE.OUTPUTS.clear()
        MODULE.PROVIDER_SETTINGS = {}
        MODULE.PROVIDER_API_KEY = None
        root = Path(self.temp_dir.name)
        self.config_path = root / "config.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "model": "test-model",
                    "max_turns": 2,
                    "max_file_bytes": 60000,
                    "max_total_project_bytes": 500000,
                    "allow_commands": ["node"],
                }
            ),
            encoding="utf-8",
        )
        MODULE.CONFIG = self.config_path
        MODULE.SESSION_DIR = root / "sessions"
        MODULE.RUNS_DIR = root / "runs"

    def tearDown(self) -> None:
        MODULE.SESSIONS.clear()
        MODULE.PROCESSES.clear()
        MODULE.OUTPUTS.clear()
        MODULE.PROVIDER_SETTINGS = {}
        MODULE.PROVIDER_API_KEY = None
        self.temp_dir.cleanup()

    def test_interactive_session_exposes_initial_workflow(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-workflow", project_path=str(project))

        state = session.state()
        self.assertEqual(state["workflow"]["phase"], "intake")
        self.assertEqual(state["workflow"]["status"], "active")
        self.assertTrue((session.run_dir / "workflow.json").is_file())
        self.assertIn("context", state)

    def test_remote_provider_configuration_is_publicly_redacted_and_not_persisted(self) -> None:
        project = Path(self.temp_dir.name) / "provider-project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-provider", project_path=str(project))
        MODULE.SESSIONS[session.session_id] = session

        result = MODULE.configure_provider(
            {
                "provider": "openai_compatible",
                "endpoint": "https://api.example.test/v1/chat/completions",
                "model": "beefy-model",
                "api_key": "secret-key-that-must-not-persist",
                "session_id": session.session_id,
            }
        )

        self.assertTrue(result["provider"]["has_api_key"])
        self.assertNotIn("api_key", result["provider"])
        self.assertEqual(result["session"]["provider"]["model"], "beefy-model")
        persisted = (session.run_dir / "config.json").read_text(encoding="utf-8")
        self.assertNotIn("secret-key-that-must-not-persist", persisted)
        self.assertEqual(session.state()["provider"]["provider"], "openai_compatible")
        session.harness.release_workspace_lease()

    def test_remote_run_passes_the_key_only_to_the_child_environment(self) -> None:
        MODULE.configure_provider(
            {
                "provider": "openai_compatible",
                "endpoint": "https://api.example.test/v1/chat/completions",
                "model": "beefy-model",
                "api_key": "secret-run-key",
            }
        )

        class DummyProcess:
            stdout = None
            returncode = 0

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

        with patch.object(MODULE.subprocess, "Popen", return_value=DummyProcess()) as popen:
            result = MODULE.start_run({"task_text": "try the remote brain", "gated": False})

        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs["env"]
        self.assertIn("--provider", command)
        self.assertNotIn("secret-run-key", command)
        self.assertEqual(environment["AGENT_LAB_API_KEY"], "secret-run-key")
        self.assertEqual(result["provider"]["model"], "beefy-model")

    def test_preset_run_passes_its_profile_and_unknown_presets_are_rejected(self) -> None:
        class DummyProcess:
            stdout = None
            returncode = 0

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

        with self.assertRaises(MODULE.ApiError) as raised:
            MODULE.start_run({"task_text": "try it", "task_name": "missing.md"})
        self.assertEqual(raised.exception.status, 400)

        with patch.object(MODULE.subprocess, "Popen", return_value=DummyProcess()) as popen:
            result = MODULE.start_run(
                {
                    "task_text": "run the round-trip smoke test",
                    "task_name": "002-file-roundtrip.md",
                    "gated": True,
                }
            )

        command = popen.call_args.args[0]
        profile_index = command.index("--task-profile-json") + 1
        profile = json.loads(command[profile_index])
        self.assertEqual(profile["name"], "002-file-roundtrip.md")
        self.assertEqual(profile["gates"]["required_files"], ["agent-check.md", "agent-check.mjs"])
        self.assertEqual(profile["gates"]["evaluator"], "agent-lab/checks/check_file_roundtrip.py")
        self.assertEqual(result["task_profile"]["title"], "File round-trip smoke test")

    def test_interactive_session_rejects_a_second_owner_of_the_same_project(self) -> None:
        project = Path(self.temp_dir.name) / "shared-project"
        project.mkdir()
        first = MODULE.InteractiveSession("chat-owner-a", project_path=str(project))

        with self.assertRaises(MODULE.WorkspaceBusyError):
            MODULE.InteractiveSession("chat-owner-b", project_path=str(project))
        with self.assertRaises(MODULE.ApiError) as raised:
            MODULE.create_session(project_path=str(project))

        self.assertEqual(raised.exception.status, 409)
        first.harness.release_workspace_lease()

    def test_interactive_confirm_mode_pauses_with_a_public_approval_record(self) -> None:
        project = Path(self.temp_dir.name) / "approval-project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-approval", project_path=str(project), approval_mode="confirm")
        session.harness.call_model = lambda: {
            "content": '{"action":"write_file","args":{"path":"index.html","content":"<main>approved</main>\\n"}}',
            "reasoning_content": "",
            "finish_reason": "stop",
            "usage": {},
        }
        session.conversation.append({"role": "user", "content": "Create the page."})
        session.job = MODULE.new_job("Create the page.", job_id="job-approval")
        session.busy = True
        session.status = "thinking"

        session.process("Create the page.", "job-approval")
        state = session.state()

        self.assertEqual(state["status"], "waiting_approval")
        self.assertFalse(state["busy"])
        self.assertEqual(state["job"]["status"], "waiting_approval")
        self.assertEqual(state["approval"]["action"], "write_file")
        self.assertNotIn("args", state["approval"])
        self.assertFalse((project / "index.html").exists())

    def test_interactive_approval_mode_survives_session_restore(self) -> None:
        project = Path(self.temp_dir.name) / "approval-restore-project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-approval-restore", project_path=str(project))
        session.set_approval_mode("confirm")

        restored = MODULE.InteractiveSession.from_disk("chat-approval-restore")

        self.assertEqual(restored.state()["approval_mode"], "confirm")
        self.assertEqual(json.loads((session.run_dir / "config.json").read_text(encoding="utf-8"))["approval_mode"], "confirm")

    def test_interactive_contract_exposes_exact_replace_text_action(self) -> None:
        self.assertIn("replace_text", MODULE.INTERACTIVE_ACTIONS)
        self.assertIn('"action":"replace_text"', MODULE.INTERACTIVE_SYSTEM_PROMPT)
        self.assertIn('"action":"delete_file"', MODULE.INTERACTIVE_SYSTEM_PROMPT)
        self.assertIn("*** Update File:", MODULE.INTERACTIVE_SYSTEM_PROMPT)

    def test_skill_catalog_exposes_bundled_and_project_local_sources(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        skill_dir = project / "skills" / "field-notes"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: field-notes\ndescription: Capture project notes.\n---\n\nUse evidence.\n",
            encoding="utf-8",
        )

        catalog = MODULE.skill_catalog(str(project))

        self.assertIn("inspect-and-plan", [item["name"] for item in catalog["skills"]])
        local = next(item for item in catalog["skills"] if item["name"] == "field-notes")
        self.assertEqual(local["source"], "project")
        self.assertTrue(catalog["defaults"])

    def test_session_persists_skill_overrides_and_snapshot(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        skill_dir = project / "skills" / "field-notes"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: field-notes\ndescription: Capture project notes.\n---\n\nUse evidence.\n",
            encoding="utf-8",
        )
        session = MODULE.InteractiveSession(
            "chat-skills",
            project_path=str(project),
            skill_overrides={"enabled": ["field-notes"], "disabled": ["verify-before-finish"]},
        )

        state = session.state()
        persisted = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))

        self.assertEqual([item["name"] for item in state["skills"]["resolved"]], ["inspect-and-plan", "field-notes"])
        self.assertEqual(persisted["skill_overrides"]["enabled"], ["field-notes"])
        self.assertEqual(persisted["skills"]["disabled"], ["verify-before-finish"])

        restored = MODULE.InteractiveSession.from_disk("chat-skills")
        self.assertEqual([item["name"] for item in restored.state()["skills"]["resolved"]], ["inspect-and-plan", "field-notes"])

    def test_discovery_endpoint_keeps_remote_search_explicit(self) -> None:
        with self.assertRaises(MODULE.ApiError):
            MODULE.discover_skills({"query": "browser", "source": "remote", "project_path": ""})

        local = MODULE.discover_skills({"query": "verification", "source": "local", "project_path": ""})
        self.assertEqual(local["source"], "local")
        self.assertEqual(local["results"][0]["name"], "verify-before-finish")

    def test_static_assets_are_served_without_stale_cache(self) -> None:
        static_root = Path(self.temp_dir.name) / "static"
        static_root.mkdir()
        (static_root / "index.html").write_bytes(b"<main>fresh</main>\n")
        previous_ui_dir = MODULE.UI_DIR
        MODULE.UI_DIR = static_root

        class Probe:
            def __init__(self) -> None:
                self.headers: dict[str, str] = {}
                self.wfile = io.BytesIO()

            def send_response(self, status: int) -> None:
                self.status = status

            def send_header(self, name: str, value: str) -> None:
                self.headers[name] = value

            def end_headers(self) -> None:
                pass

        probe = Probe()
        try:
            MODULE.Handler.send_static(probe, "index.html")
        finally:
            MODULE.UI_DIR = previous_ui_dir

        self.assertEqual(probe.status, 200)
        self.assertEqual(probe.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(probe.wfile.getvalue(), b"<main>fresh</main>\n")

    def test_run_state_loads_workflow_snapshot(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-workflow"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "workflow.json").write_text(
            json.dumps(
                {
                    "phase": "plan",
                    "status": "active",
                    "summary": "The plan is ready.",
                    "next_action": "Implement the first task.",
                    "artifacts": ["docs/plan.md"],
                    "checkpoint_count": 2,
                    "updated_at": "2026-09-19T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )

        state = MODULE.run_state("run-workflow")
        self.assertEqual(state["workflow"]["phase"], "plan")
        self.assertEqual(state["workflow"]["next_action"], "Implement the first task.")

    def test_run_state_exposes_a_review_packet_and_marks_it_stale_after_changes(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-review"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (project_dir / "index.html").write_text("<main>one</main>\n", encoding="utf-8")
        current_bytes = (project_dir / "index.html").read_bytes()
        packet = {
            "version": 1,
            "status": "current",
            "generated_at": "2026-09-21T01:00:00+00:00",
            "baseline_fingerprint": "baseline",
            "current_fingerprint": MODULE.fingerprint({"index.html": current_bytes}),
            "changed_files": [{"path": "index.html", "status": "added", "before_bytes": 0, "after_bytes": len(current_bytes)}],
            "diff": "+<main>one</main>\n",
            "diff_truncated": False,
        }
        (run_dir / "review.json").write_text(json.dumps(packet), encoding="utf-8")

        state = MODULE.run_state("run-review")
        self.assertEqual(state["review"]["status"], "current")
        self.assertEqual(state["review"]["changed_files"][0]["path"], "index.html")

        (project_dir / "index.html").write_text("<main>two</main>\n", encoding="utf-8")
        stale = MODULE.run_state("run-review")
        self.assertEqual(stale["review"]["status"], "stale")

    def test_run_state_reports_a_stale_running_progress_snapshot_as_interrupted(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-interrupted"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "progress.json").write_text(
            json.dumps({"status": "running", "turn": 4, "model_calls": 4, "tool_calls": 3}),
            encoding="utf-8",
        )

        state = MODULE.run_state("run-interrupted")

        self.assertEqual(state["status"], "interrupted")
        self.assertEqual(state["progress"]["turn"], 4)

    def test_run_state_exposes_waiting_approval_without_mislabeling_it_as_an_error(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-approval"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "progress.json").write_text(json.dumps({"status": "waiting_approval", "turn": 2}), encoding="utf-8")
        (run_dir / "approval.json").write_text(
            json.dumps({"status": "pending", "action": "write_file", "summary": {"action": "write_file", "path": "index.html"}, "turn": 2}),
            encoding="utf-8",
        )

        state = MODULE.run_state("run-approval")

        self.assertEqual(state["status"], "waiting_approval")
        self.assertEqual(state["approval"]["action"], "write_file")

    def test_resume_run_requires_a_decision_for_waiting_approval(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-approval-resume"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "progress.json").write_text(json.dumps({"status": "waiting_approval", "turn": 2}), encoding="utf-8")
        (run_dir / "approval.json").write_text(
            json.dumps({"status": "pending", "action": "write_file", "args": {"path": "index.html", "content": "x"}}),
            encoding="utf-8",
        )

        with self.assertRaises(MODULE.ApiError) as raised:
            MODULE.resume_run("run-approval-resume")
        self.assertEqual(raised.exception.status, 409)

    def test_run_state_rehydrates_persisted_worker_output(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-output"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "output.log").write_text("first line\nsecond line\n", encoding="utf-8")

        state = MODULE.run_state("run-output")

        self.assertEqual(state["output"], ["first line", "second line"])

    def test_capture_process_persists_worker_output(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-capture"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)

        class DummyProcess:
            def __init__(self):
                self.stdout = iter(["turn 1\n", "finished\r\n"])
                self.returncode = 0

            def wait(self):
                return self.returncode

        MODULE.capture_process("run-capture", DummyProcess())

        self.assertEqual(
            (run_dir / "output.log").read_text(encoding="utf-8"),
            "turn 1\nfinished\n",
        )

    def test_resume_run_launches_only_an_interrupted_record(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-resume"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "progress.json").write_text(
            json.dumps({"status": "running", "turn": 4, "checkpoint": "tool_result"}),
            encoding="utf-8",
        )

        class DummyProcess:
            stdout = None
            returncode = None

            def poll(self):
                return None

            def wait(self):
                self.returncode = 0
                return 0

        process = DummyProcess()
        with patch.object(MODULE.subprocess, "Popen", return_value=process) as popen:
            result = MODULE.resume_run("run-resume")

        self.assertTrue(result["resumed"])
        self.assertEqual(result["status"], "running")
        command = popen.call_args.args[0]
        self.assertIn("--resume-run", command)
        self.assertIn("run-resume", command)

    def test_resume_run_rejects_terminal_records(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-terminal"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "progress.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
        (run_dir / "summary.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")

        with self.assertRaises(MODULE.ApiError) as raised:
            MODULE.resume_run("run-terminal")

        self.assertEqual(raised.exception.status, 409)

    def test_stop_run_terminates_a_live_process_and_leaves_it_interrupted(self) -> None:
        run_dir = MODULE.RUNS_DIR / "run-stop"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True)
        MODULE.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (run_dir / "workspace.json").write_text(json.dumps({"project": str(project_dir)}), encoding="utf-8")
        (run_dir / "progress.json").write_text(json.dumps({"status": "running", "turn": 2}), encoding="utf-8")

        class DummyProcess:
            stdout = None

            def __init__(self):
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = 143

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        process = DummyProcess()
        MODULE.PROCESSES["run-stop"] = process

        result = MODULE.stop_run("run-stop")

        self.assertTrue(process.terminated)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["status"], "interrupted")

    def test_rehydrate_session_restores_context_and_clears_stale_busy_state(self) -> None:
        session_dir = MODULE.SESSION_DIR / "chat-restore"
        project_dir = session_dir / "project"
        project_dir.mkdir(parents=True)
        (project_dir / "notes.md").write_text("keep this project", encoding="utf-8")
        (session_dir / "config.json").write_text(
            json.dumps(
                {
                    "model": "test-model",
                    "reasoning_level": "deep",
                    "max_turns": 12,
                    "max_file_bytes": 60000,
                    "max_total_project_bytes": 500000,
                    "allow_commands": ["node"],
                }
            ),
            encoding="utf-8",
        )
        (session_dir / "workspace.json").write_text(
            json.dumps({"project": str(project_dir), "mode": "managed", "managed": True}),
            encoding="utf-8",
        )
        (session_dir / "workflow.json").write_text(
            json.dumps(
                {
                    "phase": "plan",
                    "status": "active",
                    "summary": "The plan survived the restart.",
                    "next_action": "Implement the first task.",
                    "artifacts": ["notes.md"],
                    "checkpoint_count": 2,
                    "updated_at": "2026-09-19T12:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        transcript = [
            {"role": "system", "content": "restored system prompt"},
            {"role": "user", "content": "Inspect the project."},
            {"role": "assistant", "content": '{"action":"respond","args":{"content":"I inspected it."}}'},
        ]
        (session_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
        (session_dir / "session.json").write_text(
            json.dumps(
                {
                    "session_id": "chat-restore",
                    "status": "thinking",
                    "busy": True,
                    "model": "test-model",
                    "reasoning": {"level": "deep"},
                    "model_calls": 3,
                    "tool_calls": 2,
                    "project": str(project_dir),
                    "workspace_mode": "managed",
                    "job": {
                        "job_id": "job-restore",
                        "status": "running",
                        "attempt": 1,
                        "user_message": "Inspect the project.",
                        "started_at": "2026-09-19T11:59:00+00:00",
                        "updated_at": "2026-09-19T12:00:00+00:00",
                        "finished_at": None,
                        "current_step": 1,
                        "last_action": "model_call",
                        "error": "",
                    },
                    "conversation": [
                        {"role": "user", "content": "Inspect the project."},
                        {"role": "assistant", "content": "I inspected it."},
                    ],
                }
            ),
            encoding="utf-8",
        )

        session = MODULE.InteractiveSession.from_disk("chat-restore")
        state = session.state()

        self.assertEqual(state["status"], "interrupted")
        self.assertFalse(state["busy"])
        self.assertEqual(state["job"]["status"], "interrupted")
        self.assertEqual(state["job"]["job_id"], "job-restore")
        self.assertTrue(state["job"]["user_message_persisted"])
        self.assertEqual(state["conversation"][1]["content"], "I inspected it.")
        self.assertEqual(state["workflow"]["phase"], "plan")
        self.assertEqual(session.harness.messages, transcript)
        self.assertEqual(session.harness.model_calls, 3)
        self.assertEqual(session.harness.tool_calls, 2)
        self.assertTrue(any(event["event"] == "session_rehydrated" for event in state["events"]))
        self.assertTrue(any(event["event"] == "job_interrupted" for event in state["events"]))

    def test_retry_reuses_interrupted_message_without_duplicate_conversation_entry(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-retry", project_path=str(project))
        session.conversation = [{"role": "user", "content": "Continue the build."}]
        session.harness.messages.append({"role": "user", "content": session.harness.user_content("Continue the build.")})
        session.job = MODULE.new_job("Continue the build.", job_id="job-old", now="2026-09-20T01:00:00+00:00")
        session.job = MODULE.mark_user_message_persisted(session.job, now="2026-09-20T01:00:30+00:00")
        session.job = MODULE.mark_interrupted(session.job, now="2026-09-20T01:01:00+00:00", reason="server stopped")
        session.status = "interrupted"
        session.busy = False
        started: list[tuple[str, str]] = []
        session._start_worker = lambda content, job_id, append_user=True: started.append((content, job_id))

        session.retry()
        state = session.state()

        self.assertEqual(started, [("Continue the build.", "job-old-attempt-2")])
        self.assertEqual(state["status"], "thinking")
        self.assertTrue(state["busy"])
        self.assertEqual(state["job"]["status"], "running")
        self.assertEqual(state["job"]["attempt"], 2)
        self.assertEqual(len(state["conversation"]), 1)

    def test_stop_marks_an_interactive_job_interrupted_and_rejects_late_completion(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-stop", project_path=str(project))
        session.job = MODULE.new_job("Stop this turn.", job_id="job-stop", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True

        session.stop()
        session._finish_worker("job-stop", error=None)
        state = session.state()

        self.assertEqual(state["status"], "interrupted")
        self.assertFalse(state["busy"])
        self.assertEqual(state["job"]["status"], "interrupted")
        self.assertIn("Stopped by the user", state["job"]["error"])
        self.assertTrue(any(event["event"] == "job_stop_requested" for event in state["events"]))

    def test_interrupted_job_rejects_a_new_message_until_retried(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-recovery-gate", project_path=str(project))
        session.job = MODULE.mark_interrupted(
            MODULE.new_job("Finish the build.", job_id="job-recovery", now="2026-09-20T01:00:00+00:00"),
            now="2026-09-20T01:01:00+00:00",
            reason="server stopped",
        )
        session.status = "interrupted"
        session.busy = False

        with self.assertRaises(MODULE.ApiError) as raised:
            session.send("Start something else.")

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(session.state()["job"]["user_message"], "Finish the build.")

    def test_stale_worker_cannot_clear_a_newer_attempt(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-worker-guard", project_path=str(project))
        session.job = MODULE.new_job("Do the work.", job_id="job-new", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True

        session._finish_worker("job-old", error=None)
        state = session.state()

        self.assertEqual(state["job"]["job_id"], "job-new")
        self.assertEqual(state["job"]["status"], "running")
        self.assertTrue(state["busy"])

    def test_worker_checkpoint_persists_progress_and_transcript(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-progress", project_path=str(project))
        session.job = MODULE.new_job("Inspect it.", job_id="job-progress", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True
        session.harness.messages.append({"role": "user", "content": session.harness.user_content("Inspect it.")})

        self.assertTrue(session._checkpoint_worker("job-progress", 2, "model_response"))

        persisted = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))
        transcript = json.loads((session.run_dir / "transcript.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["job"]["current_step"], 2)
        self.assertEqual(persisted["job"]["last_action"], "model_response")
        self.assertEqual(transcript[-1]["role"], "user")

    def test_retry_endpoint_returns_a_thinking_session(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-endpoint", project_path=str(project))
        session.conversation = [{"role": "user", "content": "Retry this."}]
        session.job = MODULE.mark_interrupted(
            MODULE.new_job("Retry this.", job_id="job-endpoint", now="2026-09-20T01:00:00+00:00"),
            now="2026-09-20T01:01:00+00:00",
            reason="server stopped",
        )
        session.status = "interrupted"
        session.busy = False
        session._start_worker = lambda content, job_id, append_user=True: None
        MODULE.SESSIONS[session.session_id] = session

        from http.client import HTTPConnection
        import threading

        http_server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        server_thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", http_server.server_port)
            connection.request(
                "POST",
                "/api/sessions/chat-endpoint/retry",
                body="{}",
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            http_server.shutdown()
            http_server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(response.status, 202)
        self.assertEqual(payload["status"], "thinking")
        self.assertEqual(payload["job"]["attempt"], 2)

    def test_stop_endpoint_marks_an_active_session_interrupted(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-stop-endpoint", project_path=str(project))
        session.job = MODULE.new_job("Stop this.", job_id="job-stop-endpoint", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True
        MODULE.SESSIONS[session.session_id] = session

        from http.client import HTTPConnection
        import threading

        http_server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        server_thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", http_server.server_port)
            connection.request(
                "POST",
                "/api/sessions/chat-stop-endpoint/stop",
                body="{}",
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            http_server.shutdown()
            http_server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(response.status, 202)
        self.assertEqual(payload["status"], "interrupted")
        self.assertEqual(payload["job"]["status"], "interrupted")

    def test_resume_endpoint_routes_to_the_run_resumer(self) -> None:
        from http.client import HTTPConnection
        import threading

        http_server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with patch.object(
                MODULE,
                "resume_run",
                return_value={"run_id": "run-http", "status": "running", "resumed": True},
            ) as resumer:
                connection = HTTPConnection("127.0.0.1", http_server.server_port)
                connection.request(
                    "POST",
                    "/api/runs/run-http/resume",
                    body="{}",
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            http_server.shutdown()
            http_server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(response.status, 202)
        self.assertEqual(payload["run_id"], "run-http")
        resumer.assert_called_once_with("run-http")

    def test_stop_endpoint_routes_to_the_run_stopper(self) -> None:
        from http.client import HTTPConnection
        import threading

        http_server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with patch.object(
                MODULE,
                "stop_run",
                return_value={"run_id": "run-http", "status": "interrupted", "stopped": True},
            ) as stopper:
                connection = HTTPConnection("127.0.0.1", http_server.server_port)
                connection.request(
                    "POST",
                    "/api/runs/run-http/stop",
                    body="{}",
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            http_server.shutdown()
            http_server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(response.status, 202)
        self.assertEqual(payload["status"], "interrupted")
        stopper.assert_called_once_with("run-http")

    def test_favicon_asset_is_served(self) -> None:
        from http.client import HTTPConnection
        import threading

        http_server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        server_thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", http_server.server_port)
            connection.request("GET", "/favicon.svg?v=20260920-studio-8")
            response = connection.getresponse()
            body = response.read()
        finally:
            http_server.shutdown()
            http_server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "image/svg+xml; charset=utf-8")
        self.assertIn(b"<svg", body)

    def test_worker_completion_marks_job_completed(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-complete", project_path=str(project))
        session.job = MODULE.new_job("Say done.", job_id="job-complete", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True
        session.harness.call_model = lambda: {
            "content": json.dumps({"action": "respond", "args": {"content": "Done."}}),
            "finish_reason": "stop",
        }

        session.process("Say done.", "job-complete", append_user=True)
        state = session.state()

        self.assertEqual(state["status"], "ready")
        self.assertFalse(state["busy"])
        self.assertEqual(state["job"]["status"], "completed")
        self.assertEqual(state["conversation"][-1]["content"], "Done.")

    def test_interactive_duplicate_action_is_not_dispatched_twice_and_is_persisted(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-duplicate", project_path=str(project))
        session.harness.config["max_turns"] = 4
        session.job = MODULE.new_job("Inspect the project.", job_id="job-duplicate", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True
        read = json.dumps({"action": "list_files", "args": {"path": "."}})
        respond = json.dumps({"action": "respond", "args": {"content": "I inspected it."}})
        responses = iter([read, read, respond])
        session.harness.call_model = lambda: {"content": next(responses), "finish_reason": "stop"}
        original_dispatch = session.harness.dispatch
        dispatched: list[str] = []

        def dispatch(action: str, args: dict[str, object]) -> dict[str, object]:
            dispatched.append(action)
            return original_dispatch(action, args)

        session.harness.dispatch = dispatch

        session.process("Inspect the project.", "job-duplicate", append_user=True)
        state = session.state()
        persisted = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))

        self.assertEqual(dispatched, ["list_files"])
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["job"]["status"], "completed")
        self.assertEqual(state["conversation"][-1]["content"], "I inspected it.")
        self.assertEqual(persisted["recovery"], state["recovery"])
        self.assertTrue(any(event["event"] == "recovery_duplicate_action" for event in state["events"]))

    def test_interactive_exhausted_recovery_is_visible_but_does_not_poison_session(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-recovery-stop", project_path=str(project))
        session.harness.config["max_turns"] = 4
        session.job = MODULE.new_job("Do the work.", job_id="job-recovery-stop", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True
        responses = iter(["not json", "not json"])
        session.harness.call_model = lambda: {"content": next(responses), "finish_reason": "stop"}

        session.process("Do the work.", "job-recovery-stop", append_user=True)
        state = session.state()

        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["job"]["status"], "completed")
        self.assertIn("stopped after one repair", state["conversation"][-1]["content"])
        self.assertTrue(any(event["event"] == "recovery_exhausted" for event in state["events"]))

    def test_recovery_snapshot_survives_interactive_rehydration(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-recovery-restore", project_path=str(project))
        session.harness.recovery.record_failure("invalid_model_action", "bad JSON")
        session.save_meta()

        restored = MODULE.InteractiveSession.from_disk("chat-recovery-restore")

        self.assertEqual(restored.state()["recovery"], session.state()["recovery"])

    def test_worker_failure_marks_job_failed_and_waits_for_retry(self) -> None:
        project = Path(self.temp_dir.name) / "project"
        project.mkdir()
        session = MODULE.InteractiveSession("chat-failure", project_path=str(project))
        session.job = MODULE.new_job("Try this.", job_id="job-failure", now="2026-09-20T01:00:00+00:00")
        session.status = "thinking"
        session.busy = True

        def fail_model() -> dict[str, str]:
            raise RuntimeError("model unavailable")

        session.harness.call_model = fail_model
        session.process("Try this.", "job-failure", append_user=True)
        state = session.state()

        self.assertEqual(state["status"], "error")
        self.assertFalse(state["busy"])
        self.assertEqual(state["job"]["status"], "failed")
        self.assertEqual(state["job"]["error"], "model unavailable")

    def test_restore_sessions_discovers_persisted_records(self) -> None:
        session_dir = MODULE.SESSION_DIR / "chat-discover"
        project_dir = session_dir / "project"
        project_dir.mkdir(parents=True)
        (session_dir / "session.json").write_text(
            json.dumps(
                {
                    "session_id": "chat-discover",
                    "status": "ready",
                    "busy": False,
                    "project": str(project_dir),
                    "conversation": [],
                }
            ),
            encoding="utf-8",
        )

        restored = MODULE.restore_sessions()

        self.assertEqual(restored, ["chat-discover"])
        self.assertIn("chat-discover", MODULE.SESSIONS)


if __name__ == "__main__":
    unittest.main()

