"""Global subtitle library registry is independent of CLIP profile libraries."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.services import library_service, subtitle_library_service
from src.storage import dialogue_transcript_store, subtitle_library_store
from src.utils import canonicalize_library_path


class SubtitleLibraryServiceTests(unittest.TestCase):
    def test_add_subtitle_library_does_not_touch_clip_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            clip_meta = {
                "schema_version": 2,
                "libraries": {
                    canonicalize_library_path(os.path.join(tmp, "clip_only")): {
                        "files": {},
                        "last_scan": "",
                        "index_state": "pending",
                    }
                },
            }
            video_root = os.path.join(tmp, "videos")
            os.makedirs(video_root, exist_ok=True)
            with open(os.path.join(video_root, "a.mp4"), "wb") as handle:
                handle.write(b"fake")

            config = {"data_root": tmp, "meta_file": os.path.join(data_dir, "meta.json")}

            dialogue_dir = os.path.join(data_dir, "dialogue")
            with (
                patch.object(subtitle_library_service, "load_config", return_value=config),
                patch.object(library_service, "load_config", return_value=config),
                patch.object(library_service, "load_model_metadata", return_value=dict(clip_meta)),
                patch.object(library_service, "save_model_metadata") as mock_save_clip,
                patch(
                    "src.app.config.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                patch.object(
                    subtitle_library_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
                patch.object(
                    dialogue_transcript_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
            ):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                result = subtitle_library_service.add_subtitle_library(video_root, config=config)
                self.assertTrue(result["added"])
                libs = subtitle_library_service.list_subtitle_libraries(config=config, seed=False)
                self.assertIn(canonicalize_library_path(video_root), libs)
                mock_save_clip.assert_not_called()
                # CLIP meta still only has clip_only
                self.assertEqual(len(clip_meta["libraries"]), 1)

    def test_remove_subtitle_library_deletes_transcripts_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            dialogue_dir = os.path.join(data_dir, "dialogue")
            os.makedirs(dialogue_dir, exist_ok=True)
            video_root = os.path.join(tmp, "videos")
            os.makedirs(video_root, exist_ok=True)
            video_path = os.path.join(video_root, "a.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"fake")

            config = {"data_root": tmp}
            lib_path = canonicalize_library_path(video_root)

            with (
                patch.object(subtitle_library_service, "load_config", return_value=config),
                patch(
                    "src.app.config.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                patch.object(
                    subtitle_library_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
                patch.object(
                    dialogue_transcript_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
            ):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                subtitle_library_service.add_subtitle_library(video_root, config=config)
                subtitle_library_service.register_subtitle_library_videos(
                    config=config, library_path=video_root
                )
                entries = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                self.assertEqual(len(entries), 1)
                video_id = entries[0]["video_id"]
                dialogue_transcript_store.save_dialogue_transcript(
                    video_id,
                    segments=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                    library_path=lib_path,
                    video_path=video_path,
                    config=config,
                )
                self.assertTrue(
                    dialogue_transcript_store.load_dialogue_transcript(video_id, config=config)
                )

                deleted_lance = []

                def _should_not_run(*_args, **_kwargs):
                    deleted_lance.append(True)

                ok = subtitle_library_service.remove_subtitle_library(video_root, config=config)
                self.assertTrue(ok)
                self.assertIsNone(
                    dialogue_transcript_store.load_dialogue_transcript(video_id, config=config)
                )
                self.assertEqual(deleted_lance, [])
                libs = subtitle_library_service.list_subtitle_libraries(config=config, seed=False)
                self.assertNotIn(lib_path, libs)

    def test_remove_visual_library_keeps_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            video_root = canonicalize_library_path(os.path.join(tmp, "videos"))
            meta = {
                "schema_version": 2,
                "libraries": {
                    video_root: {
                        "files": {"a.mp4": {"vid": "vid_keep", "asset_state": "ready"}},
                        "last_scan": "",
                        "index_state": "ready",
                    }
                },
            }
            config = {"data_root": tmp}
            saved = {}

            def _save(meta_payload, config=None, **_kwargs):
                saved["meta"] = meta_payload

            with (
                patch.object(library_service, "load_config", return_value=config),
                patch.object(library_service, "load_model_metadata", return_value=meta),
                patch.object(library_service, "save_model_metadata", side_effect=_save),
                patch.object(library_service, "clear_library_search_index"),
                patch.object(library_service, "garbage_collect_orphan_library_indexes"),
                patch.object(
                    library_service,
                    "get_local_model_asset_dirs",
                    return_value={"base_dir": os.path.join(tmp, "profile")},
                ),
                patch(
                    "src.storage.lance_store.garbage_collect_orphan_lance_videos",
                ),
                patch("src.storage.lance_store.compact_lance_storage"),
                patch(
                    "src.storage.dialogue_transcript_store.delete_dialogue_transcript"
                ) as mock_del_tx,
            ):
                deleted = []

                def delete_video_data(video_id, _config, **_kwargs):
                    deleted.append(video_id)

                ok = library_service.remove_library(video_root, delete_video_data)
                self.assertTrue(ok)
                self.assertEqual(deleted, ["vid_keep"])
                mock_del_tx.assert_not_called()
                self.assertNotIn(video_root, saved["meta"].get("libraries", {}))

    def test_seed_from_transcripts_and_clip_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            dialogue_dir = os.path.join(data_dir, "dialogue")
            os.makedirs(dialogue_dir, exist_ok=True)
            from_tx = canonicalize_library_path(os.path.join(tmp, "from_tx"))
            from_clip = canonicalize_library_path(os.path.join(tmp, "from_clip"))
            os.makedirs(from_tx, exist_ok=True)
            os.makedirs(from_clip, exist_ok=True)
            config = {"data_root": tmp}

            with (
                patch.object(subtitle_library_service, "load_config", return_value=config),
                patch(
                    "src.app.config.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                patch.object(
                    subtitle_library_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
                patch.object(
                    dialogue_transcript_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
                patch.object(
                    subtitle_library_service,
                    "list_transcript_library_paths",
                    return_value=[from_tx],
                ),
                patch(
                    "src.services.library_service.list_libraries",
                    return_value={from_clip: {"files": {}, "index_state": "pending"}},
                ),
            ):
                self.assertFalse(subtitle_library_store.is_subtitle_registry_seeded(config=config))
                result = subtitle_library_service.ensure_subtitle_library_seeded(config=config)
                self.assertTrue(result["seeded"])
                self.assertEqual(result["added"], 2)
                libs = subtitle_library_service.list_subtitle_libraries(config=config, seed=False)
                self.assertIn(from_tx, libs)
                self.assertIn(from_clip, libs)
                # Second call is a no-op.
                again = subtitle_library_service.ensure_subtitle_library_seeded(config=config)
                self.assertFalse(again["seeded"])

    def test_clear_subtitle_transcripts_keeps_library_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            dialogue_dir = os.path.join(data_dir, "dialogue")
            os.makedirs(dialogue_dir, exist_ok=True)
            video_root = os.path.join(tmp, "videos")
            os.makedirs(video_root, exist_ok=True)
            video_path = os.path.join(video_root, "a.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"fake")

            config = {"data_root": tmp}
            lib_path = canonicalize_library_path(video_root)
            profile_base = os.path.join(data_dir, "model_assets", "clip", "vit")
            os.makedirs(profile_base, exist_ok=True)
            with open(os.path.join(profile_base, "meta.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")

            with (
                patch.object(subtitle_library_service, "load_config", return_value=config),
                patch(
                    "src.app.config.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                patch.object(
                    subtitle_library_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
                patch.object(
                    dialogue_transcript_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
            ):
                from src.storage.profile_library_store import (
                    get_dialogue_index_state,
                    set_dialogue_index_state,
                )

                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                subtitle_library_service.add_subtitle_library(video_root, config=config)
                subtitle_library_service.register_subtitle_library_videos(
                    config=config, library_path=video_root
                )
                entries = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                video_id = entries[0]["video_id"]
                dialogue_transcript_store.save_dialogue_transcript(
                    video_id,
                    segments=[{"start": 0.0, "end": 1.0, "text": "hello"}],
                    library_path=lib_path,
                    video_path=video_path,
                    config=config,
                )
                set_dialogue_index_state(profile_base, video_id, "ready")

                result = subtitle_library_service.clear_subtitle_transcripts(
                    [video_id], config=config
                )
                self.assertEqual(result["cleared_count"], 1)
                self.assertIsNone(
                    dialogue_transcript_store.load_dialogue_transcript(video_id, config=config)
                )
                self.assertEqual(get_dialogue_index_state(profile_base, video_id), "missing")
                libs = subtitle_library_service.list_subtitle_libraries(config=config, seed=False)
                self.assertIn(lib_path, libs)
                still = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                self.assertEqual(len(still), 1)
                self.assertEqual(still[0]["video_id"], video_id)

    def test_prune_missing_subtitle_sources_removes_gone_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            dialogue_dir = os.path.join(data_dir, "dialogue")
            os.makedirs(dialogue_dir, exist_ok=True)
            video_root = os.path.join(tmp, "videos")
            os.makedirs(video_root, exist_ok=True)
            video_path = os.path.join(video_root, "a.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"fake")

            config = {"data_root": tmp}
            lib_path = canonicalize_library_path(video_root)

            with (
                patch.object(subtitle_library_service, "load_config", return_value=config),
                patch(
                    "src.app.config.get_data_storage_paths",
                    return_value={"data_dir": data_dir},
                ),
                patch.object(
                    subtitle_library_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
                patch.object(
                    dialogue_transcript_store,
                    "get_dialogue_store_dir",
                    return_value=dialogue_dir,
                ),
            ):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                subtitle_library_service.add_subtitle_library(video_root, config=config)
                subtitle_library_service.register_subtitle_library_videos(
                    config=config, library_path=video_root
                )
                entries = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                video_id = entries[0]["video_id"]
                dialogue_transcript_store.save_dialogue_transcript(
                    video_id,
                    segments=[{"start": 0.0, "end": 1.0, "text": "gone"}],
                    library_path=lib_path,
                    video_path=video_path,
                    config=config,
                )
                os.remove(video_path)

                pruned = subtitle_library_service.prune_missing_subtitle_sources(config=config)
                self.assertEqual(pruned["removed_files"], 1)
                self.assertEqual(pruned["cleared_transcripts"], 1)
                still = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                self.assertEqual(still, [])
                self.assertIsNone(
                    dialogue_transcript_store.load_dialogue_transcript(video_id, config=config)
                )


if __name__ == "__main__":
    unittest.main()
