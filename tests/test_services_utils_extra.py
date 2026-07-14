import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import numpy as np

import tests.services_test_support  # noqa: F401 - cv2/faiss stubs
from src import utils


class UtilsTests(unittest.TestCase):
    def test_save_vectors_persists_embedding_spec(self):
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as handle:
            vector_file = handle.name
        try:
            vectors = np.array([[1.0, 0.0]], dtype=np.float32)
            timestamps = np.array([0.0], dtype=np.float32)
            embedding_spec = {
                "model_id": "clip_onnx_default",
                "provider": "clip_onnx",
                "embedding_space": "clip_onnx_default",
                "dimension": 512,
                "metric": "ip",
            }

            from src.core.faiss_index import load_vectors, save_vectors

            save_vectors(vectors, timestamps, vector_file, embedding_spec=embedding_spec)
            payload = load_vectors(vector_file)
            self.assertEqual(payload.get("embedding_spec"), embedding_spec)
        finally:
            if os.path.exists(vector_file):
                os.remove(vector_file)

    def test_resolve_sampling_fps_returns_fixed_fps_by_default(self):
        result = utils.resolve_sampling_fps(
            duration_sec=600,
            config={"fps": 2},
        )

        self.assertEqual(result, 2.0)

    def test_resolve_sampling_fps_uses_fixed_mode_even_with_rules(self):
        result = utils.resolve_sampling_fps(
            duration_sec=120,
            config={"fps": 1.5, "sampling_fps_mode": "fixed", "sampling_fps_rules": "0-5m=10"},
        )

        self.assertEqual(result, 1.5)

    def test_resolve_sampling_fps_matches_custom_ranges(self):
        config = {
            "fps": 1,
            "sampling_fps_mode": "dynamic",
            "sampling_fps_rules": "0-10m=2; 10m-30m=1; 30m-=0.25",
        }

        self.assertEqual(utils.resolve_sampling_fps(duration_sec=120, config=config), 2.0)
        self.assertEqual(utils.resolve_sampling_fps(duration_sec=900, config=config), 1.0)
        self.assertEqual(utils.resolve_sampling_fps(duration_sec=3600, config=config), 0.25)

    def test_resolve_sampling_fps_falls_back_to_base_fps_when_no_range_matches(self):
        result = utils.resolve_sampling_fps(
            duration_sec=60,
            config={"fps": 1.5, "sampling_fps_mode": "dynamic", "sampling_fps_rules": "10m-20m=0.8"},
        )

        self.assertEqual(result, 1.5)

    def test_resolve_sampling_fps_uses_narrower_matching_rule_when_ranges_overlap(self):
        result = utils.resolve_sampling_fps(
            duration_sec=120,
            config={"fps": 1, "sampling_fps_mode": "dynamic", "sampling_fps_rules": "0-1h=0.5; 0-10m=2; 10m-30m=1"},
        )

        self.assertEqual(result, 2.0)

    def test_parse_sampling_fps_rules_normalizes_common_separators(self):
        rules = utils.parse_sampling_fps_rules("0-10m=2\uFF1B10m-30m=1\uFF0C30m-=0.4")

        self.assertEqual([rule["fps"] for rule in rules], [2.0, 1.0, 0.4])

    def test_validate_sampling_fps_rules_rejects_invalid_items(self):
        is_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; bad-rule")

        self.assertFalse(is_valid)

    def test_validate_sampling_fps_rules_rejects_missing_units(self):
        is_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 10-60=1")

        self.assertFalse(is_valid)

    def test_validate_sampling_fps_rules_rejects_non_minute_units(self):
        is_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 10m-1h=1")

        self.assertFalse(is_valid)

    def test_validate_sampling_fps_rules_rejects_reversed_or_overlapping_ranges(self):
        reversed_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 60m-1m=1")
        overlap_valid, _ = utils.validate_sampling_fps_rules("0-10m=2; 5m-20m=1")

        self.assertFalse(reversed_valid)
        self.assertFalse(overlap_valid)

    def test_validate_sampling_fps_rules_full_coverage_requires_tail_and_no_gaps(self):
        missing_tail_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 10m-60m=1")
        gapped_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 20m-=1")
        complete_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 10m-60m=1; 60m-=0.5")
        simplified_valid, _ = utils.validate_sampling_fps_rules_full_coverage("0-10m=2; 10m-=1")

        self.assertFalse(missing_tail_valid)
        self.assertFalse(gapped_valid)
        self.assertTrue(complete_valid)
        self.assertTrue(simplified_valid)

    def test_ensure_sampling_fps_rules_open_tail_auto_appends_default_tail(self):
        updated = utils.ensure_sampling_fps_rules_open_tail("0-10m=2; 10m-60m=1", default_tail_fps=1)
        unchanged = utils.ensure_sampling_fps_rules_open_tail("0-10m=2; 10m-=1", default_tail_fps=1)

        self.assertEqual(updated, "0-10m=2; 10m-60m=1; 60m-=1")
        self.assertEqual(unchanged, "0-10m=2; 10m-=1")

    def test_resolve_resource_path_prefers_configured_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            configured_dir = Path(temp_dir) / "models"
            configured_dir.mkdir()
            target = configured_dir / "clip_text.onnx"
            target.write_bytes(b"model")

            result = utils.resolve_resource_path("models/clip_text.onnx", str(configured_dir))

        self.assertEqual(Path(result), target)

    def test_resolve_resource_path_falls_back_to_packaged_resource(self):
        packaged_path = str(Path("D:/packaged/models/clip_text.onnx"))
        with patch("src.infra.paths.get_resource_path", return_value=packaged_path), patch(
            "src.infra.paths.os.path.exists",
            side_effect=lambda path: path == packaged_path,
        ):
            result = utils.resolve_resource_path("models/clip_text.onnx", "D:/missing-models")

        self.assertEqual(result, packaged_path)

    def test_is_standalone_app_detects_packaged_exe_without_sys_frozen(self):
        from src.infra import paths as path_mod

        with patch.object(path_mod.sys, "executable", r"D:\Release\main.dist\VideoSeek.exe"), patch.object(
            path_mod.sys, "frozen", False, create=True
        ):
            self.assertTrue(path_mod._is_standalone_app())

    def test_get_resource_path_uses_app_install_dir(self):
        with patch("src.infra.paths.get_app_install_dir", return_value=r"D:\Release\main.dist"):
            resolved = utils.get_resource_path("docs/for-agents.md")
        self.assertEqual(
            os.path.normpath(resolved),
            os.path.normpath(r"D:\Release\main.dist\docs\for-agents.md"),
        )

    def test_get_app_install_dir_dev_uses_repo_root(self):
        from src.infra import paths as path_mod

        with patch.object(path_mod, "_is_standalone_app", return_value=False):
            install_dir = utils.get_app_install_dir()
        self.assertEqual(
            os.path.normpath(install_dir),
            os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(path_mod.__file__))))),
        )

    def test_get_missing_model_files_reports_missing_entries(self):
        with patch("src.infra.model_paths.get_model_path", side_effect=lambda filename: f"D:/models/{filename}"), patch(
            "src.infra.model_paths.os.path.exists",
            side_effect=lambda path: path.endswith("clip_text.onnx"),
        ):
            missing, resolved = utils.get_missing_model_files(["clip_visual.onnx", "clip_text.onnx"])

        self.assertEqual(missing, ["clip_visual.onnx"])
        self.assertEqual(resolved["clip_text.onnx"], "D:/models/clip_text.onnx")

    @patch("src.utils.subprocess.run")
    @patch("src.utils.os.path.exists", return_value=True)
    def test_open_in_explorer_uses_windows_select_argument_split(
        self,
        _mock_exists,
        mock_run,
    ):
        with patch("src.utils.sys.platform", "win32"):
            result = utils.open_in_explorer("D:/videos/clip.mp4")

        self.assertTrue(result)
        mock_run.assert_called_once()
        args = mock_run.call_args.args[0]
        self.assertEqual(args[0], "explorer")
        self.assertEqual(args[1], "/select,")
        self.assertTrue(str(args[2]).lower().endswith("clip.mp4"))

    @patch("src.media.export_clip.subprocess.run")
    @patch("src.media.export_clip.get_ffmpeg_path", return_value="ffmpeg")
    @patch(
        "src.app.config.load_config",
        return_value={
            "preview_seconds": 6,
            "preview_width": 640,
            "preview_height": 360,
        },
    )
    @patch("src.media.export_clip.os.path.exists", return_value=False)
    def test_create_preview_clip_uses_precise_seek_after_input(
        self,
        _mock_exists,
        _mock_load_config,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.create_preview_clip("D:/videos/clip.mp4", 12.3456, "D:/cache/p.mp4")

        cmd = mock_run.call_args.args[0]
        first_ss = cmd.index("-ss")
        i_pos = cmd.index("-i")
        second_ss = cmd.index("-ss", i_pos + 1)
        self.assertLess(first_ss, i_pos)
        self.assertGreater(second_ss, i_pos)
        self.assertEqual(cmd[second_ss + 1], "1.000")
        self.assertIn("-c:a", cmd)
        self.assertIn("aac", cmd)

    @patch("src.media.export_clip.subprocess.run")
    @patch("src.media.export_clip.get_ffmpeg_path", return_value="ffmpeg")
    @patch(
        "src.app.config.load_config",
        return_value={
            "preview_seconds": 6,
            "preview_width": 640,
            "preview_height": 360,
        },
    )
    @patch("src.media.export_clip.os.path.exists", return_value=False)
    def test_create_preview_clip_respects_duration_override(
        self,
        _mock_exists,
        _mock_load_config,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.create_preview_clip("D:/videos/clip.mp4", 10.0, "D:/cache/p.mp4", duration_sec=2.25)

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-t") + 1], "2.250")

    @patch("src.media.export_clip.subprocess.run")
    @patch("src.media.export_clip.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.media.export_clip.ensure_folder_exists")
    @patch("src.media.export_clip.os.path.exists", return_value=False)
    def test_export_original_clip_reencode_mode(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.export_original_clip("D:/videos/clip.mp4", 8.0, 3.5, "D:/out/clip.mp4")

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "libx264")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "18")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")
        self.assertEqual(cmd[cmd.index("-t") + 1], "3.500")

    @patch("src.media.export_clip.subprocess.run")
    @patch("src.media.export_clip.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.media.export_clip.ensure_folder_exists")
    @patch("src.media.export_clip.os.path.exists", return_value=False)
    def test_export_original_clip_copy_mode(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.export_original_clip(
            "D:/videos/clip.mp4",
            8.0,
            3.5,
            "D:/out/clip.mp4",
            encode_mode="copy",
        )

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-c") + 1], "copy")
        self.assertNotIn("-c:v", cmd)

    @patch("src.media.export_clip.subprocess.run")
    @patch("src.media.export_clip.get_ffmpeg_path", return_value="ffmpeg")
    @patch("src.media.export_clip.ensure_folder_exists")
    @patch("src.media.export_clip.os.path.exists", return_value=False)
    def test_export_original_clip_silent_has_no_audio(
        self,
        _mock_exists,
        _mock_ensure_folder_exists,
        _mock_get_ffmpeg,
        mock_run,
    ):
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        utils.export_original_clip("D:/videos/clip.mp4", 8.0, 3.5, "D:/out/clip.mp4", silent=True)

        cmd = mock_run.call_args.args[0]
        self.assertIn("-an", cmd)
        self.assertNotIn("-c:a", cmd)
        self.assertEqual(cmd.count("-map"), 1)




if __name__ == "__main__":
    unittest.main()
