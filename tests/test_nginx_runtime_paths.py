"""Writable nginx runtime prefix (Program Files vs AppData)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.services import team_paths


class NginxRuntimePathTests(unittest.TestCase):
    def test_runtime_uses_bundle_when_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "server" / "nginx"
            conf_d = bundle / "conf" / "conf.d"
            conf_d.mkdir(parents=True)
            (bundle / "nginx.exe").write_bytes(b"MZ")
            (bundle / "conf" / "nginx.conf").write_text("worker_processes 1;\n", encoding="utf-8")
            (bundle / "conf" / "mime.types").write_text("types {}\n", encoding="utf-8")

            with mock.patch.object(team_paths, "get_nginx_bundle_root", return_value=str(bundle)):
                runtime = team_paths.get_nginx_runtime_root()
                self.assertEqual(os.path.normcase(runtime), os.path.normcase(str(bundle)))
                self.assertTrue(team_paths.nginx_bundle_ready())

    def test_runtime_falls_back_to_appdata_when_bundle_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "Program Files" / "VideoSeek" / "server" / "nginx"
            appdata = Path(tmp) / "AppData" / "VideoSeek"
            conf_d = bundle / "conf" / "conf.d"
            conf_d.mkdir(parents=True)
            (bundle / "nginx.exe").write_bytes(b"MZ")
            (bundle / "conf" / "nginx.conf").write_text(
                "worker_processes 1;\ninclude mime.types;\ninclude conf.d/*.conf;\n",
                encoding="utf-8",
            )
            (bundle / "conf" / "mime.types").write_text("types {}\n", encoding="utf-8")

            with mock.patch.object(team_paths, "get_nginx_bundle_root", return_value=str(bundle)):
                with mock.patch.object(team_paths, "get_app_data_dir", return_value=str(appdata)):
                    with mock.patch.object(team_paths, "_nginx_dir_is_writable", return_value=False):
                        runtime = team_paths.sync_nginx_runtime_from_bundle()
                        exe = team_paths.get_nginx_exe()
            expected = appdata / "nginx"
            self.assertEqual(os.path.normcase(runtime), os.path.normcase(str(expected)))
            self.assertTrue((expected / "conf" / "nginx.conf").is_file())
            self.assertTrue((expected / "conf" / "mime.types").is_file())
            self.assertTrue((expected / "logs").is_dir())
            self.assertTrue((expected / "temp").is_dir())
            self.assertEqual(os.path.normcase(exe), os.path.normcase(str(bundle / "nginx.exe")))


if __name__ == "__main__":
    unittest.main()
