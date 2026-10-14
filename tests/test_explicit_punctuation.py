"""Opening preserves text; punctuation cleanup requires an explicit choice."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from maw.postprocess import FixedProcessRequest, OutputMode, Replacement, _clean_chinese_punctuation, run_fixed_process
from maw.postprocess_ai_cleanup import _build_gap_remove
from maw.postprocess_ai_cleanup_items import scoped_item_ranges
from maw.postprocess_io import read_project, render_srt, write_artifacts
from maw.postprocess_pipeline import (
    default_postprocess_plan, load_postprocess_config, normalize_plan, postprocess_config_path,
    run_postprocess_pipeline, save_postprocess_plan,
)
from maw.project_io import write_mosp
from maw.script_alignment import project_cleanup_retained_segments, reliable_cleanup_items


class ExplicitPunctuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.mosp"

    def save_input(self, project):
        self.source.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")

    def run_clean(self, project, **kwargs):
        self.save_input(project)
        result = run_fixed_process(FixedProcessRequest(
            self.source, None, OutputMode.BOTH, (), clean_chinese_punctuation=True, **kwargs,
        ))
        self.assertEqual(json.loads(self.source.read_text(encoding="utf-8")), project)
        return read_project(result.project_path), result

    def test_old_flags_do_not_change_unicode_text_on_load_and_both_write_boundaries(self):
        text = "\t你好，世界。 Hello, world. cafe\u0301\u00a0👩‍💻？！\n "
        segment = {"start": 0, "end": 1000, "text": text,
                   "items": [{"start": 0, "end": 1000, "text": text}]}
        for flag in (None, True, False):
            with self.subTest(flag=flag):
                original = {"segments": [segment]}
                if flag is not None:
                    original["preserve_punctuation"] = flag
                self.save_input(original)
                loaded = read_project(self.source)
                mosp_path = self.root / "saved.mosp"
                write_mosp(mosp_path, loaded)
                artifact = write_artifacts(loaded, source_project_path=self.source, source_srt_path=None,
                                           operation="test", write_project=True, write_srt=False)
                for path in (mosp_path, artifact.project_path):
                    saved = read_project(path)
                    self.assertNotIn("preserve_punctuation", saved)
                    self.assertEqual(saved["segments"][0]["text"], text)
                    self.assertEqual(saved["segments"][0]["items"], segment["items"])
                self.assertEqual(json.loads(self.source.read_text(encoding="utf-8")), original)

    def test_cleanup_is_opt_in_and_preserves_item_boundaries_and_other_symbols(self):
        pieces = ["你好，", "世界。 Hello, world. cafe\u0301？！", "， ", "。\t"]
        items = [{"text": text, "start": i * 100, "end": (i + 1) * 100, "custom": i}
                 for i, text in enumerate(pieces)]
        original = {"segments": [{"id": "main-001", "start": 0, "end": 400,
                                  "text": "".join(pieces), "items": items}]}
        self.save_input(original)
        skipped = run_fixed_process(FixedProcessRequest(self.source, None, OutputMode.BOTH, ()))
        self.assertIsNone(skipped.project_path)
        cleaned, artifact = self.run_clean(original)
        cue = cleaned["segments"][0]
        self.assertEqual(cue["text"], "你好  世界   Hello, world. cafe\u0301？！")
        self.assertEqual("".join(item["text"] for item in cue["items"]), cue["text"])
        self.assertEqual([item["text"] for item in cue["items"]][-2:], ["", ""])
        self.assertEqual([{k: v for k, v in item.items() if k != "text"} for item in cue["items"]],
                         [{k: v for k, v in item.items() if k != "text"} for item in items])
        self.assertTrue("clean-punctuation" in artifact.project_path.name or "清理中文逗号句号" in artifact.project_path.name)

    def test_incomplete_items_stay_incomplete(self):
        project = {"segments": [{"start": 0, "end": 1000, "text": "完整，原文。",
                                 "items": [{"start": 0, "end": 200, "text": "原文，"},
                                           {"start": 200, "end": 300, "text": "。 "}]}]}
        output, _ = self.run_clean(project)
        cue = output["segments"][0]
        self.assertEqual(cue["text"], "完整  原文")
        self.assertEqual([item["text"] for item in cue["items"]], ["原文", ""])
        self.assertNotEqual("".join(item["text"] for item in cue["items"]), cue["text"])

    def test_verified_scopes_migrate_and_stale_scopes_do_not_revive(self):
        cue = {"id": "main-001", "start": 0, "end": 1000, "text": "啊，正文。",
               "items": [{"start": 0, "end": 200, "text": "啊，"},
                         {"start": 200, "end": 1000, "text": "正文。"}]}
        base = {"segments": [cue]}
        base["gap_remove"] = _build_gap_remove(base, scoped_item_ranges(cue, [0]))
        cleaned, _ = self.run_clean(base)
        scope = cleaned["gap_remove"]["provenance"]["sources"]["ai_cleanup"][0]["cleanup_scope"]
        self.assertEqual(scope["text"], "啊  ")
        self.assertIn("正文", render_srt(cleaned))
        self.assertNotIn("啊", render_srt(cleaned))
        stale = copy.deepcopy(base)
        stale["gap_remove"]["provenance"]["sources"]["ai_cleanup"][0]["cleanup_scope"]["text"] = "啊  "
        output, _ = self.run_clean(stale)
        self.assertNotIn("cleanup_scope", output["gap_remove"]["provenance"]["sources"]["ai_cleanup"][0])
        self.assertIn("啊", render_srt(output))

    def test_empty_trailing_punctuation_item_keeps_valid_prefix_scope_active(self):
        cue = {"id": "main-001", "start": 0, "end": 1000, "text": "啊，正文。",
               "items": [{"start": 0, "end": 200, "text": "啊，"},
                         {"start": 200, "end": 800, "text": "正文"},
                         {"start": 800, "end": 1000, "text": "。"}]}
        base = {"segments": [cue]}
        base["gap_remove"] = _build_gap_remove(base, scoped_item_ranges(cue, [0]))
        cleaned, _ = self.run_clean(base)
        self.assertEqual(cleaned["segments"][0]["items"][-1]["text"], "")
        self.assertEqual(project_cleanup_retained_segments(cleaned["segments"], cleaned["gap_remove"])[0]["text"], "正文")
        self.assertIn("正文", render_srt(cleaned))
        self.assertNotIn("啊", render_srt(cleaned))
        # Empty item text grants no permission to hide neighboring words.
        only_punctuation = {"segments": [cue]}
        only_punctuation["gap_remove"] = _build_gap_remove(only_punctuation, scoped_item_ranges(cue, [2]))
        output, _ = self.run_clean(only_punctuation)
        self.assertIn("啊", render_srt(output))
        self.assertIn("正文", render_srt(output))

    def test_empty_items_do_not_relax_mapping_or_timing_checks(self):
        cue = {"start": 0, "end": 1000, "text": "正文",
               "items": [{"start": 0, "end": 800, "text": "正文"},
                         {"start": 800, "end": 1000, "text": ""}]}
        self.assertEqual(len(reliable_cleanup_items(cue)), 2)
        for mutation in ({"start": 700}, {"end": 800}, {"end": 1001}, {"text": None}, {"start": 800.0}):
            with self.subTest(mutation=mutation):
                invalid = copy.deepcopy(cue)
                invalid["items"][1].update(mutation)
                self.assertEqual(reliable_cleanup_items(invalid), [])
        invalid = copy.deepcopy(cue)
        invalid["text"] = "缺码的正文"
        self.assertEqual(reliable_cleanup_items(invalid), [])

    def test_cleanup_precedes_user_replacements(self):
        project = {"segments": [{"start": 0, "end": 1000, "text": "你好，世界。"}]}
        self.save_input(project)
        result = run_fixed_process(FixedProcessRequest(
            self.source, None, OutputMode.JSON, (Replacement("  ", " / "),), clean_chinese_punctuation=True,
        ))
        self.assertEqual(read_project(result.project_path)["segments"][0]["text"], "你好 / 世界")

    def test_cleanup_then_replacement_keeps_empty_punctuation_items(self):
        items = [{"id": "a", "start": 0, "end": 200, "text": "你好，"},
                 {"id": "b", "start": 200, "end": 800, "text": "世界"},
                 {"id": "c", "start": 800, "end": 1000, "text": "。"}]
        self.save_input({"segments": [{"start": 0, "end": 1000, "text": "你好，世界。", "items": items}]})
        result = run_fixed_process(FixedProcessRequest(self.source, None, OutputMode.JSON,
            (Replacement("世界", "朋友"),), clean_chinese_punctuation=True))
        cue = read_project(result.project_path)["segments"][0]
        self.assertEqual(cue["text"], "你好  朋友")
        self.assertEqual([item["text"] for item in cue["items"]], ["你好  ", "朋友", ""])
        self.assertEqual([{key: value for key, value in item.items() if key != "text"} for item in cue["items"]],
                         [{key: value for key, value in item.items() if key != "text"} for item in items])

    @unittest.skipUnless(shutil.which("node"), "Node unavailable for browser/Python parity check")
    def test_browser_and_python_cleanup_match_unicode_and_newline_corpus(self):
        texts = ["甲。\n", "甲，\r\n", "甲。\u2028", "甲，\u2029", "甲。\n乙，。\t",
                 "甲。\u00a0", "cafe\u0301，👩‍💻。", "Hello, world.!?？！；，。 \t", "，。", "甲， 。 "]
        segments = [{"text": text, "items": [{"text": text[:1], "start": 0, "end": 100},
                     {"text": text[1:], "start": 100, "end": 200}]} for text in texts]
        source = """import fs from 'node:fs';
