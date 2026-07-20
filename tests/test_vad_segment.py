import os
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from src.core.asr.audio_extract import extract_audio_wav
from src.core.asr.vad_segment import (
    SpeechSegment,
    _split_oversized_segments,
    _timestamps_from_probs,
    resolve_silero_vad_model_path,
    segment_speech,
)


def _write_silent_wav(path: str, *, seconds: float = 0.5, sample_rate: int = 16000) -> None:
    frames = np.zeros(int(seconds * sample_rate), dtype=np.int16)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames.tobytes())


def _resolve_vad_model() -> str | None:
    explicit = os.environ.get("VIDEOSEEK_SILERO_VAD_PATH", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    return resolve_silero_vad_model_path()


class VadTimestampLogicTests(unittest.TestCase):
    def test_timestamps_detect_speech_island(self):
        # 20 windows * 512 / 16000 = 0.64s total; speech in middle windows
        probs = [0.05] * 4 + [0.9] * 8 + [0.05] * 8
        segments = _timestamps_from_probs(
            probs,
            audio_length_samples=20 * 512,
            sample_rate=16000,
            threshold=0.5,
            min_speech_duration_ms=100,
            max_speech_duration_s=30.0,
            min_silence_duration_ms=100,
            speech_pad_ms=0,
        )
        self.assertEqual(len(segments), 1)
        self.assertGreaterEqual(segments[0]["start"], 3 * 512)
        self.assertLessEqual(segments[0]["end"], 14 * 512)

    def test_split_oversized_segments(self):
        segments = [SpeechSegment(start_sec=0.0, end_sec=75.0)]
        split = _split_oversized_segments(segments, max_segment_duration_s=30.0)
        self.assertEqual(len(split), 3)
        self.assertAlmostEqual(split[0].duration_sec, 30.0)
        self.assertAlmostEqual(split[-1].end_sec, 75.0)


class VadPathResolveTests(unittest.TestCase):
    def test_resolve_prefers_explicit_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "silero_vad.onnx"
            model.write_bytes(b"fake")
            resolved = resolve_silero_vad_model_path(explicit_path=str(model))
            self.assertEqual(resolved, os.path.normpath(str(model)))

    def test_resolve_bundled_resource(self):
        bundled = Path(__file__).resolve().parents[1] / "resources" / "asr" / "silero_vad.onnx"
        if not bundled.is_file():
            self.skipTest("bundled silero_vad.onnx missing")
        resolved = resolve_silero_vad_model_path()
        self.assertEqual(resolved, os.path.normpath(str(bundled)))


class AudioExtractTests(unittest.TestCase):
    def test_extract_requires_existing_media(self):
        with self.assertRaises(FileNotFoundError):
            extract_audio_wav("Z:/missing/no-such-file.mp4")

    @unittest.skipUnless(
        os.path.isfile(str(Path(__file__).resolve().parents[1] / "test.wav")),
        "repo test.wav missing",
    )
    def test_extract_wav_passthrough_shape(self):
        from src.infra.ffmpeg_paths import has_ffmpeg

        if not has_ffmpeg():
            self.skipTest("ffmpeg unavailable")
        source = str(Path(__file__).resolve().parents[1] / "test.wav")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.wav")
            written = extract_audio_wav(source, out, sample_rate=16000)
            self.assertTrue(os.path.isfile(written))
            self.assertGreater(os.path.getsize(written), 0)
            with wave.open(written, "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getframerate(), 16000)
                self.assertEqual(handle.getsampwidth(), 2)

    @unittest.skipUnless(
        os.path.isfile(str(Path(__file__).resolve().parents[1] / "test.wav")),
        "repo test.wav missing",
    )
    def test_extract_mono_f32_pipe(self):
        from src.core.asr.audio_extract import extract_audio_mono_f32
        from src.infra.ffmpeg_paths import has_ffmpeg

        if not has_ffmpeg():
            self.skipTest("ffmpeg unavailable")
        source = str(Path(__file__).resolve().parents[1] / "test.wav")
        samples = extract_audio_mono_f32(source, sample_rate=16000)
        self.assertEqual(samples.dtype, np.float32)
        self.assertGreater(samples.size, 0)
        self.assertLessEqual(float(np.max(np.abs(samples))), 1.0 + 1e-3)


@unittest.skipUnless(_resolve_vad_model(), "silero_vad.onnx not available")
class SileroVadIntegrationTests(unittest.TestCase):
    def test_segment_speech_on_test_wav(self):
        root = Path(__file__).resolve().parents[1]
        wav = root / "test.wav"
        if not wav.is_file():
            self.skipTest("test.wav missing")
        segments = segment_speech(str(wav), model_path=_resolve_vad_model())
        self.assertIsInstance(segments, list)
        for item in segments:
            self.assertIsInstance(item, SpeechSegment)
            self.assertLess(item.start_sec, item.end_sec)
            self.assertGreaterEqual(item.start_sec, 0.0)

    def test_silent_wav_yields_no_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "silent.wav")
            _write_silent_wav(path, seconds=1.0)
            segments = segment_speech(path, model_path=_resolve_vad_model())
            self.assertEqual(segments, [])

    def test_silence_gate_skips_clear_silence(self):
        from src.core.asr.vad_segment import get_silero_vad_engine

        engine = get_silero_vad_engine(model_path=_resolve_vad_model())
        silent = np.zeros(16000, dtype=np.float32)
        probs = engine.infer_probs(silent, silence_rms=5e-4)
        self.assertTrue(all(p == 0.0 for p in probs))


if __name__ == "__main__":
    unittest.main()
