#!/usr/bin/env python3
"""Profile thumbnail fixture phases while retaining the real test suite.

Phase timings are inclusive, may overlap, and only include the test thread.
The ordinary full Python gate remains separate and unchanged.
"""
from __future__ import annotations

import functools
import json
import os
import sys
import threading
import time
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_tests  # noqa: E402

local = threading.local()
samples = defaultdict(list)
span_stream = None


def record(event):
    if span_stream is not None:
        span_stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        span_stream.flush()


def instrument(target, name, label):
    original = getattr(target, name)

    @functools.wraps(original)
    def measured(*args, **kwargs):
        case = getattr(local, "case", None)
        if case is not None:
            record({"event": "start", "case": case, "phase": label, "unix_seconds": time.time()})
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            if case is not None:
                item = {"phase": label, "seconds": time.perf_counter() - start}
                samples[case].append(item)
                record({"event": "finish", "case": case, **item})

    setattr(target, name, measured)


def main():
    global span_stream
    from tests import test_thumbnail_cache, test_thumbnail_server

    original_run = unittest.TestCase.run

    @functools.wraps(original_run)
    def timed_run(self, *args, **kwargs):
        previous = getattr(local, "case", None)
        local.case = self.id()
        try:
            return original_run(self, *args, **kwargs)
        finally:
            local.case = previous

    unittest.TestCase.run = timed_run
    for name, label in (("_callSetUp", "setup"), ("_callTestMethod", "test_method"),
                        ("_callTearDown", "teardown"), ("doCleanups", "cleanups")):
        instrument(unittest.TestCase, name, label)
    for name in ("load_or_build_base", "get_or_extract_frames", "sample_manifest", "read_asset", "_atomic_save"):
        instrument(test_thumbnail_cache.c, name, "cache." + name)
    for name in ("ready", "request", "stop"):
        instrument(test_thumbnail_server.ThumbnailServerTests, name, "server." + name)

    out = ROOT / ".artifacts"
    out.mkdir(parents=True, exist_ok=True)
    span_stream = (out / "thumbnail-phase-spans.jsonl").open("w", encoding="utf-8")
    try:
        code = run_tests.main([
            "tests.test_thumbnail_cache", "tests.test_thumbnail_server",
            "--report", str(out / "thumbnail-phase-results.json"),
            "--timings", str(out / "thumbnail-phase-events.jsonl"),
        ])
    finally:
        span_stream.close()
        span_stream = None
        (out / "thumbnail-phases.json").write_text(json.dumps({
            "measurement": "inclusive wall seconds; test thread only; phases may overlap",
            "samples": samples,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        try:
            with Path(summary).open("a", encoding="utf-8") as stream:
                stream.write("\n### Thumbnail phase profile\n\n")
                stream.write("Inclusive wall times; nested phases overlap. See thumbnail-phases.json for details.\n\n")
                stream.write("| Test | Setup | Test body | Cleanup | Selected operations |\n| --- | ---: | ---: | ---: | --- |\n")
                totals = []
                for case, entries in samples.items():
                    phases = defaultdict(float)
                    for entry in entries:
                        phases[entry["phase"]] += entry["seconds"]
                    totals.append((phases["setup"] + phases["test_method"] + phases["cleanups"], case, phases))
                for _, case, phases in sorted(totals, reverse=True)[:15]:
                    details = ", ".join(f"{name}: {seconds:.2f}s" for name, seconds in phases.items()
                                        if name.startswith(("cache.", "server.")))
                    stream.write(f"| `{case}` | {phases['setup']:.2f}s | {phases['test_method']:.2f}s | "
                                 f"{phases['cleanups']:.2f}s | {details} |\n")
        except OSError:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
