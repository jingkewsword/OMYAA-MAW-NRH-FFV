from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch

from scripts import appimage_support as support


@unittest.skipUnless(os.name == "posix" and shutil.which("curl") and shutil.which("bash"),
                     "Real Linux/POSIX curl, bash and executable fixtures required")
class AppImageDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.output = self.root / "AppDir" / "ffmpeg"
        self.expected = self.root / "build-side.json"
        self.asset = "ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz"
        self.archive = self.root / self.asset
        self.checksums = self.root / "checksums.sha256"

    def publish(self, revision: str = "A", *, missing: str = "", branch: str = "8.1.2") -> str:
        with tarfile.open(self.archive, "w:xz") as archive:
            for name in ("ffmpeg", "ffprobe"):
                if name == missing:
                    continue
                content = f"#!/bin/sh\nprintf '%s\\n' '{name} version {branch}-fixture-{revision}'\n".encode()
                member = tarfile.TarInfo(f"package/bin/{name}")
                member.size = len(content)
                member.mode = 0o755
                archive.addfile(member, io.BytesIO(content))
        digest = support.sha256(self.archive)
        self.checksums.write_text(f"{digest}  {self.asset}\n", encoding="utf-8")
        return digest

    def prepare(self) -> dict:
        return support.prepare_ffmpeg(self.cache, self.output, "8.1", self.asset,
                                      self.archive.as_uri(), self.checksums.as_uri(), self.expected)

    def test_same_branch_update_replaces_tools_and_provenance(self) -> None:
        first = self.publish("A")
        self.prepare()
        second = self.publish("B")
        facts = self.prepare()
        self.assertNotEqual(first, second)
        self.assertEqual(facts["archive_sha256"], second)
        self.assertIn("fixture-B", facts["binaries"]["ffmpeg"]["version"])
        self.assertEqual(support.sha256(self.output / "bin" / "ffprobe"),
                         facts["binaries"]["ffprobe"]["sha256"])
        self.assertIn(second, (self.output / "SOURCE.txt").read_text())
        self.assertEqual(len(list((self.cache / "archives").iterdir())), 2)

    def test_archive_reuse_still_refreshes_checksums_and_reextracts(self) -> None:
        self.publish()
        facts = self.prepare()
        (self.output / "bin" / "ffprobe").write_text("corrupted output")
        with patch.object(support, "download", wraps=support.download) as download:
            again = self.prepare()
        self.assertEqual([call.args[0] for call in download.call_args_list], [self.checksums.as_uri()])
        self.assertEqual(again, facts)
        self.assertEqual(support.sha256(self.output / "bin" / "ffprobe"),
                         facts["binaries"]["ffprobe"]["sha256"])

    def test_corrupt_cached_archive_is_retained_and_replaced(self) -> None:
        digest = self.publish()
        self.prepare()
        cached = self.cache / "archives" / f"{digest}-{self.asset}"
        cached.write_bytes(b"corrupt")
        self.prepare()
        self.assertEqual(support.sha256(cached), digest)
        invalid = list((self.cache / "archives").glob("*.invalid-*"))
        self.assertEqual(len(invalid), 1)
        self.assertEqual(invalid[0].read_bytes(), b"corrupt")

    def test_old_extracted_directory_cannot_bypass_missing_probe(self) -> None:
        old = self.cache / "ffmpeg-static" / "bin"
        old.mkdir(parents=True)
        (old / "ffmpeg").write_text("old executable")
        self.publish(missing="ffprobe")
        with self.assertRaisesRegex(ValueError, "regular bin/ffprobe"):
            self.prepare()
        self.assertFalse(self.expected.exists())
        self.assertFalse((self.output / "bin").exists())
        self.assertEqual((old / "ffmpeg").read_text(), "old executable")

    def test_missing_probe_does_not_overwrite_previous_valid_output(self) -> None:
        self.publish("A")
        facts = self.prepare()
        self.publish("B", missing="ffprobe")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(json.loads(self.expected.read_text()), facts)
        self.assertEqual(support.sha256(self.output / "bin" / "ffmpeg"),
                         facts["binaries"]["ffmpeg"]["sha256"])

    def test_branch_substring_does_not_accept_8_10(self) -> None:
        self.publish(branch="8.10")
        with self.assertRaisesRegex(ValueError, "Unexpected ffmpeg version"):
            self.prepare()
        self.assertFalse(self.expected.exists())

    def test_mismatched_rolling_checksum_fails_without_publishing(self) -> None:
        self.publish()
        self.checksums.write_text(f"{'0' * 64}  {self.asset}\n")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.prepare()
        self.assertFalse(self.expected.exists())
        self.assertEqual(list((self.cache / "archives").iterdir()), [])

    def test_failed_checksum_download_cannot_reuse_previous_identity(self) -> None:
        self.publish()
        facts = self.prepare()
        self.checksums.unlink()
        with self.assertRaisesRegex(ValueError, "curl failed"):
            self.prepare()
        self.assertEqual(json.loads(self.expected.read_text()), facts)

    def test_duplicate_checksum_entries_are_rejected(self) -> None:
        self.publish()
        self.checksums.write_text(self.checksums.read_text() * 2)
        with self.assertRaisesRegex(ValueError, "one valid checksum"):
            self.prepare()

    def extracted_fixture(self) -> dict:
        self.publish()
        facts = self.prepare()
        expected = {"schema": "maw.appimage-build.v1", "ffmpeg": facts, "toolchain": {}}
        support.write_json(self.output.parent / "BUILD-MANIFEST.json", expected)
        return expected

    def test_extracted_bundle_matches_independent_build_expectation(self) -> None:
        expected = self.extracted_fixture()
        support.verify_extracted(self.output.parent, expected)

    def test_tampered_probe_is_rejected_even_with_original_version_text(self) -> None:
        expected = self.extracted_fixture()
        path = self.output / "bin" / "ffprobe"
        path.write_bytes(path.read_bytes() + b"# tampered\n")
        with self.assertRaisesRegex(ValueError, "ffprobe SHA-256 mismatch"):
            support.verify_extracted(self.output.parent, expected)

    def test_tampered_source_is_rejected(self) -> None:
        expected = self.extracted_fixture()
        (self.output / "SOURCE.txt").write_text("claims a different archive")
        with self.assertRaisesRegex(ValueError, "SOURCE.txt"):
            support.verify_extracted(self.output.parent, expected)

    def test_package_manifest_is_not_its_own_authority(self) -> None:
        expected = self.extracted_fixture()
        changed = json.loads(json.dumps(expected))
        changed["ffmpeg"]["archive_sha256"] = "0" * 64
        support.write_json(self.output.parent / "BUILD-MANIFEST.json", changed)
        with self.assertRaisesRegex(ValueError, "build-side expectation"):
            support.verify_extracted(self.output.parent, expected)


