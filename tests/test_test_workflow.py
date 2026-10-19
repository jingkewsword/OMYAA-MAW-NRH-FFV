"""Selection must broaden safely and never lose a test or conceal a skip."""
from __future__ import annotations

import contextlib
import io
import json
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
        for path in (*test_policy.SITE_TOOL_PATHS, "docs/releases/1.9.0.md", "docs/assets/1.9.0/example.webp"):
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertEqual(plan["packs"], ["docs", "website"])
                self.assertFalse(plan["preview"])
                self.assertEqual(test_workflow.preparation(plan["packs"]),
                                 {"application": False, "real_media": False})
        steps = list(test_workflow.commands(["website"], ROOT / ".artifacts"))
        self.assertEqual([name for name, _, _ in steps], ["website-docs", "website-releases", "website-build"])
        self.assertIn("website/scripts/sync-maw-docs.mjs", steps[0][1])
        self.assertEqual(steps[1][1][1:], ["scripts/build_release_site.py", "--preview"])
        self.assertEqual(steps[2][1][-3:], ["--dir", "website", "build"])
        self.assertIn("website", select_packs([], release=True)["packs"])

    def test_unknown_paths_and_shared_infrastructure_expand(self):
        for path in ("new-boundary.py", "uv.lock", "tests/e2e/helpers.mjs", "JSON_SCHEMA.md"):
            with self.subTest(path=path):
                self.assertTrue(ALL_MERGE.issubset(select_packs([path])["packs"]))
        self.assertTrue(ALL_MERGE.issubset(select_packs([])["packs"]))

    def test_media_changes_preserve_real_long_fixture(self):
        plan = select_packs(["maw/quapeaks.py"])
        self.assertTrue({"common", "media", "long-media", "smoke"}.issubset(plan["packs"]))

    def test_ffprobe_failure_layers_run_for_media_changes_and_release(self):
        ids = test_policy.source_test_ids(ROOT / "tests/test_ffprobe_failure_integration.py")
        self.assertEqual({test_policy.python_pack(name) for name in ids}, {"media"})
        for method in ("test_probe_process_failures_return_unknown_information",
                       "test_probe_invalid_json_returns_unknown_information"):
            self.assertEqual(test_policy.python_pack(f"test_media.MediaResolutionTests.{method}"), "common")
        for path in ("maw/media.py", "maw/ffmpeg.py", "maw/project_io.py", "server-editor/serve.py",
                     ".github/workflows/release.yml", "tests/test_ffprobe_failure_integration.py"):
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertIn("media", plan["packs"])
                self.assertTrue(test_workflow.preparation(plan["packs"])["real_media"])
                command = next(cmd for gate, cmd, _ in test_workflow.commands(
                    plan["packs"], ROOT / ".artifacts") if gate == "python-media")
                self.assertIn("--required", command)
        release = select_packs(["README.md"], release=True)
        self.assertIn("media", release["packs"])
        self.assertIn("python-media", [gate for gate, _, _ in test_workflow.commands(release["packs"], ROOT / ".artifacts")])
        self.assertNotIn("media", select_packs(["README.md"])["packs"])

    def test_tool_regression_change_does_not_select_application(self):
        for path in test_policy.DOC_TOOL_PATHS:
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertEqual(plan["packs"], ["docs", "website"] if path in test_policy.SITE_TOOL_PATHS else ["docs"])
                self.assertFalse(plan["preview"])
                commands = list(test_workflow.commands(plan["packs"], ROOT / ".artifacts"))
                self.assertEqual([name for name, _, _ in commands if not name.startswith("website-")],
                                 ["docs-navigation", "release-docs", "docs-regressions"])
                regressions = next(command for name, command, _ in commands if name == "docs-regressions")
                for module in ("tests.test_docs_check", "tests.test_release_notes", "tests.test_release_site", "tests.test_release_publication"):
                    self.assertIn(module, regressions)
        tool_ids = {case.id() for case in run_tests.cases(run_tests.pack_suite("tools"))}
        for module in ("test_verification_checklist", "test_verification_checklist_build"):
            with self.subTest(checklist_module=module):
                expected = {case.id() for case in run_tests.cases(
                    run_tests.build_suite([f"tests.{module}"], str(ROOT / "tests"), "test_*.py"))}
                self.assertTrue(expected)
                self.assertTrue(expected.issubset(tool_ids), "tool-only changes must run Markdown/HTML regressions")
                plan = select_packs([f"tests/{module}.py"])
                self.assertEqual(plan["packs"], ["docs", "tools"])
                self.assertFalse(plan["preview"])
        for path in ("scripts/check_docs_extra.py", "tools/filmstrip-lab/backend.py", "tools/unknown/check.py"):
            with self.subTest(unknown_tool=path):
                self.assertTrue(ALL_MERGE.issubset(select_packs([path])["packs"]))
        self.assertIn("media", select_packs(["scripts/check_docs.py", "maw/quapeaks.py"])["packs"])

    def test_spec_selection_unions_changes_and_broadens_shared_boundaries(self):
        spec = "tests/e2e/keyboard-timing.spec.mjs"
        other = "tests/e2e/shared-tooltip.spec.mjs"
        plan = select_packs([spec])
        self.assertEqual(plan["packs"], ["docs", "e2e"])
        self.assertEqual(plan["e2e_specs"], [spec])
        self.assertFalse(plan["preview"])
        self.assertEqual(select_packs([spec, other])["e2e_specs"], sorted([spec, other]))
        self.assertEqual(select_packs([spec, "scripts/check_docs.py"])["e2e_specs"], [spec])
        leaf = select_packs(["web/shared/tooltip.js"])
        mixed = select_packs([spec, "web/shared/tooltip.js"])
        self.assertEqual(set(mixed["e2e_specs"]), set(leaf["e2e_specs"]) | {spec})
        self.assertTrue(set(leaf["packs"]).issubset(mixed["packs"]))
        for shared in ("web/editor/state/editor-state.js", "uv.lock", "tests/e2e/helpers.mjs"):
            with self.subTest(shared=shared):
                widened = select_packs([spec, shared])
                self.assertIn("editor-e2e", widened["packs"])
                self.assertNotIn("e2e", widened["packs"])
                self.assertEqual(widened["e2e_specs"], [])
        renamed = select_packs(["tests/e2e/deleted-old-name.spec.mjs", spec])
        self.assertIn("editor-e2e", renamed["packs"])
        self.assertEqual(renamed["e2e_specs"], [])

    def test_checklist_source_keeps_its_real_browser_consumer(self):
        spec = "tests/e2e/verification-checklist.spec.mjs"
        for path in ("tools/verification-checklist/build.py",
                     "tools/verification-checklist/templates/verification-checklist.html",
                     "tools/verification-checklist/examples/checklist.json"):
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertEqual(plan["packs"], ["docs", "e2e", "tools"])
                self.assertEqual(plan["e2e_specs"], [spec])
                self.assertFalse(plan["preview"])
        mixed = select_packs(["tools/verification-checklist/build.py", "tests/e2e/shared-tooltip.spec.mjs"])
        self.assertEqual(mixed["e2e_specs"], sorted([spec, "tests/e2e/shared-tooltip.spec.mjs"]))
        shared = select_packs(["tools/verification-checklist/build.py", "uv.lock"])
        self.assertTrue(ALL_MERGE.issubset(shared["packs"]))
        self.assertEqual(shared["e2e_specs"], [])

    def test_export_menu_keeps_new_focus_and_spacing_consumer(self):
        for path in ("web/editor/ui/editor-export-menus.js", "web/editor/io/editor-export-timeline.js"):
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertIn("tests/e2e/editor-menu-focus.spec.mjs", plan["e2e_specs"])
                self.assertIn("tests/e2e/waveform-history.spec.mjs", plan["e2e_specs"])
                self.assertIn("tests/e2e/burn-video-jobs.spec.mjs", plan["e2e_specs"])
                self.assertIn("tests/e2e/editor-help-srt-burn.spec.mjs", plan["e2e_specs"])
                self.assertNotIn("editor-e2e", plan["packs"])

    def test_checklist_preparation_keeps_consumers_and_omits_unrelated_builds(self):
        paths = ["tools/verification-checklist/templates/verification-checklist.html",
                 "tests/test_verification_checklist.py", "tests/test_verification_checklist_build.py",
                 "tests/test_verification_checklist.mjs", test_policy.CHECKLIST_SPEC]
        for path in paths:
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertEqual(plan["tools_scope"], "checklist")
                steps = list(test_workflow.commands(plan["packs"], ROOT / ".artifacts",
                    specs=plan["e2e_specs"], tools_scope=plan["tools_scope"]))
                names = [name for name, _, _ in steps]
                self.assertFalse({"build", "build-launcher", "typecheck", "python-lint"}.intersection(names))
                self.assertEqual(test_workflow.preparation(plan["packs"], plan["e2e_specs"], "checklist"),
                                 {"application": False, "real_media": False})
                if "tools" in plan["packs"]:
                    python = next(cmd for name, cmd, _ in steps if name == "python-tools")
                    self.assertTrue(set(test_policy.CHECKLIST_PYTHON).issubset(python))
                    self.assertNotIn("--pack", python)
                    node = next(cmd for name, cmd, _ in steps if name == "node-tools")
                    self.assertEqual([arg for arg in node if arg.endswith('.mjs')], [test_policy.CHECKLIST_NODE])
                    self.assertIn("docs-regressions", names)
                if "e2e" in plan["packs"]:
                    self.assertIn("browser-regressions", names)
                    self.assertEqual(next(cmd for name, cmd, _ in steps if name == "browser-regressions")[-1],
                                     test_policy.CHECKLIST_SPEC)

    def test_checklist_mixed_unknown_and_release_scopes_broaden(self):
        source = "tools/verification-checklist/build.py"
        for path in ("tests/test_type_gate.mjs", "tests/e2e/shared-tooltip.spec.mjs", "uv.lock",
                     "AGENTS.md", "JSON_SCHEMA.md", "tools/verification-checklist/../unknown.py", "unknown.py"):
            with self.subTest(path=path):
                plan = select_packs([source, path])
                # An unrelated browser consumer also restores the full tools pack.
                scope = plan["tools_scope"]
                self.assertEqual(scope, "all")
                self.assertTrue(test_workflow.preparation(plan["packs"], plan["e2e_specs"], scope)["application"])
        release = select_packs([source], release=True)
        self.assertEqual(release.get("tools_scope", "all"), "all")
        self.assertTrue(test_workflow.preparation(release["packs"])["real_media"])
        for specs in ([], [test_policy.CHECKLIST_SPEC, "tests/e2e/shared-tooltip.spec.mjs"]):
            self.assertEqual(test_workflow.preparation(["e2e"], specs),
                             {"application": True, "real_media": True})
        full = list(test_workflow.commands(["tools"], ROOT / ".artifacts"))
        self.assertIn("typecheck", [name for name, _, _ in full])
        self.assertIn("--pack", next(cmd for name, cmd, _ in full if name == "python-tools"))

    def test_checklist_ci_handoff_retains_scope_and_preparation(self):
        from scripts.check_test_gate import check_gate
        area = ROOT / ".artifacts/selection-output-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as directory:
            output = Path(directory) / "outputs.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(test_workflow.main(["--stage", "merge", "--changed",
                    "tools/verification-checklist/build.py", "--plan-only", "--github-output", str(output)]), 0)
            values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
            self.assertEqual(values["app"], "true", "the required job must still execute")
            self.assertEqual(values["tools_scope"], "checklist")
            self.assertEqual(values["application"], "false")
            self.assertEqual(values["real_media"], "false")
            jobs = {"selection": {"result": "success", "outputs": values},
                    "documentation": {"result": "success"}, "editor": {"result": "success"}}
            self.assertEqual(check_gate(jobs), [])
            for key, value in (("tools_scope", ""), ("real_media", "true"), ("application", "true")):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    check_gate({**jobs, "selection": {"result": "success", "outputs": {**values, key: value}}})
            with contextlib.redirect_stdout(io.StringIO()), patch.object(test_workflow, "execute") as execute:
                self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", "tools", "--pack", "e2e",
                    "--tools-scope", values["tools_scope"], "--e2e-specs", values["e2e_specs"], "--plan-only"]), 0)
                execute.assert_not_called()

    def test_referenced_or_exported_spec_cannot_hide_consumers(self):
        area = ROOT / ".artifacts/spec-selection-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=area) as directory:
            root = Path(directory)
            spec = root / "tests/e2e/leaf.spec.mjs"
            spec.parent.mkdir(parents=True)
            spec.write_text("// independent test module\n", encoding="utf-8")
            with patch.object(test_policy, "__file__", str(root / "scripts/test_policy.py")):
                self.assertEqual(select_packs(["tests/e2e/leaf.spec.mjs"])["packs"], ["docs", "e2e"])
                consumer = root / "tests/helpers/nested/consumer.mjs"
                consumer.parent.mkdir(parents=True)
                consumer.write_text("import '../../e2e/leaf.spec.mjs';\n", encoding="utf-8")
                self.assertTrue(ALL_MERGE.issubset(select_packs(["tests/e2e/leaf.spec.mjs"])["packs"]))
                consumer.write_text("// no dependency\n", encoding="utf-8")
                for shared in ("export const shared = {};\n", "const local = 1; export {local};\n"):
                    spec.write_text(shared, encoding="utf-8")
                    self.assertTrue(ALL_MERGE.issubset(select_packs(["tests/e2e/leaf.spec.mjs"])["packs"]))
                spec.write_text("// independent test module\n", encoding="utf-8")
                (root / "tests/test_consumer.mjs").write_text("import './e2e/leaf.spec.mjs';\n", encoding="utf-8")
                self.assertTrue(ALL_MERGE.issubset(select_packs(["tests/e2e/leaf.spec.mjs"])["packs"]))

    def test_spec_plan_survives_ci_output_and_explicit_pack_handoff(self):
        area = ROOT / ".artifacts/selection-output-fixtures"
        area.mkdir(parents=True, exist_ok=True)
        spec = "tests/e2e/shared-tooltip.spec.mjs"
        with tempfile.TemporaryDirectory(dir=area) as directory:
            output = Path(directory) / "outputs.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(test_workflow.main(["--stage", "merge", "--changed", spec,
                    "--plan-only", "--github-output", str(output)]), 0)
            values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
            self.assertEqual(values["app"], "true")
            self.assertEqual(values["e2e"], "true")
            self.assertEqual(values["editor_e2e"], "false")
            self.assertEqual(values["preview"], "false")
            self.assertEqual(json.loads(values["e2e_specs"]), [spec])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(test_workflow.main(["--stage", "merge", "--pack", "e2e",
                    "--e2e-specs", values["e2e_specs"], "--plan-only"]), 0)
            command = next(command for name, command, _ in test_workflow.commands(
                ["e2e"], Path(directory), specs=json.loads(values["e2e_specs"])) if name == "browser-regressions")
            self.assertEqual(command[-1], spec)

    def test_new_thumbnail_media_and_waveform_consumers_are_owned(self):
        for path, expected in (("tests/test_thumbnail_jobs_integration.py", {"media"}),
                               ("tests/test_thumbnail_server.py", {"media"}),
                               ("tests/test_thumbnails.py", {"common", "media"}),
                               ("tests/test_thumbnail_jobs.py", {"common"})):
            with self.subTest(path=path):
                self.assertEqual({test_policy.python_pack(name) for name in test_policy.source_test_ids(ROOT / path)}, expected)
        plan = select_packs(["web/editor/media/waveform/render.js"])
        self.assertIn("tests/e2e/filmstrip.spec.mjs", plan["e2e_specs"])
        self.assertIn("tests/e2e/filmstrip-real.spec.mjs", plan["e2e_specs"])
        self.assertNotIn("long-media", select_packs(["maw/thumbnails.py"])["packs"])

    def test_leaf_browser_change_selects_consumers_and_shared_change_expands(self):
        leaf = select_packs(["web/launcher/modules/provider-memory.js"])
        self.assertIn("e2e", leaf["packs"])
        self.assertNotIn("editor-e2e", leaf["packs"])
        self.assertTrue(all(Path(path).name.startswith("launcher-") for path in leaf["e2e_specs"]))
        for path in ("web/editor/io/editor-sticker-burn-plan.js", "web/shared/utils/sticker-placement.js",
                     "web/editor/io/editor-wiring-burn-video.js"):
            with self.subTest(path=path):
                plan = select_packs([path])
                self.assertIn("e2e", plan["packs"])
                self.assertNotIn("editor-e2e", plan["packs"])
                self.assertTrue({"tests/e2e/burn-video-jobs.spec.mjs", "tests/e2e/editor-help-srt-burn.spec.mjs",
                                 "tests/e2e/ass-export.spec.mjs"}.issubset(plan["e2e_specs"]))
        for path in ("web/editor/state/editor-state.js", "web/editor/unknown-module.js"):
            self.assertIn("editor-e2e", select_packs([path])["packs"])

    def test_real_codec_classes_keep_media_preparation_and_pure_contracts_stay_common(self):
        for module, real_class in (
            ("test_burn_video_export", "BurnVideoPrecisionTests"),
            ("test_media_keyframes", "RealKeyframeInspectorTests"),
            ("test_gap_removed_embedded_subtitles", "EmbeddedSubtitleTimelineTests"),
            ("test_gap_removed_video_timeline", "RealVideoTimelineTests"),
        ):
            path = f"tests/{module}.py"
            with self.subTest(module=module):
                ids = test_policy.source_test_ids(ROOT / path)
                real = [name for name in ids if real_class in name.split(".")]
                pure = [name for name in ids if real_class not in name.split(".")]
                self.assertTrue(real)
                self.assertTrue(pure)
                self.assertEqual({test_policy.python_pack(name) for name in real}, {"media"})
                self.assertEqual({test_policy.python_pack(name) for name in pure}, {"common"})
                plan = select_packs([path])
                self.assertTrue({"common", "media", "smoke"}.issubset(plan["packs"]))
                self.assertTrue(test_workflow.preparation(plan["packs"])["real_media"])
        for method in ("test_ass_frame_render_uses_real_libass_when_available",
                       "test_green_screen_frame_uses_playhead_time_with_real_libass"):
            with self.subTest(method=method):
                self.assertEqual(test_policy.python_pack(f"tests.test_local_editor_server.LocalEditorServerTests.{method}"), "media")
        self.assertEqual(test_policy.python_pack(
            "tests.test_local_editor_server.LocalEditorServerTests.test_ass_frame_endpoint_returns_base64_png_and_warnings"), "common")
        recording = test_policy.source_test_ids(ROOT / "tests/test_script_recording_workflow.py")
        self.assertEqual({test_policy.python_pack(name) for name in recording}, {"common", "media"})
        self.assertIn("media", select_packs(["tests/test_script_recording_workflow.py"])["packs"])
        for path in ("maw/editor_burn.py", "maw/media_keyframes.py", "maw/media_export_video.py"):
            with self.subTest(source=path):
                self.assertIn("media", select_packs([path])["packs"])

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
                with tempfile.TemporaryDirectory() as directory, \
                        patch.object(run_tests, "_run_parallel", side_effect=AssertionError("required must keep its gate")), \
                        patch.object(run_tests, "pack_suite", side_effect=lambda *_: unittest.defaultTestLoader.loadTestsFromTestCase(MissingDependency)):
                    report = Path(directory) / "required.json"
                    for selection in ([], ["--pack", "common"]):
                        self.assertEqual(run_tests.main(["--required", "--parallel", "2", "--report", str(report), *selection]), 1)
                        result = json.loads(report.read_text(encoding="utf-8"))
                        self.assertEqual(result["exit_code"], 1)
                        self.assertFalse(result["skips"][0]["platform_not_applicable"])

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
