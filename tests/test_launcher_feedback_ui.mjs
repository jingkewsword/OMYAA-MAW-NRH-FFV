import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const launcherDir = new URL("../web/launcher/", import.meta.url);
const html = readFileSync(new URL("index.html", launcherDir), "utf8");
const source = readFileSync(new URL("postprocess.js", launcherDir), "utf8");
const strings = readFileSync(new URL("i18n/launcher-strings.js", launcherDir), "utf8");

test("AI processing exposes current-operation cancel and streamed output", () => {
  assert.match(source, /bridge\("run_ai_cleanup",\s*\{[\s\S]*?operationId,/);
  assert.match(source, /bridge\("run_llm_postprocess",\s*\{[\s\S]*?operationId,/);
  assert.match(source, /bridge\("cancel_postprocess",\s*\{\s*operationId\s*\}\)/);
  assert.match(source, /result\.code === "postprocess_cancelled"/);
  assert.match(source, /result\?\.cancelled === false[\s\S]*?toolbox_ai_cancel_too_late/);
  assert.match(source, /if \(!busy \|\| postprocessCancelling\) return;/);
  assert.match(strings, /toolbox_ai_cancel_too_late:\s*"AI 处理已进入收尾或保存阶段，无法取消。"/);
  assert.match(strings, /toolbox_ai_cancel_too_late:\s*"AI processing has reached finalization or saving/);
  assert.match(source, /if \(!activePostprocessOperationId \|\| event\.operationId !== activePostprocessOperationId\) return;/);
  assert.match(source, /event\.operationId !== activePostprocessOperationId\) return;/);
  assert.match(source, /beginStreamOutput\(\);[\s\S]*?setBusy\(true, "toolbox_status_ai_cleanup"\)/);
  assert.match(html, /id="stopToolboxPostprocess"[^>]*class="ghost hidden"/);
  assert.match(html, /id="toolboxStreamOutput"/);
  assert.match(strings, /toolbox_stop_ai:\s*"停止 AI 处理"/);
  assert.match(strings, /toolbox_stop_ai:\s*"Stop AI processing"/);
});

test("missing AI provider offers settings and media rebuild tab alone stays hidden", () => {
  assert.match(source, /toolbox_ai_cleanup_need_provider"\), "error", \{ showAiSettings: true \}\)/);
  assert.match(source, /openSettings\("llmSettingsSection"\)/);
  assert.match(html, /id="toolboxPostprocessSettings"[^>]*data-i18n="toolbox_open_ai_settings"/);
  assert.match(html, /id="toolboxFfconcatTab" class="toolbox-tab hidden"/);
  assert.match(html, /id="toolboxFfconcatPanel"/);
  assert.match(html, /id="toolboxUtilitiesTabList"[^]*?<div class="toolbox-tab-list">/);
});

test("green-screen generation does not require or disable for missing media", () => {
  const mediaAction = source.match(/function renderMediaToolAction\(\) \{([\s\S]*?)\n  \}/)?.[1] || "";
  const burnAction = source.match(/async function runBurnSubtitle\(\) \{([\s\S]*?)\n  \}/)?.[1] || "";
  assert.match(mediaAction, /burn\.disabled = busy;/);
  assert.doesNotMatch(mediaAction, /utilityMediaPath|mediaPath/);
  assert.match(burnAction, /if \(!greenScreen && !mediaPath\)/);
  assert.match(burnAction, /mediaPath: greenScreen \? "" : mediaPath/);
});
