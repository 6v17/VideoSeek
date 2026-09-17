import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os_environ_note = True
import os
os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


class ChineseClipTokenizerTests(unittest.TestCase):
    def test_do_lower_case_defaults_true(self):
        from src.core.chinese_clip_provider import ChineseCLIPOnnxEngine

        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(ChineseCLIPOnnxEngine._tokenizer_do_lower_case(tmp))

    def test_do_lower_case_reads_pack_config(self):
        from src.core.chinese_clip_provider import ChineseCLIPOnnxEngine

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "tokenizer_config.json").write_text(
                json.dumps({"do_lower_case": False}),
                encoding="utf-8",
            )
            self.assertFalse(ChineseCLIPOnnxEngine._tokenizer_do_lower_case(tmp))

    def test_build_tokenizer_lowercases_english(self):
        from src.core.chinese_clip_provider import ChineseCLIPOnnxEngine

        pack = Path(r"D:\PycharmProjects\VideoSeek\models\chinese-clip\vit-large-patch14")
        if not (pack / "vocab.txt").is_file():
            self.skipTest("local Chinese CLIP pack not present")
        tok = ChineseCLIPOnnxEngine._build_tokenizer(str(pack))
        self.assertEqual(
            tok.encode("a person with a big smile").ids,
            tok.encode("A person with a big smile").ids,
        )


if __name__ == "__main__":
    unittest.main()
