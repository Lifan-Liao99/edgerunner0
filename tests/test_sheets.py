from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.sheets import (  # noqa: E402
    _build_sheets_service,
    _contiguous_ranges,
    _upsert_values,
    read_records_from_sheet,
    write_records_to_sheet,
)


class LoggedTestCase(unittest.TestCase):
    RESULT_FIELDS = (
        ("failures", "FAIL"),
        ("errors", "ERROR"),
        ("skipped", "SKIP"),
        ("expectedFailures", "EXPECTED_FAIL"),
        ("unexpectedSuccesses", "UNEXPECTED_SUCCESS"),
    )

    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult | None:
        test_name = f"{self.__class__.__name__}.{self._testMethodName}"
        if result is None:
            return super().run(result)

        before_counts = {
            field_name: len(getattr(result, field_name, []))
            for field_name, _status in self.RESULT_FIELDS
        }
        print(f"[RUN] {test_name}", flush=True)

        finished_result = super().run(result)

        status = "PASS"
        for field_name, field_status in self.RESULT_FIELDS:
            if len(getattr(result, field_name, [])) > before_counts[field_name]:
                status = field_status
                break
        print(f"[{status}] {test_name}", flush=True)
        return finished_result


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeValuesResource:
    def __init__(self, service: FakeSheetsService):
        self.service = service

    def get(self, *, spreadsheetId: str, range: str):
        if range == self.service.tab_name:
            return FakeRequest({"values": self.service.existing_values})
        if range == f"{self.service.tab_name}!1:1":
            return FakeRequest({"values": self.service.existing_values[:1]})
        raise AssertionError(f"Unexpected get range: {range}")

    def clear(self, **kwargs):
        self.service.cleared_range = kwargs["range"]
        return FakeRequest({})

    def update(self, **kwargs):
        self.service.updated_values = kwargs["body"]["values"]
        return FakeRequest({})

    def append(self, **kwargs):
        self.service.appended_values = kwargs["body"]["values"]
        return FakeRequest({})


class FakeSpreadsheetsResource:
    def __init__(self, service: FakeSheetsService):
        self.service = service

    def values(self):
        return FakeValuesResource(self.service)

    def get(self, **kwargs):
        return FakeRequest(
            {"sheets": [{"properties": {"title": self.service.tab_name, "sheetId": 123}}]}
        )

    def batchUpdate(self, **kwargs):
        self.service.batch_update_body = kwargs["body"]
        return FakeRequest({})


class FakeSheetsService:
    def __init__(self, *, tab_name: str, existing_values: list[list[str]]):
        self.tab_name = tab_name
        self.existing_values = existing_values
        self.updated_values: list[list[str]] | None = None
        self.appended_values: list[list[str]] | None = None
        self.batch_update_body: dict | None = None
        self.cleared_range: str | None = None

    def spreadsheets(self):
        return FakeSpreadsheetsResource(self)


