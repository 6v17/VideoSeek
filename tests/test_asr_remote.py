from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.core.asr.audio_io import write_wav_mono_f32
from src.core.asr.transcribe_remote import parse_transcription_payload
from src.services.asr_index_service import is_hardsub_ocr_source, pack_speech_windows
from src.services.asr_settings import (
    finalize_remote_asr_settings,
    pick_available_asr_model,
)
from src.services.understanding_resource_service import normalize_understanding_config


class AsrSettingsTests(unittest.TestCase):
    def test_openai_preset_fills_url(self):
        settings = finalize_remote_asr_settings(
            {"provider_mode": "cloud", "provider_preset": "openai", "api_keys": {"openai": "sk-test"}}
        )
        self.assertEqual(settings["base_url"], "https://api.openai.com/v1")
        self.assertEqual(settings["model"], "whisper-1")
        self.assertEqual(settings["api_keys"]["openai"], "sk-test")

    def test_keeps_custom_model_override(self):
        settings = finalize_remote_asr_settings(
            {
                "provider_mode": "cloud",
                "provider_preset": "openai",
                "model": "whisper-large-v3",
                "api_keys": {"openai": "sk-test"},
            }
        )
        self.assertEqual(settings["model"], "whisper-large-v3")
        self.assertEqual(settings["base_url"], "https://api.openai.com/v1")

    def test_custom_keeps_url(self):
        settings = finalize_remote_asr_settings(
            {
                "provider_mode": "local",
                "provider_preset": "custom",
                "base_url": "http://127.0.0.1:9000/v1",
                "model": "Systran/faster-whisper-large-v3",
            }
        )
        self.assertEqual(settings["base_url"], "http://127.0.0.1:9000/v1")
        self.assertEqual(settings["model"], "Systran/faster-whisper-large-v3")

    def test_picks_whisper_not_chat(self):
        chosen = pick_available_asr_model(
            "whisper-1",
            ["gpt-4o", "whisper-large-v3", "whisper-1"],
        )
        self.assertEqual(chosen, "whisper-1")
        chosen = pick_available_asr_model("missing", ["gpt-4o-mini", "whisper-large-v3"])
        self.assertEqual(chosen, "whisper-large-v3")

    def test_dashscope_preset_uses_qwen_audio(self):
        settings = finalize_remote_asr_settings(
            {"provider_mode": "cloud", "provider_preset": "dashscope", "api_keys": {"dashscope": "sk-test"}}
        )
        self.assertEqual(settings["base_url"], "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(settings["model"], "qwen-audio-3.0-asr-flash")

    def test_keeps_dashscope_model_override(self):
        settings = finalize_remote_asr_settings(
            {
                "provider_mode": "cloud",
                "provider_preset": "dashscope",
                "model": "qwen-audio-3.0-asr-flash",
                "api_keys": {"dashscope": "sk-test"},
            }
        )
        self.assertEqual(settings["model"], "qwen-audio-3.0-asr-flash")

    def test_normalize_understanding_config_includes_asr(self):
        cfg = normalize_understanding_config({"understanding": {}})
        self.assertIn("remote_asr", cfg["understanding"])
        self.assertEqual(cfg["understanding"]["remote_asr"]["provider_preset"], "openai")


class AsrPackTests(unittest.TestCase):
    def test_merges_nearby_spans(self):
        windows = pack_speech_windows([(0.0, 2.0), (2.4, 5.0), (20.0, 22.0)], duration_sec=30.0)
        self.assertEqual(windows[0], (0.0, 5.0))
        self.assertEqual(windows[-1], (20.0, 22.0))

    def test_splits_oversize_span(self):
        windows = pack_speech_windows([(0.0, 70.0)], duration_sec=70.0, max_window_sec=28.0)
        self.assertEqual(windows[0], (0.0, 28.0))
        self.assertEqual(windows[1], (28.0, 56.0))
        self.assertEqual(windows[2], (56.0, 70.0))

    def test_empty_vad_chunks_full_duration(self):
        windows = pack_speech_windows([], duration_sec=40.0, max_window_sec=28.0)
        self.assertEqual(windows, [(0.0, 28.0), (28.0, 40.0)])

    def test_ocr_source_detection(self):
        self.assertTrue(is_hardsub_ocr_source("vision/ocr/rapidocr-zh"))
        self.assertFalse(is_hardsub_ocr_source("asr"))


class AsrParseTests(unittest.TestCase):
    def test_offsets_verbose_segments(self):
        rows = parse_transcription_payload(
            {
                "language": "zh",
                "segments": [
                    {"start": 0.2, "end": 1.1, "text": "你好"},
                    {"start": 1.2, "end": 2.0, "text": "世界"},
                ],
            },
            offset_sec=10.0,
        )
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["start"], 10.2)
        self.assertAlmostEqual(rows[0]["end"], 11.1)
        self.assertEqual(rows[0]["text"], "你好")
        self.assertEqual(rows[0]["asr_source"], "asr")
        self.assertAlmostEqual(rows[1]["start"], 11.2)

    def test_falls_back_to_text_when_no_segments(self):
        rows = parse_transcription_payload({"text": "hello there", "duration": 1.5}, offset_sec=4.0)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["start"], 4.0)
        self.assertAlmostEqual(rows[0]["end"], 5.5)
        self.assertEqual(rows[0]["text"], "hello there")

    def test_parses_dashscope_chat_completion(self):
        rows = parse_transcription_payload(
            {
                "object": "chat.completion",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "欢迎使用阿里云。",
                            "annotations": [{"type": "audio_info", "language": "zh"}],
                        }
                    }
                ],
            },
            offset_sec=12.0,
            duration_sec=3.5,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "欢迎使用阿里云。")
        self.assertEqual(rows[0]["language"], "zh")
        self.assertAlmostEqual(rows[0]["start"], 12.0)
        self.assertAlmostEqual(rows[0]["end"], 15.5)

    def test_parses_dashscope_native_sentence(self):
        rows = parse_transcription_payload(
            {
                "output": {
                    "text": "Hello World，这里是阿里巴巴语音实验室。",
                    "sentence": {
                        "begin_time": 760,
                        "end_time": 3800,
                        "text": "Hello World，这里是阿里巴巴语音实验室。",
                    },
                },
                "usage": {"duration": 4},
            },
            offset_sec=10.0,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "Hello World，这里是阿里巴巴语音实验室。")
        self.assertAlmostEqual(rows[0]["start"], 10.76)
        self.assertAlmostEqual(rows[0]["end"], 13.8)


