// Desktop-only update surface; the native host owns privileged operations.
(function initDesktopUpdates() {
  const host = window.MOSEDesktop;
  if (!host?.update) return;
  const text = (zh, en) => window.MAWE_I18N?.language === 'en' ? en : zh;
  const button = document.createElement('button');
  button.type = 'button'; button.id = 'desktop-update-toggle';
  document.getElementById('help-toggle')?.after(button);
  const panel = document.createElement('dialog');
  panel.id = 'desktop-update-dialog'; panel.className = 'desktop-update-dialog';
  panel.setAttribute('aria-labelledby', 'desktop-update-title');
  panel.innerHTML = '<div class="desktop-update-content"><h2 id="desktop-update-title"></h2>'
    + '<p id="desktop-update-version"></p><p id="desktop-update-status" role="status" aria-live="polite"></p>'
    + '<progress id="desktop-update-progress" max="100" value="0" hidden></progress>'
    + '<label><input type="checkbox" id="desktop-update-auto"> <span id="desktop-update-auto-label"></span></label>'
    + '<details><summary id="desktop-update-notes-label"></summary><pre id="desktop-update-notes"></pre></details>'
    + '<div class="desktop-update-actions"><button type="button" data-update="check"></button>'
    + '<button type="button" data-update="download"></button><button type="button" data-update="cancel"></button>'
    + '<button type="button" data-update="reveal"></button><button type="button" data-update="install"></button>'
    + '<button type="button" data-update="release"></button><button type="button" data-update="close"></button></div></div>';
  document.body.append(panel);
  const find = (id) => panel.querySelector(`#desktop-update-${id}`);
  let state = { phase: 'idle', update: {}, progress: {} }, timer = null, inFlight = false, hostPackaged = false;
  let message = '';
  const errors = {
    offline: ['无法连接更新服务，请检查网络后重试。', 'Could not reach the update service. Check your connection and retry.'],
    rate_limited: ['更新服务暂时限流，请稍后重试。', 'The update service is rate limited. Please try again later.'],
    manifest_missing: ['该版本未提供 MOSE 更新清单，请查看发布页。', 'This release has no MOSE update manifest. See the release page.'],
    checksum_mismatch: ['更新包校验失败，请重新下载。', 'Package verification failed. Download it again.'],
    update_cancelled: ['下载已取消。', 'Download cancelled.'],
  };
  function render() {
    const update = state.update || {}, busy = ['checking', 'downloading'].includes(state.phase);
    const ready = state.phase === 'ready' || (state.phase !== 'error' && Boolean(update.downloaded));
    button.textContent = update.available ? text('有新版本', 'Update available') : text('软件更新', 'Updates');
    find('title').textContent = text('MOSE 软件更新', 'MOSE updates');
    find('version').textContent = text('当前版本：', 'Current version: ') + (update.currentVersion || '—')
      + (update.latestVersion ? text(' · 最新版本：', ' · Latest version: ') + update.latestVersion : '');
    const knownError = errors[state.errorCode || update.errorCode];
    const status = message || (state.phase === 'checking' ? text('正在检查更新…', 'Checking for updates…')
      : state.phase === 'downloading' ? text('正在下载并校验更新包…', 'Downloading and verifying the update…')
      : knownError ? text(...knownError)
      : state.phase === 'error' ? text('更新失败，请重试。', 'Update failed. Please retry.') + ` (${state.errorCode})`
      : ready ? text('下载已完成。安装前会再次校验更新包。', 'Download complete. The package will be verified again before installation.')
      : update.available ? update.assetAvailable ? text('有新版本可下载。', 'An update is available to download.')
        : text('该版本没有适用于此 MOSE 的更新包，请查看发布页。', 'No compatible MOSE package is available. See the release page.')
      : update.lastCheckedAt ? text('当前频道没有更新版本。', 'No newer release is available on this channel.')
      : text('点击检查更新获取最新版本。', 'Check for updates to fetch the latest version.'));
    find('status').textContent = status;
    find('auto-label').textContent = text('启动时自动检查（每天一次）', 'Check at startup (once per day)');
    if (!inFlight) find('auto').checked = update.autoCheck !== false;
    find('auto').disabled = busy || inFlight;
    find('notes-label').textContent = text('更新说明', 'Release notes');
    find('notes').textContent = update.releaseNotes || text('暂无更新说明。', 'No release notes available.');
    const progress = state.progress || {};
    find('progress').hidden = state.phase !== 'downloading';
    find('progress').value = progress.total ? Math.min(100, 100 * progress.received / progress.total) : 0;
    if (state.phase === 'downloading' && progress.total) find('status').textContent += ` ${(progress.received / 1048576).toFixed(1)} / ${(progress.total / 1048576).toFixed(1)} MB`;
    const labels = { check: ['检查更新', 'Check for updates'], download: ['下载更新', 'Download update'],
      cancel: ['取消下载', 'Cancel download'], reveal: ['显示更新包', 'Show downloaded package'],
      install: ['退出并安装', 'Quit and install'], release: ['发布页', 'Releases'], close: ['关闭', 'Close'] };
    for (const action of panel.querySelectorAll('[data-update]')) {
      const id = action.dataset.update;
      action.textContent = text(...labels[id]);
      action.hidden = id === 'download' ? !update.available || !update.assetAvailable || ready
        : id === 'cancel' ? state.phase !== 'downloading'
        : id === 'reveal' ? !ready
        : id === 'install' ? !ready || !hostPackaged || update.capability !== 'installer' : false;
      action.disabled = inFlight || (busy && !['cancel', 'close', 'release'].includes(id));
    }
  }
  async function refresh() {
    try { state = await host.update({ action: 'status' }); render(); }
    catch (error) { message = String(error.message || error); render(); }
    clearTimeout(timer);
    if (panel.open || ['checking', 'downloading'].includes(state.phase)) timer = setTimeout(refresh, 1000);
  }
  async function act(action, extra = {}) {
    if (inFlight) return;
    inFlight = true; message = ''; render();
    try {
      const result = await host.update({ action, tag: state.update?.latestTag, ...extra });
      if (result.update) state = result;
    } catch (error) { message = String(error.message || error); }
    finally { inFlight = false; await refresh(); }
    if (['checking', 'downloading'].includes(state.phase)) { clearTimeout(timer); timer = setTimeout(refresh, 250); }
  }
  button.addEventListener('click', () => { panel.showModal(); void refresh(); });
  panel.addEventListener('click', (event) => {
    const action = event.target.closest('[data-update]')?.dataset.update;
    if (action === 'close') panel.close();
    else if (action) void act(action, action === 'check' ? { force: true } : {});
  });
  panel.addEventListener('close', () => { button.focus(); });
  find('auto').addEventListener('change', (event) => void act('preferences', { autoCheck: event.target.checked }));
  document.addEventListener('mawe:languagechange', render);
  render();
  host.state().then(async (info) => {
    hostPackaged = info.packaged === true;
    await refresh();
    if (hostPackaged) await act('check', { force: false });
  }).catch(() => {});
})();
