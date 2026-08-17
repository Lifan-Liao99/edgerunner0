from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from edgerunner.task_config import TaskSettings  # noqa: E402
from scripts import clear_test_slot, generate_workflows  # noqa: E402


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


class ClearTestSlotTests(LoggedTestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.config_path = self.root / "config" / "tasks.toml"
        self.workflow_dir = self.root / ".github" / "workflows"
        task_dir = self.root / "tasks" / "demo"

        self.config_path.parent.mkdir(parents=True)
        task_dir.mkdir(parents=True)
        (task_dir / "alpha.py").write_text("print('ok')\n", encoding="utf-8")
        (task_dir / "beta.py").write_text("print('ok')\n", encoding="utf-8")

    def run_clear_test_slot(self) -> bool:
        with (
            patch.object(generate_workflows, "ROOT", self.root),
            patch.object(generate_workflows, "WORKFLOW_DIR", self.workflow_dir),
            patch.object(clear_test_slot, "CONFIG_PATH", self.config_path),
        ):
            return clear_test_slot.clear_test_slot()

    def write_config(self, content: str) -> None:
        self.config_path.write_text(content, encoding="utf-8")

    def test_is_test_true_is_cleared_and_workflow_is_regenerated(self) -> None:
        # Test: auto-clear repairs a branch that still has the manual slot loaded.
        # Expected: config flips to false and the generated test workflow is empty.
        self.write_config(
            """
[[tasks]]
name = "alpha"
script_path = "tasks/demo/alpha.py"
gcp_auth = false
is_test = true
"""
        )

        changed = self.run_clear_test_slot()

        self.assertTrue(changed)
        self.assertIn("is_test = false", self.config_path.read_text(encoding="utf-8"))
        slot_text = (self.workflow_dir / "test_workflow.yml").read_text(encoding="utf-8")
        self.assertIn("currently empty", slot_text)
        self.assertNotIn("--task-name alpha", slot_text)

    def test_multiple_is_test_true_tasks_are_all_cleared(self) -> None:
        # Test: auto-clear can repair the ambiguous state the generator rejects.
        # Expected: every task claiming the slot is set back to false.
        self.write_config(
            """
[[tasks]]
name = "alpha"
script_path = "tasks/demo/alpha.py"
gcp_auth = false
is_test = true

[[tasks]]
name = "beta"
script_path = "tasks/demo/beta.py"
gcp_auth = false
is_test = true
"""
        )

        changed = self.run_clear_test_slot()

        text = self.config_path.read_text(encoding="utf-8")
        self.assertTrue(changed)
        self.assertEqual(text.count("is_test = false"), 2)
        self.assertNotIn("is_test = true", text)

    def test_no_is_test_true_makes_no_changes(self) -> None:
        # Test: branches that already cleared the slot should not get empty commits.
        # Expected: no config rewrite and no workflow generation.
        config = """
[[tasks]]
name = "alpha"
script_path = "tasks/demo/alpha.py"
gcp_auth = false
is_test = false
"""
        self.write_config(config)

        changed = self.run_clear_test_slot()

        self.assertFalse(changed)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), config)
        self.assertFalse(self.workflow_dir.exists())

    def test_config_format_comments_and_field_order_are_preserved(self) -> None:
        # Test: clear_config uses tomlkit instead of rebuilding the TOML document.
        # Expected: comments and surrounding field order survive the boolean flip.
        config = """# top-level comment

[[tasks]]
# task id comment
name = "alpha"
script_path = "tasks/demo/alpha.py"
# slot marker comment
is_test = true # inline slot comment
gcp_auth = false
custom_after = "still here"
"""
        self.write_config(config)
        cleared = clear_test_slot.clear_config(
            self.config_path,
            [
                TaskSettings(
                    {
                        "name": "alpha",
                        "script_path": "tasks/demo/alpha.py",
                        "is_test": True,
                    }
                )
            ],
        )

        text = self.config_path.read_text(encoding="utf-8")
        self.assertEqual(cleared, ["alpha"])
        self.assertIn("# top-level comment", text)
        self.assertIn("# task id comment", text)
        self.assertIn("# slot marker comment", text)
        self.assertIn("is_test = false", text)
        self.assertIn("# inline slot comment", text)
        self.assertLess(text.index("name ="), text.index("script_path ="))
        self.assertLess(text.index("script_path ="), text.index("is_test ="))
        self.assertLess(text.index("is_test ="), text.index("gcp_auth ="))
        self.assertLess(text.index("gcp_auth ="), text.index("custom_after ="))


if __name__ == "__main__":
    unittest.main()
