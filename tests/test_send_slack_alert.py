from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.send_slack_alert import build_payload, main, sanitize_text, task_error_log  # noqa: E402


class LoggedTestCase(unittest.TestCase):
    RESULT_FIELDS = (
        ("failures", "FAIL"),
        ("errors", "ERROR"),
        ("skipped", "SKIP"),
        ("expectedFailures", "EXPECTED_FAIL"),
        ("unexpectedSuccesses", "UNEXPECTED_SUCCESS"),
    )

    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult | None:
        test_name = f"{self.__class__.__name__}.{self._testMethodName}"
        if result is None:
            return super().run(result)

        before_counts = {
            field_name: len(getattr(result, field_name, []))
            for field_name, _status in self.RESULT_FIELDS
        }
        print(f"[RUN] {test_name}", flush=True)

        finished_result = super().run(result)

        status = "PASS"
        for field_name, field_status in self.RESULT_FIELDS:
            if len(getattr(result, field_name, [])) > before_counts[field_name]:
                status = field_status
                break
        print(f"[{status}] {test_name}", flush=True)
        return finished_result


class SendSlackAlertTests(LoggedTestCase):
    def test_build_payload_marks_success_without_error_log(self) -> None:
        # Test: successful task runs should send clean success metadata.
        # Expected: task_status is success and error_log is empty.
        payload = build_payload(
            task_name="google_sheet_to_sheet",
            task_outcome="success",
            task_exit_code="0",
            job_status="success",
            task_log_path=Path("missing.log"),
            run_url="https://example.com/run",
            repository="owner/repo",
            workflow_name="shared / google_sheet_to_sheet",
            branch_name="main",
            trigger="workflow_dispatch",
        )

        self.assertEqual(payload["task_status"], "success")
        self.assertEqual(payload["reason"], "task completed successfully")
        self.assertEqual(payload["error_log"], "")

    def test_build_payload_includes_failure_reason_and_last_sanitized_error_line(self) -> None:
        # Test: failed task runs should include reason plus a short sanitized error.
        # Expected: payload is failure and error_log contains only the final non-empty log line.
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "task.log"
            log_path.write_text(
                "\n".join(
                    [
                        "first line with token=should_not_appear",
                        "",
                        "RuntimeError: Authorization: Bearer secret-token",
                    ]
                ),
                encoding="utf-8",
            )

            payload = build_payload(
                task_name="google_sheet_to_sheet",
                task_outcome="failure",
                task_exit_code="1",
                job_status="failure",
                task_log_path=log_path,
                run_url="https://example.com/run",
                repository="owner/repo",
                workflow_name="shared / google_sheet_to_sheet",
                branch_name="main",
                trigger="schedule",
            )

        self.assertEqual(payload["task_status"], "failure")
        self.assertEqual(payload["reason"], "task exited with code `1`")
        self.assertNotIn("first line", payload["error_log"])
        self.assertNotIn("secret-token", payload["error_log"])
        self.assertEqual(payload["error_log"], "RuntimeError: Authorization: Bearer [REDACTED]")

    def test_task_error_log_handles_missing_log(self) -> None:
        # Test: alerting should still work if the task step did not create a log file.
        # Expected: a readable placeholder is returned instead of raising.
        self.assertIn("did not produce a log", task_error_log(Path("missing.log")))

    def test_sanitize_text_redacts_common_secret_shapes(self) -> None:
        # Test: alerting should redact common credential shapes before sending Slack messages.
        # Expected: known secret values are replaced with [REDACTED].
        text = (
            "api_key=abc123 password:super-secret "
            "url=https://example.com/path?token=tok123&safe=value"
        )

        sanitized = sanitize_text(text)

        self.assertNotIn("abc123", sanitized)
        self.assertNotIn("super-secret", sanitized)
        self.assertNotIn("tok123", sanitized)
        self.assertIn("api_key=[REDACTED]", sanitized)
        self.assertIn("password=[REDACTED]", sanitized)
        self.assertIn("token=[REDACTED]", sanitized)

    def test_main_skips_when_webhook_secret_is_empty(self) -> None:
        # Test: missing Slack webhook should not fail the workflow.
        # Expected: main returns 0 and does not try to post.
        argv = [
            "send_slack_alert.py",
            "--task-name",
            "task",
            "--task-outcome",
            "success",
            "--task-exit-code",
            "0",
            "--job-status",
            "success",
            "--run-url",
            "https://example.com/run",
            "--repository",
            "owner/repo",
            "--workflow-name",
            "workflow",
            "--branch-name",
            "main",
            "--trigger",
            "workflow_dispatch",
        ]

        with (
            patch.object(sys, "argv", argv),
            patch.dict(os.environ, {}, clear=True),
            patch("scripts.send_slack_alert.post_json") as post_json_mock,
        ):
            result = main()

        self.assertEqual(result, 0)
        post_json_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
