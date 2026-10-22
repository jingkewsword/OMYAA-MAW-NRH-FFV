"""Small, conservative test ownership map. New tests default to the common gate."""
from __future__ import annotations

import os
import ast
import re
from pathlib import Path

PYTHON_PACKS = ("common", "media", "long-media", "tools", "manual")
WINDOWS_FFMPEG_TESTS = (
    "tests.test_ffmpeg.FfmpegResolverTests.test_windows_python_module_does_not_shadow_path_executables",
    "tests.test_ffmpeg.FfmpegResolverTests.test_windows_scripts_are_not_accepted_as_ffmpeg_executables",
)
MEDIA_MODULES = {"test_ffprobe_failure_integration", "test_gap_removed_audio_export", "test_gap_removed_video_compatibility",
                 "test_media_cache", "test_quapeaks_generation",
                 "test_thumbnail_jobs_integration", "test_thumbnail_server"}
MEDIA_CLASSES = {
    ("test_audio_loudness", "RealLoudnessTests"),
    ("test_burn_video_export", "BurnVideoPrecisionTests"),
    ("test_media_keyframes", "RealKeyframeInspectorTests"),
    ("test_gap_removed_embedded_subtitles", "EmbeddedSubtitleTimelineTests"),
    ("test_gap_removed_video_timeline", "RealVideoTimelineTests"),
}
SCHEMA_PATHS = {"JSON_SCHEMA.md", "docs/engineering/JSON_SCHEMA.md"}
DOC_TOOL_PATHS = {"scripts/check_docs.py", "scripts/prepare_release_notes.py",
                  "scripts/publish_release.py", "tests/test_docs_check.py", "tests/test_release_notes.py",
                  "tests/test_release_site.py", "tests/test_release_publication.py"}
SITE_TOOL_PATHS = {"scripts/build_release_site.py", "scripts/prepare_release_notes.py"}
TOOL_MODULES = {"test_docs_check", "test_release_notes", "test_release_site", "test_release_publication", "test_run_check", "test_run_tests_runner",
                "test_verification_checklist", "test_verification_checklist_build", "test_verify_sha256_script", "test_macos_icon",
                "test_packaging_contract", "test_test_workflow", "test_browser_results"}
MEDIA_METHODS = {
    "test_streaming_extraction_and_cache_match", "test_low_rate_multichannel_keeps_opposite_and_one_sided_audio",
    "test_mono_stays_identical_and_third_channel_is_included", "test_mopeaks_generation_does_not_need_native_quapeaks",
    "test_embed_waveform_adds_valid_payload_without_writing_cache",
    "test_real_audio_pipeline_writes_loadable_artifacts_without_asr",
    "test_low_volume_and_nfd_input_align_without_silence_gate",
    "test_real_preflight_never_loads_model_or_writes_artifacts",
    "test_ass_frame_render_uses_real_libass_when_available",
    "test_green_screen_frame_uses_playhead_time_with_real_libass",
    "test_srt_filter_with_special_font_name_parses_in_real_ffmpeg",
    "test_real_ffmpeg_cancel_removes_output_without_changing_source",
    "test_real_stream_copy_mp4_mkv_ts_multitrack_and_nonzero_origin",
    "test_final_generation_uses_selected_audio_track",
    "test_full_pipeline_preserves_extra_gap_and_original_text",
    "test_internal_repetition_joins_only_kept_audio_and_rejects_cross_join_tokens",
    "test_long_source_offsets_nfd_and_later_line_failure_are_transactional",
    "test_retained_extra_inside_joined_script_envelope_refuses_finalization",
    "test_source_items_fill_keeps_asr_text_and_publishes_only_complete_output",
    "test_source_items_fill_uses_selected_audio_track_and_original_offsets",
}
NODE_BROWSER = {"test_asr_presets_browser.mjs", "test_ass_canvas_raster.mjs", "test_shared_tooltip_browser.mjs"}
NODE_TOOLS = {"test_ns_rewrite_scope.mjs", "test_refactor_layout_tools.mjs", "test_type_gate.mjs",
              "test_verification_checklist.mjs"}
