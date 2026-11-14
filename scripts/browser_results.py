"""Require an actual browser run to match its discovered test collection."""
from __future__ import annotations


SCHEMA = "maw.browser-run.v2"
RETIRED_SKIP_REASON = "便携模式已弃维护，2.0 移除 HTML，见 #336 后回归分析"
RETIRED_PORTABLE_CASES = {
    ("editor-bundle.spec.mjs", "minified portable bundle preserves non-default data, paths and generated language"),
    ("editor-bundle.spec.mjs", "file executes every source and preserves project/export/undo behavior"),
    ("editor-text-tools.spec.mjs", "portable file uses the same fade rules and SRT export settings"),
    ("editor-text-tools.spec.mjs", "portable editor saves and reloads presets in its browser storage"),
    ("warma-presets.spec.mjs", "portable pages reject a stale preset library save"),
}


def browser_cases(report: dict) -> dict[str, dict]:
    found = {}

    def visit(suite, parents=()):
        for spec in suite.get("specs", []):
            for test in spec["tests"]:
                identity = f"{spec['id']}@{test['projectId']}"
                if identity in found:
                    raise ValueError(f"Duplicate browser case: {identity}")
                found[identity] = {**test, "_file": spec.get("file", "").replace("\\", "/"),
                                   "_title_path": (*parents, spec.get("title", ""))}
        for child in suite.get("suites", []):
            visit(child, (*parents, child.get("title", "")))

    for suite in report["suites"]:
        visit(suite)
    return found


def browser_config(report: dict) -> dict:
    config = report["config"]
    projects = config["projects"]
    if (config["workers"] != 2 or config["fullyParallel"] is not False
            or config["forbidOnly"] is not True or len(projects) != 1
            or projects[0]["name"] != "chromium" or projects[0]["retries"] != 0
            or projects[0]["repeatEach"] != 1):
        raise ValueError("Required browser config must use Chromium, 2 workers, file isolation, no retries, and forbidOnly")
    return {"version": config["version"], "project": projects[0]["name"],
            "workers": 2, "fullyParallel": False, "forbidOnly": True, "retries": 0}


def discovery(report: dict, required_specs=()) -> list[str]:
    browser_config(report)
    if report.get("errors"):
        raise ValueError("Browser discovery contains errors")
    cases = browser_cases(report)
    if any(test["expectedStatus"] != "passed" for test in cases.values()):
        raise ValueError("Required browser discovery contains skipped or expected-failure cases")
    if required_specs:
        files = set()
        def visit(suite):
            for spec in suite.get("specs", []):
                if spec.get("tests"):
                    files.add(spec["file"].replace("\\", "/"))
            for child in suite.get("suites", []):
                visit(child)
        for suite in report["suites"]:
            visit(suite)
        missing = sorted(path.removeprefix("tests/e2e/") for path in required_specs
                         if path.removeprefix("tests/e2e/") not in files)
        if missing:
            raise ValueError(f"Required spec has no discovered cases: {', '.join(missing)}")
    # --list reports every case as unexecuted/skipped. This is a planned set,
    # never runtime success; runtime requires an actual passing result below.
    return sorted(cases)


def verify_run(expected: list[str], report: dict) -> dict[str, list[str]]:
    browser_config(report)
    if not expected or report.get("errors"):
        raise ValueError("Required browser run is empty or contains global errors")
    cases = browser_cases(report)
    if set(cases) != set(expected):
        missing, extra = set(expected) - set(cases), set(cases) - set(expected)
        raise ValueError(f"Browser coverage mismatch: {len(missing)} missing, {len(extra)} extra")
    passed, skipped = [], []
    for identity, test in cases.items():
        results = test["results"]
        single = len(results) == 1 and results[0].get("retry", 0) == 0
        if single and test["expectedStatus"] == "passed" and test["status"] == "expected" and results[0]["status"] == "passed":
            passed.append(identity)
            continue
        annotations = [a.get("description") for a in test.get("annotations", []) if a.get("type") == "skip"]
        approved = (len(test["_title_path"]) == 1 and (test["_file"], test["_title_path"][0]) in RETIRED_PORTABLE_CASES
                    and test["projectId"] == "chromium" and annotations == [RETIRED_SKIP_REASON])
        if (approved and single and test["expectedStatus"] == "skipped" and test["status"] == "skipped"
                and results[0]["status"] == "skipped" and not results[0].get("errors")):
            skipped.append(identity)
            continue
        raise ValueError(f"Browser case did not pass or match an approved skip: {identity}")
    stats = report["stats"]
    if (stats["expected"] != len(passed) or stats["skipped"] != len(skipped)
            or any(stats[key] for key in ("unexpected", "flaky"))):
        raise ValueError("Required browser statistics contain failure, skip, flaky result, or count mismatch")
    return {"passed_ids": sorted(passed), "allowed_skipped_ids": sorted(skipped)}
