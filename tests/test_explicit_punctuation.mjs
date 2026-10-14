import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import { loadEditorModule } from './helpers/editor-module-loader.mjs';

const plain = (value) => JSON.parse(JSON.stringify(value));
const read = (file) => fs.readFileSync(new URL(`../web/${file}`, import.meta.url), 'utf8');

function fixture() {
  const elements = new Map();
  const element = () => ({ checked: false, disabled: false, value: '', style: {},
    classList: { add() {}, remove() {}, toggle() {} }, replaceChildren() {}, focus() {},
  });
  const context = { window: {}, document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    querySelectorAll() { return []; },
  }, setTimeout() {} };
  loadEditorModule(context, 'shared/editor-utils.js');
  Object.assign(context, {
    MaweBoot: { DATA: { segments: [], gap_remove: { provenance: { sources: { ai_cleanup: [] } } } } },
    MaweSelection: { selectedIdxs: new Set(), selectedExtensionIdxs: new Set() },
    MaweInlineEdit: {}, MaweDom: { textProcessModal: element() },
    MaweState: { changes: {} }, MaweHint: { flashHint(message, kind) {
      (context.hints ||= []).push({ message, kind });
    } },
    MaweGapRemoveUi: { updateGapRemoveUi() {} },
    MaweMultiSubtitleCore: {
      getActiveExtensionTrack() { return context.track; },
      getExtensionTrack(id) { return context.track?.id === id ? context.track : null; },
      markMainSegmentsDirty() {}, markMultiSubtitleDirty() {}, syncBindingOffsets() {},
    },
    MaweCommands: { run(label, mutation, options) {
      context.commandOptions = options;
      context.commandCount = (context.commandCount || 0) + 1;
      mutation({ commit() {} });
    } },
  });
  vm.runInNewContext(read('editor/cues/editor-text-cleanup.js'), context);
  context.MaweTextCleanup = context.window.MaweTextCleanup;
  vm.runInNewContext(read('editor/cues/editor-text-process.js'), context);
  context.MaweTextProcess = context.window.MaweTextProcess;
  return { context, helpers: context.window.AsrEditorUtils, elements };
}

const cue = () => ({ id: 'cue-a', start: 0, end: 1000, text: '甲，乙。',
  items: [{ start: 0, end: 400, text: '甲，' }, { start: 400, end: 1000, text: '乙。' }] });
const scope = (text) => ({ start: 0, end: 1000,
  cleanup_scope: { segment_id: 'cue-a', item_start: 0, item_end: 2, text } });

test('explicit cleanup preserves all punctuation except Chinese commas/full stops', () => {
  const { helpers } = fixture();
  assert.equal(helpers.applyTextProcessing('  甲，乙。'), '  甲，乙。');
  assert.equal(helpers.cleanChinesePunctuation('  甲，乙。'), '  甲  乙');
  assert.equal(helpers.cleanChinesePunctuation('甲,乙.!?！？；：「」…—、．，。 \t'), '甲,乙.!?！？；：「」…—、．');
  assert.equal(helpers.cleanChinesePunctuation('甲。\n乙，。'), '甲  \n乙');
  assert.equal(helpers.cleanChinesePunctuation('，。'), '');
});

test('cleanup trims only the true string end and preserves trailing line separators', () => {
  const { helpers } = fixture();
  for (const separator of ['\n', '\r\n', '\r', '\u2028', '\u2029']) {
    const text = `甲。${separator}`;
    const next = helpers.planChinesePunctuationCleanup({ text,
      items: [{ start: 0, end: 10, text: '甲。' }, { start: 10, end: 20, text: separator }] });
    assert.equal(next.text, `甲  ${separator}`);
    assert.equal(next.items.map((item) => item.text).join(''), next.text);
    const singleItem = helpers.planChinesePunctuationCleanup({ text, items: [{ start: 0, end: 20, text }] });
    assert.equal(singleItem.items[0].text, next.text);
    assert.equal(helpers.cleanChinesePunctuation(`甲。${separator}，。 \t`), `甲  ${separator}`);
  }
  assert.equal(helpers.cleanChinesePunctuation('甲。\u00a0'), '甲  \u00a0');
});

