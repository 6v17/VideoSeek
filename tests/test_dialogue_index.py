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
    def test_index_video_dialogue_orchestrates_pipeline(self):
        from src.services import dialogue_index_service as service

        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "clip.mp4")
            with open(media, "wb") as handle:
                handle.write(b"fake")
            profile = os.path.join(tmp, "profile")
            os.makedirs(profile, exist_ok=True)
            wav_path = os.path.join(tmp, "out.wav")
            with open(wav_path, "wb") as handle:
                handle.write(b"RIFF")

            with mock.patch.object(service, "ensure_dialogue_asr_ready", return_value=(True, "")), mock.patch.object(
                service, "get_local_model_asset_dirs", return_value={"base_dir": profile}
            ), mock.patch.object(
                service,
                "get_active_embedding_spec",
                return_value={
                    "model_id": "clip",
                    "provider": "openai-clip",
                    "embedding_space": "clip",
                    "dimension": 4,
                    "metric": "ip",
                },
            ), mock.patch.object(service, "extract_audio_wav", return_value=wav_path), mock.patch.object(
                service,
                "transcribe_wav",
                return_value=[
                    {
                        "start": 0.1,
                        "end": 1.2,
                        "text": "test dialogue line",
                        "language": "en",
                        "asr_source": "audio/speech_to_text/faster-whisper-medium",
                    }
                ],
            ) as transcribe_mock, mock.patch.object(
                service, "save_dialogue_transcript", return_value={"ok": True, "segment_count": 1}
            ) as save_mock, mock.patch.object(
                service,
                "get_text_embedding",
                return_value=np.asarray([1, 0, 0, 0], dtype=np.float32),
            ), mock.patch.object(
                service,
                "upsert_profile_dialogue_segments",
                return_value={"segment_rows": 1, "dimension": 4},
            ) as upsert_mock, mock.patch.object(service, "set_dialogue_index_state") as state_mock:
                result = service.index_video_dialogue(
                    "vid9",
                    media,
                    library_path=tmp,
                    mode="asr",
                )
            save_mock.assert_called_once()

            self.assertTrue(result["ok"])
            self.assertEqual(result["segment_rows"], 1)
            self.assertEqual(result["asr_source"], "audio/speech_to_text/faster-whisper-medium")
            self.assertEqual(result["mode"], "asr")
            upsert_mock.assert_called_once()
            state_mock.assert_called()
            transcribe_mock.assert_called_once()

    def test_reembed_reuses_transcripts_without_asr(self):
        from src.services import dialogue_index_service as service

        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "profile")
            os.makedirs(profile, exist_ok=True)
            existing = [
                {
                    "video_id": "vid9",
                    "video_path": os.path.join(tmp, "clip.mp4"),
                    "library_path": tmp,
                    "start": 0.1,
                    "end": 1.2,
                    "text": "stored dialogue line",
                    "language": "en",
                    "asr_source": "audio/speech_to_text/faster-whisper-medium",
                }
            ]
            with mock.patch.object(
                service, "get_local_model_asset_dirs", return_value={"base_dir": profile}
            ), mock.patch.object(
                service,
                "get_active_embedding_spec",
                return_value={
                    "model_id": "clip-b",
                    "provider": "openai-clip",
                    "embedding_space": "clip-b",
                    "dimension": 4,
                    "metric": "ip",
                },
            ), mock.patch.object(
                service, "_load_existing_transcripts", return_value=existing
            ), mock.patch.object(
                service, "ensure_dialogue_asr_ready", return_value=(False, "should not run")
            ) as asr_ready_mock, mock.patch.object(
                service, "extract_audio_wav"
            ) as extract_mock, mock.patch.object(
                service, "transcribe_wav"
            ) as transcribe_mock, mock.patch.object(
                service,
                "get_text_embedding",
                return_value=np.asarray([0, 1, 0, 0], dtype=np.float32),
            ), mock.patch.object(
                service,
                "upsert_profile_dialogue_segments",
                return_value={"segment_rows": 1, "dimension": 4},
            ) as upsert_mock, mock.patch.object(service, "set_dialogue_index_state"):
                result = service.index_video_dialogue(
                    "vid9",
                    "",
                    library_path=tmp,
                    mode="reembed",
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["reused_transcripts"])
            self.assertEqual(result["mode"], "reembed")
            asr_ready_mock.assert_not_called()
            extract_mock.assert_not_called()
            transcribe_mock.assert_not_called()
            upsert_mock.assert_called_once()
            rows = upsert_mock.call_args.args[1]
            self.assertEqual(rows[0]["text"], "stored dialogue line")

    def test_auto_reuses_existing_transcripts(self):
        from src.services import dialogue_index_service as service

        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "clip.mp4")
            with open(media, "wb") as handle:
                handle.write(b"fake")
            profile = os.path.join(tmp, "profile")
            os.makedirs(profile, exist_ok=True)
            existing = [
                {
                    "video_id": "vid9",
                    "video_path": media,
                    "library_path": tmp,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "reuse me",
                    "language": "en",
                    "asr_source": "audio/speech_to_text/faster-whisper-medium",
                }
            ]
            with mock.patch.object(
                service, "get_local_model_asset_dirs", return_value={"base_dir": profile}
            ), mock.patch.object(
                service,
                "get_active_embedding_spec",
                return_value={
                    "model_id": "clip",
                    "provider": "openai-clip",
                    "embedding_space": "clip",
                    "dimension": 4,
                    "metric": "ip",
                },
            ), mock.patch.object(
                service, "_load_existing_transcripts", return_value=existing
            ), mock.patch.object(
                service, "transcribe_wav"
            ) as transcribe_mock, mock.patch.object(
                service,
                "get_text_embedding",
                return_value=np.asarray([1, 0, 0, 0], dtype=np.float32),
            ), mock.patch.object(
                service,
                "upsert_profile_dialogue_segments",
                return_value={"segment_rows": 1, "dimension": 4},
            ), mock.patch.object(service, "set_dialogue_index_state"):
                result = service.index_video_dialogue(
                    "vid9",
                    media,
                    library_path=tmp,
                    mode="auto",
                )

            self.assertTrue(result["ok"])
            self.assertTrue(result["reused_transcripts"])
            transcribe_mock.assert_not_called()


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


if __name__ == "__main__":
    unittest.main()
