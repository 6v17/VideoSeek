import os
import tempfile
import unittest
from unittest.mock import patch

from src.services import subtitle_library_service
from src.services.dialogue_index_service import list_dialogue_index_targets
from src.storage import dialogue_transcript_store, subtitle_library_store


class SubtitleLibraryTargetTests(unittest.TestCase):
    def test_targets_come_from_global_subtitle_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            dialogue_dir = os.path.join(data_dir, "dialogue")
            os.makedirs(dialogue_dir, exist_ok=True)
            lib_root = os.path.join(tmp, "videos")
            os.makedirs(lib_root, exist_ok=True)
            media = os.path.join(lib_root, "clip.mp4")
            with open(media, "wb") as handle:
                handle.write(b"fake-video-bytes")

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
            ):
                subtitle_library_store.mark_subtitle_registry_seeded(config=config)
                added = subtitle_library_service.add_subtitle_library(lib_root, config=config)
                self.assertTrue(added.get("added") or added.get("ok"))

                registered = subtitle_library_service.register_subtitle_library_videos(
                    config=config, library_path=lib_root
                )
                self.assertGreaterEqual(registered["registered"], 1)

                entries = subtitle_library_service.list_subtitle_library_video_entries(
                    config=config, register=False
                )
                self.assertEqual(len(entries), 1)
                video_id = entries[0]["video_id"]
                self.assertTrue(video_id)

                targets = list_dialogue_index_targets(config=config)
                self.assertEqual(len(targets), 1)
                self.assertEqual(targets[0]["video_id"], video_id)
                self.assertEqual(
                    os.path.normcase(targets[0]["video_path"]),
                    os.path.normcase(os.path.normpath(media)),
                )


if __name__ == "__main__":
    unittest.main()
