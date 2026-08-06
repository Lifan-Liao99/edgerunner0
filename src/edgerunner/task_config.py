from __future__ import annotations

import argparse
from collections.abc import Callable
import copy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import tomllib
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_CONFIG_PATH = Path("config/tasks.toml")
DEFAULT_DATE_TIMEZONE = "America/New_York"
OVERRIDE_ENV_PREFIX = "EDGERUNNER_OVERRIDE_"
OVERRIDES_JSON_ENV = "EDGERUNNER_TASK_OVERRIDES"
OVERRIDE_INPUT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_DATE_OVERRIDES = {
    "startdate": {
        "path": "start_date_offset",
        "description": "Start date, YYYY-MM-DD. Converted to start_date_offset using New York time.",
    },
    "enddate": {
        "path": "end_date_offset",
        "description": "End date, YYYY-MM-DD. Converted to end_date_offset using New York time.",
    },
}


@dataclass(frozen=True)
class TaskSettings:
    params: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.params[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def with_runtime_options(self, *, skip_sheet: bool) -> TaskSettings:
        params = copy.deepcopy(self.params)
        params["skip_sheet"] = skip_sheet
        return TaskSettings(params=params)

    @property
    def name(self) -> str:
        return str(self.params["name"])

    @property
    def script_path(self) -> str:
        return str(self.params["script_path"])

    @property
    def cron_setting(self) -> str:
        return str(self.params.get("cron_setting", ""))

    @property
    def sheet_id(self) -> str:
        return str(self.params.get("sheet_id", ""))

    @property
    def tab_name(self) -> str:
        return str(self.params.get("tab_name", ""))

    @property
    def gcp_auth(self) -> bool:
        return bool(self.params.get("gcp_auth", True))

    @property
    def skip_sheet(self) -> bool:
        return bool(self.params.get("skip_sheet", False))

    @property
    def manual_overrides(self) -> list[dict[str, str]]:
        return add_reserved_manual_overrides(
            self.params,
            normalize_manual_overrides(self.params.get("manual_overrides", [])),
        )


def load_task_settings(task_name: str, config_path: Path = DEFAULT_CONFIG_PATH) -> TaskSettings:
    for task in load_all_task_settings(config_path).values():
        if task.name == task_name:
            return apply_manual_overrides(task)

    raise ValueError(f"Task '{task_name}' was not found in {config_path}")


def load_all_task_settings(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, TaskSettings]:
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    tasks: dict[str, TaskSettings] = {}
    for item in raw.get("tasks", []):
        task = TaskSettings(params=item)
        if task.name in tasks:
            raise ValueError(f"Duplicate task name: {task.name}")
        tasks[task.name] = task
    return tasks


def parse_task_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-name",
        help="Task name from config/tasks.toml. Also supports shorthand like --my_task.",
    )
    parser.add_argument("--skip-sheet", action="store_true")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "Override one configured manual_overrides input for this run. "
            "NAME can be the input name or config path."
        ),
    )
    args, unknown_args = parser.parse_known_args()
    shorthand_args = [arg for arg in unknown_args if arg.startswith("--")]

    if args.task_name and shorthand_args:
        parser.error("Use either --task-name TASK or shorthand --task_name, not both.")
    if len(shorthand_args) > 1:
        parser.error(f"Expected one task shorthand, got: {', '.join(shorthand_args)}")
    if not args.task_name and shorthand_args:
        args.task_name = shorthand_args[0][2:]
    if not args.task_name:
        parser.error("Missing task name. Use --task-name TASK or shorthand --task_name.")

    if args.override:
        try:
            parsed_overrides = _parse_cli_overrides(args.override)
        except ValueError as exc:
            parser.error(str(exc))
        os.environ[OVERRIDES_JSON_ENV] = json.dumps(parsed_overrides, ensure_ascii=True)

    return args


def run_task(task_func: Callable[[TaskSettings], Any]) -> Any:
    args = parse_task_args()
    settings = load_task_settings(args.task_name).with_runtime_options(skip_sheet=args.skip_sheet)
    result = task_func(settings)
    if result is not None:
        print(result)
    return result


