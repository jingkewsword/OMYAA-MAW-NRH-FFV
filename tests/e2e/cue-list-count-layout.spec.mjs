import { expect, test } from '@playwright/test';
import { join } from 'node:path';
import { cleanupTempDir, disableOnboarding, findFreePort, makeTempDir, startBlankServer } from './helpers.mjs';

let directory, server;
test.beforeAll(async () => {
  directory = makeTempDir('cue-count-layout');
  server = await startBlankServer(await findFreePort(), join(directory, 'settings'));
});
test.afterAll(async () => { await server?.stop(); cleanupTempDir(directory); });

test('hides the cue-list visible count at narrow widths', async ({ page }) => {
  await disableOnboarding(page);

  for (const width of [620, 480, 360]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(server.url);
    const count = page.locator('.cue-list-count');
    await expect(count).toHaveCount(1);
    await expect(count).toBeHidden();
    await expect(page.locator('#cue-list-settings-toggle')).toBeVisible();
  }
});
