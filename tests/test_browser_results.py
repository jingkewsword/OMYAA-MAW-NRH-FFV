"""Fault injection for incomplete/focused browser gates and missing CI jobs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.browser_results import SCHEMA, browser_config, combine_shards, discovery, verify_run
from scripts.check_test_gate import FLAGS, check_gate


def sample_report(ids=("one", "two")):
    return {"config": {"workers": 2, "fullyParallel": False, "forbidOnly": True, "version": "fixture",
                       "projects": [{"name": "chromium", "retries": 0, "repeatEach": 1}]}, "errors": [],
            "suites": [{"specs": [{"id": identity, "tests": [{"projectId": "chromium", "expectedStatus": "passed",
              "status": "expected", "results": [{"status": "passed", "retry": 0}]}]} for identity in ids]}],
            "stats": {"expected": len(ids), "unexpected": 0, "skipped": 0, "flaky": 0}}


def sample_shards():
    scope = {"revision": "head", "selection": "editor-e2e", "specs": [], "worktree_clean": True,
             "config": browser_config(sample_report()), "case_ids": ["one@chromium", "two@chromium"]}
    return [{"schema": SCHEMA, "scope": copy.deepcopy(scope), "shard": {"current": index, "total": 4},
             "planned_ids": ids, "passed_ids": ids[:], "status": "passed" if ids else "empty-shard"}
            for index, ids in enumerate((["one@chromium"], [], ["two@chromium"], []), 1)]


class BrowserResultsTests(unittest.TestCase):
    def test_unexecuted_discovery_cannot_be_a_runtime_pass(self):
        report = sample_report()
        for spec in report["suites"][0]["specs"]:
            spec["tests"][0]["results"] = []
        planned = discovery(report)
        with self.assertRaises(ValueError):
            verify_run(planned, report)

    def test_missing_failed_skipped_flaky_and_retried_cases_fail(self):
        expected = discovery(sample_report())
        self.assertEqual(verify_run(expected, sample_report()), expected)
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

    def test_shards_must_cover_the_full_set_once_at_the_same_revision(self):
        self.assertEqual(combine_shards(sample_shards(), 4, "head")["cases"], 2)
        for fault in ("missing", "duplicate-index", "overlap", "lost-case", "wrong-revision", "failed", "smoke-as-full", "dirty-scope"):
            reports = sample_shards()
            if fault == "missing":
                reports.pop()
            elif fault == "duplicate-index":
                reports[1]["shard"]["current"] = 1
            elif fault == "overlap":
                reports[2]["planned_ids"] = reports[2]["passed_ids"] = ["one@chromium"]
            elif fault == "lost-case":
                reports[2].update(planned_ids=[], passed_ids=[], status="empty-shard")
            elif fault == "wrong-revision":
                reports[2]["scope"]["revision"] = "other"
            elif fault == "failed":
                reports[2]["status"] = "failed"
            elif fault == "smoke-as-full":
                for record in reports:
                    record["scope"]["selection"] = "smoke"
            else:
                for record in reports:
                    record["scope"]["worktree_clean"] = False
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                combine_shards(reports, 4, "head")

    def test_missing_selector_flags_and_failed_required_jobs_cannot_pass(self):
        outputs = {flag: "false" for flag in FLAGS}
        outputs.update(tools_scope="all", e2e_specs="[]")
        jobs = {"selection": {"result": "success", "outputs": outputs}, "documentation": {"result": "success"}, "debug-tools": {"result": "success"}}
        self.assertEqual(check_gate(jobs), [])
        for malformed in ({}, {**outputs, "media": ""}, {**outputs, "app": "false", "editor_e2e": "true"}):
            with self.subTest(outputs=malformed), self.assertRaises(ValueError):
                check_gate({**jobs, "selection": {"result": "success", "outputs": malformed}})
        jobs["selection"]["outputs"] = {**outputs, "app": "true", "editor_e2e": "true",
                                        "application": "true", "real_media": "true"}
        for name in ("editor", "browser-gates"):
            jobs[name] = {"result": "success"}
        self.assertEqual(check_gate(jobs), [])
        for state in ("failure", "cancelled", "skipped"):
            jobs["browser-gates"]["result"] = state
            self.assertIn("browser-gates", check_gate(jobs))


class RealPlaywrightDiscoveryTests(unittest.TestCase):
    def test_actual_file_shards_and_only_guard_without_launching_browsers(self):
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
            command = [node, str(cli), "test", "--config", str(config), "--project=chromium", "--forbid-only", "--retries=0", "--reporter=json"]

            def invoke(extra=()):
                return subprocess.run([*command, *extra], cwd=ROOT, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30,
                                      env={**__import__("os").environ, "PLAYWRIGHT_JSON_OUTPUT_NAME": ""})

            full = invoke(["--list"])
            self.assertEqual(full.returncode, 0, full.stderr[:1000])
            expected = discovery(json.loads(full.stdout))
            observed = []
            for index in range(1, 5):
                part = invoke(["--list", f"--shard={index}/4", "--pass-with-no-tests"])
                self.assertEqual(part.returncode, 0, part.stderr[:1000])
                observed.extend(discovery(json.loads(part.stdout)))
            self.assertEqual(sorted(observed), expected)
            self.assertEqual(len(observed), len(set(observed)))
            runtime = invoke()
            self.assertEqual(runtime.returncode, 0, runtime.stderr[:1000])
            self.assertEqual(verify_run(expected, json.loads(runtime.stdout)), expected)
            (fixture / "part1.spec.mjs").write_text("import {test} from '@playwright/test'; test.only('focus',()=>{});\n", encoding="utf-8")
            focused = invoke()
            self.assertNotEqual(focused.returncode, 0)
