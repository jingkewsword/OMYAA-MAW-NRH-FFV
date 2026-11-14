import assert from 'node:assert/strict';
import test from 'node:test';
import { createUtilsModule as dataModule } from '../web/shared/utils/data.js';
import { createUtilsModule as multiModule } from '../web/shared/utils/multi-subtitle.js';

const { rebuildBindingOffsets } = multiModule(dataModule({}));
const binding = (track, main, extension) => ({
  track_id: track, main_segment_ids: [main], extension_segment_ids: [extension],
  start_offset_ms: 77, end_offset_ms: 88,
});

test('offset sync preserves track and duplicate ID precedence, unknown IDs, and strict equality', () => {
  const main = [{ id: ' m ', start: 10, end: 20 }, { id: 'm', start: 100, end: 200 }];
  const multi = { tracks: [
    { id: 'a', segments: [{ id: 'x', start: 900, end: 990 }] },
    { id: 'a', segments: [{ id: 'x', start: 110.6, end: 195.2 }, { id: 'x', start: 800, end: 880 }, { id: 0, start: 90, end: 190 }, { id: NaN, start: 1, end: 2 }] },
    { id: 'b', segments: [{ id: 'x', start: 130, end: 240 }] },
  ], bindings: [binding('a', 'm', 'x'), binding('b', 'm', 'x'), binding('a', 'm', 0), binding('a', 'm', 'x'), binding('a', 'm', NaN), binding('a', 'missing', 'x'), binding('a', 'm', 'missing')] };
  const records = [...multi.bindings];
  assert.equal(rebuildBindingOffsets(multi, main), multi);
  assert.deepEqual(multi.bindings.map(b => [b.start_offset_ms, b.end_offset_ms]), [[11, -5], [30, 40], [-10, -10], [11, -5], [77, 88], [77, 88], [77, 88]]);
  records.forEach((b, i) => assert.equal(multi.bindings[i], b));
});

test('offset indexes observe reorder, replacement and edits on each call', () => {
  const main = [{ id: 'm', start: 100, end: 200 }];
  const track = { id: 'a', segments: [{ id: 'x', start: 120, end: 230 }] };
  const multi = { tracks: [track], bindings: [binding('a', 'm', 'x')] };
  const offsets = () => [multi.bindings[0].start_offset_ms, multi.bindings[0].end_offset_ms];
  rebuildBindingOffsets(multi, main); assert.deepEqual(offsets(), [20, 30]);
  main[0].start = 110; track.segments[0].end = 250;
  rebuildBindingOffsets(multi, main); assert.deepEqual(offsets(), [10, 50]);
  track.segments.unshift({ id: 'x', start: 150, end: 260 });
  rebuildBindingOffsets(multi, main); assert.deepEqual(offsets(), [40, 60]);
  track.segments = [{ id: 'x', start: 90, end: 180 }];
  rebuildBindingOffsets(multi, main); assert.deepEqual(offsets(), [-20, -20]);
});

test('malformed sparse and null segments retain find short circuit and error behavior', () => {
  const main = [{ id: 'm', start: 1, end: 3 }];
  for (const tail of [null, undefined]) {
    const segments = [{ id: 'x', start: 2, end: 4 }, tail];
    const multi = { tracks: [{ id: 'a', segments }], bindings: [binding('a', 'm', 'x')] };
    assert.doesNotThrow(() => rebuildBindingOffsets(multi, main));
    multi.bindings = [binding('a', 'm', 'unknown')];
    assert.throws(() => rebuildBindingOffsets(multi, main), TypeError);
  }
  const segments = [{ id: 'x', start: 2, end: 4 }]; segments.length = 2;
  const multi = { tracks: [{ id: 'a', segments }], bindings: [binding('a', 'm', 'x')] };
  assert.doesNotThrow(() => rebuildBindingOffsets(multi, main));
  multi.bindings = [binding('a', 'm', 'unknown')];
  assert.throws(() => rebuildBindingOffsets(multi, main), TypeError);
});

test('referenced extension IDs are read linearly', () => {
  const size = 200; let reads = 0;
  const main = Array.from({ length: size }, (_, i) => ({ id: `m${i}`, start: i * 1000, end: i * 1000 + 900 }));
  const tracks = ['a', 'b'].map(id => ({ id, segments: main.map((s, i) => ({ get id() { reads += 1; return `${id}${i}`; }, start: s.start + 10, end: s.end - 10 })) }));
  const multi = { tracks, bindings: main.map((s, i) => binding(i % 2 ? 'a' : 'b', s.id, `${i % 2 ? 'a' : 'b'}${i}`)) };
  rebuildBindingOffsets(multi, main);
  assert.ok(reads <= size * tracks.length, `extension IDs read ${reads} times`);
  assert.ok(multi.bindings.every(b => b.start_offset_ms === 10 && b.end_offset_ms === -10));
});

test('a lone early binding does not scan the remainder of a long extension track', () => {
  let reads = 0;
  const segments = Array.from({ length: 3000 }, (_, i) => ({
    get id() { reads += 1; return `e${i}`; }, start: i * 1000 + 10, end: i * 1000 + 900,
  }));
  const multi = { tracks: [{ id: 'a', segments }], bindings: [binding('a', 'm', 'e0')] };
  rebuildBindingOffsets(multi, [{ id: 'm', start: 0, end: 1000 }]);
  assert.equal(reads, 1);
  assert.deepEqual([multi.bindings[0].start_offset_ms, multi.bindings[0].end_offset_ms], [10, -100]);
});
