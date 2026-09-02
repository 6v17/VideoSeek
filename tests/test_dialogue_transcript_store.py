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
                # Order does not matter for scatter score; ranking prefers complete spans.
                scrambled = fuzzy_dialogue_match_score("了杀都在这里", "都杀了")
                self.assertAlmostEqual(scrambled, 1.0, places=5)

                self.assertTrue(delete_dialogue_transcript("vid1"))
                self.assertIsNone(load_dialogue_transcript("vid1"))
                self.assertFalse(has_any_dialogue_transcript())

    def test_fuzzy_ranks_complete_subfield_before_scatter(self):
        from src.storage.dialogue_transcript_store import (
            _fuzzy_dialogue_rank,
            iter_matching_transcript_segment_rows,
            save_dialogue_transcript,
        )

        complete_len, complete_score = _fuzzy_dialogue_rank("全都杀了", "都杀了")
        scrambled_len, scrambled_score = _fuzzy_dialogue_rank("了杀都在这里", "都杀了")
        partial_len, partial_score = _fuzzy_dialogue_rank("我都知道了", "都杀了")
        self.assertEqual(complete_len, 3)
        self.assertEqual(scrambled_len, 1)
        self.assertEqual(partial_len, 1)
        self.assertAlmostEqual(complete_score, 1.0, places=5)
        self.assertAlmostEqual(scrambled_score, 1.0, places=5)
        self.assertAlmostEqual(partial_score, 2.0 / 3.0, places=5)
        self.assertGreater(complete_len, scrambled_len)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "vid1",
                    [
                        {
                            "start": 1.0,
                            "end": 2.0,
                            "text": "了杀都在这里",
                            "language": "zh",
                        },
                        {
                            "start": 3.0,
                            "end": 4.0,
                            "text": "全都杀了",
                            "language": "zh",
                        },
                        {
                            "start": 0.0,
                            "end": 0.5,
                            "text": "我都知道了",
                            "language": "zh",
                        },
                    ],
                    library_path=tmp,
                    video_path=os.path.join(tmp, "a.mp4"),
                    asr_source="ocr",
                )
                ranked = list(
                    iter_matching_transcript_segment_rows(
                        "都杀了",
                        video_ids=["vid1"],
                        match_mode="fuzzy",
                    )
                )
                self.assertEqual(
                    [item["text"] for item in ranked],
                    ["全都杀了", "了杀都在这里", "我都知道了"],
                )

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
                self.assertEqual(payload["segments"][0].get("speaker") or "", "")

    def test_speaker_roundtrip_update_and_inherit_on_overlap(self):
        from src.storage.dialogue_transcript_store import (
            inherit_segment_speakers,
            load_dialogue_transcript,
            save_dialogue_transcript,
            update_dialogue_segment_speaker,
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "v",
                    [
                        {"start": 1.0, "end": 3.0, "text": "开考", "asr_source": "asr"},
                        {"start": 8.0, "end": 9.0, "text": "过场", "asr_source": "asr"},
                    ],
                    library_path=tmp,
                    asr_source="asr",
                )
                self.assertTrue(update_dialogue_segment_speaker("v", 0, "柜台职员"))
                payload = load_dialogue_transcript("v")
                self.assertEqual(payload["segments"][0]["speaker"], "柜台职员")
                save_dialogue_transcript(
                    "v",
                    [
                        {"start": 1.1, "end": 2.8, "text": "现在开考", "asr_source": "asr"},
                        {"start": 8.0, "end": 9.0, "text": "过场", "asr_source": "asr"},
                    ],
                    library_path=tmp,
                    asr_source="asr",
                )
                payload = load_dialogue_transcript("v")
                self.assertEqual(payload["segments"][0]["speaker"], "柜台职员")
                self.assertEqual(payload["segments"][1].get("speaker") or "", "")

        carried = inherit_segment_speakers(
            [{"start": 10.0, "end": 12.0, "speaker": "红衣女人"}],
            [{"start": 0.0, "end": 1.0, "text": "别处", "speaker": ""}],
        )
        self.assertEqual(carried[0].get("speaker") or "", "")

    def test_update_dialogue_segment_time_text_and_speaker(self):
        from src.storage.dialogue_transcript_store import (
            load_dialogue_transcript,
            save_dialogue_transcript,
            update_dialogue_segment,
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "v",
                    [{"start": 1.0, "end": 3.0, "text": "开考", "asr_source": "asr"}],
                    library_path=tmp,
                    asr_source="asr",
                )
                self.assertTrue(
                    update_dialogue_segment(
                        "v",
                        0,
                        start=4.0,
                        end=6.5,
                        text="现在开考",
                        speaker="柜台职员",
                    )
                )
                payload = load_dialogue_transcript("v")
                row = payload["segments"][0]
                self.assertEqual(row["start"], 4.0)
                self.assertEqual(row["end"], 6.5)
                self.assertEqual(row["text"], "现在开考")
                self.assertEqual(row["speaker"], "柜台职员")
                self.assertFalse(update_dialogue_segment("v", 0, text="   "))

    def test_update_dialogue_transcript_location_after_rename(self):
        from src.storage.dialogue_transcript_store import (
            load_dialogue_transcript,
            save_dialogue_transcript,
            update_dialogue_transcript_location,
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            old_path = os.path.join(tmp, "old.mp4")
            new_path = os.path.join(tmp, "new.mp4")
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "v",
                    [{"start": 1.0, "end": 2.0, "text": "hi", "asr_source": "asr"}],
                    library_path=tmp,
                    video_path=old_path,
                    asr_source="asr",
                )
                self.assertTrue(
                    update_dialogue_transcript_location(
                        "v",
                        video_path=new_path,
                        library_path=tmp,
                    )
                )
                payload = load_dialogue_transcript("v")
                self.assertEqual(os.path.normcase(payload["video_path"]), os.path.normcase(new_path))
                self.assertFalse(
                    update_dialogue_transcript_location(
                        "v",
                        video_path=new_path,
                        library_path=tmp,
                    )
                )

    def test_rename_dialogue_speakers_bulk_merge_and_scope(self):
        from src.storage.dialogue_transcript_store import (
            load_dialogue_transcript,
            rename_dialogue_speakers,
            save_dialogue_transcript,
        )

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "v1",
                    [
                        {"start": 1.0, "end": 2.0, "text": "a", "speaker": "声线1", "asr_source": "asr"},
                        {"start": 2.0, "end": 3.0, "text": "b", "speaker": "声线1", "asr_source": "asr"},
                        {"start": 3.0, "end": 4.0, "text": "c", "speaker": "声线2", "asr_source": "asr"},
                        {"start": 4.0, "end": 5.0, "text": "d", "speaker": "", "asr_source": "asr"},
                    ],
                    library_path=tmp,
                    asr_source="asr",
                )
                save_dialogue_transcript(
                    "v2",
                    [{"start": 1.0, "end": 2.0, "text": "other", "speaker": "声线1", "asr_source": "asr"}],
                    library_path=tmp,
                    asr_source="asr",
                )
                self.assertEqual(rename_dialogue_speakers("v1", "声线1", "店长"), 2)
                payload = load_dialogue_transcript("v1")
                speakers = [row.get("speaker") or "" for row in payload["segments"]]
                self.assertEqual(speakers, ["店长", "店长", "声线2", ""])
                other = load_dialogue_transcript("v2")
                self.assertEqual(other["segments"][0]["speaker"], "声线1")
                self.assertEqual(rename_dialogue_speakers("v1", "声线2", "店长"), 1)
                payload = load_dialogue_transcript("v1")
                speakers = [row.get("speaker") or "" for row in payload["segments"]]
                self.assertEqual(speakers, ["店长", "店长", "店长", ""])
                self.assertEqual(rename_dialogue_speakers("v1", "店长", "店长"), 0)
                self.assertEqual(rename_dialogue_speakers("v1", "", "旁白"), 0)


if __name__ == "__main__":
    unittest.main()
