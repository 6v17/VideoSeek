import os
import tempfile
import unittest
import zipfile
from unittest import mock

import numpy as np


class FbankKaldiTests(unittest.TestCase):
    def test_one_second_sine_has_80_bins(self):
        from src.core.asr.fbank_kaldi import compute_fbank

        sr = 16000
        t = np.arange(sr, dtype=np.float32) / sr
        wave = np.sin(2.0 * np.pi * 220.0 * t).astype(np.float32)
        feat = compute_fbank(wave, sample_rate=sr)
        self.assertEqual(feat.shape[1], 80)
        self.assertGreaterEqual(feat.shape[0], 90)
        self.assertLessEqual(feat.shape[0], 110)
        self.assertTrue(np.isfinite(feat).all())


class CampplusPathTests(unittest.TestCase):
    def test_install_zip_and_resolve(self):
        from src.core.asr.campplus_onnx import install_campplus_from_zip, resolve_campplus_model_path

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "cam++.zip")
            dest = os.path.join(tmp, "campplus")
            with zipfile.ZipFile(zip_path, "w") as handle:
                handle.writestr("campplus.onnx", b"onnx-stub")
                handle.writestr("nested/campplus.onnx.data", b"external-data")
            installed = install_campplus_from_zip(zip_path, dest_dir=dest)
            self.assertTrue(os.path.isfile(installed))
            self.assertTrue(os.path.isfile(installed + ".data"))
            with mock.patch.dict(os.environ, {"VIDEOSEEK_CAMPPLUS_PATH": installed}, clear=False):
                self.assertEqual(resolve_campplus_model_path(), os.path.normpath(installed))

    def test_missing_model_returns_none(self):
        from src.core.asr.campplus_onnx import resolve_campplus_model_path

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VIDEOSEEK_CAMPPLUS_PATH": os.path.join(tmp, "missing.onnx")}):
                with mock.patch("src.infra.paths.get_resource_path", return_value=os.path.join(tmp, "nope.onnx")):
                    self.assertIsNone(resolve_campplus_model_path(model_dir=tmp))


