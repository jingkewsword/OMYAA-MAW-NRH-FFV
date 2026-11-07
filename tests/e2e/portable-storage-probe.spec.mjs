import { chromium, expect, test } from '@playwright/test';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { buildBrowserEditorFixture, cleanupTempDir, disableOnboarding, findFreePort,
  generateProjectJson, generateWav, makeTempDir, removeTextProcessPrefill, addTextProcessStep, startServer } from './helpers.mjs';

let directory, server, portable;
test.beforeAll(async () => {
  directory = makeTempDir('portable-storage-probe');
  const project = join(directory, 'project.json'), media = join(directory, 'synthetic.wav');
  generateProjectJson(project); generateWav(media, 300);
  portable = pathToFileURL(buildBrowserEditorFixture(join(directory, 'portable.html'))).href;
  server = await startServer(project, media, await findFreePort());
});
test.afterAll(async () => { await server?.stop(); cleanupTempDir(directory); });

async function observe(page, stage, result) {
  const state = await page.evaluate(() => {
    const read = key => { try { return localStorage.getItem(key); } catch (e) { return `ERROR: ${e}`; } };
    return { href: location.href, origin: location.origin, start: window.__probeStart,
      preset: read('moy.asr.text_processing_presets.v1'), sentinel: read('maw.portable.probe.sentinel'),
      library: window.MaweProcessing?.library ?? null,
      projectOverride: window.MaweProcessing?.projectOverride('text') ?? null,
      selected: document.querySelector('#text-preset-select')?.value ?? null };
  });
  const session = await page.context().newCDPSession(page);
  try {
    const { frameTree } = await session.send('Page.getFrameTree');
    state.storageKey = (await session.send('Storage.getStorageKeyForFrame', { frameId: frameTree.frame.id })).storageKey;
    state.browser = (await session.send('Browser.getVersion')).product;
  } catch (error) { state.cdpError = String(error); }
  finally { await session.detach(); }
  result.stages[stage] = state;
}

async function openProbe(context, result, first) {
  const page = await context.newPage();
  page.on('pageerror', error => result.errors.push(String(error.stack || error)));
  await disableOnboarding(page);
  await page.addInitScript(() => {
    const read = key => { try { return localStorage.getItem(key); } catch (e) { return `ERROR: ${e}`; } };
    window.__probeStart = { href: location.href, preset: read('moy.asr.text_processing_presets.v1'),
      sentinel: read('maw.portable.probe.sentinel') };
  });
  await page.goto(server.url);
  await expect(page.locator('.cue[data-idx="0"] .text')).toBeVisible();
  await page.goto(portable);
  await observe(page, first ? 'fileInitial' : 'reopened', result);
  if (first) await page.evaluate(() => localStorage.setItem('maw.portable.probe.sentinel', 'probe-only'));
  await page.evaluate(() => {
    AsrEditorUtils.getMainTrack(MaweBoot.DATA).segments = [{ id: 'main-1', start: 1000, end: 5000, text: '  甲  ', items: null }];
    MaweBoot.DATA.tracks = MaweBoot.DATA.tracks.filter(track => track.role !== 'secondary');
    MaweBoot.DATA.bindings = []; MaweBoot.DATA.bilingual = { display_mode: 'both' };
    MaweSettings.updateEditorSettings({ autoSaveProject: false });
    MaweSelection.clearSelection({ silent: true }); MaweCuePanel.renderAll({ waveform: 'full' });
  });
  return page;
}

