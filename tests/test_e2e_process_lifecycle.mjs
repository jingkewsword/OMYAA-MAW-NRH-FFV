import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:net';

const driver = fileURLToPath(new URL('./fixtures/e2e-lifecycle-driver.mjs', import.meta.url));
const synthetic = fileURLToPath(new URL('./fixtures/e2e-process-tree.py', import.meta.url));
const alive = pid => {
  try {
    process.kill(pid, 0);
    // Linux can retain an already-exited orphan as a zombie until PID 1 reaps
    // it. It cannot execute or own a listening socket; do not count it as live.
    if (process.platform === 'linux') {
      const stat = readFileSync(`/proc/${pid}/stat`, 'utf8');
      if (stat.slice(stat.lastIndexOf(')') + 2).startsWith('Z ')) return false;
    }
    return true;
  } catch { return false; }
};
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function startBystander() {
  const proc = spawn(process.execPath, ['-e', `
    const server = require('node:http').createServer((req, res) => res.end('bystander'));
    server.listen(0, '127.0.0.1', () => process.send(server.address().port));
  `], { stdio: ['ignore', 'ignore', 'ignore', 'ipc'], windowsHide: true });
  const port = await new Promise((resolve, reject) => {
    proc.once('message', resolve); proc.once('error', reject);
  });
  return { proc, port };
}

function killOwned(pid) {
  if (!alive(pid)) return;
  if (process.platform === 'win32') {
    execFileSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore', windowsHide: true, timeout: 5000 });
  } else process.kill(pid, 'SIGKILL');
}

async function portFree(port) {
  // Windows can report a process gone before the kernel releases its sockets.
  // Require successful rebinding within a deadline, rather than at that instant.
  const deadline = Date.now() + 2000;
  for (;;) {
    const server = createServer();
    try {
      await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
      await new Promise(resolve => server.close(resolve));
      return;
    } catch (error) {
      if (error.code !== 'EADDRINUSE' || Date.now() >= deadline) throw error;
      await delay(25);
    }
  }
}

async function waitForLeafClose(closed) {
  let timer;
  try {
    return await Promise.race([closed, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('leaf did not close within 5s')), 5000);
    })]);
  } finally { clearTimeout(timer); }
}

test('leaf waits for evidence handshake and exits on EOF without listening', { timeout: 20_000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), 'maw-leaf-handshake-'));
  let child, closed, primaryError;
  try {
    writeFileSync(join(root, 'scenario.txt'), 'ready');
    const reservation = createServer();
    await new Promise((resolve, reject) => {
      reservation.once('error', reject);
      reservation.listen(0, '127.0.0.1', resolve);
    });
    const port = reservation.address().port;
    await new Promise(resolve => reservation.close(resolve));
    child = spawn(process.env.MAW_E2E_PYTHON || 'python', [synthetic, '--port', String(port), '--leaf'], {
      cwd: root, env: { ...process.env, MAW_APP_DATA_ROOT: join(root, 'settings'), MAW_LIFECYCLE_TEST_HANDSHAKE: '1' },
      stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
    });
    closed = new Promise(resolve => child.once('close', (code, signal) => resolve({ code, signal })));
    const marker = await new Promise((resolve, reject) => {
      let output = '';
      const cleanup = () => { clearTimeout(timer); child.stdout.off('data', onData); child.off('error', onError); child.off('exit', onExit); };
      const onData = data => {
        output += data.toString();
        const newline = output.indexOf('\n');
        if (newline >= 0) { cleanup(); resolve(output.slice(0, newline).replace(/\r$/, '')); }
      };
      const onError = error => { cleanup(); reject(error); };
      const onExit = code => { cleanup(); reject(new Error(`leaf exited before handshake: ${code}`)); };
      const timer = setTimeout(() => { cleanup(); reject(new Error('leaf handshake marker timed out')); }, 10_000);
      child.stdout.on('data', onData);
      child.once('error', onError);
      child.once('exit', onExit);
    });
    assert.equal(marker, 'LEAF_WAITING');
    assert.equal(child.exitCode, null);
    await portFree(port);
    child.stdin.end();
    assert.equal((await waitForLeafClose(closed)).code, 1);
    await portFree(port);
  } catch (error) {
    primaryError = error;
  } finally {
    const cleanupErrors = [];
    if (child && child.exitCode === null && child.signalCode === null) {
      try {
        killOwned(child.pid);
        await waitForLeafClose(closed);
      } catch (error) { cleanupErrors.push(error); }
    }
    try { rmSync(root, { recursive: true }); } catch (error) { cleanupErrors.push(error); }
    if (primaryError && cleanupErrors.length) throw new AggregateError([primaryError, ...cleanupErrors], 'handshake test and cleanup failed');
    if (primaryError) throw primaryError;
    if (cleanupErrors.length) throw new AggregateError(cleanupErrors, 'handshake cleanup failed');
  }
});

