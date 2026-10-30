import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { cleanupTempDir, disableOnboarding, findFreePort, makeTempDir, startBlankServer } from './helpers.mjs';

const canonical = JSON.parse(readFileSync(new URL('../fixtures/project-tracks/legacy-three-tracks.expected.json', import.meta.url), 'utf8'));
let directory, server;
test.beforeAll(async () => { directory = makeTempDir('track-styles'); server = await startBlankServer(await findFreePort(), directory); });
test.afterAll(async () => { await server?.stop(); cleanupTempDir(directory); });
test.beforeEach(async ({ page }) => {
  await disableOnboarding(page);
  await page.goto(server.url);
  await page.waitForFunction(() => window.MaweAssManagerWiring && window.MaweMultiImport);
  await page.evaluate(async project => {
    await MaweMultiImport.openProjectFile(new File([JSON.stringify({ ...project, media: '' })], 'styles.mosp', { type: 'application/json' }), { suppressMediaPrompt: true });
  }, canonical);
  await expect.poll(() => page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('main').status)).toBe('linked');
});

test('library edits update linked tracks, project edits fork, and save is one undo', async ({ page }) => {
  await page.evaluate(() => {
    MaweAssManagerWiring.applyProjectStyleSelection('secondary', 'ass');
    MaweHistory.editorHistory.clear();
    MaweState.establishProjectCheckpoint();
  });
  expect(await page.evaluate(() => MaweState.hasProjectChanges())).toBe(false);
  await page.evaluate(() => MaweSettingsPanels.openEditorSettingsAtTab('editor-settings-tab-subtitle-style'));
  await page.locator('#ass-style-manager-open').click();
  await page.locator('#ass-style-list [data-ass-selection-id="ass"]').click();
  await page.locator('#ass-style-font-size').fill('100');
  await expect.poll(() => page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('main').style.fontSize)).toBe(100);
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').style.fontSize)).toBe(100);
  expect(await page.evaluate(() => MaweState.hasProjectChanges())).toBe(true);

  await page.evaluate(() => MaweAssManagerWiring.openProjectStyleEditor('main'));
  await page.locator('#ass-style-font-size').fill('120');
  const forked = await page.evaluate(() => ({ main: MaweAssManagerWiring.projectStyleOptions('main'), secondary: MaweAssManagerWiring.projectStyleOptions('secondary') }));
  expect(forked.main.status).toBe('forked');
  expect(forked.main.style.fontSize).toBe(120);
  expect(forked.secondary.style.fontSize).toBe(100);
  const count = await page.evaluate(() => MaweHistory.editorHistory.undoLength());
  page.once('dialog', dialog => dialog.accept());
  await page.evaluate(() => MaweAssManagerWiring.saveProjectStyleToLibrary('main'));
  expect(await page.evaluate(() => MaweHistory.editorHistory.undoLength())).toBe(count + 1);
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').style.fontSize)).toBe(120);
  const status = page.locator('[data-track-role="main"] [data-track-style-status]');
  await expect(status).toHaveText('样式库');
  await page.evaluate(() => MaweHistory.performUndo());
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('main').status)).toBe('forked');
  await expect(status).toHaveText('已修改');
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').style.fontSize)).toBe(100);
  await page.evaluate(() => MaweHistory.performRedo());
  await expect(status).toHaveText('样式库');
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').style.fontSize)).toBe(120);
});

test('same name with different parameters stays forked and survives offline reopen and swap', async ({ page }) => {
  const saved = await page.evaluate(() => {
    MaweAssManagerWiring.applyProjectStyleSelection('secondary', 'ass-extension');
    const project = JSON.parse(MaweJsonRepair.buildJson());
    const main = project.tracks.find(track => track.role === 'main');
    const snapshot = project.styles.find(style => style.id === main.style.style_id);
    snapshot.fontSize = 123;
    snapshot.fontName = 'Snapshot Fixture';
    return project;
  });
  await page.route('**/api/ass-styles', route => route.abort());
  await page.evaluate(() => localStorage.removeItem('moy.asr.ass.styles.v1'));
  await page.reload();
  await page.waitForFunction(() => window.MaweAssManagerWiring && window.MaweMultiImport);
  const result = await page.evaluate(async project => MaweMultiImport.openProjectFile(new File([JSON.stringify(project)], 'offline.mosp', { type: 'application/json' }), { suppressMediaPrompt: true }), saved);
  expect(result).toBe(true);
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('main').status)).toBe('forked');
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('main').style.fontSize)).toBe(123);
  const exportAss = () => page.evaluate(() => {
    MaweSettings.EDITOR_SETTINGS.assMode = true;
    return MaweExportSrt.buildAss();
  });
  expect(await exportAss()).toContain('Style: Default,Snapshot Fixture,');
  const before = await page.evaluate(() => Object.fromEntries(MaweBoot.DATA.tracks.map(track => [track.id, track.style?.style_id])));
  expect(await page.evaluate(() => MaweMultiImport.swapMainAndExtensionSubtitles())).toBe(true);
  const after = await page.evaluate(() => Object.fromEntries(MaweBoot.DATA.tracks.map(track => [track.id, track.style?.style_id])));
  expect(after).toEqual(before);
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').style.fontSize)).toBe(123);
  expect(await exportAss()).toContain('Style: Extension,Snapshot Fixture,');
});

