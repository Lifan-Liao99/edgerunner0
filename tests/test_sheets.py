from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.sheets import _contiguous_ranges, _upsert_values  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
