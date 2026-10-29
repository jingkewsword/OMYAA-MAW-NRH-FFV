import assert from 'node:assert/strict';
import test from 'node:test';
import { validateProjectSpeakers } from '../web/shared/utils/speaker-identity.js';

test('project speaker identities remain distinct when names and colors are equal', () => {
  const project = { speakers: [{ id: 'p1', name: '主持人', color: '#f9ca1f' },
    { id: 'p2', name: '主持人', color: '#f9ca1f' }],
  tracks: [{ segments: [{ speaker: 'p1' }, { speaker: 'p2' }, { speaker: null }] }] };
  assert.deepEqual(validateProjectSpeakers(project), []);
});

test('project speaker validation rejects dangling identities and per-word speaker fields', () => {
  const project = { speakers: [{ id: 'p1', name: '一', color: '#f9ca1f' }],
    tracks: [{ segments: [{ speaker: 'missing', items: [{ speaker: 'p1' }] }] }] };
  assert.deepEqual(validateProjectSpeakers(project).map(error => error.path),
    ['$.tracks[0].segments[0].speaker', '$.tracks[0].segments[0].items[0].speaker']);
});

test('project speaker validation rejects duplicate identities and invalid names or colors', () => {
  const project = { speakers: [{ id: 'p1', name: '一', color: '#f9ca1f' },
    { id: 'p1', name: 'bad\nname', color: 'grey' }], tracks: [] };
  assert.deepEqual(validateProjectSpeakers(project).map(error => error.path),
    ['$.speakers[1].id', '$.speakers[1].name', '$.speakers[1].color']);
});

test('project speaker validation reports invalid project shape', () => {
  assert.deepEqual(validateProjectSpeakers(null).map(error => error.path), ['$']);
  assert.deepEqual(validateProjectSpeakers({}).map(error => error.path), ['$.speakers', '$.tracks']);
});

test('unicode-only whitespace IDs are invalid across Python and JavaScript', () => {
  for (const id of ['\u0085', '\ufeff', '\u001c']) {
    const project = { speakers: [{ id, name: 'x', color: '#f9ca1f' }], tracks: [] };
    assert.deepEqual(validateProjectSpeakers(project).map(error => error.path), ['$.speakers[0].id']);
  }
});
