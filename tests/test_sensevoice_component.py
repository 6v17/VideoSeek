import json
import os
import time
import unittest

from src.core.asr.sensevoice_postprocess import (
    extract_language,
    extract_tags,
    is_meaningful_transcript,
    normalize_transcript,
    rich_transcription_postprocess,
)
from src.core.understanding.registry import build_understanding_component
from src.services.understanding_resource_service import validate_component_manifest


SENSEVOICE_MANIFEST = {
    "kind": "understanding_component",
    "manifest_version": 1,
    "id": "audio/speech_to_text/sensevoice-small",
    "modality": "audio",
    "task": "speech_to_text",
    "model_id": "sensevoice-small",
    "display_name": "SenseVoice Small ASR (ONNX FP32)",
    "install_relpath": "components/audio/speech_to_text/sensevoice-small",
    "input_kind": "chunk_audio",
    "output_kind": "transcript",
    "engine": {"registry_key": "audio.speech_to_text.sensevoice_small"},
    "required_files": [
        "model.onnx",
        "tokens.json",
        "am.mvn",
        "config.yaml",
        "configuration.json",
    ],
    "files": {"model": "model.onnx"},
    "runtime": {"prefer_gpu": False, "provider_hints": ["CPUExecutionProvider"]},
    "params": {"quantize": False, "language": "auto", "use_itn": True},
}

RAW_SAMPLE = (
    "<|ja|><|EMO_UNKNOWN|><|BGM|><|withitn|>"
    "彼を駆り立てるこの世のすてを破壊しろと この番組はご覧のスポンサーの提供でお送りしました。"
)


class SenseVoicePostprocessTests(unittest.TestCase):
    def test_extract_language_and_tags(self):
        self.assertEqual(extract_language(RAW_SAMPLE), "ja")
        self.assertIn("BGM", extract_tags(RAW_SAMPLE))

    def test_rich_transcription_postprocess_strips_control_tokens(self):
        cleaned = rich_transcription_postprocess(RAW_SAMPLE)
        self.assertNotIn("<|ja|>", cleaned)
        self.assertIn("スポンサー", cleaned)

    def test_normalize_transcript_payload(self):
        payload = normalize_transcript(RAW_SAMPLE, use_itn=True)
        self.assertEqual(payload["language"], "ja")
        self.assertTrue(is_meaningful_transcript(payload))


class SenseVoiceManifestTests(unittest.TestCase):
    def test_manifest_validation_shape(self):
        validated = validate_component_manifest(SENSEVOICE_MANIFEST)
        self.assertEqual(validated["id"], "audio/speech_to_text/sensevoice-small")
        self.assertEqual(validated["output_kind"], "transcript")


def _resolve_model_dir() -> str | None:
    resolved = _resolve_model_variant()
    return resolved[0] if resolved else None


def _resolve_model_variant() -> tuple[str, bool] | None:
    explicit = os.environ.get("VIDEOSEEK_SENSEVOICE_MODEL_DIR", "").strip()
    if explicit:
        if os.path.isfile(os.path.join(explicit, "model_quant.onnx")):
            return explicit, True
        if os.path.isfile(os.path.join(explicit, "model.onnx")):
            return explicit, False

    for candidate, quantize in (
        (r"C:\Users\LiuWei\Desktop\sensevoice\int8", True),
        (r"C:\Users\LiuWei\Desktop\sensevoice\fp32", False),
    ):
        expected = "model_quant.onnx" if quantize else "model.onnx"
        if os.path.isfile(os.path.join(candidate, expected)):
            return candidate, quantize
    return None


@unittest.skipUnless(_resolve_model_dir(), "SenseVoice ONNX model directory is not available")
class SenseVoiceOnnxIntegrationTests(unittest.TestCase):
    def test_transcribe_test_segment_wav(self):
        from src.core.asr.sensevoice_engine import SenseVoiceOnnxEngine, clear_sensevoice_engine_cache

        variant = _resolve_model_variant()
        assert variant is not None
        model_dir, quantize = variant
        wav_path = os.path.join(os.path.dirname(__file__), "..", "test_segment.wav")
        wav_path = os.path.normpath(wav_path)
        self.assertTrue(os.path.isfile(wav_path), wav_path)

        clear_sensevoice_engine_cache()
        start = time.time()
        engine = SenseVoiceOnnxEngine(model_dir, quantize=quantize, prefer_gpu=False)
        load_elapsed = time.time() - start
        result = engine.transcribe(wav_path, language="auto", use_itn=True)

        self.assertLess(load_elapsed, 30.0)
        self.assertEqual(result["language"], "ja")
        self.assertTrue(result["meaningful"])
        self.assertIn("スポンサー", result["text"])

    def test_build_understanding_component_transcribe(self):
        import tempfile

        from src.core.asr.sensevoice_engine import clear_sensevoice_engine_cache

        variant = _resolve_model_variant()
        assert variant is not None
        model_dir, quantize = variant
        wav_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "test_segment.wav"))

        manifest = dict(SENSEVOICE_MANIFEST)
        if quantize:
            manifest["required_files"] = [
                "model_quant.onnx",
                "tokens.json",
                "am.mvn",
                "config.yaml",
                "configuration.json",
            ]
            manifest["files"] = {"model": "model_quant.onnx"}
            manifest["params"] = {"quantize": True, "language": "auto", "use_itn": True}
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = os.path.join(temp_dir, "understanding_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)

            for name in manifest["required_files"]:
                source = os.path.join(model_dir, name)
                if not os.path.isfile(source):
                    self.skipTest(f"Missing model file for integration copy: {source}")
                target = os.path.join(temp_dir, name)
                with open(source, "rb") as src, open(target, "wb") as dst:
                    dst.write(src.read())

            clear_sensevoice_engine_cache()
            component = build_understanding_component(
                validate_component_manifest(manifest, component_dir=temp_dir),
                component_dir=temp_dir,
            )
            payload = component.transcribe_file(wav_path)
            self.assertEqual(payload["language"], "ja")
            self.assertIn("スポンサー", payload["text"])


if __name__ == "__main__":
    unittest.main()
