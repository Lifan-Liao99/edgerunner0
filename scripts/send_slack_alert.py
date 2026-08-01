from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib import request
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/New_York"
MAX_ERROR_LOG_CHARS = 3000
MAX_ERROR_LOG_LINES = 80


def main() -> int:
    args = parse_args()
    webhook_url = args.webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL is empty; skipping Slack alert.")
        return 0

    payload = build_payload(
        task_name=args.task_name,
        task_outcome=args.task_outcome,
        task_exit_code=args.task_exit_code,
        job_status=args.job_status,
        task_log_path=Path(args.task_log),
        run_url=args.run_url,
        repository=args.repository,
        workflow_name=args.workflow_name,
        branch_name=args.branch_name,
        trigger=args.trigger,
    )
    try:
        post_json(webhook_url, payload)
    except Exception as exc:
        print(f"Slack alert failed to send: {exc}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook-url", default="")
    parser.add_argument("--task-name", required=True)
    parser.add_argument("--task-outcome", required=True)
    parser.add_argument("--task-exit-code", required=True)
    parser.add_argument("--job-status", required=True)
    parser.add_argument("--task-log", default="task.log")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-name", required=True)
    parser.add_argument("--branch-name", required=True)
    parser.add_argument("--trigger", required=True)
    return parser.parse_args()


def build_payload(
    *,
    task_name: str,
    task_outcome: str,
    task_exit_code: str,
    job_status: str,
    task_log_path: Path,
    run_url: str,
    repository: str,
    workflow_name: str,
    branch_name: str,
    trigger: str,
) -> dict[str, str]:
    finished_at = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S %Z")
    is_success = job_status == "success" and task_outcome == "success"
    if is_success:
        status = "success"
        reason = "task completed successfully"
        error_log = ""
    else:
        status = "failure"
        reason = failure_reason(
            task_outcome=task_outcome,
            task_exit_code=task_exit_code,
            job_status=job_status,
        )
        error_log = task_error_log(task_log_path)

    return {
        "task_name": task_name,
        "task_status": status,
        "finished_at": finished_at,
        "reason": reason,
        "error_log": error_log,
        "job_status": job_status,
        "task_outcome": task_outcome,
        "exit_code": task_exit_code,
        "run_url": run_url,
        "repository": repository,
        "workflow_name": workflow_name,
        "branch_name": branch_name,
        "trigger": trigger,
    }


def failure_reason(*, task_outcome: str, task_exit_code: str, job_status: str) -> str:
    if task_outcome == "failure":
        return f"task exited with code `{task_exit_code}`"
    if task_outcome == "skipped":
        return "task step was skipped, likely because an earlier workflow step failed"
    return f"workflow ended with job status `{job_status}` and task outcome `{task_outcome}`"


def task_error_log(task_log_path: Path) -> str:
    if not task_log_path.exists():
        return "(task step did not produce a log; check the GitHub Actions run)"

    log_lines = task_log_path.read_text(errors="replace").splitlines()
    error_log = "\n".join(log_lines[-MAX_ERROR_LOG_LINES:]).strip() or "(task log was empty)"
    if len(error_log) > MAX_ERROR_LOG_CHARS:
        return error_log[-MAX_ERROR_LOG_CHARS:]
    return error_log


def post_json(webhook_url: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30):
        pass


if __name__ == "__main__":
    sys.exit(main())
