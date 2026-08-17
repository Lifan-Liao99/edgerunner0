from __future__ import annotations

from collections.abc import Iterable
from math import isfinite
import json
import os
from typing import Any

import google.auth
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from googleapiclient.discovery import build


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
WRITE_MODES = ("replace", "append", "upsert")

# Sheets access is GitHub Actions only. The workflow's 'Authenticate to Google
# Cloud' step mints a short-lived service account token through Workload
# Identity Federation, so no key material exists anywhere and the Sheets scope
# is applied per token mint. Local runs deliberately have no path to a Sheet:
# use --skip-sheet to exercise fetch and transform logic instead.
SHEETS_REQUIRES_ACTIONS_MESSAGE = (
    "Google Sheets access is only available in GitHub Actions, but this call "
    "reached the Sheets API from a local run. Two things cause that:\n"
    "  1. The run did not pass --skip-sheet on the command line.\n"
    "  2. The task script did pass --skip-sheet, but does not forward it to the "
    "helper. Every read_records_from_sheet and write_records_to_sheet call needs "
    "skip_sheet=settings.skip_sheet.\n"
    "Check the second one before re-checking your command line: the flag only "
    "reaches the API layer if the script wires it through. To read or write a "
    "real Sheet, push your branch and run the workflow instead."
)


def write_records_to_sheet(
    *,
    spreadsheet_id: str,
    tab_name: str,
    records: list[dict[str, Any]] | Any,
    write_mode: str = "replace",
    upsert_key_columns: list[str] | tuple[str, ...] | None = None,
    skip_sheet: bool = False,
) -> list[list[Any]]:
    """Write records to a Sheet tab and return the rows that were written.

    Pass `skip_sheet=settings.skip_sheet` rather than guarding the call site.
    With `skip_sheet=True` no API call happens, but the rows that would have been
    written are still built and returned, so a local run exercises the same
    transform and can log or assert on the result.
    """
    # Validated before the skip check so a bad write_mode or a missing upsert key
    # is caught during a local --skip-sheet run rather than only in CI.
    if write_mode not in WRITE_MODES:
        raise ValueError("write_mode must be one of 'replace', 'append', or 'upsert'")
    if write_mode == "upsert":
        _normalize_upsert_key_columns(upsert_key_columns)

    values = _tabular_data_to_values(records)
    if skip_sheet:
        return values

    service = _build_sheets_service()
    target_range = f"{tab_name}!A1"

    if write_mode == "replace":
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=tab_name,
            body={},
        ).execute()
        if values:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=target_range,
                valueInputOption="RAW",
                body={"values": values},
            ).execute()
    elif write_mode == "append":
        _append_values(
            service=service,
            spreadsheet_id=spreadsheet_id,
            tab_name=tab_name,
            values=values,
        )
    else:
        _upsert_values(
            service=service,
            spreadsheet_id=spreadsheet_id,
            tab_name=tab_name,
            values=values,
            upsert_key_columns=upsert_key_columns,
        )

    return values


def _append_values(
    *,
    service: Any,
    spreadsheet_id: str,
    tab_name: str,
    values: list[list[Any]],
) -> None:
    if not values:
        return

    existing_header = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{tab_name}!1:1",
    ).execute().get("values", [])
    rows_to_append = values if not existing_header else values[1:]
    if not rows_to_append:
        return

    target_range = f"{tab_name}!A1"
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=target_range,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows_to_append},
    ).execute()


def _upsert_values(
    *,
    service: Any,
    spreadsheet_id: str,
    tab_name: str,
    values: list[list[Any]],
    upsert_key_columns: list[str] | tuple[str, ...] | None = None,
) -> None:
    key_columns = _normalize_upsert_key_columns(upsert_key_columns)
    if not values:
        return

    incoming_header = [str(header).strip() for header in values[0]]
    incoming_key_indexes = [_column_index(incoming_header, column) for column in key_columns]
    incoming_keys = {
        key for row in values[1:] if (key := _row_key(row, incoming_key_indexes)) is not None
    }
    if not incoming_keys:
        return

    existing_values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=tab_name,
    ).execute().get("values", [])

    if not existing_values:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab_name}!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        return

    existing_header = [str(header).strip() for header in existing_values[0]]
    existing_key_indexes = [_column_index(existing_header, column) for column in key_columns]
    row_numbers_to_delete = [
        row_number
        for row_number, row in enumerate(existing_values[1:], start=2)
        if (key := _row_key(row, existing_key_indexes)) is not None and key in incoming_keys
    ]
    if row_numbers_to_delete:
        _delete_sheet_rows(
            service=service,
            spreadsheet_id=spreadsheet_id,
            tab_name=tab_name,
            row_numbers=row_numbers_to_delete,
        )

    rows_to_append = values[1:]
    if not rows_to_append:
        return

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows_to_append},
    ).execute()


def _delete_sheet_rows(
    *,
    service: Any,
    spreadsheet_id: str,
    tab_name: str,
    row_numbers: list[int],
) -> None:
    sheet_id = _sheet_id_for_tab(service, spreadsheet_id, tab_name)
    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": start_row - 1,
                    "endIndex": end_row,
                }
            }
        }
        for start_row, end_row in _contiguous_ranges(sorted(row_numbers, reverse=True))
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def _sheet_id_for_tab(service: Any, spreadsheet_id: str, tab_name: str) -> int:
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title))",
    ).execute()
    for sheet in spreadsheet.get("sheets", []):
        properties = sheet.get("properties", {})
        if properties.get("title") == tab_name:
            return int(properties["sheetId"])
    raise ValueError(f"Tab '{tab_name}' was not found in spreadsheet {spreadsheet_id}")


