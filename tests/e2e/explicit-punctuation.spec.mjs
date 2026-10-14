import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { cleanupTempDir, disableOnboarding, findFreePort, generateWav, makeTempDir, startServer } from './helpers.mjs';

function project(preserve) {
  return { schema: 'moy.asr.project.v1', media: 'audio.wav',
    ...(preserve === undefined ? {} : { preserve_punctuation: preserve }),
    segments: [{ id: 'main-1', start: 0, end: 2800, text: '啊，正，文。', items: [
      { text: '啊，', start: 0, end: 400 }, { text: '正，文', start: 500, end: 2200 },
      { text: '。', start: 2200, end: 2800 },
    ] }, { id: 'main-2', start: 3000, end: 5000, text: 'cafe\u0301! 😀？', items: [
      { text: 'cafe\u0301! 😀？', start: 3000, end: 5000 },
    ] }], gap_remove: { provenance: { sources: { ai_cleanup: [
      { id: 'valid', start: 0, end: 400, cleanup_scope: { segment_id: 'main-1', item_start: 0, item_end: 1, text: '啊，' } },
      { id: 'stale', start: 500, end: 2200, cleanup_scope: { segment_id: 'main-1', item_start: 1, item_end: 2, text: '正  文' } },
    ] } } } };
}

async function withProject(page, preserve, run) {
  const directory = makeTempDir('explicit-punctuation');
  const input = join(directory, 'project.mosp');
  const media = join(directory, 'audio.wav');
  let server;
  try {
    const original = project(preserve);
    writeFileSync(input, JSON.stringify(original), 'utf8');
    generateWav(media, 6);
    server = await startServer(input, media, await findFreePort());
    await disableOnboarding(page);
    await page.addInitScript(() => localStorage.setItem('moy.asr.editor.settings.v1', JSON.stringify({ autoSaveProject: false })));
    await page.goto(server.url);
    await expect(page.locator('.cue[data-idx="0"] .text')).toBeVisible();
    await run({ input, original });
  } finally {
    await server?.stop();
    cleanupTempDir(directory);
  }
}

const subtitleText = (value) => value.segments.map((cue) => ({ text: cue.text,
  items: cue.items.map(({ text, start, end }) => ({ text, start, end })) }));

for (const preserve of [undefined, false, true]) {
  test(`opening and saving preserves text and punctuation items with legacy flag ${preserve}`, async ({ page }) => {
    await withProject(page, preserve, async ({ input, original }) => {
      expect(await page.evaluate(() => MaweBoot.DATA.segments.map((cue) => ({ text: cue.text,
        items: cue.items.map(({ text, start, end }) => ({ text, start, end })) })))).toEqual(subtitleText(original));
      expect(await page.evaluate(() => MaweProjectSave.saveProjectToServer({ silent: true }))).toBe(true);
      const saved = JSON.parse(readFileSync(input, 'utf8'));
      expect(subtitleText(saved)).toEqual(subtitleText(original));
      expect(saved).not.toHaveProperty('preserve_punctuation');
      await page.reload();
      await expect(page.locator('.cue[data-idx="0"] .text')).toBeVisible();
      expect(await page.evaluate(() => MaweBoot.DATA.segments.map((cue) => ({ text: cue.text,
        items: cue.items.map(({ text, start, end }) => ({ text, start, end })) })))).toEqual(subtitleText(original));
      // Use the real file importer as well as initial server injection.
      expect(await page.evaluate(async (data) => MaweMultiImport.openProjectFile(
        new File([JSON.stringify(data)], 'import.mosp', { type: 'application/json' }), { suppressMediaPrompt: true }), original)).toBe(true);
      expect(await page.evaluate(() => MaweBoot.DATA.segments.map((cue) => ({ text: cue.text,
        items: cue.items.map(({ text, start, end }) => ({ text, start, end })) })))).toEqual(subtitleText(original));
    });
  });
}

