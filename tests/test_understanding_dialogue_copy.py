"""Understanding dialogue is a copy. Library rows stay put."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from src.services.dialogue_export_service import render_dialogue_srt
from src.services.understanding_dialogue import (
    delete_working_cue,
    ensure_working_copy,
    load_working_copy,
    save_working_copy,
    update_working_cue,
)
from src.storage.dialogue_transcript_store import load_dialogue_transcript, save_dialogue_transcript


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


if __name__ == "__main__":
    unittest.main()
