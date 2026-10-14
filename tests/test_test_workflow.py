"""Selection must broaden safely and never lose a test or conceal a skip."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import run_tests
from scripts import test_policy
from scripts import test_workflow
from scripts.test_policy import ALL_MERGE, PYTHON_PACKS, select_packs


class TestWorkflowTests(unittest.TestCase):
    def test_failed_gate_on_legacy_console_still_saves_summary(self):
        import json
        area = ROOT / '.artifacts/console-fixtures'
        area.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        console = io.TextIOWrapper(buffer, encoding='cp1252')
        failure = {'gate': 'synthetic', 'exit_code': 1, 'diagnostics': ['✖ synthetic failure'], 'tail': []}
        with tempfile.TemporaryDirectory(dir=area) as directory:
            with patch.object(test_workflow, 'ROOT', Path(directory)), \
                    patch.object(test_workflow, 'commands', return_value=[('synthetic', [], 1)]), \
                    patch.object(test_workflow, 'execute', return_value=failure), \
                    patch.object(test_workflow.os, 'chdir'), \
                    patch.object(sys, 'stdout', console), patch.dict('os.environ'):
                self.assertEqual(test_workflow.main(['--stage', 'merge', '--pack', 'lifecycle',
                                                    '--changed', 'tests/test_e2e_process_lifecycle.mjs']), 1)
            summary_path = next(Path(directory).rglob('summary.json'))
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            self.assertEqual(summary['exit_code'], 1)
            self.assertEqual(summary['results'][0]['diagnostics'], ['✖ synthetic failure'])
        console.flush()
        self.assertIn('✖ synthetic failure', buffer.getvalue().decode('utf-8'))

    def test_docs_and_website_do_not_select_application(self):
        self.assertEqual(select_packs(["docs/user/WORKFLOW.md"])["packs"], ["docs"])
        self.assertEqual(select_packs(["website/src/pages/index.astro"])["packs"], ["docs", "website"])

    def test_unknown_paths_and_shared_infrastructure_expand(self):
        for path in ("new-boundary.py", "uv.lock", "tests/e2e/helpers.mjs", "JSON_SCHEMA.md"):
            with self.subTest(path=path):
                self.assertTrue(ALL_MERGE.issubset(select_packs([path])["packs"]))
        self.assertTrue(ALL_MERGE.issubset(select_packs([])["packs"]))

    def test_media_changes_preserve_real_long_fixture(self):
        plan = select_packs(["maw/reapeaks.py"])
        self.assertTrue({"common", "media", "long-media", "smoke"}.issubset(plan["packs"]))

    def test_tool_regression_change_does_not_select_application(self):
        self.assertEqual(select_packs(["tests/test_docs_check.py"])["packs"], ["docs", "tools"])

    def test_leaf_browser_change_selects_consumers_and_shared_change_expands(self):
        leaf = select_packs(["web/launcher/modules/provider-memory.js"])
        self.assertIn("e2e", leaf["packs"])
        self.assertNotIn("editor-e2e", leaf["packs"])
        self.assertTrue(all(Path(path).name.startswith("launcher-") for path in leaf["e2e_specs"]))
        for path in ("web/editor/state/editor-state.js", "web/editor/unknown-module.js"):
            self.assertIn("editor-e2e", select_packs([path])["packs"])

    def test_export_and_gap_keep_the_mixed_waveform_consumer(self):
        consumer = "tests/e2e/waveform-history.spec.mjs"
        for path in ("web/editor/io/editor-export-timeline.js", "web/editor/ui/editor-export-menus.js", "web/shared/gap-remove-core.js"):
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertTrue("editor-e2e" in plan["packs"] or consumer in plan["e2e_specs"])

    def test_every_discovered_case_belongs_to_exactly_one_pack(self):
        def normalize(name):
            return name.removeprefix("tests.")
        discovered = [normalize(case.id()) for case in run_tests.cases(
            run_tests.build_suite([], str(ROOT / "tests"), "test_*.py"))]
        assigned = [normalize(case.id()) for pack in PYTHON_PACKS
                    for case in run_tests.cases(run_tests.pack_suite(pack))]
        self.assertEqual(len(assigned), len(set(assigned)), "packs must not duplicate cases")
        self.assertEqual(set(discovered), set(assigned), "pack routing must not drop inherited/dynamic tests")

    def test_required_skip_fails_instead_of_green(self):
        class MissingDependency(unittest.TestCase):
            def test_dependency(self):
                self.skipTest("numpy is required")
        with patch.object(run_tests, "build_suite", side_effect=lambda *_: unittest.defaultTestLoader.loadTestsFromTestCase(MissingDependency)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_tests.main(["--required"]), 1)
                self.assertEqual(run_tests.main([]), 0)

    def test_dynamic_discovery_is_loaded_and_its_change_broadens(self):
        area = ROOT / ".artifacts/dynamic-test-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            source = root / "tests/test_dynamic.py"
            source.write_text("# tests are produced by a factory\n", encoding="utf-8")
            case = type("DynamicCase", (unittest.TestCase,), {
                "__module__": "tests.test_dynamic", "test_boundary": lambda self: None})
            loaded = unittest.defaultTestLoader.loadTestsFromTestCase(case)
            with patch.object(run_tests, "ROOT", root), patch.object(unittest.TestLoader, "loadTestsFromName", return_value=loaded):
                self.assertEqual([test.id() for test in run_tests.cases(run_tests.pack_suite("common"))],
                                 ["tests.test_dynamic.DynamicCase.test_boundary"])
            with patch.object(test_policy, "__file__", str(root / "scripts/test_policy.py")):
                self.assertTrue(ALL_MERGE.issubset(select_packs(["tests/test_dynamic.py"])["packs"]))


if __name__ == "__main__":
    unittest.main()