class SheetsTests(LoggedTestCase):
    def test_contiguous_ranges_groups_descending_row_numbers(self) -> None:
        # Test: row deletes should be grouped, because Sheets deleteDimension uses ranges.
        # Expected: adjacent rows become one range and non-adjacent rows stay separate.
        self.assertEqual(_contiguous_ranges([8, 7, 6, 3]), [(6, 8), (3, 3)])

    def test_upsert_deletes_existing_rows_with_matching_key_then_appends_new_rows(self) -> None:
        # Test: upsert replaces target rows whose key/date exists in the incoming data.
        # Expected: matching target rows are deleted first, then incoming rows append without headers.
        service = FakeSheetsService(
            tab_name="target",
            existing_values=[
                ["date", "value"],
                ["2026-07-30", "old_a"],
                ["2026-07-31", "old_b"],
                ["2026-08-01", "old_c"],
                ["2026-08-02", "old_d"],
            ],
        )

        _upsert_values(
            service=service,
            spreadsheet_id="spreadsheet123",
            tab_name="target",
            values=[
                ["date", "value"],
                ["2026-07-31", "new_b"],
                ["2026-08-01", "new_c"],
            ],
            upsert_key_columns=["date"],
        )

        self.assertEqual(
            service.batch_update_body,
            {
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": 123,
                                "dimension": "ROWS",
                                "startIndex": 2,
                                "endIndex": 4,
                            }
                        }
                    }
                ]
            },
        )
        self.assertEqual(
            service.appended_values,
            [["2026-07-31", "new_b"], ["2026-08-01", "new_c"]],
        )

    def test_upsert_supports_composite_key_columns(self) -> None:
        # Test: upsert can match rows by multiple columns, not only one date column.
        # Expected: only rows with the same full date + store_id key are replaced.
        service = FakeSheetsService(
            tab_name="target",
            existing_values=[
                ["date", "store_id", "sales"],
                ["2026-07-31", "store_a", "old_a"],
                ["2026-07-31", "store_b", "old_b"],
                ["2026-08-01", "store_a", "old_c"],
            ],
        )

        _upsert_values(
            service=service,
            spreadsheet_id="spreadsheet123",
            tab_name="target",
            values=[
                ["date", "store_id", "sales"],
                ["2026-07-31", "store_b", "new_b"],
                ["2026-08-01", "store_a", "new_c"],
            ],
            upsert_key_columns=["date", "store_id"],
        )

        self.assertEqual(
            service.batch_update_body,
            {
                "requests": [
                    {
                        "deleteDimension": {
                            "range": {
                                "sheetId": 123,
                                "dimension": "ROWS",
                                "startIndex": 2,
                                "endIndex": 4,
                            }
                        }
                    }
                ]
            },
        )
        self.assertEqual(
            service.appended_values,
            [["2026-07-31", "store_b", "new_b"], ["2026-08-01", "store_a", "new_c"]],
        )

    def test_upsert_requires_key_column_name(self) -> None:
        # Test: upsert needs to know which column identifies rows to replace.
        # Expected: missing upsert_key_columns raises a clear error.
        service = FakeSheetsService(tab_name="target", existing_values=[])

        with self.assertRaisesRegex(ValueError, "upsert_key_columns is required"):
            _upsert_values(
                service=service,
                spreadsheet_id="spreadsheet123",
                tab_name="target",
                values=[["date"], ["2026-08-01"]],
                upsert_key_columns=None,
            )


class SkipSheetTests(LoggedTestCase):
    # These run with GITHUB_ACTIONS unset, the same as a developer's machine. If
    # skip_sheet ever stopped short-circuiting, _build_sheets_service would raise
    # and the test would fail, which is the guarantee worth locking down.

    def test_write_with_skip_sheet_makes_no_api_call(self) -> None:
        # Test: skip_sheet must short-circuit before the Sheets client is built.
        # Expected: no call reaches the API layer.
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("edgerunner.sheets._build_sheets_service") as service_mock,
        ):
            write_records_to_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="target",
                records=[{"date": "2026-08-01", "store": "store_a"}],
                skip_sheet=True,
            )

        service_mock.assert_not_called()

    def test_write_with_skip_sheet_returns_the_rows_it_would_have_written(self) -> None:
        # Test: the point of the skip path is still getting the transformed rows.
        # Expected: header row plus one data row, in column order.
        with patch.dict(os.environ, {}, clear=True):
            rows = write_records_to_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="target",
                records=[
                    {"date": "2026-08-01", "store": "store_a"},
                    {"date": "2026-08-02", "store": "store_b"},
                ],
                skip_sheet=True,
            )

        self.assertEqual(
            rows,
            [
                ["date", "store"],
                ["2026-08-01", "store_a"],
                ["2026-08-02", "store_b"],
            ],
        )

    def test_write_returns_the_same_rows_on_the_real_path(self) -> None:
        # Test: callers should get one shape of return value either way, so the
        # skip path is not a special case downstream.
        # Expected: the returned rows match what was sent to the API.
        service = FakeSheetsService(tab_name="target", existing_values=[])

        with (
            patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True),
            patch("edgerunner.sheets._build_sheets_service", return_value=service),
        ):
            rows = write_records_to_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="target",
                records=[{"date": "2026-08-01", "store": "store_a"}],
            )

        self.assertEqual(rows, [["date", "store"], ["2026-08-01", "store_a"]])
        self.assertEqual(rows, service.updated_values)

    def test_write_validates_write_mode_even_when_skipping(self) -> None:
        # Test: a typo in sheet_write_mode should surface during a local run, not
        # only once the task reaches GitHub Actions.
        # Expected: the skip path still rejects it.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "write_mode must be one of"):
                write_records_to_sheet(
                    spreadsheet_id="spreadsheet123",
                    tab_name="target",
                    records=[{"date": "2026-08-01"}],
                    write_mode="replce",
                    skip_sheet=True,
                )

    def test_write_validates_upsert_key_columns_even_when_skipping(self) -> None:
        # Test: same reasoning for a missing upsert key.
        # Expected: the skip path still rejects it.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "upsert_key_columns is required"):
                write_records_to_sheet(
                    spreadsheet_id="spreadsheet123",
                    tab_name="target",
                    records=[{"date": "2026-08-01"}],
                    write_mode="upsert",
                    skip_sheet=True,
                )

    def test_read_with_skip_sheet_makes_no_api_call(self) -> None:
        # Test: the read side has to short-circuit too.
        # Expected: no call reaches the API layer.
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("edgerunner.sheets._build_sheets_service") as service_mock,
        ):
            read_records_from_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="source",
                skip_sheet=True,
            )

        service_mock.assert_not_called()

    def test_read_with_skip_sheet_returns_the_mock_response(self) -> None:
        # Test: a fixture lets local runs exercise downstream transforms.
        # Expected: the fixture rows come back unchanged.
        fixture = [{"date": "2026-08-01", "store": "store_a"}]

        with patch.dict(os.environ, {}, clear=True):
            records = read_records_from_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="source",
                skip_sheet=True,
                mock_response=fixture,
            )

        self.assertEqual(records, fixture)

    def test_read_with_skip_sheet_and_no_mock_returns_empty(self) -> None:
        # Test: mock_response is optional.
        # Expected: an empty list, not None, so callers can iterate either way.
        with patch.dict(os.environ, {}, clear=True):
            records = read_records_from_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="source",
                skip_sheet=True,
            )

        self.assertEqual(records, [])

    def test_read_does_not_hand_back_the_caller_fixture_object(self) -> None:
        # Test: a module-level fixture reused across runs must not be mutable
        # through the returned list, or one task could corrupt the next.
        # Expected: mutating the result leaves the fixture intact.
        fixture = [{"date": "2026-08-01"}]

        with patch.dict(os.environ, {}, clear=True):
            records = read_records_from_sheet(
                spreadsheet_id="spreadsheet123",
                tab_name="source",
                skip_sheet=True,
                mock_response=fixture,
            )
        records.append({"date": "2026-08-02"})

        self.assertEqual(len(fixture), 1)


