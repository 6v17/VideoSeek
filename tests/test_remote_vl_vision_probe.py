import json
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.core.understanding.components.remote_vl_caption import probe_remote_vl_vision


class RemoteVlVisionProbeTests(unittest.TestCase):
    def test_vision_probe_success(self):
        config = {
            "understanding": {
                "remote_vlm": {
                    "provider_mode": "cloud",
                    "provider_preset": "siliconflow",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "model": "Qwen/Qwen2.5-VL-7B-Instruct",
                    "api_keys": {"siliconflow": "sk-test"},
                }
            }
        }
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "OK"}}]}
        ).encode("utf-8")
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_response):
            result = probe_remote_vl_vision(
                config["understanding"]["remote_vlm"],
                timeout_sec=10.0,
            )
        self.assertTrue(result.get("ok"))


if __name__ == "__main__":
    unittest.main()
