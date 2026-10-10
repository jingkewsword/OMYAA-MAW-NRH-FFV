'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const { spawn } = require('node:child_process');

async function verifyInstaller(update) {
  if (!update?.canApply || !path.isAbsolute(update.path)
      || !/^MAW-Setup-Windows-x64-v[\w.+-]+\.exe$/u.test(path.basename(update.path))
      || !Number.isSafeInteger(update.size) || update.size <= 0
      || !/^[a-f0-9]{64}$/u.test(update.sha256)) throw new Error('更新包无效。');
  const stat = await fs.promises.lstat(update.path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== update.size) throw new Error('更新包大小不符。');
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(update.path)) digest.update(chunk);
  if (digest.digest('hex') !== update.sha256) throw new Error('更新包校验失败，请重新下载。');
}

async function launchInstaller(update, spawnImpl = spawn) {
  await verifyInstaller(update);
  // Keep Installer UI visible: another Launcher may own unsaved work. Never
  // silently force-close it, and never allow a software update to reboot Windows.
  const child = spawnImpl(update.path, ['/NORESTART', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS', '/MOSEUPDATE=1'], {
    cwd: path.dirname(update.path), detached: true, stdio: 'ignore', windowsHide: false,
  });
  await new Promise((resolve, reject) => { child.once('spawn', resolve); child.once('error', reject); });
  child.unref();
}

module.exports = { verifyInstaller, launchInstaller };
