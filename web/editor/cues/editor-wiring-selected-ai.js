// The panel stays non-modal while the backend produces a candidate.
(function () {
  'use strict';
  const panel = document.getElementById('editor-ai-panel');
  const $ = id => document.getElementById(`editor-ai-${id}`);
  const core = window.MaweEditorAiCore;
  let operation = '', task = null, resultStatus = null;
  MaweExportMenus.bindToolbarExportDropdown('editor-ai-dropdown', 'editor-ai-menu-btn', 'editor-ai-menu');

  function text(message) { resultStatus = null; $('status').textContent = message; }
  function showResultStatus(report, resultOperation, hasLines) {
    const english = document.documentElement.lang === 'en';
    const counts = resultOperation === 'align' ? (english
      ? `Generated ${Number(report.alignedSegments) || 0}, skipped ${Number(report.skippedSegments) || 0}, failed ${Number(report.failedSegments) || 0}. `
      : `生成 ${Number(report.alignedSegments) || 0} 条，跳过 ${Number(report.skippedSegments) || 0} 条，失败 ${Number(report.failedSegments) || 0} 条。`) : '';
    const notice = resultOperation === 'translate' ? (english ? 'Changing a timed translation requires confirmation before removing its old word timestamps.' : '更改带字词时间码的译文前会要求确认。') : '';
    text(hasLines ? counts + (english ? 'Review the candidate. Subtitles and related data will be checked again before applying. ' : '请核对候选结果。应用前会再次检查字幕与关联数据。') + notice
      : counts + (english ? 'There is no result to apply.' : '没有可应用的结果。'));
    resultStatus = { report, resultOperation, hasLines };
  }
  document.addEventListener('mawe:languagechange', () => {
    if (resultStatus) showResultStatus(resultStatus.report, resultStatus.resultOperation, resultStatus.hasLines);
  });
  function resetButtons() { $('start').hidden = false; $('cancel').hidden = true; $('apply').hidden = true; $('preview').hidden = true; }
  function binding(config) { return { requestToken: config.requestToken, bindingGeneration: config.bindingGeneration, sourceMediaId: config.sourceMediaId }; }
  async function request(action, payload) {
    const response = await fetch(`/api/editor-ai/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'AI 任务请求失败。');
    return result;
  }
  function currentBinding(current) {
    const config = MaweBoot.SERVER_CONFIG;
    return config === current.config && config?.bindingGeneration === current.binding.bindingGeneration && config?.sourceMediaId === current.binding.sourceMediaId
      && window.MaweProjectLoad?.projectBindingEpoch === current.epoch;
  }
  async function cancelTask() {
    const active = task;
    task = null;
    if (active?.id && currentBinding(active)) {
      try { await request('cancel', { ...active.binding, id: active.id }); } catch (_) { /* Project switch already invalidates the task. */ }
    }
    resetButtons();
  }
  async function poll(active) {
    while (task === active && currentBinding(active)) {
      await new Promise(resolve => setTimeout(resolve, 700));
      if (task !== active) return;
      try {
        const response = await request('status', { ...active.binding, id: active.id });
        if (task !== active) return;
        if (!currentBinding(active)) { task = null; resetButtons(); text('工程已切换，结果已丢弃。'); return; }
        if (response.state === 'running') continue;
        $('cancel').hidden = true;
        if (response.state !== 'done') { text(response.result?.error || '任务已取消。'); task = null; $('start').hidden = false; return; }
        active.result = response.result;
        const lines = active.operation === 'translate'
          ? active.snapshot.cues.map((cue, i) => `${cue.text}\n→ ${active.result.translations?.[i]?.text || '（无结果）'}`)
          : active.operation === 'align'
          ? (active.result.aligned || []).map(entry => `${active.snapshot.cues.find(c => c.id === entry.id)?.text || ''}\n${entry.items.map(i => `${i.text} [${i.start}–${i.end}ms]`).join(' ')}`)
          : (active.result.groups || []).map(group => group.map(id => {
            const match = /^c(\d+)a(\d+)$/.exec(id);
            return match ? active.snapshot.cues[Number(match[1]) - 1]?.items?.[Number(match[2]) - 1]?.text || '' : '';
          }).join(''));
        $('preview').textContent = lines.join('\n\n'); $('preview').hidden = false;
        $('apply').hidden = !lines.length;
        showResultStatus(active.result.report || {}, active.operation, Boolean(lines.length));
        if (!lines.length) { task = null; $('start').hidden = false; }
        return;
      } catch (error) { if (task === active) { text(error.message); task = null; $('start').hidden = false; $('cancel').hidden = true; } return; }
    }
    if (task === active) { task = null; resetButtons(); text('工程已切换，结果已丢弃。'); }
  }
  document.querySelectorAll('[data-editor-ai]').forEach(button => button.addEventListener('click', async () => {
    await cancelTask();
    operation = button.dataset.editorAi;
    panel.hidden = false;
    $('title').textContent = { translate: '翻译选中字幕', align: '生成字词时间码', resegment: '重新断句' }[operation];
    $('description').textContent = operation === 'align'
      ? '使用当前工程媒体的默认音轨和本机对齐模型。'
      : '所选字幕文字将发送给启动器中配置的服务商；处理期间可继续编辑。';
    $('provider-row').hidden = operation === 'align'; $('target-row').hidden = operation !== 'translate';
    $('model-row').hidden = operation !== 'align'; $('mode-row').hidden = operation !== 'align'; $('max-row').hidden = operation !== 'resegment';
    text('选择主字幕后开始处理。');
  }));
  $('close').addEventListener('click', () => { panel.hidden = true; void cancelTask(); });
  $('cancel').addEventListener('click', () => { void cancelTask().then(() => text('任务已取消。')); });
  $('start').addEventListener('click', async () => {
    let active = null;
    try {
      const config = MaweBoot.SERVER_CONFIG;
      if (!config?.requestToken || !Number.isInteger(config.bindingGeneration) || !config.sourceMediaId) throw new Error('此功能需要本地服务器编辑器。');
      MaweCuePanel.commitCuePanelEdit();
      const mainIds = new Set([...MaweSelection.selectedIdxs].map(index => core.mainSegments(MaweBoot.DATA)[index]?.id));
      const track = MaweMultiSubtitleCore.getActiveExtensionTrack();
      const bindings = MaweBoot.DATA.bindings || [];
      const pairedIds = new Set(bindings.filter(b => b.target?.track_id === track?.id && b.source?.track_id === core.mainTrack(MaweBoot.DATA).id && mainIds.has(b.source.segment_id))
        .flatMap(b => [b.target.segment_id]));
      if (MaweState.selection.indices('overlay').size || [...MaweSelection.selectedExtensionIdxs].some(index => !pairedIds.has(track?.segments[index]?.id))) throw new Error('请只选择主字幕及其联动副字幕。');
      const snapshot = core.capture(MaweBoot.DATA, [...MaweSelection.selectedIdxs], operation);
      active = { config, binding: binding(config), snapshot, operation, mode: $('mode').value, target: $('target').value, epoch: window.MaweProjectLoad?.projectBindingEpoch };
      task = active;
      $('start').hidden = true; $('cancel').hidden = false; $('apply').hidden = true; $('preview').hidden = true;
      text('正在处理，您可以继续编辑。');
      const metadata = MaweBoot.DATA.media_metadata || {};
      const defaultTrack = metadata.audio_tracks?.find(track => track?.default === true && Number.isInteger(track.audio_index))?.audio_index ?? 0;
      const audioTrack = Number.isInteger(metadata.selected_audio_track) ? metadata.selected_audio_track : defaultTrack;
      const result = await request('start', { ...active.binding, operation, cues: snapshot.cues,
        provider: $('provider').value, target: active.target, model: $('model').value, mode: active.mode,
        maxChars: Number($('max').value), language: core.mainTrack(MaweBoot.DATA).language || '', audioTrack });
      active.id = result.id;
      if (task !== active || !currentBinding(active)) { if (currentBinding(active)) await request('cancel', { ...active.binding, id: active.id }); return; }
      void poll(active);
    } catch (error) { if (active && task !== active) return; task = null; resetButtons(); text(error.message); }
  });
  $('apply').addEventListener('click', () => {
    const active = task;
    if (!active?.result || !currentBinding(active)) { text('工程已切换，请重新运行。'); return; }
    try {
      core.ensureCurrent(MaweBoot.DATA, active.snapshot);
      MaweCuePanel.commitCuePanelEdit();
      core.ensureCurrent(MaweBoot.DATA, active.snapshot);
      let replacements = 0;
      if (active.operation === 'align' && active.mode === 'generate') {
        replacements = (active.result.aligned || []).filter(entry => active.snapshot.cues.some(cue => cue.id === entry.id && cue.items?.length)).length;
      } else if (active.operation === 'translate') {
        const multi = active.snapshot.multi;
        replacements = (active.result.translations || []).filter(entry => {
          const binding = (multi.bindings || []).find(b => b.source?.track_id === active.snapshot.trackId && b.source?.segment_id === entry.id);
          const track = (multi.tracks || []).find(t => t.id === binding?.target?.track_id);
          const cue = track?.segments?.find(s => s.id === binding?.target?.segment_id);
          return cue?.items?.length && cue.text !== entry.text;
        }).length;
      }
      if (replacements) {
        const message = document.documentElement.lang === 'en'
          ? `Applying will replace existing word timestamps on ${replacements} subtitle(s). Continue?`
          : `应用后将替换 ${replacements} 条字幕原有的字词时间码。是否继续？`;
        if (!window.confirm(message)) return;
        core.ensureCurrent(MaweBoot.DATA, active.snapshot);
      }
      const makeId = () => `ai-${crypto.randomUUID()}`;
      MaweCommands.run('应用 AI 结果', command => {
        if (active.operation === 'translate') core.applyTranslation(MaweBoot.DATA, active.snapshot, active.result.translations, active.target, makeId);
        else if (active.operation === 'align') core.applyAlignment(MaweBoot.DATA, active.snapshot, active.result.aligned, active.mode);
        else core.applyResegment(MaweBoot.DATA, active.snapshot, active.result.groups, makeId);
        MaweSelection.clearSelection({ silent: true, commitCuePanel: false });
        command.commit({ cueList: true, waveform: 'full', preview: 'update' });
      }, { captureView: true });
      task = null; resetButtons(); text('结果已应用，可使用撤销恢复。');
    } catch (error) { text(error.message); }
  });
})();
