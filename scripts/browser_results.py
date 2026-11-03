"""Require actual browser results to match discovery; combine complete shards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

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


def combine_shards(records: list[dict], total: int, revision: str) -> dict:
    if total < 1 or len(records) != total:
        raise ValueError(f"Expected {total} shard reports, received {len(records)}")
    reference = records[0]["scope"]
    full = reference["case_ids"]
    if (not full or len(full) != len(set(full)) or reference["revision"] != revision
            or reference.get("selection") != "editor-e2e" or reference.get("specs")
            or reference.get("worktree_clean") is not True):
        raise ValueError("Full browser scope is empty, duplicated, or from another revision")
    owned, indexes = set(), set()
    for record in records:
        shard = record["shard"]
        index = shard["current"]
        if (record["schema"] != SCHEMA or record["scope"] != reference or shard["total"] != total
                or not 1 <= index <= total or index in indexes):
            raise ValueError("Shard metadata is duplicated or has a different revision/config/selection/scope")
        indexes.add(index)
        planned, passed = record["planned_ids"], record["passed_ids"]
        if len(planned) != len(set(planned)) or not set(planned).issubset(full) or owned.intersection(planned):
            raise ValueError("Shard plan contains duplicate, overlapping, or out-of-scope cases")
        if not planned:
            if record["status"] != "empty-shard" or passed:
                raise ValueError("Zero-assignment shard must be explicit and contain no runtime results")
        elif record["status"] != "passed" or sorted(passed) != sorted(planned):
            raise ValueError("Shard actual results do not match its plan")
        owned.update(planned)
    if owned != set(full):
        raise ValueError(f"Incomplete browser coverage: {len(set(full) - owned)} cases missing")
    return {"status": "passed", "revision": revision, "shards": total, "cases": len(full), "scope": reference}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--total", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path(".artifacts/browser-coverage.json"))
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.reports.rglob("browser-run.json"))]
        result = combine_shards(records, args.total, revision)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"status": "failed", "error": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "scope"}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
