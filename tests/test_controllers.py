import sys
import types
import unittest
import re as std_re
from unittest.mock import MagicMock, patch

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("numpy", types.SimpleNamespace())
sys.modules.setdefault("onnxruntime", types.SimpleNamespace())
sys.modules.setdefault("faiss", types.SimpleNamespace())
sys.modules.setdefault("ftfy", types.SimpleNamespace(fix_text=lambda text: text))
sys.modules.setdefault("regex", std_re)

if "PySide6" not in sys.modules:
    qtcore = types.ModuleType("PySide6.QtCore")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _Signal:
        def __init__(self, *args, **kwargs):
            self._subscribers = []

        def connect(self, callback):
            self._subscribers.append(callback)

        def emit(self, *args, **kwargs):
            for callback in list(self._subscribers):
                callback(*args, **kwargs)

    class _Qt:
        AlignCenter = 0
        WA_NativeWindow = 100

    class _QLabel:
        def setAlignment(self, *_args, **_kwargs):
            pass

        def setPixmap(self, *_args, **_kwargs):
            pass

    class _QUrl:
        def __init__(self, value=""):
            self.value = value

        @classmethod
        def fromLocalFile(cls, path):
            return cls(path)

    class _QTimer:
        def __init__(self, *_args, **_kwargs):
            self.timeout = _Signal()

        def setInterval(self, *_args, **_kwargs):
            return None

        def start(self):
            return None

        def stop(self):
            return None

    qtcore.QObject = _QObject
    qtcore.Signal = _Signal
    qtcore.Qt = _Qt
    qtcore.QUrl = _QUrl
    qtcore.QTimer = _QTimer
    qtwidgets.QLabel = _QLabel

    pyside6 = types.ModuleType("PySide6")
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtWidgets"] = qtwidgets

if "ui.dialogs" not in sys.modules:
    dialogs_module = types.ModuleType("ui.dialogs")
    dialogs_module.ModelDownloadDialog = type("ModelDownloadDialog", (), {})
    sys.modules["ui.dialogs"] = dialogs_module

if "ui.table_views" not in sys.modules:
    table_views_module = types.ModuleType("ui.table_views")

    def _populate_result_table(*_args, **_kwargs):
        return None

    table_views_module.populate_result_table = _populate_result_table
    sys.modules["ui.table_views"] = table_views_module

if "ui.workers" not in sys.modules:
    workers_module = types.ModuleType("ui.workers")

    class _BaseWorker:
        def __init__(self, *args, **kwargs):
            self.progress_signal = _Signal()
            self.finished_signal = _Signal()
            self.error_signal = _Signal()
            self.result_ready = _Signal()
            self.finished = _Signal()
            self.thumb_ready = _Signal()

        def start(self):
            return None

        def quit(self):
            return None

        def wait(self, *_args, **_kwargs):
            return True

        def requestInterruption(self):
            return None

        def terminate(self):
            return None

        def isRunning(self):
            return False

    workers_module.ResourceDownloadWorker = _BaseWorker
    workers_module.SearchWorker = _BaseWorker
    workers_module.SearchWarmupWorker = _BaseWorker
    workers_module.ThumbLoader = _BaseWorker
    sys.modules["ui.workers"] = workers_module

from ui.runtime_resource_controller import RuntimeResourceController
from ui.preview_controller import PreviewController
from ui.search_controller import SearchController
from ui.vlc_player import VlcPreviewPlayer


def _make_parent_window():
    parent = MagicMock()
    parent.language = "zh"
    parent.is_dark_mode = True
    parent.texts = {
        "warning_title": "Warning",
        "download_models_unavailable": "Unavailable",
        "model_download_starting": "Preparing runtime resource download...",
        "searching": "Searching...",
        "no_results": "No results",
        "search_done": "Done in {duration:.2f}s | {count} results",
    }
    parent.show_info_dialog = MagicMock()
    parent.open_runtime_resource_folder = MagicMock()
    parent.handle_play = MagicMock()
    parent.handle_export_clip = MagicMock()
    parent.open_result_in_explorer = MagicMock()
    parent.media_player = MagicMock()
    parent.video_widget = MagicMock()
    parent.video_widget.winId.return_value = 123
    parent.search_page = MagicMock()
    parent.search_page.btn_search = MagicMock()
    parent.search_page.lbl_status = MagicMock()
    parent.result_table = MagicMock()
    return parent


