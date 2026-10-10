"""Appendix A helpers are public, so other packages do not import the private name."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# Importer file -> private names that must not be the imported symbol.
_CROSS_PACKAGE = {
    "src/services/embedding_preprocess.py": {"_count_profile_ready_videos"},
    "src/services/model_package_service.py": {"_read_on_disk_embedding_dimension"},
    "src/services/understanding_service.py": {"_lance_state_mtime"},
    "src/services/search_telemetry_store.py": {"_commit_meta_file"},
    "src/services/fcpxml_export_service.py": {"_probe_video_stream_with_opencv"},
    "src/services/recap_runtime.py": {"_probe_video_stream_with_opencv"},
    "src/app/single_instance.py": {"_is_standalone_app"},
    "ui/controllers/preview_controller.py": {"_resolve_base_clip_window"},
    "ui/windows/gui_preview.py": {
        "_resolve_base_clip_window",
        "_cv2",
        "_ffmpeg_capture_frame",
        "_result_mode_label",
    },
    "ui/windows/gui_understanding.py": {"_remove_paths"},
    "ui/views/dialogue_highlight.py": {"_nfkc_casefold"},
    "ui/dialogs/skip_edges.py": {"_format_duration_token"},
    "ui/windows/gui.py": {"_scroll_ancestor_vertically"},
    "ui/dialogs/shot_list_dialog.py": {"_format_time_range"},
    "ui/widgets/result_grid.py": {"_format_time_range"},
    "ui/widgets/settings/page.py": {"_fallback_text"},
}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names)
    return found


class PublicHelperTests(unittest.TestCase):
    def test_cross_package_imports_use_public_names(self):
        for relative, private_names in _CROSS_PACKAGE.items():
            imported = _imported_names(_ROOT / relative)
            leaked = private_names & imported
            self.assertFalse(leaked, f"{relative} still imports {sorted(leaked)}")

    def test_public_aliases_match_private_functions(self):
        from src.infra.paths import _is_standalone_app, is_standalone_app
        from src.media.export_clip import _resolve_base_clip_window, resolve_base_clip_window
        from src.media.probe import _probe_video_stream_with_opencv, probe_video_stream_with_opencv
        from src.media.thumbnail import _cv2, _ffmpeg_capture_frame, ffmpeg_capture_frame, load_cv2
        from src.services.search_skip_ranges import _format_duration_token, format_duration_token
        from src.storage.config_store import _read_on_disk_embedding_dimension, read_on_disk_embedding_dimension
        from src.storage.lance_search_index import _lance_state_mtime, lance_state_mtime
        from src.storage.lance_store import _count_profile_ready_videos, count_profile_ready_videos
        from src.storage.meta_io import commit_temp_file

        self.assertIs(count_profile_ready_videos, _count_profile_ready_videos)
        self.assertIs(read_on_disk_embedding_dimension, _read_on_disk_embedding_dimension)
        self.assertIs(lance_state_mtime, _lance_state_mtime)
        self.assertIs(probe_video_stream_with_opencv, _probe_video_stream_with_opencv)
        self.assertIs(is_standalone_app, _is_standalone_app)
        self.assertIs(resolve_base_clip_window, _resolve_base_clip_window)
        self.assertIs(load_cv2, _cv2)
        self.assertIs(ffmpeg_capture_frame, _ffmpeg_capture_frame)
        self.assertIs(format_duration_token, _format_duration_token)
        self.assertTrue(callable(commit_temp_file))
