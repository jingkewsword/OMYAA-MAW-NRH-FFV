import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(new URL('../web/editor/cues/editor-ai-core.js', import.meta.url), 'utf8'), context);
const core = context.MaweEditorAiCore;
const project = () => ({ segments: [
  { id: 'a', start: 0, end: 500, text: '你好', items: [{ text: '你', start: 0, end: 250 }, { text: '好', start: 250, end: 500 }] },
  { id: 'b', start: 600, end: 900, text: '呀', items: [{ text: '呀', start: 600, end: 900 }] },
  { id: 'c', start: 1000, end: 1200, text: '外', items: [{ text: '外', start: 1000, end: 1200 }] },
], multi_subtitle: { schema: 'moy.asr.multi_subtitle.v1', enabled: false, display_mode: 'both', tracks: [], bindings: [] } });
let serial = 0;
const id = () => `test-${++serial}`;

test('translation updates only selected subtitle binding and rejects conflicting edits', () => {
  const data = project(), snap = core.capture(data, [0], 'translate');
  data.segments[2].text = '未选中字幕可继续编辑';
  core.ensureCurrent(data, snap);
  core.applyTranslation(data, snap, [{ id: 'a', text: 'hello' }], 'en', id);
  assert.equal(data.multi_subtitle.tracks[0].segments[0].text, 'hello');
  assert.deepEqual(Array.from(data.multi_subtitle.bindings[0].main_segment_ids), ['a']);
  assert.equal(data.segments[2].text, '未选中字幕可继续编辑');
  assert.throws(() => core.ensureCurrent(data, snap), /关联字幕/);
});

test('translation preserves an existing English track and unrelated subtitles', () => {
  const data = project();
  data.multi_subtitle = { enabled: true, display_mode: 'both', tracks: [{ id: 'ext', language: 'English', segments: [
    { id: 'ea', start: 0, end: 500, text: 'old', items: [{ text: 'old', start: 0, end: 500 }] },
    { id: 'ec', start: 1000, end: 1200, text: 'untouched' },
  ] }], bindings: [{ id: 'binding', track_id: 'ext', main_segment_ids: ['a'], extension_segment_ids: ['ea'], start_offset_ms: 0, end_offset_ms: 0 }] };
  const snap = core.capture(data, [0], 'translate');
  core.applyTranslation(data, snap, [{ id: 'a', text: 'new' }], 'en', id);
  assert.equal(data.multi_subtitle.tracks[0].language, 'English');
  assert.equal(data.multi_subtitle.tracks[0].segments[0].text, 'new');
  assert.equal(data.multi_subtitle.tracks[0].segments[0].items, undefined);
  assert.equal(data.multi_subtitle.tracks[0].segments[1].text, 'untouched');
});

test('invalid translation and timecodes do not partially mutate project', () => {
  const data = project(), snap = core.capture(data, [0, 1], 'align');
  const before = JSON.stringify(data);
  assert.throws(() => core.applyAlignment(data, snap, [
    { id: 'a', items: [{ text: '你好', start: 0, end: 500 }] },
    { id: 'b', items: [{ text: '呀', start: 600, end: 999 }] },
  ]), /范围/);
  assert.equal(JSON.stringify(data), before);
  assert.throws(() => core.applyTranslation(data, snap, [{ id: 'a', text: 'hi' }], 'en', id), /不完整/);
  assert.equal(JSON.stringify(data), before);
});

test('resegment preserves every item and detects edits to the selection', () => {
  const data = project(), snap = core.capture(data, [0, 1], 'resegment');
  core.applyResegment(data, snap, [['c0001a0001'], ['c0001a0002', 'c0002a0001']], id);
  assert.deepEqual(Array.from(data.segments, s => s.text), ['你', '好呀', '外']);
  assert.equal(data.segments[1].items.length, 2);
  assert.throws(() => core.ensureCurrent(data, snap), /变化/);
});

test('resegment refuses bound cues and timing changes tied to cleanup scopes', () => {
  const data = project();
  data.multi_subtitle.bindings.push({ main_segment_ids: ['a'] });
  assert.throws(() => core.capture(data, [0], 'resegment'), /绑定/);
  data.gap_remove = { provenance: { sources: { ai_cleanup: [{ cleanup_scope: { segment_id: 'a' } }] } } };
  assert.throws(() => core.capture(data, [0], 'align'), /删词范围/);
});
