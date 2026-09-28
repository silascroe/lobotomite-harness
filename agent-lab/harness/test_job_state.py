from __future__ import annotations

import unittest

from job_state import (
    JobStateError,
    complete_job,
    fail_job,
    mark_interrupted,
    mark_waiting_approval,
    new_job,
    normalize_job,
    start_attempt,
    resume_approval,
    update_progress,
)


class JobStateTests(unittest.TestCase):
    def test_new_job_has_a_persistable_running_shape(self) -> None:
        job = new_job("Build the page", job_id="job-1", now="2026-09-20T01:00:00+00:00")

        self.assertEqual(job["status"], "running")
        self.assertEqual(job["attempt"], 1)
        self.assertEqual(job["user_message"], "Build the page")
        self.assertEqual(job["job_id"], "job-1")
        self.assertEqual(job["current_step"], 0)

    def test_interrupted_job_can_start_an_explicit_new_attempt(self) -> None:
        running = new_job("Build the page", job_id="job-1", now="2026-09-20T01:00:00+00:00")
        interrupted = mark_interrupted(running, now="2026-09-20T01:05:00+00:00", reason="server stopped")

        retried = start_attempt(interrupted, job_id="job-2", now="2026-09-20T01:06:00+00:00")

        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(retried["status"], "running")
        self.assertEqual(retried["attempt"], 2)
        self.assertEqual(retried["user_message"], "Build the page")
        self.assertEqual(retried["job_id"], "job-2")
        self.assertEqual(retried["error"], "")

    def test_progress_and_terminal_transitions_preserve_observable_evidence(self) -> None:
        running = new_job("Inspect files", job_id="job-1", now="2026-09-20T01:00:00+00:00")
        progressed = update_progress(running, step=2, action="tool_result", now="2026-09-20T01:01:00+00:00")
        completed = complete_job(progressed, now="2026-09-20T01:02:00+00:00")

        self.assertEqual(progressed["current_step"], 2)
        self.assertEqual(progressed["last_action"], "tool_result")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["finished_at"], "2026-09-20T01:02:00+00:00")

    def test_retry_is_rejected_for_a_completed_job(self) -> None:
        completed = complete_job(new_job("Done", job_id="job-1", now="2026-09-20T01:00:00+00:00"), now="2026-09-20T01:01:00+00:00")

        with self.assertRaises(JobStateError):
            start_attempt(completed, job_id="job-2", now="2026-09-20T01:02:00+00:00")

    def test_normalize_legacy_or_malformed_state_returns_safe_idle_job(self) -> None:
        normalized = normalize_job({"status": "running", "attempt": "not-a-number"})

        self.assertEqual(normalized["status"], "idle")
        self.assertEqual(normalized["attempt"], 0)
        self.assertEqual(normalized["user_message"], "")

    def test_failed_job_can_be_retried_without_becoming_an_automatic_retry(self) -> None:
        running = new_job("Try it", job_id="job-1", now="2026-09-20T01:00:00+00:00")
        failed = fail_job(running, "model unavailable", now="2026-09-20T01:01:00+00:00")
        retried = start_attempt(failed, job_id="job-2", now="2026-09-20T01:02:00+00:00")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(retried["attempt"], 2)

    def test_waiting_approval_round_trip_preserves_the_turn(self) -> None:
        running = new_job("Change the page", job_id="job-1", now="2026-09-20T01:00:00+00:00")
        waiting = mark_waiting_approval(running, step=3, now="2026-09-20T01:01:00+00:00")
        resumed = resume_approval(waiting, now="2026-09-20T01:02:00+00:00")

        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(waiting["current_step"], 3)
        self.assertEqual(waiting["last_action"], "approval_requested")
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(resumed["current_step"], 3)

    def test_approval_transitions_reject_wrong_source_status(self) -> None:
        running = new_job("Change the page", job_id="job-1")
        with self.assertRaises(JobStateError):
            resume_approval(running)


if __name__ == "__main__":
    unittest.main()

