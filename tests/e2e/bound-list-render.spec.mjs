import { expect, test } from '@playwright/test';
import { cleanupTempDir, disableOnboarding, findFreePort, makeTempDir, startBlankServer } from './helpers.mjs';

let directory, server;
test.beforeAll(async () => {
  directory = makeTempDir('bound-list');
  server = await startBlankServer(await findFreePort(), directory);
});
test.afterAll(async () => { await server?.stop(); cleanupTempDir(directory); });

test('dual-list binding markers follow re-render, unbind, rebind and editing', async ({ page }) => {
  await disableOnboarding(page);
  await page.goto(server.url);
  await page.waitForFunction(() => Boolean(window.MaweProjectLoad && window.MaweCuePanel));
  await page.evaluate(() => {
    MaweSettings.updateEditorSettings({ autoSaveProject: false });
    MaweProjectLoad.applyCanonicalProject({
      schema: 'moy.asr.project.v1', media: '',
      segments: [{ id: 'main-1', start: 0, end: 1000, text: '主字幕', items: [] }],
      multi_subtitle: {
        schema: 'moy.asr.multi_subtitle.v1', enabled: true, display_mode: 'both',
        tracks: [{ id: 'translation', role: 'extension', segments: [
          { id: 'extension-1', start: 0, end: 1000, text: 'Translation', items: [] },
        ] }],
        bindings: [{ id: 'bound', track_id: 'translation', main_segment_ids: ['main-1'],
          extension_segment_ids: ['extension-1'], start_offset_ms: 0, end_offset_ms: 0 }],
      },
    }, 'bound-list.mosp');
  });
  const column = () => page.locator('.multi-cue-column.extension').filter({ hasText: 'Translation' });
  await expect(column()).toHaveCount(1);
  await expect(column()).not.toHaveClass(/unbound/);

  await page.evaluate(() => {
    window.__savedBinding = structuredClone(MaweBoot.DATA.multi_subtitle.bindings[0]);
    MaweBoot.DATA.multi_subtitle.bindings = [];
    MaweCuePanel.renderAll({ waveform: 'none' });
  });
  await expect(column()).toHaveClass(/unbound/);
  await page.evaluate(() => {
    MaweBoot.DATA.multi_subtitle.bindings.push(window.__savedBinding);
    MaweCuePanel.renderAll({ waveform: 'none' });
  });
  await expect(column()).not.toHaveClass(/unbound/);

  await page.locator('.multi-cue-column.main').first().click();
  const editor = page.locator('#cue-panel-text');
  await expect(editor).toHaveValue('主字幕');
  await editor.fill('已修改');
  await editor.blur();
  await expect.poll(() => page.evaluate(() => MaweBoot.DATA.segments[0].text)).toBe('已修改');
  await expect(column()).not.toHaveClass(/unbound/);
});
