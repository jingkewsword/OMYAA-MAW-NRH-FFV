import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(new URL('../web/editor/cues/editor-ai-core.js', import.meta.url), 'utf8'), context);
const rawCore = context.MaweEditorAiCore;
const core = { ...rawCore, capture(data, ...args) {
  if (data.multi_subtitle) {
    const migrated = model.importProject({ segments: rawCore.mainSegments(data), multi_subtitle: data.multi_subtitle }).project;
    data.tracks = migrated.tracks; data.bindings = migrated.bindings; data.bilingual = migrated.bilingual;
    delete data.multi_subtitle;
  }
  return rawCore.capture(data, ...args);
} };
const model = (await import(`data:text/javascript;base64,${Buffer.from(fs.readFileSync(new URL('../web/shared/utils/project-tracks.js', import.meta.url))).toString('base64')}`)).createUtilsModule();
const project = () => model.importProject({ segments: [
  { id: 'a', start: 0, end: 500, text: '你好', items: [{ text: '你', start: 0, end: 250 }, { text: '好', start: 250, end: 500 }] },
  { id: 'b', start: 600, end: 900, text: '呀', items: [{ text: '呀', start: 600, end: 900 }] },
  { id: 'c', start: 1000, end: 1200, text: '外', items: [{ text: '外', start: 1000, end: 1200 }] },
], multi_subtitle: { schema: 'moy.asr.multi_subtitle.v1', enabled: false, display_mode: 'both', tracks: [], bindings: [] } }).project;
let serial = 0;
const id = () => `test-${++serial}`;

test('translation updates only selected subtitle binding and rejects conflicting edits', () => {
  const data = project(), snap = core.capture(data, [0], 'translate');
  core.mainSegments(data)[2].text = '未选中字幕可继续编辑';
  core.ensureCurrent(data, snap);
  core.applyTranslation(data, snap, [{ id: 'a', text: 'hello' }], 'en', id);
  assert.equal(data.tracks.find(t => t.role === 'secondary').segments[0].text, 'hello');
  assert.deepEqual([data.bindings[0].source.segment_id], ['a']);
  assert.equal(core.mainSegments(data)[2].text, '未选中字幕可继续编辑');
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
  assert.equal(data.tracks.find(t => t.role === 'secondary').language, 'English');
  assert.equal(data.tracks.find(t => t.role === 'secondary').segments[0].text, 'new');
  assert.equal(data.tracks.find(t => t.role === 'secondary').segments[0].items, undefined);
  assert.equal(data.tracks.find(t => t.role === 'secondary').segments[1].text, 'untouched');
});

test('unchanged translation retains existing word timestamps exactly', () => {
  const data = project();
  const items = [{ text: 'old', start: 0, end: 500, speaker: 'speaker1' }];
  data.multi_subtitle = { tracks: [{ id: 'ext', language: 'en', segments: [{ id: 'ea', start: 0, end: 500, text: 'old', items }] }], bindings: [{ track_id: 'ext', main_segment_ids: ['a'], extension_segment_ids: ['ea'] }] };
  core.applyTranslation(data, core.capture(data, [0], 'translate'), [{ id: 'a', text: 'old' }], 'en', id);
  assert.equal(JSON.stringify(data.tracks.find(t => t.role === 'secondary').segments[0].items), JSON.stringify(items));
});

test('fill rejects replacing even partial and zero-width existing items', () => {
  const data = project();
  core.mainSegments(data)[0].items = [{ text: '好', start: 250, end: 500 }, { text: '。', start: 500, end: 500 }];
  const snap = core.capture(data, [0], 'align'), before = JSON.stringify(data);
  assert.throws(() => core.applyAlignment(data, snap, [{ id: 'a', items: [{ text: '你好', start: 0, end: 500 }] }], 'fill'), /不能覆盖/);
  assert.equal(JSON.stringify(data), before);
});

test('resegment rejects changed group table', () => {
  const data = project(); data.subtitle_groups = { color: [], sticker: [] };
  const snap = core.capture(data, [0], 'resegment');
  data.subtitle_groups.color.push({ id: 'color-1', value: { name: 'blue' } });
  assert.throws(() => core.ensureCurrent(data, snap), /分组已变化/);
});

test('invalid translation and timecodes do not partially mutate project', () => {
  const data = project(), snap = core.capture(data, [0, 1], 'align');
  const before = JSON.stringify(data);
  assert.throws(() => core.applyAlignment(data, snap, [
    { id: 'a', items: [{ text: '你好', start: 0, end: 500 }] },
    { id: 'b', items: [{ text: '呀', start: 600, end: 999 }] },
  ], 'generate'), /范围/);
  assert.equal(JSON.stringify(data), before);
  assert.throws(() => core.applyTranslation(data, snap, [{ id: 'a', text: 'hi' }], 'en', id), /不完整/);
  assert.equal(JSON.stringify(data), before);
});

