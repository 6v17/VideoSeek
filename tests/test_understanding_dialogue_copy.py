"""Understanding dialogue is a copy. Library rows stay put."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.services.dialogue_export_service import render_dialogue_srt
from src.services.understanding_dialogue import (
    delete_working_cue,
    delete_working_cues,
    ensure_working_copy,
    load_working_copy,
    rename_working_speakers,
    replace_working_copy_from_extraction,
    save_working_copy,
    update_working_cue,
)
from src.storage.dialogue_transcript_store import load_dialogue_transcript, save_dialogue_transcript


class ChunkMetaMatchTests(unittest.TestCase):
    def test_chunk_meta_matches_payload_requires_timing(self):
        from src.services.understanding_service import chunk_meta_matches_payload

        meta = {"start": 10.0, "end": 12.0}
        ok = {"chunk_index": 1, "start_sec": 10.0, "end_sec": 12.0}
        stale = {"chunk_index": 1, "start_sec": 20.0, "end_sec": 22.0}
        self.assertTrue(chunk_meta_matches_payload(meta, ok, 1))
        self.assertFalse(chunk_meta_matches_payload(meta, stale, 1))
        self.assertFalse(chunk_meta_matches_payload(meta, ok, 0))


class UnderstandingDialogueCopyTests(unittest.TestCase):
    def test_library_cues_are_copied_once_and_edits_stay_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_dialogue_transcript(
                    "vid-copy",
                    [{"start": 1.0, "end": 2.0, "text": "库里的台词", "speaker": "甲"}],
                    library_path=tmp,
                    video_path=os.path.join(tmp, "clip.mp4"),
                    asr_source="asr",
                )
                first = ensure_working_copy("vid-copy")
                self.assertEqual(first["origin"], "library")
                self.assertEqual(first["cues"][0]["text"], "库里的台词")

                update_working_cue(
                    "vid-copy",
                    int(first["cues"][0]["seg_index"]),
                    start=1.2,
                    end=2.4,
                    text="只改副本",
                    speaker="乙",
                )
                library = load_dialogue_transcript("vid-copy")
                self.assertEqual(library["segments"][0]["text"], "库里的台词")
                self.assertEqual(library["segments"][0]["speaker"], "甲")
                copied = load_working_copy("vid-copy")
                self.assertEqual(copied["cues"][0]["text"], "只改副本")

                delete_working_cue("vid-copy", int(copied["cues"][0]["seg_index"]))
                again = ensure_working_copy("vid-copy")
                self.assertEqual(again["cues"], [])
                self.assertEqual(load_dialogue_transcript("vid-copy")["segments"][0]["text"], "库里的台词")

    def test_local_ocr_does_not_create_a_library_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_working_copy(
                    "vid-local",
                    [{"start": 0.0, "end": 1.5, "text": "硬字幕", "asr_source": "vision/ocr/rapidocr-zh"}],
                    origin="ocr",
                    video_path=os.path.join(tmp, "movie.mp4"),
                    asr_source="vision/ocr/rapidocr-zh",
                )
                self.assertIsNone(load_dialogue_transcript("vid-local"))
                cues = load_working_copy("vid-local")["cues"]
                body = render_dialogue_srt(cues)
                self.assertIn("硬字幕", body)
                self.assertIn("-->", body)

    def test_clearing_cue_text_keeps_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_working_copy(
                    "vid-empty",
                    [{"seg_index": 0, "start": 1.0, "end": 2.0, "text": "先有字"}],
                    origin="local",
                )
                self.assertTrue(
                    update_working_cue(
                        "vid-empty",
                        0,
                        start=1.0,
                        end=2.0,
                        text="",
                        speaker="",
                    )
                )
                cues = load_working_copy("vid-empty")["cues"]
                self.assertEqual(len(cues), 1)
                self.assertEqual(cues[0]["text"], "")
                self.assertEqual(cues[0]["seg_index"], 0)

    def test_extraction_skips_user_edited_working_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_working_copy(
                    "vid-protect",
                    [{"seg_index": 0, "start": 0.0, "end": 1.0, "text": "手改"}],
                    origin="asr",
                )
                update_working_cue(
                    "vid-protect",
                    0,
                    start=0.0,
                    end=1.0,
                    text="手改保留",
                )
                skipped = replace_working_copy_from_extraction(
                    "vid-protect",
                    [{"seg_index": 0, "start": 0.0, "end": 1.0, "text": "新 ASR"}],
                    origin="asr",
                    force_overwrite=False,
                )
                self.assertTrue(skipped.get("skipped_protected"))
                self.assertEqual(load_working_copy("vid-protect")["cues"][0]["text"], "手改保留")
                replaced = replace_working_copy_from_extraction(
                    "vid-protect",
                    [{"seg_index": 0, "start": 0.0, "end": 1.0, "text": "新 ASR"}],
                    origin="asr",
                    force_overwrite=True,
                )
                self.assertFalse(replaced.get("skipped_protected"))
                self.assertEqual(load_working_copy("vid-protect")["cues"][0]["text"], "新 ASR")

    def test_delete_working_cues_removes_many_in_one_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_working_copy(
                    "vid-batch-del",
                    [
                        {"seg_index": 0, "start": 0.0, "end": 1.0, "text": "留着"},
                        {"seg_index": 1, "start": 1.0, "end": 2.0, "text": "删1"},
                        {"seg_index": 2, "start": 2.0, "end": 3.0, "text": "删2"},
                        {"seg_index": 3, "start": 3.0, "end": 4.0, "text": "也留"},
                    ],
                    origin="local",
                )
                removed = delete_working_cues("vid-batch-del", [1, 2, 99])
                self.assertEqual(removed, 2)
                cues = load_working_copy("vid-batch-del")["cues"]
                self.assertEqual([row["text"] for row in cues], ["留着", "也留"])
                self.assertEqual([row["seg_index"] for row in cues], [0, 3])

    def test_rename_auto_is_batch_manual_is_one_cue(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_working_copy(
                    "vid-rename",
                    [
                        {"seg_index": 0, "start": 0.0, "end": 1.0, "text": "a", "speaker": "声线1"},
                        {"seg_index": 1, "start": 1.0, "end": 2.0, "text": "b", "speaker": "声线1"},
                        {"seg_index": 2, "start": 2.0, "end": 3.0, "text": "c", "speaker": "店长"},
                        {"seg_index": 3, "start": 3.0, "end": 4.0, "text": "d", "speaker": "店长"},
                    ],
                    origin="local",
                )
                self.assertEqual(
                    rename_working_speakers("vid-rename", "声线1", "男主"),
                    2,
                )
                cues = load_working_copy("vid-rename")["cues"]
                self.assertEqual([row["speaker"] for row in cues], ["男主", "男主", "店长", "店长"])
                self.assertEqual(
                    rename_working_speakers("vid-rename", "店长", "老板", seg_index=2),
                    1,
                )
                cues = load_working_copy("vid-rename")["cues"]
                self.assertEqual([row["speaker"] for row in cues], ["男主", "男主", "老板", "店长"])


if __name__ == "__main__":
    unittest.main()
