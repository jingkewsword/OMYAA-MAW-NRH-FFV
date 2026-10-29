import unittest

from maw.speaker_identity import asr_palette_size, distinct_speaker_ids, prepare_asr_speaker_segments
from maw.speaker import apply_project_speaker_colors, speaker_color_summary


class SpeakerIdentityTests(unittest.TestCase):
    def test_counts_distinct_nonempty_source_ids_in_first_seen_order(self):
        segments = [{"speaker": value} for value in ("6", "1", "6", "", "  ", None, "0")]
        segments.append({})
        self.assertEqual(distinct_speaker_ids(segments), ["6", "1", "0"])

    def test_palette_expands_by_count_and_never_shrinks_automatically(self):
        for count in (0, 1, 5, 6, 9, 10):
            with self.subTest(count=count):
                segments = [{"speaker": str(index)} for index in range(count)]
                self.assertEqual(asr_palette_size(segments, current_size=5), 9 if count > 5 else 5)
                self.assertEqual(asr_palette_size(segments, current_size=9), 9)

    def test_palette_count_does_not_mutate_source_data(self):
        segments = [{"speaker": "1", "items": [{"text": "Hi", "speaker": "1", "start": 0, "end": 5}]}]
        before = repr(segments)
        self.assertEqual(asr_palette_size(segments, current_size=5), 5)
        self.assertEqual(repr(segments), before)

    def test_asr_summary_uses_valid_distinct_identities(self):
        segments = [{"speaker": value} for value in ("6", "1", "6", "", "  ", None)]
        summary = speaker_color_summary(segments)
        self.assertEqual(summary["speakers"], ["6", "1"])
        self.assertEqual(summary["colored_segments"], 3)
        self.assertFalse(summary["overflow"])

    def test_blank_source_identity_is_not_assigned_a_color_group(self):
        segments = [{"speaker": "  "}, {"speaker": "6"}]
        project = {"tracks": [{"id": "main", "role": "main", "segments": segments}],
                   "subtitle_groups": {"next_id": 1, "color": [], "sticker": []}}
        self.assertEqual(apply_project_speaker_colors(project)["speakers"], ["6"])
        self.assertNotIn("color_group_id", segments[0])
        self.assertIn("color_group_id", segments[1])

    def test_cleaned_segments_keep_word_timing_but_only_store_segment_identity(self):
        source = [{"id": "cue-1", "text": "你好", "start": 0, "end": 200,
                   "speaker": "provider-1", "items": [
                       {"text": "你", "start": 0, "end": 100, "speaker": "provider-1"},
                       {"text": "好", "start": 100, "end": 200, "speaker": "provider-1"}]}]
        original = repr(source)
        result = prepare_asr_speaker_segments(source, {"provider-1": "spk-1"})
        self.assertEqual(result[0]["speaker"], "spk-1")
        self.assertEqual(result[0]["items"], [
            {"text": "你", "start": 0, "end": 100}, {"text": "好", "start": 100, "end": 200}])
        self.assertEqual(repr(source), original)

    def test_mixed_or_unmapped_identity_is_not_silently_discarded(self):
        mixed = [{"speaker": "one", "items": [{"speaker": "one"}, {"speaker": "two"}]}]
        with self.assertRaisesRegex(ValueError, "multiple source speakers"):
            prepare_asr_speaker_segments(mixed, {"one": "spk-1", "two": "spk-2"})
        with self.assertRaisesRegex(ValueError, "unmapped source speaker"):
            prepare_asr_speaker_segments([{"speaker": "one"}], {})

    def test_word_identity_can_supply_unambiguous_segment_identity(self):
        source = [{"items": [{"text": "Hi", "speaker": "one"}, {"text": "!"}]}]
        result = prepare_asr_speaker_segments(source, {"one": "spk-1"})
        self.assertEqual(result[0]["speaker"], "spk-1")
        self.assertNotIn("speaker", result[0]["items"][0])


if __name__ == "__main__":
    unittest.main()