import { loadEditorModule } from './tests/helpers/editor-module-loader.mjs';
const context = { window: {} };
loadEditorModule(context, 'shared/editor-utils.js');
process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0, 'utf8')).map(
  (segment) => context.window.AsrEditorUtils.planChinesePunctuationCleanup(segment))));"""
        browser = subprocess.run([shutil.which("node"), "--input-type=module", "-e", source],
            cwd=Path(__file__).resolve().parents[1], input=json.dumps(segments), text=True,
            encoding="utf-8", capture_output=True, check=True, timeout=30)
        expected = json.loads(browser.stdout)
        project = {"segments": copy.deepcopy(segments)}
        _clean_chinese_punctuation(project, project["segments"])
        self.assertEqual(project["segments"], expected)

    def test_pipeline_flag_defaults_off_and_requires_true(self):
        for value in (None, False, "true", "false", 1, True):
            with self.subTest(value=value):
                step = next(step for step in normalize_plan({"steps": [
                    {"id": "replace", "cleanChinesePunctuation": value}
                ]})["steps"] if step["id"] == "replace")
                self.assertIs(step["cleanChinesePunctuation"], value is True)
        self.assertFalse(next(step for step in default_postprocess_plan()["steps"] if step["id"] == "replace")["cleanChinesePunctuation"])

    def test_pipeline_runs_cleanup_without_rules_and_persists_choice(self):
        self.save_input({"segments": [{"start": 0, "end": 1000, "text": "你好，世界。"}]})
        media = self.root / "source.wav"
        media.write_bytes(b"not read by fixed processing")
        srt = self.root / "input.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好，世界。\n", encoding="utf-8")
        plan = {"enabled": True, "steps": [{"id": "replace", "enabled": True, "cleanChinesePunctuation": True}]}
        result = run_postprocess_pipeline(plan, media_path=media, project_path=self.source, srt_path=srt,
                                         env_path=self.root / "settings", ffmpeg_path=None, cancel_event=Event())
        self.assertEqual(read_project(result.project_path)["segments"][0]["text"], "你好  世界")
        env_path = self.root / "settings"
        save_postprocess_plan(env_path, plan)
        restored = load_postprocess_config(postprocess_config_path(env_path))["plan"]
        self.assertTrue(next(step for step in restored["steps"] if step["id"] == "replace")["cleanChinesePunctuation"])

    def test_launcher_bridge_accepts_explicit_cleanup_without_rules(self):
        from maw.gui_web import LauncherApi

        self.save_input({"segments": [{"start": 0, "end": 1000, "text": "你好，世界。"}]})
        api = SimpleNamespace(_emit_postprocess_status=lambda *_args: None)
        result = LauncherApi.run_fixed_process(api, {
            "projectPath": str(self.source), "outputMode": "both", "replacements": [],
            "cleanChinesePunctuation": True,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(read_project(Path(result["projectPath"]))["segments"][0]["text"], "你好  世界")
