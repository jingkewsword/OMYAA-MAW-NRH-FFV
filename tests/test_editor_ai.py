from maw.project_tracks import get_main_track
import threading
import time
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from maw.editor_ai import resegment_selection, translate_selection, validate_selection
from maw.editor_ai_jobs import EditorAiJobs


class EditorAiSelectionTests(unittest.TestCase):
    def setUp(self):
        self.cues = validate_selection([
            {"id": "one", "text": "你好", "start": 0, "end": 600,
             "items": [{"text": "你", "start": 0, "end": 300},
                       {"text": "好", "start": 300, "end": 600}]},
            {"id": "two", "text": "朋友", "start": 700, "end": 1300,
             "items": [{"text": "朋友", "start": 700, "end": 1300}]},
        ])

    def test_translation_accepts_only_exact_one_to_one_order(self):
        def complete(_prompt, rows):
            self.assertEqual([row["id"] for row in rows], ["c0001", "c0002"])
            return {"groups": [{"id": "c0001", "text": "Hello"},
                               {"id": "c0002", "text": "friend"}]}
        self.assertEqual(translate_selection(self.cues, "en", complete),
                         [{"id": "one", "text": "Hello"}, {"id": "two", "text": "friend"}])
        with self.assertRaises(ValueError):
            translate_selection(self.cues, "en", lambda *_: {"groups": [
                {"id": "c0002", "text": "friend"}, {"id": "c0001", "text": "Hello"}]})

    def test_resegment_requires_full_valid_items_and_ordered_boundaries(self):
        def complete(_prompt, rows):
            self.assertEqual(rows[0]["items"][0]["id"], "c0001a0001")
            return {"draft": "[c0001a0002]\n[c0002a0001]"}
        self.assertEqual(resegment_selection(self.cues, complete),
                         [["c0001a0001", "c0001a0002"], ["c0002a0001"]])
        with self.assertRaises(ValueError):
            resegment_selection(self.cues, lambda *_: {"draft": "[c0001a0001]"})

    def test_zero_width_punctuation_is_not_downgraded_into_a_candidate(self):
        cue = validate_selection([{"id": "a", "text": "好。", "start": 0, "end": 500,
            "items": [{"text": "好", "start": 0, "end": 500},
                      {"text": "。", "start": 500, "end": 500}]}])
        with self.assertRaises(ValueError):
            resegment_selection(cue, lambda *_: self.fail("should not call the model"))

    def test_resegment_enforces_maximum_without_cutting_items(self):
        cues = validate_selection([{"id": "a", "text": "甲乙丙丁", "start": 0, "end": 400,
            "items": [{"text": ch, "start": i * 100, "end": (i + 1) * 100}
                      for i, ch in enumerate("甲乙丙丁")]}])
        result = resegment_selection(cues, lambda *_: {"draft": "[c0001a0004]"}, max_chars=2)
        self.assertEqual([len(group) for group in result], [2, 2])

    def test_selection_rejects_duplicate_ids_and_overlaps(self):
        with self.assertRaises(ValueError):
            validate_selection([{ "id": "x", "text": "a", "start": 0, "end": 100},
                                { "id": "x", "text": "b", "start": 100, "end": 200}])
        with self.assertRaises(ValueError):
            validate_selection([{ "id": "x", "text": "a", "start": 0, "end": 100},
                                { "id": "y", "text": "b", "start": 90, "end": 200}])

    def test_cancelled_job_does_not_release_slot_until_worker_finishes(self):
        jobs = EditorAiJobs()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(jobs.close)
        self.addCleanup(release.set)
        def compute(*_args):
            entered.set()
            release.wait(2)
            return {"translations": []}
        payload = {"operation": "translate", "cues": self.cues}
        with mock.patch.object(EditorAiJobs, "_compute", side_effect=compute):
            job = jobs.start(payload, (1, "media"), None)
            self.assertTrue(entered.wait(1))
            self.assertEqual(jobs.status(job["id"], (1, "media"), cancel=True)["state"], "cancelled")
            with self.assertRaises(ValueError):
                jobs.start(payload, (1, "media"), None)
            release.set()
            for _ in range(100):
                with jobs._lock:
                    if not jobs._running:
                        break
                time.sleep(0.01)
            self.assertEqual(jobs.status(job["id"], (1, "media"))["state"], "cancelled")
            with self.assertRaises(ValueError):
                jobs.status(job["id"], (2, "other"))

    def test_alignment_accepts_only_selected_validated_results(self):
        def worker(**kwargs):
            from maw.postprocess_io import read_project
            project = read_project(Path(kwargs["project_path"]))
            self.assertEqual([cue["id"] for cue in get_main_track(project)["segments"]], ["one", "two"])
            get_main_track(project)["segments"][0]["items"] = [{"text": "你好", "start": 0, "end": 600}]
            output = Path(kwargs["output_directory"]) / "result.mosp"
            output.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
            return {"artifact": {"projectPath": str(output)}, "report": {"alignedSegments": 2}}
        with mock.patch("maw.local_runtime.run_timestamp_alignment_in_runtime", side_effect=worker), \
             mock.patch("maw.gui_config.effective_config", return_value=SimpleNamespace(model_cache_root="")):
            result = EditorAiJobs._compute({"operation": "align", "model": "qwen3-forced-aligner-0.6b",
                                            "mode": "generate"}, self.cues, Path("fixture.wav"), threading.Event())
        self.assertEqual([row["id"] for row in result["aligned"]], ["one"])

    def test_alignment_input_without_items_can_be_loaded_by_worker(self):
        def worker(**kwargs):
            from maw.postprocess_io import read_project
            project = read_project(Path(kwargs["project_path"]))
            get_main_track(project)["segments"][0]["items"] = [{"text": "hi", "start": 0, "end": 100}]
            output = Path(kwargs["output_directory"]) / "result.mosp"
            output.write_text(json.dumps(project), encoding="utf-8")
            return {"artifact": {"projectPath": str(output)}, "report": {}}
        source = validate_selection([{"id": "a", "start": 0, "end": 100, "text": "hi"}])
        with mock.patch("maw.local_runtime.run_timestamp_alignment_in_runtime", side_effect=worker), \
             mock.patch("maw.gui_config.effective_config", return_value=SimpleNamespace(model_cache_root="")):
            result = EditorAiJobs._compute({"operation": "align", "model": "qwen3-forced-aligner-0.6b", "mode": "fill"},
                                           source, Path("fixture.wav"), threading.Event())
        self.assertEqual(result["aligned"][0]["items"][0]["text"], "hi")

    def test_fill_protects_partial_and_zero_width_items_before_worker(self):
        source = validate_selection([
            {"id": "partial", "start": 0, "end": 500, "text": "AB", "items": [{"text": "B", "start": 300, "end": 500}]},
            {"id": "zero", "start": 600, "end": 1000, "text": "好。", "items": [{"text": "好", "start": 600, "end": 1000}, {"text": "。", "start": 1000, "end": 1000}]},
            {"id": "empty", "start": 1100, "end": 1200, "text": "hi"},
        ])
        def worker(**kwargs):
            from maw.postprocess_io import read_project
            project = read_project(Path(kwargs["project_path"]))
            self.assertEqual([cue["id"] for cue in get_main_track(project)["segments"]], ["empty"])
            get_main_track(project)["segments"][0]["items"] = [{"text": "hi", "start": 1100, "end": 1200}]
            output = Path(kwargs["output_directory"]) / "result.mosp"
            output.write_text(json.dumps(project), encoding="utf-8")
            return {"artifact": {"projectPath": str(output)}, "report": {"skippedSegments": 0}}
        with mock.patch("maw.local_runtime.run_timestamp_alignment_in_runtime", side_effect=worker), \
             mock.patch("maw.gui_config.effective_config", return_value=SimpleNamespace(model_cache_root="")):
            result = EditorAiJobs._compute({"operation": "align", "model": "qwen3-forced-aligner-0.6b", "mode": "fill"}, source, Path("fixture.wav"), threading.Event())
        self.assertEqual([cue["id"] for cue in result["aligned"]], ["empty"])
        self.assertEqual(result["report"]["skippedSegments"], 2)


if __name__ == "__main__":
    unittest.main()
