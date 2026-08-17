from __future__ import annotations
from typing import Any

import dlt
import requests

from edgerunner.sheets import write_records_to_sheet
from edgerunner.task_config import TaskSettings, run_task


def fetch_repo(settings: TaskSettings) -> dict[str, Any]:
    response = requests.get(
        settings["api_endpoint"],
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=int(settings.get("api_timeout_seconds", 30)),
    )
    response.raise_for_status()
    return response.json()


def transform_repo(repo: dict[str, Any]) -> dict[str, Any]:
    license_info = repo.get("license") or {}
    owner = repo.get("owner") or {}
    return {
        "full_name": repo["full_name"],
        "owner": owner.get("login", ""),
        "description": repo.get("description", ""),
        "html_url": repo["html_url"],
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "open_issues": repo["open_issues_count"],
        "default_branch": repo["default_branch"],
        "license": license_info.get("name", ""),
        "updated_at": repo["updated_at"],
        "pushed_at": repo["pushed_at"],
    }


def load_with_dlt(settings: TaskSettings, record: dict[str, Any]) -> str:
    @dlt.resource(
        name=settings["dlt_table_name"],
        write_disposition=settings.get("dlt_write_disposition", "replace"),
    )
    def repo_resource():
        yield record

    pipeline = dlt.pipeline(
        pipeline_name=settings["dlt_pipeline_name"],
        destination="duckdb",
        dataset_name=settings["dlt_dataset_name"],
    )
    return str(pipeline.run(repo_resource()))


def run(settings: TaskSettings) -> dict[str, Any]:
    record = transform_repo(fetch_repo(settings))
    load_info = load_with_dlt(settings, record)

    sheet_rows = write_records_to_sheet(
        spreadsheet_id=settings.sheet_id,
        tab_name=settings.tab_name,
        records=[record],
        write_mode=settings.get("sheet_write_mode", "replace"),
        skip_sheet=settings.skip_sheet,
    )

    return {
        "task": settings.name,
        "record_count": 1,
        "wrote_sheet": not settings.skip_sheet,
        # Header row plus data rows, whether or not the write actually happened.
        "sheet_row_count": len(sheet_rows),
        "load_info": load_info,
    }


def main() -> None:
    run_task(run)


if __name__ == "__main__":
    main()
