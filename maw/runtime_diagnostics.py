"""Read-only diagnostics for the local model managed runtimes.

The Launcher deliberately keeps optional inference dependencies out of its
own process.  This module therefore performs the potentially expensive
imports in the selected managed Python interpreter and converts every
failure into a small, JSON-safe observation.  It is intentionally shared by
Qwen/FunASR, Faster-Whisper, and MOSS callers: model-specific UI code should
not need to know how a runtime is probed.

No command output, environment value, URL, or exception text is returned by
the report.  Paths are redacted before they leave this module, and all
external probes have short timeouts so a missing or damaged runtime cannot
hold the Launcher indefinitely.
"""

from __future__ import annotations

import datetime as _datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from maw.runtimes import ManagedRuntime, get_runtime
from maw.runtimes.base import RuntimeStatus


SCHEMA_VERSION: Final[str] = "1"
PYTHON_PROBE_TIMEOUT_SECONDS: Final[float] = 3.0
GPU_PROBE_TIMEOUT_SECONDS: Final[float] = 2.0

_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_~-]{0,63}$")
_SAFE_NAME_RE = re.compile(r"[^\w .+()\[\]{}@#&,'()\-/]+", re.UNICODE)
_SENSITIVE_PATH_RE = re.compile(r"(?i)(?:https?://|authorization|bearer|api[_-]?key|token=|password=)")


_PROBE_SCRIPT: Final[str] = r'''
import importlib
import importlib.metadata
import json
import platform


def package_version(module, distribution):
    value = getattr(module, "__version__", None)
    if value is None:
        try:
            value = importlib.metadata.version(distribution)
        except BaseException:
            value = None
    return value if isinstance(value, (str, int, float)) else None


def import_package(module_name, distribution):
    try:
        module = importlib.import_module(module_name)
    except BaseException:
        return {"imported": False, "version": None}
    return {"imported": True, "version": package_version(module, distribution)}


windows_nvidia_probe = __MAW_WINDOWS_NVIDIA_PROBE__
handshake = {
    "status": "not_checked" if windows_nvidia_probe else "not_applicable",
    "code": "torch_cuda_handshake_not_checked" if windows_nvidia_probe else "windows_nvidia_probe_not_applicable",
}
result = {
    "pythonVersion": platform.python_version(),
    "torch": {"imported": False, "version": None, "cudaVersion": None, "cudaAvailable": None, "deviceCount": None, "cudaHandshake": handshake},
    "ctranslate2": import_package("ctranslate2", "ctranslate2"),
    "fasterWhisper": import_package("faster_whisper", "faster-whisper"),
}
try:
    torch = importlib.import_module("torch")
except BaseException:
    pass
else:
    torch_result = result["torch"]
    torch_result["imported"] = True
    torch_result["version"] = package_version(torch, "torch")
    try:
        version = getattr(torch, "version", None)
        torch_result["cudaVersion"] = getattr(version, "cuda", None)
    except BaseException:
        torch_result["cudaVersion"] = None
    try:
        torch_result["cudaAvailable"] = bool(torch.cuda.is_available())
    except BaseException:
        torch_result["cudaAvailable"] = None
    try:
        torch_result["deviceCount"] = int(torch.cuda.device_count())
    except BaseException:
        torch_result["deviceCount"] = None
    if windows_nvidia_probe and torch_result["cudaAvailable"] is True:
        try:
            torch.zeros(1, device="cuda").item()
        except BaseException:
            torch_result["cudaHandshake"] = {"status": "error", "code": "torch_cuda_handshake_failed"}
        else:
            torch_result["cudaHandshake"] = {"status": "pass", "code": "torch_cuda_handshake_ready"}

print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
'''


def _host_platform(platform_name: str | None) -> str:
    value = str(platform_name or sys.platform).strip().casefold()
    return value or "unknown"


def _probe_script(*, platform_name: str) -> str:
    enabled = "True" if _host_platform(platform_name) == "win32" else "False"
    return _PROBE_SCRIPT.replace("__MAW_WINDOWS_NVIDIA_PROBE__", enabled)