test('item cleanup keeps boundaries, empty items, extra properties and source immutable', () => {
  const { helpers } = fixture();
  const source = { ...cue(), text: '甲，乙。，。 \t', items: [
    { start: 0, end: 400, text: '甲，', confidence: 0.9 },
    { start: 400, end: 800, text: '乙。' },
    { start: 800, end: 1000, text: '，。 \t' },
  ] };
  const snapshot = plain(source);
  const next = helpers.planChinesePunctuationCleanup(source);
  assert.equal(next.text, '甲  乙');
  assert.equal(next.items.map((item) => item.text).join(''), next.text);
  assert.deepEqual(plain(next.items.map(({ start, end }) => ({ start, end }))), source.items.map(({ start, end }) => ({ start, end })));
  assert.equal(next.items.length, 3);
  assert.equal(next.items[2].text, '');
  assert.equal(next.items[0].confidence, 0.9);
  assert.deepEqual(source, snapshot);
});

test('already valid AI scope follows punctuation, stale scope never revives', () => {
  const { context, helpers } = fixture();
  const source = cue();
  const valid = scope(source.text), stale = scope('甲  乙'), unrelated = scope('unrelated');
  const ranges = context.MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup;
  ranges.push(valid, stale, unrelated);
  const next = helpers.planChinesePunctuationCleanup(source);
  const updates = context.MaweTextCleanup.planPunctuationCleanupScopeUpdates(source, next);
  assert.equal(updates.length, 2);
  updates.forEach(context.MaweTextCleanup.applyPunctuationCleanupScopeUpdate);
  assert.equal(valid.cleanup_scope.text, '甲  乙');
  assert.equal(context.window.AsrGapRemoveCore.getCleanupScopeItems(next, valid).length, 2);
  assert.equal(stale.cleanup_scope, undefined);
  assert.equal(unrelated.cleanup_scope.text, 'unrelated');
});

test('empty timed punctuation anchors keep nonempty scopes valid without authorizing empty scopes', () => {
  const { context, helpers } = fixture();
  const source = { id: 'cue-a', start: 0, end: 1000, text: '甲。',
    items: [{ start: 0, end: 800, text: '甲' }, { start: 800, end: 1000, text: '。' }] };
  const range = { start: 0, end: 1000,
    cleanup_scope: { segment_id: 'cue-a', item_start: 0, item_end: 2, text: '甲。' } };
  context.MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup.push(range);
  const next = helpers.planChinesePunctuationCleanup(source);
  context.MaweTextCleanup.planPunctuationCleanupScopeUpdates(source, next)
    .forEach(context.MaweTextCleanup.applyPunctuationCleanupScopeUpdate);
  const core = context.window.AsrGapRemoveCore;
  assert.equal(range.cleanup_scope.text, '甲');
  assert.equal(core.getCleanupScopeItems(next, range).length, 2);
  const emptyRange = { start: 800, end: 1000,
    cleanup_scope: { segment_id: 'cue-a', item_start: 1, item_end: 2, text: '' } };
  assert.equal(core.getCleanupScopeItems(next, emptyRange).length, 0);
  assert.equal(core.getCleanupScopeItems({ ...next, text: '乙' }, range).length, 0);
  assert.equal(core.getCleanupScopeItems({ ...next, items: [next.items[0], { ...next.items[1], start: 799 }] }, range).length, 0);
});

test('actual cleanup export wrapper projects valid scoped words with empty anchors', () => {
  const { context, helpers } = fixture();
  const core = context.window.AsrGapRemoveCore;
  const source = { id: 'cue-a', start: 0, end: 1000, text: '啊，正，文。', items: [
    { start: 0, end: 300, text: '啊，' }, { start: 300, end: 900, text: '正，文' },
    { start: 900, end: 1000, text: '。' },
  ] };
  const range = { start: 0, end: 300,
    cleanup_scope: { segment_id: 'cue-a', item_start: 0, item_end: 1, text: '啊，' } };
  context.MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup.push(range);
  const next = helpers.planChinesePunctuationCleanup(source);
  context.MaweTextCleanup.planPunctuationCleanupScopeUpdates(source, next)
    .forEach(context.MaweTextCleanup.applyPunctuationCleanupScopeUpdate);
  const gap = core.normalizeGapRemoveData(context.MaweBoot.DATA.gap_remove);
  const before = plain(next);
  const projected = helpers.buildAiCleanupSegments([next], gap)[0];
  assert.equal(projected.text, '正  文');
  assert.deepEqual(plain(projected.items.map((item) => item.text)), ['正  文', '']);
  assert.deepEqual(plain(next), before, 'export projection must not mutate raw source');
  const invalidMapping = { ...next, text: `额外${next.text}` };
  assert.equal(helpers.buildAiCleanupSegments([invalidMapping], gap)[0], invalidMapping);
  const invalidTiming = { ...next, items: next.items.map((item) => ({ ...item })) };
  invalidTiming.items[2].start = 899;
  assert.equal(helpers.buildAiCleanupSegments([invalidTiming], gap)[0], invalidTiming);
  const emptyGap = core.normalizeGapRemoveData({ provenance: { sources: { ai_cleanup: [{ start: 900, end: 1000,
    cleanup_scope: { segment_id: 'cue-a', item_start: 2, item_end: 3, text: '' } }] } } });
  assert.equal(helpers.buildAiCleanupSegments([next], emptyGap)[0], next);
});