class RuntimeResourceControllerTests(unittest.TestCase):
    @patch("ui.runtime_resource_controller.get_runtime_resource_location_text", return_value="Resources")
    @patch("ui.runtime_resource_controller.ensure_runtime_resource_dirs")
    @patch("ui.runtime_resource_controller.get_runtime_resource_status")
    def test_check_resources_shows_dialog_when_missing(
        self,
        mock_get_status,
        mock_ensure_dirs,
        _mock_location_text,
    ):
        parent = _make_parent_window()
        controller = RuntimeResourceController(parent)
        dialog = MagicMock()
        controller._ensure_dialog = MagicMock(return_value=dialog)
        mock_get_status.return_value = {
            "resources_ready": False,
            "display_files": ["clip_visual.onnx", "ffmpeg.exe"],
            "ffmpeg_ready": False,
            "model_ready": False,
            "download_enabled": True,
        }

        result = controller.check_resources(show_dialog=True)

        self.assertFalse(result)
        mock_ensure_dirs.assert_called_once()
        dialog.set_missing_state.assert_called_once_with(
            ["clip_visual.onnx", "ffmpeg.exe"],
            "Resources",
            download_enabled=True,
        )
        dialog.exec.assert_called_once()

    @patch("ui.runtime_resource_controller.get_texts")
    @patch("ui.runtime_resource_controller.get_runtime_resource_status")
    def test_start_download_shows_warning_when_unavailable(self, mock_get_status, mock_get_texts):
        parent = _make_parent_window()
        controller = RuntimeResourceController(parent)
        mock_get_status.return_value = {
            "download_enabled": False,
            "missing_model_files": ["clip_visual.onnx"],
            "ffmpeg_ready": False,
        }
        mock_get_texts.return_value = {
            "warning_title": "Warning",
            "download_models_unavailable": "Unavailable",
        }

        controller.start_download()

        parent.show_info_dialog.assert_called_once_with("Warning", "Unavailable", kind="warning")

    @patch("ui.runtime_resource_controller.ResourceDownloadWorker")
    @patch("ui.runtime_resource_controller.get_runtime_resource_status")
    def test_start_download_builds_worker_with_missing_flags(self, mock_get_status, mock_worker_cls):
        parent = _make_parent_window()
        controller = RuntimeResourceController(parent)
        dialog = MagicMock()
        controller._ensure_dialog = MagicMock(return_value=dialog)
        worker = MagicMock()
        worker.isRunning.return_value = False
        mock_worker_cls.return_value = worker
        mock_get_status.return_value = {
            "download_enabled": True,
            "missing_model_files": ["clip_visual.onnx"],
            "ffmpeg_ready": False,
        }

        controller.start_download()

        mock_worker_cls.assert_called_once_with(need_models=True, need_ffmpeg=True)
        dialog.set_progress_state.assert_called_once()
        worker.start.assert_called_once()


class SearchControllerTests(unittest.TestCase):
    @patch("ui.search_controller.SearchWorker")
    def test_start_search_disables_button_and_starts_worker(self, mock_worker_cls):
        parent = _make_parent_window()
        controller = SearchController(parent)
        worker = MagicMock()
        mock_worker_cls.return_value = worker

        controller.start_search("cat", True)

        parent.search_page.btn_search.setEnabled.assert_called_with(False)
        parent.search_page.lbl_status.setText.assert_called_with("Searching...")
        mock_worker_cls.assert_called_once_with("cat", True)
        worker.start.assert_called_once()

    def test_clear_results_resets_table(self):
        parent = _make_parent_window()
        controller = SearchController(parent)
        controller.stop_thumbnail_loading = MagicMock()

        controller.clear_results()

        controller.stop_thumbnail_loading.assert_called_once()
        parent.result_table.setRowCount.assert_called_once_with(0)

    def test_display_results_handles_empty_result(self):
        parent = _make_parent_window()
        controller = SearchController(parent)

        controller._display_results([])

        parent.result_table.setRowCount.assert_called_once_with(0)
        parent.search_page.lbl_status.setText.assert_called_with("No results")

    @patch("ui.search_controller.SearchWarmupWorker")
    def test_start_warmup_starts_once(self, mock_worker_cls):
        parent = _make_parent_window()
        controller = SearchController(parent)
        worker = MagicMock()
        mock_worker_cls.return_value = worker

        controller.start_warmup()
        controller.start_warmup()

        mock_worker_cls.assert_called_once_with()
        worker.start.assert_called_once()


