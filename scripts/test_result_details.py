"""Extract full failure inventories from this repository's three test reports."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    from .browser_results import PORTABLE_SKIPS, collection, config_identity
except ImportError:
    from browser_results import PORTABLE_SKIPS, collection, config_identity


def _kind(gate: str, result: dict) -> str:
    command = [str(arg).replace('\\', '/') for arg in result.get('command', [])]
    if command:
        if any(arg.endswith('scripts/run_tests.py') for arg in command):
            return 'python'
        if '--test' in command:
            return 'node'
        if any('@playwright/test/cli.js' in arg for arg in command):
            return 'browser'
        return 'command'
    if gate.startswith('python-') and gate != 'python-lint' or gate == 'launcher-kernel':
        return 'python'
    if gate.startswith('node-') or gate == 'editor-kernel':
        return 'node'
    if gate in {'browser-regressions', 'editor-http-smoke'}:
        return 'browser'
    return 'command'


def _record(identity, kind, reason, error='', *, location=None, log=None):
    return {'id': identity, 'kind': kind, 'reason': reason, 'error': error,
            'location': location, 'log': log}


def _python(report: dict, result: dict, failures: list, issues: list):
    log = report.get('full_log') or result.get('log')
    counts = {}
    for field in ('run', 'failures', 'errors', 'expected_failures', 'unexpected_successes'):
        value = report.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(f'Python report has invalid {field}: {value!r}; full log: {log}')
            value = 0
        counts[field] = value
    selected = report.get('selected_ids')
    if not isinstance(selected, list) or any(not isinstance(item, str) or not item for item in selected):
        issues.append(f'Python report has invalid selected_ids; full log: {log}')
    elif len(selected) != counts['run']:
        issues.append(f'Python selected {len(selected)} cases but ran {counts["run"]}; full log: {log}')
    details = report.get('failure_details', [])
    if not isinstance(details, list):
        issues.append(f'Python failure_details is not a list; full log: {log}')
        details = []
    detail_counts = {key: 0 for key in ('failure', 'error', 'expected_failure', 'unexpected_success')}
    required = '--required' in [str(item) for item in result.get('command', [])]
    for item in details:
        if not isinstance(item, dict) or item.get('kind') not in detail_counts or not isinstance(item.get('id'), str) or not item['id']:
            issues.append(f'Invalid Python failure detail: {item!r}; full log: {log}')
            continue
        kind, identity = item['kind'], item['id']
        trace = item.get('traceback')
        if not isinstance(trace, str):
            issues.append(f'Python failure {identity} lacks a traceback string; full log: {log}')
            trace = ''
        if kind != 'unexpected_success' and not trace:
            issues.append(f'Python failure {identity} has an empty traceback; full log: {log}')
        detail_counts[kind] += 1
        if kind != 'expected_failure' or required:
            failures.append(_record(identity, kind, kind.replace('_', ' '), trace, log=log))
    for kind, field in (('failure', 'failures'), ('error', 'errors'),
                        ('expected_failure', 'expected_failures'), ('unexpected_success', 'unexpected_successes')):
        if detail_counts[kind] != counts[field]:
            issues.append(f'Python {field} count {counts[field]} differs from {detail_counts[kind]} detailed entries; full log: {log}')
    skips = report.get('skips')
    if not isinstance(skips, list):
        issues.append(f'Python report has invalid skips; full log: {log}')
        skips = []
    for skip in skips:
        if not isinstance(skip, dict) or not isinstance(skip.get('id'), str) or not isinstance(skip.get('reason'), str) or not isinstance(skip.get('platform_not_applicable'), bool):
            issues.append(f'Invalid Python skip: {skip!r}; full log: {log}')
        elif required and not skip['platform_not_applicable']:
            failures.append(_record(skip['id'], 'skip', skip['reason'], log=log))


def _node(root: ET.Element, result: dict, failures: list, issues: list):
    log = result.get('log')
    cases = root.findall('.//testcase')
    if root.tag not in {'testsuites', 'testsuite'} or not cases:
        issues.append(f'Node JUnit report has no test cases or invalid root; full log: {log}')
    observed = {'tests': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0}
    for case in cases:
        name = case.get('name')
        if not name:
            issues.append(f'Node JUnit testcase lacks a name; full log: {log}')
            continue
        file = case.get('file')
        identity = f'{file}::{name}' if file else name
        outcomes = [child for child in case if child.tag in {'failure', 'error', 'skipped'}]
        if not outcomes and case.get('failure'):
            outcomes = [case]
        for tag, field in (('failure', 'failures'), ('error', 'errors'), ('skipped', 'skipped')):
            if any(item.tag == tag or tag == 'failure' and item.tag == 'testcase' for item in outcomes):
                observed[field] += 1
        for item in outcomes:
            kind = item.tag if item.tag != 'testcase' else 'failure'
            reason = item.get('message') or item.get('type') or case.get('failure') or kind
            error = ''.join(item.itertext()).strip()
            failures.append(_record(identity, kind, reason, error, location=file, log=log))
    for field, count in observed.items():
        if field in root.attrib:
            try:
                declared = int(root.attrib[field])
            except ValueError:
                issues.append(f'Invalid Node JUnit {field} count {root.attrib[field]!r}; full log: {log}')
            else:
                if declared != count:
                    issues.append(f'Node JUnit {field} count {declared} differs from {count} observed; full log: {log}')


def _browser(report: dict, result: dict, failures: list, issues: list):
    log = result.get('log')
    global_errors = report.get('errors', [])
    if not isinstance(global_errors, list):
        issues.append(f'Browser global errors is not a list; full log: {log}')
        global_errors = []
    for index, error in enumerate(global_errors, 1):
        failures.append(_record(f'<global:{index}>', 'error', 'browser runner error', error, log=log))
    suites = report.get('suites')
    if not isinstance(suites, list):
        issues.append(f'Browser suites is not a list; full log: {log}')
        return
    counts = {'expected': 0, 'unexpected': 0, 'skipped': 0, 'flaky': 0}
    seen = set()

    def walk(items, parents=()):
        if not isinstance(items, list):
            issues.append(f'Browser nested suites is not a list; full log: {log}')
            return
        for suite in items:
            if not isinstance(suite, dict):
                issues.append(f'Invalid browser suite: {suite!r}; full log: {log}')
                continue
            title = suite.get('title', '')
            titles = parents + ((title,) if parents or suite.get('line', 0) else ())
            specs = suite.get('specs', [])
            if not isinstance(specs, list):
                issues.append(f'Invalid browser specs in {title!r}; full log: {log}')
                specs = []
            for spec in specs:
                if not isinstance(spec, dict) or not isinstance(spec.get('tests'), list):
                    issues.append(f'Invalid browser spec: {spec!r}; full log: {log}')
                    continue
                file, spec_title = spec.get('file'), spec.get('title')
                if not isinstance(file, str) or not file or not isinstance(spec_title, str) or not spec_title:
                    issues.append(f'Browser spec lacks file/title: {spec!r}; full log: {log}')
                    continue
                title_parts = titles + (spec_title,)
                for test in spec['tests']:
                    if not isinstance(test, dict):
                        issues.append(f'Invalid browser test in {file}: {test!r}; full log: {log}')
                        continue
                    project = test.get('projectName')
                    identity = f'{file}::{" > ".join(title_parts)} [{project}]'
                    if identity in seen:
                        issues.append(f'Duplicate browser test {identity}; full log: {log}')
                    seen.add(identity)
                    status = test.get('status')
                    if status not in counts:
                        issues.append(f'Invalid browser status for {identity}: {status!r}; full log: {log}')
                    else:
                        counts[status] += 1
                    results = test.get('results')
                    if not isinstance(results, list):
                        issues.append(f'Browser test has invalid results: {identity}; full log: {log}')
                        results = []
                    annotations = test.get('annotations', [])
                    if not isinstance(annotations, list) or any(not isinstance(a, dict) for a in annotations):
                        issues.append(f'Browser test has invalid annotations: {identity}; full log: {log}')
                        annotations = []
                    reasons = []
                    if not results:
                        reasons.append('missing result')
                        issues.append(f'Browser test has no result: {identity}; full log: {log}')
                    if len(results) > 1 or any(isinstance(r, dict) and r.get('retry') != 0 for r in results):
                        reasons.append('retry or multiple attempts')
                    attempt_errors = []
                    for attempt in results:
                        if not isinstance(attempt, dict) or attempt.get('status') not in {'passed', 'failed', 'timedOut', 'skipped', 'interrupted'}:
                            issues.append(f'Invalid browser attempt for {identity}: {attempt!r}; full log: {log}')
                            reasons.append('invalid attempt')
                            continue
                        if attempt['status'] not in {'passed', 'skipped'}:
                            reasons.append(attempt['status'])
                        errors = attempt.get('errors', [])
                        if not isinstance(errors, list):
                            issues.append(f'Invalid attempt errors for {identity}; full log: {log}')
                        else:
                            attempt_errors.extend(errors)
                    skipped = any(isinstance(r, dict) and r.get('status') == 'skipped' for r in results)
                    skip_reasons = [a.get('description', '') for a in annotations if a.get('type') == 'skip']
                    allowed = ((file, title_parts) in PORTABLE_SKIPS
                               and skip_reasons == [PORTABLE_SKIPS[(file, title_parts)]]
                               and status == 'skipped' and test.get('expectedStatus') == 'skipped')
                    if skipped and not allowed:
                        reasons.append('unsupported skip: ' + ', '.join(skip_reasons))
                    if test.get('expectedStatus') == 'skipped' and not skipped:
                        reasons.append('expected skip did not produce a skipped result')
                    if status == 'skipped' and not skipped:
                        issues.append(f'Browser skipped status has no skipped attempt: {identity}; full log: {log}')
                        reasons.append('inconsistent skipped status')
                    if test.get('expectedStatus') not in {'passed', 'skipped'} or any(a.get('type') in {'fail', 'fixme'} for a in annotations):
                        reasons.append('expected failure or fixme is not coverage')
                    if status in {'unexpected', 'flaky'}:
                        reasons.append(status)
                    if attempt_errors and not reasons:
                        reasons.append('attempt reported errors')
                    if reasons:
                        failures.append(_record(identity, 'browser', '; '.join(dict.fromkeys(reasons)), attempt_errors,
                                                location={'file': file, 'line': spec.get('line'), 'column': spec.get('column')}, log=log))
            walk(suite.get('suites', []), titles)

    walk(suites)
    if not seen:
        issues.append(f'Browser report has no test cases; full log: {log}')
    stats = report.get('stats')
    if not isinstance(stats, dict):
        issues.append(f'Browser report has invalid stats; full log: {log}')
    else:
        for key, count in counts.items():
            if stats.get(key) != count:
                issues.append(f'Browser {key} count {stats.get(key)!r} differs from {count} observed; full log: {log}')


def _compare_browser_listing(report_dir: Path, gate: str, report: dict, issues: list, log):
    """When discovery exists, preserve all missing/extra IDs and config errors."""
    listing_path = report_dir / f'{gate}-list.json'
    if not listing_path.exists():
        return
    try:
        listing = json.loads(listing_path.read_text(encoding='utf-8'))
        expected, actual = collection(listing), collection(report)
        for key in sorted(expected.keys() - actual.keys()):
            issues.append(f'Browser discovery case missing from execution: {key}; full log: {log}')
        for key in sorted(actual.keys() - expected.keys()):
            issues.append(f'Unexpected browser execution case: {key}; full log: {log}')
        if config_identity(listing) != config_identity(report):
            issues.append(f'Browser discovery/runtime config mismatch; full log: {log}')
        if listing.get('config', {}).get('shard') != report.get('config', {}).get('shard'):
            issues.append(f'Browser discovery/runtime shard mismatch; full log: {log}')
        if listing.get('errors'):
            issues.append(f'Browser discovery reported errors: {listing["errors"]!r}; full log: {log}')
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        issues.append(f'Cannot validate browser discovery {listing_path}: {error}; full log: {log}')


def collect_failures(gate: str, report_dir: Path, result: dict) -> dict:
    """Return every available failure and explicit evidence gaps for one gate."""
    failures, issues = [], []
    kind = _kind(gate, result)
    log = result.get('log')
    process_code = result.get('process_exit_code', result.get('exit_code'))
    interrupted = result.get('status') in {'timeout', 'interrupted', 'launch-error'}
    if kind == 'command':
        if process_code != 0:
            failures.append(_record(gate, 'command', f'command {result.get("status", "completed")}; exit {process_code}', log=log))
            if not log:
                issues.append('Command failed without a full output log')
        return {'failures': failures, 'report_errors': issues, 'complete': not issues}
    report_path = Path(report_dir) / f'{gate}.{ "xml" if kind == "node" else "json"}'
    try:
        if kind == 'node':
            _node(ET.parse(report_path).getroot(), result, failures, issues)
        else:
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if not isinstance(report, dict):
                raise ValueError('report root is not an object')
            (_python if kind == 'python' else _browser)(report, result, failures, issues)
            if kind == 'browser':
                _compare_browser_listing(Path(report_dir), gate, report, issues, log)
    except (OSError, ValueError, TypeError, ET.ParseError, json.JSONDecodeError) as error:
        issues.append(f'Cannot read {kind} report {report_path}: {error}; full log: {log}')
    if interrupted:
        issues.append(f'Test process {result["status"]}; remaining cases may not have run; full log: {log}')
        failures.append(_record(gate, 'process', f'test process {result["status"]}', log=log))
    if process_code != 0 and not failures:
        failures.append(_record(gate, 'process', f'test process exited {process_code}', log=log))
        issues.append(f'Test process failed without an identified failing case; full log: {log}')
    impossible_success = (kind in {'python', 'node'} and any(f['kind'] in {'failure', 'error', 'unexpected_success'} for f in failures)
                          or kind == 'browser' and any(f['kind'] == 'error' or 'unexpected' in f['reason'] for f in failures))
    if process_code == 0 and impossible_success:
        issues.append(f'Test process exited 0 despite reported failures; full log: {log}')
    if result.get('status') in {'invalid-required-report', 'invalid-discovery'}:
        message = f'Gate report validation failed: {result.get("error", "unknown reason")}; full log: {log}'
        issues.append(message)
        if not failures:
            failures.append(_record(gate, 'report', message, log=log))
    return {'failures': failures, 'report_errors': issues, 'complete': not issues}
