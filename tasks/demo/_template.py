"""Minimal task template. Copy this file to `tasks/<client>/my_job.py`.

After copying:

1. Put all job-specific logic inside `run(settings)`.
2. Add one matching entry to `config/tasks.toml`.
3. Regenerate workflows: `python scripts/generate_workflows.py`.

Example TOML:

    [[tasks]]
    name = "my_job"
    script_path = "tasks/<client>/my_job.py"
    cron_setting = "0 5 * * *"
    sheet_id = "YOUR_GOOGLE_SHEET_ID"
    tab_name = "my_job"
    gcp_auth = true
    api_endpoint = "https://api.example.com/data"
    api_query = { limit = 100 }
    api_timeout_seconds = 30
    sheet_write_mode = "replace"
    start_date_offset = -30
    end_date_offset = -1
    manual_overrides = [
      { name = "limit", path = "api_query.limit", description = "API result limit for manual runs" },
      { name = "startdate", path = "start_date_offset", description = "Start date, YYYY-MM-DD. Converted using New York time." },
      { name = "enddate", path = "end_date_offset", description = "End date, YYYY-MM-DD. Converted using New York time." },
    ]

Local check without writing to Sheets:

    python tasks/<client>/my_job.py --task-name my_job --skip-sheet
"""

from __future__ import annotations

from typing import Any

from edgerunner.task_config import TaskSettings, run_task


def run(settings: TaskSettings) -> dict[str, Any]:
    # `run_task(run)` handles CLI args, loads config/tasks.toml, applies manual
    # overrides, and then passes the final settings into this function.

    # Required settings should use settings["key"] so missing config fails fast.
    # Optional settings can use settings.get("key", default).
    #
    #     endpoint = settings["api_endpoint"]
    #     timeout = int(settings.get("api_timeout_seconds", 30))
    #     query = dict(settings.get("api_query", {}))

    # Reserved date offsets are integers relative to New York "today".
    # If start_date_offset/end_date_offset exist in TOML, manual workflow runs
    # can accept startdate/enddate strings like 2026-08-01; the framework turns
    # those dates back into offsets before this function receives settings.
    #
    #     from edgerunner.task_config import date_from_offset
    #
    #     start_date = date_from_offset(settings["start_date_offset"])
    #     end_date = date_from_offset(settings["end_date_offset"])
    #
    # Put those strings into whatever parameter names your API expects.

    # For API credentials, keep only the Secret Manager version name in TOML:
    #
    #     api_token_secret_version = "projects/PROJECT/secrets/NAME/versions/latest"
    #
    # Then read it here:
    #
    #     from edgerunner.secrets import access_secret
    #
    #     token = access_secret(settings["api_token_secret_version"])
    #     headers = {"Authorization": f"Bearer {token}"}

    # TODO: Implement your task logic here.
    #
    # Common shape:
    #
    #     1. Read source data from an API, a Sheet, or another system.
    #     2. Transform it into a list of dicts if you want to write to Sheets.
    #     3. Write results, call another service, or return a summary.
    #
    # For Sheets output:
    #
    #     from edgerunner.sheets import write_records_to_sheet
    #
    #     records = [{"id": "123", "name": "Example"}]
    #     if not settings.skip_sheet:
    #         write_records_to_sheet(
    #             spreadsheet_id=settings.sheet_id,
    #             tab_name=settings.tab_name,
    #             records=records,  # Also accepts a pandas DataFrame.
    #             write_mode=settings.get("sheet_write_mode", "replace"),
    #         )
    #
    # Keys become column headers. Nested dicts are flattened by the Sheets helper;
    # lists and other non-scalar values are JSON encoded.

    # `--skip-sheet` becomes settings.skip_sheet for local dry runs.
    # Use it for any side effect you want to avoid during local checks.

    # Returning a value is optional. run_task prints non-None return values.
    return {
        "task": settings.name,
        "wrote_sheet": not settings.skip_sheet,
    }


def main() -> None:
    run_task(run)


if __name__ == "__main__":
    main()
