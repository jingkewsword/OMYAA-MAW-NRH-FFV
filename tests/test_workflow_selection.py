"""Concrete selection reaches execution without widening or duplicate work."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import test_workflow as workflow


def selected():
    return {"mode": "targeted", "packs": ["common", "e2e"], "tools_scope": "all", "reasons": ["test input"],
            "python_tests": ["tests/test_project_contract.py"], "node_tests": ["tests/test_editor_utils.mjs"],
            "e2e_specs": ["tests/e2e/unified-tracks.spec.mjs"],
            "preparation": {"application": True, "real_media": True, "lint": False, "preview_windows": True}}


class ConcreteWorkflowTests(unittest.TestCase):
    def test_concrete_targets_are_executed_once_and_layers_do_not_rebuild(self):
        plan = selected()
        steps = list(workflow.commands(plan["packs"], Path("reports"), selection=plan, specs=plan["e2e_specs"]))
        python = next(command for name, command, _ in steps if name == "python-selected")
        self.assertIn("tests/test_project_contract.py", python)
        self.assertNotIn("--pack", python)
        self.assertEqual([name for name, _, _ in steps].count("browser-regressions"), 1)
        layer = list(workflow.commands(plan["packs"], Path("reports"), selection=plan, specs=plan["e2e_specs"],
                                       layer="browser", shard=(2, 3)))
        self.assertEqual([name for name, _, _ in layer], ["browser-regressions"])
        self.assertIn("--shard=2/3", layer[0][1])
        self.assertIn("tests/e2e/unified-tracks.spec.mjs", layer[0][1])

    def test_full_browser_replaces_the_same_smoke_cases(self):
        steps = list(workflow.commands(["smoke", "editor-e2e", "common", "browser", "lifecycle", "tools"], Path("reports")))
        self.assertNotIn("editor-http-smoke", [name for name, _, _ in steps])
        targets = [arg for name, command, _ in steps if name.startswith("node-")
                   for arg in command if arg.startswith("tests/") and arg.endswith(".mjs")]
        self.assertEqual(len(targets), len(set(targets)))

    def test_website_inputs_precede_their_browser_consumer(self):
        plan = selected()
        plan["packs"].append("website")
        plan["e2e_specs"] = ["tests/e2e/editor-entry-retirement.spec.mjs"]
        for selection in (plan, None):
            packs = plan["packs"] if selection else ["website", "editor-e2e"]
            steps = list(workflow.commands(packs, Path("reports"), selection=selection, specs=plan["e2e_specs"]))
            names = [name for name, _, _ in steps]
            self.assertLess(names.index("website-build"), names.index("browser-regressions"))

    def test_release_rejects_partial_browser_shard(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            workflow.main(["--stage", "release", "--shard", "1/2", "--plan-only"])
        self.assertEqual(result.exception.code, 2)

    def test_execution_preserves_the_callers_temporary_filesystem(self):
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chosen = root / "system-temp"
            chosen.mkdir()
            plan = {"mode": "targeted", "packs": [], "python_tests": [], "node_tests": [], "e2e_specs": [],
                    "tools_scope": "all", "reasons": ["standard library probe"],
                    "preparation": {"application": False, "real_media": False, "lint": False}}
            def execute(name, command, timeout):
                self.assertEqual(os.environ["TEMP"], str(chosen))
                self.assertEqual(os.environ["TMP"], str(chosen))
                return {"gate": name, "command": command, "exit_code": 0, "status": "completed", "log": "probe.log"}
            try:
                with mock.patch.dict(os.environ, {"TEMP": str(chosen), "TMP": str(chosen)}), \
                        mock.patch.object(workflow, "ROOT", root), mock.patch.object(workflow, "select_packs", return_value=plan), \
                        mock.patch.object(workflow, "commands", return_value=[("probe", ["probe"], 1)]), \
                        mock.patch.object(workflow, "execute", side_effect=execute), \
                        mock.patch.object(workflow.subprocess, "check_output", return_value="a" * 40), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(workflow.main(["--changed", "README.md"]), 0)
            finally:
                os.chdir(before)

    def test_platform_preservation_layers_execute_only_the_selected_intersection(self):
        plan = selected()
        plan["ci_platforms"] = {"existing_ubuntu_python": ["tests/test_project_contract.py"],
                                "existing_windows_node": ["tests/test_editor_utils.mjs"]}
        python = list(workflow.commands(plan["packs"], Path("reports"), selection=plan, layer="python-ubuntu-existing"))
        node = list(workflow.commands(plan["packs"], Path("reports"), selection=plan, layer="node-windows-existing"))
        self.assertEqual([name for name, _, _ in python], ["python-selected"])
        self.assertEqual([name for name, _, _ in node], ["node-selected"])
        self.assertIn("tests/test_project_contract.py", python[0][1])
        self.assertIn("tests/test_editor_utils.mjs", node[0][1])

    def test_saved_plan_rejects_stale_commit_and_unsafe_or_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            plan = selected()
            plan["head"] = "a" * 40
            path.write_text(json.dumps(plan), encoding="utf-8")
            with mock.patch.object(workflow.subprocess, "check_output", return_value="b" * 40):
                with self.assertRaisesRegex(ValueError, "different commit"):
                    workflow.read_selection(path)
            del plan["head"]
            plan["python_tests"] = ["tests/../scripts/test_workflow.py"]
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "concrete test path"):
                workflow.read_selection(path)
            plan["python_tests"] = ["tests/test_project_contract.py"] * 2
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                workflow.read_selection(path)

    def test_dev_defaults_to_the_actual_impact_plan(self):
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "tests/e2e/unified-tracks.spec.mjs"
            spec.parent.mkdir(parents=True)
            spec.write_text("// concrete spec fixture\n", encoding="utf-8")
            try:
                plan = selected()
                with mock.patch.object(workflow, "ROOT", root), mock.patch.object(workflow, "select_packs", return_value=plan), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(workflow.main(["--changed", "tests/test_project_contract.py", "--plan-only"]), 0)
                saved = json.loads(next(root.glob(".artifacts/test-workflow/*/plan.json")).read_text(encoding="utf-8"))
                self.assertEqual(saved["packs"], ["common", "e2e"])
                self.assertEqual(saved["python_tests"], ["tests/test_project_contract.py"])
            finally:
                os.chdir(before)


if __name__ == "__main__":
    unittest.main()
