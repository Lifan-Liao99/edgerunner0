from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import TaskSettings  # noqa: E402
from scripts.check_test_slot_cleared import slot_problems  # noqa: E402
from scripts.generate_workflows import (  # noqa: E402
    TEST_WORKFLOW_NAME,
    empty_test_workflow_yaml,
    select_test_task,
    test_workflow_yaml,
    validate_task,
    workflow_yaml,
)


EMPTY_SLOT_TEXT = empty_test_workflow_yaml().rstrip() + "\n"


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


def build_task(name: str, *, is_test: bool = False, cron_setting: str = "") -> TaskSettings:
    params = {
        "name": name,
        "script_path": "tasks/demo/github_cpython_repo.py",
        "gcp_auth": False,
    }
    if is_test:
        params["is_test"] = True
    if cron_setting:
        params["cron_setting"] = cron_setting
    return TaskSettings(params=params)


def as_task_map(*tasks: TaskSettings) -> dict[str, TaskSettings]:
    return {task.name: task for task in tasks}


class SelectTestTaskTests(LoggedTestCase):
    def test_no_task_marked_is_test_returns_none(self) -> None:
        # Test: is_test is optional and defaults to false.
        # Expected: the test slot has no task to hold.
        tasks = as_task_map(build_task("alpha"), build_task("beta"))

        self.assertIsNone(select_test_task(tasks))

    def test_one_task_marked_is_test_is_selected(self) -> None:
        # Test: exactly one task opts into the test slot.
        # Expected: that task is returned.
        tasks = as_task_map(build_task("alpha"), build_task("beta", is_test=True))

        selected = select_test_task(tasks)

        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, "beta")

    def test_two_tasks_marked_is_test_raises_and_names_both(self) -> None:
        # Test: the slot holds one task, so two claims are ambiguous.
        # Expected: generation fails and the message names every offending task.
        tasks = as_task_map(
            build_task("alpha", is_test=True),
            build_task("beta"),
            build_task("gamma", is_test=True),
        )

        with self.assertRaises(ValueError) as raised:
            select_test_task(tasks)

        message = str(raised.exception)
        self.assertIn("alpha", message)
        self.assertIn("gamma", message)
        self.assertNotIn("beta", message)


class TestWorkflowYamlTests(LoggedTestCase):
    def test_empty_slot_is_dispatchable_and_runs_no_task(self) -> None:
        # Test: with no task selected the slot still has to exist on the default
        # branch, otherwise it is not dispatchable later.
        # Expected: workflow_dispatch is present but no task script runs.
        yaml = test_workflow_yaml(None)

        self.assertIn(f'name: "{TEST_WORKFLOW_NAME}"', yaml)
        self.assertIn("workflow_dispatch:", yaml)
        self.assertNotIn("--task-name", yaml)
        self.assertNotIn("schedule:", yaml)

    def test_filled_slot_runs_the_task_without_its_schedule(self) -> None:
        # Test: the slot carries the task's steps but must stay manual only, so
        # a scheduled task does not start running twice per cron tick.
        # Expected: the run step is present and the schedule trigger is not.
        task = build_task("alpha", is_test=True, cron_setting="0 14 * * *")

        yaml = test_workflow_yaml(task)

        self.assertIn("--task-name alpha", yaml)
        self.assertIn("workflow_dispatch:", yaml)
        self.assertNotIn("schedule:", yaml)
        self.assertNotIn("0 14 * * *", yaml)

    def test_slot_name_stays_constant_so_the_actions_list_is_stable(self) -> None:
        # Test: GitHub lists workflows by the default branch's name.
        # Expected: the slot is named the same whether or not it holds a task.
        task = build_task("alpha", is_test=True)

        self.assertIn(f'name: "{TEST_WORKFLOW_NAME}"', test_workflow_yaml(task))
        self.assertIn(f'name: "{TEST_WORKFLOW_NAME}"', test_workflow_yaml(None))

    def test_task_keeps_its_own_scheduled_workflow(self) -> None:
        # Test: is_test adds the slot, it does not replace the task's workflow.
        # Expected: the task's own workflow still carries its cron_setting.
        task = build_task("alpha", is_test=True, cron_setting="0 14 * * *")

        yaml = workflow_yaml(task)

        self.assertIn("schedule:", yaml)
        self.assertIn("0 14 * * *", yaml)
        self.assertIn('timezone: "America/New_York"', yaml)

    def test_generated_schedule_uses_new_york_timezone(self) -> None:
        # Test: cron_setting is written as local New York wall-clock time.
        # Expected: generated schedules opt into GitHub's timezone support.
        yaml = workflow_yaml(build_task("alpha", cron_setting="30 9 * * 1-5"))

        self.assertIn('cron: "30 9 * * 1-5"', yaml)
        self.assertIn('timezone: "America/New_York"', yaml)

    def test_generated_workflows_do_not_enable_dependency_cache(self) -> None:
        # Test: dependency caches can cross trust boundaries in GitHub Actions.
        # Expected: generated workflows install dependencies without cache restore.
        yaml = workflow_yaml(build_task("alpha"))

        self.assertNotIn("cache:", yaml)
        self.assertNotIn("cache: pip", yaml)