class SpeakerClusterLogicTests(unittest.TestCase):
    def test_two_groups_get_distinct_labels(self):
        from src.services.speaker_cluster_service import cluster_embeddings, speaker_cluster_label

        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        embs = np.stack([a, a * 1.02, b, b * 0.97])
        labels = cluster_embeddings(embs, threshold=0.8)
        self.assertEqual(labels[0], labels[1])
        self.assertEqual(labels[2], labels[3])
        self.assertNotEqual(labels[0], labels[2])
        self.assertEqual(speaker_cluster_label(0), "声线1")
        self.assertEqual(speaker_cluster_label(1), "声线2")

    def test_similarity_chain_does_not_collapse(self):
        from src.services.speaker_cluster_service import cluster_embeddings

        a = np.array([1.0, 0.0], dtype=np.float32)
        c = np.array([0.0, 1.0], dtype=np.float32)
        bridge = np.array([0.72, 0.72], dtype=np.float32)
        bridge = bridge / np.linalg.norm(bridge)
        embs = np.stack([a, a, a, bridge, c, c, c])
        labels = cluster_embeddings(embs, absorb_tiny=False)
        self.assertEqual(labels[0], labels[1])
        self.assertEqual(labels[-1], labels[-2])
        self.assertNotEqual(labels[0], labels[-1])

    def test_two_jittered_voices_do_not_explode(self):
        from src.services.speaker_cluster_service import cluster_embeddings

        rng = np.random.default_rng(0)

        def blob(center: np.ndarray, count: int) -> list[np.ndarray]:
            rows = []
            for _ in range(count):
                vec = center + rng.normal(0.0, 0.08, size=center.shape).astype(np.float32)
                rows.append(vec / np.linalg.norm(vec))
            return rows

        a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        embs = np.stack(blob(a, 40) + blob(b, 40))
        labels = cluster_embeddings(embs)
        self.assertEqual(len(set(labels)), 2)
        self.assertEqual(set(labels[:40]), {0})
        self.assertEqual(set(labels[40:]), {1})

    def test_embed_windows_keep_two_talkers_not_whole_span(self):
        from src.services.speaker_cluster_service import WINDOW_SEC, embed_windows_for_span

        sr = 16000
        audio = np.zeros(sr * 7, dtype=np.float32)
        audio[: 2 * sr] = 0.9
        audio[2 * sr : 3 * sr] = 0.01
        audio[4 * sr : 5 * sr] = 0.55
        windows = embed_windows_for_span(
            audio,
            start_sec=0.0,
            end_sec=7.0,
            sample_rate=sr,
            max_windows=4,
        )
        self.assertGreaterEqual(len(windows), 2)
        self.assertTrue(all(clip.size <= int(round((WINDOW_SEC + 0.05) * sr)) for clip, _energy in windows))
        energies = [float(energy) for _clip, energy in windows]
        self.assertTrue(any(value > 0.7 for value in energies))
        self.assertTrue(any(0.3 < value < 0.7 for value in energies))

    def test_long_mixed_cue_does_not_force_one_speaker(self):
        from src.services.speaker_cluster_service import cluster_video_speakers
        from src.storage.dialogue_transcript_store import (
            load_dialogue_transcript,
            save_dialogue_transcript,
        )

        sr = 16000
        audio = np.zeros(sr * 6, dtype=np.float32)
        audio[: 2 * sr] = 0.9
        audio[2 * sr : 5 * sr] = -0.45

        def embed_fn(clip):
            vec = np.zeros(8, dtype=np.float32)
            if float(clip.mean()) > 0:
                vec[0] = 1.0
            else:
                vec[1] = 1.0
            return vec

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "vid",
                    [
                        {"start": 0.0, "end": 4.0, "text": "混", "asr_source": "asr", "speaker": ""},
                        {"start": 4.0, "end": 5.0, "text": "乙", "asr_source": "asr", "speaker": ""},
                    ],
                    video_path=os.path.join(tmp, "a.mp4"),
                    asr_source="asr",
                )
                result = cluster_video_speakers(
                    "vid",
                    waveform=audio,
                    sample_rate=sr,
                    embed_fn=embed_fn,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["speakers"], 2)
                payload = load_dialogue_transcript("vid")
                speakers = [row["speaker"] for row in payload["segments"]]
                self.assertTrue(speakers[0])
                self.assertTrue(speakers[1])
                self.assertNotEqual(speakers[0], speakers[1])

    def test_fills_empty_and_skips_manual_names(self):
        from src.services.speaker_cluster_service import cluster_video_speakers
        from src.storage.dialogue_transcript_store import (
            is_auto_speaker_label,
            load_dialogue_transcript,
            save_dialogue_transcript,
        )

        self.assertTrue(is_auto_speaker_label("声线1"))
        self.assertTrue(is_auto_speaker_label("Voice 2"))
        self.assertFalse(is_auto_speaker_label("柜台职员"))

        sr = 16000
        audio = np.zeros(sr * 6, dtype=np.float32)
        audio[: sr * 3] = 0.8
        audio[sr * 3 :] = -0.8

        def embed_fn(clip):
            vec = np.zeros(8, dtype=np.float32)
            if float(clip.mean()) > 0:
                vec[0] = 1.0
            else:
                vec[1] = 1.0
            return vec

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "vid",
                    [
                        {"start": 0.5, "end": 1.5, "text": "甲", "asr_source": "asr", "speaker": ""},
                        {"start": 1.6, "end": 2.6, "text": "乙", "asr_source": "asr", "speaker": "柜台职员"},
                        {"start": 3.5, "end": 4.5, "text": "丙", "asr_source": "asr", "speaker": "声线9"},
                    ],
                    video_path=os.path.join(tmp, "a.mp4"),
                    asr_source="asr",
                )
                result = cluster_video_speakers(
                    "vid",
                    waveform=audio,
                    sample_rate=sr,
                    embed_fn=embed_fn,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["skipped"], 1)
                self.assertEqual(result["labeled"], 2)
                self.assertEqual(result["speakers"], 2)
                payload = load_dialogue_transcript("vid")
                speakers = [row["speaker"] for row in payload["segments"]]
                self.assertEqual(speakers[1], "柜台职员")
                self.assertTrue(is_auto_speaker_label(speakers[0]))
                self.assertTrue(is_auto_speaker_label(speakers[2]))
                self.assertNotEqual(speakers[0], speakers[2])

    def test_uses_current_library_path_when_stored_file_is_gone(self):
        from src.services.speaker_cluster_service import cluster_video_speakers
        from src.storage.dialogue_transcript_store import (
            load_dialogue_transcript,
            save_dialogue_transcript,
        )

        sr = 16000
        audio = np.zeros(sr, dtype=np.float32)
        audio[:] = 0.5

        def embed_fn(clip):
            vec = np.zeros(4, dtype=np.float32)
            vec[0] = 1.0
            return vec

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            living = os.path.join(tmp, "new.mp4")
            stale = os.path.join(tmp, "old.mp4")
            with mock.patch(
                "src.storage.dialogue_transcript_store.get_data_storage_paths",
                return_value={"data_dir": data_dir},
            ):
                save_dialogue_transcript(
                    "vid",
                    [{"start": 0.0, "end": 0.8, "text": "甲", "asr_source": "asr", "speaker": ""}],
                    video_path=stale,
                    asr_source="asr",
                )
                with (
                    mock.patch(
                        "src.core.asr.audio_extract.extract_audio_mono_f32",
                        return_value=audio,
                    ) as extract,
                    mock.patch(
                        "src.services.understanding_service.resolve_video_context",
                        return_value={
                            "video_path": living,
                            "library_path": tmp,
                            "source_exists": True,
                        },
                    ),
                ):
                    result = cluster_video_speakers(
                        "vid",
                        video_path=stale,
                        sample_rate=sr,
                        embed_fn=embed_fn,
                    )
                self.assertTrue(result["ok"])
                extract.assert_called()
                called_path = extract.call_args[0][0]
                self.assertEqual(os.path.normcase(called_path), os.path.normcase(living))
                payload = load_dialogue_transcript("vid")
                self.assertEqual(os.path.normcase(payload["video_path"]), os.path.normcase(living))
