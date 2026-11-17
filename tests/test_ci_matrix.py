import copy
import json
import os
from pathlib import Path
import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts import browser_results, ci_matrix, ci_run_layer, test_workflow
from tests.test_browser_results import fixture


class BrowserMatrixTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"head": "a" * 40, "mode": "targeted", "e2e_specs": ["tests/e2e/a.spec.mjs", "tests/e2e/b.spec.mjs"]}

    def test_expansion_and_override(self):
        self.assertEqual(ci_matrix.shards(self.plan), 1)
        self.plan["e2e_specs"] = [str(n) for n in range(17)]
        self.assertEqual(ci_matrix.shards(self.plan), 2)
        self.assertEqual(ci_matrix.shards(self.plan, "3"), 3)
        self.assertEqual(ci_matrix.shards({**self.plan, "mode": "full"}), 4)
        with self.assertRaises(ValueError):
            ci_matrix.shards(self.plan, "5")

    def make_evidence(self, base):
        listed_a, actual_a = fixture("a.spec.mjs", "first")
        listed_b, actual_b = fixture("b.spec.mjs", "second")
        full = copy.deepcopy(listed_a)
        full["config"]["shard"] = None
        full["suites"].append(copy.deepcopy(listed_b["suites"][0]))
        roots = []
        for index, listed, actual in ((1, listed_a, actual_a), (2, listed_b, actual_b)):
            for report in (listed, actual):
                report["config"]["shard"] = {"current": index, "total": 2}
            root = Path(base) / str(index)
            root.mkdir()
            summary = {"shard": {"current": index, "total": 2}, "head": self.plan["head"],
                       "selection_fingerprint": ci_matrix.fingerprint(self.plan), "exit_code": 0,
                       "requested_layer": "browser", "results": [{"gate": "browser-regressions", "exit_code": 0}]}
            files = {"summary.json": summary, "browser-regressions-full.json": full,
                     "browser-regressions-list.json": listed, "browser-regressions.json": actual,
                     "browser-regressions-validated.json": browser_results.validate(listed, actual, index, 2)}
            for name, value in files.items():
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            roots.append(root)
        return roots

    def test_gate_accepts_complete_discovery_and_rejects_missing_or_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = self.make_evidence(tmp)
            ci_matrix.gate(self.plan, 2, roots)
            with self.assertRaises(ValueError):
                ci_matrix.gate(self.plan, 2, roots[:1])
            report = roots[1] / "browser-regressions.json"
            value = json.loads(report.read_text(encoding="utf-8"))
            value["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "failed"
            report.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                ci_matrix.gate(self.plan, 2, roots)

    def test_gate_rejects_incomplete_union_and_stale_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = self.make_evidence(tmp)
            with self.assertRaises(ValueError):
                ci_matrix.gate({**self.plan, "head": "b" * 40}, 2, roots)
            for root in roots:
                path = root / "browser-regressions-full.json"
                value = json.loads(path.read_text(encoding="utf-8"))
                value["suites"].append(copy.deepcopy(value["suites"][0]))
                value["suites"][-1]["specs"][0]["title"] = "omitted"
                path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                ci_matrix.gate(self.plan, 2, roots)

    def test_gate_collects_failures_from_each_shard(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = self.make_evidence(tmp)
            for root in roots:
                summary = root / "summary.json"
                value = json.loads(summary.read_text(encoding="utf-8"))
                value.update(exit_code=1, results=[{"gate": "browser-regressions", "exit_code": 1}])
                summary.write_text(json.dumps(value), encoding="utf-8")
                actual = root / "browser-regressions.json"
                value = json.loads(actual.read_text(encoding="utf-8"))
                value["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "failed"
                actual.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ci_matrix.GateError) as caught:
                ci_matrix.gate(self.plan, 2, roots)
            failures = caught.exception.errors
            self.assertTrue(all(any(str(root) == e["source"] and "browser case" in e["error"]
                                    for e in failures) for root in roots))
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
            report_path = Path(tmp) / "gate.json"
            result = subprocess.run([sys.executable, "scripts/ci_matrix.py", "gate", "--plan", str(plan_path),
                                     "--root", tmp, "--total", "2", "--report", str(report_path)],
                                    capture_output=True, timeout=30, check=False)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(len([e for e in report["errors"] if e["error"].startswith("browser case (")]), 2)
            self.assertEqual(len(report["failures"]), 2)

    def test_gate_combines_complete_inventory_and_old_report_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = self.make_evidence(tmp)
            summary_path = roots[0] / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary.update(exit_code=1, results=[{"gate": "browser-regressions", "exit_code": 1,
                                                 "process_exit_code": 17}])
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            (roots[0] / "failures.json").write_text(json.dumps({"failures": [
                {"id": "one", "error": "full first traceback"}, {"id": "two", "error": "full second traceback"}],
                "report_errors": []}), encoding="utf-8")
            actual = roots[1] / "browser-regressions.json"
            value = json.loads(actual.read_text(encoding="utf-8"))
            value["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "failed"
            actual.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ci_matrix.GateError) as caught:
                ci_matrix.gate(self.plan, 2, roots)
            failures = caught.exception.failures
            self.assertEqual({entry["id"] for entry in failures}, {"one", "two", "b.spec.mjs::second [chromium]"})
            self.assertEqual([entry["process_exit_code"] for entry in failures[:2]], [17, 17])
            self.assertEqual(failures[0]["error"], "full first traceback")

    def test_group_summary_reports_independent_failures_and_blocked(self):
        steps = {name: {"outcome": outcome} for name, outcome in {
            "python": "success", "node": "failure", "first": "failure", "second": "failure",
            "third": "success", "blocked": "skipped"}.items()}
        groups = [{"id": name, "selected": True, "requires": deps} for name, deps in (
            ("first", ["python"]), ("second", ["python"]),
            ("third", ["python"]), ("blocked", ["node"]))]
        report = ci_matrix.summarize_steps(steps, groups)
        self.assertEqual(report["status"], "failed")
        self.assertEqual([item["status"] for item in report["groups"]], ["failed", "failed", "passed", "blocked"])
        self.assertEqual(report["groups"][-1]["unmet"], ["node"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            env = {**os.environ, "CI_STEPS": json.dumps(steps), "CI_GROUPS": json.dumps(groups)}
            result = subprocess.run([sys.executable, "scripts/ci_matrix.py", "steps", "--report", str(path)],
                                    env=env, capture_output=True, timeout=30, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["groups"], report["groups"])

    def test_failed_preparation_passed_as_specific_block(self):
        steps = {"build": {"outcome": "failure"}, "py_install": {"outcome": "success"}}
        requirements = {"build": True, "python-dependencies": True, "ffmpeg": False,
                        "chromium": False, "node-dependencies": False}
        self.assertEqual(ci_run_layer.blocked_preparation(steps, requirements), ["build"])

    def test_full_wrapper_forwards_failed_preparation_to_independent_fallback(self):
        source_root = test_workflow.ROOT
        before = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            (root / "tests").mkdir()
            (root / "tests/__init__.py").write_text("", encoding="utf-8")
            for name in ("run_tests.py", "test_policy.py"):
                shutil.copyfile(source_root / "scripts" / name, root / "scripts" / name)
            (root / "tests/test_a_healthy.py").write_text(
                "import unittest\nclass Case(unittest.TestCase):\n    def test_pass(self): pass\n", encoding="utf-8")
            (root / "tests/test_b_needs_numpy.py").write_text(
                "import numpy\nimport unittest\nclass Case(unittest.TestCase):\n    def test_blocked(self): pass\n", encoding="utf-8")
            output = root / "reports"
            output.mkdir()
            observed = {}

            def invoke_runner(command, **_kwargs):
                observed["command"] = command
                blocked = [command[i + 1] for i, arg in enumerate(command) if arg == "--blocked-preparation"]
                full = [sys.executable, "scripts/run_tests.py", "--pack", "common", "--required",
                        "--report", str(output / "python-common.json")]
                try:
                    os.chdir(root)
                    with mock.patch.object(test_workflow, "ROOT", root):
                        observed["summary"] = test_workflow.run_steps(
                            [("python-common", full, 20)], output, {"mode": "full"},
                            metadata={"shard": {"current": 1, "total": 1}}, blocked_preparation=blocked)
                finally:
                    os.chdir(before)
                return SimpleNamespace(returncode=observed["summary"]["exit_code"])

            prep = {key: {"outcome": outcome} for key, outcome in {
                "build": "success", "py_install": "failure", "ffmpeg": "success", "js_install": "success"}.items()}
            required = {"build": True, "python-dependencies": True, "ffmpeg": True,
                        "chromium": False, "node-dependencies": True}
            env = {"CI_PREPARATION": json.dumps(prep), "CI_REQUIREMENTS": json.dumps(required)}
            with mock.patch.dict(os.environ, env), mock.patch.object(sys, "argv", ["ci_run_layer", "--layer", "python",
                                      "--report-dir", str(output)]), \
                    mock.patch.object(ci_run_layer.subprocess, "run", side_effect=invoke_runner), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = ci_run_layer.main()
            self.assertNotEqual(code, 0)
            self.assertIn("python-dependencies", observed["command"])
            states = {item["gate"]: item["status"] for item in observed["summary"]["groups"]}
            self.assertEqual(states["python-common"], "blocked")
            self.assertEqual(states["python-fallback-test_a_healthy"], "passed")
            self.assertEqual(states["python-fallback-test_b_needs_numpy"], "blocked")

    def test_preview_full_fallback_only_when_preparation_fails(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/pr-release-windows.yml").read_text(encoding="utf-8")
        full = workflow.split("      - name: Run Python tests\n", 1)[1].split("\n      - ", 1)[0]
        partial = workflow.split("      - name: Continue independent Python files after preparation failure\n", 1)[1].split("\n      - ", 1)[0]
        for preparation in ("py_install", "build", "ffmpeg"):
            self.assertIn(f"steps.{preparation}.outcome == 'success'", full)
            self.assertIn(f"steps.{preparation}.outcome != 'success'", partial)
        self.assertIn("needs.selection.outputs.full == 'true'", partial)
        self.assertIn(".artifacts/ci-python-partial", partial)
        self.assertIn('"id":"python_partial"', workflow)


if __name__ == "__main__":
    unittest.main()
