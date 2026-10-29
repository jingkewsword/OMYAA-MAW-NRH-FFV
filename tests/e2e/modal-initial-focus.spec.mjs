import { expect, test } from '@playwright/test';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { cleanupTempDir, findFreePort, generateWav, generateWaveformPayload, makeTempDir, startServer } from './helpers.mjs';

let server, tempDir;
test.beforeAll(async () => {
  tempDir = makeTempDir('modal-focus');
  const media = join(tempDir, 'synthetic.wav');
  const project = join(tempDir, 'project.json');
  generateWav(media, 3);
  writeFileSync(project, JSON.stringify({ media: 'synthetic.wav', waveform: generateWaveformPayload(3000),
    segments: Array.from({ length: 100 }, (_, index) => ({ id: `cue-${index}`, start: index * 20,
      end: index * 20 + 20, text: `Subtitle ${index} with enough text to occupy a full editable line.` })) }));
  server = await startServer(project, media, await findFreePort());
});
test.afterAll(async () => { await server?.stop(); cleanupTempDir(tempDir); });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('moy.asr.editor.onboarding.v1', 'completed');
    localStorage.setItem('moy.asr.editor.settings.v1', JSON.stringify({ autoSaveProject: false }));
  });
  await page.goto(server.url);
  await expect(page.locator('.cue[data-idx="0"] .text')).toBeVisible();
});

for (const view of ['rows', 'single']) for (const entry of ['mouse', 'keyboard']) {
  test(`${view} ${entry} opening keeps initial focus, scroll and subsequent user ownership`, async ({ page }) => {
    await page.evaluate(view => {
      MaweBoot.DATA.timed_text_edit_view = view;
      MaweSelection.selectOnly(90);
      // Capture the end of the real click dispatch, including menu cleanup.
      document.addEventListener('click', event => {
        if (event.target.closest('#timed-text-edit-btn')) {
          window.modalInitialFocus = document.activeElement?.id || document.activeElement?.tagName;
        }
      });
    }, view);
    await page.clock.install();
    await page.clock.pauseAt(new Date());
    const menu = page.locator('#batch-operations-btn');
    if (entry === 'mouse') {
      await menu.click();
      await page.locator('#timed-text-edit-btn').click();
    } else {
      await menu.focus();
      await page.keyboard.press('Shift+Tab');
      await expect(page.locator('#timed-text-edit-btn')).toBeFocused();
      await page.keyboard.press('Enter');
    }
    const editor = page.locator(view === 'rows' ? '#timed-text-edit-rows textarea' : '#timed-text-edit-single-textarea').first();
    expect(await page.evaluate(() => window.modalInitialFocus)).toBe(view === 'rows' ? 'TEXTAREA' : 'timed-text-edit-single-textarea');
    await expect(editor).toBeFocused();
    if (view === 'rows') {
      await expect(page.locator('.timed-text-edit-row[data-index="90"]')).toBeInViewport();
    } else {
      expect(await editor.evaluate(el => ({ caret: el.selectionStart, scroll: el.scrollTop }))).toEqual({
        caret: await page.evaluate(() => MaweDom.timedTextEditDraft.texts.slice(0, 90).reduce((sum, text) => sum + text.length + 1, 0)),
        scroll: expect.any(Number),
      });
      expect(await editor.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    }
    await page.keyboard.press('Tab');
    expect(await editor.evaluate(el => document.activeElement === el)).toBe(false);
    await page.keyboard.press('Shift+Tab');
    await expect(editor).toBeFocused();
    if (entry === 'keyboard') {
      await page.keyboard.press('Home');
      await page.keyboard.press('Shift+ArrowRight');
      const earlySelection = await editor.evaluate(el => [el.selectionStart, el.selectionEnd]);
      expect(earlySelection[1] - earlySelection[0]).toBe(1);
      await page.clock.runFor(100);
      expect(await editor.evaluate(el => [el.selectionStart, el.selectionEnd])).toEqual(earlySelection);
      await page.keyboard.type('X');
    }
    await page.keyboard.press('Control+f');
    const search = page.locator('#timed-text-edit-find');
    await expect(search).toBeFocused();
    await page.keyboard.type('Subtitle');
    await page.clock.runFor(100);
    await expect(search).toBeFocused();
    await expect(search).toHaveValue('Subtitle');
    await editor.focus();
    await page.keyboard.press('Home');
    await page.keyboard.press('Shift+ArrowRight');
    const selection = await editor.evaluate(el => [el.selectionStart, el.selectionEnd]);
    await page.clock.runFor(100);
    expect(await editor.evaluate(el => [el.selectionStart, el.selectionEnd])).toEqual(selection);
    await page.keyboard.type('X');
    await page.clock.runFor(100);
    await expect(editor).toBeFocused();
    expect(await editor.inputValue()).toContain('X');
  });
}

test('custom wrapping real context-menu click focuses once and preserves Tab and typing', async ({ page }) => {
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  await page.locator('.cue[data-idx="0"] .text').click({ button: 'right' });
  await page.getByText('左右添加字符', { exact: true }).click();
  await page.locator('#ctxmenu').getByText('自定义…', { exact: true }).click();
  const left = page.locator('#wrap-chars-left'), right = page.locator('#wrap-chars-right');
  await expect(left).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(right).toBeFocused();
  await page.keyboard.type('RIGHT');
  await page.clock.runFor(100);
  await expect(right).toBeFocused();
  await expect(right).toHaveValue('RIGHT');
  await page.keyboard.press('Shift+Tab');
  await expect(left).toBeFocused();
});
