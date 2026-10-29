import unittest

from maw.speaker_identity import asr_palette_size, distinct_speaker_ids
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


if __name__ == "__main__":
    unittest.main()
