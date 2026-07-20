import os
import tempfile
import unittest
from unittest import mock


class DialogueTranscriptSqliteStoreTests(unittest.TestCase):
    def test_save_load_list_delete_and_keyword(self):
        from src.storage.dialogue_transcript_store import (
            delete_dialogue_transcript,
            get_dialogue_transcripts_db_path,
            has_any_dialogue_transcript,
            iter_matching_transcript_segment_rows,
            list_dialogue_transcript_summaries,
            load_dialogue_transcript,
            save_dialogue_transcript,
        )
        from src.storage.lance_dialogue_search import keyword_search_dialogue

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                self.assertFalse(has_any_dialogue_transcript())
                saved = save_dialogue_transcript(
                    "vid1",
                    [
                        {
                            "start": 1.0,
                            "end": 2.0,
                            "text": "Hello World",
                            "language": "en",
                        },
                        {
                            "start": 3.0,
                            "end": 4.0,
                            "text": "赞助商提供",
                            "language": "zh",
                        },
                    ],
                    library_path=tmp,
                    video_path=os.path.join(tmp, "a.mp4"),
                    asr_source="ocr",
                )
                self.assertTrue(saved["ok"])
                self.assertEqual(saved["segment_count"], 2)
                self.assertTrue(os.path.isfile(get_dialogue_transcripts_db_path()))
                self.assertTrue(has_any_dialogue_transcript())

                payload = load_dialogue_transcript("vid1")
                self.assertIsNotNone(payload)
                self.assertEqual(payload["segment_count"], 2)
                self.assertEqual(payload["asr_source"], "ocr")
                self.assertEqual(payload["segments"][1]["text"], "赞助商提供")

                summaries = list_dialogue_transcript_summaries()
                self.assertEqual(len(summaries), 1)
                self.assertEqual(summaries[0]["video_id"], "vid1")
                self.assertEqual(summaries[0]["segment_count"], 2)

                scoped = list_dialogue_transcript_summaries(video_ids=["missing"])
                self.assertEqual(scoped, [])

                matches = list(
                    iter_matching_transcript_segment_rows(
                        "hello",
                        video_ids=["vid1"],
                    )
                )
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["text"], "Hello World")

                hits = keyword_search_dialogue("赞助", top_k=5)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0].text, "赞助商提供")
                self.assertEqual(hits[0].matched_by, "keyword")

                # Exact misses a one-character OCR typo; fuzzy should recover.
                exact_typo = list(
                    iter_matching_transcript_segment_rows(
                        "赞住商",
                        video_ids=["vid1"],
                        match_mode="exact",
                    )
                )
                self.assertEqual(exact_typo, [])
                fuzzy_typo = list(
                    iter_matching_transcript_segment_rows(
                        "赞住商",
                        video_ids=["vid1"],
                        match_mode="fuzzy",
                    )
                )
                self.assertEqual(len(fuzzy_typo), 1)
                self.assertEqual(fuzzy_typo[0]["text"], "赞助商提供")
                self.assertGreaterEqual(float(fuzzy_typo[0]["score"]), 0.5)

                fuzzy_hits = keyword_search_dialogue(
                    "赞住商",
                    top_k=5,
                    match_mode="fuzzy",
                )
                self.assertEqual(len(fuzzy_hits), 1)
                self.assertEqual(fuzzy_hits[0].text, "赞助商提供")

                # BT-style: punctuation / keyword split should still hit.
                punct = list(
                    iter_matching_transcript_segment_rows(
                        "Hello_World",
                        video_ids=["vid1"],
                        match_mode="fuzzy",
                    )
                )
                self.assertEqual(len(punct), 1)
                self.assertEqual(punct[0]["text"], "Hello World")

                multi = list(
                    iter_matching_transcript_segment_rows(
                        "赞助 提供",
                        video_ids=["vid1"],
                        match_mode="fuzzy",
                    )
                )
                self.assertEqual(len(multi), 1)
                self.assertEqual(multi[0]["text"], "赞助商提供")

                from src.storage.dialogue_transcript_store import (
                    fuzzy_dialogue_accepts,
                    fuzzy_dialogue_match_score,
                )

                # Unordered single-char scatter: any landing counts; rank by hit rate.
                loose = fuzzy_dialogue_match_score("我都知道了", "都杀了")
                self.assertTrue(fuzzy_dialogue_accepts(loose, "都杀了"))
                self.assertAlmostEqual(loose, 2.0 / 3.0, places=5)
                tight = fuzzy_dialogue_match_score("全都杀了", "都杀了")
                self.assertTrue(fuzzy_dialogue_accepts(tight, "都杀了"))
                self.assertAlmostEqual(tight, 1.0, places=5)
                self.assertGreater(tight, loose)
                # Order does not matter.
                scrambled = fuzzy_dialogue_match_score("了杀都在这里", "都杀了")
                self.assertAlmostEqual(scrambled, 1.0, places=5)

                self.assertTrue(delete_dialogue_transcript("vid1"))
                self.assertIsNone(load_dialogue_transcript("vid1"))
                self.assertFalse(has_any_dialogue_transcript())

    def test_overwrite_replaces_segments(self):
        from src.storage.dialogue_transcript_store import (
            load_dialogue_transcript,
            save_dialogue_transcript,
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "v",
                    [{"start": 0.0, "end": 1.0, "text": "old"}],
                    library_path=tmp,
                )
                save_dialogue_transcript(
                    "v",
                    [{"start": 2.0, "end": 3.0, "text": "new only"}],
                    library_path=tmp,
                )
                payload = load_dialogue_transcript("v")
                self.assertEqual(payload["segment_count"], 1)
                self.assertEqual(payload["segments"][0]["text"], "new only")


if __name__ == "__main__":
    unittest.main()
