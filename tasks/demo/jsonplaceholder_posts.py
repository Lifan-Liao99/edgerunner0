from __future__ import annotations
from typing import Any

import dlt
import requests

from edgerunner.sheets import write_records_to_sheet
from edgerunner.task_config import TaskSettings, run_task


def fetch_posts(settings: TaskSettings) -> list[dict[str, Any]]:
    response = requests.get(
        settings["api_endpoint"],
        headers={"Accept": "application/json"},
        params=settings.get("api_query", {}),
        timeout=int(settings.get("api_timeout_seconds", 30)),
    )
    response.raise_for_status()
    return response.json()


def transform_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": post["id"],
            "user_id": post["userId"],
            "title": post["title"],
            "body": post["body"],
            "title_length": len(post["title"]),
        }
        for post in posts
    ]


def load_with_dlt(settings: TaskSettings, records: list[dict[str, Any]]) -> str:
    @dlt.resource(
        name=settings["dlt_table_name"],
        write_disposition=settings.get("dlt_write_disposition", "replace"),
    )
    def posts_resource():
        yield from records

    pipeline = dlt.pipeline(
        pipeline_name=settings["dlt_pipeline_name"],
        destination="duckdb",
        dataset_name=settings["dlt_dataset_name"],
    )
    return str(pipeline.run(posts_resource()))


def run(settings: TaskSettings) -> dict[str, Any]:
    records = transform_posts(fetch_posts(settings))
    load_info = load_with_dlt(settings, records)

    sheet_rows = write_records_to_sheet(
        spreadsheet_id=settings.sheet_id,
        tab_name=settings.tab_name,
        records=records,
        write_mode=settings.get("sheet_write_mode", "replace"),
        skip_sheet=settings.skip_sheet,
    )

    return {
        "task": settings.name,
        "record_count": len(records),
        "wrote_sheet": not settings.skip_sheet,
        # Header row plus data rows, whether or not the write actually happened.
        "sheet_row_count": len(sheet_rows),
        "load_info": load_info,
    }


def main() -> None:
    run_task(run)


if __name__ == "__main__":
    main()
