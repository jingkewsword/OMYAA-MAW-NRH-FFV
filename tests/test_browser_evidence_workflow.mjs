import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const workflow = readFileSync(new URL('../.github/workflows/editor-checks.yml', import.meta.url), 'utf8');
const job = name => workflow.split(`\n  ${name}:\n`)[1]?.split(/\n  [a-z][a-z-]*:\n/)[0];

test('selected browser shards preserve outcomes even when a shard fails', () => {
  const browser = job('browser');
  assert.ok(browser);
  assert.match(browser, /fail-fast: false/);
  assert.match(browser, /--layer browser --shard '\$\{\{ matrix\.shard \}\}\/\$\{\{ matrix\.total \}\}'/);
  assert.match(browser, /name: Preserve browser shard evidence\n\s+if: \$\{\{ always\(\) \}\}/);
  assert.match(browser, /name: selected-browser-\$\{\{ matrix\.shard \}\}/);
  assert.match(browser, /\.artifacts\/ci-browser\//);
  assert.match(browser, /test-results\//);
});

test('aggregate gate validates every selected browser shard', () => {
  const gate = job('browser-gate');
  assert.ok(gate);
  assert.match(gate, /needs: \[selection, browser\]/);
  assert.match(gate, /needs\.browser\.result != 'success'/);
  assert.match(gate, /pattern: selected-browser-\*/);
  assert.match(gate, /scripts\/ci_matrix\.py gate --total/);
  assert.match(job('editor'), /needs: \[selection, editor-tests, browser-gate/);
});

test('unrelated browser preparation failures do not suppress shard discovery', () => {
  const browser = job('browser');
  const chromium = browser.split('      - name: Install Chromium\n')[1].split('\n      - ')[0];
  assert.match(chromium, /!cancelled\(\).*steps\.js_install\.outcome == 'success'/);
  const run = browser.split('      - name: Discover and run selected browser shard\n')[1].split('\n      - ')[0];
  const condition = run.match(/if: \$\{\{ (.*?) \}\}/)[1];
  assert.match(condition, /steps\.chromium\.outcome == 'success'/);
  assert.doesNotMatch(condition, /steps\.(py_install|build|ffmpeg)\.outcome/);
  assert.match(run, /python scripts\/ci_run_layer\.py/);
  assert.match(run, /--blocked-preparation website/);
});