test('invalid items stay invalid and receive no invented words or timings', () => {
  const { context, helpers } = fixture();
  const source = cue();
  source.items[1].text = '另。';
  const range = scope('甲，另。');
  context.MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup.push(range);
  const next = helpers.planChinesePunctuationCleanup(source);
  assert.equal(next.text, '甲  乙');
  assert.equal(next.items[1].text, '另');
  assert.equal(context.MaweTextCleanup.planPunctuationCleanupScopeUpdates(source, next).length, 0);
  assert.equal(context.window.AsrGapRemoveCore.getCleanupScopeItems(next, range).length, 0);
});

test('selected main and secondary cues clean atomically, unselected cues stay unchanged', () => {
  const { context } = fixture();
  const data = context.MaweBoot.DATA;
  data.segments.push(cue(), { ...cue(), id: 'untouched' });
  const valid = scope('甲，乙。');
  const originalGapData = data.gap_remove;
  data.gap_remove.provenance.sources.ai_cleanup.push(valid);
  context.track = { id: 'secondary', segments: [cue()] }; // same cue ID must not grant main-scope authority
  const targets = [{ kind: 'main', index: 0 }, { kind: 'extension', index: 0, trackId: 'secondary' }];
  const options = { cleanChinesePunctuation: true };
  const rows = context.MaweTextProcess.buildTextProcessPreview(targets, options);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].after, '甲  乙');
  context.MaweTextProcess.applyPunctuationTextProcessing(rows, options);
  assert.equal(data.segments[0].text, '甲  乙');
  assert.equal(data.segments[1].text, '甲，乙。');
  assert.equal(context.track.segments[0].text, '甲  乙');
  assert.equal(valid.cleanup_scope.text, '甲  乙');
  assert.equal(context.commandCount, 1);
  assert.deepEqual(plain(context.commandOptions), { captureGapRemove: true });
  assert.equal(context.MaweState.changes.gapRemoveDirty, true);
  assert.notEqual(data.gap_remove, originalGapData, 'publish a new reference to invalidate normalized gap caches');
});

test('secondary-only cleanup cannot migrate or remove a main-track AI scope', () => {
  const { context } = fixture();
  context.MaweBoot.DATA.segments.push(cue());
  const range = scope('甲  乙');
  context.MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup.push(range);
  context.track = { id: 'secondary', segments: [cue()] };
  const options = { cleanChinesePunctuation: true };
  const rows = context.MaweTextProcess.buildTextProcessPreview([{ kind: 'extension', index: 0, trackId: 'secondary' }], options);
  context.MaweTextProcess.applyPunctuationTextProcessing(rows, options);
  assert.equal(range.cleanup_scope.text, '甲  乙');
  assert.equal(context.MaweState.changes.gapRemoveDirty, undefined);
});

test('cleaning a punctuation-only cue keeps an empty cue and its item timing', () => {
  const { context } = fixture();
  context.MaweBoot.DATA.segments.push({ id: 'empty', start: 10, end: 20, text: '，。',
    items: [{ start: 10, end: 20, text: '，。' }] });
  const options = { cleanChinesePunctuation: true };
  const rows = context.MaweTextProcess.buildTextProcessPreview([{ kind: 'main', index: 0 }], options);
  context.MaweTextProcess.applyPunctuationTextProcessing(rows, options);
  const segments = context.MaweBoot.DATA.segments;
  assert.equal(segments.length, 1);
  assert.equal(segments[0].text, '');
  assert.deepEqual(plain(segments[0].items), [{ start: 10, end: 20, text: '' }]);
});

