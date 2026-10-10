import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:net';

const driver = fileURLToPath(new URL('./fixtures/e2e-lifecycle-driver.mjs', import.meta.url));
const synthetic = fileURLToPath(new URL('./fixtures/e2e-process-tree.py', import.meta.url));
const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function killOwned(pid) {
  if (!alive(pid)) return;
  if (process.platform === 'win32') {
    execFileSync('taskkill', ['/F', '/T', '/PID', String(pid)], { stdio: 'ignore', windowsHide: true, timeout: 5000 });
  } else process.kill(pid, 'SIGKILL');
}

async function portFree(port) {
  const server = createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  await new Promise(resolve => server.close(resolve));
}

test('scroll stop removes the wrapper and its server, releases port, and is repeatable', { timeout: 25000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), 'maw-lifecycle-'));
  mkdirSync(join(root, 'server-editor'));
  copyFileSync(synthetic, join(root, 'server-editor', 'serve.py'));
  writeFileSync(join(root, 'scenario.txt'), 'ready');
  const evidence = join(root, 'evidence');
  const child = spawn(process.execPath, [driver], { cwd: root, env: {
    ...process.env, MAW_E2E_PYTHON: process.env.MAW_E2E_PYTHON || 'python', MAW_SCROLL_EVIDENCE: evidence,
  }, stdio: ['ignore', 'pipe', 'pipe', 'ipc'], windowsHide: true });
  let output = '';
  child.stdout.on('data', b => { output += b; });
  child.stderr.on('data', b => { output += b; });
  const timer = setTimeout(() => { try { killOwned(child.pid); } catch {} }, 20000);
  try {
    await new Promise((resolve, reject) => {
      child.once('message', resolve);
      child.once('error', reject);
      child.once('exit', code => reject(new Error(`driver exited ${code}: ${output}`)));
    });
    const dir = join(evidence, readdirSync(evidence)[0]);
    const pids = JSON.parse(readFileSync(join(dir, 'owned-pids.json')));
    const { port } = JSON.parse(readFileSync(join(dir, 'runtime.json')));
    const deadline = Date.now() + 2000;
    while (pids.some(alive) && Date.now() < deadline) await delay(25);
    assert.deepEqual(pids.filter(alive), [], 'owned descendants must exit, not just the wrapper');
    await portFree(port);
  } finally {
    clearTimeout(timer);
    for (const name of readdirSync(evidence)) {
      try { for (const pid of JSON.parse(readFileSync(join(evidence, name, 'owned-pids.json')))) killOwned(pid); } catch {}
    }
    killOwned(child.pid);
  }
});
