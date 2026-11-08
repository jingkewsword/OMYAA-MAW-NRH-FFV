import assert from 'node:assert/strict';
import test from 'node:test';
import { createUtilsModule as dataModule } from '../web/shared/utils/data.js';
import { createUtilsModule as multiModule } from '../web/shared/utils/multi-subtitle.js';

const { bindingForSegment, buildBoundExtensionIdSet, boundExtensionIdSetHas } = multiModule(dataModule({}));

function assertParity(multi, track, ids) {
  const set = buildBoundExtensionIdSet(multi, track);
  assert.ok(set instanceof Set);
  for (const id of ids) {
    assert.equal(boundExtensionIdSetHas(set, id), Boolean(bindingForSegment(multi, id, 'extension', track)), String(id));
  }
}

test('index matches extension binding lookup across tracks and multiple endpoints', () => {
  const multi = { bindings: [
    { track_id: 'a', main_segment_ids: ['main'], extension_segment_ids: ['same', 'second', 42, ' padded '] },
    { track_id: 'b', main_segment_ids: ['same'], extension_segment_ids: ['same', 'b-only'] },
    { track_id: 'a', main_segment_ids: [], extension_segment_ids: ['same', 'repeat', 'repeat', ''] },
    { track_id: '', extension_segment_ids: [] },
  ] };
  const ids = ['same', 'second', 'b-only', 'main', 'repeat', ' padded ', '', null, 42, '42', 'x'.repeat(161), 'missing'];
  for (const track of ['a', 'b', '', null]) assertParity(multi, track, ids);
});

test('each index reflects binding edits, replacement and track changes', () => {
  const multi = { bindings: [{ track_id: 'a', extension_segment_ids: ['first'] }] };
  assertParity(multi, 'a', ['first', 'second']);
  multi.bindings[0].extension_segment_ids.push('second');
  assertParity(multi, 'a', ['first', 'second']);
  multi.bindings = [{ track_id: 'b', extension_segment_ids: ['second'] }];
  assertParity(multi, 'a', ['first', 'second']);
  assertParity(multi, 'b', ['first', 'second']);
});

test('unexpected non-normalized binding shapes preserve the existing fallback', () => {
  assert.equal(buildBoundExtensionIdSet({ bindings: [null] }, 'a'), null);
  assert.equal(buildBoundExtensionIdSet({ bindings: [{ track_id: 'a', extension_segment_ids: 'abcd' }] }, 'a'), null);
  assert.equal(buildBoundExtensionIdSet({ bindings: [{ track_id: 'a', main_segment_ids: 42, extension_segment_ids: [] }] }, 'a'), null);
  assertParity({ bindings: [] }, 'a', ['missing']);
});
