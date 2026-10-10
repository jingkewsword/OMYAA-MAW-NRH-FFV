import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import test from 'node:test';
import { _electron as electron, expect } from '@playwright/test';

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('desktop update UI uses private IPC, persists preference, escapes notes, and has measured spacing', { timeout: 90_000 }, async () => {
  const root = mkdtempSync(path.join(tmpdir(), 'mose-updates-'));
  const settings = path.join(root, 'settings'); mkdirSync(path.join(settings, 'mose-updates'), { recursive: true });
  writeFileSync(path.join(settings, 'server-editor-settings.json'), JSON.stringify({ onboarding_status: 'completed', auto_open_last_project: false }));
  writeFileSync(path.join(settings, 'mose-updates', 'state.json'), JSON.stringify({ autoCheck: false, result: {
    currentVersion: '1.0.0', latestVersion: '99.0.0', latestTag: 'v99.0.0', available: true,
    releaseNotes: '<img src=x onerror="window.updateXss=true">\nA new release', assetAvailable: false,
  } }));
  const env = { ...process.env, MAW_APP_DATA_ROOT: settings, MAW_DESKTOP_SMOKE: '1' }; delete env.ELECTRON_RUN_AS_NODE;
  const instance = await electron.launch({
    executablePath: process.env.MOSE_TEST_EXECUTABLE || createRequire(path.join(desktop, 'package.json'))('electron'),
    args: [...(process.env.MOSE_TEST_EXECUTABLE ? [] : [desktop]), `--user-data-dir=${path.join(root, 'profile')}`], env,
  });
  try {
    const page = await instance.firstWindow();
    await page.locator('#desktop-update-toggle').click();
    await expect(page.locator('#desktop-update-version')).toContainText('99.0.0');
    await page.locator('#desktop-update-notes-label').click();
    await expect(page.locator('#desktop-update-notes')).toContainText('<img');
    assert.equal(await page.evaluate(() => Boolean(window.updateXss)), false);
    assert.equal(await page.locator('#desktop-update-notes img').count(), 0);
    assert.equal(await page.evaluate(async () => (await fetch('/api/desktop/updates', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'prepare', tag: 'v99.0.0' }),
    })).status), 403);
    const gap = await page.evaluate(() => Number.parseFloat(getComputedStyle(document.querySelector('.desktop-update-content')).rowGap));
    assert.ok(gap >= 8, `Measured update panel gap: ${gap}`);
    await page.locator('#desktop-update-auto').check();
    await expect.poll(async () => page.evaluate(async () => (await MOSEDesktop.update({ action: 'status' })).update.autoCheck)).toBe(true);
    await page.locator('#desktop-update-auto').uncheck();
    await page.evaluate(() => MAWE_I18N.applyLanguage('en'));
    await expect(page.locator('#desktop-update-title')).toHaveText('MOSE updates');
    await page.screenshot({ path: path.join(root, 'updates-en.png') });
    if (process.env.MOSE_SCREENSHOT_DIR) {
      mkdirSync(process.env.MOSE_SCREENSHOT_DIR, { recursive: true });
      await page.screenshot({ path: path.join(process.env.MOSE_SCREENSHOT_DIR, 'updates-dark.png') });
      await page.evaluate(() => MaweTheme.applyTheme('light'));
      await page.screenshot({ path: path.join(process.env.MOSE_SCREENSHOT_DIR, 'updates-light.png') });
    }
    await page.locator('[data-update="close"]').click();
    await expect(page.locator('#desktop-update-dialog')).not.toBeVisible();
    console.log(`Update panel measured gap: ${gap}px; screenshot: ${root}`);
  } finally {
    await instance.evaluate(({ dialog }) => { dialog.showMessageBoxSync = () => 0; }).catch(() => {});
    await instance.close();
  }
});