test('new secondary and overlay tracks capture styles in the same undo transaction', async ({ page }) => {
  await page.evaluate(() => {
    MaweBoot.DATA.tracks = MaweBoot.DATA.tracks.filter(track => track.role === 'main');
    MaweBoot.DATA.bindings = [];
    delete MaweBoot.DATA.bilingual.active_track_id;
    MaweHistory.editorHistory.clear();
    MaweDisplaySettings.updateMultiSubtitleUi();
    MaweSettingsPanels.openEditorSettingsAtTab('editor-settings-tab-project-tracks');
  });
  const secondary = page.locator('[data-track-role="secondary"] [data-track-field="enabled"]');
  page.once('dialog', dialog => dialog.dismiss());
  await secondary.check();
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').status)).toBe('linked');
  await page.evaluate(() => MaweHistory.performUndo());
  expect(await page.evaluate(() => MaweBoot.DATA.tracks.some(track => track.role === 'secondary'))).toBe(false);
  await page.evaluate(() => MaweHistory.performRedo());
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('secondary').status)).toBe('linked');
  const overlay = page.locator('[data-track-role="overlay"] [data-track-field="enabled"]');
  await overlay.check();
  expect(await page.evaluate(() => MaweAssManagerWiring.projectStyleOptions('overlay').status)).toBe('linked');
  await page.evaluate(() => MaweHistory.performUndo());
  expect(await page.evaluate(() => MaweBoot.DATA.tracks.some(track => track.role === 'overlay'))).toBe(false);
  await page.evaluate(() => MaweHistory.performRedo());
  const saved = await page.evaluate(() => JSON.parse(MaweJsonRepair.buildJson()));
  for (const role of ['secondary', 'overlay']) {
    const track = saved.tracks.find(track => track.role === role);
    expect(saved.styles.some(style => style.id === track.style.style_id)).toBe(true);
  }
});

test('preview switches hide stickers with their tracks without changing export', async ({ page }) => {
  await page.evaluate(() => {
    const h = AsrEditorUtils;
    for (const role of ['main', 'secondary']) {
      const track = MaweBoot.DATA.tracks.find(item => item.role === role);
      track.segments[0].start = 0;
      h.assignSubtitleGroup(MaweBoot.DATA, track.segments, [0], 'sticker', { name: role, rel: `${role}.png`, filename: `${role}.png` });
    }
    MaweDom.overlayToggle.checked = true;
    MaweDom.extensionOverlayToggle.checked = true;
    MaweDom.stickerOverlayToggle.checked = true;
    MaweSettings.EDITOR_SETTINGS.stickersEnabled = true;
    MaweStickerOverlay.stickerOverlayDataVersion += 1;
    MaweStickerOverlay.renderStickerOverlay(0);
  });
  const read = () => page.evaluate(() => ({
    preview: MaweStickerOverlay.rebuildStickerIntervals('preview').map(item => item.source.name).sort(),
    export: MaweStickerBurnPlan.collectStickerIntervals().map(item => item.rel).sort(),
  }));
  expect(await read()).toEqual({ preview: ['main', 'secondary'], export: ['main.png', 'secondary.png'] });
  await expect(page.locator('#sticker-overlay-layer img')).toHaveCount(2);
  await page.evaluate(() => { MaweDom.overlayToggle.checked = false; MaweDom.overlayToggle.dispatchEvent(new Event('change')); });
  expect(await read()).toEqual({ preview: ['secondary'], export: ['main.png', 'secondary.png'] });
  await expect(page.locator('#sticker-overlay-layer img')).toHaveCount(1);
  await page.evaluate(() => { MaweDom.extensionOverlayToggle.checked = false; MaweDom.extensionOverlayToggle.dispatchEvent(new Event('change')); });
  expect(await read()).toEqual({ preview: [], export: ['main.png', 'secondary.png'] });
  await expect(page.locator('#sticker-overlay-layer img')).toHaveCount(0);
});

test('importing a project as secondary copies its style and reference metadata', async ({ page }) => {
  const imported = await page.evaluate(async () => {
    const source = JSON.parse(MaweJsonRepair.buildJson());
    const main = source.tracks.find(track => track.role === 'main');
    main.style.vendor = { reference: true };
    const style = source.styles.find(item => item.id === main.style.style_id);
    style.fontSize = 119;
    style.vendor = { snapshot: true };
    const file = new File([JSON.stringify(source)], 'source.mosp', { type: 'application/json' });
    const segments = await MaweLoadingProgress.parseSubtitleImportFile(file);
    MaweMultiImport.pendingMultiImport = { file, segments, existingTrackId: MaweMultiSubtitleCore.getActiveExtensionTrack().id };
    const ok = MaweMultiImport.commitMultiSubtitleImport();
    const secondary = MaweBoot.DATA.tracks.find(track => track.role === 'secondary');
    return { ok, ref: secondary.style, style: MaweBoot.DATA.styles.find(item => item.id === secondary.style.style_id) };
  });
  expect(imported.ok).toBe(true);
  expect(imported.ref.vendor).toEqual({ reference: true });
  expect(imported.style.vendor).toEqual({ snapshot: true });
  expect(imported.style.fontSize).toBe(119);
});
