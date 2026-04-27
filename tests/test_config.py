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
                "data_root": str(user_root),
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

    def test_load_config_normalizes_sampling_settings_for_legacy_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_root = root / "user_app"
            user_root.mkdir()
            user_config_file = user_root / "config.json"
            user_config_file.write_text(
                json.dumps(
                    {
                        "fps": "0",
                        "sampling_fps_mode": "adaptive",
                        "sampling_fps_rules": "0-10m=2\uFF1B10m-30m=1",
                        "dynamic_fps_reference_duration": "0",
                        "dynamic_fps_min": "bad",
                        "dynamic_fps_max": "0.1",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                loaded = config_module.load_config()

            self.assertEqual(loaded["fps"], 1)
            self.assertEqual(loaded["sampling_fps_mode"], "dynamic")
            self.assertEqual(loaded["sampling_fps_rules"], "0-10m=2; 10m-30m=1")
            self.assertNotIn("dynamic_fps_reference_duration", loaded)
            self.assertNotIn("dynamic_fps_min", loaded)
            self.assertNotIn("dynamic_fps_max", loaded)

    def test_save_config_preserves_fractional_fps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                config_module.save_config({"fps": 1.5})
                loaded = config_module.load_config()

            self.assertEqual(loaded["fps"], 1.5)

    def test_load_config_uses_dynamic_sampling_mode_by_default_for_new_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"
            missing_legacy_config = root / "missing-legacy.json"

            with (
                patch.object(config_module, "CONFIG_FILE", str(user_config_file)),
                patch.object(config_module, "LEGACY_CONFIG_FILE", str(missing_legacy_config)),
            ):
                loaded = config_module.load_config()

            self.assertEqual(loaded["data_root"], str(root))
            self.assertEqual(loaded["sampling_fps_mode"], "dynamic")
            self.assertEqual(
                loaded["sampling_fps_rules"],
                "0-10m=2; 10m-60m=1; 60m-=0.5",
            )

    def test_load_config_infers_data_root_from_existing_storage_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"
            user_config_file.write_text(
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

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                loaded = config_module.load_config()

            self.assertEqual(loaded["data_root"], str(root))
            self.assertEqual(loaded["meta_file"], str(root / "data" / "meta.json"))

    def test_save_config_derives_storage_paths_from_data_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"
            target_root = root / "data_home"

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                config_module.save_config({"data_root": str(target_root)})
                loaded = config_module.load_config()

            self.assertEqual(loaded["data_root"], str(target_root))
            self.assertEqual(loaded["meta_file"], str(target_root / "data" / "meta.json"))
            self.assertEqual(loaded["vector_dir"], str(target_root / "data" / "vector"))

    def test_get_data_storage_paths_includes_remote_cache_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"
            target_root = root / "data_home"

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                config_module.save_config({"data_root": str(target_root)})
                paths = config_module.get_data_storage_paths()

            self.assertEqual(paths["data_dir"], str(target_root / "data"))
            self.assertEqual(paths["remote_dir"], str(target_root / "data" / "remote"))
            self.assertEqual(paths["preview_cache_dir"], str(target_root / "data" / "cache"))
            self.assertEqual(paths["mobile_upload_dir"], str(target_root / "data" / "mobile_uploads"))
            self.assertEqual(paths["remote_build_cache_dir"], str(target_root / "data" / "remote_build_cache"))
            self.assertEqual(paths["link_cache_dir"], str(target_root / "data" / "link_cache"))
            self.assertEqual(paths["remote_build_report_file"], str(target_root / "data" / "remote" / "build_report.json"))

    def test_save_config_preserves_sampling_rules_in_fixed_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                config_module.save_config(
                    {
                        "fps": 1,
                        "sampling_fps_mode": "fixed",
                        "sampling_fps_rules": "0-10m=2; 10m-60m=1; 60m-=0.5",
                    }
                )
                loaded = config_module.load_config()

            self.assertEqual(loaded["sampling_fps_mode"], "fixed")
            self.assertEqual(loaded["sampling_fps_rules"], "0-10m=2; 10m-60m=1; 60m-=0.5")

    def test_save_config_clamps_settings_to_safe_ranges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                config_module.save_config(
                    {
                        "search_top_k": 999,
                        "preview_seconds": 0,
                        "preview_width": 99999,
                        "preview_height": -1,
                        "thumb_width": 1,
                        "thumb_height": 999,
                        "remote_max_frames": 5,
                        "embedding_batch_size": 999,
                        "similarity_threshold": 9,
                        "max_chunk_duration": 0,
                        "min_chunk_size": 999,
                    }
                )
                loaded = config_module.load_config()

            self.assertEqual(loaded["search_top_k"], 200)
            self.assertEqual(loaded["preview_seconds"], 2)
            self.assertEqual(loaded["preview_width"], 1920)
            self.assertEqual(loaded["preview_height"], 90)
            self.assertEqual(loaded["thumb_width"], 80)
            self.assertEqual(loaded["thumb_height"], 320)
            self.assertEqual(loaded["remote_max_frames"], 200)
            self.assertEqual(loaded["embedding_batch_size"], 64)
            self.assertEqual(loaded["similarity_threshold"], 1.0)
            self.assertEqual(loaded["max_chunk_duration"], 1.0)
            self.assertEqual(loaded["min_chunk_size"], 50)

    def test_save_config_normalizes_invalid_enums(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                config_module.save_config(
                    {
                        "chunk_similarity_mode": "bad",
                        "search_mode": "oops",
                        "theme": "blue",
                        "language": "jp",
                    }
                )
                loaded = config_module.load_config()

            self.assertEqual(loaded["chunk_similarity_mode"], config_module.DEFAULT_CONFIG["chunk_similarity_mode"])
            self.assertEqual(loaded["search_mode"], config_module.DEFAULT_CONFIG["search_mode"])
            self.assertEqual(loaded["theme"], config_module.DEFAULT_CONFIG["theme"])
            self.assertEqual(loaded["language"], config_module.DEFAULT_CONFIG["language"])

    def test_load_config_coerces_string_booleans(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_config_file = root / "config.json"
            user_config_file.write_text(
                json.dumps(
                    {
                        "prefer_gpu": "false",
                        "auto_cleanup_missing_files": "true",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with patch.object(config_module, "CONFIG_FILE", str(user_config_file)):
                loaded = config_module.load_config()

            self.assertFalse(loaded["prefer_gpu"])
            self.assertTrue(loaded["auto_cleanup_missing_files"])

    def test_default_config_includes_sampling_rules_template(self):
        self.assertEqual(config_module.DEFAULT_CONFIG["sampling_fps_rules"], "0-10m=2; 10m-60m=1; 60m-=0.5")


if __name__ == "__main__":
    unittest.main()
