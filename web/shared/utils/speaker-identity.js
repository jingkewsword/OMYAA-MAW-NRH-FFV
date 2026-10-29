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
// Migration is intentionally separate from project loading and binding updates.
// The mapping is indexed by input position so callers can update references.
export function migrateSpeakerSegments(segments, sourceToProject, reservedSegmentIds = []) {
  const valid = value => typeof value === 'string' && /[^\s\u0085\u001c-\u001f]/u.test(value);
  const identity = value => {
    if (value == null || (typeof value === 'string' && !valid(value))) return null;
    if (typeof value !== 'string') throw new Error('invalid source speaker');
    return value;
  };
  const source = structuredClone(segments);
  const ids = source.map(segment => segment.id).filter(valid);
  if (new Set(ids).size !== ids.length) throw new Error('duplicate segment id');
  const used = new Set([...ids, ...reservedSegmentIds]);
  const newId = base => {
    let number = 1;
    while (used.has(`${base}-speaker-${number}`)) number++;
    const id = `${base}-speaker-${number}`;
    used.add(id);
    return id;
  };
  const result = [];
  const mappings = [];
  source.forEach((segment, index) => {
    const items = segment.items ?? [];
    if (!Array.isArray(items) || items.some(item => item === null || typeof item !== 'object' || Array.isArray(item))) {
      throw new Error('items must be an array of objects');
    }
    const segmentSpeaker = identity(segment.speaker);
    const runs = [];
    let current = [];
    let currentSpeaker = null;
    for (const item of items) {
      const speaker = identity(item.speaker);
      if (current.length && speaker !== null && currentSpeaker !== null && speaker !== currentSpeaker) {
        runs.push([current, currentSpeaker]);
        current = [];
        currentSpeaker = null;
      }
      current.push(item);
      if (speaker !== null) currentSpeaker = speaker;
    }
    if (current.length) runs.push([current, currentSpeaker]);
    if (!runs.length) runs.push([[], null]);
    const split = runs.length > 1;
    let textPieces;
    if (split) {
      if (typeof segment.text !== 'string' || items.some(item => typeof item.text !== 'string')) {
        throw new Error('cannot split segment without matching item text');
      }
      const significant = char => !/[\s\u0085\u001c-\u001f\p{P}]/u.test(char);
      const text = Array.from(segment.text);
      if (text.filter(significant).join('') !== items.flatMap(item => Array.from(item.text)).filter(significant).join('')) {
        throw new Error('cannot split segment without matching item text');
      }
      const cuts = [];
      let cursor = 0;
      for (const [run] of runs.slice(0, -1)) {
        let count = run.flatMap(item => Array.from(item.text)).filter(significant).length;
        while (cursor < text.length && count) {
          if (significant(text[cursor])) count--;
          cursor++;
        }
        while (cursor < text.length && !significant(text[cursor])) cursor++;
        cuts.push(cursor);
      }
      textPieces = [0, ...cuts].map((start, i) => text.slice(start, [...cuts, text.length][i]).join(''));
      const edges = [...runs.slice(1).map(([run]) => [run[0], 'start']),
        ...runs.slice(0, -1).map(([run]) => [run.at(-1), 'end'])];
      if (edges.some(([item, key]) => !Number.isInteger(item[key]))) {
        throw new Error('cannot split segment without integer item timestamps');
      }
      const has = key => Object.hasOwn(segment, key);
      if (has('start_frame') !== has('end_frame')) throw new Error('segment frame boundaries must be paired');
      if (has('start_frame') && edges.some(([item, key]) => !Number.isInteger(item[`${key}_frame`]))) {
        throw new Error('cannot split framed segment without item frame boundaries');
      }
    }
    const oldId = segment.id ?? null;
    const newIds = [];
    runs.forEach(([run, runSpeaker], runIndex) => {
      const out = structuredClone(segment);
      if (split) {
        if (runIndex || !valid(oldId)) out.id = newId(valid(oldId) ? oldId : `segment-${index + 1}`);
        out.items = structuredClone(run);
        out.text = textPieces[runIndex];
        out.start = runIndex === 0 ? segment.start : run[0].start;
        out.end = runIndex === runs.length - 1 ? segment.end : run.at(-1).end;
        if (Object.hasOwn(segment, 'start_frame')) {
          out.start_frame = runIndex === 0 ? segment.start_frame : run[0].start_frame;
          out.end_frame = runIndex === runs.length - 1 ? segment.end_frame : run.at(-1).end_frame;
        }
      }
      const speaker = split ? runSpeaker : (segmentSpeaker ?? runSpeaker);
      if (speaker !== null) {
        const projectId = Object.hasOwn(sourceToProject, speaker) ? sourceToProject[speaker] : null;
        if (!valid(projectId)) throw new Error('unmapped source speaker');
        out.speaker = projectId;
      } else delete out.speaker;
      for (const item of out.items ?? []) delete item.speaker;
      result.push(out);
      newIds.push(out.id ?? null);
    });
    mappings.push({ input_index: index, old_id: oldId, new_ids: newIds });
  });
  return { segments: result, mappings };
}