async function runScenario(kind, scenario, action = 'stop') {
  const root = mkdtempSync(join(tmpdir(), 'maw-lifecycle-'));
  mkdirSync(join(root, 'server-editor'));
  copyFileSync(synthetic, join(root, 'server-editor', 'serve.py'));
  writeFileSync(join(root, 'scenario.txt'), scenario);
  const evidence = join(root, 'evidence');
  mkdirSync(evidence);
  const bystander = await startBystander();
  // Successful Windows startup includes the cold PowerShell/Add-Type Job
  // supervisor. Use the real scroll fixture's existing readiness budget;
  // synthetic failure scenarios keep their short deadlines below.
  const readinessTimeoutMs = process.platform === 'win32'
    ? (scenario === 'ready' ? 45_000 : 10_000) : 1_500;
  const scenarioDeadlineMs = readinessTimeoutMs + 8_000;
  const child = spawn(process.execPath, [driver, kind, action, String(readinessTimeoutMs)], { cwd: root, env: {
    ...process.env, MAW_E2E_PYTHON: scenario === 'missing-command' ? join(root, 'missing-python')
      : process.env.MAW_E2E_PYTHON || 'python', MAW_SCROLL_EVIDENCE: evidence,
    MAW_LIFECYCLE_PARENT_ONLY: 'synthetic-supervisor-marker',
  }, stdio: ['ignore', 'pipe', 'pipe', 'ipc'], windowsHide: true });
  let output = '';
  let message;
  let timedOut = false;
  const started = Date.now();
  child.stdout.on('data', b => { output += b; });
  child.stderr.on('data', b => { output += b; });
  child.on('message', value => {
    message = value;
    if (value.ready) {
      if (process.platform === 'win32') child.kill('SIGKILL');
      else child.kill('SIGTERM');
    }
  });
  const exited = new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => resolve({ code, signal }));
  });
  const timer = setTimeout(() => {
    timedOut = true;
    try { killOwned(child.pid); } catch {}
  }, scenarioDeadlineMs);
  try {
    const result = await exited;
    assert.equal(timedOut, false, `driver exceeded deadline: ${output}`);
    if (scenario === 'ready' && action === 'stop') {
      assert.equal(result.code, 0, message?.failure || output);
      assert.equal(message?.stopped, true);
    } else if (scenario !== 'ready') {
      assert.equal(result.code, 1, output);
      assert.ok(message?.failure, output);
      if (scenario === 'hang') assert.match(message.failure, /did not/);
    } else if (action.startsWith('signal:')) {
      assert.equal(result.code, { SIGINT: 130, SIGTERM: 143, SIGBREAK: 149, SIGHUP: 129 }[action.slice(7)]);
    } else if (action === 'exit') assert.equal(result.code, 0, output);
    else if (action === 'exception') assert.equal(result.code, 1, output);
    if (action === 'hold') {
      assert.equal(message?.ready, true);
      assert.equal(message.pids.length, 2);
      assert.ok(message.pids.every(pid => Number.isInteger(pid) && pid > 0));
      assert.notEqual(message.pids[0], message.pids[1]);
    }
    assert.ok(Date.now() - started < scenarioDeadlineMs);
    const dir = join(evidence, readdirSync(evidence)[0]);
    const { port } = JSON.parse(readFileSync(join(dir, 'runtime.json')));
    if (scenario !== 'missing-command') {
      if (kind === 'scroll') {
        const environment = JSON.parse(readFileSync(join(dir, 'runtime-environment.json')));
        assert.equal(environment.localAppData, join(dir, 'settings'));
        assert.equal(environment.parentOnlyMarker, false, 'supervisor-only environment cannot reach the application');
      }
      const pids = JSON.parse(readFileSync(join(dir, 'owned-pids.json')));
      if (action === 'hold') assert.deepEqual(pids, message.pids);
      const deadline = Date.now() + 2000;
      while (pids.some(alive) && Date.now() < deadline) await delay(25);
      assert.deepEqual(pids.filter(alive), [], 'owned descendants must exit, not just the wrapper');
    }
    await portFree(port);
    assert.equal(alive(bystander.proc.pid), true, 'unrelated process must remain alive');
    const response = await fetch(`http://127.0.0.1:${bystander.port}`, { signal: AbortSignal.timeout(1000) });
    assert.equal(await response.text(), 'bystander');
  } finally {
    clearTimeout(timer);
    for (const name of readdirSync(evidence)) {
      try { for (const pid of JSON.parse(readFileSync(join(evidence, name, 'owned-pids.json')))) killOwned(pid); } catch {}
    }
    try { killOwned(child.pid); } catch {}
    bystander.proc.kill();
  }
}

for (const kind of ['scroll', 'helpers']) {
  for (const scenario of ['ready', 'startup-error', 'wrapper-exit', 'missing-command', 'hang']) {
    test(`${kind}: ${scenario} reaps descendants, frees port, and returns within deadline`,
      { timeout: process.platform === 'win32' && scenario === 'ready' ? 60_000 : 24_000 },
      () => runScenario(kind, scenario));
  }
  for (const action of ['exit', 'exception', 'signal:SIGINT', 'signal:SIGTERM',
    process.platform === 'win32' ? 'signal:SIGBREAK' : 'signal:SIGHUP', 'hold']) {
    // emit exercises the JS handler on Windows; process.kill(SIGTERM) there is
    // unconditional termination, not delivery of a catchable POSIX signal.
    test(`${kind}: ${action} cleans up after owner exit`,
      { timeout: process.platform === 'win32' ? 60_000 : 20_000 },
      () => runScenario(kind, 'ready', action));
  }
}
