"""Temporary CI proof: independent fixed-spec collection versus verified shards."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from browser_results import browser_cases, browser_config, combine_shards, discovery

SPECS = [
    "tests/e2e/editor-bundle.spec.mjs",
    "tests/e2e/editor-transactions.spec.mjs",
    "tests/e2e/editor-text-tools.spec.mjs",
    "tests/e2e/ass-cue-position.spec.mjs",
    "tests/e2e/sticker-preview-lifecycle.spec.mjs",
    "tests/e2e/warma-presets.spec.mjs",
    "tests/e2e/warma-i18n.spec.mjs"
]

def main():
    output = Path(".artifacts/independent-comparison.json")
    result = {"status": "failed"}
    try:
        if os.environ.get("DISCOVERY_JOB_RESULT") != "success" or os.environ.get("SHARD_JOB_RESULT") != "success":
            raise ValueError("Discovery or complete browser gate did not succeed")
        current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        independent = Path(".artifacts/independent-fixed")
        if (independent / "revision.txt").read_text(encoding="utf-8").strip() != current:
            raise ValueError("Independent discovery belongs to another revision")
        report = json.loads((independent / "fixed.json").read_text(encoding="utf-8"))
        fixed_ids = set(discovery(report, SPECS))
        files = sorted(Path(".artifacts/independent-shards").rglob("browser-regressions-browser-run.json"))
        records = [json.loads(path.read_text(encoding="utf-8")) for path in files]
        coverage = combine_shards(records, 4, current)
        if browser_config(report) != coverage["scope"]["config"]:
            raise ValueError("Independent discovery config/version differs from shard discovery")
        cases = browser_cases(report)
        planned = set().union(*(set(record["planned_ids"]) for record in records))
        passed = set().union(*(set(record["passed_ids"]) for record in records))
        skipped = set().union(*(set(record["allowed_skipped_ids"]) for record in records))
        missing = fixed_ids - planned
        unverified = fixed_ids - passed - skipped
        if missing or unverified or (passed & skipped):
            raise ValueError(f"Fixed cases missing from plans={len(missing)} or unverified={len(unverified)}")
        by_spec = {}
        for spec in SPECS:
            name = spec.rsplit("/", 1)[-1]
            ids = {identity for identity, case in cases.items() if case["_file"].split("/")[-1] == name}
            by_spec[name] = {"discovered": len(ids), "passed": len(ids & passed),
                             "approved_skips": len(ids & skipped), "ids": sorted(ids)}
        result = {"status": "passed", "revision": current, "config": browser_config(report),
                  "independent_ids": len(fixed_ids), "passed": len(fixed_ids & passed),
                  "approved_skips": len(fixed_ids & skipped), "by_spec": by_spec}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"status": "failed", "error": str(error)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    brief = {key: value for key, value in result.items() if key != "by_spec"}
    if result.get("by_spec"):
        brief["by_spec"] = {name: {k: v for k, v in entry.items() if k != "ids"}
                            for name, entry in result["by_spec"].items()}
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1

if __name__ == "__main__":
    sys.exit(main())
