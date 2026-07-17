import unittest
from types import SimpleNamespace
from unittest import mock


class FasterWhisperEngineTests(unittest.TestCase):
    def test_resolve_whisper_device_prefers_cuda(self):
        from src.core.asr import faster_whisper_engine as engine

        engine._CUDA_UNUSABLE_REASON = ""
        with mock.patch.object(engine, "_cuda_device_count", return_value=1), mock.patch.object(
            engine, "_cuda_runtime_usable", return_value=(True, "")
        ):
            self.assertEqual(engine.resolve_whisper_device(), ("cuda", "float16"))
        engine._CUDA_UNUSABLE_REASON = ""
        with mock.patch.object(engine, "_cuda_device_count", return_value=0):
            self.assertEqual(engine.resolve_whisper_device(), ("cpu", "int8"))
        engine._CUDA_UNUSABLE_REASON = ""
        with mock.patch.object(engine, "_cuda_device_count", return_value=1), mock.patch.object(
            engine, "_cuda_runtime_usable", return_value=(False, "missing cublas64_12.dll")
        ):
            self.assertEqual(engine.resolve_whisper_device(), ("cpu", "int8"))

    def test_transcribe_wav_falls_back_to_cpu_on_cublas_error(self):
        from src.core.asr import faster_whisper_engine as engine

        cuda_model = mock.Mock()
        cuda_model.transcribe.side_effect = RuntimeError(
            "Library cublas64_12.dll is not found or cannot be loaded"
        )
        cpu_model = mock.Mock()
        cpu_model.transcribe.return_value = (
            iter([SimpleNamespace(start=0.0, end=1.0, text="ok")]),
            SimpleNamespace(language="zh"),
        )

        with mock.patch.object(engine, "get_whisper_model", return_value=cuda_model), mock.patch.object(
            engine, "resolve_installed_whisper_model_dir", return_value="D:/model"
        ), mock.patch.object(engine, "_load_cpu_model_locked", return_value=cpu_model) as load_cpu, mock.patch(
            "os.path.isfile", return_value=True
        ):
            rows = engine.transcribe_wav("D:/tmp/a.wav")

        self.assertEqual(rows[0]["text"], "ok")
        load_cpu.assert_called_once()
        cpu_model.transcribe.assert_called_once()

    def test_transcribe_wav_maps_segments(self):
        from src.core.asr import faster_whisper_engine as engine

        fake_segments = [
            SimpleNamespace(start=0.0, end=1.0, text=" hello "),
            SimpleNamespace(start=1.2, end=2.0, text=""),
            SimpleNamespace(start=2.0, end=3.5, text="world"),
        ]
        fake_info = SimpleNamespace(language="en")
        fake_model = mock.Mock()
        fake_model.transcribe.return_value = (iter(fake_segments), fake_info)

        with mock.patch.object(engine, "get_whisper_model", return_value=fake_model), mock.patch(
            "os.path.isfile", return_value=True
        ):
            rows = engine.transcribe_wav("D:/tmp/a.wav", language="auto")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "hello")
        self.assertEqual(rows[0]["language"], "en")
        self.assertEqual(rows[1]["text"], "world")
        self.assertEqual(rows[0]["asr_source"], engine.ASR_SOURCE_ID)
        fake_model.transcribe.assert_called_once()
        kwargs = fake_model.transcribe.call_args.kwargs
        self.assertTrue(kwargs.get("vad_filter"))
        self.assertIsNone(kwargs.get("language"))

    def test_get_whisper_model_requires_imported_dir(self):
        from src.core.asr import faster_whisper_engine as engine

        with mock.patch.object(engine, "is_faster_whisper_available", return_value=True), mock.patch.object(
            engine, "resolve_installed_whisper_model_dir", return_value=None
        ):
            with self.assertRaisesRegex(RuntimeError, "not imported"):
                engine.get_whisper_model()


if __name__ == "__main__":
    unittest.main()
