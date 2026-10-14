// 文本处理：处理项选择、预览与确认应用。
// 由 split-cluster codemod 自 editor.js 拆出：状态为本模块私有，外部仅经
// window.MaweTextProcess 冻结门面访问（可变状态为访问器属性，赋值语义不变）。
// 清单位置在 editor.js 之前；editor.js 全局仅在延迟执行的回调中访问。
(function initMaweTextProcess(global) {
  'use strict';



  // === 文本处理 ===
  const textProcessButton = document.getElementById('text-process-btn');


  const textProcessSelectedOnlyCb = document.getElementById('text-process-selected-only');


  const textProcessSelectedOnlyHint = document.getElementById('text-process-selected-only-hint');


  const textProcessScopeInfo = document.getElementById('text-process-scope-info');


  const textProcessPreview = document.getElementById('text-process-preview');


  const textProcessConfirm = document.getElementById('text-process-confirm');


  const textProcessCleanPunctuation = document.getElementById('text-process-clean-punctuation');

  const textProcessTrim = document.getElementById('text-process-trim');


  const textProcessCapitalize = document.getElementById('text-process-capitalize');


  const textProcessConvertNumbers = document.getElementById('text-process-convert-numbers');


  const textProcessPrefixInput = document.getElementById('text-process-prefix-input');


  const textProcessSuffixInput = document.getElementById('text-process-suffix-input');


  const textProcessCustomWrapFields = document.getElementById('text-process-custom-wrap-fields');


  const textProcessStripMarkdown = document.getElementById('text-process-strip-markdown');


  const wrapCharsModal = document.getElementById('wrap-chars-modal');


  const wrapCharsLeftInput = document.getElementById('wrap-chars-left');


  const wrapCharsRightInput = document.getElementById('wrap-chars-right');


  let wrapCharsScope = [];
  let textProcessWrapPreset = null;


  let textProcessSelectionSnapshot = [];


  let textProcessScope = null;



  function textProcessSelectionTargets() {
    const targets = [...MaweSelection.selectedIdxs]
      .sort((a, b) => a - b)
      .map((index) => ({ kind: 'main', index }));
    const extensionTrack = MaweMultiSubtitleCore.getActiveExtensionTrack();
    if (extensionTrack) {
      [...MaweSelection.selectedExtensionIdxs]
        .sort((a, b) => a - b)
        .forEach((index) => targets.push({
          kind: 'extension',
          index,
          trackId: extensionTrack.id,
        }));
    }
    return targets;
  }



  function textProcessAllTargets() {
    return MaweBoot.DATA.segments.map((_, index) => ({ kind: 'main', index }));
  }



  function textProcessTargetSegments(target) {
    return target?.kind === 'extension'
      ? MaweMultiSubtitleCore.getExtensionTrack(target.trackId)?.segments || []
      : MaweBoot.DATA.segments;
  }



  function textProcessTargetLabel(target) {
    return `${target?.kind === 'extension' ? '副字幕' : '主字幕'}第 ${(target?.index ?? 0) + 1} 条`;
  }



  function textProcessTargets() {
    return textProcessScope && textProcessScope.length
      ? textProcessScope
      : textProcessAllTargets();
  }



  function buildTextProcessPreview(targets, options) {
    return (Array.isArray(targets) ? targets : []).flatMap((target) => {
      const segments = textProcessTargetSegments(target);
      const segment = segments[target.index];
      if (!segment) return [];
      const before = String(segment.text == null ? '' : segment.text);
      const next = planTextProcessSegment(segment, options);
      const after = next.segment.text;
      const itemsChanged = options.cleanChinesePunctuation
        && JSON.stringify(segment.items) !== JSON.stringify(next.segment.items);
      return [{ ...target, before, after, changed: before !== after || itemsChanged }];
    });
  }

  function planTextProcessSegment(segment, options) {
    if (!options.cleanChinesePunctuation) {
      return { segment: { ...segment, text: window.AsrEditorUtils.applyTextProcessing(segment.text, options) } };
    }
    const next = window.AsrEditorUtils.planChinesePunctuationCleanup(segment);
    const cleanedText = next.text;
    next.text = window.AsrEditorUtils.applyTextProcessing(cleanedText, { ...options, cleanChinesePunctuation: false });
    let timingWarning = false;
    if (next.text !== cleanedText && Array.isArray(next.items) && next.items.length) {
      const exact = next.items.map((item) => item.text).join('') === cleanedText;
      const beforeChars = Array.from(cleanedText), afterChars = Array.from(next.text);
      if (exact && beforeChars.length === afterChars.length) {
        // Keep neutral-only and empty item ownership. The generic word mapper
        // attaches neutral text to audible items, which could duplicate it here.
        let offset = 0;
        next.items = next.items.map((item) => {
          const end = offset + Array.from(item.text).length;
          const mapped = { ...item, text: afterChars.slice(offset, end).join('') };
          offset = end;
          return mapped;
        });
      } else {
        const timingSync = exact ? window.AsrEditorUtils.planWordTimingTextSync(next, cleanedText) : null;
        if (timingSync?.items?.length === next.items.length
            && timingSync.items.map((item) => item.text).join('') === next.text) next.items = timingSync.items;
        else timingWarning = true;
      }
    }
    return { segment: next, timingWarning };
  }

  function applyPunctuationTextProcessing(rows, options) {
    const drafts = rows.filter((row) => row.changed).flatMap((row) => {
      const segments = textProcessTargetSegments(row);
      const before = segments[row.index];
      if (!before || String(before.text ?? '') !== row.before) return [];
      const plan = planTextProcessSegment(before, options);
      const scopeUpdates = row.kind === 'main'
        ? MaweTextCleanup.planPunctuationCleanupScopeUpdates(before, plan.segment) : [];
      return [{ row, segments, ...plan, scopeUpdates }];
    });
    return MaweCommands.run('文本处理', (command) => {
      let scopeChanged = false;
      drafts.forEach(({ row, segments, segment, scopeUpdates }) => {
        segment._dirty = true;
        segments[row.index] = segment;
        scopeUpdates.forEach((update) => {
          MaweTextCleanup.applyPunctuationCleanupScopeUpdate(update);
          scopeChanged = true;
        });
      });
      if (scopeChanged) {
        // Gap data caches normalize by object identity; publish the updated
        // authorization as a fresh object before refreshing playback/export UI.
        MaweBoot.DATA.gap_remove = { ...MaweBoot.DATA.gap_remove };
        MaweState.changes.gapRemoveDirty = true;
        MaweGapRemoveUi.updateGapRemoveUi();
      }
      if (drafts.some(({ row }) => row.kind === 'main')) {
        MaweMultiSubtitleCore.markMainSegmentsDirty(MaweBoot.DATA.segments);
      }
      if (drafts.some(({ row }) => row.kind === 'extension')) MaweMultiSubtitleCore.markMultiSubtitleDirty();
      MaweMultiSubtitleCore.syncBindingOffsets();
      closeTextProcessModal();
      command.commit({ cueList: true, waveform: 'overlay', preview: 'update' });
      MaweHint.flashHint(`已应用文本处理：${drafts.length} 条字幕`, 'success');
      if (drafts.some((draft) => draft.timingWarning)) {
        MaweHint.flashHint('部分字词时间码文字未随组合操作更新，请按需检查', 'warning');
      }
    }, { captureGapRemove: true });
  }



  function getTextProcessOptions() {
    const customWrap = textProcessWrapPreset?.id === 'custom';
    return {
      cleanChinesePunctuation: textProcessCleanPunctuation.checked,
      trim: textProcessTrim.checked,
      capitalize: textProcessCapitalize.checked,
      convertChineseNumbers: textProcessConvertNumbers.checked,
      stripMarkdown: textProcessStripMarkdown.checked,
      addWrapChars: Boolean(textProcessWrapPreset),
      wrapLeft: customWrap ? textProcessPrefixInput.value : (textProcessWrapPreset?.left || ''),
      wrapRight: customWrap ? textProcessSuffixInput.value : (textProcessWrapPreset?.right || ''),
      skipWrapped: true,
    };
  }



  function refreshTextProcessScopeInfo() {
    const selected = textProcessScope && textProcessScope.length;
    textProcessScopeInfo.textContent = selected
      ? `当前范围：仅选中的 ${textProcessScope.length} 条字幕`
      : `当前范围：全部 ${MaweBoot.DATA.segments.length} 条主字幕`;
    textProcessScopeInfo.classList.toggle('selected', Boolean(selected));
  }



  function refreshTextProcessSelectionControl() {
    const available = textProcessSelectionSnapshot.length > 0;
    textProcessSelectedOnlyCb.disabled = !available;
    if (!available) textProcessSelectedOnlyCb.checked = false;
    if (textProcessSelectedOnlyHint) textProcessSelectedOnlyHint.hidden = available;
    textProcessScope = textProcessSelectedOnlyCb.checked
      ? [...textProcessSelectionSnapshot] : null;
    refreshTextProcessScopeInfo();
  }



  function renderTextProcessPreview() {
    const options = getTextProcessOptions();
    const wrapHasCharacters = options.addWrapChars && (options.wrapLeft || options.wrapRight);
    const hasOperation = textProcessCleanPunctuation.checked || textProcessTrim.checked || textProcessCapitalize.checked
      || textProcessConvertNumbers.checked || textProcessStripMarkdown.checked || wrapHasCharacters;
    const targets = textProcessTargets();
    textProcessPreview.replaceChildren();
    if (!hasOperation) {
      textProcessPreview.textContent = '请选择至少一项文本处理操作';
      textProcessPreview.style.color = '';
      textProcessConfirm.disabled = true;
      return;
    }
    const rows = buildTextProcessPreview(targets, options);
    const result = {
      targetCount: rows.length,
      changedCount: rows.filter((row) => row.changed).length,
      rows,
    };
    textProcessPreview.style.color = result.changedCount ? '' : 'var(--text-muted)';
    const changedRows = result.rows.filter((row) => row.changed);
    const summary = document.createElement('div');
    summary.className = 'replace-preview-summary text-process-preview-summary';
    const summaryText = document.createElement('span');
    summaryText.textContent = result.changedCount
      ? `将处理 ${result.targetCount} 条字幕，预计修改 ${result.changedCount} 条（展开查看前后文本）`
      : `选定的 ${result.targetCount} 条字幕不会发生变化`;
    summary.appendChild(summaryText);
    const detailRows = [];
    let expandAllButton = null;
    if (changedRows.length) {
      expandAllButton = document.createElement('button');
      expandAllButton.type = 'button';
      expandAllButton.className = 'text-process-preview-toggle';
      expandAllButton.textContent = '全部展开';
      summary.appendChild(expandAllButton);
    }
    textProcessPreview.appendChild(summary);
    changedRows.forEach((row) => {
      const details = document.createElement('details');
      details.className = 'replace-preview-row';
      detailRows.push(details);
      const title = document.createElement('summary');
      title.textContent = textProcessTargetLabel(row);
      details.appendChild(title);
      const before = document.createElement('div');
      before.className = 'replace-preview-before';
      before.textContent = `处理前：${row.before}`;
      const after = document.createElement('div');
      after.className = 'replace-preview-after';
      after.textContent = `处理后：${row.after}`;
      details.append(before, after);
      textProcessPreview.appendChild(details);
    });
    if (expandAllButton) {
      const refreshExpandLabel = () => {
        expandAllButton.textContent = detailRows.every((details) => details.open)
          ? '全部收缩' : '全部展开';
      };
      expandAllButton.addEventListener('click', () => {
        const expand = !detailRows.every((details) => details.open);
        detailRows.forEach((details) => { details.open = expand; });
        refreshExpandLabel();
      });
      detailRows.forEach((details) => details.addEventListener('toggle', refreshExpandLabel));
    }
    textProcessConfirm.disabled = false;
  }



  function refreshTextProcessInputState() {
    const customWrap = textProcessWrapPreset?.id === 'custom';
    if (textProcessCustomWrapFields) textProcessCustomWrapFields.hidden = !customWrap;
    document.querySelectorAll('#text-process-wrap-presets-ass [data-wrap-preset-id], #text-process-wrap-presets-common [data-wrap-preset-id]')
      .forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.wrapPresetId === (textProcessWrapPreset?.id || '')));
    });
  }



  function closeTextProcessModal() {
    MaweDom.textProcessModal.classList.remove('show');
  }


  // 「左右添加字符」：在主字幕文本两端插入字符（支持多选批量）。插入一律双符号形式；
  // 已用同一对符号包裹的条目跳过，不重复包裹。
  // warnWordTimings=false 时不再提示字词时间码失配：右键快捷包裹属于刻意
  // 加装饰符号，字词时间码必然对不上，警告只会造成困扰。
  function applyWrapChars(scope, left, right, label = '左右添加字符', { warnWordTimings = true } = {}) {
    if (MaweInlineEdit.editingState) MaweInlineEdit.finishEdit(true);
    const indexes = [...new Set((Array.isArray(scope) ? scope : [])
      .filter((index) => Number.isInteger(index) && index >= 0 && index < MaweBoot.DATA.segments.length))]
      .sort((a, b) => a - b);
    if (!indexes.length) return;
    const { wrapCharsAroundText } = window.AsrEditorUtils;
    const previews = indexes.map((index) => ({
      index,
      ...wrapCharsAroundText(MaweBoot.DATA.segments[index]?.text, left, right),
    }));
    const skipped = previews.filter((row) => row.skipped).length;
    if (!previews.some((row) => row.changed)) {
      MaweHint.flashHint(skipped ? '选中字幕已包裹相同符号，未重复添加' : '没有可添加字符的字幕', 'invalid');
      return;
    }
    return MaweCommands.run(label, (command) => {
      let changed = 0, staleWordTimings = 0;
      previews.forEach((row) => {
        if (!row.changed) return;
        const segment = MaweBoot.DATA.segments[row.index];
        const previousText = segment.text;
        segment.text = row.text;
        segment._dirty = true;
        changed += 1;
        if (window.AsrEditorUtils.planWordTimingTextSync(segment, previousText)?.warn) staleWordTimings += 1;
      });
      command.commit({ cueList: true, waveform: 'overlay', preview: 'update' });
      MaweHistory.updateUndoRedoButtons();
      MaweHint.flashHint(
        skipped ? `已为 ${changed} 条字幕添加字符；${skipped} 条已包裹相同符号，已跳过` : `已为 ${changed} 条字幕添加字符`,
        'success',
      );
      if (warnWordTimings && staleWordTimings) {
        MaweHint.flashHint(`${staleWordTimings} 条字幕的字词时间码文字未随字符添加更新，请按需检查`, 'warning');
      }
    });
  }


  function openWrapCharsModal(scope) {
    if (MaweInlineEdit.editingState) MaweInlineEdit.finishEdit(true);
    wrapCharsScope = (Array.isArray(scope) ? scope : [...MaweSelection.selectedIdxs])
      .filter((index) => Number.isInteger(index) && index >= 0 && index < MaweBoot.DATA.segments.length);
    if (!wrapCharsScope.length) {
      MaweHint.flashHint('请先选择要处理的字幕', 'invalid');
      return;
    }
    if (wrapCharsLeftInput) wrapCharsLeftInput.value = '';
    if (wrapCharsRightInput) wrapCharsRightInput.value = '';
    wrapCharsModal?.classList.add('show');
    setTimeout(() => wrapCharsLeftInput?.focus(), 50);
  }


  function closeWrapCharsModal() {
    wrapCharsModal?.classList.remove('show');
  }



  function openTextProcessModal() {
    textProcessWrapPreset = null;
    if (!MaweBoot.DATA.segments.length && !MaweMultiSubtitleCore.getActiveExtensionTrack()?.segments?.length) {
      MaweHint.flashHint('当前没有可处理的字幕', 'invalid');
      return;
    }
    if (MaweInlineEdit.editingState) MaweInlineEdit.finishEdit(true);
    textProcessSelectionSnapshot = textProcessSelectionTargets();
    textProcessSelectedOnlyCb.checked = textProcessSelectionSnapshot.length > 0;
    refreshTextProcessSelectionControl();
    [textProcessCleanPunctuation, textProcessTrim, textProcessCapitalize, textProcessConvertNumbers,
      textProcessStripMarkdown].forEach((input) => { input.checked = false; });
    textProcessWrapPreset = null;
    textProcessPrefixInput.value = '';
    textProcessSuffixInput.value = '';
    refreshTextProcessInputState();
    MaweDom.textProcessModal.classList.add('show');
    renderTextProcessPreview();
    setTimeout(() => textProcessTrim.focus(), 50);
  }

  global.MaweTextProcess = Object.freeze({
    textProcessButton,
    textProcessSelectedOnlyCb,
    textProcessSelectedOnlyHint,
    textProcessScopeInfo,
    textProcessPreview,
    textProcessConfirm,
    textProcessCleanPunctuation,
    textProcessTrim,
    textProcessCapitalize,
    textProcessConvertNumbers,
    textProcessPrefixInput,
    textProcessSuffixInput,
    textProcessCustomWrapFields,
    textProcessStripMarkdown,
    get textProcessSelectionSnapshot() { return textProcessSelectionSnapshot; },
    set textProcessSelectionSnapshot(v) { textProcessSelectionSnapshot = v; },
    get textProcessScope() { return textProcessScope; },
    set textProcessScope(v) { textProcessScope = v; },
    textProcessSelectionTargets,
    textProcessAllTargets,
    textProcessTargetSegments,
    textProcessTargetLabel,
    textProcessTargets,
    buildTextProcessPreview,
    applyPunctuationTextProcessing,
    getTextProcessOptions,
    refreshTextProcessScopeInfo,
    refreshTextProcessSelectionControl,
    renderTextProcessPreview,
    refreshTextProcessInputState,
    closeTextProcessModal,
    openTextProcessModal,
    set textProcessWrapPreset(value) { textProcessWrapPreset = value; },
    wrapCharsModal,
    wrapCharsLeftInput,
    wrapCharsRightInput,
    get wrapCharsScope() { return wrapCharsScope; },
    set wrapCharsScope(v) { wrapCharsScope = v; },
    applyWrapChars,
    openWrapCharsModal,
    closeWrapCharsModal
  });
})(typeof window !== 'undefined' ? window : globalThis);