class ReservedWorkflowNameTests(LoggedTestCase):
    def test_task_cannot_claim_the_test_slot_file_name(self) -> None:
        # Test: a task named test_workflow with no group folder would generate
        # test_workflow.yml and silently overwrite the slot.
        # Expected: validation rejects it with a clear message.
        task = TaskSettings(
            params={
                "name": "test_workflow",
                "script_path": "scripts/generate_workflows.py",
            }
        )

        with self.assertRaisesRegex(ValueError, "reserves for the manual test slot"):
            validate_task(task)


class DescribeStepTests(LoggedTestCase):
    def test_filled_slot_reports_which_task_it_holds(self) -> None:
        # Test: the slot is always named "test workflow", so a run page cannot
        # otherwise tell you what it is running.
        # Expected: the slot describes the task it holds.
        yaml = test_workflow_yaml(build_task("alpha", is_test=True))

        self.assertIn("Report the task under test (alpha)", yaml)
        self.assertIn("python scripts/describe_task.py --task-name alpha", yaml)

    def test_report_runs_before_install_and_auth(self) -> None:
        # Test: "immediately" means before the slow steps, so a wrong task is
        # visible without waiting for pip and GCP auth.
        # Expected: the report step comes first among the three.
        yaml = test_workflow_yaml(build_task("alpha", is_test=True))

        report_at = yaml.index("Report the task under test")
        install_at = yaml.index("- name: Install package")
        run_at = yaml.index("- name: Run alpha")

        self.assertLess(report_at, install_at)
        self.assertLess(install_at, run_at)

    def test_report_receives_the_same_override_inputs_as_the_run(self) -> None:
        # Test: the report claims to show overrides applied, so it needs the same
        # workflow_dispatch inputs the run step gets.
        # Expected: the override env var appears twice, once per step.
        task = TaskSettings(
            params={
                "name": "alpha",
                "script_path": "tasks/demo/github_cpython_repo.py",
                "gcp_auth": False,
                "is_test": True,
                "manual_overrides": [
                    {"name": "region", "path": "region", "description": "Region to pull"},
                ],
            }
        )

        yaml = test_workflow_yaml(task)

        self.assertEqual(yaml.count("EDGERUNNER_OVERRIDE_REGION:"), 2)

    def test_empty_slot_has_no_report_step(self) -> None:
        # Test: with no task selected there is nothing to describe.
        # Expected: the empty slot does not reference the describe script.
        self.assertNotIn("describe_task.py", test_workflow_yaml(None))

    def test_normal_task_workflow_has_no_report_step(self) -> None:
        # Test: a task's own workflow is named after the task already.
        # Expected: the extra step is only in the slot.
        self.assertNotIn("describe_task.py", workflow_yaml(build_task("alpha")))


class SlotGuardTests(LoggedTestCase):
    def test_cleared_slot_reports_no_problems(self) -> None:
        # Test: the state a pull request into main is expected to be in.
        # Expected: the guard passes.
        tasks = as_task_map(build_task("alpha"), build_task("beta"))

        self.assertEqual(slot_problems(tasks, EMPTY_SLOT_TEXT), [])

    def test_task_left_on_is_test_is_reported(self) -> None:
        # Test: someone forgot to turn is_test back off before opening the PR.
        # Expected: the guard names the task.
        tasks = as_task_map(build_task("alpha", is_test=True))

        problems = slot_problems(tasks, EMPTY_SLOT_TEXT)

        self.assertEqual(len(problems), 1)
        self.assertIn("alpha", problems[0])

    def test_two_tasks_on_is_test_are_reported_instead_of_crashing(self) -> None:
        # Test: an ambiguous config must fail the check with a message, not an
        # unhandled traceback from the generator's validation.
        # Expected: one problem naming both tasks.
        tasks = as_task_map(build_task("alpha", is_test=True), build_task("beta", is_test=True))

        problems = slot_problems(tasks, EMPTY_SLOT_TEXT)

        self.assertEqual(len(problems), 1)
        self.assertIn("alpha", problems[0])
        self.assertIn("beta", problems[0])

    def test_stale_slot_file_is_reported_even_when_config_is_clean(self) -> None:
        # Test: is_test was turned off but the workflow was never regenerated, so
        # main would still carry a dispatchable copy of the task.
        # Expected: the guard catches the file, not just the config.
        tasks = as_task_map(build_task("alpha"))
        stale_slot = test_workflow_yaml(build_task("alpha", is_test=True))

        problems = slot_problems(tasks, stale_slot)

        self.assertEqual(len(problems), 1)
        self.assertIn("still holds a task's steps", problems[0])

    def test_missing_slot_file_is_reported(self) -> None:
        # Test: deleting the slot would silently break every future branch test,
        # because GitHub needs it on the default branch to offer Run workflow.
        # Expected: the guard treats a missing file as a problem.
        tasks = as_task_map(build_task("alpha"))

        problems = slot_problems(tasks, None)

        self.assertEqual(len(problems), 1)
        self.assertIn("is missing", problems[0])


if __name__ == "__main__":
    unittest.main()
