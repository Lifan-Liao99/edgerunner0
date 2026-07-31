from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Any

import google.auth
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from googleapiclient.discovery import build

from edgerunner.env import resolve_env_reference


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def write_records_to_sheet(
    *,
    spreadsheet_id: str,
    tab_name: str,
    records: list[dict[str, Any]],
    write_mode: str = "replace",
) -> None:
    spreadsheet_id = resolve_env_reference(spreadsheet_id)
    try:
        credentials, _ = google.auth.default(scopes=[SHEETS_SCOPE])
    except DefaultCredentialsError as exc:
        raise RuntimeError(
            "Google Application Default Credentials were not found. Run "
            "`powershell -ExecutionPolicy Bypass -File .\\scripts\\setup_local_user_adc.ps1 "
            "-ProjectId YOUR_PROJECT_ID`, finish the browser login, then retry."
        ) from exc
    except RefreshError as exc:
        raise RuntimeError(
            "Google credentials were found but could not be refreshed. Run "
            "`gcloud auth application-default revoke`, then rerun "
            "`powershell -ExecutionPolicy Bypass -File .\\scripts\\setup_local_user_adc.ps1 "
            "-ProjectId YOUR_PROJECT_ID`."
        ) from exc

    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

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