def collect_runtime_diagnostics(
    platform_name: str | None = None,
    *,
    runtime_keys: Sequence[str] = ("local", "moss"),
    runtime_roots: Mapping[str, str | Path] | None = None,
    model_cache_root: str | Path | None = None,
    app_version: str = "",
    generated_at: _datetime.datetime | None = None,
) -> dict[str, object]:
    """Return one JSON-safe report for the requested managed runtimes.

    ``runtime_roots`` exists for tests and controlled callers.  The Launcher
    does not accept a user-provided root for this read-only operation; it lets
    each :class:`ManagedRuntime` resolve its configured path instead.
    """

    host_platform = _host_platform(platform_name)
    gpu = _probe_gpu(platform_name=host_platform)
    runtime_reports: dict[str, object] = {}
    all_items: list[Mapping[str, object]] = []
    for key in runtime_keys:
        runtime_key = str(key).strip().casefold()
        if not runtime_key:
            continue
        try:
            runtime = get_runtime(runtime_key)
        except KeyError:
            runtime_reports[runtime_key] = _unknown_runtime_report(runtime_key, platform_name=host_platform)
            continue
        root = runtime_roots.get(runtime_key) if runtime_roots else None
        report = diagnose_runtime(
            runtime,
            runtime_root=root,
            model_cache_root=model_cache_root,
            gpu=gpu,
            platform_name=host_platform,
        )
        runtime_reports[runtime_key] = report
        items = report.get("diagnostics")
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            all_items.extend(item for item in items if isinstance(item, Mapping))

    timestamp = generated_at or _datetime.datetime.now(_datetime.timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=_datetime.timezone.utc)
    timestamp = timestamp.astimezone(_datetime.timezone.utc)
    counts = {"pass": 0, "warning": 0, "error": 0, "not_checked": 0, "not_applicable": 0}
    for item in all_items:
        status = str(item.get("status") or "not_checked")
        if status in counts:
            counts[status] += 1
        else:
            counts["not_checked"] += 1
    overall = "error" if counts["error"] else ("warning" if counts["warning"] else "pass")
    safe_app_version = _safe_version(app_version) or "unknown"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "application": {"name": "MAW Launcher", "version": safe_app_version},
        "system": {
            "platform": _safe_atom(host_platform, fallback="unknown"),
            "os": _safe_atom(platform.system(), fallback="unknown"),
            "architecture": _safe_atom(platform.machine(), fallback="unknown"),
            "pythonVersion": _safe_version(platform.python_version()) or "unknown",
        },
        "gpu": gpu,
        "runtimes": runtime_reports,
        "summary": {"status": overall, "counts": counts},
        "pathsRedacted": True,
    }


def build_runtime_diagnostics_report(**kwargs: object) -> dict[str, object]:
    """Compatibility-friendly name for callers that build an export report."""

    return collect_runtime_diagnostics(**kwargs)  # type: ignore[arg-type]


