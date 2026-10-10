MaweStickerRoot.syncControls();
MaweStickerRoot.defaultButton.addEventListener('click', () =>
  MaweStickerRoot.applyRoot('default', MaweStickerRoot.defaultInput.value));
MaweStickerRoot.projectButton.addEventListener('click', () =>
  MaweStickerRoot.applyRoot('project', MaweStickerRoot.projectInput.value));
MaweStickerRoot.overrideToggle.addEventListener('change', () => {
  if (!MaweStickerRoot.overrideToggle.checked) { MaweStickerRoot.applyRoot('project', ''); return; }
  MaweStickerRoot.projectInput.disabled = false;
  MaweStickerRoot.projectButton.disabled = false;
  MaweStickerRoot.projectInput.value = MaweBoot.STICKER_ROOT || MaweStickerRoot.getDefaultRoot();
  MaweStickerRoot.projectInput.focus();
});
if (!MaweStickerRoot.projectRoot() && MaweStickerRoot.getDefaultRoot()) MaweStickerRoot.activateProjectRoot();

// Both the personal default and project override retain native folder selection.
if (window.MOSEDesktop?.available) {
  for (const [scope, input, apply] of [
    ['default', MaweStickerRoot.defaultInput, MaweStickerRoot.defaultButton],
    ['project', MaweStickerRoot.projectInput, MaweStickerRoot.projectButton],
  ]) {
    const browse = document.createElement('button');
    browse.type = 'button';
    browse.textContent = '选择文件夹…';
    browse.id = scope === 'default' ? 'sticker-root-browse' : 'project-sticker-root-browse';
    apply.before(browse);
    browse.addEventListener('click', async () => {
      if (input.disabled) return;
      try {
        const directory = await window.MOSEDesktop.chooseDirectory();
        if (directory) await MaweStickerRoot.applyRoot(scope, directory);
      } catch (error) {
        MaweHint.flashHint(error.message || String(error), 'warning');
      }
    });
  }
}
