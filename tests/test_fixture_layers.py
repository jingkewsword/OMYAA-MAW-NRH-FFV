from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock

from scripts.test_policy import python_pack


class ExplicitTestGroupTests(unittest.TestCase):
    def test_media_generation_is_partitioned_without_losing_original_cases(self):
        from tests import test_reapeaks_fixture as fixtures
        suite = unittest.defaultTestLoader.loadTestsFromModule(fixtures)
        ids = [case.id() for group in suite for case in group]
        generated = {identity.rsplit('.', 1)[-1]: python_pack(identity)
                     for identity in ids if '_generated_matches_fixture' in identity}
        self.assertEqual(generated, {'test_tone30_generated_matches_fixture': 'long-media',
                                    'test_tone_dual_generated_matches_fixture': 'media',
                                    'test_tone_48k_generated_matches_fixture': 'media'})
        self.assertEqual(sum('_generated_matches_fixture' in identity for identity in ids), 3)
        self.assertEqual(len(ids), len(set(ids)))

    def test_checksum_discovery_does_not_start_bash_but_execution_probes_it(self):
        spec = importlib.util.spec_from_file_location('checksum_fixture_probe', Path(__file__).resolve().parents[1] / 'tests/test_verify_sha256_script.py')
        module = importlib.util.module_from_spec(spec)
        with mock.patch('shutil.which', return_value='bash'), \
                mock.patch('subprocess.run', side_effect=AssertionError('discovery must not start Bash')):
            spec.loader.exec_module(module)
            self.assertGreater(unittest.defaultTestLoader.loadTestsFromModule(module).countTestCases(), 0)
        with mock.patch.object(module, 'usable_bash', return_value=None) as probe:
            with self.assertRaises(unittest.SkipTest):
                module.VerifySha256ScriptTests.setUpClass()
            probe.assert_called_once()


if __name__ == '__main__':
    unittest.main()
