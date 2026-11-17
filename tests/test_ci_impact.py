"""Trust and output contracts for GitHub change selection."""
import unittest
import subprocess
from unittest.mock import patch

from scripts import ci_impact


class GitHubDiffTests(unittest.TestCase):
    base = "a" * 40
    head = "b" * 40

    def fake_git(self, *args):
        if args == ("rev-parse", "HEAD"):
            return self.head.encode()
        if args == ("rev-parse", "HEAD^1"):
            return self.base.encode()
        if "--diff-filter=D" in args:
            return b""
        if args[0] == "diff":
            return b"README.md\0maw/example.py\0"
        raise AssertionError(args)

    @patch("scripts.ci_impact.git")
    def test_pull_request_checks_merge_parent_and_preserves_union(self, git):
        git.side_effect = self.fake_git
        env = {"GITHUB_EVENT_NAME": "pull_request", "PR_BASE_SHA": self.base, "GITHUB_SHA": self.head}
        self.assertEqual(ci_impact.event_paths(env)[:2], (["README.md", "maw/example.py"], False))
        env["PR_BASE_SHA"] = "c" * 40
        self.assertTrue(ci_impact.event_paths(env)[1])

    @patch("scripts.ci_impact.subprocess.run")
    @patch("scripts.ci_impact.git")
    def test_push_requires_ancestor_and_matching_checkout(self, git, run):
        git.side_effect = self.fake_git
        env = {"GITHUB_EVENT_NAME": "push", "PUSH_BEFORE_SHA": self.base, "GITHUB_SHA": self.head}
        self.assertEqual(ci_impact.event_paths(env)[:2], (["README.md", "maw/example.py"], False))
        run.assert_called_once()
        env["GITHUB_SHA"] = "c" * 40
        self.assertTrue(ci_impact.event_paths(env)[1])
        env["PUSH_BEFORE_SHA"] = "0" * 40
        self.assertTrue(ci_impact.event_paths(env)[1])

    @patch("scripts.ci_impact.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git"))
    @patch("scripts.ci_impact.git")
    def test_non_ancestor_push_is_not_trusted(self, git, _run):
        git.side_effect = self.fake_git
        env = {"GITHUB_EVENT_NAME": "push", "PUSH_BEFORE_SHA": self.base, "GITHUB_SHA": self.head}
        self.assertTrue(ci_impact.event_paths(env)[1])

    @patch("scripts.ci_impact.git")
    def test_deleted_paths_reach_selector(self, git):
        def deleted(*args):
            return b"removed.py\0" if args[0] == "diff" else self.fake_git(*args)
        git.side_effect = deleted
        env = {"GITHUB_EVENT_NAME": "pull_request", "PR_BASE_SHA": self.base, "GITHUB_SHA": self.head}
        self.assertEqual(ci_impact.event_paths(env)[:2], (["removed.py"], False))

    def test_unsupported_event_falls_back(self):
        self.assertTrue(ci_impact.event_paths({"GITHUB_EVENT_NAME": "workflow_dispatch"})[1])

    def test_selected_outputs_do_not_expand_empty_layers(self):
        plan = {"mode": "targeted", "packs": ["docs"], "python_tests": ["tests/test_docs_check.py"],
                "node_tests": [], "e2e_specs": [], "preparation": {
                    "application": False, "real_media": False, "preview_windows": False, "lint": False}}
        output = ci_impact.outputs(plan)
        self.assertEqual(output["python"], "true")
        self.assertEqual(output["docs"], "true")
        self.assertEqual(output["browser"], "false")
        self.assertEqual(output["preview_windows"], "false")

    @patch("scripts.ci_impact.git", return_value=b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    @patch("scripts.ci_impact.event_paths", return_value=(["some-change"], False, "trusted", "a" * 40))
    @patch("scripts.ci_impact.select_packs")
    def test_existing_platform_checks_are_intersections(self, select, _paths, _git):
        select.return_value = {"mode": "targeted", "packs": ["docs"],
                               "python_tests": ["tests/test_docs_check.py", "tests/test_project_io.py"],
                               "node_tests": ["tests/test_e2e_process_lifecycle.mjs", "tests/test_editor_state.mjs"],
                               "e2e_specs": [], "preparation": {"application": False, "real_media": False,
                                                                 "preview_windows": False, "lint": False}}
        plan = ci_impact.create_plan({"GITHUB_EVENT_NAME": "pull_request"})
        self.assertEqual(plan["ci_platforms"]["existing_ubuntu_python"], ["tests/test_docs_check.py"])
        self.assertEqual(plan["ci_platforms"]["existing_windows_node"], ["tests/test_e2e_process_lifecycle.mjs"])
        self.assertEqual(ci_impact.outputs(plan)["windows_node"], "true")
        select.assert_called_once_with(["some-change"], release=False, base_ref="a" * 40)

    @patch("scripts.ci_impact.git", return_value=b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    @patch("scripts.ci_impact.event_paths", return_value=(["some-change"], False, "trusted", "a" * 40))
    @patch("scripts.ci_impact.select_packs")
    def test_push_retains_only_existing_windows_python_subset(self, select, _paths, _git):
        select.return_value = {"mode": "targeted", "packs": ["docs"],
                               "python_tests": ["tests/test_docs_check.py", "tests/test_project_io.py"],
                               "node_tests": [], "e2e_specs": [],
                               "preparation": {"application": False, "real_media": False,
                                               "preview_windows": False, "lint": False}}
        plan = ci_impact.create_plan({"GITHUB_EVENT_NAME": "push"})
        self.assertEqual(plan["ci_platforms"]["existing_windows_python"], ["tests/test_docs_check.py"])
        self.assertEqual(ci_impact.outputs(plan)["windows_python"], "true")
        self.assertEqual(plan["ci_platforms"]["existing_ubuntu_python"], [])


if __name__ == "__main__":
    unittest.main()
