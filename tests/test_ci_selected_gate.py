"""CI selection must not turn missing evidence into a successful required gate."""
from __future__ import annotations

import json
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
    flags.update(tools_scope=scope, e2e_specs=specs)
    return flags


def jobs(*packs, **kwargs):
    return {
        "selection": {"result": "success", "outputs": outputs(*packs, **kwargs)},
        "documentation": {"result": "success"},
        "debug-tools": {"result": "success"},
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
        for key in ("preview", "e2e_specs"):
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


class PreviewWorkflowContractTests(CompactContainerAssertions, unittest.TestCase):
    def test_preview_keeps_successful_skip_and_rejects_invalid_selection(self):
        workflow = (ROOT / ".github/workflows/pr-release-windows.yml").read_text(encoding="utf-8")
        build = workflow.split("\n  build-windows:\n", 1)[1]
        self.assertIn("if: ${{ always() }}", build)
        self.assertIn("needs.selection.result != 'success'", build)
        self.assertIn("needs.selection.outputs.preview != 'true'", build)
        self.assertIn("needs.selection.outputs.preview != 'false'", build)
        self.assertIn("run: exit 1", build)
        for step in ("Build MAW bundle", "Upload MAW-lite release preview"):
            with self.subTest(step=step):
                content = build.split(f"- name: {step}\n", 1)[1].split("\n      - ", 1)[0]
                self.assertIn("if: ${{ needs.selection.outputs.preview == 'true' }}", content)

    def test_comment_distinguishes_skipped_built_and_failed(self):
        workflow = (ROOT / ".github/workflows/pr-release-comment.yml").read_text(encoding="utf-8")
        self.assertIn("const intentionallySkipped = run.conclusion === 'success'", workflow)
        self.assertIn("bundle?.conclusion === 'skipped'", workflow)
        self.assertIn("const succeeded = run.conclusion === 'success'", workflow)
        self.assertIn("bundle?.conclusion === 'success' && upload?.conclusion === 'success'", workflow)
        self.assertIn("intentionallySkipped ?", workflow)


class RequiredPythonReportTests(unittest.TestCase):
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
