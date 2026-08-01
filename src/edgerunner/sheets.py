from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Any

import google.auth
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from googleapiclient.discovery import build


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Local runs authenticate with user ADC. A user refresh token only carries the
# scopes granted at login time, so the Sheets scope has to be requested there
# rather than here; cloud-platform is included so gcloud can attach a quota
# project. In GitHub Actions the auth step supplies credentials instead.
ADC_LOGIN_COMMAND = (
    f"gcloud auth application-default login --scopes={SHEETS_SCOPE},{CLOUD_PLATFORM_SCOPE}"
)


def write_records_to_sheet(
    *,
    spreadsheet_id: str,
    tab_name: str,
    records: list[dict[str, Any]],
    write_mode: str = "replace",
) -> None:
    service = _build_sheets_service()

    values = _records_to_values(records)
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
        return

    if not values:
        return

    if write_mode != "append":
        raise ValueError("write_mode must be either 'replace' or 'append'")

    existing_header = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{tab_name}!1:1",
    ).execute().get("values", [])
    rows_to_append = values if not existing_header else values[1:]
    if not rows_to_append:
        return

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=target_range,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows_to_append},
    ).execute()


def read_records_from_sheet(
    *,
    spreadsheet_id: str,
    tab_name: str,
    read_range: str | None = None,
) -> list[dict[str, Any]]:
    service = _build_sheets_service()
    range_name = read_range or tab_name
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute().get("values", [])
    return _values_to_records(values)


def _build_sheets_service():
    credentials = _load_credentials()
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _load_credentials():
    try:
        credentials, _ = google.auth.default(scopes=[SHEETS_SCOPE])
        return credentials
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Google Application Default Credentials were not found. For a local run, "
            f"sign in with `{ADC_LOGIN_COMMAND}` and finish the browser login, or pass "
            "--skip-sheet to skip the Sheets write. In GitHub Actions this means the "
            "'Authenticate to Google Cloud' step did not run."
        ) from exc
    except RefreshError as exc:
        raise RuntimeError(
            "Google credentials were found but could not be refreshed. Run "
            "`gcloud auth application-default revoke`, then sign in again with "
            f"`{ADC_LOGIN_COMMAND}`."
        ) from exc


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
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