class BackwardCompatibilityTests(LoggedTestCase):
    def test_write_without_skip_sheet_still_hits_the_actions_gate(self) -> None:
        # Test: skip_sheet defaults to False, so untouched call sites behave
        # exactly as they did before this parameter existed.
        # Expected: a local run still fails at the gate.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "only available in GitHub Actions"):
                write_records_to_sheet(
                    spreadsheet_id="spreadsheet123",
                    tab_name="target",
                    records=[{"date": "2026-08-01"}],
                )

    def test_read_without_skip_sheet_still_hits_the_actions_gate(self) -> None:
        # Test: same default for the read side.
        # Expected: a local run still fails at the gate.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "only available in GitHub Actions"):
                read_records_from_sheet(spreadsheet_id="spreadsheet123", tab_name="source")


class SheetsAuthGateTests(LoggedTestCase):
    def test_building_the_service_outside_github_actions_raises(self) -> None:
        # Test: Sheets access is GitHub Actions only.
        # Expected: a local run is told to use --skip-sheet before any API call.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "only available in GitHub Actions"):
                _build_sheets_service()

    def test_a_non_actions_value_does_not_open_the_gate(self) -> None:
        # Test: the gate checks for the exact value GitHub Actions sets.
        # Expected: GITHUB_ACTIONS set to anything else still refuses.
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "only available in GitHub Actions"):
                _build_sheets_service()

    def test_inside_github_actions_the_gate_defers_to_credentials(self) -> None:
        # Test: in Actions the gate passes and normal credential loading happens.
        # Expected: _load_credentials is reached and its result reaches build().
        with (
            patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=True),
            patch("edgerunner.sheets._load_credentials", return_value="fake-credentials"),
            patch("edgerunner.sheets.build", return_value="fake-service") as build_mock,
        ):
            self.assertEqual(_build_sheets_service(), "fake-service")

        build_mock.assert_called_once_with(
            "sheets",
            "v4",
            credentials="fake-credentials",
            cache_discovery=False,
        )


if __name__ == "__main__":
    unittest.main()
