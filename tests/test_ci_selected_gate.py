"""CI selection must not turn missing evidence into a successful required gate."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import test_workflow
from scripts.check_test_gate import FLAGS, check_gate
from tests.compact_assertions import CompactContainerAssertions

ROOT = Path(__file__).resolve().parents[1]


def outputs(*packs, specs="[]", scope="all"):
    flags = {key: "false" for key in FLAGS}
    for pack in packs:
        flags[pack.replace("-", "_")] = "true"
    flags["app"] = str(bool(set(packs) - {"docs", "website"})).lower()
    flags.update({key: str(value).lower() for key, value in
                  test_workflow.preparation(packs, json.loads(specs), scope).items()})
    flags.update(tools_scope=scope, e2e_specs=specs, light="false")
    return flags


def jobs(*packs, **kwargs):
    return {
        "selection": {"result": "success", "outputs": outputs(*packs, **kwargs)},
        "documentation": {"result": "success"},
        "debug-tools": {"result": "success"},
        "upstream-editor": {"result": "success"},
        "editor": {"result": "success"},
        "posix-contracts": {"result": "success"},
        "browser-gates": {"result": "success"},
        "website": {"result": "success"},
    }


class RequiredGateTests(unittest.TestCase):
    def test_documentation_and_website_are_required_when_selected(self):
        state = jobs("docs", "website")
        self.assertEqual(check_gate(state), [])
        for job in ("documentation", "debug-tools", "website"):
            for result in ("failure", "cancelled", "skipped"):
                with self.subTest(job=job, result=result):
                    state = jobs("docs", "website")
                    state[job]["result"] = result
                    self.assertIn(job, check_gate(state))

    def test_upstream_and_unselected_job_failures_do_not_pass(self):
        for name in ("upstream-editor", "browser-gates"):
            for result in ("failure", "cancelled"):
                state = jobs("docs")
                state[name]["result"] = result
                with self.subTest(name=name, result=result):
                    self.assertIn(name, check_gate(state))
        state = jobs("docs")
        del state["upstream-editor"]
        self.assertIn("upstream-editor", check_gate(state))

    def test_light_selection_requires_valid_output_and_successful_website(self):
        state = jobs("docs", "website")
        state["selection"]["outputs"]["light"] = "true"
        self.assertEqual(check_gate(state), [])
        for result in (None, "failure", "cancelled", "skipped"):
            changed = copy.deepcopy(state)
            if result is None:
                del changed["website"]
            else:
                changed["website"]["result"] = result
            self.assertIn("website", check_gate(changed))
        for light in (None, "", "yes"):
            changed = jobs("docs")
            if light is None:
                del changed["selection"]["outputs"]["light"]
            else:
                changed["selection"]["outputs"]["light"] = light
            with self.assertRaises(ValueError):
                check_gate(changed)
        changed = jobs("docs")
        changed["selection"]["outputs"]["light"] = "true"
        with self.assertRaises(ValueError):
            check_gate(changed)

    def test_upstream_light_paths_select_website_and_full_boundaries_stay_full(self):
        from scripts.ci_impact import light_path
        from scripts.test_policy import select_packs
        light_paths = ("README.md", "docs/INDEX.md", "website/README.md", "docs/user/FAQ.md",
                       "website/src/index.astro", "website/public/logo.svg", "website/docs/PROJECT_BRIEF.md")
        for path in light_paths:
            with self.subTest(path=path):
                self.assertTrue(light_path(path))
                self.assertIn("website", select_packs([path])["packs"])
        for path in ("website/src/pages/docs/generated.md", "website/public/docs-assets/a.png",
                     "CHANGELOG.md", "docs/engineering/DEVELOPMENT.md", "maw/project.py"):
            with self.subTest(path=path):
                self.assertFalse(light_path(path))
        self.assertFalse(all(light_path(path) for path in ("README.md", "maw/project.py")))
        self.assertIn("website", select_packs([])["packs"])

    def test_upstream_selector_falls_back_to_full_on_bad_diff_or_mixed_paths(self):
        from scripts import ci_impact
        base = "a" * 40
        scenarios = (([base + "\n", b"README.md\0docs/user/FAQ.md\0"], "true"),
                     ([base + "\n", b"CHANGELOG.md\0"], "false"),
                     ([base + "\n", b"README.md\0maw/project.py\0"], "false"),
                     (["b" * 40 + "\n"], "false"),
                     ([base + "\n", OSError("diff failed")], "false"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs"
            for replies, expected in scenarios:
                output.write_text("", encoding="utf-8")
                with self.subTest(expected=expected, replies=str(replies)), \
                        patch.dict("os.environ", {"PR_BASE_SHA": base, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_OUTPUT": str(output)}), \
                        patch.object(ci_impact.subprocess, "check_output", side_effect=replies), \
                        contextlib.redirect_stdout(io.StringIO()):
                    ci_impact.main()
                self.assertEqual(output.read_text(encoding="utf-8").strip(), f"light={expected}")
            output.write_text("", encoding="utf-8")
            with patch.dict("os.environ", {"PR_BASE_SHA": base, "GITHUB_EVENT_NAME": "push", "GITHUB_OUTPUT": str(output)}), \
                    patch.object(ci_impact.subprocess, "check_output") as git, contextlib.redirect_stdout(io.StringIO()):
                ci_impact.main()
            self.assertEqual(output.read_text(encoding="utf-8").strip(), "light=false")
            git.assert_not_called()

    def test_light_website_is_single_consumer_and_full_job_remains(self):
        workflow = (ROOT / ".github/workflows/editor-checks.yml").read_text(encoding="utf-8")
        upstream = workflow.split("\n  upstream-editor:\n", 1)[1].split("\n  documentation:\n", 1)[0]
        website = workflow.split("\n  website:\n", 1)[1].split("\n  browser-gates:\n", 1)[0]
        self.assertIn("if: ${{ always() }}", upstream)
        self.assertIn("needs.selection.outputs.light != 'true'", upstream)
        self.assertNotIn("Verify website document consumers", upstream)
        self.assertIn("uses: actions/setup-python@v6", website)
        self.assertIn("python-version: '3.11'", website)
        self.assertIn("tests/test_readme_content_sync.mjs", website)
        self.assertIn("--pack website", website)

    def test_selection_failure_never_succeeds_even_with_valid_outputs(self):
        for result in ("failure", "cancelled", "skipped"):
            with self.subTest(result=result):
                state = jobs("docs")
                state["selection"]["result"] = result
                self.assertIn("selection", check_gate(state))

    def test_absent_or_invalid_outputs_are_not_interpreted_as_false(self):
        for key in FLAGS:
            for value in (None, "", "yes"):
                with self.subTest(key=key, value=value):
                    state = jobs("docs")
                    if value is None:
                        del state["selection"]["outputs"][key]
                    else:
                        state["selection"]["outputs"][key] = value
                    with self.assertRaises((ValueError, KeyError)):
                        check_gate(state)
        for key in ("e2e_specs",):
            with self.subTest(missing=key):
                state = jobs("docs")
                del state["selection"]["outputs"][key]
                with self.assertRaises((ValueError, KeyError)):
                    check_gate(state)
        for key, value in (("tools_scope", ""), ("tools_scope", "wrong"),
                           ("e2e_specs", "{"), ("e2e_specs", "{}"),
                           ("e2e_specs", "[123]")):
            with self.subTest(key=key, value=value):
                state = jobs("docs")
                state["selection"]["outputs"][key] = value
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    check_gate(state)

    def test_selected_jobs_cannot_be_missing_skipped_cancelled_or_failed(self):
        cases = (("editor", ("common",)), ("posix-contracts", ("common",)),
                 ("browser-gates", ("editor-e2e",)), ("website", ("website",)))
        for job, packs in cases:
            for result in (None, "failure", "cancelled", "skipped"):
                with self.subTest(job=job, result=result):
                    state = jobs(*packs)
                    if result is None:
                        del state[job]
                    else:
                        state[job]["result"] = result
                    self.assertIn(job, check_gate(state))

    def test_conflicting_or_invalid_preparation_is_rejected(self):
        state = jobs("common")
        state["selection"]["outputs"]["application"] = "false"
        with self.assertRaises(ValueError):
            check_gate(state)
        state = jobs("editor-e2e")
        state["selection"]["outputs"]["e2e"] = "true"
        with self.assertRaises(ValueError):
            check_gate(state)

    def test_only_expected_skips_are_allowed(self):
        state = jobs("docs")
        for name in ("editor", "posix-contracts", "browser-gates", "website"):
            state[name]["result"] = "skipped"
        self.assertEqual(check_gate(state), [])


class EditorCompatibilityCheckTests(unittest.TestCase):
    def test_compatibility_check_always_requires_actual_gate_success(self):
        workflow = (ROOT / ".github/workflows/editor-checks.yml").read_text(encoding="utf-8")
        windows = workflow.split("\n  editor:\n", 1)[1].split("\n  posix-contracts:\n", 1)[0]
        gate = workflow.split("\n  test-gate:\n", 1)[1].split("\n  editor-compat:\n", 1)[0]
        compat = workflow.split("\n  editor-compat:\n", 1)[1]
        self.assertIn("name: Windows selected tests", windows)
        self.assertIn("name: Required test gate", gate)
        self.assertIn("name: editor", compat)
        self.assertIn("if: ${{ always() }}", compat)
        self.assertIn("needs: test-gate", compat)
        self.assertIn("TEST_GATE_RESULT: ${{ needs.test-gate.result }}", compat)
        self.assertIn("needs: [selection, debug-tools, upstream-editor, documentation, editor, posix-contracts, browser-gates, website]", gate)
        self.assertIn("RESULTS: ${{ toJSON(needs) }}", gate)
        self.assertNotIn("editor-compat", gate)
        self.assertEqual(workflow.count("    name: editor\n"), 1)
        command = next(line.strip()[5:] for line in compat.splitlines() if line.strip().startswith("run: "))
        args = shlex.split(command)
        self.assertEqual(args[0], "python")
        args[0] = sys.executable
        for result in ("success", "failure", "cancelled", "skipped", "", "unknown"):
            with self.subTest(result=result):
                completed = subprocess.run(args, env={**os.environ, "TEST_GATE_RESULT": result}, capture_output=True)
                self.assertEqual(completed.returncode == 0, result == "success")


class PlatformCoverageTests(unittest.TestCase):
    def test_windows_exemptions_are_exact_and_have_linux_consumers(self):
        from scripts import test_policy
        workflow = (ROOT / ".github/workflows/editor-checks.yml").read_text(encoding="utf-8")
        block = workflow.split("- name: Required POSIX-only Python cases", 1)[1].split("\n      - ", 1)[0]
        self.assertIn("--required --report", block)
        self.assertEqual(len(test_policy.POSIX_REQUIRED_CASES), 8)
        for identity, reason in test_policy.POSIX_REQUIRED_CASES.items():
            with self.subTest(identity=identity):
                self.assertIn("tests." + identity, block)
                with patch.object(test_policy.os, "name", "nt"):
                    self.assertTrue(test_policy.allowed_platform_skip("tests." + identity, reason))
                    self.assertFalse(test_policy.allowed_platform_skip("tests." + identity, reason + " changed"))
                    self.assertFalse(test_policy.allowed_platform_skip("tests." + identity + "_other", reason))
                with patch.object(test_policy.os, "name", "posix"):
                    self.assertFalse(test_policy.allowed_platform_skip("tests." + identity, reason))


class PreviewWorkflowContractTests(CompactContainerAssertions, unittest.TestCase):
    def test_preview_keeps_successful_skip_and_rejects_invalid_selection(self):
        workflow = (ROOT / ".github/workflows/pr-release-windows.yml").read_text(encoding="utf-8")
        build = workflow.split("\n  build-windows:\n", 1)[1]
        self.assertIn("if: ${{ always() }}", build)
        self.assertIn("needs.selection.result != 'success'", build)
        self.assertIn("needs.selection.outputs.light != 'true'", build)
        self.assertIn("needs.selection.outputs.light != 'false'", build)
        self.assertIn("run: exit 1", build)
        for step in ("Build MAW bundle", "Upload MAW-lite release preview"):
            with self.subTest(step=step):
                content = build.split(f"- name: {step}\n", 1)[1].split("\n      - ", 1)[0]
                self.assertIn("if: ${{ needs.selection.outputs.light != 'true' }}", content)

    def test_comment_distinguishes_skipped_built_and_failed(self):
        workflow = (ROOT / ".github/workflows/pr-release-comment.yml").read_text(encoding="utf-8")
        self.assertIn("const intentionallySkipped = run.conclusion === 'success'", workflow)
        self.assertIn("bundle?.conclusion === 'skipped'", workflow)
        self.assertIn("const succeeded = run.conclusion === 'success'", workflow)
        self.assertIn("bundle?.conclusion === 'success' && upload?.conclusion === 'success'", workflow)
        self.assertIn("intentionallySkipped ?", workflow)


class ExecutionReceiptTests(CompactContainerAssertions, unittest.TestCase):
    def test_completed_process_with_nonzero_exit_is_reported_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.md"
            with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}):
                test_workflow.write_execution_summary(root, {"packs": ["common"]},
                    [{"gate": "python-common", "status": "completed", "exit_code": 7, "duration_seconds": 1}], [], 7)
            content = summary.read_text(encoding="utf-8")
            self.assertIn("| python-common | failed | completed | 7 |", content)

    def test_nonzero_process_keeps_failure_counts_and_exit_code(self):
        area = ROOT / ".artifacts/python-report-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as directory:
            root = Path(directory)
            github_summary = root / "github.md"
            def commands(_packs, output, **_kwargs):
                yield "python-lifecycle", ["python", "--report", str(output / "python.json")], 1
            def execute(_name, command, _timeout):
                Path(command[-1]).write_text(json.dumps({"selected_ids": ["a", "b"], "run": 2, "failures": 1, "errors": 0, "skips": []}), encoding="utf-8")
                return {"gate": "python-lifecycle", "status": "completed", "exit_code": 7,
                        "duration_seconds": 1, "diagnostics": [], "tail": []}
            with patch.object(test_workflow, "ROOT", root), patch.object(test_workflow.os, "chdir"), \
                    patch.object(test_workflow, "commands", side_effect=commands), \
                    patch.object(test_workflow, "execute", side_effect=execute), \
                    patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(github_summary)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", "lifecycle", "--changed", "maw/project.py"]), 1)
            result = json.loads(next(root.rglob("summary.json")).read_text(encoding="utf-8"))["results"][0]
            self.assertEqual(result["exit_code"], 7)
            self.assertEqual(result["counts"]["failures"], 1)
            self.assertIn("| python-lifecycle | failed | completed | 7 |", github_summary.read_text(encoding="utf-8"))

    def test_failed_reports_keep_real_counts_and_missing_fields_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python_report = root / "python.json"
            python_report.write_text(json.dumps({"selected_ids": ["a", "b"], "run": 2, "failures": 1, "errors": 0, "skips": []}), encoding="utf-8")
            self.assertEqual(test_workflow.report_counts("python", python_report),
                             {"selected": 2, "run": 2, "failures": 1, "errors": 0, "skipped": 0})
            python_report.write_text('{"run": 1}', encoding="utf-8")
            self.assertEqual(test_workflow.report_counts("python", python_report)["failures"], "unknown")
            node_report = root / "node.xml"
            node_report.write_text('<testsuites><testsuite><testcase><failure/></testcase><testcase><skipped/></testcase></testsuite></testsuites>', encoding="utf-8")
            self.assertEqual(test_workflow.report_counts("node", node_report),
                             {"run": 2, "failures": 1, "errors": 0, "skipped": 1})
            browser_report = root / "browser.json"
            browser_report.write_text(json.dumps({"stats": {"expected": 3, "unexpected": 1, "skipped": 1, "flaky": 0}}), encoding="utf-8")
            self.assertEqual(test_workflow.report_counts("browser", browser_report),
                             {"passed": 3, "failures": 1, "skipped": 1, "flaky": 0})
            self.assertTrue(all(value == "unknown" for value in test_workflow.report_counts("browser", root / "missing.json").values()))


class RequiredPythonReportTests(unittest.TestCase):
    def test_missing_dependencies_mark_all_selected_gates_not_run(self):
        area = ROOT / ".artifacts/python-report-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as directory:
            root = Path(directory)
            summary_file = root / "github-summary.md"
            with patch.object(test_workflow, "ROOT", root), \
                    patch.object(test_workflow.os, "chdir"), \
                    patch.object(test_workflow.importlib.util, "find_spec", return_value=None), \
                    patch.object(test_workflow, "commands", return_value=iter([("python-common", ["python"], 1)])), \
                    patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary_file)}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", "common", "--changed", "maw/project.py"]), 1)
            report = json.loads(next(root.rglob("summary.json")).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "required-dependency-missing")
            self.assertEqual(report["not_run"], ["python-common"])
            self.assertIn("not-run", summary_file.read_text(encoding="utf-8"))

    def test_required_report_is_complete_and_records_passing_results(self):
        area = ROOT / ".artifacts/python-report-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        valid = {"selected_ids": ["tests.test_example.Example.test_case"], "run": 1,
                 "failures": 0, "errors": 0, "skips": [], "expected_failures": 0,
                 "unexpected_successes": 0, "exit_code": 0, "mode": "serial",
                 "workers": 1, "wall_seconds": 0.1, "full_log": "test.log"}
        reports = {"missing": None, "empty": {}, "passed": valid}
        for key in ("failures", "errors", "expected_failures", "unexpected_successes", "exit_code"):
            report = copy.deepcopy(valid)
            report[key] = 1
            reports[key] = report
        report = copy.deepcopy(valid)
        report["skips"] = [{"id": valid["selected_ids"][0], "reason": "dependency unavailable",
                            "platform_not_applicable": False}]
        reports["unsupported-skip"] = report
        report = copy.deepcopy(valid)
        allowed_id = "tests.test_ass_fonts.FontRootsTests.test_darwin_roots_include_mobile_asset_font_directories"
        report["selected_ids"] = [allowed_id]
        report["skips"] = [{"id": allowed_id, "reason": "本机没有 MobileAsset 字体资产目录",
                            "platform_not_applicable": True}]
        reports["allowed-platform-skip"] = report
        report = copy.deepcopy(valid)
        report.update(selected_ids=[], run=0)
        reports["no-tests"] = report
        for outcome, report in reports.items():
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(dir=area) as directory:
                root = Path(directory)

                def commands(_packs, report_dir, **_kwargs):
                    yield "python-lifecycle", ["python", "scripts/run_tests.py", "--required",
                                               "--report", str(report_dir / "python-lifecycle.json")], 1

                def execute(name, command, _timeout):
                    if report is not None:
                        Path(command[command.index("--report") + 1]).write_text(json.dumps(report), encoding="utf-8")
                    return {"gate": name, "exit_code": 0, "diagnostics": [], "tail": []}

                with patch.object(test_workflow, "ROOT", root), \
                        patch.object(test_workflow, "commands", side_effect=commands), \
                        patch.object(test_workflow, "execute", side_effect=execute), \
                        patch.object(test_workflow.os, "chdir"), patch.dict("os.environ"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = test_workflow.main(["--stage", "merge", "--pack", "lifecycle",
                                               "--changed", "tests/test_e2e_process_lifecycle.mjs"])
                self.assertEqual(code, 0 if outcome in {"passed", "allowed-platform-skip"} else 1)
                summary = json.loads(next(root.rglob("summary.json")).read_text(encoding="utf-8"))
                self.assertEqual(summary["exit_code"], code)
                if outcome not in {"passed", "allowed-platform-skip"}:
                    self.assertEqual(summary["results"][0]["status"], "invalid-required-report")


if __name__ == "__main__":
    unittest.main()
