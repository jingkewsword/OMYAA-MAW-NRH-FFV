from contextlib import ExitStack
from pathlib import Path
import tempfile
import contextlib
import io
import os
import json
import unittest
from unittest.mock import patch

from scripts import browser_results, test_workflow


class ShortTempTests(unittest.TestCase):
    def test_skips_unchanged_alias_then_selects_distinct_same_file_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "first").mkdir()
            (base / "second").mkdir()
            env = {"TEMP": str(base / "first"), "LOCALAPPDATA": str(base / "second")}
            (base / "second" / "Temp").mkdir()
            with patch.object(test_workflow, "windows_short_path", side_effect=lambda p: p if "first" in p else p + "-alias"), \
                    patch.object(Path, "samefile", return_value=True), ExitStack() as stack:
                selected, label = test_workflow.select_ci_short_temp(stack, env)
                self.assertEqual(label, "LOCALAPPDATA/Temp")
                self.assertTrue(selected.is_dir())
                self.assertEqual(list((base / "first").iterdir()), [])
            self.assertFalse(selected.exists())

    def test_no_valid_alias_or_wrong_file_fails_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(test_workflow, "windows_short_path", side_effect=lambda p: p + "-alias"), \
                    patch.object(Path, "samefile", return_value=False), ExitStack() as stack:
                with self.assertRaisesRegex(OSError, "No candidate"):
                    test_workflow.select_ci_short_temp(stack, {"TEMP": root})
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_only_ancestor_alias_does_not_count_for_new_directory(self):
        with tempfile.TemporaryDirectory() as root:
            def ancestor_only(path):
                return str(Path(root).parent / "OTHER~1" / Path(path).name)
            with patch.object(test_workflow, "windows_short_path", side_effect=ancestor_only), \
                    patch.object(Path, "samefile", return_value=True), ExitStack() as stack:
                with self.assertRaisesRegex(OSError, "No candidate"):
                    test_workflow.select_ci_short_temp(stack, {"TEMP": root})
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_opt_in_is_limited_to_windows_common_and_cleans_selected_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "chosen"
            selected.mkdir()
            observed = []
            def execute(name, _command, _timeout):
                observed.append(os.environ["TEMP"])
                return {"gate": name, "exit_code": 0, "status": "completed", "diagnostics": [], "tail": []}
            for enabled, packs, expected in (("1", "common", True), ("0", "common", False), ("1", "lifecycle", False)):
                with self.subTest(enabled=enabled, packs=packs), \
                        patch.object(test_workflow, "ROOT", root), \
                        patch.object(test_workflow.os, "chdir"), \
                        patch.object(test_workflow, "select_ci_short_temp", return_value=(selected, "TEMP")) as choose, \
                        patch.object(test_workflow, "commands", return_value=iter([("python-common", ["test"], 1)])), \
                        patch.object(test_workflow, "execute", side_effect=execute), \
                        patch.object(test_workflow.importlib.util, "find_spec", return_value=object()), \
                        patch.dict(os.environ, {"MAW_CI_SHORT_TEMP": enabled, "GITHUB_ACTIONS": "true"}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", packs, "--changed", "maw/project.py"]), 0)
                    self.assertEqual(choose.called, expected and os.name == "nt")
                if expected and os.name == "nt":
                    self.assertEqual(Path(observed[-1]), selected / "workflow-temp")
                    Path(observed[-1]).rmdir()

    def test_short_environment_is_limited_to_common_and_cleaned_after_failure(self):
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory(prefix="path with space 字-") as directory:
                root = Path(directory)
                candidates = root / "candidate"
                candidates.mkdir()
                keep = candidates / "do-not-delete"
                keep.write_text("keep", encoding="utf-8")
                observed = []
                selected = []
                def select(stack, _environment):
                    handle = tempfile.TemporaryDirectory(prefix="owned-long-temp-", dir=candidates)
                    path = Path(stack.enter_context(handle))
                    selected.append(path)
                    return path, "TEMP"
                def commands(_packs, _output, **_kwargs):
                    yield "python-common", ["first"], 1
                    yield "browser-followup", ["second"], 1
                def execute(name, _command, _timeout):
                    observed.append((name, tuple(os.environ[key] for key in ("TEMP", "TMP", "TMPDIR"))))
                    return {"gate": name, "status": "completed", "exit_code": exit_code if name == "python-common" else 0,
                            "diagnostics": [], "tail": []}
                with patch.object(test_workflow, "ROOT", root), patch.object(test_workflow.os, "chdir"), \
                        patch.object(test_workflow, "ci_short_temp_enabled", return_value=True), \
                        patch.object(test_workflow, "select_ci_short_temp", side_effect=select), \
                        patch.object(test_workflow, "commands", side_effect=commands), \
                        patch.object(test_workflow, "execute", side_effect=execute), \
                        patch.object(test_workflow.importlib.util, "find_spec", return_value=object()), \
                        patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", "common", "--changed", "maw/project.py"]), int(exit_code != 0))
                    workflow_temp = os.environ["TEMP"]
                    self.assertEqual(tuple(os.environ[key] for key in ("TEMP", "TMP", "TMPDIR")), (workflow_temp,) * 3)
                self.assertEqual(observed[0][1], (str(selected[0] / "workflow-temp"),) * 3)
                if exit_code == 0:
                    self.assertEqual(observed[1][1], (workflow_temp,) * 3)
                else:
                    self.assertEqual(len(observed), 1)
                self.assertFalse(selected[0].exists())
                self.assertEqual(keep.read_text(encoding="utf-8"), "keep")
                plan = json.loads(next(root.rglob("plan.json")).read_text(encoding="utf-8"))
                summary = json.loads(next(root.rglob("summary.json")).read_text(encoding="utf-8"))
                self.assertEqual(plan["python_common_temp_location"], "TEMP")
                self.assertEqual(summary["plan"]["python_common_temp_location"], "TEMP")
                self.assertEqual(summary["exit_code"], exit_code)

    def test_preparation_and_cleanup_failure_have_truthful_receipts(self):
        for fault, process_exit in (("mkdir", 0), ("cleanup", 0), ("cleanup", 7)):
            with self.subTest(fault=fault, process_exit=process_exit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                selected = root / "selected"
                selected.mkdir()
                original_mkdir = Path.mkdir
                called = []
                github_summary = root / "github-summary.md"
                def mkdir(path, *args, **kwargs):
                    if fault == "mkdir" and path == selected / "workflow-temp":
                        raise OSError("short directory denied")
                    return original_mkdir(path, *args, **kwargs)
                def select(stack, _env):
                    def cleanup():
                        if fault == "cleanup":
                            raise OSError("cleanup denied")
                    stack.callback(cleanup)
                    return selected, "TEMP"
                def execute(name, _command, _timeout):
                    called.append(name)
                    return {"gate": name, "status": "completed", "exit_code": process_exit,
                            "diagnostics": [], "tail": []}
                with patch.object(test_workflow, "ROOT", root), patch.object(test_workflow.os, "chdir"), \
                        patch.object(test_workflow, "ci_short_temp_enabled", return_value=True), \
                        patch.object(test_workflow, "select_ci_short_temp", side_effect=select), \
                        patch.object(test_workflow, "commands", return_value=iter([("python-common", ["test"], 1)])), \
                        patch.object(test_workflow, "execute", side_effect=execute), \
                        patch.object(test_workflow.importlib.util, "find_spec", return_value=object()), \
                        patch.object(Path, "mkdir", mkdir), patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(github_summary)}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", "common", "--changed", "maw/project.py"]), 1)
                receipt = json.loads(next(root.rglob("summary.json")).read_text(encoding="utf-8"))
                self.assertEqual(receipt["exit_code"], process_exit or 1)
                self.assertEqual(receipt["status"], "short-temp-preparation-failed" if fault == "mkdir" else "short-temp-cleanup-failed")
                self.assertIn("denied", receipt["error"])
                self.assertIn(receipt["status"], github_summary.read_text(encoding="utf-8"))
                self.assertEqual(receipt["not_run"], ["python-common"] if fault == "mkdir" else [])
                self.assertEqual(called, [] if fault == "mkdir" else ["python-common"])
                self.assertTrue(selected.is_dir())

    def test_temporary_environment_restores_missing_and_existing_values_on_exception(self):
        with patch.dict(os.environ, {"TEMP": "original", "TMP": "before"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "failure"):
                with test_workflow.temporary_environment({"TEMP": "short", "TMP": "short", "TMPDIR": "short"}):
                    raise RuntimeError("failure")
            self.assertEqual(dict(os.environ), {"TEMP": "original", "TMP": "before"})

    def test_api_failure_falls_through_without_leaving_probe(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(test_workflow, "windows_short_path", side_effect=OSError("unavailable")), ExitStack() as stack:
                with self.assertRaisesRegex(OSError, "No candidate"):
                    test_workflow.select_ci_short_temp(stack, {"TEMP": root})
            self.assertEqual(list(Path(root).iterdir()), [])


class BrowserDiagnosticTests(unittest.TestCase):
    def test_failed_shards_report_raw_counts_without_passing_coverage(self):
        records = [{"shard": {"current": i}, "status": "failed" if i == 2 else "passed",
                    "diagnostic_counts": {"passed": 10, "failures": int(i == 2), "skipped": 1, "flaky": 0}}
                   for i in range(1, 5)]
        diagnostic = browser_results.diagnostic_shards(records, 4)
        self.assertEqual(diagnostic["totals"], {"passed": 40, "failures": 1, "skipped": 4, "flaky": 0})
        self.assertEqual(diagnostic["shards"][1]["status"], "failed")
        with self.assertRaises((ValueError, KeyError)):
            browser_results.combine_shards(records, 4, "head")
        records[1]["diagnostic_counts"].pop("passed")
        self.assertEqual(browser_results.diagnostic_shards(records, 4)["totals"]["passed"], "unknown")
        self.assertEqual(browser_results.diagnostic_shards(records[:3], 4)["totals"]["failures"], "unknown")
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "result.json"
            report.write_text('{"stats": []}', encoding="utf-8")
            self.assertTrue(all(value == "unknown" for value in test_workflow.browser_diagnostic_counts(report).values()))
            report.write_text('{"stats": {"expected": 4, "unexpected": 0, "skipped": 0, "flaky": 0}}', encoding="utf-8")
            self.assertTrue(all(value == "unknown" for value in test_workflow.browser_diagnostic_counts(report).values()))


if __name__ == "__main__":
    unittest.main()
