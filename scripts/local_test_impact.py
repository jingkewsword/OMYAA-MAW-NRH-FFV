"""Local test selection. Shared, unknown and deleted paths widen coverage."""
from __future__ import annotations
import json
import re
import subprocess
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


def select_packs(paths: list[str], *, release: bool = False, base_ref: str | None = None) -> dict:
    """Select literal consumers, widening dynamic application boundaries by domain."""
    try:
        from .test_impact_graph import consumers, document_consumers
        from .test_policy import MEDIA_MODULES, MEDIA_CLASSES, MEDIA_METHODS
    except ImportError:
        from test_impact_graph import consumers, document_consumers
        from test_policy import MEDIA_MODULES, MEDIA_CLASSES, MEDIA_METHODS

    root = Path(__file__).resolve().parents[1]
    all_packs = sorted(ALL_MERGE | {"docs"})

    def full(reason):
        return {"mode": "full", "packs": all_packs, "python_tests": [], "node_tests": [],
                "e2e_specs": [], "tools_scope": "all", "reasons": [reason],
                "preparation": {"application": True, "real_media": True, "lint": True,
                                "preview_windows": True, "python_dependencies": True}}

    if release or not paths:
        return full("release or unavailable change list: expand all required packs")
    normalized = sorted(set(p.replace("\\", "/").removeprefix("./") for p in paths))
    if any(not p or p.startswith("/") or ":" in p or any(part in {"", ".", ".."} for part in p.split("/"))
           for p in normalized):
        return full("malformed path")

    def category(p):
        if p == "package.json" or p in {".github/workflows/editor-checks.yml", ".github/workflows/pr-release-windows.yml",
                                      ".github/workflows/python-lint.yml"}:
            return "governance"
        if p.startswith("tools/verification-checklist/"):
            return "checklist"
        if p.startswith("website/scripts/"):
            return "website-script"
        if p in {"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "AGENTS.md"} or p.startswith(("docs/", "website/")):
            return "docs"
        if p in {"maw_gui.py", "edit.py"} or p.startswith(("maw/", "web/", "tests/", "scripts/", "server-editor/")):
            return "domain"
        return "unknown"

    if any(category(p) == "unknown" for p in normalized):
        return full("unknown or broad contract/dependency input")
    if any(p.startswith("website/src/pages/docs/") and not p.endswith(".md")
           or p.startswith(("website/src/pages/releases/",
           "website/src/generated/", "website/public/docs-assets/", "website/public/releases/", "website/public/release-assets/"))
           or p.startswith("docs/") and not p.endswith(".md") and not p.startswith(("docs/assets/", "docs/logs/")) for p in normalized):
        return full("schema, generated or non-document contract input")

    package_scope = None
    if "package.json" in normalized:
        try:
            old = subprocess.run(["git", "show", f"{base_ref or 'HEAD'}:package.json"], cwd=root,
                                 capture_output=True, check=True).stdout.decode("utf-8")
            before, after = json.loads(old), json.loads((root / "package.json").read_text(encoding="utf-8"))
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise ValueError("package manifest must be an object")
            if {k: v for k, v in before.items() if k != "scripts"} != {k: v for k, v in after.items() if k != "scripts"}:
                return full("package dependencies, engine or other shared configuration changed")
            package_scope = "scripts" if before.get("scripts") != after.get("scripts") else "unchanged"
        except (OSError, UnicodeError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
            package_scope = "unavailable"

    packs, python, node, specs, reasons = set(), set(), set(), set(), []
    application = media = lint = preview = False
    governance = [p for p in normalized if category(p) == "governance"]
    if governance:
        python.update(f"tests/{name}" for name in ("test_local_test_workflow.py", "test_impact_consumers.py",
                      "test_ci_impact.py", "test_ci_matrix.py", "test_workflow_selection.py", "test_test_workflow.py")
                      if (root / "tests" / name).is_file())
        reasons.append("workflow and test-selection governance consumers")
        if ".github/workflows/pr-release-windows.yml" in governance:
            preview = True
        if ".github/workflows/editor-checks.yml" in governance or package_scope == "unavailable":
            node.update(p for p in ("tests/test_editor_bundle.mjs", "tests/test_launcher_bundle.mjs") if (root / p).is_file())
            specs.update(p for p in ("tests/e2e/editor-bundle.spec.mjs", "tests/e2e/editor-transactions.spec.mjs") if (root / p).is_file())
            application = True
        if package_scope == "scripts":
            if (root / "tests/test_web_build.py").is_file():
                python.add("tests/test_web_build.py")
            node.update(p for p in ("tests/test_editor_bundle.mjs", "tests/test_launcher_bundle.mjs") if (root / p).is_file())
            application = True
            reasons.append("package scripts changed: check manifest-triggered bundle rebuild")
        elif package_scope == "unchanged":
            reasons.append("package manifest matches the comparison baseline")
        elif package_scope == "unavailable":
            reasons.append("package baseline unavailable: include governance and build smoke")
    checklist = any(category(p) == "checklist" for p in normalized)
    documents = [p for p in normalized if category(p) == "docs"]
    domains = [p for p in normalized if category(p) == "domain"]
    schema = any(p in {"docs/engineering/JSON_SCHEMA.md", "website/src/pages/docs/json-schema.md"} for p in documents)
    if documents:
        packs.add("docs")
        python.update({"tests/test_docs_check.py", "tests/test_release_notes.py", "tests/test_release_site.py",
                       "tests/test_release_publication.py"})
        if any(p in {"README.md", "docs/INDEX.md", "website/README.md"} or p in SITE_EXTRA_DOCUMENTS
               or p.startswith(("website/", "docs/user/", "docs/releases/", "docs/assets/")) for p in documents):
            packs.add("website")
        reasons.append("document and website consumers")
    if checklist:
        packs.update({"docs", "tools", "e2e"})
        python.update(f"tests/{name.rsplit('.', 1)[-1]}.py" for name in CHECKLIST_PYTHON)
        python.update({"tests/test_docs_check.py", "tests/test_release_notes.py", "tests/test_release_site.py",
                       "tests/test_release_publication.py"})
        node.add(CHECKLIST_NODE)
        specs.update(CHECKLIST_SPECS)
        reasons.append("checklist and its direct browser consumers")
    website_scripts = [p for p in normalized if category(p) == "website-script"]
    if website_scripts:
        packs.add("website")
        reasons.append("website script and its consumers")
    if "scripts/build-tool-docs.mjs" in domains:
        packs.add("docs")
        reasons.append("tool documentation generator and asset freshness check")

    for consumer in document_consumers(root, documents) if documents else ():
        if consumer.endswith('.py'):
            python.add(consumer)
        elif consumer.endswith('.mjs') and consumer.startswith('tests/e2e/'):
            specs.add(consumer)
        elif consumer.endswith('.mjs'):
            node.add(consumer)
    inputs = domains + website_scripts + governance + [p for p in normalized if category(p) == "checklist"]
    if inputs:
        reached, unmatched, graph_errors = consumers(root, inputs, direct_only=set(governance))
        if graph_errors:
            # An unreadable or syntactically invalid source can hide an import.
            # Widen by language rather than silently treating the graph as complete.
            if any(p.endswith('.py') for p in graph_errors):
                python.update(x.relative_to(root).as_posix() for x in (root / 'tests').glob('test_*.py'))
            if any(not p.endswith('.py') for p in graph_errors):
                node.update(x.relative_to(root).as_posix() for x in (root / 'tests').glob('test_*.mjs'))
                specs.update(x.relative_to(root).as_posix() for x in (root / 'tests/e2e').glob('*.spec.mjs'))
            reasons.append("unreadable or invalid graph input: widen affected test domains")
        for p in reached:
            if not (root / p).is_file():
                continue
            if p.startswith("tests/test_") and p.endswith(".py"):
                python.add(p)
            elif p.startswith("tests/test_") and p.endswith(".mjs"):
                node.add(p)
            elif p.startswith("tests/e2e/") and p.endswith(".spec.mjs"):
                specs.add(p)
        reasons.append("literal direct and transitive consumers")

    # Classic script registration and server/browser calls are dynamic. Expand
    # to the relevant product domain; explicitly broad assembly remains broad.
    app_sources = [p for p in domains if p in {"maw_gui.py", "edit.py"} or p.startswith(("maw/", "web/", "server-editor/"))]
    web_sources = [p for p in app_sources if p.startswith("web/")]
    if app_sources or any(p.startswith("scripts/packaging/") or p in {"scripts/build-windows.ps1", "scripts/build-editor.mjs", "scripts/build-launcher.mjs"} for p in domains):
        preview = True
    lint = ".github/workflows/python-lint.yml" in governance or any(
        p.endswith(".py") and (p in {"maw_gui.py", "edit.py"} or p.startswith(("maw/", "server-editor/", "scripts/"))) for p in domains)
    dynamic_specs = set()
    dynamic_nodes = set()
    if any(p in {"scripts/build-editor.mjs", "scripts/build-launcher.mjs"} for p in domains):
        dynamic_specs.update(x.stem.removesuffix('.spec') for x in (root / 'tests/e2e').glob('*.spec.mjs')
                             if not x.name.startswith('tool-') and x.name != 'verification-checklist.spec.mjs')
        dynamic_nodes.update(x.name for x in (root / 'tests').glob('test_*.mjs')
                             if node_pack(x.name) not in {'tools', 'lifecycle'})
        application = True
        reasons.append("application builders assemble shared runtime: include application UI domain")
    for p in app_sources:
        if p == "web/editor/cues/editor-color-filter.js":
            dynamic_specs.update({"cue-color-filter", "overlay-track", "speaker-identity-surfaces"})
            dynamic_nodes.update({"test_editor_cues_imports.mjs", "test_editor_feedback_ui.mjs", "test_v2_cue_panel_render.mjs"})
        elif p.startswith("web/editor/cues/"):
            dynamic_specs.update({"cue-color-filter", "cue-context-seek", "editor-transactions", "timed-text-edit",
                                  "split-desynced-items", "split-word-gap", "word-timing", "unified-tracks"})
            dynamic_nodes.update({"test_editor_cues_imports.mjs", "test_editor_commands.mjs"})
        elif p.startswith("web/editor/styles/"):
            dynamic_specs.update({"ass-cue-position", "ass-frame-preview", "ass-export", "speaker-labels", "speaker-manager"})
            dynamic_nodes.update({"test_editor_styles_imports.mjs", "test_ass_cue_style.mjs"})
        elif p.startswith("web/editor/media/"):
            dynamic_specs.update({"audio-processing", "filmstrip", "filmstrip-real", "waveform-click-seek",
                                  "waveform-cue-quick-edit", "playback-refresh"})
            dynamic_nodes.update({"test_waveform_js.mjs", "test_audio_processing.mjs"})
        elif p.startswith("web/editor/io/"):
            dynamic_specs.update({"editor-transactions", "project-boundary", "new-project", "fcp7-export",
                                  "otio-export", "ass-export", "unified-tracks"})
            dynamic_nodes.update({"test_editor_export_srt.mjs", "test_project_boundary.mjs"})
        elif p in {"web/editor.css", "web/editor-template.html"}:
            dynamic_specs.update({"cue-list-layout", "editor-feedback-layout", "settings-structure", "media-controls-layout",
                                  "cue-color-filter", "editor-transactions", "new-project"})
            dynamic_nodes.update({"test_editor_bundle.mjs", "test_editor_feedback_ui.mjs"})
        elif p.startswith("web/launcher/"):
            dynamic_specs.update(x.stem.removesuffix('.spec') for x in (root / 'tests/e2e').glob('launcher-*.spec.mjs'))
            dynamic_nodes.update(x.name for x in (root / 'tests').glob('test_launcher*.mjs'))
        elif p.startswith("web/shared/") or p.startswith("web/editor/") or p in {"web/editor-scripts.txt", "web/launcher-scripts.txt", "web/editor-modules.json"}:
            dynamic_specs.update(x.stem.removesuffix('.spec') for x in (root / 'tests/e2e').glob('*.spec.mjs')
                                 if not x.name.startswith('tool-') and x.name != 'verification-checklist.spec.mjs')
            dynamic_nodes.update(x.name for x in (root / 'tests').glob('test_*.mjs')
                                 if node_pack(x.name) not in {'tools', 'lifecycle'})
            reasons.append("shared or assembly script: include application UI domain")
        elif p.startswith("web/"):
            dynamic_specs.update(x.stem.removesuffix('.spec') for x in (root / 'tests/e2e').glob('*.spec.mjs')
                                 if not x.name.startswith('tool-') and x.name != 'verification-checklist.spec.mjs')
            dynamic_nodes.update(x.name for x in (root / 'tests').glob('test_*.mjs')
                                 if node_pack(x.name) not in {'tools', 'lifecycle'})
            reasons.append("unclassified web runtime input: include application UI domain")
        elif p.startswith("maw/thumbnail"):
            dynamic_specs.update({"filmstrip", "filmstrip-cache", "filmstrip-real", "media-controls-layout"})
            dynamic_nodes.update({"test_editor_thumbnails.mjs"})
        elif p in {"maw/project_tracks.py", "maw/project.py", "maw/project_mutations.py"}:
            dynamic_specs.update({"project-boundary", "unified-tracks", "v2-migration-save", "speaker-identity-project",
                                  "new-project", "editor-transactions", "fcp7-export"})
        elif p.startswith("server-editor/") or p in {"maw_gui.py", "edit.py"}:
            dynamic_specs.update({"editor-bundle", "new-project", "editor-transactions", "project-boundary"})
            if p == "maw_gui.py":
                dynamic_specs.update(x.stem.removesuffix('.spec') for x in (root / 'tests/e2e').glob('launcher-*.spec.mjs'))
    if schema:
        dynamic_specs.update({"project-boundary", "unified-tracks", "v2-migration-save", "fcp7-export", "ass-export"})
        python.update({"tests/test_project_contract.py", "tests/test_project_tracks.py", "tests/test_project_io.py"})
        node.update({"tests/test_project_boundary.mjs", "tests/test_tracks_export_plan.mjs"})
        reasons.append("project schema consumers across save, migration and export")
    if dynamic_specs or dynamic_nodes:
        specs.update(f"tests/e2e/{name}.spec.mjs" for name in dynamic_specs
                     if (root / f"tests/e2e/{name}.spec.mjs").is_file())
        node.update(f"tests/{name}" for name in dynamic_nodes if (root / "tests" / name).is_file())
        reasons.append("runtime assembly or server calls: include affected product-domain consumers")
    if web_sources:
        application = True
    for p in domains:
        if p.startswith("tests/") and p.endswith(".py") and (root / p).is_file():
            source = (root / p).read_text(encoding="utf-8")
            if re.search(r"^\s*def\s+load_tests\s*\(", source, re.M):
                python.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.py"))
                reasons.append("dynamic unittest load_tests: include Python test domain")
    deleted = [p for p in domains if not (root / p).is_file()]
    for p in deleted:
        if p.startswith("tests/fixtures/"):
            python.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.py"))
            node.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.mjs"))
            specs.update(x.relative_to(root).as_posix() for x in (root / "tests/e2e").glob("*.spec.mjs"))
            reasons.append("deleted fixture may have dynamic consumers: include test domains")
        elif p.startswith("tests/test_") and p.endswith(".py"):
            python.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.py"))
            reasons.append("deleted Python test may affect discovery: include Python domain")
        elif p.startswith("tests/test_") and p.endswith(".mjs"):
            node.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.mjs"))
            reasons.append("deleted Node test may affect imports: include Node domain")
        elif p.startswith("tests/e2e/") and p.endswith(".spec.mjs"):
            specs.update(x.relative_to(root).as_posix() for x in (root / "tests/e2e").glob("*.spec.mjs"))
            reasons.append("deleted browser spec may affect shared discovery: include browser domain")
    if any(p.startswith("tests/config/") for p in domains):
        specs.update(x.relative_to(root).as_posix() for x in (root / "tests/e2e").glob("*.spec.mjs"))
        reasons.append("browser runner configuration affects browser discovery")
    if inputs and unmatched:
        # New and deleted modules may be loaded dynamically. Do not allow a
        # second, well-understood change in the same plan to hide this gap.
        uncertain_fixtures = [p for p in unmatched if p.startswith(("tests/fixtures/", "tests/helpers/", "tests/e2e/")) and not p.endswith(".spec.mjs")]
        if uncertain_fixtures:
            python.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.py"))
            node.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.mjs"))
            specs.update(x.relative_to(root).as_posix() for x in (root / "tests/e2e").glob("*.spec.mjs"))
            reasons.append("fixture or helper without visible consumers: include test domains")
        unclassified = [p for p in unmatched if category(p) in {"domain", "website-script"} and not p.startswith(("web/", "tests/fixtures/", "tests/helpers/", "tests/e2e/", "tests/config/"))]
        if any(p.endswith(".py") for p in unclassified):
            python.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.py"))
            reasons.append("no visible consumer: include Python domain for dynamic loading")
        if any(p.endswith((".js", ".mjs", ".ts")) for p in unclassified):
            node.update(x.relative_to(root).as_posix() for x in (root / "tests").glob("test_*.mjs"))
            reasons.append("no visible consumer: include Node domain for dynamic loading")
        if any(not p.endswith((".py", ".js", ".mjs", ".ts")) for p in unclassified):
            return full("input has no identifiable consumers or safe domain")
    if any(node_pack(Path(p).name) in {"common", "browser"} and Path(p).name not in {"test_readme_content_sync.mjs", "test_browser_evidence_workflow.mjs", "test_tool_markdown.mjs"} for p in node):
        application = True
    if any(p.startswith("tests/e2e/") for p in specs):
        if any(not Path(p).name.startswith("tool-") and p != CHECKLIST_SPEC for p in specs):
            application = media = True
    media_modules = MEDIA_MODULES | {module for module, _ in MEDIA_CLASSES} | {
        "test_media", "test_ffmpeg", "test_reapeaks", "test_reapeaks_fixture", "test_thumbnails"}
    media_node = {"test_ass_animation.mjs", "test_ass_canvas_layout.mjs", "test_ass_font_aliases.mjs", "test_ass_oracle_cache.mjs"}
    if any(Path(p).name in media_node for p in node):
        media = True
    if any(Path(p).stem in media_modules for p in python):
        media = True
    if not media:
        for target in python:
            file = root / target
            if file.is_file():
                source = file.read_text(encoding="utf-8")
                if any(f"def {name}(" in source for name in MEDIA_METHODS):
                    media = True
                    break
    if "tests/e2e/editor-entry-retirement.spec.mjs" in specs:
        packs.add("website")
    if python or node:
        packs.add("common")
    if specs:
        packs.add("e2e")
    if media:
        packs.add("media")
    if any(not (root / p).is_file() for p in domains):
        reasons.append("deleted domain path: retain known references and widen its dynamic domain")
    return {"mode": "targeted", "packs": sorted(packs), "python_tests": sorted(python),
            "node_tests": sorted(node), "e2e_specs": sorted(specs),
            "tools_scope": "checklist" if checklist else "all", "reasons": reasons,
            "preparation": {"application": application, "real_media": media, "lint": lint,
                            "preview_windows": preview,
                            "python_dependencies": bool(python - {"tests/test_docs_check.py", "tests/test_release_notes.py",
                                                                     "tests/test_release_site.py", "tests/test_release_publication.py"})}}
