"""Select the shared test plan from a verified GitHub event diff."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

if __package__:
    from scripts.local_test_impact import select_packs
else:
    from local_test_impact import select_packs

EXISTING_UBUNTU_PYTHON = (
    "tests/test_docs_check.py", "tests/test_release_notes.py", "tests/test_release_site.py",
    "tests/test_release_publication.py", "tests/test_run_check.py", "tests/test_compact_assertions.py",
    "tests/test_editor_assets.py", "tests/test_editor_manifest.py", "tests/test_ocr_scan.py",
    "tests/test_ocr_scan_regressions.py", "tests/test_ocr_runtime.py", "tests/test_runtime_process_cleanup.py",
    "tests/test_process_tree_posix.py", "tests/test_term_extract_aggregate.py",
    "tests/test_term_extract_ai_filter.py", "tests/test_term_extract_cli_cache.py",
    "tests/test_term_extract_export.py", "tests/test_term_extract_report.py", "tests/test_term_extract_score.py",
    "tests/test_verification_checklist.py", "tests/test_verification_checklist_build.py",
    "tests/test_media.py", "tests/test_ffmpeg.py", "tests/test_ffprobe_failure_integration.py",
)
EXISTING_WINDOWS_NODE = (
    "tests/test_e2e_output_tail.mjs", "tests/test_e2e_server_lifecycle.mjs",
    "tests/test_e2e_process_lifecycle.mjs", "tests/test_e2e_server_process.mjs",
)
EXISTING_WINDOWS_PYTHON = EXISTING_UBUNTU_PYTHON[:6]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def event_paths(env: dict[str, str]) -> tuple[list[str], bool, str, str | None]:
    """Trust a PR merge's base parent or an ancestor push's before commit."""
    event = env.get("GITHUB_EVENT_NAME", "")
    base = env.get("PR_BASE_SHA", "") if event == "pull_request" else env.get("PUSH_BEFORE_SHA", "")
    if event not in {"pull_request", "push"} or not re.fullmatch(r"[0-9a-f]{40}", base) or base == "0" * 40:
        return [], True, "no trusted event base", None
    try:
        head = git("rev-parse", "HEAD").decode().strip()
        if env.get("GITHUB_SHA") != head:
            raise ValueError("checkout differs from event SHA")
        if event == "pull_request":
            if git("rev-parse", "HEAD^1").decode().strip() != base:
                raise ValueError("PR base differs from merge parent")
        else:
            subprocess.run(["git", "merge-base", "--is-ancestor", base, head],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        paths = [p.decode("utf-8") for p in git("diff", "--name-only", "--no-renames", "-z", base, head).split(b"\0") if p]
        if not paths:
            raise ValueError("empty change list")
        return paths, False, f"trusted {event} diff", base
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as error:
        return [], True, f"untrusted diff: {error}", None


def create_plan(env: dict[str, str]) -> dict:
    paths, fallback, reason, base = event_paths(env)
    plan = select_packs(paths, release=fallback, base_ref=base)
    plan.update(changed_paths=paths, diff_reason=reason, head=git("rev-parse", "HEAD").decode().strip())
    # Record CI's platform ownership alongside the common selection. A layer
    # receipt records actual execution; this section only describes the plan.
    flags = outputs(plan)
    event = env.get("GITHUB_EVENT_NAME")
    ubuntu_runs = event != "workflow_dispatch"
    windows_runs = event != "push"
    full = plan["mode"] == "full"
    plan["ci_platforms"] = {
        "ubuntu": [layer for layer in ("node", "browser") if ubuntu_runs and flags[layer] == "true"]
                  + (["python"] if event == "push" and flags["python"] == "true" else []),
        "windows": (["python"] if windows_runs and flags["python"] == "true" else [])
                   + (["preview-display-launcher-package"] if windows_runs and flags["preview_windows"] == "true" else []),
        "documentation": ["ubuntu", "windows"] if ubuntu_runs and flags["docs"] == "true" else [],
        "website": ["ubuntu"] if ubuntu_runs and flags["website"] == "true" else [],
        # These are intersections with the checks that already ran on the
        # corresponding platforms, not new cross-platform full suites.
        "existing_ubuntu_python": [p for p in EXISTING_UBUNTU_PYTHON
                                   if event == "pull_request" and (full or p in plan["python_tests"])],
        "existing_windows_node": [p for p in EXISTING_WINDOWS_NODE
                                  if ubuntu_runs and (full or p in plan["node_tests"])],
        "existing_windows_python": [p for p in EXISTING_WINDOWS_PYTHON
                                    if event == "push" and (full or p in plan["python_tests"])],
    }
    return plan


def outputs(plan: dict) -> dict[str, str]:
    full = plan["mode"] == "full"
    prep = plan["preparation"]
    values = {
        "full": full,
        "docs": "docs" in plan["packs"],
        "website": "website" in plan["packs"],
        "python": full or bool(plan["python_tests"]),
        "node": full or bool(plan["node_tests"]),
        "readme_node": full or "tests/test_readme_content_sync.mjs" in plan["node_tests"],
        "browser": full or bool(plan["e2e_specs"]),
        "application": prep["application"],
        "python_dependencies": prep.get("python_dependencies", True),
        "real_media": prep["real_media"],
        "preview_windows": prep["preview_windows"],
        "lint": prep["lint"],
        "ubuntu_python": bool(plan.get("ci_platforms", {}).get("existing_ubuntu_python")),
        "windows_node": bool(plan.get("ci_platforms", {}).get("existing_windows_node")),
        "windows_python": bool(plan.get("ci_platforms", {}).get("existing_windows_python")),
    }
    return {"plan": json.dumps(plan, ensure_ascii=True, separators=(",", ":")),
            **{key: str(value).lower() for key, value in values.items()}}


def main() -> None:
    plan = create_plan(dict(os.environ))
    print(json.dumps(plan, ensure_ascii=True, indent=2))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8", newline="\n") as stream:
            for name, value in outputs(plan).items():
                stream.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
