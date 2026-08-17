"""Print the resolved config for one task.

The manual test slot is always named "test workflow", so its run page never says
which task it is actually running. This prints that up front, and appends the
same report to the GitHub step summary so it is visible without opening the log.

The values come from config/tasks.toml on the checked-out ref, with manual
overrides applied, so the report shows what the task will really run with rather
than what the workflow file was generated from.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import load_task_settings  # noqa: E402

CONFIG_PATH = ROOT / "config" / "tasks.toml"
FRAMEWORK_FIELDS = ("name", "script_path", "cron_setting", "gcp_auth", "is_test")
# Reported as a list of input names rather than dumped in full: the descriptions
# are documentation for the Run workflow form, not values the task runs with.
OVERRIDES_FIELD = "manual_overrides"


def build_report(task_name: str) -> str:
    settings = load_task_settings(task_name, CONFIG_PATH)
    params = settings.params

    framework = {key: params[key] for key in FRAMEWORK_FIELDS if key in params}
    framework["manual_override_inputs"] = [
        override["name"] for override in settings.manual_overrides
    ]
    custom = {
        key: value
        for key, value in params.items()
        if key not in FRAMEWORK_FIELDS and key != OVERRIDES_FIELD
    }

    lines = [
        f"## Task under test: `{settings.name}`",
        "",
        f"Script: `{settings.script_path}`",
        "",
        "Framework config from `config/tasks.toml`:",
        "",
        "```json",
        json.dumps(framework, indent=2, default=str),
        "```",
        "",
        "Task config, with manual overrides applied:",
        "",
        "```json",
        json.dumps(custom, indent=2, default=str),
        "```",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-name", required=True)
    args = parser.parse_args()

    try:
        report = build_report(args.task_name)
    except ValueError as exc:
        # A task named in a generated workflow but missing from the config means
        # the workflow is stale. Say so instead of failing the run on a
        # traceback from deep inside the task script later on.
        print(
            f"Could not describe task '{args.task_name}': {exc}\n"
            "The workflow may have been generated from a different revision of "
            "config/tasks.toml. Run scripts/generate_workflows.py and commit the result.",
            file=sys.stderr,
        )
        return 1

    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(report + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
