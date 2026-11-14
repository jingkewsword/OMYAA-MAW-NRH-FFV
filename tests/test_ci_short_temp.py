from contextlib import ExitStack
from pathlib import Path
import tempfile
import contextlib
import io
import os
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
                        patch.object(test_workflow, "commands", return_value=iter([("gate", ["test"], 1)])), \
                        patch.object(test_workflow, "execute", side_effect=execute), \
                        patch.object(test_workflow.importlib.util, "find_spec", return_value=object()), \
                        patch.dict(os.environ, {"MAW_CI_SHORT_TEMP": enabled, "GITHUB_ACTIONS": "true"}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", packs, "--changed", "maw/project.py"]), 0)
                    self.assertEqual(choose.called, expected and os.name == "nt")
                if expected and os.name == "nt":
                    self.assertEqual(Path(observed[-1]), selected / "workflow-temp")
                    Path(observed[-1]).rmdir()

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
