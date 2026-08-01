"""Template for a new task script. Not a task itself; nothing runs this file.

To use it:

1. Copy to `tasks/my_job.py`.
2. Rename the `fetch_items` / `transform_items` functions to fit the job.
3. Add the matching entry to `config/tasks.toml` (see below).
4. Regenerate workflows: `python scripts/generate_workflows.py`

The TOML entry this template expects. `name` through `gcp_auth` are the fields
the generator requires; everything after them is this script's own parameters,
so add or drop keys as the job needs:

    [[tasks]]
    name = "my_job"
    script_path = "tasks/my_job.py"
    cron_setting = "0 5 * * *"
    sheet_id = "YOUR_GOOGLE_SHEET_ID"
    tab_name = "my_job"
    gcp_auth = true
    api_endpoint = "https://api.example.com/data"
    api_query = { limit = 100 }
    api_timeout_seconds = 30
    dlt_pipeline_name = "my_job_pipeline"
    dlt_dataset_name = "my_dataset"
    dlt_table_name = "my_table"
    dlt_write_disposition = "replace"
    sheet_write_mode = "replace"
    start_date_offset = -30
    end_date_offset = -1
    manual_overrides = [
      { name = "limit", path = "api_query.limit", description = "API result limit for manual runs" },
    ]

Check it locally without writing to Sheets:

    python tasks/my_job.py --task-name my_job --skip-sheet
"""

from __future__ import annotations
from typing import Any

import dlt
import requests

from edgerunner.sheets import write_records_to_sheet
from edgerunner.task_config import TaskSettings, load_task_settings, parse_task_args


def fetch_items(settings: TaskSettings) -> list[dict[str, Any]]:
    """Call the source API. Every knob comes from the TOML entry, not from code."""
    headers = {"Accept": "application/json"}

    # If the endpoint needs a credential, read it from Secret Manager at runtime
    # rather than putting it in config/tasks.toml, which is checked in:
    #
    #     from edgerunner.secrets import access_secret
    #
    #     token = access_secret(settings["api_token_secret_version"])
    #     headers["Authorization"] = f"Bearer {token}"
    #
    # where the TOML holds only the address of the secret, not its value:
    #
    #     api_token_secret_version = "projects/PROJECT/secrets/NAME/versions/latest"

    response = requests.get(
        settings["api_endpoint"],
        headers=headers,
        params=settings.get("api_query", {}),
        timeout=int(settings.get("api_timeout_seconds", 30)),
    )
    response.raise_for_status()
    return response.json()


def transform_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape the payload into flat records: one dict per row, keys become columns.

    Nested dicts are flattened into dotted column names on the way to Sheets, and
    anything that is not a str/int/float/bool is JSON encoded, so returning
    nested values is allowed but explicit fields read better in the sheet.
    """
    return [
        {
            "id": item["id"],
            "name": item.get("name", ""),
        }
        for item in items
    ]


def load_with_dlt(settings: TaskSettings, records: list[dict[str, Any]]) -> str:
    """Load records into the local duckdb destination via dlt."""

    @dlt.resource(
        name=settings["dlt_table_name"],
        write_disposition=settings.get("dlt_write_disposition", "replace"),
    )
    def items_resource():
        yield from records

    pipeline = dlt.pipeline(
        pipeline_name=settings["dlt_pipeline_name"],
        destination="duckdb",
        dataset_name=settings["dlt_dataset_name"],
    )
    return str(pipeline.run(items_resource()))


def main() -> None:
    args = parse_task_args("One line describing what this task does.")
    settings = load_task_settings(args.task_name)

    # --- Reading settings -- copy the patterns you need -----------------------
    #
    # Fields the generator knows about have convenience properties:
    #
    #     settings.name           settings.sheet_id      settings.gcp_auth
    #     settings.script_path    settings.tab_name      settings.cron_setting
    #
    # Every other key in the TOML entry is this script's own parameter:
    #
    #     settings["api_endpoint"]                  required; KeyError if missing
    #     settings.get("api_timeout_seconds", 30)   optional, with a default
    #     settings.params                           the whole entry as a dict
    #
    # Prefer settings[...] for anything the task cannot run without, so a
    # misconfigured entry fails immediately instead of silently using a default.
    #
    # If the TOML entry has manual_overrides, GitHub workflow_dispatch inputs and
    # local --override values are merged before the settings reach this script.
    # Scheduled runs keep the default TOML values.
    #
    # start_date_offset and end_date_offset are reserved fields. If a task has
    # them, generated workflows expose startdate/enddate inputs for manual runs;
    # those YYYY-MM-DD dates are converted back into integer offsets using New
    # York time. Use edgerunner.task_config.date_from_offset() to turn offsets
    # into API date strings with the same timezone convention.
    #
    # One script can back several tasks: add multiple TOML entries with the same
    # script_path and different name values. --task-name picks which entry loads,
    # so read all environment-specific values from settings and none from module
    # level constants.
    # -------------------------------------------------------------------------

    records = transform_items(fetch_items(settings))
    load_info = load_with_dlt(settings, records)

    if not args.skip_sheet:
        write_records_to_sheet(
            spreadsheet_id=settings.sheet_id,
            tab_name=settings.tab_name,
            records=records,
            write_mode=settings.get("sheet_write_mode", "replace"),
        )

    print(
        {
            "task": settings.name,
            "record_count": len(records),
            "wrote_sheet": not args.skip_sheet,
            "load_info": load_info,
        }
    )


if __name__ == "__main__":
    main()
