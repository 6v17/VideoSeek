import unittest

from ui.widgets.chunk_timeline import ChunkTimelineSegment, distribute_segment_widths, effective_timeline_duration


class ChunkTimelineLayoutTests(unittest.TestCase):
    def test_distribute_segment_widths_sums_to_usable(self):
        segments = [
            ChunkTimelineSegment(start_sec=0.0, end_sec=10.0),
            ChunkTimelineSegment(start_sec=10.0, end_sec=25.0),
            ChunkTimelineSegment(start_sec=25.0, end_sec=40.0),
        ]
        widths = distribute_segment_widths(segments, 240, duration_sec=40.0, min_segment_width=12)
        self.assertEqual(sum(widths), 240)
        self.assertTrue(all(width >= 12 for width in widths))

    def test_duration_ignores_longer_video_tail(self):
        segments = [
            ChunkTimelineSegment(start_sec=0.0, end_sec=30.0),
            ChunkTimelineSegment(start_sec=30.0, end_sec=60.0),
        ]
        self.assertEqual(effective_timeline_duration(segments, 3600.0), 60.0)

    def test_many_segments_keep_minimum_width_budget(self):
        segments = [
            ChunkTimelineSegment(start_sec=index * 2.0, end_sec=(index + 1) * 2.0)
            for index in range(120)
        ]
        widths = distribute_segment_widths(segments, 2400, duration_sec=240.0, min_segment_width=12)
        self.assertEqual(len(widths), 120)
        self.assertEqual(sum(widths), 2400)


if __name__ == "__main__":
    unittest.main()
