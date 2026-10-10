"""SRT import matches registered subtitle-library videos and writes transcripts."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from src.services import library_service, subtitle_library_service
from src.services.subtitle_srt_import import (
    SRT_SOURCE_ID,
    apply_subtitle_srt_import,
    parse_srt_text,
    plan_subtitle_srt_import,
)
from src.storage import dialogue_transcript_store, subtitle_library_store
from src.utils import canonicalize_library_path


def _write(path: str, text: str, *, encoding: str = "utf-8") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="\n") as handle:
        handle.write(text)


class ParseSrtTests(unittest.TestCase):
    def test_cues_keep_times_and_drop_markup(self):
        cues = parse_srt_text(
            "1\n"
            "00:00:01,500 --> 00:00:03,000\n"
            "<i>你好</i> {\\an8}世界\n"
            "\n"
            "2\n"
            "00:01:02.250 --> 00:01:04.000\n"
            "second line\n"
        )
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["start"], 1.5)
        self.assertEqual(cues[0]["end"], 3.0)
        self.assertEqual(cues[0]["text"], "你好 世界")
        self.assertEqual(cues[1]["start"], 62.25)
        self.assertEqual(cues[1]["text"], "second line")

    def test_gb18030_file_decodes(self):
        from src.services.subtitle_srt_import import _read_srt_text

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "zh.srt")
            with open(path, "wb") as handle:
                handle.write("1\n00:00:00,000 --> 00:00:01,000\n中文台词\n".encode("gb18030"))
            cues = parse_srt_text(_read_srt_text(path))
        self.assertEqual(cues[0]["text"], "中文台词")


class SubtitleSrtImportTests(unittest.TestCase):
    def _bind(self, tmp: str):
        data_dir = os.path.join(tmp, "data")
        dialogue_dir = os.path.join(data_dir, "dialogue")
        os.makedirs(dialogue_dir, exist_ok=True)
        config = {"data_root": tmp}
        return data_dir, dialogue_dir, config

    def _patches(self, data_dir: str, dialogue_dir: str, config: dict):
        stack = ExitStack()
        stack.enter_context(patch.object(subtitle_library_service, "load_config", return_value=config))
        stack.enter_context(patch.object(library_service, "load_config", return_value=config))
        stack.enter_context(
            patch("src.app.config.get_data_storage_paths", return_value={"data_dir": data_dir})
        )
        stack.enter_context(
            patch.object(subtitle_library_store, "get_dialogue_store_dir", return_value=dialogue_dir)
        )
        stack.enter_context(
            patch.object(dialogue_transcript_store, "get_dialogue_store_dir", return_value=dialogue_dir)
        )
        return stack

    def test_unique_name_and_language_suffix_initialize_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir, dialogue_dir, config = self._bind(tmp)
            video_root = os.path.join(tmp, "videos")
            os.makedirs(video_root, exist_ok=True)
            with open(os.path.join(video_root, "show.mkv"), "wb") as handle:
                handle.write(b"fake-show")
            with open(os.path.join(video_root, "extra.mp4"), "wb") as handle:
                handle.write(b"fake-extra")
            srt_dir = os.path.join(tmp, "subs")
            _write(
                os.path.join(srt_dir, "show.zh-Hans.srt"),
                "1\n00:00:00,000 --> 00:00:01,000\n开场\n",
            )
            _write(
                os.path.join(srt_dir, "missing.srt"),
                "1\n00:00:00,000 --> 00:00:01,000\n没有这个视频\n",
            )
            with self._patches(data_dir, dialogue_dir, config):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                added = subtitle_library_service.add_subtitle_library(video_root, config=config)
                self.assertTrue(added["added"])
                plan = plan_subtitle_srt_import(
                    [
                        os.path.join(srt_dir, "show.zh-Hans.srt"),
                        os.path.join(srt_dir, "missing.srt"),
                    ],
                    config=config,
                )
                self.assertEqual(len(plan["matches"]), 1)
                self.assertEqual(plan["matches"][0]["segment_count"], 1)
                self.assertFalse(plan["matches"][0]["replaces"])
                self.assertEqual(len(plan["unmatched"]), 1)
                applied = apply_subtitle_srt_import(plan["matches"], config=config)
                self.assertEqual(applied["imported"], 1)
                saved = dialogue_transcript_store.load_dialogue_transcript(
                    plan["matches"][0]["video_id"],
                    config=config,
                )
                self.assertEqual(saved["asr_source"], SRT_SOURCE_ID)
                self.assertEqual(saved["segments"][0]["text"], "开场")
                self.assertEqual(
                    canonicalize_library_path(saved["library_path"]),
                    canonicalize_library_path(video_root),
                )

    def test_same_folder_wins_and_a_loose_duplicate_name_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir, dialogue_dir, config = self._bind(tmp)
            first = os.path.join(tmp, "lib-a")
            second = os.path.join(tmp, "lib-b")
            os.makedirs(first, exist_ok=True)
            os.makedirs(second, exist_ok=True)
            with open(os.path.join(first, "ep.mp4"), "wb") as handle:
                handle.write(b"a")
            with open(os.path.join(second, "ep.mp4"), "wb") as handle:
                handle.write(b"b")
            _write(
                os.path.join(first, "ep.srt"),
                "1\n00:00:01,000 --> 00:00:02,000\n旁边这份\n",
            )
            _write(
                os.path.join(tmp, "ep.srt"),
                "1\n00:00:01,000 --> 00:00:02,000\n外面这份\n",
            )
            with self._patches(data_dir, dialogue_dir, config):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                subtitle_library_service.add_subtitle_library(first, config=config)
                subtitle_library_service.add_subtitle_library(second, config=config)
                plan = plan_subtitle_srt_import(
                    [os.path.join(first, "ep.srt"), os.path.join(tmp, "ep.srt")],
                    config=config,
                )
                self.assertEqual(len(plan["matches"]), 1)
                self.assertEqual(os.path.basename(os.path.dirname(plan["matches"][0]["video_path"])), "lib-a")
                self.assertEqual(plan["matches"][0]["segments"][0]["text"], "旁边这份")
                reasons = [item["reason"] for item in plan["skipped"]]
                self.assertIn("ambiguous", reasons)

    def test_reimport_replaces_the_existing_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir, dialogue_dir, config = self._bind(tmp)
            video_root = os.path.join(tmp, "videos")
            os.makedirs(video_root, exist_ok=True)
            video_path = os.path.join(video_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"clip")
            srt_path = os.path.join(tmp, "clip.srt")
            _write(srt_path, "1\n00:00:00,000 --> 00:00:01,000\n新字幕\n")
            with self._patches(data_dir, dialogue_dir, config):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                subtitle_library_service.add_subtitle_library(video_root, config=config)
                entries = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=True
                )
                dialogue_transcript_store.save_dialogue_transcript(
                    entries[0]["video_id"],
                    [{"start": 0.0, "end": 1.0, "text": "旧字幕"}],
                    library_path=video_root,
                    video_path=video_path,
                    asr_source="ocr",
                    config=config,
                )
                plan = plan_subtitle_srt_import([srt_path], config=config)
                self.assertTrue(plan["matches"][0]["replaces"])
                apply_subtitle_srt_import(plan["matches"], config=config)
                saved = dialogue_transcript_store.load_dialogue_transcript(
                    entries[0]["video_id"],
                    config=config,
                )
                self.assertEqual(saved["segments"][0]["text"], "新字幕")
                self.assertEqual(saved["asr_source"], SRT_SOURCE_ID)
