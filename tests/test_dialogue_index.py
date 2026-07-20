import os
import tempfile
import unittest
from unittest import mock

import numpy as np


class DialogueLanceStoreTests(unittest.TestCase):
    def test_upsert_and_keyword_search(self):
        try:
            import lancedb  # noqa: F401
        except ImportError:
            self.skipTest("lancedb not installed")

        from src.storage.lance_dialogue_search import keyword_search_dialogue, search_dialogue
        from src.storage.lance_store import (
            DIALOGUE_INDEX_STATE_READY,
            DIALOGUE_SEGMENTS_TABLE_NAME,
            _connect_lance,
            _list_table_names,
            get_dialogue_index_state,
            serialize_embedding_spec,
            set_dialogue_index_state,
            upsert_profile_dialogue_segments,
        )

        dim = 8
        spec = {
            "model_id": "clip_onnx_default",
            "provider": "openai-clip",
            "embedding_space": "clip_test",
            "dimension": dim,
            "metric": "ip",
        }
        vector_a = np.zeros(dim, dtype=np.float32)
        vector_a[0] = 1.0
        vector_b = np.zeros(dim, dtype=np.float32)
        vector_b[1] = 1.0

        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "profile")
            os.makedirs(profile, exist_ok=True)
            result = upsert_profile_dialogue_segments(
                "vid1",
                [
                    {
                        "start": 1.0,
                        "end": 2.5,
                        "text": "スポンサーの提供でお送りしました",
                        "language": "ja",
                        "asr_source": "audio/speech_to_text/sensevoice-small",
                        "vector": vector_a,
                    },
                    {
                        "start": 3.0,
                        "end": 4.0,
                        "text": "hello world",
                        "language": "en",
                        "asr_source": "audio/speech_to_text/sensevoice-small",
                        "vector": vector_b,
                    },
                ],
                library_path=tmp,
                video_path=os.path.join(tmp, "clip.mp4"),
                embedding_spec=spec,
                profile_base_dir=profile,
            )
            self.assertEqual(result["segment_rows"], 2)
            set_dialogue_index_state(profile, "vid1", DIALOGUE_INDEX_STATE_READY)
            self.assertEqual(get_dialogue_index_state(profile, "vid1"), DIALOGUE_INDEX_STATE_READY)

            db = _connect_lance(profile)
            self.assertIn(DIALOGUE_SEGMENTS_TABLE_NAME, _list_table_names(db))

            from src.storage.dialogue_transcript_store import save_dialogue_transcript

            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_dialogue_transcript(
                    "vid1",
                    [
                        {
                            "start": 1.0,
                            "end": 2.5,
                            "text": "スポンサーの提供でお送りしました",
                            "language": "ja",
                        },
                        {
                            "start": 3.0,
                            "end": 4.0,
                            "text": "hello world",
                            "language": "en",
                        },
                    ],
                    library_path=tmp,
                    video_path=os.path.join(tmp, "clip.mp4"),
                )

            with mock.patch(
                "src.storage.lance_dialogue_search.get_active_embedding_spec",
                return_value=spec,
            ), mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ), mock.patch(
                "src.storage.dialogue_transcript_store.ensure_shared_transcripts",
                return_value=0,
            ):
                hits = keyword_search_dialogue(
                    "スポンサー",
                    profile_base_dir=profile,
                    top_k=5,
                )
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0].matched_by, "keyword")
                self.assertIn("スポンサー", hits[0].text)

                # Keyword search reads shared transcripts — not bound to CLIP.
                wrong_spec = dict(spec)
                wrong_spec["embedding_space"] = "other_space"
                with mock.patch(
                    "src.storage.lance_dialogue_search.get_active_embedding_spec",
                    return_value=wrong_spec,
                ):
                    unbound = keyword_search_dialogue(
                        "スポンサー",
                        profile_base_dir=profile,
                        top_k=5,
                    )
                    self.assertEqual(len(unbound), 1)
                    self.assertIn("スポンサー", unbound[0].text)

                query = np.zeros(dim, dtype=np.float32)
                query[0] = 1.0
                routed = search_dialogue(
                    "no-substring-match-xyz",
                    profile_base_dir=profile,
                    top_k=3,
                    query_vector=query,
                    match_mode="semantic",
                )
                self.assertEqual(routed["matched_by"], "vector")
                self.assertGreaterEqual(len(routed["hits"]), 1)
                self.assertEqual(routed["hits"][0].text, "スポンサーの提供でお送りしました")

                # Weak nearest neighbors must not surface as false-positive dialogue hits.
                weak_query = np.ones(dim, dtype=np.float32)
                weak = search_dialogue(
                    "no-substring-match-xyz",
                    profile_base_dir=profile,
                    top_k=3,
                    query_vector=weak_query,
                    match_mode="semantic",
                )
                self.assertEqual(weak["matched_by"], "vector")
                self.assertEqual(weak["hits"], [])
                self.assertEqual(weak["message"], "no dialogue matches")

                segment_only = search_dialogue(
                    "no-substring-match-xyz",
                    profile_base_dir=profile,
                    top_k=3,
                    query_vector=query,
                    match_mode="segment",
                )
                self.assertEqual(segment_only["matched_by"], "keyword")
                self.assertEqual(segment_only["hits"], [])

            self.assertIn("embedding_space", serialize_embedding_spec(spec))


