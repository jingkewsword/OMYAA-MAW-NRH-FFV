"""Verify local browser execution matches discovery without skipped results."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.browser_results import discovery, verify_run


def sample_report(ids=("one", "two")):
    return {"config": {"workers": 2, "fullyParallel": False, "forbidOnly": True, "version": "fixture",
                       "projects": [{"name": "chromium", "retries": 0, "repeatEach": 1}]}, "errors": [],
            "suites": [{"specs": [{"id": identity, "tests": [{"projectId": "chromium", "expectedStatus": "passed",
              "status": "expected", "results": [{"status": "passed", "retry": 0}]}]} for identity in ids]}],
            "stats": {"expected": len(ids), "unexpected": 0, "skipped": 0, "flaky": 0}}

class BrowserResultsTests(unittest.TestCase):
    def test_each_explicit_spec_contributes_a_discovered_case(self):
        report = sample_report()
        report["suites"][0]["specs"][0]["file"] = "one.spec.mjs"
        report["suites"][0]["specs"][1]["file"] = "two.spec.mjs"
        self.assertEqual(discovery(report, ["tests/e2e/one.spec.mjs", "tests/e2e/two.spec.mjs"]),
                         discovery(report))
        report["suites"][0]["specs"].pop()
        with self.assertRaisesRegex(ValueError, "spec.*no discovered cases"):
            discovery(report, ["tests/e2e/one.spec.mjs", "tests/e2e/two.spec.mjs"])

    def test_unexecuted_discovery_cannot_be_a_runtime_pass(self):
        report = sample_report()
        for spec in report["suites"][0]["specs"]:
            spec["tests"][0]["results"] = []
        planned = discovery(report)
        with self.assertRaises(ValueError):
            verify_run(planned, report)


    def test_missing_failed_skipped_flaky_and_retried_cases_fail(self):
        expected = discovery(sample_report())
        self.assertEqual(verify_run(expected, sample_report()), {"passed_ids": expected, "allowed_skipped_ids": []})
        for fault in ("missing", "failed", "skipped", "flaky", "retry", "global-error"):
            report = sample_report()
            case = report["suites"][0]["specs"][0]["tests"][0]
            if fault == "missing":
                report["suites"][0]["specs"].pop()
            elif fault in ("failed", "skipped"):
                case["results"][0]["status"] = fault
            elif fault == "flaky":
                report["stats"]["flaky"] = 1
            elif fault == "retry":
                case["results"][0]["retry"] = 1
            else:
                report["errors"] = [{"message": "teardown failed"}]
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                verify_run(expected, report)

    def test_only_exact_upstream_retired_portable_skip_is_accepted(self):
        report = sample_report()
        spec = report["suites"][0]["specs"][0]
        spec.update(file="editor-bundle.spec.mjs", title="file executes every source and preserves project/export/undo behavior")
        case = spec["tests"][0]
        reason = "便携模式已弃维护，2.0 移除 HTML，见 #336 后回归分析"
        case.update(expectedStatus="skipped", status="skipped", annotations=[{"type": "skip", "description": reason}],
                    results=[{"status": "skipped", "retry": 0}])
        report["stats"].update(expected=1, skipped=1)
        result = verify_run(["one@chromium", "two@chromium"], report)
        self.assertEqual(result, {"passed_ids": ["two@chromium"], "allowed_skipped_ids": ["one@chromium"]})
        for fault in ("file", "title", "project", "reason", "retry", "missing-result", "stats"):
            bad = json.loads(json.dumps(report))
            broken = bad["suites"][0]["specs"][0]
            test = broken["tests"][0]
            if fault in ("file", "title"):
                broken[fault] += "-other"
            elif fault == "project":
                test["projectId"] = "firefox"
            elif fault == "reason":
                test["annotations"][0]["description"] = "other reason"
            elif fault == "retry":
                test["results"][0]["retry"] = 1
            elif fault == "stats":
                bad["stats"]["skipped"] = 0
            else:
                test["results"] = []
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                verify_run(["one@" + ("firefox" if fault == "project" else "chromium"), "two@chromium"], bad)


class RealPlaywrightDiscoveryTests(unittest.TestCase):
    def test_actual_discovery_execution_and_only_guard_without_launching_browsers(self):
        node = shutil.which("node")
        cli = ROOT / "node_modules/@playwright/test/cli.js"
        if not node or not cli.exists():
            self.skipTest("locked Node/Playwright development dependencies are required")
        area = ROOT / ".artifacts/browser-gate-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as directory:
            fixture = Path(directory)
            config = fixture / "config.mjs"
            config.write_text("export default {testDir:'.', workers:2, projects:[{name:'chromium'}]};\n", encoding="utf-8")
            for index in (1, 2):
                (fixture / f"part{index}.spec.mjs").write_text(
                    "import {test,expect} from '@playwright/test';\n"
                    f"test('case{index}a',()=>expect(1).toBe(1));\n"
                    f"test('case{index}b',()=>expect(2).toBe(2));\n", encoding="utf-8")
            (fixture / "editor-bundle.spec.mjs").write_text(
                "import {test} from '@playwright/test';\n"
                "test('file executes every source and preserves project/export/undo behavior', () => {"
                "test.skip(true, '便携模式已弃维护，2.0 移除 HTML，见 #336 后回归分析'); });\n", encoding="utf-8")
            command = [node, str(cli), "test", "--config", str(config), "--project=chromium", "--forbid-only", "--retries=0", "--reporter=json"]

            def invoke(extra=()):
                return subprocess.run([*command, *extra], cwd=ROOT, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30,
                                      env={**__import__("os").environ, "PLAYWRIGHT_JSON_OUTPUT_NAME": ""})

            full = invoke(["--list"])
            self.assertEqual(full.returncode, 0, full.stderr[:1000])
            expected = discovery(json.loads(full.stdout))
            runtime = invoke()
            self.assertEqual(runtime.returncode, 0, runtime.stderr[:1000])
            verified = verify_run(expected, json.loads(runtime.stdout))
            self.assertEqual(len(verified["passed_ids"]), 4)
            self.assertEqual(len(verified["allowed_skipped_ids"]), 1)
            self.assertEqual(sorted(verified["passed_ids"] + verified["allowed_skipped_ids"]), expected)
            (fixture / "part1.spec.mjs").write_text("import {test} from '@playwright/test'; test.only('focus',()=>{});\n", encoding="utf-8")
            focused = invoke()
            self.assertNotEqual(focused.returncode, 0)
