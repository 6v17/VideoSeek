import json
import unittest
from unittest.mock import patch

from src.services.asr_settings import probe_remote_asr_draft
from src.services.llm_settings import probe_remote_llm_draft


class OpenAiCompatLlmAsrProbeTests(unittest.TestCase):
    def test_llm_draft_cloud_unlisted_chat_ok(self):
        catalog_body = json.dumps({"data": [{"id": "other-model"}]}).encode("utf-8")
        draft = {
            "provider_mode": "cloud",
            "provider_preset": "siliconflow",
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "deepseek-ai/DeepSeek-V3",
            "api_keys": {"siliconflow": "sk-test"},
        }

        with (
            patch(
                "src.services.cancellable_http.urlopen_read_with_deadline",
                return_value=(200, catalog_body),
            ),
            patch(
                "src.services.cancellable_http.urlopen_json_with_stop",
                return_value={"choices": [{"message": {"content": "OK"}}]},
            ),
        ):
            probe = probe_remote_llm_draft(draft, timeout_sec=20.0, chat_probe=True)

        self.assertTrue(probe.get("reachable"))
        self.assertTrue(probe.get("model_available"))
        self.assertTrue(probe.get("chat_probed"))
        self.assertTrue(probe.get("model_unlisted"))

    def test_asr_draft_cloud_unlisted_speech_ok(self):
        catalog_body = json.dumps({"data": [{"id": "other-asr"}]}).encode("utf-8")
        draft = {
            "provider_mode": "cloud",
            "provider_preset": "siliconflow",
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "FunAudioLLM/SenseVoiceSmall",
            "api_keys": {"siliconflow": "sk-test"},
        }

        with (
            patch(
                "src.services.cancellable_http.urlopen_read_with_deadline",
                return_value=(200, catalog_body),
            ),
            patch(
                "src.core.asr.transcribe_remote.probe_remote_asr_transcription",
                return_value={"ok": True, "detail": "silent clip accepted"},
            ),
        ):
            probe = probe_remote_asr_draft(draft, timeout_sec=25.0, asr_probe=True)

        self.assertTrue(probe.get("reachable"))
        self.assertTrue(probe.get("model_available"))
        self.assertTrue(probe.get("asr_probed"))
        self.assertTrue(probe.get("model_unlisted"))

    def test_llm_local_catalog_miss_without_chat_probe(self):
        catalog_body = json.dumps({"data": [{"id": "local-other"}]}).encode("utf-8")
        draft = {
            "provider_mode": "local",
            "provider_preset": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "missing-model",
            "api_keys": {},
        }

        with patch("src.services.openai_compat_probe.urllib.request.urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = catalog_body
            probe = probe_remote_llm_draft(draft, timeout_sec=20.0, chat_probe=False)

        self.assertEqual(probe.get("error_code"), "model_not_found")
        self.assertFalse(probe.get("model_available"))


if __name__ == "__main__":
    unittest.main()