class AsrDashscopeRouteTests(unittest.TestCase):
    def test_dashscope_host_uses_chat_asr(self):
        from src.core.asr.transcribe_remote import _http_error_message, uses_dashscope_chat_asr

        self.assertTrue(
            uses_dashscope_chat_asr(
                {"provider_preset": "dashscope", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"}
            )
        )
        self.assertFalse(
            uses_dashscope_chat_asr({"provider_preset": "openai", "base_url": "https://api.openai.com/v1"})
        )
        message = _http_error_message(
            404,
            "",
            url="https://dashscope.aliyuncs.com/compatible-mode/v1/audio/transcriptions",
        )
        self.assertIn("chat/completions", message)

    def test_qwen_audio_uses_native_generation(self):
        from src.core.asr.transcribe_remote import (
            build_dashscope_input_audio,
            build_dashscope_native_payload,
            dashscope_native_generation_url,
            uses_dashscope_native_audio_asr,
        )

        self.assertTrue(
            uses_dashscope_native_audio_asr(
                {
                    "provider_preset": "dashscope",
                    "model": "qwen-audio-3.0-asr-flash",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                }
            )
        )
        self.assertFalse(
            uses_dashscope_native_audio_asr(
                {
                    "provider_preset": "dashscope",
                    "model": "qwen3-asr-flash",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                }
            )
        )
        self.assertEqual(
            dashscope_native_generation_url("https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        )
        audio = build_dashscope_input_audio(b"RIFF", filename="clip.wav", content_type="audio/wav")
        self.assertEqual(audio["format"], "wav")
        self.assertTrue(str(audio["data"]).startswith("data:audio/wav;base64,"))
        payload = build_dashscope_native_payload(
            b"RIFF",
            model="qwen-audio-3.0-asr-flash",
            filename="clip.wav",
            content_type="audio/wav",
            language="zh",
        )
        self.assertEqual(payload["parameters"]["format"], "wav")
        self.assertEqual(payload["parameters"]["sample_rate"], "16000")
        self.assertEqual(payload["parameters"]["language_hints"], ["zh"])
        data = payload["input"]["messages"][0]["content"][0]["input_audio"]["data"]
        self.assertTrue(str(data).startswith("data:audio/wav;base64,"))

    def test_format_empty_error_is_readable(self):
        from src.core.asr.transcribe_remote import _http_error_message

        message = _http_error_message(
            400,
            '{"error":{"message":"format is empty","code":"UNSUPPORTED_FORMAT"}}',
        )
        self.assertIn("format=wav", message)
        self.assertNotEqual(message[:1], "{")

    def test_no_words_is_empty_not_fatal(self):
        from src.core.asr.transcribe_remote import (
            _ensure_asr_success,
            _http_error_message,
            is_empty_asr_result,
            parse_transcription_payload,
        )

        body = '{"request_id":"abc","code":"CLIENT_ERROR","message":"ASR_RESPONSE_HAVE_NO_WORDS"}'
        self.assertTrue(is_empty_asr_result(body))
        self.assertIn("没有识别到语音", _http_error_message(400, body))
        payload = _ensure_asr_success({"code": "CLIENT_ERROR", "message": "ASR_RESPONSE_HAVE_NO_WORDS"})
        self.assertEqual(parse_transcription_payload(payload), [])


class AsrWavTests(unittest.TestCase):
    def test_write_wav_roundtrip_header(self):
        import wave

        samples = np.zeros(1600, dtype=np.float32)
        samples[10:20] = 0.5
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.wav"
            write_wav_mono_f32(str(path), samples, sample_rate=16000)
            with wave.open(str(path), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getframerate(), 16000)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertEqual(handle.getnframes(), 1600)


class AsrSkipOcrTests(unittest.TestCase):
    def test_skips_existing_ocr_unless_forced(self):
        from src.services.asr_index_service import transcribe_video_asr

        existing = {
            "video_id": "vid1",
            "video_path": "C:/missing.mp4",
            "asr_source": "vision/ocr/rapidocr-zh",
            "segment_count": 3,
            "segments": [{"start": 0, "end": 1, "text": "hi"}],
        }
        with patch("src.services.asr_index_service.load_dialogue_transcript", return_value=existing):
            result = transcribe_video_asr("vid1", force=False)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "ocr_exists")


class AsrNoWordsWindowTests(unittest.TestCase):
    def test_no_words_window_is_skipped(self):
        from src.services.asr_index_service import _transcribe_span

        waveform = np.zeros(int(16000 * 1.5), dtype=np.float32)
        waveform[200:400] = 0.2
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "src.services.asr_index_service.transcribe_wav_bytes",
                side_effect=RuntimeError(
                    '{"code":"CLIENT_ERROR","message":"ASR_RESPONSE_HAVE_NO_WORDS"}'
                ),
            ):
                rows = _transcribe_span(
                    waveform,
                    0.0,
                    1.2,
                    settings={},
                    language="",
                    tmp_dir=tmp,
                    clip_index=0,
                    stop_callback=lambda: False,
                )
        self.assertEqual(rows, [])


class AsrTransientErrorTests(unittest.TestCase):
    def test_detects_connection_reset_10054(self):
        from src.core.asr.transcribe_remote import format_asr_error, is_transient_asr_error

        raw = "<urlopen error [Errno 10054] 远程主机强迫关闭了一个现有的连接。>"
        self.assertTrue(is_transient_asr_error(raw))
        message = format_asr_error(raw)
        self.assertIn("不是整段", message)
        self.assertIn("10054", message)

    def test_http_429_is_transient(self):
        from src.core.asr.transcribe_remote import is_transient_asr_error

        error = urllib.error.HTTPError("https://example.com", 429, "Too Many Requests", hdrs=None, fp=None)
        self.assertTrue(is_transient_asr_error(error))


if __name__ == "__main__":
    unittest.main()
