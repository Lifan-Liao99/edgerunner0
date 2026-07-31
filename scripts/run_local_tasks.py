from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import load_all_task_settings  # noqa: E402


def load_tasks():
    return list(load_all_task_settings(ROOT / "config" / "tasks.toml").values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local task scripts.")
    parser.add_argument("--local-test", action="store_true", help="Run only local_test tasks.")
    parser.add_argument("--write-sheet", action="store_true", help="Allow tasks to write Sheets.")
    args = parser.parse_args()

    tasks = load_tasks()
    if args.local_test:
        tasks = [task for task in tasks if task.local_test]

    for task in tasks:
        command = [sys.executable, task.script_path]
        if not args.write_sheet:
            command.append("--skip-sheet")
        if args.local_test:
            command.append("--use-sample-on-failure")

        print(f"Running {task.name}: {' '.join(command)}")
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
