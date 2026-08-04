from __future__ import annotations

from typing import Any

from edgerunner.task_config import TaskSettings, run_task
from tasks.shared.google_sheet_to_sheet import run as sheet_transfer


def build_follow_up_summary(
    settings: TaskSettings,
    sheet_transfer_result: dict[str, Any],
) -> dict[str, Any]:
    # This is the "do something else" step in the demo.
    # Replace this with a real downstream action, such as writing an audit table,
    # calling another API, or preparing TaskSettings for another imported task.
    return {
        "message": "Finished sheet transfer and built a downstream summary.",
        "task_name": settings.name,
        "target_tab_name": settings.tab_name,
        "transferred_record_count": sheet_transfer_result["record_count"],
        "date_window": {
            "start_date": sheet_transfer_result["start_date"],
            "end_date": sheet_transfer_result["end_date"],
        },
    }


def run(settings: TaskSettings) -> dict[str, Any]:
    # A composed task is still a normal task script. It receives one TaskSettings
    # object from tasks.toml, calls another task's run(settings), then continues
    # with its own logic.
    sheet_transfer_result = sheet_transfer(settings)
    follow_up_result = build_follow_up_summary(settings, sheet_transfer_result)

    print(follow_up_result["message"])

    return {
        "task": settings.name,
        "sheet_transfer": sheet_transfer_result,
        "follow_up": follow_up_result,
    }


def main() -> None:
    run_task(run)


if __name__ == "__main__":
    main()
