// 服务器接管回归：空白服务器里打开/拖入工程时，服务器应按工程记录的媒体
// 绝对路径定位同目录同名工程并接管——媒体自动加载、保存按钮可用、
// 内容不一致的同名文件不得掉包接管；旧工程接管后仍须显式另存 v2。
import { expect, test } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import {
  cleanupTempDir,
  DURATION_MS,
  findFreePort,
  generateWaveformPayload,
  generateWav,
  getMainTrack,
  makeTempDir,
  startBlankServer,
  testSegments,
} from './helpers.mjs';

let tempDir;
let server;
let projectPath;
let mediaPath;

test.beforeAll(async () => {
  tempDir = makeTempDir('attach');
  mediaPath = join(tempDir, 'synthetic.wav');
  projectPath = join(tempDir, 'project.json');
  generateWav(mediaPath, 5);
  // 工程必须记录媒体的绝对路径，服务器才能按它定位同目录同名工程。
  const project = {
    media: mediaPath,
    segments: testSegments(),
    waveform: generateWaveformPayload(DURATION_MS),
  };
  writeFileSync(projectPath, JSON.stringify(project, null, 2), 'utf-8');
  server = await startBlankServer(await findFreePort(), join(tempDir, '.settings'));
});

test.afterAll(async () => {
  await server?.stop();
  cleanupTempDir(tempDir);
});

function dropProject(page, name, content) {
  const base64 = Buffer.from(content, 'utf-8').toString('base64');
  return page.evaluateHandle(({ base64: data, name: fileName }) => {
    const dt = new DataTransfer();
    const bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
    dt.items.add(new File([bytes], fileName, { type: 'application/json' }));
    return dt;
  }, { base64, name }).then((dataTransfer) => page.dispatchEvent('body', 'drop', { dataTransfer }));
}

// 先跑掉包拒绝：此时服务器仍是空白状态，保存按钮必须保持禁用。
test('a same-named project with different content is not swapped in', async ({ page }) => {
  await page.goto(server.url);
  const tampered = JSON.parse(readFileSync(projectPath, 'utf-8'));
  tampered.segments = [{ start: 0, end: 1000, text: '不是磁盘上的内容', items: [] }];
  await dropProject(page, 'project.json', JSON.stringify(tampered));

  // 接管被拒绝：回退为手动选择媒体，保存保持禁用。
  await expect(page.locator('#project-media-modal')).toHaveClass(/show/);
  await expect(page.locator('#save-project')).toBeDisabled();
});

test('dropping a legacy project lets the blank server take over but saves into a new v2 file', async ({ page }) => {
  await page.goto(server.url);
  const reload = page.waitForEvent('load');
  const original = readFileSync(projectPath, 'utf-8');
  await dropProject(page, 'project.json', original);
  await reload;

  // 接管成功：整页刷新为服务器渲染状态，媒体与保存同时恢复。
  await expect(page.locator('#media-name')).toHaveText('synthetic.wav');
  await expect(page.locator('#project-media-modal')).not.toHaveClass(/show/);
  await expect(page.locator('#save-project')).toBeEnabled();
  const playerSrc = await page.evaluate(() => document.getElementById('player').currentSrc);
  expect(playerSrc).toContain('/media');

  await page.evaluate(() => {
    MaweSettings.updateEditorSettings({ autoSaveProject: false });
    MaweServerSave.scheduleAutoSave();
    MaweServerSave.scheduleAutoSaveFlush();
  });
  await page.locator('.cue').first().click();
  await page.locator('#cue-panel-text').fill('AttachedSave');
  await page.locator('#cue-panel-target').click();
  expect(await page.evaluate(() => ({
    text: AsrEditorUtils.getMainTrack(MaweBoot.DATA).segments[0].text,
    dirty: AsrEditorUtils.getMainTrack(MaweBoot.DATA).segments[0]._dirty,
    canSave: MaweBoot.SERVER_CONFIG.canSave,
  }))).toEqual({ text: 'AttachedSave', dirty: true, canSave: true });
  expect(await page.evaluate(() => MaweServerSave.requiresMigrationSaveAs)).toBe(true);
  await page.evaluate(() => {
    window.migrationWrites = [];
    window.migrationName = '';
    window.showSaveFilePicker = async options => {
      window.migrationName = options.suggestedName;
      return { name: options.suggestedName, getFile: async () => ({ size: 0 }),
        createWritable: async () => ({ write: async blob => window.migrationWrites.push(await blob.text()), close: async () => {} }) };
    };
  });
  let serverWrites = 0;
  page.on('request', request => { if (request.url().endsWith('/api/project') && request.method() === 'POST') serverWrites += 1; });
  await page.keyboard.press('Control+s');
  await expect.poll(() => page.evaluate(() => window.migrationWrites.length)).toBe(1);
  const saved = JSON.parse(await page.evaluate(() => window.migrationWrites[0]));
  expect(await page.evaluate(() => window.migrationName)).toMatch(/_v2\.mosp$/);
  expect(saved.schema).toBe('moy.asr.project.v2');
  expect(getMainTrack(saved).segments[0]).toMatchObject({ id: 'main-cue-1', text: 'AttachedSave' });
  expect(await page.evaluate(() => MaweServerSave.requiresMigrationSaveAs)).toBe(false);
  expect(readFileSync(projectPath, 'utf-8')).toBe(original);
  expect(serverWrites).toBe(0);
});
