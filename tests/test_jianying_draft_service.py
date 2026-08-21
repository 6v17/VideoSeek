"""Tests for Jianying draft helpers used by shot-list export."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services import jianying_draft_service as jy


def _resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in (
        r"E:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ):
        if os.path.isfile(candidate):
            return candidate
    return ""


class JianyingDraftServiceTests(unittest.TestCase):
    def test_list_drafts_filters_real_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "假期混剪"
            real.mkdir()
            (real / "draft_content.json").write_text("{}", encoding="utf-8")
            junk = root / "not_a_draft"
            junk.mkdir()
            encrypted = root / "encrypted"
            encrypted.mkdir()
            (encrypted / "draft_content.json").write_text("aH1cjgh88FCtNotJson", encoding="utf-8")
            items = jy.list_jianying_drafts(str(root))
            by_name = {item.name: item for item in items}
            self.assertIn("假期混剪", by_name)
            self.assertTrue(by_name["假期混剪"].readable)
            self.assertIn("encrypted", by_name)
            self.assertFalse(by_name["encrypted"].readable)

    def test_resolve_uses_config_when_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = jy.resolve_jianying_drafts_dir(config={"jianying_drafts_dir": tmp})
            self.assertEqual(os.path.normcase(path), os.path.normcase(tmp))

    def test_normalize_frame_hit_expands_to_about_six_seconds(self):
        start, duration = jy._normalize_clip_span(
            start_sec=10.0,
            end_sec=10.0,
            match_kind="frame",
            media_path="",
        )
        self.assertAlmostEqual(start, 7.0, places=2)
        self.assertAlmostEqual(duration, 6.0, places=2)

    def test_normalize_keeps_real_segment_range(self):
        start, duration = jy._normalize_clip_span(
            start_sec=2.0,
            end_sec=8.5,
            match_kind="clip",
            media_path="",
        )
        self.assertAlmostEqual(start, 2.0, places=2)
        self.assertAlmostEqual(duration, 6.5, places=2)

    @patch("src.services.jianying_draft_service.is_jianying_draft_support_available", return_value=True)
    def test_append_requires_existing_media(self, _mock_avail):
        with self.assertRaises(jy.JianyingDraftError):
            jy.append_clip_to_jianying_draft(
                drafts_dir="D:/missing",
                draft_name="demo",
                video_path="D:/nope.mp4",
                start_sec=1.0,
                end_sec=2.0,
            )

    @patch("src.services.jianying_draft_service.is_jianying_draft_support_available", return_value=True)
    @patch("src.services.jianying_draft_service._append_clip_onto_script")
    def test_export_skips_missing_and_counts_ok(self, mock_append, _mock_avail):
        with tempfile.TemporaryDirectory() as tmp:
            items = [
                SimpleNamespace(
                    video_path="https://example.com/a.mp4",
                    start_sec=1.0,
                    end_sec=2.0,
                    match_kind="frame",
                ),
                SimpleNamespace(
                    video_path=os.path.join(tmp, "missing.mp4"),
                    start_sec=1.0,
                    end_sec=2.0,
                    match_kind="frame",
                ),
            ]
            with self.assertRaises(jy.JianyingDraftError):
                jy.export_shot_list_to_jianying_draft(items, drafts_dir=tmp)
            mock_append.assert_not_called()

    def test_export_keeps_all_clips_on_one_track(self):
        if not jy.is_jianying_draft_support_available():
            self.skipTest("pyJianYingDraft not installed")

        import json
        import subprocess

        ffmpeg = _resolve_ffmpeg()
        if not ffmpeg:
            self.skipTest("ffmpeg unavailable for sample media")

        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "sample.mp4")
            try:
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=320x240:d=12",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=44100:cl=stereo",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        media,
                    ],
                    check=True,
                    capture_output=True,
                )
            except (OSError, subprocess.CalledProcessError):
                self.skipTest("ffmpeg failed to create sample media")

            items = [
                SimpleNamespace(video_path=media, start_sec=1.0, end_sec=3.0, match_kind="clip"),
                SimpleNamespace(video_path=media, start_sec=4.0, end_sec=7.0, match_kind="clip"),
                SimpleNamespace(video_path=media, start_sec=8.0, end_sec=8.0, match_kind="frame"),
            ]
            payload = jy.export_shot_list_to_jianying_draft(
                items,
                drafts_dir=tmp,
                draft_name="layout-test",
            )
            content_path = os.path.join(payload["draft_path"], "draft_content.json")
            with open(content_path, encoding="utf-8") as handle:
                data = json.load(handle)
            video_tracks = [track for track in data.get("tracks", []) if track.get("type") == "video"]
            self.assertEqual(len(video_tracks), 1, video_tracks)
            segments = video_tracks[0].get("segments") or []
            self.assertEqual(len(segments), 3)
            starts = [int(seg["target_timerange"]["start"]) for seg in segments]
            durations = [int(seg["target_timerange"]["duration"]) for seg in segments]
            self.assertEqual(starts[0], 0)
            self.assertEqual(starts[1], starts[0] + durations[0])
            self.assertEqual(starts[2], starts[1] + durations[1])


if __name__ == "__main__":
    unittest.main()
