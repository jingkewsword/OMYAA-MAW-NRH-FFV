// Explicitly requested, bounded checks. Never run during settings refresh/init.
const runtimeDiagnosticState = { operationId: "", busy: false, cancelling: false, report: null, error: "" };

function renderRuntimeDiagnostics() {
  const current = runtimeDiagnosticState;
  $("runtimeDiagnosticTarget").disabled = current.busy;
  $("checkRuntimeDiagnostics").disabled = current.busy;
  $("testRuntimeCuda").disabled = current.busy;
  $("cancelRuntimeDiagnostics").classList.toggle("hidden", !current.busy);
  $("cancelRuntimeDiagnostics").disabled = current.cancelling || !current.operationId;
  $("exportRuntimeDiagnostics").disabled = current.busy || !current.report;
  const output = $("runtimeDiagnosticResult");
  output.replaceChildren();
  if (current.busy || current.error) {
    const line = document.createElement("p");
    line.className = "hint";
    line.textContent = t(current.error || (current.cancelling ? "rd_cancelling" : "rd_running"));
    output.append(line);
  }
  if (!current.report) return;
  const target = document.createElement("p");
  target.className = "hint";
  target.textContent = `${t("rd_target")}: ${current.report.runtimeKey === "moss" ? "MOSS" : t("rd_local")}`;
  output.append(target);
  for (const check of current.report.checks || []) {
    const line = document.createElement("p");
    line.className = `hint runtime-diagnostic-${check.status}`;
    line.textContent = `${t(`rd_${check.id}`)}: ${t(`rd_${check.code}`)}${check.pythonVersion ? ` · Python ${check.pythonVersion}` : ""}`;
    if (check.torchVersion) line.textContent += ` · PyTorch ${check.torchVersion}`;
    if (check.cudaVersion) line.textContent += ` · CUDA ${check.cudaVersion}`;
    output.append(line);
  }
}

async function runRuntimeDiagnostics(testCuda = false) {
  const current = runtimeDiagnosticState;
  if (current.busy) return;
  if (window.MAWLauncher.backend !== "real") {
    current.error = "rd_unavailable";
    renderRuntimeDiagnostics();
    return;
  }
  current.busy = true;
  current.cancelling = false;
  current.operationId = "";
  current.report = null;
  current.error = "";
  renderRuntimeDiagnostics();
  try {
    const started = await bridge("start_runtime_diagnostics", {
      runtimeKey: $("runtimeDiagnosticTarget").value, testCuda,
    });
    if (!started.ok) { current.error = "rd_unavailable"; return; }
    current.operationId = started.operationId;
    renderRuntimeDiagnostics();
    // Backend owns the timeout and process. Closing the drawer leaves the job
    // visible on reopening; cancelling always addresses this operation only.
    while (true) {
      const result = await bridge("get_runtime_diagnostics", { operationId: current.operationId });
      if (!result.ok) { current.error = "rd_unavailable"; return; }
      if (!result.running) { current.report = result.report; return; }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  } finally {
    current.busy = false;
    current.cancelling = false;
    renderRuntimeDiagnostics();
  }
}

async function cancelRuntimeDiagnostics() {
  const current = runtimeDiagnosticState;
  if (!current.busy || !current.operationId || current.cancelling) return;
  current.cancelling = true;
  renderRuntimeDiagnostics();
  const result = await bridge("cancel_runtime_diagnostics", { operationId: current.operationId });
  if (!result.ok) {
    current.cancelling = false;
    current.error = "rd_unavailable";
    renderRuntimeDiagnostics();
  }
}

async function exportRuntimeDiagnostics() {
  if (!runtimeDiagnosticState.report || runtimeDiagnosticState.busy) return;
  const result = await bridge("export_runtime_diagnostics", { operationId: runtimeDiagnosticState.operationId });
  if (!result.ok) { runtimeDiagnosticState.error = "rd_export_failed"; renderRuntimeDiagnostics(); }
  else if (!result.cancelled) setStatus(t("saved"));
}
