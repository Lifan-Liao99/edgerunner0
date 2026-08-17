"""Fail when the manual test slot is still loaded with a task.

The slot exists so a new task can be dispatched from a testing branch before it
merges. Once it merges, leaving is_test = true would keep a second dispatchable
copy of that task on the default branch forever, drifting from the task's own
generated workflow. This check gates pull requests into main so the slot goes
back to empty as part of review.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import TaskSettings  # noqa: E402
from scripts.generate_workflows import (  # noqa: E402
    TEST_WORKFLOW_STEM,
    WORKFLOW_DIR,
    empty_test_workflow_yaml,
    load_tasks,
    select_test_task,
)

SLOT_RELATIVE_PATH = f".github/workflows/{TEST_WORKFLOW_STEM}.yml"
FIX_HINT = (
    "Fix: set is_test = false in config/tasks.toml (or delete the line), then run\n"
    "  python scripts/generate_workflows.py\n"
    "and commit both the config and the regenerated workflow."
)


def slot_problems(tasks: dict[str, TaskSettings], slot_text: str | None) -> list[str]:
    """Describe every reason the test slot is not clear. Empty list means clear."""
    problems: list[str] = []

    try:
        test_task = select_test_task(tasks)
    except ValueError as exc:
        # More than one task claims the slot. Report it here too, so a pull
        # request fails with this message instead of only breaking generation.
        problems.append(str(exc))
    else:
        if test_task is not None:
            problems.append(
                f"Task '{test_task.name}' still sets is_test = true in config/tasks.toml."
            )

    if slot_text is None:
        problems.append(
            f"{SLOT_RELATIVE_PATH} is missing. It has to stay on the default branch, "
            "otherwise no future branch can dispatch it."
        )
    elif slot_text != empty_test_workflow_yaml().rstrip() + "\n":
        problems.append(
            f"{SLOT_RELATIVE_PATH} still holds a task's steps. Regenerate it so the "
            "slot is empty on main."
        )

    return problems


def main() -> int:
    try:
        tasks = load_tasks()
    except ValueError as exc:
        print(f"config/tasks.toml is invalid: {exc}", file=sys.stderr)
        return 1

    slot_path = WORKFLOW_DIR / f"{TEST_WORKFLOW_STEM}.yml"
    slot_text = slot_path.read_text(encoding="utf-8") if slot_path.is_file() else None

    problems = slot_problems(tasks, slot_text)
    if not problems:
        print("Test slot is clear: no task sets is_test = true.")
        return 0

    print("The manual test slot must be empty before merging to main.", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(f"\n{FIX_HINT}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
