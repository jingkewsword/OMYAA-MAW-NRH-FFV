"""Selection must broaden safely and never lose a test or conceal a skip."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import run_tests
from scripts.test_policy import ALL_MERGE, PYTHON_PACKS, select_packs


class TestWorkflowTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
