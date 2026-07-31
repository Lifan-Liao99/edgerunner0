from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


DEFAULT_CONFIG_PATH = Path("config/tasks.toml")


@dataclass(frozen=True)
class TaskSettings:
    name: str
    script_path: str
    cron_setting: str
    sheet_id: str
    tab_name: str
    gcp_auth: bool = True


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
        task = TaskSettings(**item)
        if task.name in tasks:
            raise ValueError(f"Duplicate task name: {task.name}")
        tasks[task.name] = task
    return tasks
