"""Require an actual browser run to match its discovered test collection."""
from __future__ import annotations


SCHEMA = "maw.browser-run.v1"


def browser_cases(report: dict) -> dict[str, dict]:
    found = {}

    def visit(suite):
        for spec in suite.get("specs", []):
            for test in spec["tests"]:
                identity = f"{spec['id']}@{test['projectId']}"
                if identity in found:
                    raise ValueError(f"Duplicate browser case: {identity}")
                found[identity] = test
        for child in suite.get("suites", []):
            visit(child)

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


def discovery(report: dict) -> list[str]:
    browser_config(report)
    if report.get("errors"):
        raise ValueError("Browser discovery contains errors")
    cases = browser_cases(report)
    if any(test["expectedStatus"] != "passed" for test in cases.values()):
        raise ValueError("Required browser discovery contains skipped or expected-failure cases")
    # --list reports every case as unexecuted/skipped. This is a planned set,
    # never runtime success; runtime requires an actual passing result below.
    return sorted(cases)


def verify_run(expected: list[str], report: dict) -> list[str]:
    browser_config(report)
    if not expected or report.get("errors"):
        raise ValueError("Required browser run is empty or contains global errors")
    cases = browser_cases(report)
    if set(cases) != set(expected):
        missing, extra = set(expected) - set(cases), set(cases) - set(expected)
        raise ValueError(f"Browser coverage mismatch: {len(missing)} missing, {len(extra)} extra")
    for identity, test in cases.items():
        results = test["results"]
        if (test["expectedStatus"] != "passed" or test["status"] != "expected"
                or len(results) != 1 or results[0]["status"] != "passed"
                or results[0].get("retry", 0) != 0):
            raise ValueError(f"Browser case did not pass exactly once: {identity}")
    stats = report["stats"]
    if stats["expected"] != len(expected) or any(stats[key] for key in ("unexpected", "skipped", "flaky")):
        raise ValueError("Required browser statistics contain failure, skip, flaky result, or count mismatch")
    return sorted(cases)
