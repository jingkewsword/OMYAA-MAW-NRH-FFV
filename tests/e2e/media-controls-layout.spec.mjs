import { expect, test } from '@playwright/test';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { buildPortableBlankEditor, cleanupTempDir, disableOnboarding, findFreePort,
  makeTempDir, startBlankServer } from './helpers.mjs';

let directory, portable, server;
test.beforeAll(async () => {
  directory = makeTempDir('media-controls-layout');
  portable = pathToFileURL(buildPortableBlankEditor(join(directory, 'current.edit.html'))).href;
  server = await startBlankServer(await findFreePort(), join(directory, 'settings'));
});
test.afterAll(async () => { await server?.stop(); cleanupTempDir(directory); });

test.beforeEach(async ({ page }) => {
  await disableOnboarding(page);
});

for (const transport of ['file', 'HTTP']) test(`${transport} media controls stay on one line and keep fullscreen visible at narrow widths`, async ({ page }) => {
  for (const width of [620, 500, 340]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(transport === 'file' ? portable : server.url);

    const metrics = await page.locator('#media-controls').evaluate((controls) => {
      const fullscreen = document.getElementById('media-fullscreen');
      const seek = document.getElementById('media-seek');
      const stepBack = document.getElementById('media-step-back');
      const stepForward = document.getElementById('media-step-forward');
      const gain = document.getElementById('audio-processing-toggle');
      const rate = document.querySelector('.media-rate-control');
      const controlsRect = controls.getBoundingClientRect();
      const fullscreenRect = fullscreen.getBoundingClientRect();
      return {
        controlsHeight: controlsRect.height,
        fullscreenVisible: getComputedStyle(fullscreen).display !== 'none'
          && fullscreenRect.width > 0 && fullscreenRect.height > 0,
        fullscreenInLine: fullscreenRect.top >= controlsRect.top - 1
          && fullscreenRect.bottom <= controlsRect.bottom + 1
          && fullscreenRect.right <= controlsRect.right + 1,
        seekWidth: seek.getBoundingClientRect().width,
        stepBackDisplay: getComputedStyle(stepBack).display,
        stepForwardDisplay: getComputedStyle(stepForward).display,
        gainVisible: getComputedStyle(gain).display !== 'none' && gain.getBoundingClientRect().width > 0,
        rateVisible: getComputedStyle(rate).display !== 'none' && rate.getBoundingClientRect().width > 0,
        gainInLine: gain.getBoundingClientRect().bottom <= controlsRect.bottom + 1,
        rateInLine: rate.getBoundingClientRect().bottom <= controlsRect.bottom + 1,
      };
    });

    expect(metrics.controlsHeight).toBeLessThan(60);
    expect(metrics.fullscreenVisible).toBe(true);
    expect(metrics.fullscreenInLine).toBe(true);
    expect(metrics.seekWidth).toBeGreaterThan(0);
    expect(metrics.stepBackDisplay).toBe('none');
    expect(metrics.stepForwardDisplay).toBe('none');
    expect(metrics.gainVisible && metrics.gainInLine).toBe(true);
    expect(metrics.rateVisible && metrics.rateInLine).toBe(true);
  }
});
