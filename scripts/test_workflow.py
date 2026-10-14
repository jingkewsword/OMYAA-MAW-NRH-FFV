#!/usr/bin/env python3
"""Development kernels, impact-selected merge packs, and explicit release gates."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

if __package__:
    from .run_check import run
    from .browser_results import SCHEMA, browser_config, discovery, verify_run
    from .test_policy import DEV_NODE, DEV_PYTHON, PYTHON_PACKS, node_pack, select_packs
else:
    from run_check import run
    from browser_results import SCHEMA, browser_config, discovery, verify_run
    from test_policy import DEV_NODE, DEV_PYTHON, PYTHON_PACKS, node_pack, select_packs

ROOT = Path(__file__).resolve().parents[1]
PACKS = ("docs", "common", "browser", "smoke", "media", "long-media", "lifecycle", "tools", "e2e", "editor-e2e", "website", "manual")


def changed_paths(base_ref: str | None) -> list[str]:
    args = ["git", "diff", "--name-only", "--no-renames", "-z", f"{base_ref}...HEAD" if base_ref else "HEAD"]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, check=True)
    paths = [p for p in result.stdout.decode("utf-8").split("\0") if p]
    if not base_ref:
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"],
                                  cwd=ROOT, capture_output=True, check=True)
        paths.extend(p for p in untracked.stdout.decode("utf-8").split("\0") if p)
    return sorted(set(paths))


def commands(packs: list[str], report_dir: Path, *, dev: bool = False, component: str = "all", specs=(), shard=None):
    python = sys.executable
    node = shutil.which("node") or "node"
    playwright = [node, "node_modules/@playwright/test/cli.js", "test", "--project=chromium",
                  "--forbid-only", "--workers=2", "--retries=0"]
    if dev:
        if component in {"python", "all"}:
            yield "python-kernel", [python, "scripts/run_tests.py", "--required", *DEV_PYTHON], 60
        if component in {"editor", "all"}:
            yield "editor-kernel", [node, "--test", *(f"tests/{name}" for name in DEV_NODE)], 60
        if component == "launcher":
            yield "launcher-kernel", [python, "scripts/run_tests.py", "--required", "tests.test_launcher_contract"], 60
        return
    if set(packs) & {"common", "tools"}:
        yield "python-lint", [python, "-m", "ruff", "check"], 60
    if set(packs) & {"common", "browser", "smoke", "e2e", "editor-e2e", "media", "long-media", "tools"}:
        yield "build", [node, "scripts/build-editor.mjs", "--write"], 60
        yield "build-launcher", [node, "scripts/build-launcher.mjs", "--write"], 60
        yield "typecheck", [node, "node_modules/typescript/bin/tsc", "-p", "tsconfig.typecheck.json"], 120
    for pack in packs:
        if pack == "docs":
            yield "docs-navigation", [python, "scripts/check_docs.py"], 60
            yield "release-docs", [python, "scripts/prepare_release_notes.py", "--check-all"], 60
            if "tools" not in packs:
                yield "docs-regressions", [python, "scripts/run_tests.py", "--required", "tests.test_docs_check", "tests.test_release_notes"], 120
        if pack in PYTHON_PACKS:
            yield f"python-{pack}", [python, "scripts/run_tests.py", "--pack", pack, "--required",
                   "--report", str(report_dir / f"python-{pack}.json")], 300 if pack == "long-media" else 240
        if pack in {"common", "browser", "lifecycle", "tools"}:
            targets = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "tests").glob("*.mjs")) if node_pack(p.name) == pack]
            if targets:
                yield f"node-{pack}", [node, "--test", "--test-reporter=spec", "--test-reporter-destination=stdout",
                       "--test-reporter=junit", f"--test-reporter-destination={report_dir / ('node-' + pack + '.xml')}", *targets], 240
        if pack == "smoke":
            yield "editor-http-smoke", [*playwright, "--reporter=line,json", f"--output={report_dir / 'smoke-artifacts'}", "tests/e2e/editor-bundle.spec.mjs", "tests/e2e/editor-transactions.spec.mjs"], 300
        if pack == "editor-e2e":
            # Includes Launcher specs: shared browser/host code crosses both UIs.
            yield "browser-regressions", [*playwright, "--reporter=line,json", f"--output={report_dir / 'browser-artifacts'}",
                   *([f"--shard={shard[0]}/{shard[1]}"] if shard else [])], 900
        if pack == "e2e":
            yield "browser-regressions", [*playwright, "--reporter=line,json", f"--output={report_dir / 'browser-artifacts'}",
                   *([f"--shard={shard[0]}/{shard[1]}"] if shard else []), *specs], 900
        if pack == "website":
            yield "website-build", [shutil.which("pnpm") or "pnpm", "--dir", "website", "build"], 240


def parse_shard(value: str) -> tuple[int, int]:
    if not re.fullmatch(r"[1-9]\d*/[1-9]\d*", value):
        raise argparse.ArgumentTypeError("browser-shard must be index/total, for example 1/4")
    index, total = map(int, value.split("/"))
    if index > total:
        raise argparse.ArgumentTypeError("browser-shard index exceeds total")
    return index, total


def execute(name: str, command: list[str], timeout: int) -> dict:
    print(f"Running {name} (deadline {timeout}s)", flush=True)
    _, result = run(command, timeout, ROOT / ".artifacts/checks")
    print(f"{name}: exit={result['exit_code']}; seconds={result['duration_seconds']}; log={result['log']}", flush=True)
    return {"gate": name, **result}


def prepare_browser(name, command, directory, shard, specs, selection, results):
    full_command = [arg.replace("--reporter=line,json", "--reporter=json")
                    for arg in command if not arg.startswith("--shard=")]

    def capture(label, argv):
        report_path = directory / f"{name}-{label}.json"
        os.environ["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(report_path)
        result = execute(f"{name}-discover-{label}", [*argv, "--list"], 60)
        results.append(result)
        if result["exit_code"]:
            raise ValueError(f"Browser discovery failed; log={result['log']}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return report, discovery(report)

    full_report, full_ids = capture("full", full_command)
    if not full_ids:
        raise ValueError("Required full browser discovery is empty")
    if shard:
        part_report, planned = capture("shard", [*full_command, f"--shard={shard[0]}/{shard[1]}", "--pass-with-no-tests"])
        if part_report["config"]["shard"] != {"current": shard[0], "total": shard[1]}:
            raise ValueError("Browser discovery returned incorrect shard metadata")
        if browser_config(part_report) != browser_config(full_report) or not set(planned).issubset(full_ids):
            raise ValueError("Browser shard discovery does not belong to the full scope")
    else:
        planned = full_ids
    scope = {"revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
             "worktree_clean": not subprocess.check_output(["git", "status", "--porcelain=v1"], text=True).strip(),
             "config": browser_config(full_report), "selection": selection, "specs": list(specs), "case_ids": full_ids}
    return {"schema": SCHEMA, "scope": scope,
            "shard": {"current": shard[0], "total": shard[1]} if shard else {"current": 1, "total": 1},
            "planned_ids": planned, "passed_ids": [], "status": "pending"}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("dev", "merge", "release"), default="dev")
    parser.add_argument("--component", choices=("all", "python", "editor", "launcher"), default="all")
    parser.add_argument("--pack", action="append", choices=PACKS)
    parser.add_argument("--changed", action="append", help="explicit changed path (repeatable); no shell patterns")
    parser.add_argument("--base-ref", help="Git base for CI; diff failure stops selection")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--e2e-specs", help="JSON concrete spec paths from the CI selector")
    parser.add_argument("--browser-shard", type=parse_shard, help="explicit browser partition; full success requires every shard")
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    paths = args.changed if args.changed is not None else changed_paths(args.base_ref)
    plan = select_packs(paths, release=args.stage == "release")
    packs = args.pack or plan["packs"]
    specs = json.loads(args.e2e_specs) if args.e2e_specs else plan["e2e_specs"]
    if not isinstance(specs, list) or any(not isinstance(path, str) or not path.startswith("tests/e2e/")
            or ".." in Path(path).parts or not (ROOT / path).is_file() for path in specs):
        parser.error("e2e-specs must contain existing repository spec paths")
    if "e2e" in packs and not specs:
        parser.error("e2e requires concrete specs; use editor-e2e for the full collection")
    if args.stage == "dev" and not args.pack:
        # The kernel is fixed; changed modules are run with --stage merge after
        # inspection, rather than hidden inside every edit/save cycle.
        packs = []
    if "e2e" in packs and "editor-e2e" in packs:
        parser.error("e2e and editor-e2e are mutually exclusive")
    if len(packs) != len(set(packs)):
        parser.error("duplicate packs would repeat the same gate")
    if args.browser_shard and not set(packs) & {"e2e", "editor-e2e"}:
        parser.error("browser-shard requires e2e or editor-e2e")
    plan.update(stage=args.stage, changed_paths=paths, packs=packs, e2e_specs=specs,
                browser_shard=args.browser_shard)
    output_dir = ROOT / ".artifacts/test-workflow" / uuid.uuid4().hex[:12]
    output_dir.mkdir(parents=True)
    (output_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for name in PACKS:
                output.write(f"{name.replace('-', '_')}={str(name in packs).lower()}\n")
            output.write(f"app={str(bool(set(packs) - {'docs', 'website'})).lower()}\n")
            output.write(f"preview={str(plan['preview']).lower()}\n")
            output.write(f"e2e_specs={json.dumps(specs)}\n")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"Evidence: {output_dir.relative_to(ROOT)}")
    if args.plan_only:
        return 0
    required_modules = {"numpy", "soundfile"} if set(packs) & {"common", "media", "long-media"} else set()
    if set(packs) & {"common", "tools"}:
        required_modules.add("ruff")
    if set(packs) & {"media", "long-media", "tools"}:
        required_modules.add("PIL")
    if set(packs) & {"media", "long-media"}:
        required_modules.add("quapeaks")
    missing = [name for name in sorted(required_modules) if importlib.util.find_spec(name) is None]
    if set(packs) & {"media", "long-media"}:
        missing.extend(name for name in ("ffmpeg", "ffprobe") if not shutil.which(name))
    if missing:
        report = {"status": "required-dependency-missing", "missing": missing, "exit_code": 1, "plan": plan}
        (output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Required dependencies missing: {', '.join(missing)}; gate not verified")
        return 1
    # Explicit interpreter settings avoid implicit environment synchronization.
    os.environ.setdefault("MAW_TEST_PYTHON", sys.executable)
    os.environ.setdefault("MAW_E2E_PYTHON", sys.executable)
    temp = output_dir / "tmp"
    temp.mkdir()
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(temp)
    results = []
    for name, command, timeout in commands(packs, output_dir, dev=args.stage == "dev" and not args.pack, component=args.component, specs=specs, shard=args.browser_shard):
        browser_record = None
        if name in {"editor-http-smoke", "browser-regressions"}:
            try:
                browser_record = prepare_browser(name, command, output_dir,
                    args.browser_shard if name == "browser-regressions" else None,
                    specs if "e2e" in packs and name == "browser-regressions" else [],
                    "smoke" if name == "editor-http-smoke" else "e2e" if "e2e" in packs else "editor-e2e", results)
            except (OSError, ValueError, KeyError, TypeError) as error:
                print(str(error))
                results.append({"gate": name, "status": "invalid-discovery", "exit_code": 1, "error": str(error)})
                break
            if not browser_record["planned_ids"]:
                browser_record["status"] = "empty-shard"
                (output_dir / "browser-run.json").write_text(json.dumps(browser_record, indent=2) + "\n", encoding="utf-8")
                results.append({"gate": name, "status": "empty-shard", "exit_code": 0})
                print(f"{name}: explicit zero-assignment shard of a nonempty full scope")
                continue
        browser_report = output_dir / f"{name}.json"
        os.environ["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(browser_report)
        result = execute(name, command, timeout)
        code = result["exit_code"]
        try:
            if not code and name.startswith("node-"):
                xml = ET.parse(output_dir / f"{name}.xml")
                if not xml.findall(".//testcase") or xml.findall(".//skipped"):
                    raise ValueError("Required Node report is empty or contains skipped cases")
            if not code and browser_record:
                report = json.loads(browser_report.read_text(encoding="utf-8"))
                if browser_config(report) != browser_record["scope"]["config"]:
                    raise ValueError("Browser runtime configuration differs from discovery")
                browser_record["passed_ids"] = verify_run(browser_record["planned_ids"], report)
                if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != browser_record["scope"]["revision"]:
                    raise ValueError("Git revision changed while the browser gate was running")
                browser_record["status"] = "passed"
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            code = 1
            result.update(exit_code=1, status="invalid-required-report", error=str(error))
            print(str(error))
        if browser_record:
            if code:
                browser_record["status"] = "failed"
            (output_dir / "browser-run.json").write_text(json.dumps(browser_record, indent=2) + "\n", encoding="utf-8")
        results.append(result)
        if code:
            print("\n".join(dict.fromkeys(result["diagnostics"] + result["tail"])))
            break
    summary = {"plan": plan, "results": results, "exit_code": next((r["exit_code"] for r in results if r["exit_code"]), 0)}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if summary["exit_code"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
