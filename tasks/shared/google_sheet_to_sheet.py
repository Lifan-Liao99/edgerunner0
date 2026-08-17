from __future__ import annotations
from datetime import date, timedelta
from typing import Any

import pandas as pd

from edgerunner.sheets import read_records_from_sheet, write_records_to_sheet
from edgerunner.task_config import (
    TaskSettings,
    business_today,
    date_from_offset,
    run_task,
)


def local_fixture_records() -> list[dict[str, Any]]:
    """Stand-in source rows for --skip-sheet runs.

    Shaped like the real source tab: first column is the date the window filter
    reads. The dates are relative to today rather than fixed, so some rows fall
    inside the configured window and some outside. That way a local run actually
    exercises filter_dataframe_by_date_window instead of passing an empty frame
    through it, where any filtering bug would look like a pass.
    """
    today = business_today()
    return [
        {
            "date": (today - timedelta(days=days_ago)).isoformat(),
            "store": store,
            "revenue": revenue,
        }
        for days_ago, store, revenue in (
            (0, "store_a", "140.00"),
            (2, "store_a", "220.50"),
            (5, "store_b", "180.25"),
            (30, "store_c", "90.75"),
        )
    ]


def fetch_source_dataframe(settings: TaskSettings) -> pd.DataFrame:
    records = read_records_from_sheet(
        spreadsheet_id=settings["source_sheet_id"],
        tab_name=settings["source_tab_name"],
        read_range=settings.get("source_range"),
        skip_sheet=settings.skip_sheet,
        mock_response=local_fixture_records(),
    )
    return pd.DataFrame(records)


def filter_dataframe_by_date_window(
    dataframe: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    if dataframe.empty or len(dataframe.columns) == 0:
        return dataframe

    date_column = dataframe.columns[0]
    parsed_dates = pd.to_datetime(
        dataframe[date_column],
        errors="coerce",
        format="mixed",
    ).dt.normalize()
    mask = parsed_dates.between(
        pd.Timestamp(start_date),
        pd.Timestamp(end_date),
        inclusive="both",
    )
    return dataframe.loc[mask].copy()


def run(settings: TaskSettings) -> dict[str, Any]:
    source_dataframe = fetch_source_dataframe(settings)
    start_date = date.fromisoformat(date_from_offset(settings["start_date_offset"]))
    end_date = date.fromisoformat(date_from_offset(settings["end_date_offset"]))
    filtered_dataframe = filter_dataframe_by_date_window(
        source_dataframe,
        start_date=start_date,
        end_date=end_date,
    )

    write_records_to_sheet(
        spreadsheet_id=settings.sheet_id,
        tab_name=settings.tab_name,
        records=filtered_dataframe,
        write_mode=settings.get("sheet_write_mode", "replace"),
        upsert_key_columns=settings.get("sheet_upsert_key_columns"),
        skip_sheet=settings.skip_sheet,
    )

    return {
        "task": settings.name,
        "source_sheet_id": settings["source_sheet_id"],
        "source_tab_name": settings["source_tab_name"],
        "source_range": settings.get("source_range"),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "target_sheet_id": settings.sheet_id,
        "target_tab_name": settings.tab_name,
        "source_record_count": len(source_dataframe),
        "record_count": len(filtered_dataframe),
        "wrote_sheet": not settings.skip_sheet,
    }


def main() -> None:
    run_task(run)


if __name__ == "__main__":
    main()
