import unittest

from ui.widgets.chunk_timeline import (
    ChunkTimelineSegment,
    distribute_segment_widths,
    effective_timeline_duration,
    layout_segments_sequential,
)


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

    def test_sequential_layout_uses_uniform_gap_between_neighbors(self):
        segments = [
            ChunkTimelineSegment(start_sec=0.0, end_sec=2.0),
            ChunkTimelineSegment(start_sec=120.0, end_sec=122.0),
            ChunkTimelineSegment(start_sec=240.0, end_sec=242.0),
        ]
        placements, _total_width = layout_segments_sequential(
            segments,
            duration_sec=300.0,
            min_segment_width=14,
            segment_gap=2,
        )
        gaps = [placements[1][0] - (placements[0][0] + placements[0][1]), placements[2][0] - (placements[1][0] + placements[1][1])]
        self.assertEqual(gaps[0], gaps[1])
        self.assertEqual(gaps[0], 2)

    def test_sequential_layout_keeps_minimum_width_without_overlap(self):
        segments = [
            ChunkTimelineSegment(start_sec=float(index), end_sec=float(index + 1))
            for index in range(40)
        ]
        placements, total_width = layout_segments_sequential(
            segments,
            duration_sec=1469.0,
            min_segment_width=14,
            segment_gap=2,
            pixels_per_second=6.0,
        )
        self.assertEqual(len(placements), 40)
        order = sorted(range(40), key=lambda index: segments[index].start_sec)
        previous_right = -999
        for index in order:
            left, width = placements[index]
            self.assertGreaterEqual(width, 14)
            self.assertGreaterEqual(left, previous_right)
            previous_right = left + width
        self.assertGreaterEqual(total_width, previous_right)

    def test_sequential_layout_preserves_segment_index_order(self):
        segments = [
            ChunkTimelineSegment(start_sec=0.0, end_sec=2.0),
            ChunkTimelineSegment(start_sec=100.0, end_sec=102.0),
        ]
        placements, _total_width = layout_segments_sequential(
            segments,
            duration_sec=200.0,
            min_segment_width=14,
            segment_gap=2,
        )
        self.assertLess(placements[0][0], placements[1][0])

    def test_sequential_layout_expands_to_fill_target_width(self):
        segments = [
            ChunkTimelineSegment(start_sec=float(index), end_sec=float(index + 1))
            for index in range(8)
        ]
        target = 640
        placements, total_width = layout_segments_sequential(
            segments,
            duration_sec=60.0,
            min_segment_width=14,
            segment_gap=2,
            target_inner_width=target,
        )
        self.assertEqual(total_width, target)
        right_edge = max(left + width for left, width in placements)
        self.assertEqual(right_edge, target)
        self.assertTrue(all(width >= 14 for _left, width in placements))


if __name__ == "__main__":
    unittest.main()