def diagnose_runtime(
    runtime: ManagedRuntime,
    *,
    runtime_root: str | Path | None = None,
    model_cache_root: str | Path | None = None,
    gpu: Mapping[str, object] | None = None,
    platform_name: str | None = None,
) -> dict[str, object]:
    """Diagnose one runtime without raising optional-import failures."""

    try:
        status = runtime.status(runtime_root=runtime_root, model_cache_root=model_cache_root)
    except Exception:  # noqa: BLE001 - diagnostics must not crash the GUI.
        return _runtime_failure_report(runtime, code="runtime_status_unavailable", platform_name=platform_name)

    host_platform = _host_platform(platform_name)
    runtime_gpu = dict(gpu) if gpu is not None else _probe_gpu(platform_name=host_platform)
    item_list: list[dict[str, object]] = []
    item_list.append(_runtime_status_item(status))
    python_result = _probe_python(runtime, status, runtime_root, platform_name=host_platform)
    item_list.append(_python_item(python_result))
    item_list.append(_gpu_item(runtime_gpu))

    package_probe = python_result.get("packages")
    if not isinstance(package_probe, Mapping):
        package_probe = {}
    torch = _package_mapping(package_probe.get("torch"))
    ctranslate2 = _package_mapping(package_probe.get("ctranslate2"))
    faster_whisper = _package_mapping(package_probe.get("fasterWhisper"))

    torch_result = _torch_result(torch, python_result, platform_name=host_platform)
    item_list.extend(torch_result["items"])
    if runtime.spec.key == "local":
        item_list.append(_optional_package_item("ctranslate2", ctranslate2, python_result))
        item_list.append(_optional_package_item("faster-whisper", faster_whisper, python_result))
    else:
        item_list.append(_not_applicable_item("ctranslate2", "仅 local runtime 使用 CTranslate2 探测。", "CTranslate2 is only probed for the local runtime."))
        item_list.append(_not_applicable_item("faster-whisper", "仅 local runtime 使用 Faster-Whisper 探测。", "Faster-Whisper is only probed for the local runtime."))

    runtime_version = _safe_version(status.runtime_version) or "unknown"
    configured_version = _safe_version(runtime.spec.runtime_version) or "unknown"
    runtime_payload: dict[str, object] = {
        "runtimeKey": runtime.spec.key,
        "status": _safe_atom(status.status, fallback="unknown"),
        "ready": bool(status.ready),
        "path": redact_path(status.path),
        "runtimePath": redact_path(status.path),
        "pythonPath": redact_path(status.python_path),
        "configuredRuntimeVersion": configured_version,
        "runtimeVersion": runtime_version,
        "python": {
            "status": python_result.get("status", "not_checked"),
            "code": python_result.get("code", "python_unavailable"),
            "version": _safe_version(str(python_result.get("version") or "")) or None,
        },
        "gpu": runtime_gpu,
        "torch": torch_result["payload"],
        # Flat aliases make the report convenient for simple exporters while
        # retaining the grouped object for future fields.
        "torchVersion": torch_result["payload"].get("version"),
        "torchCudaVersion": torch_result["payload"].get("cudaVersion"),
        "torchCudaAvailable": torch_result["payload"].get("cudaAvailable"),
        "torchDeviceCount": torch_result["payload"].get("deviceCount"),
        "torchCudaHandshake": torch_result["payload"].get("cudaHandshake"),
        "ctranslate2": _package_payload(ctranslate2, python_result, applicable=runtime.spec.key == "local"),
        "fasterWhisper": _package_payload(faster_whisper, python_result, applicable=runtime.spec.key == "local"),
        "diagnostics": item_list,
    }
    if status.model_cache_path:
        runtime_payload["modelCachePath"] = redact_path(status.model_cache_path)
    return runtime_payload


