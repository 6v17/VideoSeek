import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("cv2", object())
sys.modules.setdefault("numpy", object())

from src.app import config as config_module


class ConfigMigrationTests(unittest.TestCase):
    def test_load_config_migrates_legacy_storage_to_user_app_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy_app"
            legacy_root.mkdir()
            legacy_data_dir = legacy_root / "data"
            legacy_data_dir.mkdir()
            (legacy_data_dir / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")

            legacy_config_file = legacy_root / "config.json"
            legacy_config_file.write_text(
                json.dumps(
                    {
                        "meta_file": "data/meta.json",
                        "vector_dir": "data/vector",
                        "index_dir": "data/index",
                        "cross_index_file": "data/global/cross_video_index.faiss",
                        "cross_vector_file": "data/global/cross_video_vectors.npy",
                        "cross_chunk_index_file": "data/global/cross_chunk_index.faiss",
                        "cross_chunk_vector_file": "data/global/cross_chunk_vectors.npy",
                        "remote_index_file": "data/remote/remote_index.faiss",
                        "remote_vector_file": "data/remote/remote_vectors.npy",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            user_root = root / "user_app"
            user_data_dir = user_root / "data"
            user_config_file = user_root / "config.json"
            default_config = {
                **config_module.DEFAULT_CONFIG,
                "meta_file": str(user_data_dir / "meta.json"),
                "vector_dir": str(user_data_dir / "vector"),
                "index_dir": str(user_data_dir / "index"),
                "cross_index_file": str(user_data_dir / "global" / "cross_video_index.faiss"),
                "cross_vector_file": str(user_data_dir / "global" / "cross_video_vectors.npy"),
                "cross_chunk_index_file": str(user_data_dir / "global" / "cross_chunk_index.faiss"),
                "cross_chunk_vector_file": str(user_data_dir / "global" / "cross_chunk_vectors.npy"),
                "remote_index_file": str(user_data_dir / "remote" / "remote_index.faiss"),
                "remote_vector_file": str(user_data_dir / "remote" / "remote_vectors.npy"),
            }
            legacy_default_config = {
                **default_config,
                "meta_file": str(legacy_data_dir / "meta.json"),
                "vector_dir": str(legacy_data_dir / "vector"),
                "index_dir": str(legacy_data_dir / "index"),
                "cross_index_file": str(legacy_data_dir / "global" / "cross_video_index.faiss"),
                "cross_vector_file": str(legacy_data_dir / "global" / "cross_video_vectors.npy"),
                "cross_chunk_index_file": str(legacy_data_dir / "global" / "cross_chunk_index.faiss"),
                "cross_chunk_vector_file": str(legacy_data_dir / "global" / "cross_chunk_vectors.npy"),
                "remote_index_file": str(legacy_data_dir / "remote" / "remote_index.faiss"),
                "remote_vector_file": str(legacy_data_dir / "remote" / "remote_vectors.npy"),
            }

            with (
                patch.object(config_module, "CONFIG_FILE", str(user_config_file)),
                patch.object(config_module, "LEGACY_CONFIG_FILE", str(legacy_config_file)),
                patch.object(config_module, "DATA_DIR", str(user_data_dir)),
                patch.object(config_module, "LEGACY_DATA_DIR", str(legacy_data_dir)),
                patch.object(config_module, "DEFAULT_CONFIG", default_config),
                patch.object(config_module, "LEGACY_DEFAULT_CONFIG", legacy_default_config),
            ):
                loaded = config_module.load_config()

            self.assertEqual(loaded["meta_file"], str(user_data_dir / "meta.json"))
            self.assertTrue((user_data_dir / "meta.json").exists())
            self.assertTrue(user_config_file.exists())

    def test_load_config_resets_invalid_legacy_runtime_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy_root = root / "legacy_app"
            legacy_root.mkdir()
            legacy_config_file = legacy_root / "config.json"
            legacy_config_file.write_text(
                json.dumps(
                    {
                        "model_dir": "Z:/nonexistent/VideoSeek/models",
                        "ffmpeg_path": "Z:/nonexistent/VideoSeek/bin/ffmpeg.exe",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            user_root = root / "user_app"
            user_config_file = user_root / "config.json"
            default_model_dir = str(user_root / "models")
            default_config = {**config_module.DEFAULT_CONFIG, "model_dir": default_model_dir}

            with (
                patch.object(config_module, "CONFIG_FILE", str(user_config_file)),
                patch.object(config_module, "LEGACY_CONFIG_FILE", str(legacy_config_file)),
                patch.object(config_module, "DEFAULT_CONFIG", default_config),
                patch("src.app.config.get_default_model_dir", return_value=default_model_dir),
            ):
                loaded = config_module.load_config()

            self.assertEqual(loaded["model_dir"], default_model_dir)
            self.assertEqual(loaded["ffmpeg_path"], "")
            self.assertTrue(user_config_file.exists())


if __name__ == "__main__":
    unittest.main()
