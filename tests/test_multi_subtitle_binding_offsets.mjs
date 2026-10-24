import assert from 'node:assert/strict';
import test from 'node:test';
import { createUtilsModule as createDataUtils } from '../web/shared/utils/data.js';
import { createUtilsModule as createMultiSubtitleUtils } from '../web/shared/utils/multi-subtitle.js';

const { rebuildBindingOffsets } = createMultiSubtitleUtils(createDataUtils({}));
const binding = (trackId, mainId, extensionId) => ({
  track_id: trackId,
  main_segment_ids: [mainId],
  extension_segment_ids: [extensionId],
  start_offset_ms: 77,
  end_offset_ms: 88,
});

test('binding offsets retain per-track lookup, first extension match, and existing main/track precedence', () => {
  const main = [{ id: ' m ', start: 10, end: 20 }, { id: 'm', start: 100, end: 200 }];
  const first = { id: 'shared', start: '110.6', end: '195.2' };
  const multi = {
    tracks: [
      { id: 'a', segments: [{ id: 'shared', start: 900, end: 990 }] },
      { id: 'a', segments: [first, { id: 'shared', start: 800, end: 880 }] },
      { id: 'b', segments: [{ id: 'shared', start: 130, end: 240 }] },
    ],
    bindings: [binding('a', 'm', 'shared'), binding('b', 'm', 'shared')],
  };
  const records = [...multi.bindings];
  assert.equal(rebuildBindingOffsets(multi, main), multi);
  assert.deepEqual(multi.bindings.map(({ start_offset_ms, end_offset_ms }) => [start_offset_ms, end_offset_ms]), [[11, -5], [30, 40]]);
  assert.equal(multi.bindings[0], records[0]);
  assert.equal(multi.bindings[1], records[1]);
  assert.equal(multi.tracks[1].segments[0], first);
});

test('missing binding endpoints and tracks preserve their previous offsets', () => {
  const multi = {
    tracks: [{ id: 'a', segments: [{ id: 'x', start: 20, end: 80 }] }, { id: 'empty' }],
    bindings: [binding('a', 'missing', 'x'), binding('a', 'm', 'missing'), binding('missing', 'm', 'x'), binding('empty', 'm', 'x')],
  };
  const before = structuredClone(multi);
  rebuildBindingOffsets(multi, [{ id: 'm', start: 10, end: 90 }]);
  assert.deepEqual(multi, before);
  assert.equal(rebuildBindingOffsets(null, []), null);
  assert.equal(rebuildBindingOffsets(undefined, []), undefined);
  rebuildBindingOffsets(multi, null);
  assert.deepEqual(multi, before);
});

test('binding offset lookups are rebuilt after in-place timing edits and track replacements', () => {
  const main = [{ id: 'm', start: 100, end: 200 }];
  const track = { id: 'a', segments: [{ id: 'x', start: 120, end: 230 }] };
  const multi = { tracks: [track], bindings: [binding('a', 'm', 'x')] };
  const offsets = () => [multi.bindings[0].start_offset_ms, multi.bindings[0].end_offset_ms];
  rebuildBindingOffsets(multi, main);
  assert.deepEqual(offsets(), [20, 30]);
  main[0].start = 110;
  track.segments[0].end = 250;
  rebuildBindingOffsets(multi, main);
  assert.deepEqual(offsets(), [10, 50]);
  track.segments.unshift({ id: 'x', start: 150, end: 260 });
  rebuildBindingOffsets(multi, main);
  assert.deepEqual(offsets(), [40, 60]);
  track.segments = [{ id: 'x', start: 90, end: 180 }];
  rebuildBindingOffsets(multi, main);
  assert.deepEqual(offsets(), [-20, -20]);
});

test('grouped bindings continue taking the first endpoint on each side', () => {
  const record = binding('a', 'm1', 'x1');
  record.main_segment_ids.push('m2');
  record.extension_segment_ids.push('x2');
  const multi = {
    tracks: [{ id: 'a', segments: [{ id: 'x2', start: 2000, end: 2900 }, { id: 'x1', start: 15, end: 95 }] }],
    bindings: [record],
  };
  rebuildBindingOffsets(multi, [{ id: 'm1', start: 10, end: 100 }, { id: 'm2', start: 1000, end: 1900 }]);
  assert.deepEqual([record.start_offset_ms, record.end_offset_ms], [5, -5]);
  assert.deepEqual(record.main_segment_ids, ['m1', 'm2']);
  assert.deepEqual(record.extension_segment_ids, ['x1', 'x2']);
});

test('binding offsets preserve strict extension ID matching and numeric timing conversion', () => {
  const multi = {
    tracks: [{ id: 'a', segments: [{ id: 0, start: '100.2', end: '210.9' }, { id: '0', start: 120, end: 240 }, { id: NaN, start: 900, end: 990 }] }],
    bindings: [binding('a', 'm', 0), binding('a', 'm', '0'), binding('a', 'm', NaN)],
  };
  rebuildBindingOffsets(multi, [{ id: 'm', start: '100.4', end: '200.2' }]);
  assert.ok(Object.is(multi.bindings[0].start_offset_ms, -0));
  assert.equal(multi.bindings[0].end_offset_ms, 11);
  assert.deepEqual([multi.bindings[1].start_offset_ms, multi.bindings[1].end_offset_ms], [20, 40]);
  assert.deepEqual([multi.bindings[2].start_offset_ms, multi.bindings[2].end_offset_ms], [77, 88]);
});

test('binding offset synchronization reads extension IDs linearly across referenced tracks', () => {
  const size = 200;
  let reads = 0;
  const main = Array.from({ length: size }, (_, index) => ({ id: `m${index}`, start: index * 1000, end: index * 1000 + 900 }));
  const tracks = ['a', 'b'].map((id) => ({ id, segments: main.map((segment, index) => ({
    get id() { reads += 1; return `${id}${index}`; },
    start: segment.start + 10,
    end: segment.end - 10,
  })) }));
  const multi = { tracks, bindings: main.map((segment, index) => binding(index % 2 ? 'a' : 'b', segment.id, `${index % 2 ? 'a' : 'b'}${index}`)) };
  rebuildBindingOffsets(multi, main);
  assert.ok(reads <= size * tracks.length * 2, `expected linear extension ID reads, got ${reads}`);
  assert.ok(multi.bindings.every((record) => record.start_offset_ms === 10 && record.end_offset_ms === -10));
});
