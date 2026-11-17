"""Expand and verify the selected Ubuntu browser shards."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

if __package__:
    from . import browser_results
else:
    import browser_results


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


def gate(plan: dict, total: int, roots: list[Path]) -> None:
    if total < 1 or len(roots) != total:
        raise ValueError("missing or unexpected browser shard evidence")
    expected = fingerprint(plan)
    package = Path(__file__).resolve().parents[1] / "package.json"
    expected_version = json.loads(package.read_text(encoding="utf-8"))["devDependencies"]["@playwright/test"]
    union = set()
    full_ids = None
    config = None
    seen = set()
    for root in roots:
        def read(name):
            return json.loads((root / name).read_text(encoding="utf-8"))

        summary = read("summary.json")
        coordinate = summary["shard"]
        current = coordinate["current"]
        if (type(current) is not int or not 1 <= current <= total or current in seen
                or coordinate != {"current": current, "total": total}
                or summary["head"] != plan["head"] or summary["selection_fingerprint"] != expected
                or summary["exit_code"] != 0 or summary["requested_layer"] != "browser"):
            raise ValueError("invalid, failed or mismatched browser shard receipt")
        seen.add(current)
        full = read("browser-regressions-full.json")
        listed = read("browser-regressions-list.json")
        actual = read("browser-regressions.json")
        validated = read("browser-regressions-validated.json")
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
        if browser_results.validate(listed, actual, current, total) != validated:
            raise ValueError("browser validated outcome differs from reports")
        ids = set(browser_results.collection(listed))
        if union & ids:
            raise ValueError("browser shards overlap")
        union.update(ids)
    if seen != set(range(1, total + 1)) or union != full_ids:
        raise ValueError("browser shard union differs from complete discovery")
    if plan["mode"] == "targeted":
        selected_files = {path.removeprefix("tests/e2e/") for path in plan["e2e_specs"]}
        if {case[0] for case in full_ids} != selected_files:
            raise ValueError("browser discovery differs from selected spec files")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("expand", "gate"))
    parser.add_argument("--plan", type=Path, default=Path(".artifacts/ci-plan.json"))
    parser.add_argument("--root", type=Path, default=Path(".artifacts/browser-evidence"))
    parser.add_argument("--total", type=int)
    args = parser.parse_args()
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
        gate(plan, args.total, roots)
        print(f"Verified {args.total} browser shard(s), exact discovery union and outcomes")


if __name__ == "__main__":
    main()
