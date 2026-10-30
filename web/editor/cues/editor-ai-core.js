// Pure candidate validation and mutation helpers; the editor owns transactions.
(function (global) {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const fail = message => { throw new Error(message); };

  function mainTrack(project) {
    const tracks = project.tracks?.filter(t => t.role === 'main');
    if (tracks?.length !== 1) fail('工程缺少唯一主字幕轨。');
    return tracks[0];
  }
  function mainSegments(project) { return mainTrack(project).segments; }
  // Detached selection snapshot; never install legacy containers on the project.
  function related(project) {
    return { tracks: project.tracks.filter(t => t.role === 'secondary'),
      bindings: project.bindings || [], bilingual: project.bilingual || null };
  }
  function capture(project, indices, operation) {
    const sorted = [...new Set(indices)].sort((a, b) => a - b);
    if (!sorted.length || sorted.length > 100 || sorted.some(i => !mainSegments(project)[i])) fail('请选择 1 到 100 条主字幕。');
    if (operation === 'resegment' && sorted.some((v, i) => i && v !== sorted[i - 1] + 1)) fail('重新断句需要选择连续的主字幕。');
    const cues = sorted.map(i => mainSegments(project)[i]);
    if (new Set(cues.map(c => c.id)).size !== cues.length || cues.some(c => !c.id || !String(c.text || '').trim() || mainSegments(project).filter(s => s.id === c.id).length !== 1)) fail('选中字幕缺少唯一稳定 ID 或文本。');
    const multi = related(project);
    const ids = new Set(cues.map(c => c.id));
    if (operation !== 'translate' && project.timebase?.unit === 'frames') fail('帧时间基准下暂不支持生成时间码或 AI 断句。');
    const scopes = project.gap_remove?.provenance?.sources?.ai_cleanup || [];
    if (operation !== 'translate' && scopes.some(g => ids.has(g?.cleanup_scope?.segment_id))) fail('选中字幕有关联的 AI 删词范围，请先处理该范围。');
    if (operation === 'resegment') {
      if ((multi.bindings || []).some(b => b.source?.track_id === mainTrack(project).id && ids.has(b.source?.segment_id))) fail('选中字幕已有副字幕绑定，请先解除绑定再断句。');
      if (JSON.stringify(mainSegments(project)).includes('"headIdx"')) fail('工程含字幕分组引用，暂不支持 AI 断句。');
      const allowed = new Set(['id', 'text', 'start', 'end', 'start_frame', 'end_frame', 'items', 'speaker', '_dirty']);
      if (cues.some(c => Object.keys(c).some(k => !allowed.has(k) && c[k] != null))) fail('选中字幕包含尚不能安全迁移的附加属性。');
      if (new Set(cues.map(c => c.speaker || '')).size > 1) fail('不同说话人的字幕请分别断句。');
      if (cues.some(c => !Array.isArray(c.items) || !c.items.length || c.items.map(x => x.text).join('') !== c.text)) fail('断句需要完整覆盖原文的字词时间码。');
    }
    return { speakers: clone(project.speakers || null), trackId: mainTrack(project).id, trackSettings: clone(Object.fromEntries(Object.entries(mainTrack(project)).filter(([k]) => k !== 'segments' && k !== '_dirty'))), operation, indices: sorted, cues: clone(cues), multi: clone(multi), gap: clone(project.gap_remove || null), timebase: clone(project.timebase || null),
      groups: operation === 'resegment' ? clone(project.subtitle_groups || null) : null,
      order: operation === 'resegment' ? mainSegments(project).map(c => c.id) : null,
      neighbors: operation === 'resegment' ? clone([mainSegments(project)[sorted[0] - 1] || null, mainSegments(project)[sorted.at(-1) + 1] || null]) : null };
  }

  function ensureCurrent(project, snap) {
    if (!equal(project.speakers || null, snap.speakers)) fail("说话人身份表已变化，请重新运行。");
    if (mainTrack(project).id !== snap.trackId || !equal(Object.fromEntries(Object.entries(mainTrack(project)).filter(([k]) => k !== 'segments' && k !== '_dirty')), snap.trackSettings)) fail('主字幕轨已变化，请重新运行。');
    const current = snap.cues.map(cue => mainSegments(project).find(c => c.id === cue.id));
    if (current.some((cue, i) => !cue || !equal(cue, snap.cues[i]))) fail('选中的字幕已变化，请重新运行。');
    if (!equal(related(project), snap.multi) || !equal(project.gap_remove || null, snap.gap)) fail('关联字幕或删词范围已变化，请重新运行。');
    if (!equal(project.timebase || null, snap.timebase)) fail('工程时间基准已变化，请重新运行。');
    if (snap.order && !equal(project.subtitle_groups || null, snap.groups)) fail('字幕分组已变化，请重新运行。');
    if (snap.order && (!equal(mainSegments(project).map(c => c.id), snap.order) ||
        !equal([mainSegments(project)[snap.indices[0] - 1] || null, mainSegments(project)[snap.indices.at(-1) + 1] || null], snap.neighbors))) fail('字幕顺序或相邻字幕已变化，请重新运行。');
  }

  function applyTranslation(project, snap, translations, target, makeId) {
    if (!Array.isArray(translations) || translations.length !== snap.cues.length || translations.some((t, i) => t.id !== snap.cues[i].id || typeof t.text !== 'string' || !t.text.trim())) fail('翻译结果不完整。');
    const multi = clone(snap.multi);
    multi.tracks ||= []; multi.bindings ||= [];
    let track = multi.tracks[0];
    if (!track) { track = { id: makeId(), role: 'secondary', enabled: true, name: target === 'zh' ? '中文翻译' : '英文翻译', language: target, split_mode: target === 'zh' ? 'continuous' : 'word', segments: [] }; multi.tracks.push(track); }
    const language = String(track.language || '').trim().toLowerCase();
    const aliases = target === 'zh' ? ['zh', 'zh-cn', 'zh-hans', 'chinese', '中文', '汉语'] : ['en', 'en-us', 'en-gb', 'english', '英文', '英语'];
    if (language && !aliases.includes(language)) fail('现有副字幕轨的语言与目标语言不同。');
    if (!language) track.language = target;
    track.segments ||= [];
    for (let i = 0; i < snap.cues.length; i++) {
      const cue = snap.cues[i], translated = translations[i];
      const matches = multi.bindings.filter(b => b.source?.track_id === snap.trackId && b.source?.segment_id === cue.id);
      if (matches.length > 1 || matches.some(b => b.target?.track_id !== track.id || !b.target?.segment_id)) fail('副字幕绑定不符合一对一契约。');
      if (matches.length) {
        const extension = track.segments.find(s => s.id === matches[0].target.segment_id);
        if (!extension) fail('找不到绑定的副字幕。');
        if (extension.text !== translated.text) {
          extension.text = translated.text; delete extension.items; extension._dirty = true;
        }
      } else {
        if (JSON.stringify(track.segments).includes('"headIdx"')) fail('副字幕轨含分组引用，暂不能插入译文。');
        if (track.segments.some(s => s.start < cue.end && cue.start < s.end)) fail('新译文与已有副字幕重叠，请先处理对应副字幕。');
        const extId = makeId();
        track.segments.push({ id: extId, start: cue.start, end: cue.end, text: translated.text, _dirty: true });
        multi.bindings.push({ id: makeId(), source: { track_id: snap.trackId, segment_id: cue.id }, target: { track_id: track.id, segment_id: extId }, start_offset_ms: 0, end_offset_ms: 0 });
      }
    }
    track.segments.sort((a, b) => a.start - b.start || a.end - b.end);
    track.enabled = true;
    const position = project.tracks.findIndex(t => t.id === track.id);
    if (position < 0) project.tracks.push(track); else project.tracks[position] = track;
    project.bindings = multi.bindings;
    project.bilingual = { ...(project.bilingual || {}), active_track_id: track.id, display_mode: 'both' };
  }

  function applyAlignment(project, snap, aligned, mode = 'fill') {
    if (!Array.isArray(aligned)) fail('时间码结果无效。');
    const ids = new Set();
    for (const entry of aligned) {
      const cue = snap.cues.find(c => c.id === entry.id);
      if (!cue || ids.has(entry.id) || !Array.isArray(entry.items) || !entry.items.length) fail('时间码结果无效。');
      if (mode === 'fill' && Array.isArray(cue.items) && cue.items.length) fail('补缺不能覆盖已有字词时间码。');
      let previous = cue.start;
      for (const item of entry.items) {
        if (!item || typeof item.text !== 'string' || !Number.isInteger(item.start) || !Number.isInteger(item.end) || item.start < previous || item.end < item.start || item.end > cue.end) fail('时间码超出字幕范围。');
        previous = item.end;
      }
      if (entry.items.map(item => item.text).join('').replace(/\s/g, '') !== cue.text.replace(/\s/g, '')) fail('时间码未覆盖字幕文本。');
      ids.add(entry.id);
    }
    for (const entry of aligned) { const cue = mainSegments(project).find(c => c.id === entry.id); cue.items = clone(entry.items); cue._dirty = true; }
  }

  function applyResegment(project, snap, groups, makeId) {
    const atoms = snap.cues.flatMap((cue, i) => cue.items.map((item, j) => ({ id: `c${String(i + 1).padStart(4, '0')}a${String(j + 1).padStart(4, '0')}`, item })));
    if (!Array.isArray(groups) || !groups.length || groups.some(g => !Array.isArray(g) || !g.length) || !equal(groups.flat(), atoms.map(a => a.id))) fail('断句结果未完整覆盖字词。');
    let cursor = 0;
    const replacement = groups.map(group => {
      const items = atoms.slice(cursor, cursor + group.length).map(a => clone(a.item)); cursor += group.length;
      const start = items[0].start, end = items.at(-1).end;
      if (!Number.isInteger(start) || !Number.isInteger(end) || start >= end) fail('断句结果时间范围无效。');
      return { id: makeId(), start, end, text: items.map(i => i.text).join(''), items, ...(snap.cues[0].speaker ? { speaker: snap.cues[0].speaker } : {}), _dirty: true };
    });
    mainSegments(project).splice(snap.indices[0], snap.cues.length, ...replacement);
  }
  global.MaweEditorAiCore = Object.freeze({ mainTrack, mainSegments, capture, ensureCurrent, applyTranslation, applyAlignment, applyResegment });
})(globalThis);