class StaticRuntimeTests(unittest.TestCase):
    def elf(self, program_type: int = 1, machine: int = 62) -> bytes:
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", header, 18, machine)
        struct.pack_into("<Q", header, 32, 64)
        struct.pack_into("<HH", header, 54, 56, 1)
        entry = struct.pack("<I", program_type) + bytes(52)
        return bytes(header) + entry

    def check_elf(self, contents: bytes) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime"
            path.write_bytes(contents)
            support.require_static_x86_64(path)

    def test_static_x86_64_is_accepted(self) -> None:
        self.check_elf(self.elf())

    def test_dynamic_interpreter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dynamic interpreter"):
            self.check_elf(self.elf(program_type=3))

    def test_wrong_architecture_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "x86_64"):
            self.check_elf(self.elf(machine=183))

    def test_non_elf_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "x86_64"):
            self.check_elf(b"an HTML error page")

    def runtime_with_digest_slot(self) -> bytes:
        data = bytearray(self.elf())
        names = b"\0.shstrtab\0.digest_md5\0"
        names_offset = len(data)
        data.extend(names)
        digest_offset = len(data)
        data.extend(bytes(16))
        sections_offset = len(data)
        struct.pack_into("<Q", data, 40, sections_offset)
        struct.pack_into("<HHH", data, 58, 64, 3, 1)
        data.extend(bytes(64 * 3))
        struct.pack_into("<I", data, sections_offset + 64, 1)
        struct.pack_into("<QQ", data, sections_offset + 64 + 24, names_offset, len(names))
        struct.pack_into("<I", data, sections_offset + 128, 11)
        struct.pack_into("<QQ", data, sections_offset + 128 + 24, digest_offset, 16)
        return bytes(data)

    def test_only_the_known_md5_slot_can_change_runtime_identity(self) -> None:
        original = self.runtime_with_digest_slot()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime"
            path.write_bytes(original)
            expected = support.sha256(path)
            changed = bytearray(original)
            slot = len(self.elf()) + len(b"\0.shstrtab\0.digest_md5\0")
            changed[slot:slot + 16] = b"x" * 16
            path.write_bytes(changed)
            self.assertEqual(support.runtime_digest(path, len(original)), expected)
            changed[80] ^= 1
            path.write_bytes(changed)
            self.assertNotEqual(support.runtime_digest(path, len(original)), expected)

    def test_untrusted_runtime_is_rejected_before_any_execution(self) -> None:
        contents = self.runtime_with_digest_slot()
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "image.AppImage"
            image.write_bytes(contents)
            manifest = Path(temporary) / "expected.json"
            support.write_json(manifest, {
                "schema": "maw.appimage-build.v1",
                "toolchain": {"runtime": {"size": len(contents), "sha256": "0" * 64}},
            })
            with mock.patch.object(support, "run") as execute:
                with self.assertRaisesRegex(ValueError, "runtime bytes differ"):
                    support.verify_appimage(image, manifest)
                execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
