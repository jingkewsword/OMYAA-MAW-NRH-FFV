"""Failure inventory from actual result reports, including failed commands."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.test_result_details import collect_failures


class ResultDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = {'exit_code': 1, 'command': ['python', 'scripts/run_tests.py', '--required'], 'log': 'full-output.log'}

    def write_json(self, gate, value):
        (self.root / f'{gate}.json').write_text(json.dumps(value), encoding='utf-8')

    def test_python_collects_all_and_permitted_skip(self):
        long_error = 'traceback-' * 3000
        self.write_json('python-selected', {'run': 4, 'selected_ids': ['a', 'b', 'c', 'd'],
            'failures': 1, 'errors': 1, 'expected_failures': 0, 'unexpected_successes': 0,
            'skips': [{'id': 'c', 'reason': 'not available', 'platform_not_applicable': False},
                      {'id': 'd', 'reason': 'platform', 'platform_not_applicable': True}],
            'failure_details': [{'id': 'a', 'kind': 'failure', 'traceback': long_error},
                                {'id': 'b', 'kind': 'error', 'traceback': 'full traceback b'}],
            'full_log': 'python-full.log'})
        result = collect_failures('python-selected', self.root, self.result)
        self.assertTrue(result['complete'], result)
        self.assertEqual({f['id'] for f in result['failures']}, {'a', 'b', 'c'})
        self.assertEqual(next(f for f in result['failures'] if f['id'] == 'a')['error'], long_error)
        self.assertEqual(result['report_errors'], [])

    def test_missing_counts_only_and_inconsistent_reports_are_incomplete(self):
        result = collect_failures('python-selected', self.root, self.result)
        self.assertFalse(result['complete'])
        self.assertTrue(result['report_errors'])
        self.write_json('python-selected', {'run': 2, 'selected_ids': ['a', 'b'], 'failures': 2, 'errors': 0,
            'skips': [], 'expected_failures': 0, 'unexpected_successes': 0, 'full_log': 'python-full.log'})
        result = collect_failures('python-selected', self.root, self.result)
        self.assertFalse(result['complete'])
        self.assertIn('python-full.log', str(result['report_errors']))
        self.write_json('python-selected', {'run': 2, 'selected_ids': ['a', 'b'], 'failures': 2, 'errors': 0,
            'skips': [], 'expected_failures': 0, 'unexpected_successes': 0,
            'failure_details': [{'id': 'a', 'kind': 'failure', 'traceback': 'broken'}]})
        self.assertFalse(collect_failures('python-selected', self.root, self.result)['complete'])

    @unittest.skipUnless(shutil.which('node'), 'Node required for real JUnit format')
    def test_actual_node_junit_multiple_failures_and_skip(self):
        source = self.root / 'sample.mjs'
        source.write_text("import {test} from 'node:test';\ntest('first',()=>{throw Error('first-detail')});\ntest('second',()=>{throw Error('second-detail')});\ntest.skip('third',()=>{});\n", encoding='utf-8')
        report = self.root / 'node-selected.xml'
        done = subprocess.run(['node', '--test', '--test-reporter=junit', f'--test-reporter-destination={report}', str(source)], capture_output=True)
        self.assertNotEqual(done.returncode, 0)
        result = collect_failures('node-selected', self.root, {'exit_code': done.returncode, 'command': ['node', '--test'], 'log': 'node-output.log'})
        self.assertTrue(result['complete'], result)
        self.assertEqual(len(result['failures']), 3)
        self.assertIn('first-detail', str(result['failures']))
        self.assertIn('second-detail', str(result['failures']))
        self.assertIn('third', str(result['failures']))

    def test_browser_retries_global_errors_missing_result_and_skip(self):
        def case(name, status, results, annotations=()):
            return {'title': name, 'file': 'example.spec.mjs', 'line': 10,
                    'tests': [{'projectName': 'chromium', 'expectedStatus': 'passed', 'status': status,
                               'annotations': list(annotations), 'results': results}]}
        report = {'suites': [{'title': 'example.spec.mjs', 'line': 0, 'specs': [
            case('failed', 'unexpected', [{'status': 'failed', 'retry': 0, 'errors': [{'message': 'failure details'}]}]),
            case('retried', 'flaky', [{'status': 'failed', 'retry': 0, 'errors': [{'message': 'first attempt'}]}, {'status': 'passed', 'retry': 1, 'errors': []}]),
            case('skipped', 'skipped', [{'status': 'skipped', 'retry': 0, 'errors': []}], [{'type': 'skip', 'description': 'missing codec'}]),
            case('not-run', 'unexpected', [])]}], 'errors': [{'message': 'global worker failure'}],
            'stats': {'expected': 0, 'unexpected': 2, 'skipped': 1, 'flaky': 1}}
        self.write_json('browser-regressions', report)
        result = collect_failures('browser-regressions', self.root, {'exit_code': 1, 'command': ['node', 'node_modules/@playwright/test/cli.js', 'test'], 'log': 'browser.log'})
        self.assertEqual(len(result['failures']), 5, result)
        self.assertFalse(result['complete'])  # A listed test has no result.
        for text in ('failure details', 'first attempt', 'missing codec', 'not-run', 'global worker failure'):
            self.assertIn(text, str(result))

    def test_all_python_ids_are_preserved_without_truncation(self):
        ids = [f'test_{i}' for i in range(300)]
        self.write_json('python-selected', {'run': len(ids), 'selected_ids': ids, 'failures': len(ids), 'errors': 0,
            'skips': [], 'expected_failures': 0, 'unexpected_successes': 0,
            'failure_details': [{'id': name, 'kind': 'failure', 'traceback': name + '-trace'} for name in ids]})
        result = collect_failures('python-selected', self.root, self.result)
        self.assertTrue(result['complete'], result)
        self.assertEqual([f['id'] for f in result['failures']], ids)
        self.assertEqual(result['failures'][-1]['error'], 'test_299-trace')

    def test_browser_discovery_reports_all_missing_ids(self):
        from tests.test_browser_results import fixture
        listed, actual = fixture()
        for name in ('missing-1', 'missing-2'):
            other = dict(listed['suites'][0]['specs'][0])
            other['title'] = name
            listed['suites'][0]['specs'].append(other)
        self.write_json('browser-regressions-list', listed)
        self.write_json('browser-regressions', actual)
        result = collect_failures('browser-regressions', self.root, {'exit_code': 0,
            'command': ['node', 'node_modules/@playwright/test/cli.js', 'test'], 'log': 'browser.log'})
        self.assertFalse(result['complete'])
        self.assertIn('missing-1', str(result['report_errors']))
        self.assertIn('missing-2', str(result['report_errors']))

    def test_node_bad_counts_and_python_expected_outcomes(self):
        (self.root / 'node-selected.xml').write_text('<testsuites tests="2" failures="2"><testcase name="one"><failure message="x">trace</failure></testcase></testsuites>', encoding='utf-8')
        result = collect_failures('node-selected', self.root, {'exit_code': 1, 'command': ['node', '--test'], 'log': 'node.log'})
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['report_errors']), 2)
        self.write_json('python-selected', {'run': 2, 'selected_ids': ['a', 'b'], 'failures': 0, 'errors': 0,
            'skips': [], 'expected_failures': 1, 'unexpected_successes': 1,
            'failure_details': [{'id': 'a', 'kind': 'expected_failure', 'traceback': 'original trace'},
                                {'id': 'b', 'kind': 'unexpected_success', 'traceback': ''}]})
        result = collect_failures('python-selected', self.root, self.result)
        self.assertTrue(result['complete'], result)
        self.assertEqual({f['id'] for f in result['failures']}, {'a', 'b'})

    def test_timeout_with_partial_failure_report_is_incomplete(self):
        self.write_json('python-selected', {'run': 1, 'selected_ids': ['a'], 'failures': 1, 'errors': 0,
            'skips': [], 'expected_failures': 0, 'unexpected_successes': 0,
            'failure_details': [{'id': 'a', 'kind': 'failure', 'traceback': 'partial trace'}]})
        result = collect_failures('python-selected', self.root, {**self.result, 'status': 'timeout', 'exit_code': 124})
        self.assertFalse(result['complete'])
        self.assertEqual({f['id'] for f in result['failures']}, {'a', 'python-selected'})
        self.assertIn('remaining cases', str(result['report_errors']))

    def test_nonzero_process_without_failure_does_not_look_complete(self):
        self.write_json('python-selected', {'run': 1, 'selected_ids': ['a'], 'failures': 0, 'errors': 0,
            'skips': [], 'expected_failures': 0, 'unexpected_successes': 0, 'failure_details': []})
        result = collect_failures('python-selected', self.root, self.result)
        self.assertFalse(result['complete'])
        self.assertEqual(result['failures'][0]['log'], 'full-output.log')

    def test_non_test_failure_has_full_log_and_invalid_test_report_is_error(self):
        result = collect_failures('build', self.root, {'exit_code': 3, 'command': ['node', 'scripts/build-editor.mjs'], 'log': 'build-output.log'})
        self.assertTrue(result['complete'])
        self.assertEqual(result['failures'][0]['log'], 'build-output.log')
        lint = collect_failures('python-lint', self.root, {'exit_code': 1, 'command': ['python', '-m', 'ruff', 'check'], 'log': 'lint.log'})
        self.assertTrue(lint['complete'])
        self.assertEqual(lint['failures'][0]['log'], 'lint.log')
        (self.root / 'node-selected.xml').write_text('<broken', encoding='utf-8')
        result = collect_failures('node-selected', self.root, {'exit_code': 1, 'command': ['node', '--test'], 'log': 'node-output.log'})
        self.assertFalse(result['complete'])
        self.assertTrue(result['report_errors'])