def redact_path(value: str | Path | None) -> str:
    """Return a display/export-safe path with the user's home replaced."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if _SENSITIVE_PATH_RE.search(raw):
        return "<redacted-path>"
    normalized = raw.replace("/", "\\")
    prefixes: list[str] = []
    try:
        prefixes.append(str(Path.home().resolve(strict=False)))
    except (OSError, RuntimeError, ValueError):
        pass
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        prefixes.append(user_profile)
    else:
        home_drive = os.environ.get("HOMEDRIVE", "").strip()
        home_path = os.environ.get("HOMEPATH", "").strip()
        if home_drive and home_path:
            prefixes.append(home_drive + home_path)
    for prefix in prefixes:
        prefix_text = prefix.replace("/", "\\").rstrip("\\")
        if not prefix_text:
            continue
        if normalized.casefold() == prefix_text.casefold():
            return "<user-home>"
        marker = prefix_text + "\\"
        if normalized.casefold().startswith(marker.casefold()):
            return "<user-home>\\" + normalized[len(marker) :]
    return normalized


def _unknown_runtime_report(runtime_key: str, *, platform_name: str | None = None) -> dict[str, object]:
    item = _item(
        "runtime",
        "runtime_missing",
        "error",
        "未找到该运行时。",
        "This runtime is not registered.",
    )
    return {
        "runtimeKey": runtime_key,
        "status": "missing",
        "ready": False,
        "path": "",
        "runtimePath": "",
        "pythonPath": "",
        "configuredRuntimeVersion": "unknown",
        "runtimeVersion": "unknown",
        "python": {"status": "not_checked", "code": "runtime_missing", "version": None},
        "gpu": _probe_gpu(platform_name=platform_name),
        "torch": {
            **_empty_package_payload("torch", "runtime_missing"),
            "cudaHandshake": _not_applicable_or_not_checked(platform_name),
        },
        "torchVersion": None,
        "torchCudaVersion": None,
        "torchCudaAvailable": None,
        "torchDeviceCount": None,
        "torchCudaHandshake": _not_applicable_or_not_checked(platform_name),
        "ctranslate2": _empty_package_payload("ctranslate2", "runtime_missing"),
        "fasterWhisper": _empty_package_payload("faster-whisper", "runtime_missing"),
        "diagnostics": [item],
    }


def _runtime_failure_report(runtime: ManagedRuntime, *, code: str, platform_name: str | None = None) -> dict[str, object]:
    item = _item(
        "runtime",
        code,
        "error",
        "无法读取本地运行环境状态；请稍后重新扫描。",
        "The runtime status could not be read; try scanning again later.",
    )
    return {
        "runtimeKey": runtime.spec.key,
        "status": "unknown",
        "ready": False,
        "path": "",
        "runtimePath": "",
        "pythonPath": "",
        "configuredRuntimeVersion": _safe_version(runtime.spec.runtime_version) or "unknown",
        "runtimeVersion": "unknown",
        "python": {"status": "not_checked", "code": code, "version": None},
        "gpu": _probe_gpu(platform_name=platform_name),
        "torch": {
            **_empty_package_payload("torch", code),
            "cudaHandshake": _not_applicable_or_not_checked(platform_name),
        },
        "torchVersion": None,
        "torchCudaVersion": None,
        "torchCudaAvailable": None,
        "torchDeviceCount": None,
        "torchCudaHandshake": _not_applicable_or_not_checked(platform_name),
        "ctranslate2": _empty_package_payload("ctranslate2", code),
        "fasterWhisper": _empty_package_payload("faster-whisper", code),
        "diagnostics": [item],
    }


def _probe_python(
    runtime: ManagedRuntime,
    status: RuntimeStatus,
    runtime_root: str | Path | None,
    *,
    platform_name: str | None = None,
) -> dict[str, object]:
    python_path = str(status.python_path or "").strip()
    if not python_path:
        return {"status": "not_checked", "code": "python_unavailable", "version": None}
    try:
        environment = runtime.environment(runtime_root or status.path)
        result = subprocess.run(
            [python_path, "-c", _probe_script(platform_name=_host_platform(platform_name))],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PYTHON_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "code": "python_probe_timeout", "version": None}
    except (OSError, ValueError, RuntimeError):
        return {"status": "error", "code": "python_unavailable", "version": None}
    if getattr(result, "returncode", 1) != 0:
        return {"status": "error", "code": "python_probe_failed", "version": None}
    output = str(getattr(result, "stdout", "") or "")
    parsed = _parse_probe_output(output)
    if parsed is None:
        return {"status": "error", "code": "python_probe_failed", "version": None}
    return {
        "status": "pass",
        "code": "python_ready",
        "version": _safe_version(str(parsed.get("pythonVersion") or "")) or None,
        "packages": parsed,
    }


def _parse_probe_output(output: str) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get("torch"), dict):
            return value
    return None


def _probe_gpu(*, platform_name: str | None = None) -> dict[str, object]:
    if _host_platform(platform_name) != "win32":
        return _gpu_payload(
            False,
            False,
            (),
            "windows_nvidia_probe_not_applicable",
            "non_windows",
            applicable=False,
        )
    executable = shutil.which("nvidia-smi")
    if not executable:
        return _gpu_payload(False, False, (), "gpu_not_detected", "nvidia_smi_missing")
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GPU_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _gpu_payload(False, False, (), "gpu_not_detected", "nvidia_smi_timeout")
    except (OSError, ValueError):
        return _gpu_payload(False, False, (), "gpu_not_detected", "nvidia_smi_unavailable")
    if getattr(result, "returncode", 1) != 0:
        return _gpu_payload(False, False, (), "gpu_not_detected", "nvidia_smi_failed")
    names = tuple(_safe_gpu_name(line) for line in str(getattr(result, "stdout", "") or "").splitlines())
    names = tuple(name for name in names if name)
    if not names:
        return _gpu_payload(False, True, (), "gpu_not_detected", "nvidia_smi_no_gpu")
    return _gpu_payload(True, True, names, "gpu_detected", "")


def _not_applicable_or_not_checked(platform_name: str | None) -> dict[str, str]:
    if _host_platform(platform_name) != "win32":
        return {"status": "not_applicable", "code": "windows_nvidia_probe_not_applicable"}
    return {"status": "not_checked", "code": "torch_cuda_handshake_not_checked"}


def _gpu_payload(
    detected: bool,
    nvidia_smi_available: bool,
    names: Sequence[str],
    code: str,
    reason: str,
    *,
    applicable: bool = True,
) -> dict[str, object]:
    values = list(names)
    status = "pass" if detected else ("warning" if applicable else "not_applicable")
    return {
        "status": status,
        "code": code,
        "available": detected,
        "detected": detected,
        "nvidiaSmiAvailable": nvidia_smi_available,
        "names": values,
        "name": values[0] if values else "",
        "observedReason": reason,
        "note": {
            "zh": (
                "已从 nvidia-smi 读到 GPU 名称；这只是当前观测结果。"
                if detected
                else (
                    "Windows NVIDIA 专项探测仅适用于 Windows；当前平台不适用。"
                    if not applicable
                    else "未从 nvidia-smi 读到可用 GPU；这不等于驱动或 CUDA 一定不兼容。"
                )
            ),
            "en": (
                "GPU name was read from nvidia-smi; this is an observation only."
                if detected
                else (
                    "The Windows NVIDIA probe does not apply on this platform."
                    if not applicable
                    else "No usable GPU was reported by nvidia-smi; this does not by itself prove driver or CUDA incompatibility."
                )
            ),
        },
    }


def _runtime_status_item(status: RuntimeStatus) -> dict[str, object]:
    if status.status == "ready" and status.ready:
        return _item("runtime", "runtime_ready", "pass", "运行环境已就绪。", "The runtime is ready.")
    if status.status == "missing":
        return _item("runtime", "runtime_missing", "error", "未找到运行环境。", "The runtime was not found.")
    if status.status == "installing":
        return _item("runtime", "runtime_installing", "warning", "运行环境仍处于安装状态。", "The runtime is still marked as installing.")
    return _item("runtime", "runtime_broken", "warning", "运行环境需要进一步检查或修复。", "The runtime needs further checking or repair.")


def _python_item(result: Mapping[str, object]) -> dict[str, object]:
    code = str(result.get("code") or "python_unavailable")
    if code == "python_ready":
        return _item("python", code, "pass", "Python 探测成功。", "The managed Python probe succeeded.")
    if code == "python_probe_timeout":
        return _item("python", code, "error", "Python 探测超时，已停止等待。", "The Python probe timed out and was stopped.")
    if code == "python_probe_failed":
        return _item("python", code, "error", "Python 探测未返回有效结果。", "The Python probe did not return a valid result.")
    return _item("python", "python_unavailable", "error", "无法启动或定位托管 Python。", "The managed Python could not be started or located.")


def _gpu_item(gpu: Mapping[str, object]) -> dict[str, object]:
    code = str(gpu.get("code") or "gpu_not_detected")
    if code == "windows_nvidia_probe_not_applicable" or gpu.get("status") == "not_applicable":
        return _item(
            "gpu",
            "windows_nvidia_probe_not_applicable",
            "not_applicable",
            "Windows NVIDIA 专项探测不适用于当前平台。",
            "The Windows NVIDIA probe does not apply on this platform.",
        )
    if bool(gpu.get("detected")):
        return _item("gpu", code, "pass", "已探测到 NVIDIA GPU。", "An NVIDIA GPU was detected.")
    return _item("gpu", "gpu_not_detected", "warning", "未探测到可用的 NVIDIA GPU；这只是观测结果。", "No usable NVIDIA GPU was detected; this is an observation only.")


def _torch_cuda_handshake(torch: Mapping[str, object], *, platform_name: str | None = None) -> dict[str, str]:
    if _host_platform(platform_name) != "win32":
        return {"status": "not_applicable", "code": "windows_nvidia_probe_not_applicable"}
    value = torch.get("cudaHandshake")
    if isinstance(value, Mapping):
        code = str(value.get("code") or "")
        if code == "torch_cuda_handshake_ready":
            return {"status": "pass", "code": code}
        if code == "torch_cuda_handshake_failed":
            return {"status": "error", "code": code}
    return {"status": "not_checked", "code": "torch_cuda_handshake_not_checked"}


def _torch_cuda_handshake_item(handshake: Mapping[str, object]) -> dict[str, object]:
    code = str(handshake.get("code") or "torch_cuda_handshake_not_checked")
    status = str(handshake.get("status") or "not_checked")
    if code == "torch_cuda_handshake_ready":
        return _item(
            "torch-cuda-handshake",
            code,
            "pass",
            "Torch CUDA 轻量握手成功。",
            "The lightweight Torch CUDA handshake succeeded.",
        )
    if code == "torch_cuda_handshake_failed":
        return _item(
            "torch-cuda-handshake",
            code,
            "error",
            "Torch CUDA 轻量握手失败；这只是当前观测结果，请按诊断说明手动检查。",
            "The lightweight Torch CUDA handshake failed; this is an observation only. Review the diagnostic guidance manually.",
        )
    if code == "windows_nvidia_probe_not_applicable":
        return _item(
            "torch-cuda-handshake",
            code,
            "not_applicable",
            "Windows NVIDIA 专项握手不适用于当前平台。",
            "The Windows NVIDIA handshake does not apply on this platform.",
        )
    return _item(
        "torch-cuda-handshake",
        "torch_cuda_handshake_not_checked",
        "not_checked",
        "尚未执行 Torch CUDA 轻量握手。",
        "The lightweight Torch CUDA handshake was not run.",
    )


def _torch_result(
    torch: Mapping[str, object],
    python_result: Mapping[str, object],
    *,
    platform_name: str | None = None,
) -> dict[str, object]:
    imported = bool(torch.get("imported"))
    python_code = str(python_result.get("code") or "python_unavailable")
    handshake = _torch_cuda_handshake(torch, platform_name=platform_name)
    if imported:
        version = _safe_version(str(torch.get("version") or "")) or None
        cuda_version = _safe_version(str(torch.get("cudaVersion") or "")) or None
        cuda_available = torch.get("cudaAvailable") if isinstance(torch.get("cudaAvailable"), bool) else None
        device_count = torch.get("deviceCount")
        if not isinstance(device_count, int) or isinstance(device_count, bool) or device_count < 0:
            device_count = None
        items = [_item("torch", "torch_ready", "pass", "Torch 导入成功。", "Torch imported successfully.")]
        if cuda_available is True:
            items.append(_item("torch-cuda", "torch_cuda_available", "pass", "Torch 报告 CUDA 可用。", "Torch reports CUDA as available."))
        elif cuda_available is False:
            items.append(_item("torch-cuda", "torch_cuda_unavailable", "warning", "Torch 报告 CUDA 当前不可用；这不等于驱动一定不兼容。", "Torch reports CUDA unavailable right now; this does not by itself prove driver incompatibility."))
        else:
            items.append(_item("torch-cuda", "torch_cuda_probe_failed", "warning", "无法完成 Torch CUDA 状态探测。", "Torch CUDA state could not be probed."))
        items.append(_torch_cuda_handshake_item(handshake))
        payload = {
            "status": "pass",
            "code": "torch_ready",
            "version": version,
            "cudaVersion": cuda_version,
            "cudaAvailable": cuda_available,
            "deviceCount": device_count,
            "cudaHandshake": handshake,
        }
        return {"payload": payload, "items": items}
    code = "torch_import_failed" if python_code == "python_ready" else python_code
    status = "error" if code == "torch_import_failed" else "not_checked"
    message_zh = "Torch 无法导入，已记录为结构化诊断。" if code == "torch_import_failed" else "由于 Python 探测不可用，尚未检查 Torch。"
    message_en = "Torch could not be imported; the failure is recorded as a structured diagnostic." if code == "torch_import_failed" else "Torch was not checked because the Python probe was unavailable."
    return {
        "payload": {
            "status": status,
            "code": code,
            "version": None,
            "cudaVersion": None,
            "cudaAvailable": None,
            "deviceCount": None,
            "cudaHandshake": handshake,
        },
        "items": [
            _item("torch", code, status, message_zh, message_en),
            _item("torch-cuda", code, "not_checked", message_zh, message_en),
            _torch_cuda_handshake_item(handshake),
        ],
    }


def _optional_package_item(
    label: str,
    package: Mapping[str, object],
    python_result: Mapping[str, object],
) -> dict[str, object]:
    module_key = "ctranslate2" if label == "ctranslate2" else "fasterWhisper"
    imported = bool(package.get("imported"))
    if imported:
        code = "ctranslate2_ready" if label == "ctranslate2" else "faster_whisper_ready"
        display = "CTranslate2" if label == "ctranslate2" else "Faster-Whisper"
        return _item(module_key, code, "pass", f"{display} 导入成功。", f"{display} imported successfully.")
    python_code = str(python_result.get("code") or "python_unavailable")
    if python_code != "python_ready":
        return _item(module_key, python_code, "not_checked", "由于 Python 探测不可用，尚未检查该组件。", "This component was not checked because the Python probe was unavailable.")
    code = "ctranslate2_unavailable" if label == "ctranslate2" else "faster_whisper_unavailable"
    display = "CTranslate2" if label == "ctranslate2" else "Faster-Whisper"
    return _item(module_key, code, "warning", f"{display} 不可用或无法导入。", f"{display} is unavailable or could not be imported.")


def _package_payload(
    package: Mapping[str, object],
    python_result: Mapping[str, object],
    *,
    applicable: bool,
) -> dict[str, object]:
    if not applicable:
        return {"status": "not_applicable", "code": "not_applicable", "version": None, "imported": None}
    imported = bool(package.get("imported"))
    if imported:
        return {"status": "pass", "code": "package_ready", "version": _safe_version(str(package.get("version") or "")) or None, "imported": True}
    python_code = str(python_result.get("code") or "python_unavailable")
    return {"status": "not_checked" if python_code != "python_ready" else "warning", "code": python_code, "version": None, "imported": False}


def _empty_package_payload(name: str, code: str) -> dict[str, object]:
    return {"status": "not_checked", "code": code, "version": None, "imported": False, "name": name}


def _package_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _item(
    item_id: str,
    code: str,
    status: str,
    zh: str,
    en: str,
) -> dict[str, object]:
    messages = {"zh": zh, "en": en}
    return {"id": item_id, "code": code, "status": status, "message": messages, "note": messages}


def _not_applicable_item(item_id: str, zh: str, en: str) -> dict[str, object]:
    return _item(item_id, "not_applicable", "not_applicable", zh, en)


def _safe_atom(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text or "\n" in text or "\r" in text:
        return fallback
    return text[:80]


def _safe_version(value: str) -> str:
    text = str(value or "").strip()
    return text if _VERSION_RE.fullmatch(text) else ""


def _safe_gpu_name(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text or _SENSITIVE_PATH_RE.search(text):
        return ""
    text = _SAFE_NAME_RE.sub("", text).strip()
    return text[:160]


__all__ = [
    "GPU_PROBE_TIMEOUT_SECONDS",
    "PYTHON_PROBE_TIMEOUT_SECONDS",
    "SCHEMA_VERSION",
    "build_runtime_diagnostics_report",
    "collect_runtime_diagnostics",
    "diagnose_runtime",
    "redact_path",
]
