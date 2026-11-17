#!/usr/bin/env python3
"""Impact-selected development and CI checks, with explicit release gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

if __package__:
    from .run_check import run
    from .browser_results import validate as validate_browser
    from .test_policy import PYTHON_PACKS, WINDOWS_FFMPEG_TESTS
    from .local_test_impact import CHECKLIST_NODE, CHECKLIST_PYTHON, CHECKLIST_SPECS, DEV_NODE, DEV_PYTHON, node_pack, select_packs
else:
    from run_check import run
    from browser_results import validate as validate_browser
    from test_policy import PYTHON_PACKS, WINDOWS_FFMPEG_TESTS
    from local_test_impact import CHECKLIST_NODE, CHECKLIST_PYTHON, CHECKLIST_SPECS, DEV_NODE, DEV_PYTHON, node_pack, select_packs

ROOT = Path(__file__).resolve().parents[1]
PACKS = ("docs", "common", "browser", "smoke", "media", "long-media", "lifecycle", "tools", "e2e", "editor-e2e", "website", "manual")


def changed_paths(base_ref: str | None, *, deleted_only: bool = False) -> list[str]:
    args = ["git", "diff", "--name-only", "--no-renames", "-z"]
    if deleted_only:
        args.append("--diff-filter=D")
    comparisons = [[*args, f"{base_ref}...HEAD"]] if base_ref else [args, [*args, "--cached"]]
    paths = []
    for comparison in comparisons:
        result = subprocess.run(comparison, cwd=ROOT, capture_output=True, check=True)
        paths.extend(p for p in result.stdout.decode("utf-8").split("\0") if p)
    if not base_ref and not deleted_only:
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


def _pack_commands(packs: list[str], report_dir: Path, *, dev: bool = False, component: str = "all", specs=(), tools_scope="all"):
    python = sys.executable
    node = shutil.which("node") or "node"
    playwright = [node, "node_modules/@playwright/test/cli.js", "test", "--config=tests/config/playwright.config.mjs", "--project=chromium",
                  "--forbid-only", "--workers=2", "--retries=0", "--shard=1/1"]
    if dev:
        if component in {"python", "all"}:
            yield "python-kernel", [python, "scripts/run_tests.py", "--required", "--report", str(report_dir / "python-kernel.json"), *DEV_PYTHON], 60
        if component in {"editor", "all"}:
            yield "editor-kernel", [node, "--test", "--test-reporter=spec", "--test-reporter-destination=stdout",
                  "--test-reporter=junit", f"--test-reporter-destination={report_dir / 'editor-kernel.xml'}",
                  *(f"tests/{name}" for name in DEV_NODE)], 60
        if component in {"launcher", "all"}:
            yield "launcher-kernel", [python, "scripts/run_tests.py", "--required", "--report", str(report_dir / "launcher-kernel.json"),
                  "tests.test_launcher_contract"], 60
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
                                           "tests.test_release_site", "tests.test_release_publication", "--report",
                                           str(report_dir / "docs-regressions.json")], 120
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
                   ], 900
        if pack == "e2e":
            yield "browser-regressions", [*playwright, "--reporter=line,json", f"--output={report_dir / 'browser-artifacts'}",
                   *specs], 900
        if pack == "website":
            yield "website-docs", [node, "website/scripts/sync-maw-docs.mjs"], 60
            yield "website-releases", [python, "scripts/build_release_site.py", "--preview"], 180
            yield "website-build", [shutil.which("pnpm") or "pnpm", "--dir", "website", "build"], 240


def command_layer(name: str) -> str:
    if name in {"python-lint", "build", "build-launcher", "typecheck"}:
        return "prepare"
    if name in {"docs-navigation", "release-docs"}:
        return "docs"
    if name.startswith("website-"):
        return "website"
    if name.startswith("node-") or name == "editor-kernel":
        return "node"
    if name in {"editor-http-smoke", "browser-regressions"}:
        return "browser"
    return "python"


def website_before_browser(steps):
    website = [step for step in steps if command_layer(step[0]) == "website"]
    remaining = [step for step in steps if command_layer(step[0]) != "website"]
    index = next((i for i, step in enumerate(remaining) if command_layer(step[0]) == "browser"), len(remaining))
    return remaining[:index] + website + remaining[index:]


def commands(packs: list[str], report_dir: Path, *, dev: bool = False, component: str = "all",
             specs=(), tools_scope="all", selection=None, layer="all", shard=(1, 1)):
    """Execute the same concrete selection locally and in each CI layer."""
    existing = {"python-ubuntu-existing": ("existing_ubuntu_python", "python_tests", "python"),
                "python-windows-existing": ("existing_windows_python", "python_tests", "python"),
                "node-windows-existing": ("existing_windows_node", "node_tests", "node")}
    if layer in existing:
        key, targets, layer = existing[layer]
        selection = {**selection, "mode": "targeted", "packs": [], "python_tests": [], "node_tests": [], "e2e_specs": [],
                     targets: selection["ci_platforms"][key]}
        packs, specs = [], []
    if not selection or selection.get("mode") != "targeted":
        steps = list(_pack_commands(packs, report_dir, dev=dev, component=component, specs=specs, tools_scope=tools_scope))
        if "website" in packs and "editor-e2e" in packs and layer == "all":
            steps = website_before_browser(steps)
        for step in steps:
            if step[0] == "editor-http-smoke" and "editor-e2e" in packs:
                continue  # Same Chromium cases/configuration are in the full collection.
            if layer in {"all", command_layer(step[0])}:
                if command_layer(step[0]) == "browser":
                    step = (step[0], [f"--shard={shard[0]}/{shard[1]}" if arg.startswith("--shard=") else arg
                                     for arg in step[1]], step[2])
                yield step
        return

    python = sys.executable
    node = shutil.which("node") or "node"
    prep = selection["preparation"]
    steps = []
    if prep.get("lint"):
        paths = [path for path in selection.get("changed_paths", []) if path.endswith(".py") and (ROOT / path).is_file()]
        steps.append(("python-lint", [python, "-m", "ruff", "check", *paths], 60))
    if prep.get("application"):
        steps.extend((
            ("build", [node, "scripts/build-editor.mjs", "--write"], 60),
            ("build-launcher", [node, "scripts/build-launcher.mjs", "--write"], 60),
            ("typecheck", [node, "node_modules/typescript/bin/tsc", "-p", "web/tsconfig.typecheck.json"], 120),
        ))
    if "docs" in packs:
        steps.extend((
            ("docs-navigation", [python, "scripts/check_docs.py"], 60),
            ("release-docs", [python, "scripts/prepare_release_notes.py", "--check-all"], 60),
        ))
    targets = selection["python_tests"]
    for target in targets:
        name = "python-selected" if len(targets) == 1 else f"python-{Path(target).stem}"
        steps.append((name, [python, "scripts/run_tests.py", "--automated", "--required", "--report",
                      str(report_dir / f"{name}.json"), target], 300))
    targets = selection["node_tests"]
    for target in targets:
        name = "node-selected" if len(targets) == 1 else f"node-{Path(target).stem}"
        steps.append((name, [node, "--test", "--test-reporter=spec", "--test-reporter-destination=stdout",
                      "--test-reporter=junit", f"--test-reporter-destination={report_dir / (name + '.xml')}", target], 240))
    if specs:
        steps.append(("browser-regressions", [node, "node_modules/@playwright/test/cli.js", "test",
                      "--config=tests/config/playwright.config.mjs", "--project=chromium", "--forbid-only",
                      "--workers=2", "--retries=0", f"--shard={shard[0]}/{shard[1]}", "--reporter=line,json",
                      f"--output={report_dir / 'browser-artifacts'}", *specs], 900))
    if "website" in packs:
        steps.extend((
            ("website-docs", [node, "website/scripts/sync-maw-docs.mjs"], 60),
            ("website-releases", [python, "scripts/build_release_site.py", "--preview"], 180),
            ("website-build", [shutil.which("pnpm") or "pnpm", "--dir", "website", "build"], 240),
        ))
    # A browser contract may serve website/dist. Prepare that input before the
    # browser consumes it, including on a clean local checkout.
    if "tests/e2e/editor-entry-retirement.spec.mjs" in specs and layer == "all":
        steps = website_before_browser(steps)
    for step in steps:
        if layer in {"all", command_layer(step[0])}:
            yield step


def read_selection(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("mode") not in {"targeted", "full"}:
        raise ValueError("selection plan requires targeted/full mode")
    if plan.get("head"):
        current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        if plan["head"] != current:
            raise ValueError("selection plan belongs to a different commit")
    for key in ("packs", "python_tests", "node_tests", "e2e_specs", "reasons"):
        if not isinstance(plan.get(key), list) or any(not isinstance(item, str) for item in plan[key]):
            raise ValueError(f"invalid selection list: {key}")
        if len(plan[key]) != len(set(plan[key])):
            raise ValueError(f"duplicate selection entries: {key}")
    if not isinstance(plan.get("preparation"), dict):
        raise ValueError("selection plan requires preparation flags")
    for key, suffix in (("python_tests", ".py"), ("node_tests", ".mjs"), ("e2e_specs", ".spec.mjs")):
        for target in plan[key]:
            parts = target.split("/")
            if not target.startswith("tests/") or not target.endswith(suffix) or "\\" in target or any(
                    part in {"", ".", ".."} for part in parts) or not (ROOT / target).is_file():
                raise ValueError(f"invalid concrete test path: {target}")
    for key, suffix in (("existing_ubuntu_python", ".py"), ("existing_windows_python", ".py"), ("existing_windows_node", ".mjs")):
        targets = plan.get("ci_platforms", {}).get(key, [])
        if not isinstance(targets, list) or any(not isinstance(item, str) for item in targets) or len(targets) != len(set(targets)):
            raise ValueError(f"invalid existing platform selection: {key}")
        if any(not item.startswith("tests/") or not item.endswith(suffix) or "\\" in item
               or any(part in {"", ".", ".."} for part in item.split("/")) or not (ROOT / item).is_file() for item in targets):
            raise ValueError(f"invalid existing platform test path: {key}")
        if plan["mode"] == "targeted" and set(targets) - set(plan["python_tests"] if suffix == ".py" else plan["node_tests"]):
            raise ValueError(f"platform selection is outside the shared plan: {key}")
    if set(plan["packs"]) - set(PACKS) or len(plan["packs"]) != len(set(plan["packs"])):
        raise ValueError("selection plan contains unknown or duplicate packs")
    return plan


def execute(name: str, command: list[str], timeout: int) -> dict:
    print(f"Running {name} (deadline {timeout}s)", flush=True)
    _, result = run(command, timeout, ROOT / ".artifacts/checks")
    print(f"{name}: exit={result['exit_code']}; seconds={result['duration_seconds']}; log={result['log']}", flush=True)
    return {"gate": name, **result}


def prepare_browser(name, command, directory, specs, selection, results):
    full_path = directory / f"{name}-full.json"
    os.environ["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(full_path.resolve())
    full_command = [arg for arg in command if not arg.startswith("--shard=")]
    result = execute(f"{name}-full-discover", [*full_command, "--list"], 60)
    results.append(result)
    if result["exit_code"]:
        raise ValueError(f"Browser full discovery failed; log={result['log']}")
    # The full collection is saved separately so CI can verify the shard union.
    full = json.loads(full_path.read_text(encoding="utf-8"))
    if full.get("errors") or full.get("config", {}).get("shard") is not None:
        raise ValueError("invalid full browser discovery")
    report_path = directory / f"{name}-list.json"
    os.environ["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(report_path.resolve())
    result = execute(f"{name}-discover", [*command, "--list"], 60)
    results.append(result)
    if result["exit_code"]:
        raise ValueError(f"Browser discovery failed; log={result['log']}")
    listed = json.loads(report_path.read_text(encoding="utf-8"))
    return listed


def write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def step_dependencies(steps, plan, external=()):
    """Only named preparation outcomes block their actual consumers."""
    names = {name for name, _, _ in steps}
    if __package__:
        from .test_prerequisites import prerequisites
    else:
        from test_prerequisites import prerequisites
    dependencies = {}
    for name, command, _ in steps:
        required = list(prerequisites(command, ROOT))
        targets = [Path(arg).stem for arg in command if arg.startswith("tests/")]
        if name == "website-build":
            required.extend(("website-docs", "website-releases"))
        if "test_launcher_bundle" in targets:
            required.append("build-launcher")
        if command_layer(name) == "browser":
            if plan.get("preparation", {}).get("application"):
                required.append("build")
            specs = plan.get("e2e_specs", [])
            if not specs or any("/launcher-" in path for path in specs):
                required.append("build-launcher")
            if not specs or "tests/e2e/editor-entry-retirement.spec.mjs" in specs:
                required.append("website-build")
        dependencies[name] = sorted({dependency for dependency in required if dependency in names or dependency in external})
    return dependencies


def run_steps(steps, output_dir, plan, *, metadata, requirements=None, blocked_preparation=()):
    """Complete independent groups and persist every outcome as it arrives."""
    if __package__:
        from .test_result_details import collect_failures
    else:
        from test_result_details import collect_failures
    names = [name for name, _, _ in steps]
    if len(names) != len(set(names)):
        raise ValueError("duplicate execution group names")
    unavailable = set(blocked_preparation)
    requirements = requirements if requirements is not None else step_dependencies(steps, plan, unavailable)
    states = {name: {"gate": name, "status": "not-run", "origin": None, "process_exit_code": None} for name in names}
    results, failures, report_errors = [], [], []
    fallback_added = False

    def save():
        failed = [name for name, state in states.items() if state["status"] == "failed"]
        blocked = [name for name, state in states.items() if state["status"] == "blocked"]
        unfinished = [name for name, state in states.items() if state["status"] in {"not-run", "running"}]
        code = int(bool(failed or blocked or unfinished or report_errors))
        summary = {**metadata, "plan": plan, "selected_gates": names, "groups": list(states.values()), "results": results,
                   "executed": [name for name, state in states.items() if state["origin"] == "executed"],
                   "reused": [], "failed": failed, "blocked": blocked, "not_run": unfinished,
                   "status": "not-selected" if not names else "failed" if failed else "incomplete" if code else "passed",
                   "failures_file": str((output_dir / "failures.json").resolve()), "exit_code": code}
        write_json(output_dir / "failures.json", {"failures": failures, "report_errors": report_errors})
        write_json(output_dir / "summary.json", summary)
        return summary

    save()
    for name, command, timeout in steps:
        blocked_by = [dependency for dependency in requirements.get(name, [])
                      if dependency in unavailable or dependency not in states or states[dependency]["status"] != "passed"]
        if command_layer(name) == "browser":
            # All shards share Node and Chromium. App/media/site requirements
            # depend on the actual shard collection and are checked after list.
            blocked_by = [dependency for dependency in blocked_by if dependency not in
                          {"website", "website-build", "build", "build-launcher", "ffmpeg", "python-dependencies"}]
        if blocked_by:
            state = {"gate": name, "status": "blocked", "origin": None, "process_exit_code": None,
                     "exit_code": 1, "blocked_by": blocked_by, "command": command}
            states[name] = state
            results.append(state)
            if plan.get("mode") == "full" and any(str(arg).endswith("scripts/run_tests.py") for arg in command) and not fallback_added:
                # A full discovery group may require unavailable application
                # setup. Still attempt every independent concrete file, without
                # pretending these partial results satisfy full discovery/hooks.
                fallback_added = True
                fallback = []
                for path in sorted((ROOT / "tests").glob("test_*.py")):
                    group = f"python-fallback-{path.stem}"
                    target = path.relative_to(ROOT).as_posix()
                    fallback.append((group, [sys.executable, "scripts/run_tests.py", "--automated", "--required", "--report",
                                             str(output_dir / f"{group}.json"), target], 300))
                requirements.update(step_dependencies(fallback, plan, unavailable | {key for key, value in states.items()
                                                                                   if value["status"] == "failed"}))
                for group, _, _ in fallback:
                    names.append(group)
                    states[group] = {"gate": group, "status": "not-run", "origin": None, "process_exit_code": None,
                                     "fallback_for": name}
                steps.extend(fallback)
            if command_layer(name) == "node":
                # The old full Node packs already contain concrete files; keep
                # their independent standard-library tests runnable as well.
                targets = [arg for arg in command if str(arg).replace("\\", "/").startswith("tests/") and arg.endswith(".mjs")]
                if len(targets) > 1:
                    fallback = []
                    for target in targets:
                        group = f"node-fallback-{Path(target).stem}"
                        if group in states:
                            continue
                        concrete = [arg for arg in command if arg not in targets]
                        concrete = [f"--test-reporter-destination={output_dir / (group + '.xml')}"
                                    if arg.startswith("--test-reporter-destination=") and arg.endswith(".xml") else arg
                                    for arg in concrete]
                        fallback.append((group, [*concrete, target], timeout))
                    requirements.update(step_dependencies(fallback, plan, unavailable | {key for key, value in states.items()
                                                                                       if value["status"] == "failed"}))
                    for group, _, _ in fallback:
                        names.append(group)
                        states[group] = {"gate": group, "status": "not-run", "origin": None, "process_exit_code": None,
                                         "fallback_for": name}
                    steps.extend(fallback)
            save()
            continue
        states[name].update(status="running", origin="executed")
        save()
        browser_record = None
        try:
            if command_layer(name) == "browser":
                browser_record = prepare_browser(name, command, output_dir, plan.get("e2e_specs", []), "selected", results)
                if __package__:
                    from .browser_results import collection
                    from .test_prerequisites import prerequisites
                else:
                    from browser_results import collection
                    from test_prerequisites import prerequisites
                files = {identity[0] for identity in collection(browser_record)}
                concrete = [arg for arg in command if not arg.startswith("tests/e2e/")] + [f"tests/e2e/{file}" for file in sorted(files)]
                needed = prerequisites(concrete, ROOT)
                failed_steps = {key for key, value in states.items() if value["status"] in {"failed", "blocked"}}
                actual_blocked = (unavailable | failed_steps) & needed
                if any(file.startswith("launcher-") for file in files) and "build-launcher" in failed_steps:
                    actual_blocked.add("build-launcher")
                if "editor-entry-retirement.spec.mjs" in files:
                    actual_blocked.update((unavailable | failed_steps) & {"website", "website-build"})
                if actual_blocked:
                    state = {"gate": name, "status": "blocked", "origin": None, "process_exit_code": None,
                             "exit_code": 1, "blocked_by": sorted(actual_blocked), "command": command}
                    states[name] = state
                    results.append(state)
                    save()
                    continue
            os.environ["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str((output_dir / f"{name}.json").resolve())
            result = execute(name, command, timeout)
            result.update(process_exit_code=result["exit_code"], process_status=result["status"], origin="executed")
            details = collect_failures(name, output_dir, result)
            if not details["complete"] and not details["report_errors"]:
                details["report_errors"].append("failure evidence is incomplete")
            failures.extend({"gate": name, **detail} for detail in details["failures"])
            report_errors.extend({"gate": name, "error": error} for error in details["report_errors"])
            if details["failures"] or details["report_errors"]:
                result["exit_code"] = result["exit_code"] or 1
            if details["report_errors"]:
                result["report_errors"] = details["report_errors"]
            if browser_record:
                try:
                    actual = json.loads((output_dir / f"{name}.json").read_text(encoding="utf-8"))
                    validated = validate_browser(browser_record, actual, metadata["shard"]["current"], metadata["shard"]["total"])
                    write_json(output_dir / f"{name}-validated.json", validated)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    result["exit_code"] = result["exit_code"] or 1
                    report_errors.append({"gate": name, "error": str(error)})
            result["status"] = "passed" if not result["exit_code"] else "failed"
        except (OSError, ValueError, KeyError, TypeError) as error:
            result = {"gate": name, "status": "failed", "origin": "executed", "exit_code": 1,
                      "process_exit_code": None, "command": command, "error": str(error)}
            report_errors.append({"gate": name, "error": str(error)})
        if "fallback_for" in states[name]:
            result["fallback_for"] = states[name]["fallback_for"]
        states[name] = result
        results.append(result)
        save()
        if result["exit_code"]:
            print(f"{name}: failed; complete evidence: {output_dir / 'failures.json'}", flush=True)
        if result.get("process_status") == "interrupted":
            break  # An explicit user interruption stops scheduling new groups.
    return save()


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("dev", "merge", "release"), default="dev")
    parser.add_argument("--component", choices=("all", "python", "editor", "launcher"),
                        help="explicit fixed development kernel; default dev uses impact selection")
    parser.add_argument("--pack", action="append", choices=PACKS)
    parser.add_argument("--changed", action="append", help="explicit changed path (repeatable); no shell patterns")
    parser.add_argument("--base-ref", help="Git base for committed branch changes; diff failure stops selection")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--e2e-specs", help="JSON concrete spec paths for an explicit e2e pack")
    parser.add_argument("--tools-scope", choices=("all", "checklist"), help="explicit tool consumer scope for reproduction")
    parser.add_argument("--selection-plan", type=Path, help="execute a saved concrete selection for this commit")
    parser.add_argument("--layer", choices=("all", "docs", "website", "python", "node", "browser", "prepare",
                                           "python-ubuntu-existing", "python-windows-existing", "node-windows-existing"), default="all")
    parser.add_argument("--report-dir", type=Path, help="fresh evidence directory (default: unique local run)")
    parser.add_argument("--shard", default="1/1", help="browser shard CURRENT/TOTAL; all other layers stay unchanged")
    parser.add_argument("--blocked-preparation", action="append", default=[],
                        choices=("build", "python-dependencies", "ffmpeg", "chromium", "node-dependencies", "website"),
                        help="CI preparation that failed; only its actual consumers are blocked")
    args = parser.parse_args(argv)
    try:
        current, total = (int(value) for value in args.shard.split("/"))
        if not 1 <= current <= total:
            raise ValueError
    except ValueError:
        parser.error("shard must be CURRENT/TOTAL with 1 <= CURRENT <= TOTAL")
    if args.stage == "release" and args.pack:
        parser.error("release runs the full required set; use --stage merge for a partial pack")
    if args.selection_plan and (args.changed or args.base_ref or args.pack or args.e2e_specs or args.tools_scope):
        parser.error("selection-plan cannot be combined with selection overrides")
    if args.stage == "release" and (args.selection_plan or args.component or args.layer != "all"):
        parser.error("release requires the complete collection, without layer or saved-selection overrides")
    if args.stage == "release" and total != 1:
        parser.error("release requires all browser cases in this run; use merge/CI for verified shards")
    if args.component and (args.stage != "dev" or args.pack or args.selection_plan):
        parser.error("component selects an explicit development kernel only")
    os.chdir(ROOT)
    try:
        plan = read_selection(args.selection_plan) if args.selection_plan else None
        paths = plan.get("changed_paths", []) if plan else args.changed if args.changed is not None else changed_paths(args.base_ref)
        deleted = [] if args.selection_plan or args.changed is not None else changed_paths(args.base_ref, deleted_only=True)
        plan = plan or select_packs(paths, release=args.stage == "release", base_ref=args.base_ref)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    selection_fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True,
                                                     separators=(",", ":")).encode("utf-8")).hexdigest()
    packs = args.pack or plan["packs"]
    specs = json.loads(args.e2e_specs) if args.e2e_specs else plan["e2e_specs"]
    if not isinstance(specs, list) or any(not isinstance(path, str) or not path.startswith("tests/e2e/") or not path.endswith(".spec.mjs")
            or ".." in Path(path).parts or not (ROOT / path).is_file() for path in specs):
        parser.error("e2e-specs must contain existing repository spec paths")
    if "e2e" in packs and not specs:
        parser.error("e2e requires concrete specs; use editor-e2e for the full collection")
    if args.component:
        packs = []
    if "e2e" in packs and "editor-e2e" in packs:
        parser.error("e2e and editor-e2e are mutually exclusive")
    if len(packs) != len(set(packs)):
        parser.error("duplicate packs would repeat the same gate")
    tools_scope = args.tools_scope or ("all" if args.pack else plan.get("tools_scope", "all"))
    if args.stage == "release" or set(packs) - {"docs", "tools", "e2e", "website"} or (
            "e2e" in packs and not (specs and set(specs).issubset(CHECKLIST_SPECS))):
        tools_scope = "all"
    prep = plan.get("preparation") if plan.get("preparation") and not args.pack else preparation(packs, specs, tools_scope)
    plan.update(stage=args.stage, changed_paths=paths, deleted_paths=deleted, packs=packs, e2e_specs=specs,
                tools_scope=tools_scope, requested_layer=args.layer, preparation=prep)
    if args.pack or args.component:
        plan["mode"] = "explicit-pack" if args.pack else "development-kernel"
    output_dir = (args.report_dir or ROOT / ".artifacts/test-workflow" / uuid.uuid4().hex[:12]).resolve()
    if output_dir.exists():
        parser.error("report-dir must be fresh; existing evidence cannot be reused")
    output_dir.mkdir(parents=True)
    (output_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"Evidence: {output_dir.relative_to(ROOT)}")
    if args.plan_only:
        return 0
    # Validate dependencies with their selected commands. A missing media
    # capability must not prevent an unrelated standard-library check.
    # Explicit interpreter settings avoid implicit environment synchronization.
    os.environ.setdefault("MAW_TEST_PYTHON", sys.executable)
    os.environ.setdefault("MAW_E2E_PYTHON", sys.executable)
    # Preserve the caller's effective temporary filesystem. In particular, moving
    # Windows fixtures from the system drive to a workspace drive can remove 8.3
    # aliases. Sandboxed callers can explicitly choose a writable TEMP/TMP.
    try:
        steps = list(commands(packs, output_dir, dev=bool(args.component), component=args.component or "all", specs=specs,
                              tools_scope=tools_scope, selection=plan, layer=args.layer, shard=(current, total)))
    except ValueError as error:
        report = {"status": "invalid-plan", "error": str(error), "exit_code": 1, "plan": plan}
        (output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(str(error))
        return 1
    metadata = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "selection_fingerprint": selection_fingerprint, "shard": {"current": current, "total": total},
                "requested_layer": args.layer, "blocked_preparation": sorted(set(args.blocked_preparation))}
    summary = run_steps(steps, output_dir, plan, metadata=metadata, blocked_preparation=args.blocked_preparation)
    return 1 if summary["exit_code"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
