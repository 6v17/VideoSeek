import os
import tempfile
import unittest
from unittest import mock


class SubtitleLibraryTargetTests(unittest.TestCase):
    def test_targets_include_unsynced_library_videos(self):
        from src.services.dialogue_index_service import list_dialogue_index_targets
        from src.services.library_service import register_library_videos

        with tempfile.TemporaryDirectory() as tmp:
            lib_root = os.path.join(tmp, "videos")
            os.makedirs(lib_root, exist_ok=True)
            media = os.path.join(lib_root, "clip.mp4")
            with open(media, "wb") as handle:
                handle.write(b"fake-video-bytes")

            meta = {
                "libraries": {
                    lib_root: {"files": {}, "last_scan": "", "index_state": "pending"},
                }
            }

            def _load(config=None):
                return meta

            def _save(new_meta, config=None):
                # save_model_metadata may pass the same dict instance.
                if new_meta is meta:
                    return
                snapshot = dict(new_meta)
                meta.clear()
                meta.update(snapshot)

            with mock.patch("src.services.library_service.load_config", return_value={}), mock.patch(
                "src.services.library_service.load_model_metadata",
                side_effect=_load,
            ), mock.patch(
                "src.services.library_service.save_model_metadata",
                side_effect=_save,
            ), mock.patch(
                "src.storage.asset_store.load_model_metadata",
                side_effect=_load,
            ):
                result = register_library_videos(library_path=lib_root)
                self.assertGreaterEqual(result["registered"], 1)

                lib_key = next(iter(meta["libraries"]))
                files = meta["libraries"][lib_key]["files"]
                self.assertIn("clip.mp4", files)
                info = files["clip.mp4"]
                self.assertEqual(info["asset_state"], "missing_asset")
                self.assertTrue(str(info.get("vid") or "").strip())

                targets = list_dialogue_index_targets()
                self.assertEqual(len(targets), 1)
                self.assertEqual(
                    os.path.normcase(targets[0]["video_path"]),
                    os.path.normcase(os.path.normpath(media)),
                )
                self.assertEqual(targets[0]["video_id"], info["vid"])


if __name__ == "__main__":
    unittest.main()
