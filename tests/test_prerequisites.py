import tempfile
import unittest
from pathlib import Path

from scripts.test_prerequisites import prerequisites


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def test_python_actual_transitive_imports_and_fake_source(self):
        self.write('tests/test_stdlib.py', 'import unittest\nexample = "import numpy; import requests"\n')
        self.write('tests/test_math.py', 'from sample.helper import use\n')
        self.write('sample/helper.py', 'import numpy\nfrom PIL import Image\nimport requests\n')
        pure = prerequisites(['python', 'scripts/run_tests.py', '--required', 'tests/test_stdlib.py'], self.root)
        third_party = prerequisites(['python', 'scripts/run_tests.py', '--required', 'tests/test_math.py'], self.root)
        self.assertEqual(pure, set())
        self.assertEqual(third_party, {'python-dependencies'})

    def test_node_transitive_and_browser_spec_boundaries(self):
        self.write('tests/test_governance.mjs', "import test from 'node:test'; import fs from 'fs';")
        self.write('tests/test_feature.mjs', "import './helpers/feature.mjs';")
        self.write('tests/helpers/feature.mjs', "import { build } from 'esbuild';")
        pure = prerequisites(['node', '--test', 'tests/test_governance.mjs'], self.root)
        external = prerequisites(['node', '--test', 'tests/test_feature.mjs'], self.root)
        self.assertEqual(pure, set())
        self.assertEqual(external, {'node-dependencies'})
        self.write('tests/e2e/tool-pages.spec.mjs', "import {test} from '@playwright/test';")
        self.write('tests/e2e/media.spec.mjs', "import {test} from '@playwright/test'; startServer(); execFileSync('ffmpeg', []);")
        base = ['node', 'node_modules/@playwright/test/cli.js', 'test']
        self.assertEqual(prerequisites(base + ['tests/e2e/tool-pages.spec.mjs'], self.root), {'node-dependencies', 'chromium'})
        self.assertEqual(prerequisites(base + ['tests/e2e/media.spec.mjs'], self.root), {'node-dependencies', 'chromium', 'build', 'ffmpeg'})

    def test_real_repository_files(self):
        root = Path(__file__).resolve().parents[1]
        pure = prerequisites(['node', '--test', 'tests/test_browser_evidence_workflow.mjs'], root)
        self.assertNotIn('node-dependencies', pure)
        self.assertNotIn('build', pure)
        self.assertEqual(prerequisites(['python', 'scripts/run_tests.py', 'tests/test_result_details.py'], root), set())
        self.assertEqual(prerequisites(['python', 'scripts/run_tests.py', 'tests/test_run_tests_runner.py'], root), set())
        self.assertNotIn('ffmpeg', prerequisites(['python', 'scripts/run_tests.py', 'tests/test_prerequisites.py'], root))
        raster = prerequisites(['node', '--test', 'tests/test_editor_utils.mjs'], root)
        self.assertIn('node-dependencies', raster)
        self.assertNotIn('build', raster)
        browser = prerequisites(['node', '--test', 'tests/test_shared_tooltip_browser.mjs'], root)
        self.assertIn('chromium', browser)
        app = prerequisites(['node', 'node_modules/@playwright/test/cli.js', 'test', 'tests/e2e/filmstrip-real.spec.mjs'], root)
        self.assertTrue({'build', 'ffmpeg', 'chromium', 'node-dependencies', 'python-dependencies'}.issubset(app))
        self.assertNotIn('python-dependencies', pure)
        media = prerequisites(['python', 'scripts/run_tests.py', 'tests/test_ffprobe_failure_integration.py'], root)
        self.assertIn('ffmpeg', media)
        oracle = prerequisites(['python', 'scripts/run_tests.py', 'tests/test_ass_stacking_pixel_oracle.py'], root)
        self.assertIn('ffmpeg', oracle)

    def test_build_requires_repository_bundle_not_temp_fixture(self):
        self.write('tests/test_temp.py', "import tempfile\nfrom pathlib import Path\ndef sample():\n    root = Path(tempfile.mkdtemp())\n    bundle = root / 'web/editor/boot/editor-bundle.js'\n    bundle.write_text('fixture')\n")
        self.write('tests/test_repo.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\ndef sample():\n    bundle = ROOT / 'web/editor/boot/editor-bundle.js'\n    return bundle.read_text()\n")
        self.write('tests/test_temp.mjs', "import {mkdtempSync} from 'node:fs'; const root = mkdtempSync('fixture'); const path = root + '/web/editor/boot/editor-bundle.js';")
        self.write('tests/test_repo.mjs', "const root = fileURLToPath(new URL('../', import.meta.url)); const artifact = path.join(root, 'web/editor/boot/editor-bundle.js');")
        for name in ('tests/test_temp.py', 'tests/test_temp.mjs'):
            cmd = ['python', 'scripts/run_tests.py', name] if name.endswith('.py') else ['node', '--test', name]
            self.assertNotIn('build', prerequisites(cmd, self.root), name)
        for name in ('tests/test_repo.py', 'tests/test_repo.mjs'):
            cmd = ['python', 'scripts/run_tests.py', name] if name.endswith('.py') else ['node', '--test', name]
            self.assertIn('build', prerequisites(cmd, self.root), name)
        repo = Path(__file__).resolve().parents[1]
        for name in ('tests/test_editor_manifest.py', 'tests/test_web_build.py'):
            self.assertNotIn('build', prerequisites(['python', 'scripts/run_tests.py', name], repo), name)
        self.assertNotIn('build', prerequisites(['node', '--test', 'tests/test_web_build_artifact.mjs'], repo))
        for name in ('tests/test_editor_bundle.mjs', 'tests/test_launcher_bundle.mjs'):
            needed = prerequisites(['node', '--test', name], repo)
            self.assertIn('build', needed, name)
            self.assertIn('node-dependencies', needed, name)
        self.assertIn('build', prerequisites(['python', 'scripts/run_tests.py', 'tests/test_editor_assets.py'], repo))

    def test_unknown_full_python_group_is_conservative(self):
        plan = prerequisites(['python', 'scripts/run_tests.py', '--required', '--report', 'run.json'], self.root)
        self.assertTrue({'python-dependencies', 'ffmpeg', 'build'}.issubset(plan))
