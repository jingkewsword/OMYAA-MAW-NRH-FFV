import assert from 'node:assert/strict';
import test from 'node:test';
import { loadEditorModule } from './helpers/editor-module-loader.mjs';

const context = { window: {} };
loadEditorModule(context, 'shared/editor-utils.js');
const utils = context.window.AsrEditorUtils;
const plain = value => JSON.parse(JSON.stringify(value));

function project() {
  const result = utils.makeProject([
    { id: 'hidden-main', start: 0, end: 4900, text: 'hidden', disabled: true, sticker_group_id: 'sticker-1' },
    { id: 'main-1', start: 5000, end: 6000, text: 'source', color_group_id: 'color-1', sticker_group_id: 'sticker-1' },
  ], { projectFields: { media: '/sample.wav', duration_ms: 8000, gaps: [{ start: 1000, end: 2000, removed: true }],
    subtitle_groups: { next_id: 2, color: [{ id: 'color-1', value: { name: 'yellow' } }],
      sticker: [{ id: 'sticker-1', value: { name: 'cat', path: 'cat.png', width: 720, height: 480 } }] } } });
  result.tracks.push(
    { id: 'active', role: 'secondary', name: 'active', enabled: true,
      segments: [{ id: 'active-1', start: 6000, end: 6500, text: 'translation', color_group_id: 'color-1', sticker_group_id: 'sticker-1' }] },
    { id: 'overlay', role: 'overlay', name: 'overlay', enabled: true, segments: [
      { id: 'hidden-overlay', start: 0, end: 4000, text: 'hidden overlay', disabled: true, sticker_group_id: 'sticker-1' },
      { id: 'overlay-1', start: 6500, end: 6700, text: 'overlap', sticker_group_id: 'sticker-1' },
    ] },
  );
  result.bilingual = { display_mode: 'both', active_track_id: 'active' };
  return result;
}

test('canonical export selects the secondary track and emits a cross-track sticker group once', () => {
  const input = project(); const before = plain(input);
  const plan = utils.buildProjectExportPlan(input, { timelineMode: 'source' });
  assert.deepEqual(Array.from(plan.cues.main, cue => cue.text), ['source']);
  assert.deepEqual(Array.from(plan.cues.extension, cue => cue.text), ['translation']);
  assert.deepEqual(Array.from(plan.cues.overlay, cue => cue.text), ['overlap']);
  assert.equal(plan.stickers.length, 1);
  assert.equal(plan.overlayStickers.length, 0);
  assert.deepEqual([plan.stickers[0].sourceStartMs, plan.stickers[0].sourceEndMs], [0, 6700]);
  assert.equal(plan.cues.main[0].startMs, 5000);
  assert.deepEqual(plain(input), before);
});

test('canonical export maps gaps without changing source tracks or including disabled language members', () => {
  const input = project(); input.tracks.find(track => track.id === 'active').enabled = false;
  const before = plain(input);
  const plan = utils.buildProjectExportPlan(input, { timelineMode: 'gap_removed' });
  assert.equal(plan.cues.extension.length, 0);
  assert.equal(plan.cues.main[0].startMs, 4000);
  assert.deepEqual([plan.stickers[0].startMs, plan.stickers[0].endMs], [0, 5700]);
  assert.equal(input.tracks[0].segments[1].start, 5000);
  assert.deepEqual(plain(input), before);
});

test('explicit future and mixed-schema export documents are rejected without mutation', () => {
  for (const [input, path] of [[Object.assign(project(), { schema: 'moy.asr.project.v99' }), /\$\.schema/],
    [Object.assign(project(), { segments: [] }), /\$\.segments/]]) {
    input.tracks[0].segments[1].items = null;
    const before = plain(input);
    assert.throws(() => utils.buildProjectExportPlan(input, { timelineMode: 'source' }), path);
    assert.deepEqual(plain(input), before);
  }
});

test('runtime null items export without changing tracks or losing waveform duration', () => {
  const input = project();
  delete input.duration_ms;
  input.waveform = { duration_ms: 8000 };
  input.tracks[0].segments[1].items = null;
  input.tracks[2].segments[1].items = null;
  input.tracks[1].segments[0].items = [{ start: 6000, end: 6500, text: 'translation' }];
  const before = plain(input);
  const plan = utils.buildProjectExportPlan(input, { timelineMode: 'source' });
  assert.equal(plan.sourceDurationMs, 8000);
  assert.equal(plan.cues.main[0].text, 'source');
  assert.equal(plan.cues.overlay[0].text, 'overlap');
  assert.equal(plan.cues.extension[0].text, 'translation');
  assert.deepEqual(plain(input), before);
});

test('export still rejects malformed tracks and word timing at their original paths', () => {
  const cases = [
    [p => { p.tracks[0].segments = null; }, /\$\.tracks\[0\]\.segments/],
    [p => { p.tracks[0].segments[0].items = {}; }, /\$\.tracks\[0\]\.segments\[0\]\.items/],
    [p => { p.tracks[0].segments[0].items = 'bad'; }, /\$\.tracks\[0\]\.segments\[0\]\.items/],
    [p => { p.tracks[0].segments[0].items = [{ start: -1, end: 3, text: 'bad' }]; }, /\$\.tracks\[0\]\.segments\[0\]\.items\[0\]\.start/],
  ];
  for (const [mutate, path] of cases) {
    const input = project(); input.tracks[2].segments[1].items = null; mutate(input);
    const before = plain(input);
    assert.throws(() => utils.buildProjectExportPlan(input, { timelineMode: 'source' }), path);
    assert.deepEqual(plain(input), before);
  }
});
