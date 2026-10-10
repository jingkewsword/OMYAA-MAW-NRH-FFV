import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { EventEmitter } from 'node:events';
import { verifyInstaller, launchInstaller } from '../src/update_install.cjs';

test('installer handoff rechecks bytes and never silently closes other apps or reboots', async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'mose-update-test-'));
  const file = path.join(root, 'MAW-Setup-Windows-x64-v2.0.0.exe');
  const bytes = Buffer.from('fake installer; never executed');
  writeFileSync(file, bytes);
  const update = { canApply: true, path: file, size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
  await verifyInstaller(update);
  let called = false;
  await launchInstaller(update, (exe, args, options) => {
    called = true;
    assert.equal(exe, file);
    assert.ok(args.includes('/NORESTART'));
    assert.ok(!args.includes('/VERYSILENT'));
    assert.ok(!args.includes('/FORCECLOSEAPPLICATIONS'));
    assert.equal(options.detached, true);
    const child = new EventEmitter(); child.unref = () => {};
    queueMicrotask(() => child.emit('spawn'));
    return child;
  });
  assert.ok(called);
  writeFileSync(file, Buffer.alloc(bytes.length));
  await assert.rejects(verifyInstaller(update), /校验失败/u);
  await assert.rejects(verifyInstaller({ ...update, canApply: false }), /无效/u);
  await assert.rejects(verifyInstaller({ ...update, path: 'relative.exe' }), /无效/u);
});
