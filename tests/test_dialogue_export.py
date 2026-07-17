import os
import tempfile
import unittest
from unittest import mock


class DialogueExportServiceTests(unittest.TestCase):
    def test_export_srt_and_txt(self):
        from src.services.dialogue_export_service import (
            export_dialogue_transcripts,
            render_dialogue_srt,
            render_dialogue_txt,
        )

        srt = render_dialogue_srt(
            [{"start": 1.5, "end": 3.0, "text": "hello world"}]
        )
        self.assertIn("00:00:01,500 --> 00:00:03,000", srt)
        self.assertIn("hello world", srt)

        txt = render_dialogue_txt(
            [{"start": 1.5, "end": 3.0, "text": "hello world"}]
        )
        self.assertIn("hello world", txt)
        self.assertIn("1.500", txt)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            out_dir = os.path.join(tmp, "out")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ), mock.patch(
                "src.services.dialogue_export_service.ensure_shared_transcripts",
                return_value=0,
            ):
                from src.storage.dialogue_transcript_store import save_dialogue_transcript

                save_dialogue_transcript(
                    "vid1",
                    [{"start": 0.0, "end": 1.0, "text": "台词一行"}],
                    video_path=os.path.join(tmp, "clip.mp4"),
                    library_path=tmp,
                )
                result = export_dialogue_transcripts(out_dir, format="srt")
            self.assertTrue(result["ok"])
            self.assertEqual(result["exported"], 1)
            self.assertTrue(os.path.isfile(result["files"][0]))
            with open(result["files"][0], "r", encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("台词一行", body)


if __name__ == "__main__":
    unittest.main()
