"""On-demand, offline checks of the existing managed ASR runtimes.

Reports deliberately contain codes and version numbers, never child output,
exception messages, paths or environment variables. A passing CUDA smoke test
does not validate model inference or CTranslate2's CUDA/cuDNN dependencies.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from threading import Event, Lock

from maw.gui_platform import (
    popen_process_tree,
    process_group_kwargs,
    release_process_tree,
    terminate_process_tree,
)
from maw.diagnostics import app_version
from maw.runtimes import get_runtime

PROBE_TIMEOUT = 60.0  # Cold imports can take substantially longer than 3 seconds.
_PREFIX = "MAW_DIAGNOSTIC:"
_CODES = {
    "imports_ok", "import_failed", "cuda_ok", "cuda_unavailable", "cuda_failed",
    "torch_import_failed",
}

# Run inside the selected managed interpreter. Reuse its installation self-check
# verbatim; do not instantiate models or add a second dependency inventory.
_PROBE = r'''
import json, platform, sys
phase, verify = sys.argv[1:]
result = {"version": platform.python_version()}
if phase == "imports":
    try:
        exec(verify, {})
        result["code"] = "imports_ok"
    except BaseException:
        result["code"] = "import_failed"
else:
    try:
        import torch
    except BaseException:
        result["code"] = "torch_import_failed"
    else:
        try:
            if not torch.cuda.is_available():
                result["code"] = "cuda_unavailable"
            else:
                value = torch.zeros(1, device="cuda")
                value.add_(1)
                torch.cuda.synchronize()
                result["code"] = "cuda_ok" if value.item() == 1 else "cuda_failed"
        except BaseException:
            result["code"] = "cuda_failed"
torch = sys.modules.get("torch")
if torch is not None:
    result["torchVersion"] = str(getattr(torch, "__version__", ""))
    result["cudaVersion"] = str(getattr(getattr(torch, "version", None), "cuda", ""))
print("MAW_DIAGNOSTIC:" + json.dumps(result), flush=True)
'''


def _check(phase: str, code: str, version: str = "") -> dict[str, str]:
    status = "pass" if code in {"imports_ok", "cuda_ok"} else "error"
    if code in {"not_requested", "runtime_missing", "runtime_installing", "cancelled"}:
        status = "not_checked"
    elif code in {"cuda_unavailable", "timeout", "runtime_broken"}:
        status = "warning"
    result = {"id": phase, "status": status, "code": code}
    if re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", version):
        result["pythonVersion"] = version
    return result


def _package_version(value: str) -> bool:
    return re.fullmatch(
        r"\d{1,3}(?:\.\d{1,8}){1,3}(?:(?:a|b|rc|\.dev)\d{1,8})?(?:\+(?:cu\d{2,4}|cpu))?", value,
    ) is not None


def _probe(
    command: list[str], env: dict[str, str], cwd: Path, cancel: Event,
    *, timeout: float = PROBE_TIMEOUT,
) -> dict[str, str]:
    """Bound both runtime and report size; always reap our process tree."""
    if cancel.is_set():
        return {"code": "cancelled"}
    # A file avoids pipe deadlocks and keeps arbitrary native-library output out
    # of memory and reports. It is closed/deleted even on cancellation or crash.
    with tempfile.TemporaryFile() as output:
        try:
            process = popen_process_tree(
                command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=output, stderr=output, **process_group_kwargs(),
            )
        except OSError:
            return {"code": "start_failed"}
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel.wait(0.05):
                    return {"code": "cancelled"}
                if time.monotonic() >= deadline:
                    return {"code": "timeout"}
            if cancel.is_set():
                return {"code": "cancelled"}
            if process.returncode != 0:
                return {"code": "process_failed"}
            size = output.seek(0, 2)
            output.seek(max(0, size - 8192))
            for line in reversed(output.read(8192).decode("utf-8", errors="replace").splitlines()):
                if not line.startswith(_PREFIX):
                    continue
                try:
                    data = json.loads(line[len(_PREFIX):])
                except (ValueError, TypeError):
                    break
                if isinstance(data, dict) and isinstance(data.get("code"), str) and data["code"] in _CODES:
                    result = {"code": data["code"], "version": str(data.get("version", ""))}
                    for key in ("torchVersion", "cudaVersion"):
                        value = data.get(key)
                        if isinstance(value, str) and _package_version(value):
                            result[key] = value
                    return result
                break
            return {"code": "invalid_report"}
        finally:
            # Also removes any descendants left behind by an exited probe.
            try:
                terminate_process_tree(process)
            finally:
                release_process_tree(process)


def collect_runtime_diagnostics(
    runtime_key: str, test_cuda: bool, cancel: Event, model_cache_root: str | None = None,
) -> dict[str, object]:
    runtime = get_runtime(runtime_key)
    root = runtime.resolve_root()
    status = runtime.status(runtime_root=root, model_cache_root=model_cache_root)
    checks = [_check("runtime", f"runtime_{status.status}")]
    if status.ready:
        checks[0] = {"id": "runtime", "status": "pass", "code": "runtime_ready"}
    # Installing/missing/broken environments must not be executed. Checking does
    # not recover or change their manifest; the existing Repair action owns that.
    if status.ready:
        env = runtime.environment(runtime_root=root, model_cache_root=model_cache_root)
        env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        for phase in ("imports", "cuda"):
            if phase == "cuda" and not test_cuda:
                checks.append(_check(phase, "not_requested"))
                continue
            result = _probe(
                [str(runtime.interpreter(root)), "-c", _PROBE, phase, runtime.spec.verify_command],
                env, root, cancel,
            )
            check = _check(phase, result["code"], result.get("version", ""))
            for key in ("torchVersion", "cudaVersion"):
                if key in result:
                    check[key] = result[key]
            checks.append(check)
    else:
        checks.extend(_check(phase, "not_requested") for phase in ("imports", "cuda"))
    return {
        "schema": "maw.runtime-diagnostics.v1",
        "appVersion": app_version(),
        "platform": sys.platform,
        "runtimeKey": runtime_key,
        "runtimeVersion": runtime.spec.runtime_version,
        "modelInference": "not_checked",
        "checks": checks,
    }


class RuntimeDiagnostics:
    """One bounded job per Launcher, with id-scoped polling and cancellation."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._id = ""
        self._cancel = Event()
        self._running = False
        self._closed = False
        self._report: dict[str, object] | None = None
        self._worker: threading.Thread | None = None

    def start(self, runtime_key: str, test_cuda: bool, model_cache_root: str | None = None) -> dict[str, object]:
        if runtime_key not in {"local", "moss"}:
            return {"ok": False, "code": "invalid_runtime"}
        with self._lock:
            if self._closed or self._running:
                return {"ok": False, "code": "busy"}
            self._id = uuid.uuid4().hex
            self._cancel = Event()
            self._report = None
            self._running = True
            self._worker = threading.Thread(
                target=self._run, args=(runtime_key, test_cuda, self._cancel, model_cache_root), daemon=True,
            )
            self._worker.start()
            return {"ok": True, "operationId": self._id}

    def _run(self, runtime_key: str, test_cuda: bool, cancel: Event, model_cache_root: str | None) -> None:
        try:
            report = collect_runtime_diagnostics(runtime_key, test_cuda, cancel, model_cache_root)
        except Exception:
            # Exceptions can contain personal paths or credentials. Do not put
            # their messages in bridge errors, logs or downloadable reports.
            report = {
                "schema": "maw.runtime-diagnostics.v1", "runtimeKey": runtime_key,
                "modelInference": "not_checked", "checks": [_check("runtime", "check_failed")],
            }
        with self._lock:
            self._report = report
            self._running = False

    def poll(self, operation_id: str) -> dict[str, object]:
        with self._lock:
            if not operation_id or operation_id != self._id:
                return {"ok": False, "code": "unknown_operation"}
            return {"ok": True, "running": self._running, "report": self._report}

    def cancel(self, operation_id: str) -> dict[str, object]:
        with self._lock:
            if not operation_id or operation_id != self._id:
                return {"ok": False, "code": "unknown_operation"}
            if self._running:
                self._cancel.set()
            return {"ok": True, "running": self._running}

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._cancel.set()
            worker = self._worker
        if worker is not None:
            worker.join(timeout=12)
