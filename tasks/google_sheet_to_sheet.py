from __future__ import annotations
from datetime import date
from typing import Any

import pandas as pd

from edgerunner.sheets import read_records_from_sheet, write_records_to_sheet
from edgerunner.task_config import (
    TaskSettings,
    date_from_offset,
    run_task,
)


def fetch_source_dataframe(settings: TaskSettings) -> pd.DataFrame:
    records = read_records_from_sheet(
        spreadsheet_id=settings["source_sheet_id"],
        tab_name=settings["source_tab_name"],
        read_range=settings.get("source_range"),
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

    if not settings.skip_sheet:
        write_records_to_sheet(
            spreadsheet_id=settings.sheet_id,
            tab_name=settings.tab_name,
            records=filtered_dataframe,
            write_mode=settings.get("sheet_write_mode", "replace"),
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
