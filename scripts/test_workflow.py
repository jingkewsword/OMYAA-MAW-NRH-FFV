#!/usr/bin/env python3
"""Development kernels, impact-selected merge packs, and explicit release gates."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

if __package__:
    from .run_check import run
    from .browser_results import SCHEMA, browser_config, discovery, verify_run
    from .test_policy import CHECKLIST_NODE, CHECKLIST_PYTHON, CHECKLIST_SPECS, DEV_NODE, DEV_PYTHON, PYTHON_PACKS, WINDOWS_FFMPEG_TESTS, node_pack, select_packs
else:
    from run_check import run
    from browser_results import SCHEMA, browser_config, discovery, verify_run
    from test_policy import CHECKLIST_NODE, CHECKLIST_PYTHON, CHECKLIST_SPECS, DEV_NODE, DEV_PYTHON, PYTHON_PACKS, WINDOWS_FFMPEG_TESTS, node_pack, select_packs

ROOT = Path(__file__).resolve().parents[1]
PACKS = ("docs", "common", "browser", "smoke", "media", "long-media", "lifecycle", "tools", "e2e", "editor-e2e", "website", "manual")


def windows_short_path(path: str) -> str:
    get_short = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    get_short.restype = ctypes.c_uint
    size = get_short(path, None, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(size)
    length = get_short(path, buffer, size)
    if not length or length >= size:
        raise OSError("GetShortPathNameW failed or returned an incomplete path")
    return buffer.value


def select_ci_short_temp(stack: ExitStack, environment: dict) -> tuple[Path, str]:
    candidates = [("TEMP", environment.get("TEMP")),
                  ("LOCALAPPDATA/Temp", str(Path(environment["LOCALAPPDATA"]) / "Temp") if environment.get("LOCALAPPDATA") else None),
                  ("USERPROFILE", environment.get("USERPROFILE")),
                  ("SystemDrive", environment.get("SystemDrive", "") + "\\" if environment.get("SystemDrive") else None)]
    for label, root in candidates:
        if not root or not Path(root).is_absolute():
            continue
        try:
            probe = tempfile.TemporaryDirectory(prefix="maw-ci-short-path-probe-long-", dir=root)
        except OSError:
            continue
        try:
            path = Path(probe.name)
            short = Path(windows_short_path(str(path)))
            if (short.name.casefold() != path.name.casefold()
                    and short != path.resolve() and short.samefile(path)):
                stack.enter_context(probe)
                return path, label
        except OSError:
            pass
        probe.cleanup()
    raise OSError("No candidate temporary location provides a distinct, same-file Windows 8.3 alias")


def ci_short_temp_enabled(packs) -> bool:
    return (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("MAW_CI_SHORT_TEMP") == "1"
            and os.name == "nt" and "common" in packs)


@contextmanager
def temporary_environment(values: dict[str, str]):
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def changed_paths(base_ref: str | None) -> list[str]:
    args = ["git", "diff", "--name-only", "--no-renames", "-z"]
    comparisons = [[*args, f"{base_ref}...HEAD"]] if base_ref else [args, [*args, "--cached"]]
    paths = []
    for comparison in comparisons:
        result = subprocess.run(comparison, cwd=ROOT, capture_output=True, check=True)
        paths.extend(p for p in result.stdout.decode("utf-8").split("\0") if p)
    if not base_ref:
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"],
                                  cwd=ROOT, capture_output=True, check=True)
        paths.extend(p for p in untracked.stdout.decode("utf-8").split("\0") if p)
    return sorted(set(paths))


def preparation(packs, specs=(), tools_scope="all"):
    """Unknown/mixed browser consumers retain the existing application/media prep."""
    checklist_only = bool(specs) and set(specs).issubset(CHECKLIST_SPECS)
    app = bool(set(packs) & {"common", "browser", "smoke", "editor-e2e", "media", "long-media"}
               or "tools" in packs and tools_scope != "checklist"
               or "e2e" in packs and not checklist_only)
    media = bool(set(packs) & {"media", "long-media", "editor-e2e"}
                 or "e2e" in packs and not checklist_only)
    return {"application": app, "real_media": media}


def commands(packs: list[str], report_dir: Path, *, dev: bool = False, component: str = "all", specs=(), shard=None, tools_scope="all"):
    python = sys.executable
    node = shutil.which("node") or "node"
    playwright = [node, "node_modules/@playwright/test/cli.js", "test", "--config=tests/config/playwright.config.mjs", "--project=chromium",
                  "--forbid-only", "--workers=2", "--retries=0"]
    if dev:
        if component in {"python", "all"}:
            yield "python-kernel", [python, "scripts/run_tests.py", "--required", *DEV_PYTHON], 60
        if component in {"editor", "all"}:
            yield "editor-kernel", [node, "--test", *(f"tests/{name}" for name in DEV_NODE)], 60
        if component in {"launcher", "all"}:
            yield "launcher-kernel", [python, "scripts/run_tests.py", "--required", "tests.test_launcher_contract"], 60
        return
    if "common" in packs or "tools" in packs and tools_scope != "checklist":
        yield "python-lint", [python, "-m", "ruff", "check"], 60
    if preparation(packs, specs, tools_scope)["application"]:
        yield "build", [node, "scripts/build-editor.mjs", "--write"], 60
        yield "build-launcher", [node, "scripts/build-launcher.mjs", "--write"], 60
        yield "typecheck", [node, "node_modules/typescript/bin/tsc", "-p", "web/tsconfig.typecheck.json"], 120
    for pack in packs:
        if pack == "lifecycle" and os.name == "nt":
            yield "python-windows-ffmpeg", [python, "scripts/run_tests.py", "--required",
                   "--report", str(report_dir / "python-windows-ffmpeg.json"), *WINDOWS_FFMPEG_TESTS], 60
        if pack == "docs":
            yield "docs-navigation", [python, "scripts/check_docs.py"], 60
            yield "release-docs", [python, "scripts/prepare_release_notes.py", "--check-all"], 60
            if "tools" not in packs or tools_scope == "checklist":
                yield "docs-regressions", [python, "scripts/run_tests.py", "--required", "tests.test_docs_check", "tests.test_release_notes",
                                           "tests.test_release_site", "tests.test_release_publication"], 120
        if pack in PYTHON_PACKS:
            targets = list(CHECKLIST_PYTHON) if pack == "tools" and tools_scope == "checklist" else ["--pack", pack]
            # Pack discovery retains unittest package/import/load_tests semantics.
            # The measured file-parallel engine remains available for full discovery.
            yield f"python-{pack}", [python, "scripts/run_tests.py", *targets, "--required",
                   "--report", str(report_dir / f"python-{pack}.json")], 300 if pack == "long-media" else 240
        if pack in {"common", "browser", "lifecycle", "tools"}:
            targets = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "tests").glob("*.mjs")) if node_pack(p.name) == pack]
            if pack == "tools" and tools_scope == "checklist":
                targets = [CHECKLIST_NODE]
            if not targets:
                raise ValueError(f"No Node tests found for required pack: {pack}")
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
            yield "website-docs", [node, "website/scripts/sync-maw-docs.mjs"], 60
            yield "website-releases", [python, "scripts/build_release_site.py", "--preview"], 180
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
        required_specs = [arg for arg in command if arg.startswith("tests/e2e/") and arg.endswith(".spec.mjs")]
        return report, discovery(report, required_specs)

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
            "planned_ids": planned, "passed_ids": [], "allowed_skipped_ids": [], "status": "pending"}


def report_counts(kind, path):
    keys = {"python": ("selected", "run", "failures", "errors", "skipped"),
            "node": ("run", "failures", "errors", "skipped"),
            "browser": ("passed", "failures", "skipped", "flaky")}[kind]
    counts = dict.fromkeys(keys, "unknown")
    try:
        if kind == "node":
            xml = ET.parse(path)
            cases = xml.findall(".//testcase")
            if cases:
                counts.update(run=len(cases), failures=len(xml.findall(".//failure")),
                              errors=len(xml.findall(".//error")), skipped=len(xml.findall(".//skipped")))
        else:
            report = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                return counts
            if kind == "python":
                if isinstance(report.get("selected_ids"), list):
                    counts["selected"] = len(report["selected_ids"])
                if isinstance(report.get("skips"), list):
                    counts["skipped"] = len(report["skips"])
                for name in ("run", "failures", "errors"):
                    if type(report.get(name)) is int and report[name] >= 0:
                        counts[name] = report[name]
            else:
                stats = report.get("stats", {})
                if not isinstance(stats, dict):
                    return counts
                for key, field in (("passed", "expected"), ("failures", "unexpected"), ("skipped", "skipped"), ("flaky", "flaky")):
                    if type(stats.get(field)) is int and stats[field] >= 0:
                        counts[key] = stats[field]
    except (OSError, ValueError, TypeError, ET.ParseError):
        pass
    return counts


def browser_diagnostic_counts(path: Path) -> dict:
    unknown = dict.fromkeys(("passed", "failures", "skipped", "flaky"), "unknown")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(report, dict) or not isinstance(report.get("config"), dict)
                or not isinstance(report.get("suites"), list) or not isinstance(report.get("stats"), dict)):
            return unknown
    except (OSError, ValueError):
        return unknown
    return report_counts("browser", path)


def write_execution_summary(output_dir, plan, results, not_run, exit_code, *, status=None, error=None):
    summary = {"plan": plan, "results": results, "not_run": not_run, "exit_code": exit_code}
    if status:
        summary["status"] = status
    if error:
        summary["error"] = error
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        lines = ["## Test workflow execution", "", f"Selected packs: {', '.join(plan['packs']) or 'none'}", "",
                 "| Gate | Result | Process status | Exit | Seconds | Counts |", "| --- | --- | --- | --- | --- | --- |"]
        for result in results:
            process_status = result.get("process_status", result.get("status", "unknown"))
            outcome = "passed" if result["exit_code"] == 0 and result.get("status") not in {"timeout", "interrupted", "invalid-required-report", "invalid-discovery"} else "failed"
            counts = result.get("counts", {})
            lines.append(f"| {result['gate']} | {outcome} | {process_status} | {result['exit_code']} | {result.get('duration_seconds', '—')} | {json.dumps(counts, ensure_ascii=False)} |")
        for name in not_run:
            lines.append(f"| {name} | not-run | — | — | — | — |")
        if error:
            lines.extend(["", f"Workflow error ({status or 'unknown'}): {error}"])
        lines.extend(["", "Reports and logs are in the test evidence artifact. Python counts are aggregate; individual passing outcomes are not recorded.", ""])
        with open(destination, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines))


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
    parser.add_argument("--tools-scope", choices=("all", "checklist"), help="explicit tool consumer scope from the CI selector")
    parser.add_argument("--browser-shard", type=parse_shard, help="explicit browser partition; full success requires every shard")
    args = parser.parse_args(argv)
    if args.stage == "release" and args.pack:
        parser.error("release runs the full required set; use --stage merge for a partial pack")
    os.chdir(ROOT)
    paths = args.changed if args.changed is not None else changed_paths(args.base_ref)
    plan = select_packs(paths, release=args.stage == "release")
    packs = args.pack or plan["packs"]
    specs = json.loads(args.e2e_specs) if args.e2e_specs else plan["e2e_specs"]
    if not isinstance(specs, list) or any(not isinstance(path, str) or not path.startswith("tests/e2e/") or not path.endswith(".spec.mjs")
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
    tools_scope = args.tools_scope or ("all" if args.pack else plan.get("tools_scope", "all"))
    if args.stage == "release" or set(packs) - {"docs", "tools", "e2e", "website"} or (
            "e2e" in packs and not (specs and set(specs).issubset(CHECKLIST_SPECS))):
        tools_scope = "all"
    plan.update(stage=args.stage, changed_paths=paths, packs=packs, e2e_specs=specs,
                browser_shard=args.browser_shard, tools_scope=tools_scope,
                preparation=preparation(packs, specs, tools_scope))
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
            output.write(f"tools_scope={tools_scope}\n")
            for name, needed in plan['preparation'].items():
                output.write(f"{name}={str(needed).lower()}\n")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"Evidence: {output_dir.relative_to(ROOT)}")
    if args.plan_only:
        return 0
    try:
        steps = list(commands(packs, output_dir, dev=args.stage == "dev" and not args.pack, component=args.component, specs=specs, shard=args.browser_shard, tools_scope=tools_scope))
    except ValueError as error:
        write_execution_summary(output_dir, plan, [], [], 1, status="invalid-plan", error=str(error))
        print(str(error))
        return 1
    required_modules = {"numpy", "soundfile"} if set(packs) & {"common", "media", "long-media"} else set()
    if "common" in packs or "tools" in packs and tools_scope != "checklist":
        required_modules.add("ruff")
    if set(packs) & {"media", "long-media"} or "tools" in packs and tools_scope != "checklist":
        required_modules.add("PIL")
    if set(packs) & {"media", "long-media"}:
        required_modules.add("quapeaks")
    missing = [name for name in sorted(required_modules) if importlib.util.find_spec(name) is None]
    if set(packs) & {"media", "long-media"}:
        missing.extend(name for name in ("ffmpeg", "ffprobe") if not shutil.which(name))
    if missing:
        write_execution_summary(output_dir, plan, [], [name for name, _, _ in steps], 1,
                                status="required-dependency-missing", error=", ".join(missing))
        print(f"Required dependencies missing: {', '.join(missing)}; gate not verified")
        return 1
    # Explicit interpreter settings avoid implicit environment synchronization.
    os.environ.setdefault("MAW_TEST_PYTHON", sys.executable)
    os.environ.setdefault("MAW_E2E_PYTHON", sys.executable)
    results = []
    phase = "preparation"
    failure_status = None
    failure_error = None
    active_gate = None
    try:
        with ExitStack() as stack:
            if ci_short_temp_enabled(packs):
                temp_root, location = select_ci_short_temp(stack, os.environ)
                plan["python_common_temp_location"] = location
                (output_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"Windows CI python-common temporary location: {location}")
                short_temp = temp_root / "workflow-temp"
                short_temp.mkdir()
            else:
                short_temp = None
            temp = output_dir / "tmp"
            temp.mkdir()
            for key in ("TEMP", "TMP", "TMPDIR"):
                os.environ[key] = str(temp)
            phase = "execution"
            for name, command, timeout in steps:
                active_gate = name
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
                        browser_record["diagnostic_counts"] = {"passed": 0, "failures": 0, "skipped": 0, "flaky": 0}
                        (output_dir / f"{name}-browser-run.json").write_text(json.dumps(browser_record, indent=2) + "\n", encoding="utf-8")
                        results.append({"gate": name, "status": "empty-shard", "exit_code": 0})
                        print(f"{name}: explicit zero-assignment shard of a nonempty full scope")
                        continue
                browser_report = output_dir / f"{name}.json"
                os.environ["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(browser_report)
                if name == "python-common" and short_temp is not None:
                    with temporary_environment({key: str(short_temp) for key in ("TEMP", "TMP", "TMPDIR")}):
                        result = execute(name, command, timeout)
                else:
                    result = execute(name, command, timeout)
                code = result["exit_code"]
                result["process_status"] = result.get("status", "unknown")
                if "--report" in command:
                    result["counts"] = report_counts("python", Path(command[command.index("--report") + 1]))
                elif name.startswith("node-"):
                    result["counts"] = report_counts("node", output_dir / f"{name}.xml")
                elif browser_record:
                    result["counts"] = browser_diagnostic_counts(browser_report)
                    browser_record["diagnostic_counts"] = dict(result["counts"])
                try:
                    if not code and "--report" in command:
                        report = json.loads(Path(command[command.index("--report") + 1]).read_text(encoding="utf-8"))
                        if (not report["selected_ids"] or report["run"] != len(report["selected_ids"])
                                or report["exit_code"] != 0
                                or any(report[key] for key in ("failures", "errors", "expected_failures", "unexpected_successes"))
                                or any(not skip["platform_not_applicable"] for skip in report["skips"])):
                            raise ValueError("Required Python report is empty or contains unverified outcomes")
                    if not code and name.startswith("node-"):
                        xml = ET.parse(output_dir / f"{name}.xml")
                        if not xml.findall(".//testcase") or any(xml.findall(f".//{tag}") for tag in ("skipped", "failure", "error")):
                            raise ValueError("Required Node report is empty or contains non-passing cases")
                    if not code and browser_record:
                        report = json.loads(browser_report.read_text(encoding="utf-8"))
                        if browser_config(report) != browser_record["scope"]["config"]:
                            raise ValueError("Browser runtime configuration differs from discovery")
                        browser_record.update(verify_run(browser_record["planned_ids"], report))
                        result["counts"]["selected"] = len(browser_record["planned_ids"])
                        result["counts"]["allowed_skipped"] = len(browser_record["allowed_skipped_ids"])
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
                    (output_dir / f"{name}-browser-run.json").write_text(json.dumps(browser_record, indent=2) + "\n", encoding="utf-8")
                results.append(result)
                if code:
                    print("\n".join(dict.fromkeys(result["diagnostics"] + result["tail"])))
                    break
            phase = "cleanup"
    except OSError as error:
        failure_status = {"preparation": "short-temp-preparation-failed",
                          "execution": "execution-error", "cleanup": "short-temp-cleanup-failed"}[phase]
        failure_error = str(error)
        if phase == "execution" and active_gate and not any(result["gate"] == active_gate for result in results):
            results.append({"gate": active_gate, "status": "execution-error", "exit_code": 1, "error": failure_error})
        print(f"{failure_status}: {error}")
    completed = {result["gate"] for result in results}
    not_run = [name for name, _, _ in steps if name not in completed]
    exit_code = next((result["exit_code"] for result in results if result["exit_code"]), 0)
    if failure_status and not exit_code:
        exit_code = 1
    write_execution_summary(output_dir, plan, results, not_run, exit_code,
                            status=failure_status, error=failure_error)
    return 1 if exit_code else 0


if __name__ == "__main__":
    raise SystemExit(main())