def normalize_manual_overrides(raw_overrides: Any) -> list[dict[str, str]]:
    if raw_overrides is None:
        return []
    if not isinstance(raw_overrides, list):
        raise ValueError("manual_overrides must be a list")

    overrides: list[dict[str, str]] = []
    for raw_override in raw_overrides:
        if isinstance(raw_override, str):
            name = raw_override
            path = raw_override
            description = f"Override {path}"
        elif isinstance(raw_override, dict):
            path = str(raw_override.get("path", raw_override.get("name", ""))).strip()
            name = str(raw_override.get("name", path.replace(".", "_"))).strip()
            description = str(raw_override.get("description", f"Override {path}")).strip()
        else:
            raise ValueError("Each manual_overrides item must be a string or table")

        if name in RESERVED_DATE_OVERRIDES and path == name:
            path = RESERVED_DATE_OVERRIDES[name]["path"]
            if description == f"Override {name}":
                description = RESERVED_DATE_OVERRIDES[name]["description"]

        if not name:
            raise ValueError("Each manual_overrides item must have a non-empty name")
        if not path:
            raise ValueError(f"manual_overrides item '{name}' must have a non-empty path")
        if not _is_valid_override_name(name):
            raise ValueError(
                f"Invalid manual_overrides name '{name}'. Use letters, numbers, and underscores."
            )

        overrides.append(
            {
                "name": name,
                "path": path,
                "description": description,
                "env_var": override_env_var(name),
            }
        )

    return overrides


def add_reserved_manual_overrides(
    params: dict[str, Any],
    overrides: list[dict[str, str]],
) -> list[dict[str, str]]:
    overrides_by_name = {override["name"]: override for override in overrides}

    for name, reserved in RESERVED_DATE_OVERRIDES.items():
        path = reserved["path"]
        if name in overrides_by_name:
            if overrides_by_name[name]["path"] != path:
                raise ValueError(f"Reserved manual_overrides input '{name}' must target '{path}'")
            continue
        if path in params:
            overrides.append(
                {
                    "name": name,
                    "path": path,
                    "description": reserved["description"],
                    "env_var": override_env_var(name),
                }
            )

    return overrides


def apply_manual_overrides(task: TaskSettings) -> TaskSettings:
    specs = task.manual_overrides
    if not specs:
        return task

    requested_overrides = _collect_requested_overrides(specs)
    if not requested_overrides:
        return task

    updated_params = copy.deepcopy(task.params)
    for spec in specs:
        has_name_override = spec["name"] in requested_overrides
        value = requested_overrides.get(spec["name"], requested_overrides.get(spec["path"]))
        if value is None or value == "":
            continue
        if spec["name"] in RESERVED_DATE_OVERRIDES and has_name_override:
            _set_nested_value(updated_params, spec["path"], _date_to_offset(value))
            continue
        _set_nested_value(
            updated_params,
            spec["path"],
            _coerce_override_value(value, _get_nested_value(updated_params, spec["path"])),
        )

    return TaskSettings(params=updated_params)


def override_env_var(name: str) -> str:
    return f"{OVERRIDE_ENV_PREFIX}{name.upper()}"


def _collect_requested_overrides(specs: list[dict[str, str]]) -> dict[str, str]:
    overrides: dict[str, str] = {}

    raw_json = os.environ.get(OVERRIDES_JSON_ENV)
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{OVERRIDES_JSON_ENV} must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{OVERRIDES_JSON_ENV} must be a JSON object")
        overrides.update(
            {str(key): str(value) for key, value in parsed.items() if value is not None}
        )

    for spec in specs:
        env_value = os.environ.get(spec["env_var"])
        if env_value:
            overrides[spec["name"]] = env_value

    return overrides


def _parse_cli_overrides(raw_overrides: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_override in raw_overrides:
        if "=" not in raw_override:
            raise ValueError(f"Invalid override '{raw_override}'. Expected NAME=VALUE.")
        name, value = raw_override.split("=", 1)
        if not name.strip():
            raise ValueError(f"Invalid override '{raw_override}'. NAME cannot be empty.")
        parsed[name.strip()] = value
    return parsed


def _is_valid_override_name(name: str) -> bool:
    return bool(OVERRIDE_INPUT_NAME_PATTERN.fullmatch(name))


def _get_nested_value(params: dict[str, Any], path: str) -> Any:
    current: Any = params
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _set_nested_value(params: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    current = params
    for key in keys[:-1]:
        next_value = current.get(key)
        if next_value is None:
            next_value = {}
            current[key] = next_value
        if not isinstance(next_value, dict):
            raise ValueError(f"Cannot override '{path}' because '{key}' is not a table")
        current = next_value
    current[keys[-1]] = value


def _coerce_override_value(value: str, current_value: Any) -> Any:
    if current_value is None or isinstance(current_value, str):
        return value
    if isinstance(current_value, bool):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
        raise ValueError(f"Cannot parse boolean override value '{value}'")
    if isinstance(current_value, int) and not isinstance(current_value, bool):
        return int(value)
    if isinstance(current_value, float):
        return float(value)
    if isinstance(current_value, (list, dict)):
        return json.loads(value)
    return value


def business_today() -> date:
    return datetime.now(ZoneInfo(DEFAULT_DATE_TIMEZONE)).date()


def date_from_offset(days: int | str) -> str:
    return (business_today() + timedelta(days=int(days))).isoformat()


def _date_to_offset(value: str) -> int:
    try:
        target_date = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"Date override '{value}' must use YYYY-MM-DD format") from exc
    return (target_date - business_today()).days