def _contiguous_ranges(descending_row_numbers: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    if not descending_row_numbers:
        return ranges

    start = descending_row_numbers[0]
    end = descending_row_numbers[0]
    for row_number in descending_row_numbers[1:]:
        if row_number == end - 1:
            end = row_number
            continue
        ranges.append((end, start))
        start = row_number
        end = row_number
    ranges.append((end, start))
    return ranges


def _column_index(headers: list[str], column_name: str) -> int:
    normalized_column_name = column_name.strip()
    for index, header in enumerate(headers):
        if header == normalized_column_name:
            return index
    raise ValueError(f"Column '{column_name}' was not found in sheet headers: {headers}")


def _normalize_upsert_key_columns(
    upsert_key_columns: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if not upsert_key_columns:
        raise ValueError("upsert_key_columns is required when write_mode is 'upsert'")

    raw_columns = [str(column).strip() for column in upsert_key_columns]
    columns = [column for column in raw_columns if column]
    if not columns:
        raise ValueError("upsert key columns cannot be empty")
    if len(columns) != len(set(columns)):
        raise ValueError(f"upsert key columns cannot contain duplicates: {columns}")
    return columns


def _row_key(row: list[Any], key_indexes: list[int]) -> tuple[str, ...] | None:
    key = tuple(_key_value(row[index]) if index < len(row) else "" for index in key_indexes)
    return key if all(key) else None


def _key_value(value: Any) -> str:
    return str(value).strip()


def read_records_from_sheet(
    *,
    spreadsheet_id: str,
    tab_name: str,
    read_range: str | None = None,
    skip_sheet: bool = False,
    mock_response: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read records from a Sheet tab.

    Pass `skip_sheet=settings.skip_sheet` rather than guarding the call site.
    With `skip_sheet=True` no API call happens and `mock_response` is returned
    instead, so downstream transforms still run locally against realistically
    shaped rows. Without a `mock_response` the result is an empty list.
    """
    if skip_sheet:
        # Copied so a module-level fixture cannot be mutated by the caller and
        # silently change what later runs see.
        return list(mock_response) if mock_response is not None else []

    service = _build_sheets_service()
    range_name = read_range or tab_name
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute().get("values", [])
    return _values_to_records(values)


def _build_sheets_service():
    _require_github_actions()
    credentials = _load_credentials()
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _require_github_actions() -> None:
    # Fail before the API call so a local run gets this message rather than a
    # 403 from Sheets about the user account behind whatever ADC happens to
    # exist on the machine.
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(SHEETS_REQUIRES_ACTIONS_MESSAGE)


def _load_credentials():
    try:
        credentials, _ = google.auth.default(scopes=[SHEETS_SCOPE])
        return credentials
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Google Application Default Credentials were not found. The workflow's "
            "'Authenticate to Google Cloud' step did not run or did not complete, so "
            "no service account credentials are available."
        ) from exc
    except RefreshError as exc:
        raise RuntimeError(
            "Google service account credentials were found but could not be refreshed. "
            "Check that the GCP_WORKLOAD_IDENTITY_PROVIDER and GCP_SERVICE_ACCOUNT "
            "secrets are correct and that the Workload Identity pool still trusts this "
            "repository."
        ) from exc


def _tabular_data_to_values(data: list[dict[str, Any]] | Any) -> list[list[Any]]:
    if _is_pandas_dataframe(data):
        return _dataframe_to_values(data)
    return _records_to_values(data)


def _is_pandas_dataframe(value: Any) -> bool:
    return hasattr(value, "columns") and hasattr(value, "itertuples") and hasattr(value, "empty")


def _dataframe_to_values(dataframe: Any) -> list[list[Any]]:
    headers = [str(column) for column in dataframe.columns]
    if dataframe.empty:
        return [headers] if headers else []

    rows = [
        [_cell_value(value) for value in row]
        for row in dataframe.itertuples(index=False, name=None)
    ]
    return [headers, *rows]


def _records_to_values(records: list[dict[str, Any]]) -> list[list[Any]]:
    if not records:
        return []

    flattened = [_flatten_record(record) for record in records]
    headers = _headers(flattened)
    rows = [[_cell_value(record.get(header)) for header in headers] for record in flattened]
    return [headers, *rows]


def _headers(records: Iterable[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for record in records:
        for key in record:
            seen.setdefault(key, None)
    return list(seen)


def _flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in record.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_record(value, full_key))
        else:
            flattened[full_key] = value
    return flattened


def _cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if _is_missing_value(value):
        return ""
    if _is_numpy_scalar(value):
        return _cell_value(value.item())
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _is_missing_value(value: Any) -> bool:
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return True
    if isinstance(value, float) and not isfinite(value):
        return True
    try:
        return bool(value is not value or value != value)
    except (TypeError, ValueError):
        return False


def _is_numpy_scalar(value: Any) -> bool:
    if not hasattr(value, "item") or isinstance(value, (str, bytes)):
        return False
    try:
        return value.item() is not value
    except (AttributeError, TypeError, ValueError):
        return False


def _values_to_records(values: list[list[Any]]) -> list[dict[str, Any]]:
    if not values:
        return []

    headers = _normalize_headers(values[0])
    records: list[dict[str, Any]] = []
    for row in values[1:]:
        record = {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(headers)
        }
        if any(value != "" for value in record.values()):
            records.append(record)
    return records


def _normalize_headers(header_row: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, raw_header in enumerate(header_row, start=1):
        header = str(raw_header).strip() or f"column_{index}"
        count = seen.get(header, 0)
        seen[header] = count + 1
        headers.append(header if count == 0 else f"{header}_{count + 1}")
    return headers
