"""Remember the last desktop clip-export folder."""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.clip_export_service import (
    export_save_dialog_start,
    last_export_dir,
    remember_export_path,
)


class ExportLastDirTests(unittest.TestCase):
    def test_remember_file_path_and_suggest_next_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = {}

            def fake_load():
                return {"export_last_dir": saved.get("dir", "")}

            def fake_save(cfg):
                saved["dir"] = cfg["export_last_dir"]

            with (
                patch("src.services.clip_export_service.load_config", side_effect=fake_load),
                patch("src.app.config.save_config", side_effect=fake_save),
            ):
                remember_export_path(os.path.join(tmp, "clip.mp4"))

            self.assertEqual(os.path.normpath(saved["dir"]), os.path.normpath(tmp))
            start = export_save_dialog_start("next.mp4", config={"export_last_dir": tmp})
            self.assertEqual(os.path.normpath(start), os.path.normpath(os.path.join(tmp, "next.mp4")))

    def test_missing_folder_is_ignored(self):
        self.assertEqual(last_export_dir({"export_last_dir": "D:/no/such/export/dir"}), "")
        self.assertEqual(export_save_dialog_start("clip.mp4", config={"export_last_dir": ""}), "clip.mp4")


if __name__ == "__main__":
    unittest.main()
