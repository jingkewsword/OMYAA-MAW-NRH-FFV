import { test, expect } from '@playwright/test';
import { join } from 'node:path';
import { disableOnboarding, findFreePort, makeTempDir, cleanupTempDir, startBlankServer } from './helpers.mjs';

let directory, server;
test.beforeAll(async () => {
  directory = makeTempDir('selected-ai');
  server = await startBlankServer(await findFreePort(), join(directory, 'settings'));
});
test.afterAll(async () => { await server?.stop(); cleanupTempDir(directory); });

test('translation candidate remains separate until applied and can be undone', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await disableOnboarding(page);
  await page.goto(server.url);
  await page.waitForFunction(() => Boolean(window.MaweCoreState?.waveformEditor));
  await page.evaluate(() => {
    MaweProjectLoad.applyCanonicalProject({ schema: 'moy.asr.project.v1', media: '', segments: [
      { id: 'a', start: 0, end: 500, text: 'Hello' },
      { id: 'b', start: 700, end: 1000, text: 'World' },
    ] }, 'test.mosp');
    // This test stubs the AI endpoint after a browser-side project import.
    // A real server-bound project obtains these values from project binding.
    Object.assign(MaweBoot.SERVER_CONFIG, { bindingGeneration: 1, sourceMediaId: 'mock-binding' });
    MaweSelection.selectOnly(0);
  });
  await page.route('**/api/editor-ai/start', route => route.fulfill({ json: { id: 'fake', state: 'running' } }));
  await page.route('**/api/editor-ai/status', route => route.fulfill({ json: { id: 'fake', state: 'done', result: { translations: [{ id: 'a', text: '你好' }] } } }));
  await page.locator('#editor-ai-menu-btn').click();
  await page.locator('[data-editor-ai="translate"]').click();
  await page.locator('#editor-ai-start').click();
  await expect(page.locator('#editor-ai-apply')).toBeVisible();
  expect(await page.evaluate(() => MaweBoot.DATA.multi_subtitle.tracks.length)).toBe(0);
  await page.evaluate(() => { MaweBoot.DATA.segments[1].text = 'Changed while waiting'; });
  await page.locator('#editor-ai-apply').click();
  expect(await page.evaluate(() => MaweBoot.DATA.multi_subtitle.tracks[0].segments[0].text)).toBe('你好');
  expect(await page.evaluate(() => MaweBoot.DATA.segments[1].text)).toBe('Changed while waiting');
  await page.evaluate(() => MaweHistory.performUndo());
  expect(await page.evaluate(() => MaweBoot.DATA.multi_subtitle.tracks.length)).toBe(0);
  expect(await page.evaluate(() => MaweBoot.DATA.segments[1].text)).toBe('Changed while waiting');
  const gap = await page.evaluate(() => {
    const a = document.querySelector('#editor-ai-description').getBoundingClientRect();
    const b = document.querySelector('#editor-ai-provider-row').getBoundingClientRect();
    return b.top - a.bottom;
  });
  expect(gap).toBeGreaterThanOrEqual(8);
  await page.screenshot({ path: '.artifacts/selected-ai-panel.png' });
  expect(errors).toEqual([]);
});

