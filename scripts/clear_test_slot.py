"""Clear the manual test slot from config/tasks.toml and regenerate workflows."""

from __future__ import annotations

from pathlib import Path
import sys

import tomlkit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import TaskSettings  # noqa: E402
from scripts import generate_workflows  # noqa: E402


CONFIG_PATH = ROOT / "config" / "tasks.toml"


def selected_test_tasks(tasks: dict[str, TaskSettings]) -> list[TaskSettings]:
    """Return every task that currently claims the test slot."""
    try:
        selected = generate_workflows.select_test_task(tasks)
    except ValueError:
        # Auto-clear is allowed to repair the same ambiguity the generator and
        # guard reject. Clear every claim, then regenerate from the clean config.
        return [task for task in tasks.values() if task.is_test]
    return [selected] if selected is not None else []


def clear_config(config_path: Path, test_tasks: list[TaskSettings]) -> list[str]:
    """Set selected tasks' is_test fields to false while preserving TOML layout."""
    task_names = {task.name for task in test_tasks}
    if not task_names:
        return []

    text = config_path.read_text(encoding="utf-8")
    document = tomlkit.parse(text)
    cleared: list[str] = []

    for task_table in document.get("tasks", []):
        name = str(task_table.get("name", ""))
        if name in task_names and bool(task_table.get("is_test", False)):
            task_table["is_test"] = False
            cleared.append(name)

    if cleared:
        config_path.write_text(tomlkit.dumps(document), encoding="utf-8", newline="\n")

    return cleared


def clear_test_slot() -> bool:
    """Clear any occupied slot and regenerate workflows. Returns whether it changed files."""
    tasks = generate_workflows.load_tasks()
    test_tasks = selected_test_tasks(tasks)
    if not test_tasks:
        print("No task sets is_test = true in config/tasks.toml; nothing to clear.")
        return False

    cleared = clear_config(CONFIG_PATH, test_tasks)
    if not cleared:
        print("No matching is_test = true fields were found in config/tasks.toml.")
        return False

    print(f"Cleared test slot for: {', '.join(cleared)}")
    generate_workflows.write_workflows()
    return True


def main() -> int:
    try:
        clear_test_slot()
    except PermissionError as exc:
        print(f"Could not update the test slot files: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Could not update the test slot files: {exc}", file=sys.stderr)
        return 1

    # This script only edits the checkout. The workflow push step may still fail
    # if branch protection blocks workflow commits, or if a fork PR gives
    # GITHUB_TOKEN no write access; Test Slot Guard remains the fallback.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
