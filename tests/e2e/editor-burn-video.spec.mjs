import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import http from 'node:http';
import { join } from 'node:path';
import { cleanupTempDir, disableOnboarding, findFreePort, generateWav, generateWaveformPayload, makeTempDir, startServer } from './helpers.mjs';

const source = fs.readFileSync(new URL('../../web/editor/io/editor-wiring-export-actions.js', import.meta.url), 'utf8');
const start = source.indexOf("document.getElementById('download-burn-video')");
const handler = source.slice(start, source.indexOf("document.getElementById('download-json')", start));
if (start < 0) throw new Error('Burn video handler missing');

async function fixture(page, options, run) {
  const requests = [];
  const server = http.createServer((req, res) => {
    if (req.url !== '/burn') return res.end('<button id="download-burn-video">烧录视频</button>');
    let data = '';
    req.on('data', chunk => { data += chunk; });
    req.on('end', () => {
      requests.push(JSON.parse(data));
      res.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': options.truncated ? '20' : '3', Connection: 'close' });
      res.end(Buffer.from('mp4'));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.evaluate(options => {
      window.hints = [];
      window.saved = { bytes: [], closed: false, aborted: false, commits: [] };
      window.MaweBoot = { FILENAME_BASE: 'edited', SERVER_CONFIG: {
        canBurnVideoExport: true, burnVideoExportUrl: '/burn', requestToken: 'token', burnVideoSourceName: 'source.mp4',
      } };
      window.MaweCoreState = { player: { src: options.blob ? 'blob:null/media' : `${location.origin}/media` } };
      window.MaweSettings = { EDITOR_SETTINGS: { assMode: options.ass } };
      window.MaweExportSrt = { buildAss: () => 'edited ASS', buildSrt: () => 'edited SRT' };
      window.MaweInlineEdit = { editingState: {}, extensionEditingState: {},
        finishEdit: () => saved.commits.push('main'), finishExtensionEdit: () => saved.commits.push('extension') };
      window.MaweHint = { flashHint: text => hints.push(text) };
      window.MaweHost = { server: { fetch: (...args) => fetch(...args) }, files: {
        hasSavePicker: () => true,
        pickSaveFile: async () => {
          if (options.cancel) throw new DOMException('Cancelled', 'AbortError');
          return { name: 'edited_subtitled.mp4', createWritable: async () => ({
            write: async chunk => { saved.bytes.push(...chunk); },
            close: async () => { saved.closed = true; }, abort: async () => { saved.aborted = true; },
          }) };
        },
      } };
    }, options);
    await page.addScriptTag({ content: handler });
    await run(requests);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}

for (const ass of [true, false]) {
  test(`burn uses current ${ass ? 'ASS' : 'SRT'} and commits both tracks`, async ({ page }) => {
    await fixture(page, { ass }, async requests => {
      await page.click('#download-burn-video');
      await expect.poll(() => page.evaluate(() => saved.closed)).toBe(true);
      expect(requests).toEqual([{ requestToken: 'token', format: ass ? 'ass' : 'srt', subtitles: ass ? 'edited ASS' : 'edited SRT' }]);
      expect(await page.evaluate(() => saved.commits)).toEqual(['main', 'extension']);
      expect(await page.evaluate(() => saved.bytes)).toEqual([109, 112, 52]);
      await expect(page.locator('#download-burn-video')).toBeEnabled();
    });
  });
}

test('incomplete download aborts file and enables another export', async ({ page }) => {
  await fixture(page, { truncated: true }, async () => {
    await page.click('#download-burn-video');
    await expect.poll(() => page.evaluate(() => hints.some(t => t.includes('导出失败')))).toBe(true);
    expect(await page.evaluate(() => saved.closed)).toBe(false);
    expect(await page.evaluate(() => saved.aborted)).toBe(true);
    await expect(page.locator('#download-burn-video')).toBeEnabled();
  });
});

for (const options of [{ cancel: true }, { blob: true }]) {
  test(`${options.cancel ? 'cancelled picker' : 'browser-only media'} never starts FFmpeg`, async ({ page }) => {
    await fixture(page, options, async requests => {
      await page.click('#download-burn-video');
      await expect(page.locator('#download-burn-video')).toBeEnabled();
      expect(requests).toEqual([]);
      expect(await page.evaluate(() => saved.closed)).toBe(false);
      if (options.cancel) expect(await page.evaluate(() => hints)).toEqual([]);
      else expect(await page.evaluate(() => hints.at(-1))).toContain('绑定当前媒体');
    });
  });
}

test('built editor places burn next to project export and sends edited ASS', async ({ page }) => {
  const dir = makeTempDir('editor-burn');
  let server;
  try {
    const media = join(dir, 'source.wav');
    const project = join(dir, 'project.json');
    generateWav(media, 3);
    fs.writeFileSync(project, JSON.stringify({ media, waveform: generateWaveformPayload(3000),
      segments: [{ id: 'one', start: 500, end: 1500, text: 'Original' }] }));
    server = await startServer(project, media, await findFreePort());
    await disableOnboarding(page);
    await page.addInitScript(() => {
      window.savedVideo = { closed: false, bytes: 0 };
      window.showSaveFilePicker = async options => ({ name: options.suggestedName,
        createWritable: async () => ({
          write: async data => { savedVideo.bytes += data.byteLength; },
          close: async () => { savedVideo.closed = true; }, abort: async () => {},
        }),
      });
    });
    let request;
    await page.route('**/api/exports/burn-video', async route => {
      request = route.request().postDataJSON();
      await route.fulfill({ status: 200, contentType: 'video/mp4', headers: { 'Content-Length': '3' }, body: 'mp4' });
    });
    await page.goto(server.url);
    await page.waitForFunction(() => window.MaweCoreState?.player?.currentSrc.includes('/media'));
    await expect(page.locator('#download-json + #download-burn-video')).toHaveText('烧录视频');
    await page.evaluate(() => {
      window.MaweBoot.DATA.segments[0].text = 'Edited subtitle';
      window.MaweSettings.updateEditorSettings({ assMode: true });
    });
    await page.click('#download-burn-video');
    await expect.poll(() => page.evaluate(() => savedVideo.closed)).toBe(true);
    expect(request.format).toBe('ass');
    expect(request.subtitles).toContain('Edited subtitle');
    expect(request.requestToken).toBeTruthy();
  } finally {
    await server?.stop();
    cleanupTempDir(dir);
  }
});
