import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
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

test('project style editing clears library selection after fork and allows returning to library editing', async ({ page }) => {
  await page.evaluate(() => MaweAssManagerWiring.openProjectStyleEditor('main'));
  const selected = page.locator('#ass-style-list [aria-selected="true"]');
  await expect(selected).toHaveAttribute('data-ass-selection-id', 'ass');
  const librarySize = await page.evaluate(() => ASS_STYLE_LIBRARY.styles.find(style => style.id === 'ass').fontSize);
  await page.locator('#ass-style-font-size').fill('121');
  await expect(selected).toHaveCount(0);
  expect(await page.evaluate(() => ASS_STYLE_LIBRARY.styles.find(style => style.id === 'ass').fontSize)).toBe(librarySize);
  await page.locator('#ass-style-window-close').click();
  await page.evaluate(() => MaweAssManagerWiring.openProjectStyleEditor('main'));
  await expect(selected).toHaveCount(0);
  await expect(page.locator('#ass-style-font-size')).toHaveValue('121');
  await page.locator('#ass-style-list [data-ass-selection-id="ass"]').click();
  await expect(selected).toHaveAttribute('data-ass-selection-id', 'ass');
  await expect(page.locator('#ass-style-font-size')).toHaveValue(String(librarySize));
});

test('stale project style target cannot write the library after track creation is undone', async ({ page }) => {
  await page.evaluate(() => { MaweBoot.DATA.tracks = MaweBoot.DATA.tracks.filter(track => track.role !== 'overlay'); MaweHistory.editorHistory.clear(); });
  await page.evaluate(() => MaweSettingsPanels.openEditorSettingsAtTab('editor-settings-tab-project-tracks'));
  await page.locator('[data-track-role="overlay"] [data-track-field="enabled"]').check();
  await page.locator('[data-track-role="overlay"] [data-track-style-action="edit"]').click();
  const before = await page.evaluate(() => JSON.stringify(ASS_STYLE_LIBRARY));
  // The floating panel blocks the shortcut; its non-modal undo button remains reachable.
  await page.locator('#undo-btn').evaluate(element => element.click());
  expect(await page.evaluate(() => AsrEditorUtils.getOverlayTrack(MaweBoot.DATA))).toBeNull();
  await expect(page.locator('#ass-style-form')).toBeHidden();
  await page.locator('#ass-style-font-size').evaluate(element => { element.value = '121'; element.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(await page.evaluate(() => JSON.stringify(ASS_STYLE_LIBRARY))).toBe(before);
});

test('project style target is invalidated when another project with the same track id opens', async ({ page }) => {
  await page.evaluate(() => MaweAssManagerWiring.openProjectStyleEditor('main'));
  const before = await page.evaluate(() => JSON.stringify(ASS_STYLE_LIBRARY));
  const epoch = await page.evaluate(() => MaweState.projectEpoch);
  await page.locator('#open-project-file').setInputFiles({ name: 'another.mosp', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ ...canonical, media: '' })) });
  await expect.poll(() => page.evaluate(() => MaweState.projectEpoch)).toBeGreaterThan(epoch);
  await expect(page.locator('#ass-style-form')).toBeHidden();
  const snapshot = await page.evaluate(() => JSON.stringify(MaweBoot.DATA.styles));
  await page.locator('#ass-style-font-size').evaluate(element => { element.value = '121'; element.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(await page.evaluate(() => JSON.stringify(MaweBoot.DATA.styles))).toBe(snapshot);
  expect(await page.evaluate(() => JSON.stringify(ASS_STYLE_LIBRARY))).toBe(before);
});

test('cue style control has 8px spacing without shifting the video stage', async ({ page }, info) => {
  await page.evaluate(() => { MaweSettings.EDITOR_SETTINGS.assMode = true; MaweSelection.clearSelection(); });
  const stage = () => page.locator('.player-stage').evaluate(element => { const r = element.getBoundingClientRect(); return { top: r.top, height: r.height }; });
  const before = await stage();
  await page.evaluate(() => { const track = AsrEditorUtils.getMainTrack(MaweBoot.DATA); MaweCuePanel.setCuePanelTarget('main', 0, track.id); });
  await expect(page.locator('#cue-ass-style-controls')).toBeVisible();
  const gaps = await page.evaluate(() => {
    const target = document.querySelector('#cue-panel-target').getBoundingClientRect();
    const control = document.querySelector('#cue-ass-style-controls').getBoundingClientRect();
    const text = document.querySelector('.cue-panel-text-row').getBoundingClientRect();
    return { above: control.top - target.bottom, below: text.top - control.bottom };
  });
  await page.locator('#current-cue-panel').screenshot({ path: info.outputPath('cue-style-spacing.png') });
  writeFileSync(info.outputPath('cue-style-spacing.json'), JSON.stringify({ gaps, before, after: await stage() }, null, 2));
  expect(gaps.above).toBeGreaterThanOrEqual(8);
  expect(gaps.below).toBeGreaterThanOrEqual(8);
  expect(await stage()).toEqual(before);
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

for (const role of ['main', 'secondary', 'overlay']) test(`cue style selector overrides ${role}, undoes, reopens and clears to track style`, async ({ page }) => {
  const setup = await page.evaluate(role => {
    const track = MaweBoot.DATA.tracks.find(track => track.role === role);
    track.enabled = true;
    const cue = track.segments[0];
    cue.assOverride = { pos: { x: 640, y: 360 }, scale: 1.2 };
    const style = ASS_STYLE_LIBRARY.styles.find(style => style.id === 'ass-extension');
    Object.assign(style, { fontName: 'Arial', fontSize: 103, primaryColor: '#123456' });
    MaweSettings.EDITOR_SETTINGS.assMode = true;
    MaweDom.overlayToggle.checked = true; MaweDom.extensionOverlayToggle.checked = true;
    MaweCuePanel.setCuePanelTarget(role === 'secondary' ? 'extension' : role, 0, track.id);
    MaweHistory.editorHistory.clear();
    return { id: cue.id, trackId: track.id, styles: JSON.parse(JSON.stringify(MaweBoot.DATA.styles)) };
  }, role);
  await page.locator('#cue-ass-style').selectOption('ass-extension');
  const read = () => page.evaluate(id => {
    const cue = MaweBoot.DATA.tracks.flatMap(track => track.segments).find(cue => cue.id === id);
    MawePlaybackLoop.refreshSubtitlePreview(cue.start + 1, 0);
    const item = MaweAssPreview.stackPlan.slices.flatMap(slice => slice.items).find(item => item.segment.id === id);
    return { style: cue.assStyle, pos: cue.assOverride, rendered: item?.style.fontSize,
      styles: MaweBoot.DATA.styles, ass: MaweExportSrt.buildAss(), undo: MaweHistory.editorHistory.undoLength() };
  }, setup.id);
  let current = await read();
  expect(current.style.fontSize).toBe(103);
  expect(current.rendered).toBe(103);
  expect(current.styles).toEqual(setup.styles);
  expect(current.ass).toContain(`Style: Cue_${role === 'secondary' ? 'extension' : role}_0,Arial,103,`);
  expect(current.pos).toEqual({ pos: { x: 640, y: 360 }, scale: 1.2 });
  expect(current.undo).toBe(1);
  await page.evaluate(() => MaweHistory.performUndo());
  expect((await read()).style).toBeUndefined();
  await page.evaluate(() => MaweHistory.performRedo());
  expect((await read()).rendered).toBe(103);
  const saved = await page.evaluate(() => JSON.parse(MaweJsonRepair.buildJson()));
  await page.reload();
  await page.waitForFunction(() => window.MaweMultiImport);
  await page.evaluate(async ({ saved, role, trackId }) => {
    await MaweMultiImport.openProjectFile(new File([JSON.stringify(saved)], 'cue-style.mosp', { type: 'application/json' }), { suppressMediaPrompt: true });
    MaweCuePanel.setCuePanelTarget(role === 'secondary' ? 'extension' : role, 0, trackId);
  }, { saved, role, trackId: setup.trackId });
  expect((await read()).rendered).toBe(103);
  await page.locator('#cue-ass-style').selectOption('');
  current = await read();
  expect(current.style).toBeUndefined();
  expect(current.pos).toEqual({ pos: { x: 640, y: 360 }, scale: 1.2 });
  expect(current.ass).not.toContain(`Style: Cue_${role === 'secondary' ? 'extension' : role}_0,`);
});