test('explicit cleanup previews, preserves timing and atomically undoes scope changes', async ({ page }) => {
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  await withProject(page, undefined, async ({ input, original }) => {
    // Simulate a stale authorization left by a later ordinary text edit. Initial
    // import already removes stale scopes, so seed it after loading here.
    await page.evaluate((scope) => {
      MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup.find((range) => range.id === 'stale').cleanup_scope = scope;
    }, original.gap_remove.provenance.sources.ai_cleanup[1].cleanup_scope);
    await page.evaluate(() => { MaweSelection.clearSelection({ silent: true }); MaweTextProcess.openTextProcessModal(); });
    const cleanup = page.locator('#text-process-clean-punctuation');
    await expect(cleanup).not.toBeChecked();
    await expect(page.locator('#text-process-confirm')).toBeDisabled();
    await cleanup.check();
    await expect(page.locator('#text-process-preview')).toContainText('啊  正  文');
    const spacing = await cleanup.evaluate((element) => {
      const row = element.closest('label');
      const previous = row.previousElementSibling;
      return previous ? row.getBoundingClientRect().top - previous.getBoundingClientRect().bottom : 8;
    });
    expect(spacing).toBeGreaterThanOrEqual(8);
    writeFileSync(test.info().outputPath('editor-spacing.json'), JSON.stringify({ vertical_gap_px: spacing }));
    await page.screenshot({ path: test.info().outputPath('explicit-cleanup-dialog.png'), fullPage: true });
    await page.locator('#text-process-confirm').click();
    expect(browserErrors).toEqual([]);
    const state = () => page.evaluate(() => ({ segments: MaweBoot.DATA.segments.map((cue) => ({ text: cue.text,
      items: cue.items.map(({ text, start, end }) => ({ text, start, end })) })),
      ranges: MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup,
      history: MaweHistory.editorHistory.undoLength(), projected: MaweExportSrt.cleanupMainSegments()[0].text }));
    const cleaned = await state();
    expect(cleaned.segments[0].text).toBe('啊  正  文');
    expect(cleaned.segments[0].items.map((item) => item.text)).toEqual(['啊  ', '正  文', '']);
    expect(cleaned.segments.map((cue) => cue.items.map(({ start, end }) => [start, end])))
      .toEqual(subtitleText(original).map((cue) => cue.items.map(({ start, end }) => [start, end])));
    expect(cleaned.segments[1]).toEqual(subtitleText(original)[1]);
    expect(cleaned.ranges.find((range) => range.id === 'valid').cleanup_scope.text).toBe('啊  ');
    expect(cleaned.ranges.find((range) => range.id === 'stale')).not.toHaveProperty('cleanup_scope');
    expect(cleaned.projected).toBe('正  文');
    expect(cleaned.history).toBe(1);
    await page.locator('#undo-btn').click();
    const undone = await state();
    expect(undone.segments).toEqual(subtitleText(original));
    expect(undone.ranges.find((range) => range.id === 'valid').cleanup_scope.text).toBe('啊，');
    expect(undone.ranges.find((range) => range.id === 'stale').cleanup_scope.text).toBe('正  文');
    await page.locator('#redo-btn').click();
    expect(await state()).toEqual(cleaned);
    expect(await page.evaluate(() => MaweProjectSave.saveProjectToServer({ silent: true }))).toBe(true);
    const saved = JSON.parse(readFileSync(input, 'utf8'));
    expect(subtitleText(saved)).toEqual(cleaned.segments);
    await page.reload();
    await expect(page.locator('.cue[data-idx="0"] .text')).toBeVisible();
    expect((await state()).segments).toEqual(cleaned.segments);
    expect((await state()).projected).toBe('正  文');
  });
});

test('Launcher cleanup is opt-in and saved in an automatic fixed-processing plan', async ({ page }) => {
  await page.goto(`file://${resolve('web/launcher/index.html')}`);
  await page.waitForFunction(() => window.MAWLauncher?.config?.postprocessProviders?.length > 0);
  await page.evaluate(() => {
    window.__punctuationPlans = [];
    const original = window.MAWLauncher.callBackend;
    window.MAWLauncher.callBackend = async (method, payload) => {
      if (method === 'save_postprocess_plan') {
        window.__punctuationPlans.push(structuredClone(payload.plan));
        return { ok: true, plan: payload.plan };
      }
      if (method === 'run_fixed_process') {
        window.__punctuationRequest = payload;
        return { ok: false, error: 'Synthetic bridge response' };
      }
      return original(method, payload);
    };
  });
  await page.locator('#toolboxFab').click();
  await page.locator('#toolboxReplaceTab').click();
  const checkbox = page.locator('#postprocessCleanPunctuation');
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await page.locator('#toolboxInputPath').fill('D:\\Synthetic\\source.mosp');
  await page.locator('#runFixedProcess').click();
  await expect.poll(() => page.evaluate(() => window.__punctuationRequest?.cleanChinesePunctuation)).toBe(true);
  expect(await page.evaluate(() => window.__punctuationRequest.replacements)).toEqual([]);
  const spacing = await checkbox.evaluate((element) => {
    const row = element.closest('label');
    const hint = row.nextElementSibling;
    return hint.getBoundingClientRect().top - row.getBoundingClientRect().bottom;
  });
  expect(spacing).toBeGreaterThanOrEqual(8);
  writeFileSync(test.info().outputPath('launcher-spacing.json'), JSON.stringify({ vertical_gap_px: spacing }));
  await page.screenshot({ path: test.info().outputPath('launcher-cleanup.png'), fullPage: true });
  await page.locator('#toolboxClose').click();
  await page.locator('#autoPostprocessEnabled').check();
  await page.locator('#autoStepReplace').check();
  await expect.poll(() => page.evaluate(() => window.__punctuationPlans.at(-1)?.steps.find((step) => step.id === 'replace')))
    .toMatchObject({ enabled: true, cleanChinesePunctuation: true });
});
