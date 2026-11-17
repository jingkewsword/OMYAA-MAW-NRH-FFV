"""Independent groups finish, preserve raw exits, and report blocked consumers."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from scripts import test_workflow as workflow
from tests.test_browser_results import fixture


class CompleteGroupTests(unittest.TestCase):
    def run_groups(self, groups, dependencies=None):
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "reports"
            output.mkdir()
            steps = [(name, [sys.executable, "-c",
                            "from pathlib import Path; import sys; "
                            "p=Path('calls'); p.write_text((p.read_text() if p.exists() else '')+sys.argv[1]+'\\n'); "
                            "sys.exit(int(sys.argv[2]))", name, str(code)], 15) for name, code in groups]
            try:
                os.chdir(root)
                with mock.patch.object(workflow, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                    summary = workflow.run_steps(steps, output, {}, metadata={"shard": {"current": 1, "total": 1}},
                                                 requirements=dependencies)
                calls = (root / "calls").read_text().splitlines()
                details = json.loads((output / "failures.json").read_text(encoding="utf-8"))
                saved = json.loads((output / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual(summary, saved)
                return calls, summary, details
            finally:
                os.chdir(before)

    def test_multiple_failures_do_not_stop_the_last_independent_group(self):
        calls, summary, details = self.run_groups([("first", 7), ("second", 9), ("last", 0)])
        self.assertEqual(calls, ["first", "second", "last"])
        self.assertEqual(summary["failed"], ["first", "second"])
        self.assertEqual(summary["not_run"], [])
        self.assertEqual([group["process_exit_code"] for group in summary["groups"]], [7, 9, 0])
        self.assertEqual(len(details["failures"]), 2)
        self.assertNotEqual(summary["exit_code"], 0)

    def test_preparation_failure_blocks_only_declared_consumers(self):
        calls, summary, _ = self.run_groups([("prepare", 23), ("dependent", 0), ("independent", 0)],
                                            {"dependent": ["prepare"]})
        self.assertEqual(calls, ["prepare", "independent"])
        self.assertEqual(summary["blocked"], ["dependent"])
        self.assertIsNone(summary["groups"][1]["process_exit_code"])
        self.assertEqual(summary["groups"][1]["blocked_by"], ["prepare"])
        self.assertNotEqual(summary["exit_code"], 0)

    def test_complete_success_is_distinct_from_an_unrun_group(self):
        calls, summary, details = self.run_groups([("first", 0), ("second", 0)])
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["exit_code"], 0)
        self.assertEqual(details, {"failures": [], "report_errors": []})

    def test_exit_zero_with_unsupported_node_skip_still_fails_the_gate(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for the real JUnit subprocess")
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "reports"
            output.mkdir()
            source = root / "skipped.mjs"
            source.write_text("import { test } from 'node:test'; test.skip('unverified capability', () => {});\n", encoding="utf-8")
            command = [node, "--test", "--test-reporter=junit", f"--test-reporter-destination={output / 'node-fixture.xml'}", str(source)]
            try:
                os.chdir(root)
                with mock.patch.object(workflow, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                    summary = workflow.run_steps([("node-fixture", command, 15)], output, {},
                                                 metadata={"shard": {"current": 1, "total": 1}}, requirements={})
                self.assertEqual(summary["groups"][0]["process_exit_code"], 0)
                self.assertNotEqual(summary["exit_code"], 0)
                details = json.loads((output / "failures.json").read_text(encoding="utf-8"))
                self.assertTrue(any(item["kind"] == "skipped" for item in details["failures"]))
            finally:
                os.chdir(before)

    def test_mixed_browser_preparation_is_decided_by_the_actual_shard(self):
        for file, expected in (("tool.spec.mjs", "passed"), ("app.spec.mjs", "blocked")):
            with self.subTest(file=file), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                output = root / "reports"
                output.mkdir()
                for name, source in {
                    "tests/e2e/tool.spec.mjs": "import {test} from '@playwright/test';",
                    "tests/e2e/app.spec.mjs": "startServer(); execFileSync('ffmpeg', []);",
                    "server-editor/serve.py": "import requests\n",
                }.items():
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(source, encoding="utf-8")
                listed, actual = fixture(file)
                command = ["node", "node_modules/@playwright/test/cli.js", "test", "tests/e2e/tool.spec.mjs", "tests/e2e/app.spec.mjs"]
                plan = {"mode": "targeted", "e2e_specs": command[-2:], "preparation": {"application": True}}
                def execute(name, args, timeout):
                    (output / f"{name}.json").write_text(json.dumps(actual), encoding="utf-8")
                    return {"gate": name, "command": args, "status": "completed", "exit_code": 0, "log": "full.log"}
                with mock.patch.object(workflow, "ROOT", root), mock.patch.object(workflow, "prepare_browser", return_value=listed), \
                        mock.patch.object(workflow, "execute", side_effect=execute) as run, contextlib.redirect_stdout(io.StringIO()):
                    summary = workflow.run_steps([("browser-regressions", command, 30)], output, plan,
                                                 metadata={"shard": {"current": 1, "total": 4}},
                                                 blocked_preparation=("build", "python-dependencies", "ffmpeg"))
                self.assertEqual(summary["groups"][0]["status"], expected)
                self.assertEqual(run.call_count, int(expected == "passed"))

    def test_full_preparation_failure_still_runs_independent_files(self):
        before = Path.cwd()
        source_root = workflow.ROOT
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "tests").mkdir()
            (root / "tests/__init__.py").write_text("", encoding="utf-8")
            for name in ("run_tests.py", "test_policy.py"):
                shutil.copyfile(source_root / "scripts" / name, root / "scripts" / name)
            for name, content in {
                "test_a_healthy.py": "import unittest\nclass Case(unittest.TestCase):\n    def test_pass(self): pass\n",
                "test_b_dependency.py": "import numpy\nimport unittest\nclass Case(unittest.TestCase):\n    def test_blocked(self): self.fail('dependency was not prepared')\n",
                "test_c_failure.py": "import unittest\nclass Case(unittest.TestCase):\n    def test_failure(self): self.fail('real independent failure')\n",
                "test_d_healthy.py": "import unittest\nclass Case(unittest.TestCase):\n    def test_last(self): pass\n",
            }.items():
                (root / "tests" / name).write_text(content, encoding="utf-8")
            output = root / "reports"
            output.mkdir()
            command = [sys.executable, "scripts/run_tests.py", "--pack", "common", "--required", "--report", str(output / "python-common.json")]
            try:
                os.chdir(root)
                with mock.patch.object(workflow, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                    summary = workflow.run_steps([("python-common", command, 20)], output, {"mode": "full"},
                                                 metadata={"shard": {"current": 1, "total": 1}},
                                                 blocked_preparation=("python-dependencies",))
                states = {group["gate"]: group["status"] for group in summary["groups"]}
                self.assertEqual(states["python-common"], "blocked")
                self.assertEqual(states["python-fallback-test_b_dependency"], "blocked")
                self.assertEqual(states["python-fallback-test_c_failure"], "failed")
                self.assertEqual(states["python-fallback-test_a_healthy"], "passed")
                self.assertEqual(states["python-fallback-test_d_healthy"], "passed")
                self.assertNotEqual(summary["exit_code"], 0)
            finally:
                os.chdir(before)

    def test_full_node_pack_keeps_independent_files_after_install_failure(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for file-level fallback")
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            targets = []
            for name, content in {
                "test_a.mjs": "import {test} from 'node:test'; test('healthy', () => {});",
                "test_dependency.mjs": "import missing from 'not-installed-fixture-package';",
                "test_z.mjs": "import {test} from 'node:test'; test('last healthy', () => {});",
            }.items():
                (root / "tests" / name).write_text(content, encoding="utf-8")
                targets.append("tests/" + name)
            output = root / "reports"
            output.mkdir()
            command = [node, "--test", "--test-reporter=junit", f"--test-reporter-destination={output / 'node-common.xml'}", *targets]
            try:
                os.chdir(root)
                with mock.patch.object(workflow, "ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                    summary = workflow.run_steps([("node-common", command, 20)], output, {"mode": "full"},
                                                 metadata={"shard": {"current": 1, "total": 1}},
                                                 blocked_preparation=("node-dependencies",))
                states = {group["gate"]: group["status"] for group in summary["groups"]}
                self.assertEqual(states["node-common"], "blocked")
                self.assertEqual(states["node-fallback-test_dependency"], "blocked")
                self.assertEqual(states["node-fallback-test_a"], "passed")
                self.assertEqual(states["node-fallback-test_z"], "passed")
                self.assertNotEqual(summary["exit_code"], 0)
            finally:
                os.chdir(before)


if __name__ == "__main__":
    unittest.main()