CHECKLIST_PYTHON = ("tests.test_verification_checklist", "tests.test_verification_checklist_build")
CHECKLIST_NODE = "tests/test_verification_checklist.mjs"
CHECKLIST_SPEC = "tests/e2e/verification-checklist.spec.mjs"
DEV_PYTHON = ("tests.test_project_contract", "tests.test_project_io", "tests.test_project_backups")
DEV_NODE = ("test_editor_runtime.mjs", "test_editor_state.mjs", "test_editor_commands.mjs",
            "test_editor_host.mjs", "test_editor_history_gestures.mjs")


def python_pack(test_id: str) -> str:
    parts = test_id.split(".")
    module = next((part for part in parts if part.startswith("test_")), "")
    method = parts[-1]
    if module in TOOL_MODULES:
        return "tools"
    if method == "test_real_mosp_keeps_only_real_take_boundaries":
        return "manual"
    if "LongMediaGeneratedFixtureTests" in parts or method == "test_eleven_minute_real_audio_preserves_acoustic_offsets":
        return "long-media"
    if any(owner == module and name in parts for owner, name in MEDIA_CLASSES):
        return "media"
    if module == "test_thumbnails" and "ThumbnailIntegrationTests" in parts:
        return "media"
    if module in MEDIA_MODULES or (module == "test_reapeaks_fixture" and "GeneratedFixtureTests" in parts):
        return "media"
    if method in MEDIA_METHODS or (module == "test_reapeaks" and method.startswith("test_generate_for_media_")):
        return "media"
    return "common"


def node_pack(filename: str) -> str:
    if filename in NODE_BROWSER:
        return "browser"
    if filename.startswith("test_e2e_"):
        return "lifecycle"
    if filename in NODE_TOOLS:
        return "tools"
    return "common"


