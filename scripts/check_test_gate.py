"""Validate GitHub job results without treating missing selector flags as false."""
from __future__ import annotations

import json
import os

FLAGS = ("app", "common", "browser", "smoke", "media", "long_media", "lifecycle", "tools", "website", "e2e", "editor_e2e")


def check_gate(jobs: dict) -> list[str]:
    required = ["selection", "documentation"]
    outputs = jobs["selection"]["outputs"]
    if any(outputs.get(flag) not in ("true", "false") for flag in FLAGS):
        raise ValueError("Missing or invalid required selector flags")
    if ((outputs["app"] == "false" and any(outputs[flag] == "true" for flag in FLAGS if flag not in ("app", "website")))
            or outputs["e2e"] == outputs["editor_e2e"] == "true"):
        raise ValueError("Contradictory required selector flags")
    for name, flag in (("editor", "app"), ("windows-lifecycle", "lifecycle"), ("website", "website")):
        if outputs[flag] == "true":
            required.append(name)
    if outputs["editor_e2e"] == "true":
        required.append("browser-gates")
    return [name for name in required if jobs.get(name, {}).get("result") != "success"]


def main() -> int:
    try:
        failed = check_gate(json.loads(os.environ["RESULTS"]))
    except (KeyError, ValueError, TypeError) as error:
        print(f"Required test gate failed: {error}")
        return 1
    if failed:
        print("Required jobs did not succeed: " + ", ".join(failed))
        return 1
    print("Every selected required job and browser coverage gate succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
