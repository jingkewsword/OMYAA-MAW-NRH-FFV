"""Local selector coverage for real 2.0 consumers and fail-closed diff handling."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import local_test_impact as impact, test_workflow as workflow


class LocalSelectionTests(unittest.TestCase):
    def test_checklist_documents_and_independent_specs(self):
        plan = impact.select_packs(["tools/verification-checklist/build.py"])
        self.assertEqual(plan["tools_scope"], "checklist")
        self.assertEqual(set(plan["e2e_specs"]), set(impact.CHECKLIST_SPECS))
        self.assertIn("tests/test_verification_checklist.py", plan["python_tests"])
        for path in ("tests/e2e/unified-tracks.spec.mjs", "tests/e2e/v2-migration-save.spec.mjs"):
            self.assertIn(path, impact.select_packs([path])["e2e_specs"])
        plan = impact.select_packs(["README.md", "tests/e2e/unified-tracks.spec.mjs"])
        self.assertEqual(plan["mode"], "targeted")
        self.assertIn("website", plan["packs"])
        self.assertIn("tests/e2e/unified-tracks.spec.mjs", plan["e2e_specs"])
        self.assertEqual(impact.select_packs(["README.md"], release=True)["mode"], "full")
        self.assertEqual(impact.select_packs(["../README.md"])["mode"], "full")

    def test_dynamic_load_tests_expands_python_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tests").mkdir()
            (root / "tests/test_dynamic.py").write_text("def load_tests(loader, tests, pattern): return tests\n")
            (root / "tests/test_another.py").write_text("# a separate test\n")
            with mock.patch.object(impact, "__file__", str(root / "scripts/local_test_impact.py")):
                plan = impact.select_packs(["tests/test_dynamic.py"])
                self.assertEqual(plan["mode"], "targeted")
                self.assertIn("tests/test_another.py", plan["python_tests"])
                self.assertEqual(plan["e2e_specs"], [])

    def test_changed_paths_collects_staged_unstaged_untracked_and_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.name", "Local Test")
            git("config", "user.email", "local@example.invalid")
            for name in ("staged", "unstaged"):
                (root / name).write_text("before")
            git("add", "staged", "unstaged")
            git("commit", "-qm", "base")
            (root / "staged").write_text("after")
            git("add", "staged")
            (root / "unstaged").write_text("after")
            (root / "untracked").write_text("new")
            with mock.patch.object(workflow, "ROOT", root):
                self.assertEqual(workflow.changed_paths(None), ["staged", "unstaged", "untracked"])
                self.assertEqual(workflow.changed_paths("HEAD"), [])
                git("commit", "-qm", "change")
                self.assertEqual(workflow.changed_paths("HEAD^"), ["staged"])
                git("rm", "staged")
                (root / "staged").write_text("recreated outside the index")
                self.assertEqual(workflow.changed_paths(None, deleted_only=True), ["staged"])
                with self.assertRaises(subprocess.CalledProcessError):
                    workflow.changed_paths("missing-base")

    def test_release_refuses_partial_and_browser_runs_shard_validation(self):
        with self.assertRaises(SystemExit) as result:
            workflow.main(["--stage", "release", "--pack", "media", "--plan-only"])
        self.assertEqual(result.exception.code, 2)
        steps = list(workflow.commands(["editor-e2e"], Path("reports")))
        browser = next(command for name, command, _ in steps if name == "browser-regressions")
        self.assertIn("--shard=1/1", browser)
        self.assertIn("--retries=0", browser)


if __name__ == "__main__":
    unittest.main()
