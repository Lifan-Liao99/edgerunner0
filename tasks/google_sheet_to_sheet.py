from __future__ import annotations
from datetime import date, datetime
from typing import Any

from edgerunner.sheets import read_records_from_sheet, write_records_to_sheet
from edgerunner.task_config import (
    TaskSettings,
    date_from_offset,
    load_task_settings,
    parse_task_args,
)


def fetch_source_rows(settings: TaskSettings) -> list[dict[str, Any]]:
    return read_records_from_sheet(
        spreadsheet_id=settings["source_sheet_id"],
        tab_name=settings["source_tab_name"],
        read_range=settings.get("source_range"),
    )


def filter_rows_by_date_window(
    records: list[dict[str, Any]],
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if _date_in_window(_date_from_first_column(record), start_date, end_date)
    ]


def _date_in_window(value: date | None, start_date: date, end_date: date) -> bool:
    return value is not None and start_date <= value <= end_date


def _date_from_first_column(record: dict[str, Any]) -> date | None:
    if not record:
        return None
    return _parse_sheet_date(next(iter(record.values())))


def _parse_sheet_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def main() -> None:
    args = parse_task_args("Copy rows from one Google Sheet to another.")
    settings = load_task_settings(args.task_name)

    source_records = fetch_source_rows(settings)
    start_date = date.fromisoformat(date_from_offset(settings["start_date_offset"]))
    end_date = date.fromisoformat(date_from_offset(settings["end_date_offset"]))
    records = filter_rows_by_date_window(
        source_records,
        start_date=start_date,
        end_date=end_date,
    )

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
            "source_sheet_id": settings["source_sheet_id"],
            "source_tab_name": settings["source_tab_name"],
            "source_range": settings.get("source_range"),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "target_sheet_id": settings.sheet_id,
            "target_tab_name": settings.tab_name,
            "source_record_count": len(source_records),
            "record_count": len(records),
            "wrote_sheet": not args.skip_sheet,
        }
    )


if __name__ == "__main__":
    main()