class PreviewControllerTests(unittest.TestCase):
    @patch("ui.preview_controller.VlcPreviewPlayer")
    def test_start_warmup_initializes_vlc_player_once(self, mock_vlc_cls):
        parent = _make_parent_window()
        controller = PreviewController(parent)

        controller.start_warmup()
        controller.start_warmup()

        mock_vlc_cls.assert_called_once_with(parent.video_widget)

    @patch("ui.preview_controller.VlcPreviewPlayer")
    @patch("ui.preview_controller.get_video_duration_seconds", return_value=120.0)
    @patch("ui.preview_controller.load_config", return_value={"preview_seconds": 6})
    def test_play_prefers_vlc_for_direct_preview(self, _mock_config, _mock_duration, mock_vlc_cls):
        parent = _make_parent_window()
        vlc_player = MagicMock()
        vlc_player.play.return_value = True
        mock_vlc_cls.return_value = vlc_player
        controller = PreviewController(parent)

        result = controller.play("D:/videos/clip.mp4", 30.0)

        self.assertTrue(result)
        vlc_player.play.assert_called_once_with("D:/videos/clip.mp4", 27.0, stop_sec=33.0)
        parent.media_player.setSource.assert_called_once()

    @patch("ui.preview_controller.create_preview_clip")
    @patch("ui.preview_controller.build_preview_cache_path", return_value="D:/cache/preview.mp4")
    @patch("ui.preview_controller.VlcPreviewPlayer")
    @patch("ui.preview_controller.get_video_duration_seconds", return_value=120.0)
    @patch("ui.preview_controller.load_config", return_value={"preview_seconds": 6})
    def test_play_falls_back_to_generated_clip_when_vlc_playback_fails(
        self,
        _mock_config,
        _mock_duration,
        mock_vlc_cls,
        _mock_cache_path,
        mock_create_preview,
    ):
        parent = _make_parent_window()
        vlc_player = MagicMock()
        vlc_player.play.return_value = False
        mock_vlc_cls.return_value = vlc_player
        mock_create_preview.return_value = MagicMock(returncode=0)
        controller = PreviewController(parent)

        result = controller.play("D:/videos/clip.mp4", 30.0)

        self.assertTrue(result)
        mock_create_preview.assert_called_once_with(
            "D:/videos/clip.mp4",
            27.0,
            "D:/cache/preview.mp4",
            duration_sec=6.0,
        )
        parent.media_player.play.assert_called_once()

    def test_stop_preview_clears_current_preview_context(self):
        parent = _make_parent_window()
        controller = PreviewController(parent)
        controller.vlc_player = MagicMock()
        controller.current_preview_context = {
            "video_path": "D:/videos/clip.mp4",
            "start_sec": 1.0,
            "end_sec": 3.0,
        }
        controller.cleanup_previous_preview = MagicMock()

        controller.stop_preview()

        controller.vlc_player.stop.assert_called_once()
        parent.media_player.stop.assert_called_once()
        parent.media_player.setSource.assert_called_once()
        controller.cleanup_previous_preview.assert_called_once()
        self.assertIsNone(controller.current_preview_context)


class VlcPreviewPlayerTests(unittest.TestCase):
    def test_handle_timeout_pauses_instead_of_stopping(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()
        player._stop_at_ms = 33000
        player._player.get_time.return_value = 33001

        player._handle_timeout()

        player._player.set_time.assert_called_once_with(33000)
        player._player.pause.assert_called_once()

    def test_shutdown_detaches_and_releases_player(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        mock_player = MagicMock()
        mock_instance = MagicMock()
        player._player = mock_player
        player._instance = mock_instance

        player.shutdown()

        if sys.platform == "win32":
            mock_player.set_hwnd.assert_called_once_with(0)
        elif sys.platform == "darwin":
            mock_player.set_nsobject.assert_called_once_with(0)
        else:
            mock_player.set_xwindow.assert_called_once_with(0)
        mock_player.release.assert_called_once()
        mock_instance.release.assert_called_once()
        self.assertIsNone(player._player)
        self.assertIsNone(player._instance)
        self.assertTrue(player._released)

    def test_stop_clears_bound_media(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()

        player.stop()

        player._player.stop.assert_called_once()
        player._player.set_media.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
