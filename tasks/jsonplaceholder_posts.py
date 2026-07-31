from __future__ import annotations

import argparse
from typing import Any

import dlt
import requests

from edgerunner.sheets import write_records_to_sheet
from edgerunner.task_config import load_task_settings


TASK_NAME = "jsonplaceholder_posts"
API_ENDPOINT = "https://jsonplaceholder.typicode.com/posts"


def fetch_posts() -> list[dict[str, Any]]:
    response = requests.get(
        API_ENDPOINT,
        headers={"Accept": "application/json"},
        params={"userId": 1},
        timeout=30,
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


def load_with_dlt(records: list[dict[str, Any]]) -> str:
    @dlt.resource(name="posts", write_disposition="replace")
    def posts_resource():
        yield from records

    pipeline = dlt.pipeline(
        pipeline_name="jsonplaceholder_posts_pipeline",
        destination="duckdb",
        dataset_name="jsonplaceholder",
    )
    return str(pipeline.run(posts_resource()))


def main() -> None:
    settings = load_task_settings(TASK_NAME)

    parser = argparse.ArgumentParser(description="Load JSONPlaceholder posts.")
    parser.add_argument("--skip-sheet", action="store_true")
    args = parser.parse_args()

    records = transform_posts(fetch_posts())
    load_info = load_with_dlt(records)

    if not args.skip_sheet:
        write_records_to_sheet(
            spreadsheet_id=settings.sheet_id,
            tab_name=settings.tab_name,
            records=records,
            write_mode="replace",
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
