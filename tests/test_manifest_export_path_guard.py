import json
import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.manifest_export_service import execute_export_manifest


class ManifestExportPathGuardTests(unittest.TestCase):
    def test_write_path_rejects_indexed_library_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = os.path.join(tmp, "library")
            os.makedirs(lib, exist_ok=True)
            target = os.path.join(lib, "out.json")
            with patch(
                "src.services.clip_export_service.output_path_allowed",
                return_value=False,
            ):
                with self.assertRaises(ValueError) as ctx:
                    execute_export_manifest(
                        project="t",
                        items=[
                            {
                                "video_path": os.path.join(lib, "a.mp4"),
                                "start_sec": 0.0,
                                "end_sec": 1.0,
                            }
                        ],
                        write_path=target,
                        dedupe=False,
                    )
            self.assertIn("library", str(ctx.exception).lower())
            self.assertFalse(os.path.isfile(target))

    def test_write_path_allows_export_outside_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "exports")
            os.makedirs(out_dir, exist_ok=True)
            target = os.path.join(out_dir, "manifest.json")
            with patch(
                "src.services.clip_export_service.output_path_allowed",
                return_value=True,
            ):
                result = execute_export_manifest(
                    project="t",
                    items=[
                        {
                            "video_path": os.path.join(tmp, "a.mp4"),
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                        }
                    ],
                    write_path=target,
                    dedupe=False,
                )
            self.assertTrue(result.get("ok"))
            self.assertTrue(os.path.isfile(target))
            with open(target, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["project"], "t")


if __name__ == "__main__":
    unittest.main()
