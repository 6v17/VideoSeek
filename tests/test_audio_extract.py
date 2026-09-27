import subprocess
import unittest
from unittest.mock import patch

from src.core.asr.audio_extract import _run_ffmpeg


class AudioExtractTests(unittest.TestCase):
    def test_run_ffmpeg_maps_timeout_to_runtime_error(self):
        with patch(
            "src.core.asr.audio_extract.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1.0),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                _run_ffmpeg(["ffmpeg", "-version"], timeout_sec=1.0)
        self.assertIn("timed out", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
