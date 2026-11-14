"""The full browser plan must include each displaced upstream consumer."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import test_workflow


class FullBrowserContractTests(unittest.TestCase):
    def report(self, files, shard=None):
        specs = [{"id": f"case-{index}", "file": Path(path).name,
                  "title": "case", "tests": [{"projectId": "chromium", "expectedStatus": "passed"}]}
                 for index, path in enumerate(files)]
        return {"config": {"workers": 2, "fullyParallel": False, "forbidOnly": True, "version": "fixture",
                           "projects": [{"name": "chromium", "retries": 0, "repeatEach": 1}], "shard": shard},
                "errors": [], "suites": [{"specs": specs}]}

    def run_discovery(self, full, part=None, *, selection="editor-e2e", command=None):
        observed = []
        def execute(name, args, timeout):
            observed.append(args)
            report = full if name.endswith("-full") else part
            Path(os.environ["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(json.dumps(report), encoding="utf-8")
            return {"gate": name, "exit_code": 0, "log": "fixture"}
        def git(args, **kwargs):
            return "head\n" if "rev-parse" in args else ""
        with tempfile.TemporaryDirectory() as directory, patch.object(test_workflow, "execute", side_effect=execute), \
                patch.object(test_workflow.subprocess, "check_output", side_effect=git), patch.dict(os.environ):
            result = test_workflow.prepare_browser("browser-regressions", command or ["node", "--reporter=line,json"],
                Path(directory), (1, 4) if part is not None else None,
                [] if selection == "editor-e2e" else ["tests/e2e/one.spec.mjs"], selection, [])
        return result, observed

    def test_full_plan_requires_every_fixed_file_even_when_nonempty(self):
        names = test_workflow.FULL_EDITOR_REQUIRED_SPECS
        with self.assertRaisesRegex(ValueError, "spec.*no discovered cases"):
            self.run_discovery(self.report(names[:-1]))

    def test_full_plan_allows_shard_without_other_fixed_files(self):
        names = test_workflow.FULL_EDITOR_REQUIRED_SPECS
        full = self.report(names)
        part = self.report(names[:1], {"current": 1, "total": 4})
        result, commands = self.run_discovery(full, part)
        self.assertEqual(len(result["planned_ids"]), 1)
        self.assertEqual(result["scope"]["specs"], [])
        self.assertFalse(any(path in command for command in commands for path in names))

    def test_partial_plan_does_not_require_full_fixed_set(self):
        partial = self.report(["tests/e2e/one.spec.mjs"])
        for selection in ("e2e", "smoke"):
            with self.subTest(selection=selection):
                result, _ = self.run_discovery(partial, selection=selection, command=["node", "tests/e2e/one.spec.mjs"])
                self.assertEqual(len(result["planned_ids"]), 1)

    def test_fixed_contract_matches_original_upstream_command(self):
        workflow = (test_workflow.ROOT / ".github/workflows/editor-checks.yml").read_text(encoding="utf-8")
        fixed = workflow.split("- name: Real file and HTTP editor", 1)[1].split("\n      - ", 1)[0]
        command = next(line.strip()[5:] for line in fixed.splitlines() if line.strip().startswith("run: "))
        actual = {arg for arg in command.split() if arg.startswith("tests/e2e/")}
        self.assertEqual(actual, set(test_workflow.FULL_EDITOR_REQUIRED_SPECS))


if __name__ == "__main__":
    unittest.main()
