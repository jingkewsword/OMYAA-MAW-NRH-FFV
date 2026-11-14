"""Require actual browser results to match discovery; combine complete shards."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

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
    passed_count = skipped_count = 0
    for record in records:
        shard = record["shard"]
        index = shard["current"]
        if (record["schema"] != SCHEMA or record["scope"] != reference or shard["total"] != total
                or not 1 <= index <= total or index in indexes):
            raise ValueError("Shard metadata is duplicated or has a different revision/config/selection/scope")
        indexes.add(index)
        planned, passed, skipped = record["planned_ids"], record["passed_ids"], record["allowed_skipped_ids"]
        if len(planned) != len(set(planned)) or not set(planned).issubset(full) or owned.intersection(planned):
            raise ValueError("Shard plan contains duplicate, overlapping, or out-of-scope cases")
        if not planned:
            if record["status"] != "empty-shard" or passed or skipped:
                raise ValueError("Zero-assignment shard must be explicit and contain no runtime results")
        elif (record["status"] != "passed" or len(passed + skipped) != len(set(passed + skipped))
              or sorted(passed + skipped) != sorted(planned)):
            raise ValueError("Shard actual results do not match its plan")
        passed_count += len(passed)
        skipped_count += len(skipped)
        owned.update(planned)
    if owned != set(full):
        raise ValueError(f"Incomplete browser coverage: {len(set(full) - owned)} cases missing")
    return {"status": "passed", "revision": revision, "shards": total, "cases": len(full), "passed": passed_count, "allowed_skipped": skipped_count, "scope": reference}


def diagnostic_shards(records: list[dict], total: int) -> dict:
    """Raw runtime statistics are diagnostic only and never prove coverage."""
    keys = ("passed", "failures", "skipped", "flaky")
    shards = []
    indices = []
    for record in records:
        if not isinstance(record, dict):
            record = {}
        shard = record.get("shard", {})
        if not isinstance(shard, dict):
            shard = {}
        index = shard.get("current")
        if type(index) is not int:
            index = None
        indices.append(index)
        counts = record.get("diagnostic_counts", {})
        if not isinstance(counts, dict):
            counts = {}
        shards.append({"shard": index, "status": record.get("status", "unknown"),
                       "counts": {key: counts.get(key, "unknown") if type(counts.get(key)) is int
                                  and counts[key] >= 0 else "unknown" for key in keys}})
    complete = len(records) == total and set(indices) == set(range(1, total + 1))
    totals = {key: sum(item["counts"][key] for item in shards)
              if complete and all(type(item["counts"][key]) is int for item in shards) else "unknown"
              for key in keys}
    return {"label": "raw runtime statistics, not coverage validation", "shards": shards, "totals": totals}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--total", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path(".artifacts/browser-coverage.json"))
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    records = []
    read_error = None
    for path in sorted(args.reports.rglob("browser-regressions-browser-run.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            records.append({})
            read_error = f"Unreadable shard report {path}: {error}"
    try:
        if read_error:
            raise ValueError(read_error)
        result = combine_shards(records, args.total, revision)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"status": "failed", "error": str(error)}
    result["diagnostic"] = diagnostic_shards(records, args.total)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "scope"}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
