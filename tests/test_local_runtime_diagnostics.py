"""Focused tests for the read-only local-runtime diagnostics report."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from maw.gui_web import LauncherApi, LauncherPaths
from maw.local_runtime_diagnostics import collect_runtime_diagnostics, redact_path
from maw.runtimes import LOCAL, MOSS
from maw.runtimes.base import RuntimeStatus


def _probe_output(*, torch_imported: bool = True, ctranslate2_imported: bool = True, cuda_available: bool | None = True) -> str:
    return json.dumps(
        {
            "pythonVersion": "3.11.9",
            "torch": {
                "imported": torch_imported,
                "version": "2.13.0",
                "cudaVersion": "13.0",
                "cudaAvailable": cuda_available if torch_imported else None,
                "deviceCount": 1 if torch_imported else None,
            },
            "ctranslate2": {"imported": ctranslate2_imported, "version": "4.6.0"},
            "fasterWhisper": {"imported": ctranslate2_imported, "version": "1.2.0"},
        }
    )


class LocalRuntimeDiagnosticsTests(unittest.TestCase):
    def test_missing_runtimes_have_structured_codes_and_are_json_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("maw.runtime_diagnostics._probe_gpu", return_value={
                "status": "warning",
                "code": "gpu_not_detected",
                "available": False,
                "detected": False,
                "nvidiaSmiAvailable": False,
                "names": [],
                "name": "",
                "observedReason": "nvidia_smi_missing",
                "note": {"zh": "未探测到。", "en": "Not detected."},
            }):
                report = collect_runtime_diagnostics(
                    runtime_roots={"local": root / "local-runtime", "moss": root / "local-runtime-moss"},
                    generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )

        self.assertEqual(report["schemaVersion"], "1")
        self.assertEqual(report["generatedAt"], "2026-01-02T00:00:00Z")
        runtimes = report["runtimes"]
        self.assertIsInstance(runtimes, dict)
        for key in ("local", "moss"):
            runtime = runtimes[key]
            self.assertEqual(runtime["runtimeKey"], key)
            self.assertEqual(runtime["status"], "missing")
            self.assertEqual(runtime["python"]["code"], "python_unavailable")
            self.assertEqual(runtime["torch"]["code"], "python_unavailable")
            self.assertTrue(any(item["code"] == "runtime_missing" for item in runtime["diagnostics"]))
        json.dumps(report, ensure_ascii=False)

    def test_python_probe_reports_torch_and_local_components_without_raw_output(self) -> None:
        home = Path.home().resolve(strict=False)
        local_status = RuntimeStatus(
            status="ready",
            ready=True,
            path=str(home / "AppData" / "Local" / "MAW" / "local-runtime"),
            python_path=str(home / "AppData" / "Local" / "MAW" / "local-runtime" / "python" / "python.exe"),
            detail="ignored",
            runtime_version=LOCAL.spec.runtime_version,
        )
        moss_status = RuntimeStatus(
            status="ready",
            ready=True,
            path=str(home / "AppData" / "Local" / "MAW" / "local-runtime-moss"),
            python_path=str(home / "AppData" / "Local" / "MAW" / "local-runtime-moss" / "python" / "python.exe"),
            detail="ignored",
            runtime_version=MOSS.spec.runtime_version,
        )
        completed = SimpleNamespace(returncode=0, stdout=_probe_output())
        with mock.patch.object(LOCAL, "status", return_value=local_status), mock.patch.object(MOSS, "status", return_value=moss_status):
            with mock.patch.object(LOCAL, "environment", return_value={}), mock.patch.object(MOSS, "environment", return_value={}):
                with mock.patch("maw.runtime_diagnostics._probe_gpu", return_value={
                    "status": "pass", "code": "gpu_detected", "available": True, "detected": True,
                    "nvidiaSmiAvailable": True, "names": ["NVIDIA RTX Test"], "name": "NVIDIA RTX Test",
                    "observedReason": "", "note": {"zh": "已探测。", "en": "Detected."},
                }):
                    with mock.patch("maw.runtime_diagnostics.subprocess.run", return_value=completed) as run:
                        report = collect_runtime_diagnostics()

        local = report["runtimes"]["local"]
        moss = report["runtimes"]["moss"]
        self.assertEqual(local["torchVersion"], "2.13.0")
        self.assertEqual(local["torchCudaVersion"], "13.0")
        self.assertTrue(local["torchCudaAvailable"])
        self.assertEqual(local["torchDeviceCount"], 1)
        self.assertEqual(local["ctranslate2"]["version"], "4.6.0")
        self.assertEqual(local["fasterWhisper"]["version"], "1.2.0")
        self.assertEqual(moss["ctranslate2"]["code"], "not_applicable")
        self.assertEqual(moss["fasterWhisper"]["code"], "not_applicable")
        self.assertTrue(all(call.kwargs["timeout"] == 3.0 for call in run.call_args_list))
        exported = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("ignored", exported)
        self.assertNotIn("Authorization", exported)
        self.assertNotIn(str(home), exported)
        self.assertIn("<user-home>", exported)

    def test_gpu_probe_missing_reports_observed_failure_without_raising(self) -> None:
        with mock.patch("maw.runtime_diagnostics.shutil.which", return_value=None):
            report = collect_runtime_diagnostics(runtime_keys=())

        gpu = report["gpu"]
        self.assertFalse(gpu["nvidiaSmiAvailable"])
        self.assertFalse(gpu["available"])
        self.assertEqual(gpu["code"], "gpu_not_detected")
        json.dumps(report)

    def test_torch_cuda_unavailable_is_distinct_from_torch_import_failure(self) -> None:
        status = RuntimeStatus(
            status="ready",
            ready=True,
            path="runtime",
            python_path="runtime/python.exe",
            detail="",
            runtime_version=LOCAL.spec.runtime_version,
        )
        completed = SimpleNamespace(returncode=0, stdout=_probe_output(cuda_available=False))
        gpu = {
            "status": "warning", "code": "gpu_not_detected", "available": False, "detected": False,
            "nvidiaSmiAvailable": False, "names": [], "name": "", "observedReason": "nvidia_smi_missing",
            "note": {"zh": "未探测到。", "en": "Not detected."},
        }
        with mock.patch.object(LOCAL, "status", return_value=status), mock.patch.object(LOCAL, "environment", return_value={}):
            with mock.patch("maw.runtime_diagnostics._probe_gpu", return_value=gpu):
                with mock.patch("maw.runtime_diagnostics.subprocess.run", return_value=completed):
                    report = collect_runtime_diagnostics(runtime_keys=("local",))

        local = report["runtimes"]["local"]
        self.assertEqual(local["torch"]["code"], "torch_ready")
        self.assertFalse(local["torchCudaAvailable"])
        self.assertTrue(any(item["code"] == "torch_cuda_unavailable" for item in local["diagnostics"]))

    def test_torch_and_ctranslate2_import_failures_are_structured(self) -> None:
        status = RuntimeStatus(
            status="ready",
            ready=True,
            path="runtime",
            python_path="runtime/python.exe",
            detail="",
            runtime_version=LOCAL.spec.runtime_version,
        )
        completed = SimpleNamespace(returncode=0, stdout=_probe_output(torch_imported=False, ctranslate2_imported=False))
        gpu = {
            "status": "warning", "code": "gpu_not_detected", "available": False, "detected": False,
            "nvidiaSmiAvailable": False, "names": [], "name": "", "observedReason": "nvidia_smi_missing",
            "note": {"zh": "未探测到。", "en": "Not detected."},
        }
        with mock.patch.object(LOCAL, "status", return_value=status), mock.patch.object(LOCAL, "environment", return_value={}):
            with mock.patch("maw.runtime_diagnostics._probe_gpu", return_value=gpu):
                with mock.patch("maw.runtime_diagnostics.subprocess.run", return_value=completed):
                    report = collect_runtime_diagnostics(runtime_keys=("local",))

        local = report["runtimes"]["local"]
        self.assertEqual(local["torch"]["code"], "torch_import_failed")
        self.assertEqual(local["ctranslate2"]["status"], "warning")
        self.assertTrue(any(item["code"] == "torch_import_failed" for item in local["diagnostics"]))
        self.assertTrue(any(item["code"] == "ctranslate2_unavailable" for item in local["diagnostics"]))

    def test_timeout_and_import_failure_are_structured_without_exception_text(self) -> None:
        status = RuntimeStatus(
            status="ready",
            ready=True,
            path="runtime",
            python_path="runtime/python.exe",
            detail="not exported",
            runtime_version=LOCAL.spec.runtime_version,
        )
        with mock.patch.object(LOCAL, "status", return_value=status), mock.patch.object(LOCAL, "environment", return_value={}):
            with mock.patch("maw.runtime_diagnostics._probe_gpu", return_value={
                "status": "warning", "code": "gpu_not_detected", "available": False, "detected": False,
                "nvidiaSmiAvailable": False, "names": [], "name": "", "observedReason": "nvidia_smi_missing",
                "note": {"zh": "未探测到。", "en": "Not detected."},
            }):
                with mock.patch("maw.runtime_diagnostics.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 3)):
                    report = collect_runtime_diagnostics(runtime_keys=("local",))

        local = report["runtimes"]["local"]
        self.assertEqual(local["python"]["code"], "python_probe_timeout")
        self.assertEqual(local["torch"]["code"], "python_probe_timeout")
        self.assertEqual(local["ctranslate2"]["code"], "python_probe_timeout")
        self.assertNotIn("TimeoutExpired", json.dumps(report))

    def test_redact_path_hides_home_and_suspicious_values(self) -> None:
        home = str(Path.home()).replace("/", "\\")
        self.assertTrue(redact_path(home + "\\AppData\\Local\\MAW").startswith("<user-home>"))
        self.assertEqual(redact_path("https://user:secret@example.invalid/runtime"), "<redacted-path>")

    def test_launcher_api_returns_report_at_top_level_and_in_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = LauncherPaths(root=root, env_path=root / ".env", launcher_html=root / "launcher.html")
            expected = {"schemaVersion": "1", "runtimes": {"local": {}, "moss": {}}}
            api = LauncherApi(paths=paths)
            with mock.patch("maw.gui_web.collect_runtime_diagnostics", return_value=expected) as collect:
                result = api.get_local_runtime_diagnostics()

        self.assertTrue(result["ok"])
        self.assertEqual(result["schemaVersion"], "1")
        self.assertIs(result["report"], expected)
        collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
