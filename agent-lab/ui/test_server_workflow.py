from __future__ import annotations

import io
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


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

    def test_interactive_contract_exposes_exact_replace_text_action(self) -> None:
        self.assertIn("replace_text", MODULE.INTERACTIVE_ACTIONS)
        self.assertIn('"action":"replace_text"', MODULE.INTERACTIVE_SYSTEM_PROMPT)
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
