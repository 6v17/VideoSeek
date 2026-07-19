"""Dialogue search scope should resolve against the global subtitle library."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.services import search_scope, subtitle_library_service
from src.storage import dialogue_transcript_store, subtitle_library_store
from src.utils import canonicalize_library_path


class DialogueSearchScopeTests(unittest.TestCase):
    def test_resolve_subtitle_scope_video_ids_from_global_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            dialogue_dir = os.path.join(data_dir, "dialogue")
            os.makedirs(dialogue_dir, exist_ok=True)
            root_a = canonicalize_library_path(os.path.join(tmp, "lib_a"))
            root_b = canonicalize_library_path(os.path.join(tmp, "lib_b"))
            os.makedirs(root_a, exist_ok=True)
            os.makedirs(root_b, exist_ok=True)
            path_a = os.path.join(root_a, "a.mp4")
            path_b = os.path.join(root_b, "b.mp4")
            for path in (path_a, path_b):
                with open(path, "wb") as handle:
                    handle.write(b"x")
            config = {"data_root": tmp}

            with (
                patch.object(subtitle_library_service, "load_config", return_value=config),
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
                subtitle_library_service.add_subtitle_library(root_a, config=config)
                subtitle_library_service.add_subtitle_library(root_b, config=config)
                subtitle_library_service.register_subtitle_library_videos(config=config)
                entries = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                by_path = {
                    search_scope.normalize_scope_path(item["video_path"]): item["video_id"]
                    for item in entries
                }
                vid_a = by_path[search_scope.normalize_scope_path(path_a)]

                ids = search_scope.resolve_subtitle_scope_video_ids(
                    video_paths=[path_a],
                    config=config,
                )
                self.assertEqual(ids, [vid_a])

                ids_lib = search_scope.resolve_subtitle_scope_video_ids(
                    library_paths=[root_b],
                    config=config,
                )
                self.assertEqual(len(ids_lib), 1)
                self.assertEqual(
                    ids_lib[0],
                    by_path[search_scope.normalize_scope_path(path_b)],
                )


if __name__ == "__main__":
    unittest.main()
