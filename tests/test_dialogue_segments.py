import unittest

from src.core.asr.dialogue_segments import merge_adjacent_transcripts


class MergeAdjacentTranscriptsTests(unittest.TestCase):
    def test_merges_nearby_chinese_chars_into_phrase(self):
        rows = [
            {"start": 1.0, "end": 1.2, "text": "你", "language": "zh"},
            {"start": 1.3, "end": 1.5, "text": "好", "language": "zh"},
            {"start": 1.55, "end": 1.9, "text": "世界", "language": "zh"},
            {"start": 5.0, "end": 5.4, "text": "再见", "language": "zh"},
        ]
        merged = merge_adjacent_transcripts(rows, max_gap_sec=0.65)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["text"], "你好世界")
        self.assertEqual(merged[0]["start"], 1.0)
        self.assertEqual(merged[0]["end"], 1.9)
        self.assertEqual(merged[1]["text"], "再见")

    def test_keeps_space_for_latin(self):
        rows = [
            {"start": 0.0, "end": 0.4, "text": "hello", "language": "en"},
            {"start": 0.5, "end": 0.9, "text": "world", "language": "en"},
        ]
        merged = merge_adjacent_transcripts(rows)
        self.assertEqual(merged[0]["text"], "hello world")

    def test_does_not_merge_across_large_gap(self):
        rows = [
            {"start": 0.0, "end": 0.4, "text": "甲", "language": "zh"},
            {"start": 3.0, "end": 3.4, "text": "乙", "language": "zh"},
        ]
        merged = merge_adjacent_transcripts(rows, max_gap_sec=0.65)
        self.assertEqual(len(merged), 2)


    def test_does_not_merge_different_speakers(self):
        rows = [
            {"start": 1.0, "end": 1.4, "text": "甲", "language": "zh", "speaker": "柜台职员"},
            {"start": 1.5, "end": 1.9, "text": "乙", "language": "zh", "speaker": "红衣女人"},
        ]
        merged = merge_adjacent_transcripts(rows, max_gap_sec=0.65)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["speaker"], "柜台职员")

    def test_merges_same_speaker(self):
        rows = [
            {"start": 1.0, "end": 1.4, "text": "你", "language": "zh", "speaker": "红衣女人"},
            {"start": 1.5, "end": 1.9, "text": "好", "language": "zh", "speaker": "红衣女人"},
        ]
        merged = merge_adjacent_transcripts(rows, max_gap_sec=0.65)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["text"], "你好")
        self.assertEqual(merged[0]["speaker"], "红衣女人")


if __name__ == "__main__":
    unittest.main()