test('ABBA compares file storage across temporary and persistent profiles', async () => {
  test.setTimeout(4 * 60_000);
  const failures = [];
  for (const [index, mode] of ['A', 'B', 'B', 'A'].entries()) {
    const result = { sample: index + 1, mode, errors: [], stages: {}, checks: {} };
    const options = { headless: true, locale: 'zh-CN', viewport: { width: 1280, height: 1400 },
      ...(process.env.MAW_E2E_CHROMIUM_PATH ? { executablePath: process.env.MAW_E2E_CHROMIUM_PATH } : {}) };
    let browser, context;
    const profile = join(directory, `profile-${index}`);
    try {
      if (mode === 'A') { browser = await chromium.launch(options); context = await browser.newContext({ locale: 'zh-CN', viewport: options.viewport }); }
      else context = await chromium.launchPersistentContext(profile, options);
      let page = await openProbe(context, result, true);
      await page.locator('#text-process-btn').click();
      await removeTextProcessPrefill(page);
      await expect(page.locator('#text-preset-status')).toHaveAttribute('data-state', 'local');
      await addTextProcessStep(page, 'trim');
      page.once('dialog', dialog => dialog.accept('便携清理'));
      await page.locator('#text-preset-save-as').click(); await page.locator('#text-preset-default').click();
      await expect(page.locator('#text-preset-select option:checked')).toHaveText('便携清理 ★');
      await observe(page, 'beforeReload', result);
      await page.reload(); await observe(page, 'afterReload', result);
      await page.evaluate(() => { AsrEditorUtils.getMainTrack(MaweBoot.DATA).segments = [{ id: 'main-1', start: 1000, end: 5000, text: '  甲  ', items: null }]; MaweCuePanel.renderAll({ waveform: 'full' }); });
      await page.locator('#text-process-btn').click();
      result.checks.status = await expect(page.locator('#text-preset-status')).toHaveAttribute('data-state', 'local').then(() => true, () => false);
      await observe(page, 'afterOpen', result);
      result.checks.reload = await expect(page.locator('#text-preset-select option:checked')).toHaveText('便携清理 ★').then(() => true, () => false);
      result.checks.previewCount = await expect(page.locator('#text-process-preview')).toContainText('将处理 1 条字幕，预计修改 1 条').then(() => true, () => false);
      result.checks.processing = await expect(page.locator('.replace-preview-after')).toHaveText('处理后：甲').then(() => true, () => false);
      if (result.checks.processing) {
        await page.locator('#text-process-confirm').click();
        result.checks.applied = await page.evaluate(() => AsrEditorUtils.getMainTrack(MaweBoot.DATA).segments[0].text === '甲');
      } else result.checks.applied = false;
      if (mode === 'B') {
        await context.close(); context = null;
        context = await chromium.launchPersistentContext(profile, options);
        page = await openProbe(context, result, false);
        await page.locator('#text-process-btn').click();
        result.checks.restartStatus = await expect(page.locator('#text-preset-status')).toHaveAttribute('data-state', 'local').then(() => true, () => false);
        await observe(page, 'restartOpen', result);
        result.checks.restart = await expect(page.locator('#text-preset-select option:checked')).toHaveText('便携清理 ★').then(() => true, () => false);
        result.checks.restartPreviewCount = await expect(page.locator('#text-process-preview')).toContainText('将处理 1 条字幕，预计修改 1 条').then(() => true, () => false);
        result.checks.restartProcessing = await expect(page.locator('.replace-preview-after')).toHaveText('处理后：甲').then(() => true, () => false);
        if (result.checks.restartProcessing) {
          await page.locator('#text-process-confirm').click();
          result.checks.restartApplied = await page.evaluate(() => AsrEditorUtils.getMainTrack(MaweBoot.DATA).segments[0].text === '甲');
        } else result.checks.restartApplied = false;
      }
      expect(result.checks.reload).toBe(true);
      expect(result.checks.status).toBe(true);
      expect(result.checks.previewCount).toBe(true);
      expect(result.checks.processing).toBe(true);
      expect(result.checks.applied).toBe(true);
      expect(result.stages.afterReload.start.sentinel).toBe('probe-only');
      if (mode === 'B') {
        expect(result.checks.restart).toBe(true); expect(result.checks.restartStatus).toBe(true); expect(result.checks.restartPreviewCount).toBe(true); expect(result.checks.restartProcessing).toBe(true); expect(result.checks.restartApplied).toBe(true);
        expect(result.stages.reopened.start.sentinel).toBe('probe-only');
      }
    } catch (error) {
      result.failure = String(error.stack || error);
      failures.push({ sample: index + 1, mode, error: result.failure });
    } finally {
      for (const handle of [context, browser]) if (handle) {
        try { await handle.close(); } catch (error) {
          const message = String(error.stack || error);
          result.errors.push(message); failures.push({ sample: index + 1, mode, error: message });
        }
      }
      console.log('PORTABLE_STORAGE_PROBE', JSON.stringify(result));
    }
  }
  expect(failures).toEqual([]);
});