class DialogueIndexServiceTests(unittest.TestCase):
    def test_index_video_dialogue_maps_asr_mode_to_ocr(self):
        from src.services import dialogue_index_service as service

        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "clip.mp4")
            with open(media, "wb") as handle:
                handle.write(b"fake")

            with mock.patch(
                "src.services.subtitle_index_service.index_video_subtitles",
                return_value={
                    "ok": True,
                    "video_id": "vid9",
                    "segment_rows": 1,
                    "mode": "ocr",
                    "asr_source": "vision/ocr/rapidocr",
                },
            ) as index_mock:
                result = service.index_video_dialogue(
                    "vid9",
                    media,
                    library_path=tmp,
                    mode="asr",
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["segment_rows"], 1)
            self.assertEqual(index_mock.call_args.kwargs.get("mode"), "ocr")

    def test_reembed_maps_to_reuse_mode(self):
        from src.services import dialogue_index_service as service

        with mock.patch(
            "src.services.subtitle_index_service.index_video_subtitles",
            return_value={
                "ok": True,
                "video_id": "vid9",
                "segment_rows": 1,
                "mode": "reuse",
                "reused_transcripts": True,
            },
        ) as index_mock:
            result = service.index_video_dialogue(
                "vid9",
                "",
                library_path="D:/lib",
                mode="reembed",
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["reused_transcripts"])
        self.assertEqual(index_mock.call_args.kwargs.get("mode"), "reuse")

    def test_auto_passes_through_to_subtitle_index(self):
        from src.services import dialogue_index_service as service

        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "clip.mp4")
            with open(media, "wb") as handle:
                handle.write(b"fake")

            with mock.patch(
                "src.services.subtitle_index_service.index_video_subtitles",
                return_value={
                    "ok": True,
                    "video_id": "vid9",
                    "segment_rows": 1,
                    "mode": "reuse",
                    "reused_transcripts": True,
                },
            ) as index_mock:
                result = service.index_video_dialogue(
                    "vid9",
                    media,
                    library_path=tmp,
                    mode="auto",
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["reused_transcripts"])
            self.assertEqual(index_mock.call_args.kwargs.get("mode"), "auto")


class SharedDialogueTranscriptStoreTests(unittest.TestCase):
    def test_save_load_independent_of_profile(self):
        from src.storage.dialogue_transcript_store import (
            list_shared_transcript_segments,
            load_dialogue_transcript,
            save_dialogue_transcript,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                saved = save_dialogue_transcript(
                    "vid_shared",
                    [{"start": 1.0, "end": 2.0, "text": "公用台词", "language": "zh"}],
                    library_path=tmp,
                    video_path=os.path.join(tmp, "a.mp4"),
                    asr_source="audio/speech_to_text/faster-whisper-medium",
                )
                self.assertTrue(saved["ok"])
                payload = load_dialogue_transcript("vid_shared")
                self.assertIsNotNone(payload)
                self.assertEqual(payload["segment_count"], 1)
                rows = list_shared_transcript_segments("vid_shared")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["text"], "公用台词")

    def test_summaries_skip_segment_payload(self):
        from src.storage.dialogue_transcript_store import (
            list_dialogue_transcript_summaries,
            save_dialogue_transcript,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                save_dialogue_transcript(
                    "vid_a",
                    [{"start": 0.0, "end": 1.0, "text": "alpha", "language": "en"}],
                    library_path=tmp,
                    video_path=os.path.join(tmp, "a.mp4"),
                )
                rows = list_dialogue_transcript_summaries()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["video_id"], "vid_a")
                self.assertEqual(rows[0]["segment_count"], 1)
                self.assertNotIn("segments", rows[0])

    def test_keyword_search_respects_video_ids_scope(self):
        from src.storage.dialogue_transcript_store import save_dialogue_transcript
        from src.storage.lance_dialogue_search import keyword_search_dialogue

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": tmp},
            ):
                for video_id, text in (
                    ("vid_keep", "find me please"),
                    ("vid_skip", "find me please"),
                ):
                    save_dialogue_transcript(
                        video_id,
                        [{"start": 0.0, "end": 1.0, "text": text, "language": "en"}],
                        library_path=tmp,
                        video_path=os.path.join(tmp, f"{video_id}.mp4"),
                    )
                with mock.patch(
                    "src.storage.dialogue_transcript_store.ensure_shared_transcripts",
                    return_value=0,
                ), mock.patch(
                    "src.storage.dialogue_transcript_store.has_any_dialogue_transcript",
                    return_value=True,
                ):
                    hits = keyword_search_dialogue(
                        "find me",
                        video_ids=["vid_keep"],
                        top_k=10,
                    )
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0].video_id, "vid_keep")


if __name__ == "__main__":
    unittest.main()
