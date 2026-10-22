import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.infra import ffmpeg_paths


def _write_fake_pe(path: Path, *, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"MZ" + (b"\0" * max(0, size - 2))
    path.write_bytes(payload)


class FfmpegBinaryUsableTests(unittest.TestCase):
    def test_stub_bytes_are_not_usable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stub = Path(temp_dir) / "ffmpeg.exe"
            stub.write_bytes(b"ffmpeg")
            self.assertFalse(ffmpeg_paths.is_ffmpeg_binary_usable(str(stub)))

    def test_small_pe_header_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tiny = Path(temp_dir) / "ffmpeg.exe"
            _write_fake_pe(tiny, size=1024)
            self.assertFalse(ffmpeg_paths.is_ffmpeg_binary_usable(str(tiny)))

    def test_large_pe_like_file_is_usable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = Path(temp_dir) / "ffmpeg.exe"
            _write_fake_pe(binary, size=ffmpeg_paths._MIN_FFMPEG_BYTES)
            self.assertTrue(ffmpeg_paths.is_ffmpeg_binary_usable(str(binary)))


class HasFfmpegSkipsBrokenManagedCopyTests(unittest.TestCase):
    def test_broken_appdata_stub_does_not_count_as_installed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = os.path.join(temp_dir, "VideoSeek")
            stub = Path(app_data) / "bin" / "ffmpeg.exe"
            stub.parent.mkdir(parents=True)
            stub.write_bytes(b"ffmpeg")

            with (
                patch("src.infra.ffmpeg_paths.get_app_data_dir", return_value=app_data),
                patch("src.infra.ffmpeg_paths.get_app_install_dir", return_value=temp_dir),
                patch("src.infra.ffmpeg_paths.shutil.which", return_value=None),
                patch(
                    "src.app.config.load_config",
                    return_value={"ffmpeg_path": str(stub)},
                ),
            ):
                self.assertFalse(ffmpeg_paths.has_ffmpeg())
                path, source = ffmpeg_paths.resolve_ffmpeg_path_info()
                self.assertEqual(path, "")
                self.assertEqual(source, "missing")


class BundledImportRetriesBrokenFfmpegTests(unittest.TestCase):
    def test_plan_includes_ffmpeg_when_managed_copy_is_stub(self):
        from src.services import bundled_runtime_service

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = os.path.join(temp_dir, "runtime")
            app_data = os.path.join(temp_dir, "VideoSeek")
            os.makedirs(runtime_dir)
            Path(runtime_dir, "ffmpeg.exe").write_bytes(b"seed")
            Path(runtime_dir, "chinese-clip.zip").write_bytes(b"zip")
            with open(os.path.join(runtime_dir, "manifest.json"), "w", encoding="utf-8") as handle:
                handle.write('{"files": ["ffmpeg.exe", "chinese-clip.zip"]}')

            stub = Path(app_data) / "bin" / "ffmpeg.exe"
            stub.parent.mkdir(parents=True)
            stub.write_bytes(b"ffmpeg")

            ready_status = {
                "resources_ready": True,
                "model_ready": True,
                "ffmpeg_ready": True,
                "model_root_dir": os.path.join(app_data, "models"),
                "model_dir": os.path.join(app_data, "models"),
            }

            with (
                patch("src.services.bundled_runtime_service.get_bundled_runtime_dir", return_value=runtime_dir),
                patch("src.services.runtime_resource_service.get_runtime_resource_status", return_value=ready_status),
                patch("src.services.bundled_runtime_service.is_chinese_clip_bundled_variant_installed", return_value=True),
                patch("src.services.bundled_runtime_service.is_bundled_rapidocr_installed", return_value=True),
                patch("src.infra.ffmpeg_paths.get_app_data_dir", return_value=app_data),
                patch("src.infra.ffmpeg_paths.get_app_install_dir", return_value=temp_dir),
                patch("src.infra.ffmpeg_paths.shutil.which", return_value=None),
                patch("src.app.config.load_config", return_value={"ffmpeg_path": str(stub)}),
            ):
                plan = bundled_runtime_service.plan_bundled_import(runtime_dir=runtime_dir)

            names = {os.path.basename(path).lower() for path in plan.get("paths") or []}
            self.assertIn("ffmpeg.exe", names)


if __name__ == "__main__":
    unittest.main()
