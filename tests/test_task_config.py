from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import (  # noqa: E402
    OVERRIDES_JSON_ENV,
    TaskSettings,
    load_all_task_settings,
    date_from_offset,
    load_task_settings,
    normalize_manual_overrides,
    override_env_var,
    parse_task_args,
    run_task,
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


class TaskConfigTests(LoggedTestCase):
    def write_config(self, content: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "tasks.toml"
        config_path.write_text(content, encoding="utf-8")
        return config_path

    def test_load_task_settings_reads_defaults_without_overrides(self) -> None:
        # Test: a task can be loaded from TOML with nested custom config.
        # Expected: values come through exactly as TOML defaults when no override is set.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "api_task"
            script_path = "tasks/api_task.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "output"
            gcp_auth = true
            api_query = { limit = 100 }
            start_date_offset = -5
            end_date_offset = -1
            """
        )

        with patch.dict(os.environ, {}, clear=True):
            settings = load_task_settings("api_task", config_path=config_path)

        self.assertEqual(settings.name, "api_task")
        self.assertEqual(settings["api_query"]["limit"], 100)
        self.assertEqual(settings["start_date_offset"], -5)
        self.assertEqual(settings["end_date_offset"], -1)

    def test_cron_setting_is_optional_for_manual_only_tasks(self) -> None:
        # Test: a task can omit cron_setting when it should only run manually.
        # Expected: settings.cron_setting returns an empty string instead of raising.
        settings = TaskSettings(
            {
                "name": "manual_only_task",
                "script_path": "tasks/manual_only_task.py",
                "sheet_id": "sheet123",
                "tab_name": "output",
            }
        )

        self.assertEqual(settings.cron_setting, "")

    def test_sheet_fields_are_optional_for_non_sheet_tasks(self) -> None:
        # Test: tasks that do not read or write Sheets do not need Sheet config.
        # Expected: convenience properties return empty strings instead of raising.
        settings = TaskSettings(
            {
                "name": "api_only_task",
                "script_path": "tasks/api_only_task.py",
            }
        )

        self.assertEqual(settings.sheet_id, "")
        self.assertEqual(settings.tab_name, "")

    def test_load_all_task_settings_rejects_duplicate_names(self) -> None:
        # Test: task names are unique identifiers in tasks.toml.
        # Expected: duplicate names raise a clear ValueError instead of overwriting silently.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "same_name"
            script_path = "tasks/one.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "one"

            [[tasks]]
            name = "same_name"
            script_path = "tasks/two.py"
            cron_setting = "0 13 * * *"
            sheet_id = "sheet123"
            tab_name = "two"
            """
        )

        with self.assertRaisesRegex(ValueError, "Duplicate task name"):
            load_all_task_settings(config_path)

    def test_load_task_settings_raises_for_missing_task(self) -> None:
        # Test: loading a task name that does not exist is an explicit error.
        # Expected: ValueError includes the missing task name.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "api_task"
            script_path = "tasks/api_task.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "output"
            """
        )

        with self.assertRaisesRegex(ValueError, "Task 'missing_task' was not found"):
            load_task_settings("missing_task", config_path=config_path)

    def test_manual_override_updates_nested_value_and_preserves_type(self) -> None:
        # Test: a configured manual override can target a nested TOML path.
        # Expected: api_query.limit is updated and coerced back to int.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "api_task"
            script_path = "tasks/api_task.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "output"
            api_query = { limit = 100 }
            manual_overrides = [
              { name = "limit", path = "api_query.limit", description = "Manual limit" },
            ]
            """
        )

        with patch.dict(os.environ, {"EDGERUNNER_OVERRIDE_LIMIT": "250"}, clear=True):
            settings = load_task_settings("api_task", config_path=config_path)

        self.assertEqual(settings["api_query"]["limit"], 250)
        self.assertIsInstance(settings["api_query"]["limit"], int)

    def test_manual_override_coerces_common_toml_types(self) -> None:
        # Test: override strings from GitHub inputs/env are converted to the current TOML type.
        # Expected: bool, float, list, and table values keep useful Python types.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "typed_task"
            script_path = "tasks/typed_task.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "output"
            enabled = false
            rate = 1.5
            labels = ["default"]
            metadata = { region = "us" }
            manual_overrides = [
              "enabled",
              "rate",
              "labels",
              "metadata",
            ]
            """
        )

        with patch.dict(
            os.environ,
            {
                "EDGERUNNER_OVERRIDE_ENABLED": "true",
                "EDGERUNNER_OVERRIDE_RATE": "2.75",
                "EDGERUNNER_OVERRIDE_LABELS": '["daily", "manual"]',
                "EDGERUNNER_OVERRIDE_METADATA": '{"region": "eu"}',
            },
            clear=True,
        ):
            settings = load_task_settings("typed_task", config_path=config_path)

        self.assertIs(settings["enabled"], True)
        self.assertEqual(settings["rate"], 2.75)
        self.assertEqual(settings["labels"], ["daily", "manual"])
        self.assertEqual(settings["metadata"], {"region": "eu"})

    def test_unconfigured_override_is_ignored(self) -> None:
        # Test: env vars cannot override arbitrary settings unless TOML allows them.
        # Expected: EDGERUNNER_OVERRIDE_LIMIT is ignored because manual_overrides is absent.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "api_task"
            script_path = "tasks/api_task.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "output"
            api_query = { limit = 100 }
            """
        )

        with patch.dict(os.environ, {"EDGERUNNER_OVERRIDE_LIMIT": "250"}, clear=True):
            settings = load_task_settings("api_task", config_path=config_path)

        self.assertEqual(settings["api_query"]["limit"], 100)

    def test_manual_overrides_auto_include_date_inputs_when_offsets_exist(self) -> None:
        # Test: start/end date offsets are reserved config fields.
        # Expected: tasks with offsets automatically expose startdate/enddate manual inputs.
        settings = TaskSettings(
            {
                "name": "date_task",
                "script_path": "tasks/date_task.py",
                "cron_setting": "0 12 * * *",
                "sheet_id": "sheet123",
                "tab_name": "output",
                "start_date_offset": -30,
                "end_date_offset": -1,
            }
        )

        override_names = [override["name"] for override in settings.manual_overrides]

        self.assertEqual(override_names, ["startdate", "enddate"])

    def test_reserved_date_overrides_convert_dates_to_offsets(self) -> None:
        # Test: startdate/enddate are reserved manual inputs for date offsets.
        # Expected: YYYY-MM-DD inputs are converted into integer offsets from New York today.
        config_path = self.write_config(
            """
            [[tasks]]
            name = "date_task"
            script_path = "tasks/date_task.py"
            cron_setting = "0 12 * * *"
            sheet_id = "sheet123"
            tab_name = "output"
            start_date_offset = -5
            end_date_offset = -1
            """
        )

        with (
            patch("edgerunner.task_config.business_today", return_value=date(2026, 8, 1)),
            patch.dict(
                os.environ,
                {
                    "EDGERUNNER_OVERRIDE_STARTDATE": "2026-07-20",
                    "EDGERUNNER_OVERRIDE_ENDDATE": "2026-07-31",
                },
                clear=True,
            ),
        ):
            settings = load_task_settings("date_task", config_path=config_path)

        self.assertEqual(settings["start_date_offset"], -12)
        self.assertEqual(settings["end_date_offset"], -1)

    def test_normalize_manual_overrides_accepts_reserved_date_names(self) -> None:
        # Test: users may explicitly list startdate/enddate in manual_overrides.
        # Expected: reserved names are mapped to start_date_offset/end_date_offset paths.
        overrides = normalize_manual_overrides(["startdate", "enddate"])

        self.assertEqual(overrides[0]["name"], "startdate")
        self.assertEqual(overrides[0]["path"], "start_date_offset")
        self.assertEqual(overrides[1]["name"], "enddate")
        self.assertEqual(overrides[1]["path"], "end_date_offset")

    def test_normalize_manual_overrides_rejects_invalid_input_names(self) -> None:
        # Test: GitHub input names must be valid identifier-like strings.
        # Expected: names with spaces are rejected before workflows are generated.
        with self.assertRaisesRegex(ValueError, "Invalid manual_overrides name"):
            normalize_manual_overrides([{"name": "bad name", "path": "api_query.limit"}])

    def test_override_env_var_uses_framework_prefix(self) -> None:
        # Test: workflow generation and task loading share one env var naming helper.
        # Expected: override names become EDGERUNNER_OVERRIDE_* env vars.
        self.assertEqual(override_env_var("startdate"), "EDGERUNNER_OVERRIDE_STARTDATE")

    def test_parse_task_args_stores_cli_overrides_as_json_env(self) -> None:
        # Test: local --override arguments are captured by the shared CLI parser.
        # Expected: overrides are stored as JSON for load_task_settings to consume.
        with (
            patch.object(
                sys,
                "argv",
                ["task.py", "--task-name", "api_task", "--override", "limit=250"],
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            args = parse_task_args()

            self.assertEqual(args.task_name, "api_task")
            self.assertEqual(json.loads(os.environ[OVERRIDES_JSON_ENV]), {"limit": "250"})

    def test_parse_task_args_accepts_task_name_shorthand(self) -> None:
        # Test: local task runs support the short --task_name style.
        # Expected: --api_task is normalized into args.task_name == "api_task".
        with (
            patch.object(sys, "argv", ["task.py", "--api_task"]),
            patch.dict(os.environ, {}, clear=True),
        ):
            args = parse_task_args()

        self.assertEqual(args.task_name, "api_task")

    def test_date_from_offset_uses_business_today(self) -> None:
        # Test: scripts can convert integer offsets into date strings through the framework.
        # Expected: offset math is relative to the framework business_today value.
        with patch("edgerunner.task_config.business_today", return_value=date(2026, 8, 1)):
            self.assertEqual(date_from_offset(-5), "2026-07-27")
            self.assertEqual(date_from_offset("-1"), "2026-07-31")

    def test_run_task_passes_settings_into_task_function(self) -> None:
        # Test: run_task is the shared main wrapper for task scripts.
        # Expected: it loads settings, attaches skip_sheet, calls the task, prints its result.
        captured_settings: list[TaskSettings] = []

        def task(settings: TaskSettings) -> dict[str, object]:
            captured_settings.append(settings)
            return {"task": settings.name, "skip_sheet": settings.skip_sheet}

        with (
            patch.object(sys, "argv", ["task.py", "--task-name", "api_task", "--skip-sheet"]),
            patch(
                "edgerunner.task_config.load_task_settings",
                return_value=TaskSettings(
                    {
                        "name": "api_task",
                        "script_path": "tasks/api_task.py",
                        "cron_setting": "0 12 * * *",
                        "sheet_id": "sheet123",
                        "tab_name": "output",
                    }
                ),
            ),
            patch("builtins.print") as print_mock,
        ):
            result = run_task(task)

        self.assertEqual(result, {"task": "api_task", "skip_sheet": True})
        self.assertTrue(captured_settings[0].skip_sheet)
        print_mock.assert_called_once_with({"task": "api_task", "skip_sheet": True})


if __name__ == "__main__":
    unittest.main()
