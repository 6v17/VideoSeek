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
        r"D:\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe",
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

    def test_recap_spans_keep_real_duration(self):
        spans = jy.recap_export_clip_spans(
            [
                {"src_in": 10.0, "src_out": 16.0, "tl_in": 0.0, "tl_out": 6.0, "vo": "第一句"},
                {"src_in": 20.0, "src_out": 20.02, "tl_in": 6.0, "tl_out": 6.02, "vo": "太短"},
                {"src_in": 30.0, "src_out": 38.0, "vo": "第二句"},
            ]
        )
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[0]["src_in"], 10.0)
        self.assertAlmostEqual(spans[0]["duration"], 6.0)
        self.assertEqual(spans[0]["vo"], "第一句")
        self.assertAlmostEqual(spans[1]["src_in"], 30.0)
        self.assertAlmostEqual(spans[1]["duration"], 8.0)

    def test_recap_captions_extend_empty_vo(self):
        vo = "一二三四五" * 8
        captions = jy.merge_recap_captions(
            [
                {"duration": 4.0, "vo": vo},
                {"duration": 4.0, "vo": ""},
                {"duration": 4.0, "vo": "转折"},
            ]
        )
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["text"], vo)
        self.assertAlmostEqual(captions[0]["start"], 0.0)
        self.assertAlmostEqual(captions[0]["duration"], 8.0)
        self.assertEqual(captions[1]["text"], "转折")
        self.assertAlmostEqual(captions[1]["start"], 8.0)
        self.assertAlmostEqual(captions[1]["duration"], 4.0)

    def test_recap_captions_skip_full_shot_empty_follow(self):
        captions = jy.merge_recap_captions(
            [
                {"duration": 6.0, "vo": "开场"},
                {"duration": 3.0, "vo": ""},
                {"duration": 4.0, "vo": "转折"},
            ]
        )
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["text"], "开场")
        self.assertAlmostEqual(captions[0]["duration"], 6.0)
        self.assertAlmostEqual(captions[1]["start"], 9.0)
        self.assertAlmostEqual(captions[1]["duration"], 4.0)

    def test_safe_draft_slug_strips_illegal_chars(self):
        self.assertEqual(jy._safe_draft_slug('海贼王/终章:上', fallback="解说"), "海贼王_终章_上")
        self.assertEqual(jy._safe_draft_slug("   ", fallback="解说"), "解说")

    @patch("src.services.jianying_draft_service.is_jianying_draft_support_available", return_value=True)
    def test_export_recap_requires_clips(self, _mock_avail):
        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "clip.mp4")
            Path(media).write_bytes(b"x")
            with self.assertRaises(jy.JianyingDraftError):
                jy.export_recap_to_jianying_draft([], video_path=media, drafts_dir=tmp)

    @patch("src.services.jianying_draft_service.is_jianying_draft_support_available", return_value=True)
    def test_export_recap_requires_media(self, _mock_avail):
        with self.assertRaises(jy.JianyingDraftError):
            jy.export_recap_to_jianying_draft(
                [{"src_in": 1.0, "src_out": 5.0, "vo": "hi"}],
                video_path="D:/nope.mp4",
                drafts_dir="D:/missing",
            )

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

    def test_export_recap_lays_clips_and_captions(self):
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

            clips = [
                {"src_in": 1.0, "src_out": 3.0, "tl_in": 0.0, "tl_out": 2.0, "vo": "开场旁白"},
                {"src_in": 4.0, "src_out": 7.0, "tl_in": 2.0, "tl_out": 5.0, "vo": ""},
                {"src_in": 8.0, "src_out": 10.0, "tl_in": 5.0, "tl_out": 7.0, "vo": "第二句"},
            ]
            payload = jy.export_recap_to_jianying_draft(
                clips,
                video_path=media,
                drafts_dir=tmp,
                draft_name="recap-test",
                title="测试解说",
                fps=30,
                width=320,
                height=240,
            )
            content_path = os.path.join(payload["draft_path"], "draft_content.json")
            with open(content_path, encoding="utf-8") as handle:
                data = json.load(handle)
            video_tracks = [track for track in data.get("tracks", []) if track.get("type") == "video"]
            text_tracks = [track for track in data.get("tracks", []) if track.get("type") == "text"]
            self.assertEqual(len(video_tracks), 1, video_tracks)
            self.assertEqual(len(text_tracks), 1, text_tracks)
            video_segs = video_tracks[0].get("segments") or []
            text_segs = text_tracks[0].get("segments") or []
            self.assertEqual(len(video_segs), 3)
            self.assertEqual(len(text_segs), 2)
            self.assertEqual(payload.get("caption_count"), 2)
            durations = [int(seg["target_timerange"]["duration"]) for seg in video_segs]
            self.assertAlmostEqual(durations[0] / 1_000_000, 2.0, places=2)
            self.assertAlmostEqual(durations[1] / 1_000_000, 3.0, places=2)
            self.assertAlmostEqual(durations[2] / 1_000_000, 2.0, places=2)
            caption_durs = [int(seg["target_timerange"]["duration"]) for seg in text_segs]
            self.assertAlmostEqual(caption_durs[0] / 1_000_000, 2.0, places=2)
            self.assertAlmostEqual(caption_durs[1] / 1_000_000, 2.0, places=2)

    def test_merge_recap_captions_follows_picture(self):
        captions = jy.merge_recap_captions(
            [
                {"duration": 4.0, "vo": "开场很长的一句", "vo_tl_in": 0.0, "vo_tl_out": 6.5},
                {"duration": 4.0, "vo": "下一句", "vo_tl_in": 6.5, "vo_tl_out": 8.0},
            ]
        )
        self.assertEqual(len(captions), 2)
        self.assertAlmostEqual(captions[0]["start"], 0.0)
        self.assertAlmostEqual(captions[0]["duration"], 4.0)
        self.assertAlmostEqual(captions[1]["start"], 4.0)
        self.assertAlmostEqual(captions[1]["duration"], 4.0)

    def test_recap_captions_empty_follow_stays_on_same_line(self):
        vo = "一二三四五" * 8
        captions = jy.merge_recap_captions(
            [
                {"duration": 4.0, "vo": vo},
                {"duration": 6.0, "vo": ""},
                {"duration": 4.0, "vo": "下一句"},
            ]
        )
        self.assertEqual(len(captions), 2)
        self.assertAlmostEqual(captions[0]["start"], 0.0)
        self.assertAlmostEqual(captions[0]["duration"], 10.0)
        self.assertAlmostEqual(captions[1]["start"], 10.0)
        self.assertAlmostEqual(captions[1]["duration"], 4.0)

    def test_merge_recap_captions_skips_duplicate_line(self):
        captions = jy.merge_recap_captions(
            [
                {"duration": 4.0, "vo": "监考官宣布考试开始。"},
                {"duration": 3.0, "vo": "监考官宣布考试开始。"},
                {"duration": 4.0, "vo": "全场安静下来。"},
            ]
        )
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["text"], "监考官宣布考试开始。")
        self.assertAlmostEqual(captions[0]["duration"], 7.0)
        self.assertEqual(captions[1]["text"], "全场安静下来。")
        self.assertAlmostEqual(captions[1]["start"], 7.0)

    def test_stretched_picture_and_captions_share_timeline(self):
        from src.services.recap_service import stretch_recap_clips_for_vo, vo_needed_sec

        vo = "一二三四五" * 8
        clips = [
            {"src_in": 10.0, "src_out": 14.0, "vo": vo},
            {"src_in": 40.0, "src_out": 44.0, "vo": "下一句。"},
        ]
        stretched = stretch_recap_clips_for_vo(clips, media_duration=80.0)
        spans = jy.recap_export_clip_spans(stretched)
        captions = jy.merge_recap_captions(spans)
        self.assertEqual(len(spans), 2)
        self.assertEqual(len(captions), 2)
        self.assertGreaterEqual(spans[0]["duration"], vo_needed_sec(vo) - 0.35)
        self.assertAlmostEqual(captions[0]["duration"], spans[0]["duration"], places=2)
        self.assertAlmostEqual(captions[1]["start"], spans[0]["duration"], places=2)
        self.assertAlmostEqual(captions[1]["duration"], spans[1]["duration"], places=2)
        video_end = sum(item["duration"] for item in spans)
        cap_end = captions[-1]["start"] + captions[-1]["duration"]
        self.assertAlmostEqual(video_end, cap_end, places=2)


if __name__ == "__main__":
    unittest.main()
