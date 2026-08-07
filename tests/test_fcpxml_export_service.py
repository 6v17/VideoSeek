import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from src.services.fcpxml_export_service import (
    build_fcpxml_document,
    export_shot_list_fcpxml,
    fcpxml_time,
    media_path_to_file_url,
    _parse_smpte_timecode,
)
from src.services.shot_list_service import ShotListItem


def _probe(
    duration=60.0,
    fps=25.0,
    width=1920,
    height=1080,
    tc_start=0.0,
):
    return {
        "duration": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "tc_start": tc_start,
    }


class FcpxmlExportServiceTests(unittest.TestCase):
    def test_fcpxml_time_25fps(self):
        # Apple-style: 25 frames at 1/25s → 25/25s
        self.assertEqual(fcpxml_time(1.0, 25.0), "25/25s")
        self.assertEqual(fcpxml_time(0.0, 25.0), "0s")
        self.assertEqual(fcpxml_time(10.0, 25.0), "250/25s")

    def test_fcpxml_time_2997(self):
        self.assertEqual(fcpxml_time(10.0, 29.97), "300300/30000s")

    def test_parse_smpte_timecode(self):
        self.assertEqual(_parse_smpte_timecode("01:00:00:00", 25.0), 3600.0)
        self.assertAlmostEqual(_parse_smpte_timecode("00:00:10:12", 25.0), 10.48)

    def test_media_path_to_file_url_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clip.mp4")
            with open(path, "wb") as handle:
                handle.write(b"x")
            url = media_path_to_file_url(path)
            self.assertTrue(url.startswith("file:///"))
            self.assertIn("clip.mp4", url)

    def test_premiere_pathurl_windows_drive(self):
        from src.services.fcpxml_export_service import media_path_to_premiere_pathurl

        if os.name != "nt":
            self.skipTest("Windows pathurl format")
        url = media_path_to_premiere_pathurl(r"E:\素材\clip.mp4")
        self.assertTrue(url.startswith("file://localhost/E:/"), url)
        self.assertNotIn("E%3a", url.lower().replace("e%3a", "E%3a"))
        self.assertFalse(url.startswith("file:///E:"), url)
        self.assertIn("clip.mp4", url)

    def test_build_document_uses_native_fps_for_source_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "ep01.mp4")
            with open(path_a, "wb") as handle:
                handle.write(b"fake")
            items = [ShotListItem("a", path_a, 10.0, 15.0, 0.9)]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(fps=30.0),
            ):
                xml_text, meta = build_fcpxml_document(items, project_name="Demo")
            self.assertEqual(meta["exported_count"], 1)
            # Source in-point must use media fps (30), not a default 25 timeline.
            self.assertIn('start="300/30s"', xml_text)
            self.assertIn('duration="150/30s"', xml_text)
            self.assertIn("FFVideoFormat1080p30", xml_text)
            root = ET.fromstring(xml_text.split("?>", 1)[-1].replace("<!DOCTYPE fcpxml>", ""))
            assets = root.findall(".//asset")
            clips = root.findall(".//asset-clip")
            self.assertEqual(len(assets), 1)
            self.assertEqual(len(clips), 1)
            self.assertTrue(assets[0].get("src", "").startswith("file://"))
            # asset format should not be the sequence format r1
            self.assertNotEqual(assets[0].get("format"), "r1")
            self.assertEqual(clips[0].get("format"), assets[0].get("format"))

    def test_frame_hit_pads_six_seconds_at_23976(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "aot24.mp4")
            with open(path_a, "wb") as handle:
                handle.write(b"fake")
            # Shot-list UI shows 21:31 → 1291s (frame-level hit) → export 1288..1294.
            items = [ShotListItem("a", path_a, 1291.0, 1291.0, 0.9, match_kind="frame")]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(duration=1469.63, fps=23.976, width=1280, height=720),
            ):
                xml_text, _meta = build_fcpxml_document(items, project_name="AOT")
            self.assertIn("FFVideoFormat720p2398", xml_text)
            self.assertIn('frameDuration="1001/24000s"', xml_text)
            # 1288s → round(1288*24000/1001)=30881 frames → 30881*1001/24000
            self.assertIn('start="30911881/24000s"', xml_text)
            # 6s duration at 23.976 → 144 frames
            self.assertIn('duration="144144/24000s"', xml_text)

    def test_segment_hit_keeps_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "ep.mp4")
            with open(path_a, "wb") as handle:
                handle.write(b"fake")
            items = [ShotListItem("a", path_a, 10.0, 18.0, 0.9, match_kind="clip")]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(fps=25.0),
            ):
                xml_text, _meta = build_fcpxml_document(items)
            self.assertIn('start="250/25s"', xml_text)
            self.assertIn('duration="200/25s"', xml_text)

    def test_fcp7_xml_for_premiere(self):
        from src.services.fcpxml_export_service import build_fcp7_xml_document, export_shot_list_nle_xml

        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "ep.mp4")
            with open(path_a, "wb") as handle:
                handle.write(b"fake")
            items = [ShotListItem("a", path_a, 10.0, 15.0, 0.9, match_kind="clip")]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(fps=25.0),
            ):
                xml_text, meta = build_fcp7_xml_document(items, project_name="Demo")
                out = os.path.join(tmp, "shot_list.xml")
                result = export_shot_list_nle_xml(items, write_path=out)
            self.assertEqual(meta["format"], "fcp7_xml")
            self.assertIn("<xmeml version=\"5\">", xml_text)
            self.assertIn("<pathurl>file://localhost/", xml_text)
            self.assertIn("<in>250</in>", xml_text)
            self.assertIn("<out>375</out>", xml_text)
            # 5s clip on 25fps sequence → timeline end-start = 125
            self.assertIn("<start>0</start>", xml_text)
            self.assertIn("<end>125</end>", xml_text)
            self.assertEqual(result["format"], "fcp7_xml")
            self.assertTrue(os.path.isfile(out))

    def test_fcp7_mixed_fps_timeline_uses_sequence_timebase(self):
        from src.services.fcpxml_export_service import build_fcp7_xml_document

        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "a.mp4")
            path_b = os.path.join(tmp, "b.mp4")
            for path in (path_a, path_b):
                with open(path, "wb") as handle:
                    handle.write(b"fake")
            items = [
                ShotListItem("a", path_a, 10.0, 16.0, 0.9, match_kind="clip"),
                ShotListItem("b", path_b, 20.0, 26.0, 0.8, match_kind="clip"),
            ]

            def _fake_probe(path):
                if path.endswith("a.mp4"):
                    return _probe(fps=23.976, width=1280, height=720)
                return _probe(fps=29.97, width=1920, height=1080)

            with patch("src.services.fcpxml_export_service._probe_media", side_effect=_fake_probe):
                xml_text, meta = build_fcp7_xml_document(items)
            # Sequence follows first clip (23.976 → timebase 24 NTSC).
            self.assertEqual(round(float(meta["fps"]), 3), 23.976)
            # Second clip is 6s → 144 sequence frames at 23.976, not 180 at 29.97.
            self.assertIn("<start>144</start>", xml_text)
            self.assertIn("<end>288</end>", xml_text)
            # Premiere reads clipitem in/out in sequence timebase on mixed-fps timelines.
            # 20s @23.976 → 480 frames (not 599 @29.97).
            self.assertIn("<in>480</in>", xml_text)
            self.assertIn("<out>624</out>", xml_text)
            self.assertNotIn("<in>599</in>", xml_text)
            # File still keeps native 29.97 rate for the 30fps media.
            self.assertIn("<timebase>30</timebase>", xml_text)
            # Resolve needs pathurl on audio clipitems + A/V link blocks.
            self.assertIn("<linkclipref>clipitem-1</linkclipref>", xml_text)
            self.assertIn("<linkclipref>audio-clipitem-1</linkclipref>", xml_text)
            self.assertIn("<linkclipref>audio-clipitem-1b</linkclipref>", xml_text)
            # Audio tracks use distinct file ids with full pathurl (not bare file-1 refs).
            self.assertIn('id="file-1-a1"', xml_text)
            self.assertIn('id="file-2-a1"', xml_text)
            self.assertGreaterEqual(xml_text.count("<pathurl>"), 6)

    def test_fcp7_timeline_frames_do_not_overlap(self):
        from src.services.fcpxml_export_service import build_fcp7_xml_document

        with tempfile.TemporaryDirectory() as tmp:
            paths = [os.path.join(tmp, f"c{i}.mp4") for i in range(5)]
            for path in paths:
                with open(path, "wb") as handle:
                    handle.write(b"fake")
            # Five 6s frame-hits → cumulative seconds 0,6,12,18,24 where frames(24)≠frames(18)+frames(6)
            items = [
                ShotListItem(f"c{i}", paths[i], 10.0 + i, 10.0 + i, 0.9, match_kind="frame")
                for i in range(5)
            ]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(duration=120.0, fps=23.976),
            ):
                xml_text, _meta = build_fcp7_xml_document(items)
            starts = [int(x) for x in re.findall(r"<clipitem id=\"clipitem-\d+\">.*?<start>(\d+)</start>", xml_text, flags=re.S)]
            ends = [int(x) for x in re.findall(r"<clipitem id=\"clipitem-\d+\">.*?<end>(\d+)</end>", xml_text, flags=re.S)]
            self.assertEqual(len(starts), 5)
            for prev_end, start in zip(ends, starts[1:]):
                self.assertEqual(prev_end, start)

    def test_frame_hit_clamps_at_media_start(self):
        from src.services.fcpxml_export_service import _clip_span_seconds

        item = ShotListItem("a", "x.mp4", 1.0, 1.0, 0.9, match_kind="frame")
        start, duration = _clip_span_seconds(item, 25.0, media_duration=100.0)
        self.assertEqual(start, 0.0)
        self.assertEqual(duration, 6.0)  # shift window to keep ±3s length when possible

    def test_frame_hit_clamps_at_media_end(self):
        from src.services.fcpxml_export_service import _clip_span_seconds

        item = ShotListItem("a", "x.mp4", 98.0, 98.0, 0.9, match_kind="frame")
        start, duration = _clip_span_seconds(item, 25.0, media_duration=100.0)
        self.assertEqual(start, 94.0)
        self.assertEqual(duration, 6.0)

    def test_timecode_offset_applied_to_source_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "tc.mp4")
            with open(path_a, "wb") as handle:
                handle.write(b"fake")
            items = [ShotListItem("a", path_a, 10.0, 12.0, 0.9)]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(fps=25.0, tc_start=3600.0),
            ):
                xml_text, _meta = build_fcpxml_document(items, project_name="TC")
            # asset starts at 01:00:00:00; clip in-point = 01:00:10:00
            self.assertIn('start="90000/25s"', xml_text)  # asset
            self.assertIn('start="90250/25s"', xml_text)  # clip = 3610s

    def test_export_skips_remote_and_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, "local.mp4")
            with open(local, "wb") as handle:
                handle.write(b"fake")
            out = os.path.join(tmp, "out.fcpxml")
            items = [
                ShotListItem("r", "http://host/play/1", 1.0, 2.0, 0.5),
                ShotListItem("l", local, 5.0, 8.0, 0.7),
            ]
            with patch(
                "src.services.fcpxml_export_service._probe_media",
                return_value=_probe(duration=30.0, fps=25.0),
            ):
                result = export_shot_list_fcpxml(items, write_path=out, project_name="Basket")
            self.assertTrue(result["ok"])
            self.assertEqual(result["exported_count"], 1)
            self.assertEqual(result["skipped_remote"], 1)
            self.assertTrue(os.path.isfile(out))
            text = open(out, encoding="utf-8").read()
            self.assertIn("skipped_remote=1", text)

    def test_export_all_remote_raises(self):
        items = [ShotListItem("r", "https://host/a.mp4", 0.0, 1.0, 0.1)]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.fcpxml")
            with self.assertRaises(ValueError):
                export_shot_list_fcpxml(items, write_path=out)


if __name__ == "__main__":
    unittest.main()
