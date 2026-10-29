// Pure validation for the proposed segment-level speaker identity contract.
export function validateProjectSpeakers(project) {
  const errors = [];
  const add = (path, message) => errors.push({ path, message });
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  if (!object(project)) { add('$', 'must be an object'); return errors; }
  let speakers = project?.speakers;
  if (!Array.isArray(speakers)) { add('$.speakers', 'must be an array'); speakers = []; }
  const ids = new Set();
  speakers.forEach((speaker, index) => {
    const path = `$.speakers[${index}]`;
    if (!object(speaker)) { add(path, 'must be an object'); return; }
    if (typeof speaker.id !== 'string' || !/[^\s\u0085\u001c-\u001f]/u.test(speaker.id) || ids.has(speaker.id)) {
      add(`${path}.id`, 'must be a unique nonempty string');
    } else ids.add(speaker.id);
    if (typeof speaker.name !== 'string' || Array.from(speaker.name).length > 64
        || /[\u0000-\u001f\u007f-\u009f]/u.test(speaker.name)) {
      add(`${path}.name`, 'must be a name of at most 64 characters without control characters');
    }
    if (typeof speaker.color !== 'string' || !/^#[0-9a-f]{6}$/i.test(speaker.color)) {
      add(`${path}.color`, 'must be a six-digit hex color');
    }
  });
  if (!Array.isArray(project?.tracks)) { add('$.tracks', 'must be an array'); return errors; }
  project.tracks.forEach((track, trackIndex) => {
    const path = `$.tracks[${trackIndex}].segments`;
    if (!object(track) || !Array.isArray(track.segments)) { add(path, 'must be an array'); return; }
    track.segments.forEach((segment, segmentIndex) => {
      const segmentPath = `${path}[${segmentIndex}]`;
      if (!object(segment)) { add(segmentPath, 'must be an object'); return; }
      if (segment.speaker != null && (typeof segment.speaker !== 'string' || !ids.has(segment.speaker))) {
        add(`${segmentPath}.speaker`, 'must reference a project speaker');
      }
      if (segment.items == null) return;
      if (!Array.isArray(segment.items)) { add(`${segmentPath}.items`, 'must be an array'); return; }
      segment.items.forEach((item, itemIndex) => {
        if (object(item) && Object.hasOwn(item, 'speaker')) {
          add(`${segmentPath}.items[${itemIndex}].speaker`, 'speaker belongs to the segment');
        }
      });
    });
  });
  return errors;
}
