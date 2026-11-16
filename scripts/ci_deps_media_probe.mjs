// Temporary experiment: actually decode generated audio and video in Chromium.
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const dir = '.artifacts/deps-experiment';
mkdirSync(dir, { recursive: true });
const result = { capabilities: {}, playback: {} };
let browser;
try {
  for (const [name, args] of Object.entries({
    mp4: ['-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest'],
    wav: ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1', '-c:a', 'pcm_s16le'],
  })) execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...args, `${dir}/probe.${name}`], { stdio: 'inherit' });
  result.mp4Streams = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,codec_type', '-of', 'json', `${dir}/probe.mp4`], { encoding: 'utf8' }));
  browser = await chromium.launch();
  result.chromiumVersion = browser.version();
  const page = await browser.newPage();
  result.capabilities = await page.evaluate(() => {
    const video = document.createElement('video');
    const audio = document.createElement('audio');
    return { h264_aac: video.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'),
      wav: audio.canPlayType('audio/wav; codecs="1"') };
  });
  for (const [name, mime] of Object.entries({ mp4: 'video/mp4', wav: 'audio/wav' })) {
    const data = readFileSync(`${dir}/probe.${name}`).toString('base64');
    result.playback[name] = await page.evaluate(async ({ name, mime, data }) => {
      const media = document.createElement(name === 'wav' ? 'audio' : 'video');
      const context = new AudioContext();
      const source = context.createMediaElementSource(media);
      const analyser = context.createAnalyser();
      const silent = context.createGain();
      silent.gain.value = 0;
      source.connect(analyser).connect(silent).connect(context.destination);
      media.src = `data:${mime};base64,${data}`;
      return await new Promise(resolve => {
        let peak = 0;
        const samples = new Float32Array(analyser.fftSize);
        const sampler = setInterval(() => { analyser.getFloatTimeDomainData(samples); for (const sample of samples) peak = Math.max(peak, Math.abs(sample)); }, 30);
        const finish = value => { clearTimeout(timer); clearInterval(sampler); context.close(); resolve(value); };
        const timer = setTimeout(() => finish({ ok: false, error: 'timeout' }), 10000);
        media.onended = () => finish({ ok: peak > 0.001 && (name !== 'mp4' || media.videoWidth > 0), duration: media.duration, audio_peak: peak, video_width: media.videoWidth || null });
        media.onerror = () => finish({ ok: false, error: media.error?.message });
        context.resume().then(() => media.play()).catch(error => finish({ ok: false, error: String(error) }));
      });
    }, { name, mime, data });
  }
  if (Object.values(result.playback).some(item => !item.ok)) process.exitCode = 1;
} catch (error) {
  result.error = String(error.stack || error);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  writeFileSync(`${dir}/media-probe.json`, JSON.stringify(result, null, 2));
}
