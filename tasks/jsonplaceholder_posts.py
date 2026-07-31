from __future__ import annotations

import argparse
from typing import Any

import dlt
from dotenv import load_dotenv
import requests
from requests import RequestException

from edgerunner.sheets import write_records_to_sheet
from edgerunner.task_config import load_task_settings


TASK_NAME = "jsonplaceholder_posts"
API_ENDPOINT = "https://jsonplaceholder.typicode.com/posts"
SAMPLE_POSTS = [
    {
        "userId": 1,
        "id": 1,
        "title": "sample public-api post",
        "body": "Used when the local network cannot reach the public endpoint.",
    },
    {
        "userId": 1,
        "id": 2,
        "title": "second sample post",
        "body": "The real workflow still calls the public endpoint by default.",
    },
]


def fetch_posts(*, use_sample_on_failure: bool) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            API_ENDPOINT,
            headers={"Accept": "application/json"},
            params={"userId": 1},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except RequestException as exc:
        if use_sample_on_failure:
            print(f"Could not reach {API_ENDPOINT}; using bundled sample data. Error: {exc}")
            return SAMPLE_POSTS
        raise RuntimeError(
            f"Could not reach {API_ENDPOINT}. Check network/proxy access or rerun with "
            "--use-sample-on-failure for local smoke testing."
        ) from exc


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
    load_dotenv()
    settings = load_task_settings(TASK_NAME)

    parser = argparse.ArgumentParser(description="Load JSONPlaceholder posts.")
    parser.add_argument("--skip-sheet", action="store_true")
    parser.add_argument("--use-sample-on-failure", action="store_true")
    args = parser.parse_args()

    records = transform_posts(fetch_posts(use_sample_on_failure=args.use_sample_on_failure))
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
