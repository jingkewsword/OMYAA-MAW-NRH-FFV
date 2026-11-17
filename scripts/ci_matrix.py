"""Expand and verify the selected Ubuntu browser shards."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

if __package__:
    from . import browser_results, test_result_details
else:
    import browser_results
    import test_result_details


def fingerprint(plan: dict) -> str:
    raw = json.dumps(plan, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def shards(plan: dict, override: str = "") -> int:
    selected = plan["mode"] == "full" or bool(plan["e2e_specs"])
    if not selected:
        return 0
    if override:
        if override not in {"1", "2", "3", "4"}:
            raise ValueError("browser shard override must be between 1 and 4")
        return int(override)
    return 4 if plan["mode"] == "full" else min(4, max(1, math.ceil(len(plan["e2e_specs"]) / 16)))


def matrix(plan: dict, override: str = "") -> dict:
    total = shards(plan, override)
    return {"include": [{"shard": n, "total": total} for n in range(1, total + 1)]
            or [{"shard": 1, "total": 1}]}


def summarize_steps(steps: dict, groups: list[dict]) -> dict:
    """Classify selected checks without turning failed steps into success."""
    records = []
    for group in groups:
        name = group["id"]
        selected = group["selected"]
        dependencies = group.get("requires", [])
        if type(selected) is not bool or not isinstance(name, str) or not isinstance(dependencies, list):
            raise ValueError("invalid check specification")
        outcome = steps.get(name, {}).get("outcome", "missing")
        unmet = [dependency for dependency in dependencies
                 if steps.get(dependency, {}).get("outcome") != "success"]
        if not selected:
            status = "not_selected"
        elif outcome == "success":
            status = "passed"
        elif outcome == "failure":
            status = "failed"
        elif unmet:
            status = "blocked"
        else:
            status = "not_run"
        records.append({"id": name, "status": status, "outcome": outcome, "unmet": unmet})
    failures = [record for record in records if record["status"] in {"failed", "blocked", "not_run"}]
    return {"status": "failed" if failures else "passed", "groups": records, "steps": steps}


class GateError(ValueError):
    def __init__(self, errors: list[dict], failures: list[dict]):
        self.errors = errors
        self.failures = failures
        super().__init__("; ".join(f"{e['source']}: {e['error']}" for e in errors))


def gate(plan: dict, total: int, roots: list[Path]) -> None:
    errors = []
    failures = []
    if total < 1 or len(roots) != total:
        errors.append({"source": "matrix", "error": f"expected {total} shard receipts; found {len(roots)}"})
    expected = fingerprint(plan)
    package = Path(__file__).resolve().parents[1] / "package.json"
    expected_version = json.loads(package.read_text(encoding="utf-8"))["devDependencies"]["@playwright/test"]
    union, seen = set(), set()
    full_ids = config = None
    for root in roots:
        def read(name):
            return json.loads((root / name).read_text(encoding="utf-8"))
        source = str(root)
        try:
            summary = read("summary.json")
            browser_result = next((item for item in summary.get("results", [])
                                   if item.get("gate") == "browser-regressions"), {})
            inventory_path = root / "failures.json"
            if inventory_path.exists():
                inventory = read("failures.json")
                if not isinstance(inventory.get("failures"), list) or not isinstance(inventory.get("report_errors"), list):
                    raise ValueError("malformed browser failure inventory")
            else:
                # Older receipts predate failures.json; recover the same case
                # inventory from the actual browser JSON when present.
                inventory = test_result_details.collect_failures("browser-regressions", root, browser_result)
            process_code = browser_result.get("process_exit_code", browser_result.get("exit_code"))
            failures.extend({**entry, "source": source, "process_exit_code": process_code}
                            for entry in inventory["failures"])
            errors.extend({"source": source, "error": str(message)} for message in inventory["report_errors"])
            coordinate = summary["shard"]
            current = coordinate["current"]
            if (type(current) is not int or not 1 <= current <= total or current in seen
                    or coordinate != {"current": current, "total": total}
                    or summary["head"] != plan["head"] or summary["selection_fingerprint"] != expected
                    or summary["requested_layer"] != "browser"):
                raise ValueError("invalid or mismatched browser shard receipt")
            seen.add(current)
            if summary["exit_code"] != 0:
                errors.append({"source": source, "error": f"shard {current} failed: exit {summary['exit_code']}"})
                for result in summary.get("results", []):
                    if result.get("exit_code"):
                        errors.append({"source": source, "error": f"{result.get('gate', 'unknown gate')}: "
                                       f"status {result.get('status', 'unknown')}, exit {result['exit_code']}; "
                                       f"blocked by {result.get('blocked_by', [])}; {result.get('log', '')}"})
            full = read("browser-regressions-full.json")
            listed = read("browser-regressions-list.json")
            actual = read("browser-regressions.json")
            for case, outcome in browser_results.collection(actual).items():
                for attempt in outcome.get("results", []):
                    if attempt.get("status") in {"failed", "timedOut", "interrupted"}:
                        errors.append({"source": source, "error": f"browser case {case}: {attempt['status']}"})
            complete = browser_results.full_collection(full)
            identity = browser_results.config_identity(listed)
            if identity.get("version") != expected_version:
                raise ValueError("browser discovery uses an unexpected Playwright version")
            if browser_results.config_identity(full) != identity:
                raise ValueError("unsharded and shard configurations differ")
            if full_ids is None:
                full_ids, config = complete, identity
            elif full_ids != complete or config != identity:
                raise ValueError("browser shard discoveries disagree")
            ids = set(browser_results.collection(listed))
            if union & ids:
                raise ValueError("browser shards overlap")
            union.update(ids)
            result = browser_results.validate(listed, actual, current, total)
            validated = read("browser-regressions-validated.json")
            if result != validated:
                raise ValueError("browser validated outcome differs from reports")
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            errors.append({"source": source, "error": str(error)})
    if seen != set(range(1, total + 1)) or union != full_ids:
        missing = sorted(set(range(1, total + 1)) - seen)
        if missing:
            errors.append({"source": "matrix", "error": f"missing shard receipts: {missing}"})
        errors.append({"source": "matrix", "error": "browser shard union differs from complete discovery"})
    if plan["mode"] == "targeted" and full_ids is not None:
        selected_files = {path.removeprefix("tests/e2e/") for path in plan["e2e_specs"]}
        if {case[0] for case in full_ids} != selected_files:
            errors.append({"source": "matrix", "error": "browser discovery differs from selected spec files"})
    if failures and not errors:
        errors.append({"source": "matrix", "error": f"{len(failures)} browser failures in shard inventories"})
    if errors:
        raise GateError(errors, failures)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("expand", "gate", "steps"))
    parser.add_argument("--plan", type=Path, default=Path(".artifacts/ci-plan.json"))
    parser.add_argument("--root", type=Path, default=Path(".artifacts/browser-evidence"))
    parser.add_argument("--total", type=int)
    parser.add_argument("--report", type=Path, default=Path(".artifacts/browser-gate.json"))
    args = parser.parse_args()
    if args.action == "steps":
        report = summarize_steps(json.loads(os.environ["CI_STEPS"]), json.loads(os.environ["CI_GROUPS"]))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(report["groups"], indent=2))
        if report["status"] != "passed":
            raise SystemExit(1)
        return
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if args.action == "expand":
        override = os.environ.get("CI_BROWSER_SHARDS", "")
        result = matrix(plan, override)
        if output := os.environ.get("GITHUB_OUTPUT"):
            with Path(output).open("a", encoding="utf-8", newline="\n") as stream:
                stream.write("browser_matrix=" + json.dumps(result, separators=(",", ":")) + "\n")
                stream.write(f"browser_shards={shards(plan, override)}\n")
        print(json.dumps(result))
    else:
        if args.total is None:
            raise ValueError("browser shard total required")
        roots = sorted(path.parent for path in args.root.rglob("summary.json"))
        try:
            gate(plan, args.total, roots)
        except GateError as error:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({"status": "failed", "errors": error.errors, "failures": error.failures},
                                              ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8", newline="\n")
            for entry in error.errors[:20]:
                print(f"{entry['source']}: {entry['error']}")
            print(f"{len(error.errors)} errors; {len(error.failures)} individual failures; full report: {args.report}")
            raise SystemExit(1) from error
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"status": "passed", "errors": [], "failures": []}, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
        print(f"Verified {args.total} browser shard(s), exact discovery union and outcomes")


if __name__ == "__main__":
    main()
