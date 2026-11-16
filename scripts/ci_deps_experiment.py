"""Temporary CI experiment: record command timing and preserve native exit status."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

root = Path('.artifacts/deps-experiment')
root.mkdir(parents=True, exist_ok=True)
name, *command = sys.argv[1:]
if name == 'experiment-start':
    (root / 'experiment-start.json').write_text(json.dumps({'start_utc': datetime.now(timezone.utc).isoformat(), 'monotonic': time.monotonic()}), encoding='utf-8')
    sys.exit(0)
if name == 'experiment-end':
    start_path = root / 'experiment-start.json'
    start = json.loads(start_path.read_text(encoding='utf-8')) if start_path.exists() else {}
    start['end_utc'] = datetime.now(timezone.utc).isoformat()
    start['seconds'] = round(time.monotonic() - start['monotonic'], 3) if 'monotonic' in start else None
    start['scope'] = 'after checkout through tests, excludes artifact upload and action post steps'
    (root / 'experiment-total.json').write_text(json.dumps(start, indent=2), encoding='utf-8')
    sys.exit(0)
started = datetime.now(timezone.utc).isoformat()
clock = time.monotonic()
code = 1
try:
    code = subprocess.call(command)
finally:
    record = {'stage': name, 'command': command, 'start_utc': started,
              'end_utc': datetime.now(timezone.utc).isoformat(),
              'seconds': round(time.monotonic() - clock, 3), 'exit_code': code,
              'sha': os.getenv('GITHUB_SHA'), 'run_id': os.getenv('GITHUB_RUN_ID')}
    (root / f'{name}.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
sys.exit(code)
