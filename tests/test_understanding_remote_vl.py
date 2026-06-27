import io
import json
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.core.understanding.base import UnderstandingStoppedError
from src.core.understanding.components.remote_vl_caption import RemoteVlCaptionComponent


REMOTE_MANIFEST = {
    "kind": "understanding_component",
    "manifest_version": 1,
    "id": "vision/image_caption/qwen3-vl-remote",
    "modality": "vision",
    "task": "image_caption",
    "model_id": "qwen3-vl-remote",
    "delivery": "remote",
    "engine": {"registry_key": "vision.image_caption.qwen3_vl_remote"},
    "required_files": ["understanding_manifest.json"],
}


class RemoteVlCaptionTests(unittest.TestCase):
    def test_infer_returns_caption_text(self):
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        cv2.rectangle(image, (10, 10), (50, 50), (255, 255, 255), -1)
        response_body = {
            "choices": [{"message": {"content": "a white square on black background"}}],
        }
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps(response_body).encode("utf-8")
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)

        component = RemoteVlCaptionComponent(REMOTE_MANIFEST, "/tmp/qwen3-vl-remote")
        config = {
            "understanding": {
                "remote_vlm": {
                    "base_url": "http://127.0.0.1:1234/v1",
                    "model": "qwen3-vl-8b-instruct",
                    "prompt": "Describe the image.",
                    "timeout_sec": 30,
                    "max_tokens": 64,
                }
            }
        }
        with (
            patch("src.core.understanding.components.remote_vl_caption.load_config", return_value=config),
            patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen,
        ):
            result = component.infer(image)

        self.assertEqual(result["text"], "a white square on black background")
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:1234/v1/chat/completions")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen3-vl-8b-instruct")
        self.assertTrue(payload["messages"][0]["content"][0]["text"])
        self.assertNotIn("Authorization", request.headers)

    def test_infer_sends_authorization_when_api_key_configured(self):
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        response_body = {
            "choices": [{"message": {"content": "caption"}}],
        }
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps(response_body).encode("utf-8")
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)

        component = RemoteVlCaptionComponent(REMOTE_MANIFEST, "/tmp/qwen3-vl-remote")
        config = {
            "understanding": {
                "remote_vlm": {
                    "provider_mode": "cloud",
                    "provider_preset": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o",
                    "api_keys": {"openai": "sk-test-key"},
                    "prompt": "Describe the image.",
                    "timeout_sec": 30,
                    "max_tokens": 64,
                }
            }
        }
        with (
            patch("src.core.understanding.components.remote_vl_caption.load_config", return_value=config),
            patch("urllib.request.urlopen", return_value=fake_response) as mock_urlopen,
        ):
            component.infer(image)

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-key")

    def test_infer_empty_image_returns_empty_text(self):
        component = RemoteVlCaptionComponent(REMOTE_MANIFEST, "/tmp/qwen3-vl-remote")
        self.assertEqual(component.infer(None)["text"], "")

    def test_infer_raises_when_stop_requested_before_request(self):
        component = RemoteVlCaptionComponent(REMOTE_MANIFEST, "/tmp/qwen3-vl-remote")
        component.bind_should_stop_callback(lambda: True)
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        with self.assertRaises(UnderstandingStoppedError):
            component.infer(image)
