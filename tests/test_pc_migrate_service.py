import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import pc_migrate_service as svc


def _abs_key(path) -> str:
    """Compare paths the same way production code does (abspath, not Path.resolve).

    On some Windows runners TEMP uses 8.3 prefixes (``RUNNER~1``); ``Path.resolve()``
    expands them while ``os.path.abspath`` does not, so mixing the two flakes CI.
    """
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(path)))))


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
            self.assertEqual(_abs_key(saved[0]["data_root"]), _abs_key(target_root))
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
                    "src.storage.lance_store.remap_lance_library_roots",
                    return_value={"ok": True, "videos": 2, "updates": 2, "tables": 2},
                ) as lance_remap,
                patch(
                    "src.storage.dialogue_transcript_store.remap_transcript_library_roots",
                    return_value={"ok": True, "rows": 3},
                ),
                patch(
                    "src.storage.evidence_tags_store.remap_tag_library_roots",
                    return_value={"ok": True, "rows": 4},
                ),
                patch(
                    "src.services.search_scope.invalidate_searchable_path_index_cache",
                    return_value=None,
                ),
            ):
                result = svc.apply_library_path_remaps({str(old_lib): str(new_lib)}, config=cfg)

            self.assertTrue(result["ok"])
            self.assertEqual(result["remapped"], 1)
            self.assertEqual(result["lance_videos"], 2)
            self.assertEqual(result["transcript_rows"], 3)
            self.assertEqual(result["tag_rows"], 4)
            self.assertTrue(lance_remap.called)
            from src.storage.profile_library_store import load_profile_meta

            meta = load_profile_meta(str(profile_base))
            libs = meta.get("libraries") or {}
            self.assertEqual(len(libs), 1)
            only_key = next(iter(libs))
            self.assertEqual(_abs_key(only_key), _abs_key(new_lib))
            self.assertTrue(saved)
            self.assertEqual(
                _abs_key(saved[0]["search_scope_library_paths"][0]),
                _abs_key(new_lib),
            )
            self.assertEqual(
                _abs_key(saved[0]["download_target_library"]),
                _abs_key(new_lib),
            )


    def test_load_manifest_rejects_future_format_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "format": svc.PC_MIGRATE_FORMAT,
                        "format_version": svc.PC_MIGRATE_VERSION + 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                svc.load_pc_migrate_manifest(str(root))

    def test_rewrite_path_under_library_root(self):
        from src.storage.video_identity import rewrite_path_under_library_root

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            new.mkdir()
            media = old / "clip.mp4"
            media.write_bytes(b"x")
            rewritten = rewrite_path_under_library_root(str(media), str(old), str(new))
            self.assertEqual(_abs_key(rewritten), _abs_key(new / "clip.mp4"))
            # Also when the old root is already canonicalize()'d (normcase).
            from src.storage.video_identity import canonicalize_library_path

            rewritten_canon = rewrite_path_under_library_root(
                str(media),
                canonicalize_library_path(str(old)),
                str(new),
            )
            self.assertEqual(_abs_key(rewritten_canon), _abs_key(new / "clip.mp4"))
            self.assertIsNone(
                rewrite_path_under_library_root(str(root / "other" / "a.mp4"), str(old), str(new))
            )


class LanceLibraryRemapTests(unittest.TestCase):
    def test_remap_lance_library_roots_updates_stored_paths(self):
        import importlib.util

        if importlib.util.find_spec("lancedb") is None:
            self.skipTest("lancedb not installed")
        import numpy as np
        from src.storage.asset_store import save_metadata
        from src.storage.lance_search_index import get_lance_video_library_path, get_lance_video_location
        from src.storage.lance_store import remap_lance_library_roots, upsert_profile_video_vectors
        from src.storage.video_identity import canonicalize_library_path

        vectors = np.random.randn(2, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            old_lib = Path(tmp) / "videos_old"
            new_lib = Path(tmp) / "videos_new"
            old_lib.mkdir()
            new_lib.mkdir()
            media = old_lib / "clip.mp4"
            media.write_bytes(b"video")

            data_dir = Path(tmp) / "data"
            profile_dir = data_dir / "model_assets" / "openai-clip" / "vit-base-patch32"
            vector_dir = profile_dir / "vector"
            vector_dir.mkdir(parents=True)
            save_metadata({"libraries": {}}, str(profile_dir / "meta.json"))
            config = {
                "schema_version": 2,
                "vector_search_backend": "lance",
                "data_root": tmp,
                "meta_file": str(data_dir / "meta.json"),
                "models": {
                    "active_profile": "clip_test",
                    "profiles": [
                        {
                            "id": "clip_test",
                            "provider": "clip_onnx",
                            "runtime": {
                                "model_dir": str(Path(tmp) / "models"),
                                "model_variant": "vit-base-patch32",
                            },
                        }
                    ],
                },
            }
            data_dir.mkdir(exist_ok=True)
            from src.core.faiss_index import save_vectors

            save_vectors(vectors, timestamps, str(vector_dir / "vid_remap_vectors.npy"))
            result = upsert_profile_video_vectors(
                "vid_remap",
                config=config,
                library_path=str(old_lib),
                video_path=str(media),
            )
            self.assertFalse(result.get("error"))
            self.assertEqual(
                get_lance_video_library_path(str(profile_dir), "vid_remap"),
                canonicalize_library_path(str(old_lib)),
            )

            remap = remap_lance_library_roots(
                str(profile_dir),
                {canonicalize_library_path(str(old_lib)): str(new_lib)},
            )
            self.assertTrue(remap["ok"])
            self.assertGreaterEqual(remap["videos"], 1)
            self.assertEqual(
                get_lance_video_library_path(str(profile_dir), "vid_remap"),
                canonicalize_library_path(str(new_lib)),
            )
            _lib, stored_path = get_lance_video_location(str(profile_dir), "vid_remap")
            self.assertEqual(_abs_key(stored_path), _abs_key(new_lib / "clip.mp4"))


if __name__ == "__main__":
    unittest.main()
