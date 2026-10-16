import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../web/launcher/local/launcher-runtime-diagnostics.js', import.meta.url), 'utf8');

function setup(bridge) {
  const elements = new Map();
  const node = () => ({ value: 'moss', disabled: false, children: [], classList: { toggle() {} },
    replaceChildren() { this.children = []; }, append(child) { this.children.push(child); } });
  const context = vm.createContext({
    window: { MAWLauncher: { backend: 'real' } },
    $: id => { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); },
    document: { createElement: node }, bridge, t: key => key, setStatus() {},
    setTimeout: callback => callback(),
  });
  vm.runInContext(source, context);
  return { context, elements };
}

test('module loading never invokes checks; double click cannot start a second job', async () => {
  const calls = [];
  let release;
  const report = { runtimeKey: 'moss', checks: [{ id: 'imports', status: 'pass', code: 'imports_ok', pythonVersion: '3.11.9', torchVersion: '2.9.0+cu130', cudaVersion: '13.0' }] };
  const { context, elements } = setup(async (method, payload) => {
    calls.push({ method, payload });
    if (method === 'start_runtime_diagnostics') return new Promise(resolve => { release = resolve; });
    if (method === 'get_runtime_diagnostics') return { ok: true, running: false, report };
    return { ok: true };
  });
  assert.equal(calls.length, 0);
  const first = context.runRuntimeDiagnostics(false);
  await context.runRuntimeDiagnostics(true);
  assert.equal(calls.length, 1);
  assert.equal(elements.get('testRuntimeCuda').disabled, true);
  assert.equal(elements.get('cancelRuntimeDiagnostics').disabled, true);
  release({ ok: true, operationId: 'current' });
  await first;
  assert.equal(elements.get('exportRuntimeDiagnostics').disabled, false);
  assert.match(elements.get('runtimeDiagnosticResult').children.at(-1).textContent, /PyTorch 2\.9\.0\+cu130 · CUDA 13\.0/);
  await context.exportRuntimeDiagnostics();
  assert.equal(calls.at(-1).method, 'export_runtime_diagnostics');
  assert.equal(JSON.stringify(calls.at(-1).payload), '{"operationId":"current"}');
});

test('a failed start or lost polling response restores controls without exporting a stale report', async () => {
  for (const failAt of ['start_runtime_diagnostics', 'get_runtime_diagnostics']) {
    const { context, elements } = setup(async method => method === failAt
      ? { ok: false } : { ok: true, operationId: 'current' });
    await context.runRuntimeDiagnostics();
    assert.equal(elements.get('checkRuntimeDiagnostics').disabled, false);
    assert.equal(elements.get('exportRuntimeDiagnostics').disabled, true);
    assert.equal(elements.get('runtimeDiagnosticResult').children[0].textContent, 'rd_unavailable');
  }
});

test('cancelling uses the current operation and stays busy until backend cleanup completes', async () => {
  let finish;
  const cancelled = [];
  const { context, elements } = setup(async (method, payload) => {
    if (method === 'start_runtime_diagnostics') return { ok: true, operationId: 'current' };
    if (method === 'get_runtime_diagnostics') return new Promise(resolve => { finish = resolve; });
    if (method === 'cancel_runtime_diagnostics') { cancelled.push(payload.operationId); return { ok: true }; }
  });
  const checking = context.runRuntimeDiagnostics(true);
  await Promise.resolve();
  await context.cancelRuntimeDiagnostics();
  await context.cancelRuntimeDiagnostics();
  assert.deepEqual(cancelled, ['current']);
  assert.equal(elements.get('checkRuntimeDiagnostics').disabled, true);
  finish({ ok: true, running: false, report: { runtimeKey: 'moss', checks: [{ id: 'cuda', code: 'cancelled', status: 'not_checked' }] } });
  await checking;
  assert.equal(elements.get('checkRuntimeDiagnostics').disabled, false);
});