def source_test_ids(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [f"{path.stem}.{cls.name}.{method.name}" for cls in tree.body if isinstance(cls, ast.ClassDef)
            for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            and method.name.startswith("test")]


def allowed_platform_skip(test_id: str, reason: str) -> bool:
    """Dependency/codec/fixture skips are never successes in a required pack."""
    if os.name == "nt":
        return (test_id.endswith("test_open_existing_path_uses_external_opener_for_file_and_folder")
                or "test_verify_sha256_script.VerifySha256ScriptTests" in test_id
                and "需要能读取仓库路径且带 sha256sum/awk/grep 的 bash" in reason
                or ("symbolic links unavailable:" in reason or "Symlink creation is unavailable:" in reason)
                and any(name in test_id for name in ("test_editor_manifest.", "test_asr_presets.")))
    return (test_id in WINDOWS_FFMPEG_TESTS and reason == "Windows PATHEXT resolution"
            or test_id.endswith("test_open_output_folder_uses_startfile_on_windows")
            or "test_local_log.DefaultLogDirectoryTests." in test_id)


ALL_MERGE = {"common", "browser", "smoke", "media", "long-media", "lifecycle", "tools", "editor-e2e", "website"}

# Leaf risks select existing consumer families. Shared state/host/schema/layout
# and an unrecognized leaf deliberately keep the full-browser fallback.
E2E_FAMILIES = (
    (("gap",), ("gap-", "ai-cleanup", "script-alignment", "script-timestamp", "waveform-history", "waveform-deletion", "burn-video-jobs", "editor-help-srt-burn")),
    (("ai_cleanup", "ai-cleanup", "postprocess_ai"), ("ai-cleanup", "gap-", "marker")),
    (("script_match", "script-match", "script_alignment", "script_timestamp", "server-align/"), ("script-", "server-align", "launcher-script-match", "gap-")),
    (("waveform", "reapeaks", "quapeaks", "media_cache", "playback", "seek", "audition"), ("waveform-", "playback-", "playhead-", "hover-seek", "subtitle-seek", "cue-context", "media-controls", "gap-", "filmstrip")),
    (("thumbnail", "filmstrip"), ("filmstrip", "waveform-view-performance", "settings-structure")),
    (("segmentation", "punctuation", "word_timing", "word-timing", "timed-text", "text-tools", "split", "merge"), ("word-timing", "timed-text", "split-", "keyboard-timing", "editor-text-tools", "launcher-resegment")),
    (("ass_", "ass-", "/ass.", "font", "subtitle-preview"), ("ass-", "subtitle-preview", "bilingual-label", "burn-video-jobs", "editor-help-srt-burn")),
    (("export", "fcp7", "otio"), ("ass-export", "fcp7-export", "otio-export", "gap-", "multi-subtitle", "speaker-label", "waveform-history", "editor-menu-focus", "burn-video-jobs", "editor-help-srt-burn")),
    (("sticker", "burn-video"), ("burn-video-jobs", "editor-help-srt-burn", "ass-export")),
    (("marker", "speaker", "overlay", "multi-subtitle", "multi_subtitle"), ("marker", "speaker-label", "overlay-track", "multi-subtitle")),
    (("cue-scroll", "cue-list", "cue-render"), ("cue-", "click-behavior", "layout-feedback")),
    (("tooltip",), ("shared-tooltip", "launcher-keycaps")),
    (("onboarding",), ("onboarding", "new-project")),
    (("qwen", "openai_asr", "doubao", "soniox", "local_asr", "gui_workflow", "cli.py"), ("launcher-",)),
)


def related_specs(path: str) -> list[str] | None:
    if any(token in path for token in ("/state/", "/host/", "history", "project", "manifest", "scripts.txt", "boot/", "editor.css", "layout", "serve.py")) and not path.startswith("server-align/"):
        return None
    if path.startswith("web/launcher/") or path.startswith("web/launcher"):
        prefixes = ("launcher-",)
    else:
        prefixes = tuple(prefix for tokens, family in E2E_FAMILIES if any(token in path for token in tokens) for prefix in family)
    if not prefixes:
        return None
    root = Path(__file__).resolve().parents[1]
    specs = [str(p.relative_to(root)).replace("\\", "/") for p in sorted((root / "tests/e2e").glob("*.spec.mjs")) if p.name.startswith(prefixes)]
    return specs or None


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
    """Unknown paths broaden; absence of a reliable diff also broadens."""
    selected = {"docs"}
    reasons = ["documentation navigation is always checked"]
    preview = release
    e2e_specs = set()
    if release or not paths:
        return {"packs": sorted(ALL_MERGE | selected), "preview": True, "e2e_specs": [],
                "reasons": ["release or unavailable change list: expand all required packs"]}
    for original in paths:
        path = original.replace("\\", "/").removeprefix("./")
        if path in {"maw/ffmpeg.py", "tests/test_ffmpeg.py"}:
            selected.add("lifecycle")
        if path in SITE_TOOL_PATHS or path.startswith(("docs/releases/", "docs/assets/")):
            selected.add("website")
            reasons.append(f"release site consumes this document input: {path}")
            continue
        if path.startswith("docs/") or path in {"README.md", "CHANGELOG.md", "CONTRIBUTING.md", "AGENTS.md", "JSON_SCHEMA.md"}:
            if path in SCHEMA_PATHS:
                selected.update(ALL_MERGE)
            continue
        if path.startswith("website/"):
            selected.add("website")
            continue
        if path in DOC_TOOL_PATHS:
            reasons.append(f"document tooling and its regressions are covered by docs: {path}")
            continue
        if path.startswith("tools/verification-checklist/"):
            selected.update({"tools", "e2e"})
            e2e_specs.add("tests/e2e/verification-checklist.spec.mjs")
            continue
        if path.startswith("tests/e2e/") and path.endswith(".spec.mjs"):
            scope = spec_scope(path)
            if scope == "independent":
                selected.add("e2e")
                e2e_specs.add(path)
                reasons.append(f"independent browser spec: {path}")
            elif scope == "missing":
                selected.add("editor-e2e")
                reasons.append(f"missing browser spec: {path}")
            else:
                selected.update(ALL_MERGE)
                reasons.append(f"shared or unrecognized spec consumers: {path}")
            continue
        # Shared test infrastructure/locks/workflows can invalidate every gate.
        if path.startswith(("scripts/test_", "scripts/run_", "scripts/browser_results", "scripts/check_test_gate", ".github/workflows/", "tests/e2e/", "tests/fixtures/", "tests/config/")) or path in {"pyproject.toml", "uv.lock", "package.json", "pnpm-lock.yaml", "playwright.config.mjs"}:
            selected.update(ALL_MERGE)
            preview = True
            reasons.append(f"shared infrastructure: {path}")
            continue
        if path.startswith("tests/test_"):
            if path.endswith(".py"):
                source = Path(__file__).resolve().parents[1] / path
                if not source.is_file():
                    selected.update(ALL_MERGE)
                    reasons.append(f"deleted/unavailable test source: {path}")
                    continue
                ids = source_test_ids(source)
                if not ids:
                    selected.update(ALL_MERGE)
                    reasons.append(f"unrecognized/dynamic test discovery: {path}")
                    continue
                owners = {python_pack(name) for name in ids} - {"manual"}
                selected.update(owners)
            else:
                owners = {node_pack(Path(path).name)}
                selected.update(owners)
            if owners - {"tools"}:
                selected.update({"common", "browser", "smoke"})
            continue
        selected.update({"common", "browser", "smoke"})
        if path.startswith("web/") or path in {"edit.py", "server-editor/index.html"}:
            specs = related_specs(path)
            selected.add("e2e" if specs else "editor-e2e")
            e2e_specs.update(specs or [])
        elif path.startswith(("maw/", "server-editor/", "server-align/")) or path in {"maw_gui.py", "generate_subtitle_qwen_api.py"}:
            specs = related_specs(path)
            selected.update({"media", "e2e" if specs else "editor-e2e"})
            e2e_specs.update(specs or [])
            if any(token in path for token in ("waveform", "reapeaks", "quapeaks", "script_timestamp", "project", "history")):
                selected.add("long-media")
        elif path.startswith(("resources/", "scripts/build-", "scripts/verify_", "scripts/packaging/", "runtime/", "local-runtime/", "ocr-runtime/", "moss-runtime/")) or path in {"MAW.spec", "requirements.txt"}:
            preview = True
            selected.update({"tools", "media"})
        else:
            selected.update(ALL_MERGE)
            preview = True
            reasons.append(f"unknown path: {path}")
    if "editor-e2e" in selected:
        selected.discard("e2e")
        e2e_specs.clear()
    return {"packs": sorted(selected), "preview": preview, "reasons": reasons, "e2e_specs": sorted(e2e_specs),
            "tools_scope": checklist_tools_scope(paths)}


def checklist_tools_scope(paths: list[str]) -> str:
    """A closed consumer boundary, never inferred from tools pack membership."""
    normalized = [path.replace("\\", "/").removeprefix("./") for path in paths]
    checklist = {CHECKLIST_NODE, CHECKLIST_SPEC, *(module.replace(".", "/") + ".py" for module in CHECKLIST_PYTHON)}
    def owned(path):
        return ".." not in Path(path).parts and (path.startswith("tools/verification-checklist/") or path in checklist)
    def docs(path):
        return path not in SCHEMA_PATHS and (path.startswith("docs/")
                or path in {"README.md", "CHANGELOG.md", "CONTRIBUTING.md"} or path in DOC_TOOL_PATHS)
    return "checklist" if normalized and any(owned(path) for path in normalized) and all(
        owned(path) or docs(path) for path in normalized) else "all"
