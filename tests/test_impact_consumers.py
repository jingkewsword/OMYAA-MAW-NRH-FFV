import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import local_test_impact as impact


class ConsumerSelectionTests(unittest.TestCase):
    def test_python_source_has_real_consumers_and_mixed_docs(self):
        plan = impact.select_packs(['maw/project_tracks.py', 'CHANGELOG.md'])
        self.assertEqual(plan['mode'], 'targeted')
        self.assertIn('tests/test_project_tracks.py', plan['python_tests'])
        self.assertIn('tests/test_speaker_project_migration.mjs', plan['node_tests'])
        self.assertIn('tests/e2e/speaker-identity-project.spec.mjs', plan['e2e_specs'])
        self.assertIn('docs', plan['packs'])
        self.assertIn('tests/test_release_notes.py', plan['python_tests'])

    def test_fixture_and_helper_reach_consumers(self):
        plan = impact.select_packs(['tests/fixtures/project-tracks/canonical.json'])
        self.assertIn('tests/test_python_track_output.py', plan['python_tests'])
        helper = impact.select_packs(['tests/helpers/editor-module-loader.mjs'])
        self.assertIn('tests/test_editor_utils.mjs', helper['node_tests'])
        self.assertIn('tests/e2e/ass-cue-position.spec.mjs', helper['e2e_specs'])

    def test_web_dynamic_consumers_and_deleted_domain(self):
        for path in ['web/editor/cues/editor-color-filter.js']:
            plan = impact.select_packs([path])
            self.assertEqual(plan['mode'], 'targeted')
            self.assertIn('tests/test_editor_cues_imports.mjs', plan['node_tests'])
            self.assertIn('tests/e2e/cue-color-filter.spec.mjs', plan['e2e_specs'])
            self.assertNotIn('tests/e2e/launcher-zoom.spec.mjs', plan['e2e_specs'])
            self.assertTrue(plan['preparation']['application'])
        deleted = impact.select_packs(['web/editor/cues/deleted-example.js'])
        self.assertIn('tests/test_editor_cues_imports.mjs', deleted['node_tests'])
        self.assertIn('tests/e2e/unified-tracks.spec.mjs', deleted['e2e_specs'])
        self.assertEqual(impact.select_packs(['missing.py'])['mode'], 'full')

    def test_transitive_import_and_deleted_source_in_small_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, source in {
                'maw/leaf.py': 'VALUE = 1\n',
                'maw/service.py': 'from maw.leaf import VALUE\n',
                'tests/test_service.py': 'from maw.service import VALUE\n',
                'tests/test_unrelated.py': 'VALUE = 2\n',
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding='utf-8')
            with mock.patch.object(impact, '__file__', str(root / 'scripts/local_test_impact.py')):
                plan = impact.select_packs(['maw/leaf.py'])
                self.assertIn('tests/test_service.py', plan['python_tests'])
                self.assertNotIn('tests/test_unrelated.py', plan['python_tests'])
                (root / 'maw/leaf.py').unlink()
                deleted = impact.select_packs(['maw/leaf.py'])
                self.assertIn('tests/test_service.py', deleted['python_tests'])
                self.assertNotIn('tests/test_unrelated.py', deleted['python_tests'])

    def test_manifest_and_website_prerequisite(self):
        manifest = impact.select_packs(['web/editor-scripts.txt'])
        self.assertEqual(manifest['mode'], 'targeted')
        self.assertIn('tests/test_editor_bundle.mjs', manifest['node_tests'])
        self.assertIn('tests/e2e/editor-bundle.spec.mjs', manifest['e2e_specs'])
        self.assertTrue(manifest['preparation']['application'])
        retirement = impact.select_packs(['tests/e2e/editor-entry-retirement.spec.mjs'])
        self.assertIn('website', retirement['packs'])

    def test_mixed_unknown_dynamic_python_is_not_hidden_by_docs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'maw').mkdir()
            (root / 'tests').mkdir()
            (root / 'maw/new_module.py').write_text('VALUE = 1\n', encoding='utf-8')
            (root / 'tests/test_other.py').write_text('# dynamic loader\n', encoding='utf-8')
            (root / 'CHANGELOG.md').write_text('# Changes\n', encoding='utf-8')
            with mock.patch.object(impact, '__file__', str(root / 'scripts/local_test_impact.py')):
                plan = impact.select_packs(['maw/new_module.py', 'CHANGELOG.md'])
                self.assertIn('tests/test_other.py', plan['python_tests'])
                self.assertIn('docs', plan['packs'])
                self.assertTrue(any('dynamic loading' in reason for reason in plan['reasons']))

    def test_website_sync_does_not_need_app_build(self):
        plan = impact.select_packs(['website/scripts/sync-maw-docs.mjs'])
        self.assertIn('website', plan['packs'])
        self.assertIn('tests/test_readme_content_sync.mjs', plan['node_tests'])
        self.assertFalse(plan['preparation']['application'])
        self.assertFalse(plan['preparation']['preview_windows'])

    def test_multiline_relative_package_import_and_syntax_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, source in {
                'maw/__init__.py': 'VALUE = 1\n',
                'maw/leaf.py': 'from . import (\n    VALUE,\n)\n',
                'tests/test_leaf.py': 'from maw.leaf import VALUE\n',
                'tests/test_other.py': '# independent\n',
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding='utf-8')
            with mock.patch.object(impact, '__file__', str(root / 'scripts/local_test_impact.py')):
                plan = impact.select_packs(['maw/__init__.py'])
                self.assertIn('tests/test_leaf.py', plan['python_tests'])
                self.assertNotIn('tests/test_other.py', plan['python_tests'])
                (root / 'maw/leaf.py').write_text('from (broken\n', encoding='utf-8')
                plan = impact.select_packs(['maw/__init__.py'])
                self.assertIn('tests/test_other.py', plan['python_tests'])
                self.assertTrue(any('invalid graph input' in reason for reason in plan['reasons']))

    def test_governance_and_package_change_classification(self):
        plan = impact.select_packs(['.github/workflows/python-lint.yml'])
        self.assertEqual(plan['mode'], 'targeted')
        self.assertTrue(plan['preparation']['lint'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'tests').mkdir()
            (root / 'tests/test_local_test_workflow.py').write_text('# selection contract\n', encoding='utf-8')
            (root / 'package.json').write_text(json.dumps({'scripts': {'test': 'new'}, 'engines': {'node': '22'}}), encoding='utf-8')
            old = mock.Mock(stdout=json.dumps({'scripts': {'test': 'old'}, 'engines': {'node': '22'}}).encode())
            with mock.patch.object(impact, '__file__', str(root / 'scripts/local_test_impact.py')), \
                 mock.patch.object(impact.subprocess, 'run', return_value=old):
                self.assertEqual(impact.select_packs(['package.json'], base_ref='base')['mode'], 'targeted')
                old.stdout = json.dumps({'scripts': {'test': 'old'}, 'engines': {'node': '20'}}).encode()
                self.assertEqual(impact.select_packs(['package.json'], base_ref='base')['mode'], 'full')

    def test_media_preparation_follows_selected_tests(self):
        for path in ('tests/test_media.py', 'tests/test_ffmpeg.py', 'tests/test_ffprobe_failure_integration.py'):
            self.assertTrue(impact.select_packs([path])['preparation']['real_media'], path)
        docs = impact.select_packs(['CHANGELOG.md'])['preparation']
        self.assertFalse(docs['real_media'])
        self.assertFalse(docs['python_dependencies'])

    def test_windows_build_and_workflow_literal_consumers(self):
        windows = impact.select_packs(['scripts/build-windows.ps1'])
        self.assertTrue(windows['preparation']['preview_windows'])
        workflow = impact.select_packs(['.github/workflows/editor-checks.yml'])
        self.assertIn('tests/test_browser_evidence_workflow.mjs', workflow['node_tests'])
        self.assertEqual(workflow['mode'], 'targeted')
        docs = impact.select_packs(['CHANGELOG.md'])
        self.assertFalse(docs['preparation']['preview_windows'])

    def test_thumbnail_server_and_real_document_consumer(self):
        plan = impact.select_packs(['maw/thumbnail_jobs.py'])
        self.assertIn('tests/e2e/filmstrip-real.spec.mjs', plan['e2e_specs'])
        readme = impact.select_packs(['README.md'])
        self.assertNotIn('tests/test_local_models.py', readme['python_tests'])
        self.assertNotIn('tests/e2e/tool-markdown.spec.mjs', readme['e2e_specs'])
        changelog = impact.select_packs(['CHANGELOG.md'])
        self.assertIn('tests/e2e/tool-pages.spec.mjs', changelog['e2e_specs'])
        self.assertNotIn('tests/e2e/changelog-write-lock.spec.mjs', changelog['e2e_specs'])

    def test_log_attachment_stays_with_document_consumers(self):
        for path in ('docs/logs/1.8.0-beta.1/2026-10-09/first-verification/parts/00-head.html',
                     'docs/logs/unversioned/2026-10-11/feedback/MAW 2.0 新版本核对-img-261009_232150.webp'):
            plan = impact.select_packs([path])
            self.assertEqual(plan['mode'], 'targeted')
            self.assertIn('docs', plan['packs'])
            self.assertFalse(plan['preparation']['preview_windows'])
            self.assertFalse(plan['preparation']['real_media'])

    def test_tool_docs_generator_runs_freshness_consumer(self):
        plan = impact.select_packs(['scripts/build-tool-docs.mjs'])
        self.assertIn('docs', plan['packs'])
        self.assertIn('tests/test_tool_markdown.mjs', plan['node_tests'])
        self.assertEqual(plan['mode'], 'targeted')

    def test_rooted_log_fixture_read_across_lines(self):
        path = 'docs/logs/1.8.0-beta.1/2026-10-09/first-verification/maw-verification-v1.8.0b1-to-main.html'
        plan = impact.select_packs([path])
        self.assertIn('tests/test_verification_checklist.py', plan['python_tests'])
        self.assertEqual(plan['mode'], 'targeted')
        readme = impact.select_packs(['README.md'])
        self.assertNotIn('tests/test_local_models.py', readme['python_tests'])
        self.assertNotIn('tests/e2e/tool-markdown.spec.mjs', readme['e2e_specs'])
        self.assertFalse(readme['preparation']['application'])

    def test_site_document_mirrors_follow_document_consumers(self):
        mirrors = ['website/src/pages/docs/development.md',
                   'website/src/pages/docs/documentation-index.md']
        for paths in (mirrors, ['docs/engineering/DEVELOPMENT.md', 'docs/INDEX.md', *mirrors]):
            plan = impact.select_packs(paths)
            self.assertEqual(plan['mode'], 'targeted')
            self.assertIn('docs', plan['packs'])
            self.assertIn('website', plan['packs'])
            self.assertFalse(plan['preparation']['application'])
            self.assertFalse(plan['preparation']['preview_windows'])
        contract = impact.select_packs(['website/src/pages/docs/json-schema.md'])
        self.assertIn('tests/test_project_contract.py', contract['python_tests'])
        self.assertIn('tests/e2e/project-boundary.spec.mjs', contract['e2e_specs'])
        self.assertEqual(impact.select_packs([*mirrors, 'pnpm-lock.yaml'])['mode'], 'full')

    def test_release_is_full(self):
        self.assertEqual(impact.select_packs(['CHANGELOG.md'], release=True)['mode'], 'full')