test('alignment and resegmentation apply validated candidates and reject stale source edits', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await disableOnboarding(page);
  await page.goto(server.url);
  await page.waitForFunction(() => Boolean(window.MaweCoreState?.waveformEditor));
  await page.evaluate(() => {
    MaweProjectLoad.applyCanonicalProject({ schema: 'moy.asr.project.v1', media: '', segments: [
      { id: 'a', start: 0, end: 500, text: '你好' },
      { id: 'b', start: 600, end: 900, text: '呀' },
    ] }, 'test.mosp');
    Object.assign(MaweBoot.SERVER_CONFIG, { bindingGeneration: 1, sourceMediaId: 'mock-binding' });
    MaweSelection.selectOnly(0);
  });
  let operation = '', emptyAlignment = false;
  await page.route('**/api/editor-ai/start', route => {
    operation = route.request().postDataJSON().operation;
    return route.fulfill({ json: { id: 'fake', state: 'running' } });
  });
  await page.route('**/api/editor-ai/status', route => route.fulfill({ json: { id: 'fake', state: 'done', result: operation === 'align'
    ? { aligned: emptyAlignment ? [] : [{ id: 'a', items: [{ text: '你', start: 0, end: 250 }, { text: '好', start: 250, end: 500 }] }], report: {} }
    : { groups: [['c0001a0001'], ['c0001a0002']] } } }));
  await page.locator('#editor-ai-menu-btn').click();
  await page.locator('[data-editor-ai="align"]').click();
  await page.locator('#editor-ai-start').click();
  await expect(page.locator('#editor-ai-apply')).toBeVisible();
  await page.locator('#editor-ai-apply').click();
  expect(await page.evaluate(() => MaweBoot.DATA.segments[0].items.length)).toBe(2);
  await page.evaluate(() => MaweSelection.selectOnly(0));
  await page.locator('#editor-ai-menu-btn').click();
  await page.locator('[data-editor-ai="resegment"]').click();
  await page.locator('#editor-ai-start').click();
  await expect(page.locator('#editor-ai-apply')).toBeVisible();
  await page.evaluate(() => { MaweBoot.DATA.segments[0].text = '已修改'; });
  await page.locator('#editor-ai-apply').click();
  await expect(page.locator('#editor-ai-status')).toContainText('已变化');
  expect(await page.evaluate(() => MaweBoot.DATA.segments.length)).toBe(2);
  await page.evaluate(() => { MaweBoot.DATA.segments[0].text = '你好'; });
  await page.locator('#editor-ai-apply').click();
  expect(await page.evaluate(() => MaweBoot.DATA.segments.map(cue => cue.text))).toEqual(['你', '好', '呀']);
  await page.evaluate(() => MaweHistory.performUndo());
  expect(await page.evaluate(() => MaweBoot.DATA.segments.map(cue => cue.text))).toEqual(['你好', '呀']);
  emptyAlignment = true;
  await page.evaluate(() => MaweSelection.selectOnly(0));
  await page.locator('#editor-ai-menu-btn').click();
  await page.locator('[data-editor-ai="align"]').click();
  await page.locator('#editor-ai-start').click();
  await expect(page.locator('#editor-ai-status')).toContainText('没有可应用的结果');
  await expect(page.locator('#editor-ai-start')).toBeVisible();
  expect(errors).toEqual([]);
});

test('English AI panel preserves literal subtitle text in the candidate preview', async ({ page }) => {
  await disableOnboarding(page);
  await page.addInitScript(() => localStorage.setItem('mawe.language', 'en'));
  await page.goto(server.url);
  await page.waitForFunction(() => Boolean(window.MaweCoreState?.waveformEditor));
  await page.evaluate(() => {
    MaweProjectLoad.applyCanonicalProject({ schema: 'moy.asr.project.v1', media: '', segments: [
      { id: 'a', start: 0, end: 500, text: '关闭', items: [
        { text: '关', start: 0, end: 250 }, { text: '闭', start: 250, end: 500 },
      ] },
    ] }, 'test.mosp');
    Object.assign(MaweBoot.SERVER_CONFIG, { bindingGeneration: 1, sourceMediaId: 'mock-binding' });
    MaweSelection.selectOnly(0);
  });
  await page.route('**/api/editor-ai/start', route => route.fulfill({ json: { id: 'fake', state: 'running' } }));
  await page.route('**/api/editor-ai/status', route => route.fulfill({ json: { id: 'fake', state: 'done', result: { groups: [['c0001a0001', 'c0001a0002']] } } }));
  await page.locator('#editor-ai-menu-btn').click();
  await expect(page.locator('[data-editor-ai="resegment"]')).toHaveText('Resegment subtitles');
  await page.locator('[data-editor-ai="resegment"]').click();
  await expect(page.locator('#editor-ai-title')).toHaveText('Resegment subtitles');
  await page.locator('#editor-ai-start').click();
  await expect(page.locator('#editor-ai-preview')).toHaveText('关闭');
  await expect(page.locator('#editor-ai-status')).toContainText('Review the candidate');
  await page.evaluate(() => window.MAWE_I18N.applyLanguage('zh', false));
  await expect(page.locator('#editor-ai-status')).toContainText('请核对候选结果');
  await page.evaluate(() => window.MAWE_I18N.applyLanguage('en', false));
  await expect(page.locator('#editor-ai-status')).toContainText('Review the candidate');
  await expect(page.locator('#editor-ai-preview')).toHaveText('关闭');
});
