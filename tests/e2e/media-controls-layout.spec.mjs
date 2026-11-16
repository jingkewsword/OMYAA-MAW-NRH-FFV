import { expect, test } from '@playwright/test';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { disableOnboarding } from './helpers.mjs';

const blankEditorUrl = pathToFileURL(join(process.cwd(), 'blank-editor.html')).href;

test.beforeEach(async ({ page }) => {
  await disableOnboarding(page);
});

test('media controls stay on one line and keep fullscreen visible at narrow widths', async ({ page }) => {
  for (const width of [620, 500, 340]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(blankEditorUrl);

    const metrics = await page.locator('#media-controls').evaluate((controls) => {
      const fullscreen = document.getElementById('media-fullscreen');
      const seek = document.getElementById('media-seek');
      const stepBack = document.getElementById('media-step-back');
      const stepForward = document.getElementById('media-step-forward');
      const volume = document.getElementById('audio-processing-toggle');
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
        volumeVisible: getComputedStyle(volume).display !== 'none'
          && volume.getBoundingClientRect().width > 0 && volume.getBoundingClientRect().height > 0,
        volumeInLine: volume.getBoundingClientRect().top >= controlsRect.top - 1
          && volume.getBoundingClientRect().bottom <= controlsRect.bottom + 1
          && volume.getBoundingClientRect().right <= controlsRect.right + 1,
      };
    });

    expect(metrics.controlsHeight).toBeLessThan(60);
    expect(metrics.fullscreenVisible).toBe(true);
    expect(metrics.fullscreenInLine).toBe(true);
    expect(metrics.seekWidth).toBeGreaterThan(0);
    expect(metrics.stepBackDisplay).toBe('none');
    expect(metrics.stepForwardDisplay).toBe('none');
    expect(metrics.volumeVisible).toBe(true);
    expect(metrics.volumeInLine).toBe(true);
    await page.locator('#audio-processing-toggle').click();
    await expect(page.locator('#audio-processing-panel')).toBeVisible();
    await expect(page.locator('#media-volume')).toBeVisible();
  }
});
