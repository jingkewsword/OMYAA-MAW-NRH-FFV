from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import mock

from maw import runtime_diagnostics as diagnostics
from maw.gui_web import LauncherApi, LauncherPaths


class RuntimeProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, PYTHONPATH=str(self.root))

    def probe(self, script: str, cancel: Event | None = None, timeout: float = 5) -> dict:
        return diagnostics._probe(
            [sys.executable, "-c", script], self.env, self.root, cancel or Event(), timeout=timeout,
        )

    def child(self, phase: str, verify: str = "pass") -> dict:
        return diagnostics._probe(
            [sys.executable, "-c", diagnostics._PROBE, phase, verify],
            self.env, self.root, Event(), timeout=5,
        )

    def test_uses_existing_verify_and_discards_noisy_private_output(self) -> None:
        result = self.child("imports", "print('PRIVATE-SENTINEL'); import json")
        self.assertEqual(result["code"], "imports_ok")
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(result))
        self.assertRegex(result["version"], r"^\d+\.\d+\.\d+$")

    def test_import_exception_never_exports_message_or_traceback(self) -> None:
        result = self.child("imports", "raise ImportError('PRIVATE-SENTINEL')")
        self.assertEqual(result["code"], "import_failed")
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(result))

    def test_native_exit_is_not_reported_as_a_known_cuda_root_cause(self) -> None:
        self.assertEqual(self.probe("import os; os._exit(23)")["code"], "process_failed")

    def test_timeout_and_cancellation_reap_real_child(self) -> None:
        processes = []
        real_spawn = diagnostics.popen_process_tree

        def spawn(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            processes.append(process)
            return process

        with mock.patch.object(diagnostics, "popen_process_tree", side_effect=spawn):
            self.assertEqual(self.probe("import time; time.sleep(30)", timeout=0.15)["code"], "timeout")
            cancel = Event()
            import threading
            timer = threading.Timer(0.15, cancel.set)
            timer.start()
            try:
                self.assertEqual(self.probe("import time; time.sleep(30)", cancel)["code"], "cancelled")
            finally:
                timer.join()
        self.assertEqual(len(processes), 2)
        self.assertTrue(all(process.poll() is not None for process in processes))

    def test_cancel_before_spawn_and_start_failure(self) -> None:
        cancel = Event()
        cancel.set()
        with mock.patch.object(diagnostics, "popen_process_tree") as spawn:
            self.assertEqual(self.probe("pass", cancel)["code"], "cancelled")
        spawn.assert_not_called()
        with mock.patch.object(diagnostics, "popen_process_tree", side_effect=OSError("PRIVATE-SENTINEL")):
            self.assertEqual(self.probe("pass"), {"code": "start_failed"})

    def test_invalid_protocol_and_oversized_output_are_bounded(self) -> None:
        for data in ('not json', '{"code":"unknown"}', '[]', '{"code": []}'):
            with self.subTest(data=data):
                self.assertEqual(self.probe(f"print('MAW_DIAGNOSTIC:' + {data!r})")["code"], "invalid_report")
        result = self.probe("print('noise' * 100000); print('MAW_DIAGNOSTIC:{\"code\":\"imports_ok\",\"version\":\"PRIVATE-SENTINEL\"}')")
        self.assertEqual(result["code"], "imports_ok")
        self.assertNotIn("pythonVersion", diagnostics._check("imports", result["code"], result["version"]))

    def test_report_accepts_only_version_numbers_and_known_fields(self) -> None:
        raw = {"code": "imports_ok", "torchVersion": "2.9.0+cu130", "cudaVersion": "13.0", "path": "PRIVATE-SENTINEL", "stderr": "PRIVATE-SENTINEL"}
        result = self.probe(f"print('MAW_DIAGNOSTIC:' + {json.dumps(raw)!r})")
        self.assertEqual(result["torchVersion"], "2.9.0+cu130")
        self.assertEqual(result["cudaVersion"], "13.0")
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(result))
        raw["torchVersion"] = "PRIVATE-SENTINEL"
        result = self.probe(f"print('MAW_DIAGNOSTIC:' + {json.dumps(raw)!r})")
        self.assertNotIn("torchVersion", result)

    def test_cuda_unavailable_success_and_failure_with_fake_torch(self) -> None:
        cases = [
            ("class C:\n def is_available(self): return False\ncuda=C()\n", "cuda_unavailable"),
            ("class C:\n def is_available(self): return True\n def synchronize(self): pass\ncuda=C()\nclass T:\n def add_(self, value): pass\n def item(self): return 1\ndef zeros(*args, **kwargs): return T()\n", "cuda_ok"),
            ("class C:\n def is_available(self): raise RuntimeError('PRIVATE-SENTINEL')\ncuda=C()\n", "cuda_failed"),
            ("raise ImportError('PRIVATE-SENTINEL')\n", "torch_import_failed"),
        ]
        for source, expected in cases:
            with self.subTest(expected=expected):
                # Disable bytecode reuse when replacing this synthetic module.
                self.env["PYTHONDONTWRITEBYTECODE"] = "1"
                (self.root / "torch.py").write_text(source, encoding="utf-8")
                result = self.child("cuda")
                self.assertEqual(result["code"], expected)
                self.assertNotIn("PRIVATE-SENTINEL", json.dumps(result))