test('resegment preserves every item and detects edits to the selection', () => {
  const data = project(), snap = core.capture(data, [0, 1], 'resegment');
  core.applyResegment(data, snap, [['c0001a0001'], ['c0001a0002', 'c0002a0001']], id);
  assert.deepEqual(Array.from(core.mainSegments(data), s => s.text), ['你', '好呀', '外']);
  assert.equal(core.mainSegments(data)[1].items.length, 2);
  assert.throws(() => core.ensureCurrent(data, snap), /变化/);
});

test('resegment refuses bound cues and timing changes tied to cleanup scopes', () => {
  const data = project();
  data.bindings.push({ source: { track_id: 'main', segment_id: 'a' }, target: { track_id: 'secondary', segment_id: 'b' } });
  assert.throws(() => core.capture(data, [0], 'resegment'), /绑定/);
  data.gap_remove = { provenance: { sources: { ai_cleanup: [{ cleanup_scope: { segment_id: 'a' } }] } } };
  assert.throws(() => core.capture(data, [0], 'align'), /删词范围/);
});


test('v2 translation survives canonical serialization and protects binding changes', () => {
  const data = project(), snap = core.capture(data, [0], 'translate');
  core.applyTranslation(data, snap, [{ id: 'a', text: 'Hello' }], 'en', id);
  assert.equal(model.validateTracksProject(data).ok, true);
  const reopened = model.importProject(JSON.parse(JSON.stringify(data))).project;
  assert.equal(reopened.tracks.find(t => t.role === 'secondary').segments[0].text, 'Hello');
  assert.equal('multi_subtitle' in reopened, false);
  assert.equal('segments' in reopened, false);
  const pending = core.capture(reopened, [0], 'translate');
  reopened.bindings[0].start_offset_ms = 1;
  assert.throws(() => core.ensureCurrent(reopened, pending), /关联字幕/);
});

test('v2 track swap invalidates pending candidate even when cue contents match', () => {
  const data = project(), snap = core.capture(data, [0], 'align');
  data.tracks[0].id = 'another-main';
  assert.throws(() => core.ensureCurrent(data, snap), /主字幕轨/);
});

test('v2 resegmentation remains valid after save and reopen', () => {
  const data = project(), snap = core.capture(data, [0, 1], 'resegment');
  core.applyResegment(data, snap, [['c0001a0001'], ['c0001a0002', 'c0002a0001']], id);
  assert.equal(model.validateTracksProject(data).ok, true);
  assert.equal(model.importProject(JSON.parse(JSON.stringify(data))).project.tracks[0].segments.length, 3);
});


test('AI preserves existing speakers and refuses cross-speaker resegmentation', () => {
  const data = project();
  core.mainSegments(data)[0].speaker = 'A';
  core.mainSegments(data)[1].speaker = 'B';
  const before = JSON.stringify(data);
  assert.throws(() => core.capture(data, [0, 1], 'resegment'), /说话人/);
  assert.equal(JSON.stringify(data), before);
  core.applyAlignment(data, core.capture(data, [0], 'align'), [{ id: 'a', items: [{ text: '你好', start: 0, end: 500 }] }], 'generate');
  assert.equal(core.mainSegments(data)[0].speaker, 'A');
  core.applyTranslation(data, core.capture(data, [0], 'translate'), [{ id: 'a', text: 'Hello' }], 'en', id);
  const secondary = data.tracks.find(t => t.role === 'secondary');
  secondary.segments[0].speaker = 'translator';
  core.applyTranslation(data, core.capture(data, [0], 'translate'), [{ id: 'a', text: 'Hi' }], 'en', id);
  assert.equal(data.tracks.find(t => t.role === 'secondary').segments[0].speaker, 'translator');
  assert.equal(core.mainSegments(data)[0].speaker, 'A');
  const split = project();
  core.mainSegments(split)[0].speaker = 'A';
  core.applyResegment(split, core.capture(split, [0], 'resegment'), [['c0001a0001'], ['c0001a0002']], id);
  assert.deepEqual(core.mainSegments(split).slice(0, 2).map(c => c.speaker), ['A', 'A']);
});


test('speaker identity table is preserved and changes invalidate pending AI', () => {
  const data = project();
  data.speakers = [{ id: 'person-1', name: 'Alice', color: '#ffcc00' }];
  core.mainSegments(data)[0].speaker = 'person-1';
  const original = JSON.stringify(data.speakers);
  const snap = core.capture(data, [0], 'translate');
  core.applyTranslation(data, snap, [{ id: 'a', text: 'Hi' }], 'en', id);
  assert.equal(JSON.stringify(data.speakers), original);
  const pending = core.capture(data, [0], 'align');
  data.speakers[0].id = 'replacement';
  assert.throws(() => core.ensureCurrent(data, pending), /身份表/);
});