test('combining capitalization with punctuation does not authorize changed AI words', () => {
  const { context } = fixture();
  const source = { id: 'cue-a', start: 0, end: 1000, text: 'hello，world。',
    items: [{ start: 0, end: 400, text: 'hello，' }, { start: 400, end: 1000, text: 'world。' }] };
  const range = scope(source.text);
  context.MaweBoot.DATA.segments.push(source);
  context.MaweBoot.DATA.gap_remove.provenance.sources.ai_cleanup.push(range);
  const options = { cleanChinesePunctuation: true, capitalize: true };
  const rows = context.MaweTextProcess.buildTextProcessPreview([{ kind: 'main', index: 0 }], options);
  context.MaweTextProcess.applyPunctuationTextProcessing(rows, options);
  const next = context.MaweBoot.DATA.segments[0];
  assert.equal(next.text, 'Hello  world');
  assert.equal(next.items[0].text, 'Hello  ');
  assert.equal(range.cleanup_scope.text, 'hello，world。');
  assert.equal(context.window.AsrGapRemoveCore.getCleanupScopeItems(next, range).length, 0);
});

test('combined capitalization preserves standalone neutral and empty item ownership', () => {
  const { context } = fixture();
  const source = { id: 'combined', start: 0, end: 1000, text: 'hello，world。', items: [
    { start: 0, end: 300, text: 'hello' }, { start: 300, end: 400, text: '，' },
    { start: 400, end: 900, text: 'world' }, { start: 900, end: 1000, text: '。' },
  ] };
  context.MaweBoot.DATA.segments.push(source);
  const options = { cleanChinesePunctuation: true, capitalize: true };
  const rows = context.MaweTextProcess.buildTextProcessPreview([{ kind: 'main', index: 0 }], options);
  context.MaweTextProcess.applyPunctuationTextProcessing(rows, options);
  const next = context.MaweBoot.DATA.segments[0];
  assert.equal(next.text, 'Hello  world');
  assert.deepEqual(plain(next.items.map((item) => item.text)), ['Hello', '  ', 'world', '']);
  assert.deepEqual(plain(next.items.map(({ start, end }) => ({ start, end }))), source.items.map(({ start, end }) => ({ start, end })));
});

test('ambiguous combined wrapping preserves cleanup items and warns instead of duplicating or dropping anchors', () => {
  const { context } = fixture();
  const source = { id: 'combined', start: 0, end: 1000, text: 'hello，world。', items: [
    { start: 0, end: 300, text: 'hello' }, { start: 300, end: 400, text: '，' },
    { start: 400, end: 900, text: 'world' }, { start: 900, end: 1000, text: '。' },
  ] };
  context.MaweBoot.DATA.segments.push(source);
  const options = { cleanChinesePunctuation: true, addWrapChars: true, wrapLeft: '[', wrapRight: ']' };
  const rows = context.MaweTextProcess.buildTextProcessPreview([{ kind: 'main', index: 0 }], options);
  context.MaweTextProcess.applyPunctuationTextProcessing(rows, options);
  const next = context.MaweBoot.DATA.segments[0];
  assert.equal(next.text, '[hello  world]');
  assert.deepEqual(plain(next.items.map((item) => item.text)), ['hello', '  ', 'world', '']);
  assert.deepEqual(plain(next.items.map(({ start, end }) => ({ start, end }))), source.items.map(({ start, end }) => ({ start, end })));
  assert.ok(context.hints.some((hint) => hint.kind === 'warning'));
});

test('opening the modal resets cleanup to unchecked and all-cue scope names main track', () => {
  const { context, elements } = fixture();
  context.MaweBoot.DATA.segments.push(cue());
  elements.get('text-process-clean-punctuation').checked = true;
  context.MaweTextProcess.openTextProcessModal();
  assert.equal(elements.get('text-process-clean-punctuation').checked, false);
  assert.equal(elements.get('text-process-confirm').disabled, true);
  assert.equal(elements.get('text-process-scope-info').textContent, '当前范围：全部 1 条主字幕');
});

test('new scope and cleanup copy have English translations', () => {
  const context = { window: {} };
  vm.runInNewContext(read('shared/editor-i18n.js'), context);
  const translate = context.window.MAWE_I18N.translateText;
  assert.equal(translate('清理中文逗号、句号', 'en'), 'Clean Chinese commas and full stops');
  assert.equal(translate('当前范围：全部 3 条主字幕', 'en'), 'Current scope: all 3 main subtitles');
  assert.equal(translate('句中换为两个空格，句尾移除', 'en'), 'Replace with two spaces within a cue; remove at the end');
});
