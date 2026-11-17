"""Run a selected CI layer, passing failed preparation to its file groups."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def blocked_preparation(steps: dict, requirements: dict) -> list[str]:
    ids = {"build": "build", "python-dependencies": "py_install", "ffmpeg": "ffmpeg",
           "chromium": "chromium", "node-dependencies": "js_install"}
    if set(requirements) != set(ids) or any(type(value) is not bool for value in requirements.values()):
        raise ValueError("invalid CI preparation requirements")
    return [name for name, needed in requirements.items()
            if needed and steps.get(ids[name], {}).get("outcome") != "success"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--plan", default=".artifacts/ci-plan.json")
    parser.add_argument("--shard")
    parser.add_argument("--blocked-preparation", action="append", default=[])
    args = parser.parse_args()
    steps = json.loads(os.environ["CI_PREPARATION"])
    requirements = json.loads(os.environ["CI_REQUIREMENTS"])
    blocked = list(dict.fromkeys([*blocked_preparation(steps, requirements), *args.blocked_preparation]))
    venv = Path(".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    # On POSIX the venv executable is a symlink. Resolving it selects the base
    # interpreter and loses the venv's installed packages.
    interpreter = str(venv.absolute()) if steps.get("py_install", {}).get("outcome") == "success" else sys.executable
    env = {**os.environ, "MAW_TEST_PYTHON": interpreter, "MAW_E2E_PYTHON": interpreter}
    command = [interpreter, "scripts/test_workflow.py", "--stage", "merge", "--selection-plan",
               args.plan, "--layer", args.layer, "--report-dir", args.report_dir]
    if args.shard:
        command += ["--shard", args.shard]
    for name in blocked:
        command += ["--blocked-preparation", name]
    print("Unavailable preparation:", ", ".join(blocked) or "none", flush=True)
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
