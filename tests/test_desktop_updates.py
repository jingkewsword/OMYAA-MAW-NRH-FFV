from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
import threading
import urllib.request
import urllib.error
from pathlib import Path
from threading import Event
from unittest import mock

from maw.desktop_updates import DesktopUpdates
from maw.updater import UpdateClient, UpdateError, UpdateCancelled, select_release
from scripts.generate_update_manifest import build_manifest
from tests.test_updater import FakeResponse


class DesktopUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def client(self, product="mose", system="win32", machine="AMD64"):
        return UpdateClient(data_root=self.root / "state", current_version="1.0.0",
                            frozen=False, product=product, system=system, machine=machine)

    def release(self, manifest):
        assets = [{"name": a["name"], "size": a["size"],
                   "browser_download_url": f'https://github.com/Moyf/moys-asr-workflow/releases/download/v2.0.0/{a["name"]}'}
                  for a in manifest["assets"]]
        return select_release([{"tag_name": "v2.0.0", "assets": assets}], "1.0.0")

    def assets(self):
        for name in ["MAW-Windows-x64-v2.0.0.zip", "MAW-Setup-Windows-x64-v2.0.0.exe",
                     "MOSE-macOS-arm64-v2.0.0.zip", "MOSE-Linux-x64-v2.0.0.AppImage"]:
            (self.root / name).write_bytes(b"package")

    def test_legacy_maw_manifest_never_contains_native_mose_assets(self):
        self.assets()
        manifest = build_manifest(self.root, "v2.0.0", include_mose_suite=True)
        self.assertTrue(all(a["name"].startswith("MAW-") for a in manifest["assets"]))
        self.assertTrue(self.client("maw")._select_asset(self.release(manifest), manifest).name.startswith("MAW-"))

    def test_mose_selects_platform_specific_package_and_uses_separate_state(self):
        self.assets()
        manifest = build_manifest(self.root, "v2.0.0", include_mose_suite=True, product="mose")
        for system, machine, prefix in [("win32", "AMD64", "MAW-Windows-"), ("darwin", "arm64", "MOSE-macOS-"), ("linux", "x86_64", "MOSE-Linux-")]:
            with self.subTest(system=system):
                client = self.client(system=system, machine=machine)
                self.assertTrue(client._select_asset(self.release(manifest), manifest).name.startswith(prefix))
        self.assertNotEqual(self.client().state_path, self.client("maw").state_path)

    def test_mose_does_not_accept_an_old_maw_only_package(self):
        self.assets()
        manifest = build_manifest(self.root, "v2.0.0")
        self.assertIsNone(self.client()._select_asset(self.release(manifest), manifest))
        # A malformed product field must produce a controlled error, not TypeError.
        manifest["assets"][0]["products"] = [{}]
        with self.assertRaises(UpdateError):
            self.client()._select_asset(self.release(manifest), manifest)

    def test_mose_check_download_hash_validation_and_ready_path(self):
        self.assets()
        manifest = build_manifest(self.root, "v2.0.0", include_mose_suite=True, product="mose")
        release = self.release(manifest)
        metadata = {"tag_name": "v2.0.0", "assets": list(release.api_assets) + [{
            "name": "mose-update-manifest.json", "browser_download_url":
            "https://github.com/Moyf/moys-asr-workflow/releases/download/v2.0.0/mose-update-manifest.json"}]}
        client = self.client()
        responses = [FakeResponse(json.dumps([metadata]).encode()), FakeResponse(json.dumps(manifest).encode()), FakeResponse(b"package")]
        with mock.patch("maw.updater.urlopen", side_effect=responses):
            result = client.check(force=True)
            self.assertTrue(result["assetAvailable"])
            path = client.download("v2.0.0")
        service = DesktopUpdates(client)
        self.assertNotIn("downloadPath", service.status()["update"])
        self.assertEqual(service.operation("ready", {"tag": "v2.0.0"})["path"], str(path))
        path.write_bytes(b"changed")
        with self.assertRaises(UpdateError):
            service.operation("ready", {"tag": "v2.0.0"})

    def test_check_jobs_are_serialized_and_report_network_errors(self):
        client = self.client()
        entered, release = Event(), Event()
        def check(**_):
            entered.set()
            release.wait(3)
            raise UpdateError("offline")
        service = DesktopUpdates(client)
        with mock.patch.object(client, "check", side_effect=check):
            self.assertEqual(service.operation("check", {})["phase"], "checking")
            self.assertTrue(entered.wait(1))
            with self.assertRaises(UpdateError): service.operation("check", {})
            release.set()
            for _ in range(100):
                if service.status()["phase"] == "error": break
                time.sleep(.01)
        self.assertEqual(service.status()["errorCode"], "offline")

    def test_cancel_download_is_not_reported_as_ready(self):
        client = self.client()
        entered = Event()
        def download(_tag, *, cancel_event, on_progress):
            on_progress(1, 5); entered.set()
            cancel_event.wait(3)
            raise UpdateCancelled()
        service = DesktopUpdates(client)
        with mock.patch.object(client, "download", side_effect=download):
            service.operation("download", {"tag": "v2.0.0"})
            self.assertTrue(entered.wait(1))
            service.operation("cancel", {})
            for _ in range(100):
                if service.status()["phase"] == "cancelled": break
                time.sleep(.01)
        self.assertEqual(service.status()["phase"], "cancelled")

    def test_installer_contains_only_build_time_source_checks(self):
        source = (Path(__file__).resolve().parents[1] / "installer/maw.iss").read_text(encoding="utf8")
        self.assertIn('#if !FileExists(MawSourceDir', source)
        self.assertNotIn("function InitializeSetup", source)
        self.assertIn('"{app}\\MOSE\\MOSE.exe"; Description: "Open MOSE', source)
        self.assertIn('ValueData: """{app}\\MOSE\\MOSE.exe"" ""%1"""', source)

    def test_private_api_requires_token_and_native_control_for_install_preparation(self):
        from tests.test_local_editor_server import server_editor as server
        editor = server.EditorServer(("127.0.0.1", 0), server.ServerProject({"segments": []}, None, None, None, []),
                                     no_waveform=True, settings_path=self.root / 'settings.json',
                                     desktop_mode=True, desktop_token="test-token")
        worker = threading.Thread(target=editor.serve_forever, daemon=True); worker.start()
        try:
            url = f"http://127.0.0.1:{editor.server_port}/api/desktop/updates"
            for payload, headers, expected in [
                ({"action": "status"}, {}, 403),
                ({"action": "ready", "tag": "v2.0.0"}, {"X-MAW-Desktop-Token": "test-token"}, 403),
                ({"action": []}, {"X-MAW-Desktop-Token": "test-token"}, 400),
            ]:
                with self.subTest(payload=payload):
                    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
                    with self.assertRaises(urllib.error.HTTPError) as result:
                        urllib.request.urlopen(request, timeout=3)
                    self.assertEqual(result.exception.code, expected)
        finally:
            editor.shutdown(); editor.server_close(); worker.join(3)
