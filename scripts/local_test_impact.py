"""Local test selection. Shared, unknown and deleted paths widen coverage."""
from __future__ import annotations
import re
from pathlib import Path
NODE_BROWSER = {"test_asr_presets_browser.mjs", "test_ass_canvas_raster.mjs", "test_shared_tooltip_browser.mjs"}
NODE_TOOLS = {"test_ns_rewrite_scope.mjs", "test_refactor_layout_tools.mjs", "test_type_gate.mjs",
              "test_verification_checklist.mjs"}
CHECKLIST_PYTHON = ("tests.test_verification_checklist", "tests.test_verification_checklist_build")
CHECKLIST_NODE = "tests/test_verification_checklist.mjs"
CHECKLIST_SPEC = "tests/e2e/verification-checklist.spec.mjs"
CHECKLIST_SPECS = (CHECKLIST_SPEC, "tests/e2e/tool-compact.spec.mjs", "tests/e2e/tool-pages.spec.mjs")
DEV_PYTHON = ("tests.test_project_contract", "tests.test_project_io", "tests.test_project_backups")
DEV_NODE = ("test_editor_runtime.mjs", "test_editor_state.mjs", "test_editor_commands.mjs",
            "test_editor_host.mjs", "test_editor_history_gestures.mjs")

def node_pack(filename: str) -> str:
    if filename in NODE_BROWSER:
        return "browser"
    if filename.startswith("test_e2e_"):
        return "lifecycle"
    if filename in NODE_TOOLS:
        return "tools"
    return "common"


ALL_MERGE = {"common", "browser", "smoke", "media", "long-media", "lifecycle", "tools", "editor-e2e", "website"}
SITE_EXTRA_DOCUMENTS = {"docs/engineering/DEVELOPMENT.md", "docs/engineering/LLM_POSTPROCESS_PROTOCOL.md", "docs/engineering/MOSE.md", "docs/logs/unversioned/2026-07-28/ASR_PROVIDER_RESEARCH.md"}


def spec_scope(path: str) -> str:
    """Only narrow runnable specs with no exported or referenced test module.

    This is deliberately conservative, not a general JS dependency resolver.
    Shared helpers/fixtures never enter this path. Literal references anywhere
    in test JS, including Node consumers and nested helpers, keep all packs.
    """
    root = Path(__file__).resolve().parents[1]
    source = root / path
    try:
        if ".." in Path(path).parts:
            return "shared"
        if source.is_file() and re.search(r"\bexport\s+(?:default|const|let|var|async|function|class)\b|\bexport\s*[{*]",
                                         source.read_text(encoding="utf-8")):
            return "shared"
        for consumer in (root / "tests").rglob("*"):
            if consumer != source and consumer.suffix in {".mjs", ".js", ".ts"} and consumer.is_file():
                if source.name in consumer.read_text(encoding="utf-8"):
                    return "shared"
    except (OSError, UnicodeError):
        return "shared"
    return "independent" if source.is_file() else "missing"


def select_packs(paths: list[str], *, release: bool = False) -> dict:
    root = Path(__file__).resolve().parents[1]
    def full(reason):
        return {"packs": sorted(ALL_MERGE | {"docs"}), "e2e_specs": [],
                "tools_scope": "all", "reasons": [reason]}
    if release or not paths:
        return full("release or unavailable change list: expand all required packs")
    normalized = [p.replace("\\", "/").removeprefix("./") for p in paths]
    if any(not p or p.startswith("/") or ":" in p or any(part in {"", ".", ".."} for part in p.split("/"))
           or not (root / p).is_file() for p in normalized):
        return full("deleted, unavailable or malformed path")
    def category(p):
        if p.startswith("tools/verification-checklist/"):
            return "checklist"
        if p.startswith("tests/e2e/") and p.endswith(".spec.mjs"):
            return "spec"
        if p.startswith("website/scripts/"):
            return "other"
        if p in {"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "AGENTS.md"} or p.startswith(("docs/", "website/")):
            return "docs"
        return "other"
    categories = {category(p) for p in normalized}
    if len(categories) != 1 or "other" in categories:
        return full("shared, unknown, dynamic or mixed changes")
    kind = categories.pop()
    if kind == "spec":
        if any(spec_scope(p) != "independent" for p in normalized):
            return full("browser spec has shared or unknown consumers")
        return {"packs": ["docs", "e2e"], "e2e_specs": sorted(set(normalized)),
                "tools_scope": "all", "reasons": ["independent browser specs"]}
    if kind == "checklist":
        return {"packs": ["docs", "e2e", "tools"], "e2e_specs": list(CHECKLIST_SPECS),
                "tools_scope": "checklist", "reasons": ["checklist and its three browser consumers"]}
    if any(p in {"JSON_SCHEMA.md", "docs/engineering/JSON_SCHEMA.md"}
           or p.startswith(("website/src/pages/docs/", "website/src/pages/releases/", "website/src/generated/",
                            "website/public/docs-assets/", "website/public/releases/", "website/public/release-assets/"))
           or p.startswith("docs/") and not p.endswith(".md") and not p.startswith("docs/assets/")
           for p in normalized):
        return full("schema, generated or non-document inputs")
    website = any(p in {"README.md", "docs/INDEX.md", "website/README.md"} or p in SITE_EXTRA_DOCUMENTS
                  or p.startswith(("website/", "docs/user/", "docs/releases/", "docs/assets/")) for p in normalized)
    return {"packs": ["docs", "website"] if website else ["docs"], "e2e_specs": [],
            "tools_scope": "all", "reasons": ["document and website consumers"]}