class RuntimeDiagnosticCollectionTests(unittest.TestCase):
    def runtime(self, status: str = "ready") -> mock.Mock:
        runtime = mock.Mock()
        runtime.spec = SimpleNamespace(runtime_version="7", verify_command="EXISTING_VERIFY")
        runtime.status.return_value = SimpleNamespace(status=status, ready=status == "ready", path="PRIVATE-SENTINEL")
        runtime.resolve_root.return_value = Path("test-runtime")
        runtime.interpreter.return_value = Path("test-python")
        runtime.environment.return_value = {"PRIVATE-SENTINEL": "PRIVATE-SENTINEL"}
        return runtime

    def test_incomplete_environments_never_execute_or_repair(self) -> None:
        for status in ("missing", "installing", "broken"):
            runtime = self.runtime(status)
            with self.subTest(status=status), mock.patch.object(diagnostics, "get_runtime", return_value=runtime), mock.patch.object(diagnostics, "_probe") as probe:
                report = diagnostics.collect_runtime_diagnostics("local", True, Event())
                self.assertEqual(report["checks"][0]["code"], f"runtime_{status}")
                self.assertNotIn("PRIVATE-SENTINEL", json.dumps(report))
                probe.assert_not_called()
                runtime.install.assert_not_called()
                runtime.mark_install_aborted.assert_not_called()

    def test_runtime_spec_and_paths_reused_cuda_requires_opt_in(self) -> None:
        runtime = self.runtime()
        with mock.patch.object(diagnostics, "get_runtime", return_value=runtime) as lookup, mock.patch.object(diagnostics, "_probe", return_value={"code": "imports_ok", "version": "3.11.9"}) as probe:
            report = diagnostics.collect_runtime_diagnostics("moss", False, Event(), "configured-cache")
        lookup.assert_called_once_with("moss")
        runtime.status.assert_called_once_with(runtime_root=Path("test-runtime"), model_cache_root="configured-cache")
        runtime.environment.assert_called_once_with(runtime_root=Path("test-runtime"), model_cache_root="configured-cache")
        self.assertEqual(probe.call_count, 1)
        command, env, root, _ = probe.call_args.args
        self.assertEqual(command[-2:], ["imports", "EXISTING_VERIFY"])
        self.assertEqual(root, Path("test-runtime"))
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(report["checks"][-1]["code"], "not_requested")
        self.assertEqual(report["modelInference"], "not_checked")
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(report))

    def test_failed_imports_still_allow_independent_torch_check(self) -> None:
        with mock.patch.object(diagnostics, "get_runtime", return_value=self.runtime()), mock.patch.object(diagnostics, "_probe", side_effect=[{"code": "import_failed"}, {"code": "cuda_ok"}]) as probe:
            report = diagnostics.collect_runtime_diagnostics("local", True, Event())
        self.assertEqual(probe.call_count, 2)
        self.assertEqual([item["code"] for item in report["checks"]], ["runtime_ready", "import_failed", "cuda_ok"])


