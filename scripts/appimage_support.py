"""Prepare and verify the Linux AppImage's build dependencies and provenance.

The rolling FFmpeg checksum is refreshed for each build. Only archives are
cached; each invocation extracts and validates both tools afresh. This module
uses the existing shell checksum verifier and curl, without GitHub API access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "scripts" / "appimage-toolchain.json"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(arguments: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180)
    if result.returncode:
        raise ValueError(f"{Path(arguments[0]).name} failed ({result.returncode}): "
                         f"{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip() or result.stderr.strip()


def download(url: str, output: Path) -> None:
    run(["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
         "--retry-delay", "2", "--connect-timeout", "20", "--max-time", "150",
         "--output", str(output), url])


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                     dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def cached_asset(cache: Path, asset: str, digest: str, url: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid SHA-256 in dependency identity")
    if PurePosixPath(asset).name != asset or "\\" in asset:
        raise ValueError("Asset must be a file name")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{digest}-{asset}"
    if target.exists():
        if sha256(target) == digest:
            print(f"Reusing verified archive: {asset} ({digest})")
            return target
        invalid = target.with_name(f"{target.name}.invalid-{time.time_ns()}")
        target.replace(invalid)
        print(f"Invalid cache retained at: {invalid}", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="download-", dir=cache) as temporary:
        staged = Path(temporary) / asset
        download(url, staged)
        if sha256(staged) != digest:
            raise ValueError(f"SHA-256 mismatch for {asset}; refusing build")
        staged.replace(target)
    return target


def checksum_identity(checksums: Path, asset: str) -> str:
    matches = []
    for line in checksums.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == asset:
            matches.append(fields[0].removeprefix("\\"))
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0]):
        raise ValueError(f"Expected one valid checksum entry for {asset}")
    return matches[0]


def tool_version(path: Path, name: str, branch: str) -> str:
    output = run([str(path), "-version"])
    first = output.splitlines()[0] if output else ""
    if not re.match(rf"^{name} version n?{re.escape(branch)}(?:[.\s-]|$)", first):
        raise ValueError(f"Unexpected {name} version for branch {branch}: {first}")
    return first


def extract_tools(archive: Path, destination: Path) -> None:
    """Extract only regular bin/ffmpeg and bin/ffprobe, rejecting duplicates/links."""
    with tarfile.open(archive, "r:xz") as stream:
        for name in ("ffmpeg", "ffprobe"):
            members = [member for member in stream.getmembers()
                       if PurePosixPath(member.name).parts[-2:] == ("bin", name)]
            if len(members) != 1 or not members[0].isfile():
                raise ValueError(f"Archive must contain exactly one regular bin/{name}")
            destination.mkdir(parents=True, exist_ok=True)
            with stream.extractfile(members[0]) as source, (destination / name).open("wb") as target:
                shutil.copyfileobj(source, target)
            (destination / name).chmod(0o755)


def prepare_ffmpeg(cache: Path, output: Path, branch: str, asset: str,
                   url: str, checksums_url: str, manifest: Path) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ffmpeg-", dir=cache) as temporary:
        stage = Path(temporary)
        checksums = stage / "checksums.sha256"
        download(checksums_url, checksums)
        digest = checksum_identity(checksums, asset)
        archive = cached_asset(cache / "archives", asset, digest, url)
        # Reuse the verifier's explicit-target-path semantics (PR #125).
        run(["bash", str(ROOT / "scripts" / "verify_sha256.sh"),
             str(checksums), asset, str(archive)])
        extract_tools(archive, stage / "bin")
        binaries = {}
        for name in ("ffmpeg", "ffprobe"):
            path = stage / "bin" / name
            binaries[name] = {"sha256": sha256(path), "version": tool_version(path, name, branch)}
        source = (
            f"FFmpeg {branch} stable branch — BtbN FFmpeg-Builds linux64-gpl static build\n"
            "Build provider: https://github.com/BtbN/FFmpeg-Builds\n"
            f"Original archive: {url}\nArchive SHA-256: {digest}\n"
            "License: GPL-3.0 (full text in GPLv3.txt)\n"
            "Upstream FFmpeg source: https://github.com/FFmpeg/FFmpeg\n"
            "This MAW package includes only ffmpeg and ffprobe from the original build.\n"
            + "".join(f"{name}: {facts['version']}\n{name} SHA-256: {facts['sha256']}\n"
                      for name, facts in binaries.items())
        )
        (stage / "SOURCE.txt").write_text(source, encoding="utf-8", newline="\n")
        facts = {"branch": branch, "asset": asset, "url": url, "archive_sha256": digest,
                 "binaries": binaries, "source_sha256": sha256(stage / "SOURCE.txt")}
        (output / "bin").mkdir(parents=True, exist_ok=True)
        for name in binaries:
            shutil.copy2(stage / "bin" / name, output / "bin" / name)
        shutil.copy2(stage / "SOURCE.txt", output / "SOURCE.txt")
        write_json(output / "BUILD-MANIFEST.json", facts)
        write_json(manifest, facts)
    return facts


def require_static_x86_64(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != 62:
            raise ValueError(f"Expected x86_64 little-endian ELF: {path.name}")
        offset = struct.unpack_from("<Q", header, 32)[0]
        entry_size, count = struct.unpack_from("<HH", header, 54)
        if entry_size < 56 or count == 0 or count > 1024:
            raise ValueError("Invalid ELF program headers")
        for index in range(count):
            stream.seek(offset + index * entry_size)
            entry = stream.read(entry_size)
            if len(entry) != entry_size:
                raise ValueError("Truncated ELF program header")
            if struct.unpack_from("<I", entry)[0] == 3:  # PT_INTERP
                raise ValueError(f"Runtime has a dynamic interpreter: {path.name}")


def runtime_digest(path: Path, size: int) -> str:
    """Hash runtime bytes, zeroing only appimagetool's 16-byte image MD5 slot.

    appimagetool 1.9.1 embeds the final image digest in .digest_md5. The official
    runtime has zeros there; every other byte, including its ELF section table,
    must still match the pinned official runtime SHA-256.
    """
    if not 64 < size < 4 * 1024 * 1024:
        raise ValueError("Invalid fixed runtime size")
    with path.open("rb") as stream:
        data = bytearray(stream.read(size))
    if len(data) != size:
        raise ValueError("Truncated runtime")
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    entry_size, count, names_index = struct.unpack_from("<HHH", data, 58)
    if entry_size < 64 or not 0 < count <= 1024 or names_index >= count:
        raise ValueError("Invalid runtime ELF section table")
    if section_offset + entry_size * count > size:
        raise ValueError("Runtime ELF section table is outside runtime")
    names_header = section_offset + entry_size * names_index
    names_offset, names_size = struct.unpack_from("<QQ", data, names_header + 24)
    if names_offset + names_size > size:
        raise ValueError("Invalid runtime section names")
    names = data[names_offset:names_offset + names_size]
    slots = []
    for index in range(count):
        header = section_offset + index * entry_size
        name_offset = struct.unpack_from("<I", data, header)[0]
        if name_offset >= len(names):
            raise ValueError("Invalid runtime section name offset")
        name = names[name_offset:].split(b"\0", 1)[0]
        if name == b".digest_md5":
            slots.append(struct.unpack_from("<QQ", data, header + 24))
    if len(slots) != 1 or slots[0][1] != 16 or slots[0][0] + 16 > size:
        raise ValueError("Expected exactly one 16-byte .digest_md5 runtime slot")
    data[slots[0][0]:slots[0][0] + 16] = bytes(16)
    return hashlib.sha256(data).hexdigest()


def prepare_toolchain(output: Path, manifest: Path) -> dict:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    facts = {}
    for name, pin in pins.items():
        archive = cached_asset(output / "archives", pin["asset"], pin["sha256"], pin["url"])
        target = output / pin["asset"]
        shutil.copy2(archive, target)
        target.chmod(0o755)
        if name == "runtime":
            require_static_x86_64(target)
            if runtime_digest(target, target.stat().st_size) != pin["sha256"]:
                raise ValueError("Official runtime does not have the expected empty MD5 slot")
            version = run([str(target), "--appimage-version"])
        else:
            version = run([str(target), "--appimage-extract-and-run", "--version"])
        if pin["source_commit"] not in version:
            raise ValueError(f"Unexpected official {name} source version: {version}")
        facts[name] = {**pin, "version": version, "size": target.stat().st_size}
        if name == "runtime":
            facts[name]["license_sha256"] = sha256(ROOT / "scripts" / "licenses" / "appimage-runtime.txt")
    write_json(manifest, facts)
    return facts


def combine_manifests(ffmpeg: Path, toolchain: Path, output: Path) -> None:
    write_json(output, {"schema": "maw.appimage-build.v1",
                       "ffmpeg": json.loads(ffmpeg.read_text(encoding="utf-8")),
                       "toolchain": json.loads(toolchain.read_text(encoding="utf-8"))})


def verify_extracted(root: Path, expected: dict) -> None:
    if json.loads((root / "BUILD-MANIFEST.json").read_text(encoding="utf-8")) != expected:
        raise ValueError("Bundled build manifest differs from the build-side expectation")
    ffmpeg = expected["ffmpeg"]
    if set(ffmpeg["binaries"]) != {"ffmpeg", "ffprobe"}:
        raise ValueError("Build expectation must contain both FFmpeg tools")
    if sha256(root / "ffmpeg" / "SOURCE.txt") != ffmpeg["source_sha256"]:
        raise ValueError("FFmpeg SOURCE.txt differs from verified build provenance")
    if json.loads((root / "ffmpeg" / "BUILD-MANIFEST.json").read_text(encoding="utf-8")) != ffmpeg:
        raise ValueError("Bundled FFmpeg manifest differs from build-side expectation")
    for name, facts in ffmpeg["binaries"].items():
        path = root / "ffmpeg" / "bin" / name
        if sha256(path) != facts["sha256"]:
            raise ValueError(f"Bundled {name} SHA-256 mismatch")
        if tool_version(path, name, ffmpeg["branch"]) != facts["version"]:
            raise ValueError(f"Bundled {name} version mismatch")


def verify_appimage(appimage: Path, manifest: Path) -> None:
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    if expected.get("schema") != "maw.appimage-build.v1":
        raise ValueError("Unsupported build manifest schema")
    require_static_x86_64(appimage)
    runtime = expected["toolchain"]["runtime"]
    # Authenticate the external runtime bytes before executing any image flags.
    # The independent build manifest supplies the boundary; the runtime's
    # reported payload offset is checked below only after its identity is known.
    digest = runtime_digest(appimage, runtime["size"])
    if digest != runtime["sha256"]:
        raise ValueError("Embedded runtime bytes differ from fixed official runtime")
    version = run([str(appimage.resolve()), "--appimage-version"])
    if version != runtime["version"]:
        raise ValueError("Embedded runtime version differs from fixed build runtime")
    # appimagetool prepends the provided runtime. Its payload offset gives the
    # exact boundary, allowing its bytes to be checked against the official pin.
    offset = int(run([str(appimage.resolve()), "--appimage-offset"]))
    if offset != runtime["size"]:
        raise ValueError("Embedded runtime length differs from fixed build runtime")
    with tempfile.TemporaryDirectory(prefix="appimage-verification-") as temporary:
        run([str(appimage.resolve()), "--appimage-extract"], cwd=Path(temporary))
        extracted = Path(temporary) / "squashfs-root"
        verify_extracted(extracted, expected)
        if sha256(extracted / "APPIMAGE-RUNTIME-LICENSE.txt") != runtime["license_sha256"]:
            raise ValueError("Bundled runtime license notice mismatch")
    print("OK: fixed static runtime, bundled FFmpeg/FFprobe and build provenance verified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ffmpeg = commands.add_parser("prepare-ffmpeg")
    for argument in ("cache", "output", "manifest"):
        ffmpeg.add_argument(f"--{argument}", type=Path, required=True)
    for argument in ("branch", "asset", "url", "checksums-url"):
        ffmpeg.add_argument(f"--{argument}", required=True)
    toolchain = commands.add_parser("prepare-toolchain")
    toolchain.add_argument("--output", type=Path, required=True)
    toolchain.add_argument("--manifest", type=Path, required=True)
    combined = commands.add_parser("build-manifest")
    for argument in ("ffmpeg", "toolchain", "output"):
        combined.add_argument(f"--{argument}", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--appimage", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare-ffmpeg":
            prepare_ffmpeg(args.cache, args.output, args.branch, args.asset, args.url,
                           args.checksums_url, args.manifest)
        elif args.command == "prepare-toolchain":
            prepare_toolchain(args.output, args.manifest)
        elif args.command == "build-manifest":
            combine_manifests(args.ffmpeg, args.toolchain, args.output)
        else:
            verify_appimage(args.appimage, args.manifest)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        print(f"AppImage build verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
