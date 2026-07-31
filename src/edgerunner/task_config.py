from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any


DEFAULT_CONFIG_PATH = Path("config/tasks.toml")


@dataclass(frozen=True)
class TaskSettings:
    params: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.params[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    @property
    def name(self) -> str:
        return str(self.params["name"])

    @property
    def script_path(self) -> str:
        return str(self.params["script_path"])

    @property
    def cron_setting(self) -> str:
        return str(self.params["cron_setting"])

    @property
    def sheet_id(self) -> str:
        return str(self.params["sheet_id"])

    @property
    def tab_name(self) -> str:
        return str(self.params["tab_name"])

    @property
    def gcp_auth(self) -> bool:
        return bool(self.params.get("gcp_auth", True))


def load_task_settings(task_name: str, config_path: Path = DEFAULT_CONFIG_PATH) -> TaskSettings:
    for task in load_all_task_settings(config_path).values():
        if task.name == task_name:
            return task

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


def parse_task_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--task-name",
        help="Task name from config/tasks.toml. Also supports shorthand like --my_task.",
    )
    parser.add_argument("--skip-sheet", action="store_true")
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

    return args