class RuntimeDiagnosticJobTests(unittest.TestCase):
    def wait_done(self, job, operation_id):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = job.poll(operation_id)
            if not result["running"]:
                return result
            time.sleep(0.01)
        self.fail("diagnostic worker did not finish")

    def test_one_job_scoped_cancel_shutdown_and_restart(self) -> None:
        entered = Event()
        received = []

        def collect(key, cuda, cancel, model_cache_root):
            received.append((key, cuda))
            entered.set()
            cancel.wait(3)
            return {"checks": [{"code": "cancelled"}]}

        job = diagnostics.RuntimeDiagnostics()
        self.addCleanup(job.shutdown)
        with mock.patch.object(diagnostics, "collect_runtime_diagnostics", side_effect=collect):
            self.assertFalse(job.start("ocr", False)["ok"])
            operation = job.start("moss", True)["operationId"]
            self.assertTrue(entered.wait(1))
            self.assertEqual(job.start("local", False)["code"], "busy")
            self.assertFalse(job.cancel("stale-id")["ok"])
            self.assertTrue(job.poll(operation)["running"])
            job.cancel(operation)
            self.wait_done(job, operation)
            next_id = job.start("local", False)["operationId"]
            self.assertFalse(job.poll(operation)["ok"])
            job.shutdown()
            self.assertFalse(job.poll(next_id)["running"])
            self.assertFalse(job.start("local", False)["ok"])
        self.assertEqual(received, [("moss", True), ("local", False)])

    def test_unexpected_exception_is_not_exported(self) -> None:
        job = diagnostics.RuntimeDiagnostics()
        self.addCleanup(job.shutdown)
        with mock.patch.object(diagnostics, "collect_runtime_diagnostics", side_effect=RuntimeError("PRIVATE-SENTINEL")):
            operation = job.start("local", False)["operationId"]
            result = self.wait_done(job, operation)
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(result))
        self.assertEqual(result["report"]["checks"][0]["code"], "check_failed")


class RuntimeDiagnosticBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        paths = LauncherPaths(root=self.root, env_path=self.root / "unused.env", launcher_html=self.root / "unused.html")
        with mock.patch("maw.gui_web._sync_local_runtime_root"):
            self.api = LauncherApi(paths=paths, window_getter=lambda: None)
        self.addCleanup(self.api._runtime_diagnostics.shutdown)

    def test_bridge_does_not_coerce_string_into_cuda_opt_in(self) -> None:
        with mock.patch.object(self.api._runtime_diagnostics, "start", return_value={"ok": True}) as start:
            self.api.start_runtime_diagnostics({"runtimeKey": "moss", "testCuda": "true"})
            self.assertEqual(start.call_args.args[:2], ("moss", False))

    def test_export_uses_completed_server_report_and_native_save_dialog(self) -> None:
        report = {"schema": "maw.runtime-diagnostics.v1", "checks": [{"code": "imports_ok"}]}
        target = self.root / "report.json"
        with mock.patch.object(self.api._runtime_diagnostics, "poll", return_value={"ok": True, "running": False, "report": report}), mock.patch("maw.gui_web._file_dialog", return_value=(str(target),)) as dialog:
            result = self.api.export_runtime_diagnostics({"operationId": "id", "report": "PRIVATE-SENTINEL", "path": "ignored"})
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), report)
        self.assertFalse(dialog.call_args.kwargs["open_dialog"])

    def test_export_rejects_running_or_stale_report_and_handles_cancel_or_io_failure(self) -> None:
        with mock.patch.object(self.api._runtime_diagnostics, "poll", return_value={"ok": False}), mock.patch("maw.gui_web._file_dialog") as dialog:
            self.assertFalse(self.api.export_runtime_diagnostics({})["ok"])
            dialog.assert_not_called()
        with mock.patch.object(self.api._runtime_diagnostics, "poll", return_value={"ok": True, "running": True, "report": {"checks": []}}):
            self.assertFalse(self.api.export_runtime_diagnostics({})["ok"])
        with mock.patch.object(self.api._runtime_diagnostics, "poll", return_value={"ok": True, "report": {"checks": []}}), mock.patch("maw.gui_web._file_dialog", return_value=None):
            self.assertTrue(self.api.export_runtime_diagnostics({})["cancelled"])
        with mock.patch.object(self.api._runtime_diagnostics, "poll", return_value={"ok": True, "report": {"checks": []}}), mock.patch("maw.gui_web._file_dialog", side_effect=OSError("PRIVATE-SENTINEL")):
            result = self.api.export_runtime_diagnostics({})
        self.assertEqual(result, {"ok": False, "code": "export_failed"})
