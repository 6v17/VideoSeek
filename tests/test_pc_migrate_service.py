import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import pc_migrate_service as svc


class PcMigrateServiceTests(unittest.TestCase):
    def test_sanitize_config_redacts_secrets(self):
        raw = {
            "prefer_gpu": True,
            "api_key": "secret-value",
            "understanding": {"llm": {"api_keys": {"openai": "sk-test"}, "base_url": "https://x"}},
            "nested": {"authorization": "Bearer x"},
        }
        cleaned = svc._sanitize_config_for_export(raw)
        self.assertTrue(cleaned["prefer_gpu"])
        self.assertEqual(cleaned["api_key"], "")
        self.assertEqual(cleaned["understanding"]["llm"]["api_keys"], "")
        self.assertEqual(cleaned["understanding"]["llm"]["base_url"], "https://x")
        self.assertEqual(cleaned["nested"]["authorization"], "")

    def test_export_and_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "app"
            storage = data_root / "data"
            storage.mkdir(parents=True)
            (storage / "meta.json").write_text('{"libraries": {}}', encoding="utf-8")
            (storage / "vector").mkdir()
            (storage / "vector" / "sample.npy").write_bytes(b"vec")

            lib_a = root / "videos_a"
            lib_a.mkdir()
            lib_missing = root / "videos_gone"
            # intentionally not created

            config = {
                "data_root": str(data_root),
                "meta_file": str(storage / "meta.json"),
                "prefer_gpu": False,
                "api_key": "should-not-export",
                "search_scope_library_paths": [str(lib_a), str(lib_missing)],
                "download_target_library": str(lib_a),
                "model_dir": str(root / "models_local"),
                "ffmpeg_path": str(root / "ffmpeg.exe"),
            }

            export_dir = root / "migrate-pack"
            export_dir.mkdir()

            with (
                patch("src.services.pc_migrate_service.load_config", return_value=dict(config)),
                patch(
                    "src.services.pc_migrate_service.build_library_path_map",
                    return_value=[
                        {"path": str(lib_a), "source": "library", "exists": True, "file_count": 0},
                        {"path": str(lib_missing), "source": "library", "exists": False, "file_count": 0},
                    ],
                ),
                patch("src.services.pc_migrate_service.get_app_version", return_value="test"),
                patch(
                    "src.services.pc_migrate_service.get_configured_data_root",
                    return_value=str(data_root),
                ),
            ):
                exported = svc.export_pc_migrate_bundle(str(export_dir))

            self.assertTrue(exported["ok"])
            self.assertTrue((export_dir / "manifest.json").is_file())
            self.assertTrue((export_dir / "data" / "meta.json").is_file())
            snapshot = json.loads((export_dir / "config.snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot.get("api_key"), "")
            self.assertFalse(snapshot.get("prefer_gpu"))

            target_root = root / "new-pc"
            saved = []

            with (
                patch("src.services.pc_migrate_service.load_config", return_value=dict(config)),
                patch("src.services.pc_migrate_service.save_config", side_effect=saved.append),
                patch(
                    "src.services.pc_migrate_service.get_configured_data_root",
                    return_value=str(data_root),
                ),
                patch(
                    "src.services.pc_migrate_service.build_data_storage_paths",
                    side_effect=lambda dr: {
                        "meta_file": str(Path(dr) / "data" / "meta.json"),
                        "data_dir": str(Path(dr) / "data"),
                    },
                ),
            ):
                imported = svc.import_pc_migrate_bundle(
                    str(export_dir),
                    target_data_root=str(target_root),
                )

            self.assertTrue(imported["ok"])
            self.assertTrue((target_root / "data" / "meta.json").is_file())
            self.assertTrue((target_root / "data" / "vector" / "sample.npy").is_file())
            self.assertTrue(
                any(os.path.normcase(p) == os.path.normcase(str(lib_missing)) for p in imported["missing_libraries"])
            )
            self.assertTrue(saved)
            self.assertEqual(os.path.normcase(saved[0]["data_root"]), os.path.normcase(str(target_root.resolve())))
            self.assertEqual(saved[0]["model_dir"], config["model_dir"])
            self.assertEqual(saved[0]["ffmpeg_path"], config["ffmpeg_path"])
            self.assertFalse(saved[0]["prefer_gpu"])
            # Local secrets on the destination machine are preserved, not overwritten by empty export.
            self.assertEqual(saved[0]["api_key"], "should-not-export")

    def test_import_rejects_nonempty_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pack = root / "pack"
            (pack / "data").mkdir(parents=True)
            (pack / "data" / "meta.json").write_text("{}", encoding="utf-8")
            (pack / "manifest.json").write_text(
                json.dumps({"format": svc.PC_MIGRATE_FORMAT, "format_version": 1}),
                encoding="utf-8",
            )
            target = root / "busy"
            (target / "data").mkdir(parents=True)
            (target / "data" / "meta.json").write_text("{}", encoding="utf-8")

            with (
                patch("src.services.pc_migrate_service.load_config", return_value={"data_root": str(root)}),
                patch(
                    "src.services.pc_migrate_service.build_data_storage_paths",
                    side_effect=lambda dr: {
                        "meta_file": str(Path(dr) / "data" / "meta.json"),
                        "data_dir": str(Path(dr) / "data"),
                    },
                ),
            ):
                with self.assertRaises(ValueError):
                    svc.import_pc_migrate_bundle(str(pack), target_data_root=str(target))

    def test_apply_library_path_remaps_updates_meta_and_scopes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_lib = root / "old_lib"
            new_lib = root / "new_lib"
            new_lib.mkdir()
            profile_base = root / "profile"
            profile_base.mkdir()
            (profile_base / "meta.json").write_text(
                json.dumps(
                    {
                        "libraries": {
                            str(old_lib): {"files": {"a.mp4": {"vid": "v1"}}, "index_state": "ready"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            cfg = {
                "data_root": str(root),
                "meta_file": str(profile_base / "meta.json"),
                "search_scope_library_paths": [str(old_lib)],
                "download_target_library": str(old_lib),
            }
            saved = []

            with (
                patch("src.services.pc_migrate_service.load_config", return_value=dict(cfg)),
                patch("src.services.pc_migrate_service.save_config", side_effect=saved.append),
                patch(
                    "src.services.pc_migrate_service._iter_library_meta_bases",
                    return_value=[str(profile_base)],
                ),
                patch(
                    "src.services.search_scope.invalidate_searchable_path_index_cache",
                    return_value=None,
                ),
            ):
                result = svc.apply_library_path_remaps({str(old_lib): str(new_lib)}, config=cfg)

            self.assertTrue(result["ok"])
            self.assertEqual(result["remapped"], 1)
            from src.storage.profile_library_store import load_profile_meta

            meta = load_profile_meta(str(profile_base))
            libs = meta.get("libraries") or {}
            self.assertEqual(len(libs), 1)
            only_key = next(iter(libs))
            self.assertEqual(os.path.normcase(only_key), os.path.normcase(str(new_lib.resolve())))
            self.assertTrue(saved)
            self.assertEqual(
                os.path.normcase(saved[0]["search_scope_library_paths"][0]),
                os.path.normcase(str(new_lib.resolve())),
            )
            self.assertEqual(
                os.path.normcase(saved[0]["download_target_library"]),
                os.path.normcase(str(new_lib.resolve())),
            )


if __name__ == "__main__":
    unittest.main()
