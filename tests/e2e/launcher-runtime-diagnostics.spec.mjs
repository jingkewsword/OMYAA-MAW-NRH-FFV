import { test, expect } from '@playwright/test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const launcherUrl = pathToFileURL(fileURLToPath(new URL('../../web/launcher/index.html', import.meta.url))).href;

for (const [language, theme, width] of [['zh', 'light', 1000], ['en', 'dark', 760]]) {
  test(`runtime checks are explicit, cancellable and exportable (${language}, ${theme})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 950 });
    await page.goto(launcherUrl);
    await page.waitForFunction(() => window.MAWLauncher?.config?.providers?.length > 0);
    const config = await page.evaluate(() => window.MAWLauncher.config);
    await page.addInitScript(({ config, language, theme }) => {
      window.__diagnosticCalls = [];
      window.__diagnosticRunning = false;
      window.__diagnosticId = 0;
      window.pywebview = { api: new Proxy({}, { get(_, method) {
        if (method === 'then') return undefined;
        if (method === 'get_config') return async () => ({ ...config, guiLang: language, theme });
        if (method === 'start_runtime_diagnostics') return async payload => {
          window.__diagnosticCalls.push({ method, payload });
          window.__diagnosticRunning = true;
          return { ok: true, operationId: String(++window.__diagnosticId) };
        };
        if (method === 'get_runtime_diagnostics') return async () => ({
          ok: true, running: window.__diagnosticRunning,
          report: { schema: 'maw.runtime-diagnostics.v1', runtimeKey: 'moss', modelInference: 'not_checked', checks: [
            { id: 'runtime', status: 'pass', code: 'runtime_ready' },
            { id: 'imports', status: 'not_checked', code: 'cancelled' },
            { id: 'cuda', status: 'not_checked', code: 'not_requested' },
          ] },
        });
        if (method === 'cancel_runtime_diagnostics') return async payload => {
          window.__diagnosticCalls.push({ method, payload });
          window.__diagnosticRunning = false;
          return { ok: true };
        };
        if (method === 'export_runtime_diagnostics') return async payload => {
          window.__diagnosticCalls.push({ method, payload });
          return { ok: true };
        };
        return async () => ({ ok: true });
      } }) };
    }, { config, language, theme });
    await page.reload();
    await page.waitForFunction(() => window.MAWLauncher?.config?.providers?.length > 0);
    await page.locator('#provider').selectOption('local');
    await page.evaluate(() => window.MAWLauncher.openSettings('localRuntimePanel'));
    await expect(page.locator('#checkRuntimeDiagnostics')).toBeVisible();
    expect(await page.evaluate(() => window.__diagnosticCalls)).toEqual([]);
    await expect(page.locator('#exportRuntimeDiagnostics')).toBeDisabled();
    await page.locator('#runtimeDiagnosticTarget').selectOption('moss');
    await page.locator('#checkRuntimeDiagnostics').click();
    await expect(page.locator('#cancelRuntimeDiagnostics')).toBeEnabled();
    await expect(page.locator('#testRuntimeCuda')).toBeDisabled();
    await expect(page.locator('#runtimeDiagnosticTarget')).toBeDisabled();
    expect(await page.evaluate(() => window.__diagnosticCalls[0].payload)).toEqual({ runtimeKey: 'moss', testCuda: false });
    await page.evaluate(() => window.MAWLauncher.closeSettings());
    await page.evaluate(() => window.MAWLauncher.openSettings('localRuntimePanel'));
    await expect(page.locator('#cancelRuntimeDiagnostics')).toBeEnabled();
    await page.locator('#cancelRuntimeDiagnostics').click();
    await expect(page.locator('#exportRuntimeDiagnostics')).toBeEnabled();
    await expect(page.locator('#runtimeDiagnosticResult')).toContainText(language === 'zh' ? '已取消' : 'Cancelled');
    await expect(page.locator('#runtimeDiagnosticResult')).not.toContainText('rd_');
    await page.locator('#exportRuntimeDiagnostics').click();
    expect(await page.evaluate(() => window.__diagnosticCalls.at(-1))).toEqual({ method: 'export_runtime_diagnostics', payload: { operationId: '1' } });

    const gaps = await page.locator('.runtime-diagnostics').evaluate(section => {
      const children = [...section.children].filter(node => getComputedStyle(node).display !== 'none');
      return children.slice(1).map((node, i) => Math.round(node.getBoundingClientRect().top - children[i].getBoundingClientRect().bottom));
    });
    expect(gaps.every(gap => gap >= 8), JSON.stringify(gaps)).toBe(true);
    const outsideGaps = await page.locator('.runtime-diagnostics').evaluate(section => {
      const previous = section.previousElementSibling.previousElementSibling;
      const next = document.getElementById('localRuntimeProgress').nextElementSibling;
      return [section.getBoundingClientRect().top - previous.getBoundingClientRect().bottom,
        next.getBoundingClientRect().top - section.getBoundingClientRect().bottom];
    });
    expect(outsideGaps.every(gap => gap >= 8), JSON.stringify(outsideGaps)).toBe(true);
    console.log('runtime diagnostic gaps', JSON.stringify({ gaps, outsideGaps }));
    await page.locator('.runtime-diagnostics').screenshot({ path: testInfo.outputPath(`runtime-diagnostics-${language}-${theme}.png`) });

    await page.locator('#testRuntimeCuda').click();
    await expect(page.locator('#cancelRuntimeDiagnostics')).toBeEnabled();
    expect(await page.evaluate(() => window.__diagnosticCalls.filter(call => call.method === 'start_runtime_diagnostics').at(-1).payload.testCuda)).toBe(true);
    await page.locator('#cancelRuntimeDiagnostics').click();
    await expect(page.locator('#checkRuntimeDiagnostics')).toBeEnabled();
  });
}

test('static demo does not pretend to run diagnostics', async ({ page }) => {
  await page.goto(launcherUrl);
  await page.waitForFunction(() => window.MAWLauncher?.config?.providers?.length > 0);
  await page.locator('#provider').selectOption('local');
  await page.evaluate(() => window.MAWLauncher.openSettings('localRuntimePanel'));
  await page.locator('#checkRuntimeDiagnostics').click();
  await expect(page.locator('#runtimeDiagnosticResult')).toContainText('真实 Launcher');
  await expect(page.locator('#checkRuntimeDiagnostics')).toBeEnabled();
  await expect(page.locator('#exportRuntimeDiagnostics')).toBeDisabled();
});
