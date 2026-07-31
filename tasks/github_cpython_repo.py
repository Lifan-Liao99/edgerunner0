from __future__ import annotations

import argparse
from typing import Any

import dlt
from dotenv import load_dotenv
import requests
from requests import RequestException

from edgerunner.sheets import write_records_to_sheet
from edgerunner.task_config import load_task_settings


TASK_NAME = "github_cpython_repo"
API_ENDPOINT = "https://api.github.com/repos/python/cpython"
SAMPLE_REPO = {
    "full_name": "python/cpython",
    "description": "The Python programming language",
    "html_url": "https://github.com/python/cpython",
    "stargazers_count": 0,
    "forks_count": 0,
    "open_issues_count": 0,
    "default_branch": "main",
    "updated_at": "2026-07-31T00:00:00Z",
    "pushed_at": "2026-07-31T00:00:00Z",
    "owner": {"login": "python"},
    "license": {"name": "Python Software Foundation License"},
}


def fetch_repo(*, use_sample_on_failure: bool) -> dict[str, Any]:
    try:
        response = requests.get(
            API_ENDPOINT,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except RequestException as exc:
        if use_sample_on_failure:
            print(f"Could not reach {API_ENDPOINT}; using bundled sample data. Error: {exc}")
            return SAMPLE_REPO
        raise RuntimeError(
            f"Could not reach {API_ENDPOINT}. Check network/proxy access or rerun with "
            "--use-sample-on-failure for local smoke testing."
        ) from exc


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


def load_with_dlt(record: dict[str, Any]) -> str:
    @dlt.resource(name="repo_metadata", write_disposition="replace")
    def repo_resource():
        yield record

    pipeline = dlt.pipeline(
        pipeline_name="github_cpython_repo_pipeline",
        destination="duckdb",
        dataset_name="github",
    )
    return str(pipeline.run(repo_resource()))


def main() -> None:
    load_dotenv()
    settings = load_task_settings(TASK_NAME)

    parser = argparse.ArgumentParser(description="Load GitHub CPython repo metadata.")
    parser.add_argument("--skip-sheet", action="store_true")
    parser.add_argument("--use-sample-on-failure", action="store_true")
    args = parser.parse_args()

    record = transform_repo(fetch_repo(use_sample_on_failure=args.use_sample_on_failure))
    load_info = load_with_dlt(record)

    if not args.skip_sheet:
        write_records_to_sheet(
            spreadsheet_id=settings.sheet_id,
            tab_name=settings.tab_name,
            records=[record],
            write_mode="replace",
        )

    print(
        {
            "task": settings.name,
            "record_count": 1,
            "wrote_sheet": not args.skip_sheet,
            "load_info": load_info,
        }
    )


if __name__ == "__main__":
    main()
