import importlib.util
import sys
import types
import unittest
import re as std_re
from unittest.mock import MagicMock, patch


def _stub_if_missing(module_name, factory):
    if importlib.util.find_spec(module_name) is not None:
        return
    sys.modules.setdefault(module_name, factory())


_stub_if_missing("cv2", lambda: types.SimpleNamespace())
_stub_if_missing("onnxruntime", lambda: types.SimpleNamespace())
_stub_if_missing("faiss", lambda: types.SimpleNamespace())
_stub_if_missing("ftfy", lambda: types.SimpleNamespace(fix_text=lambda text: text))
_stub_if_missing("regex", lambda: std_re)

_USE_PYSIDE_STUB = importlib.util.find_spec("PySide6") is None


class _Signal:
    def __init__(self, *args, **kwargs):
        self._subscribers = []

    def connect(self, callback):
        self._subscribers.append(callback)

    def emit(self, *args, **kwargs):
        for callback in list(self._subscribers):
            callback(*args, **kwargs)


def _install_lightweight_ui_stubs():
    if "ui.dialogs" not in sys.modules:
        dialogs_module = types.ModuleType("ui.dialogs")
        dialogs_module.ModelDownloadDialog = type("ModelDownloadDialog", (), {})
        sys.modules["ui.dialogs"] = dialogs_module

    if "ui.views.table_views" not in sys.modules:
        table_views_module = types.ModuleType("ui.views.table_views")

        def _populate_result_table(*_args, **_kwargs):
            return None

        table_views_module.populate_result_table = _populate_result_table
        sys.modules["ui.views.table_views"] = table_views_module

    workers_module = sys.modules.get("ui.workers")
    if workers_module is not None and getattr(workers_module, "__file__", None):
        return

    # Prefer the real workers module when importable (keeps SearchConfig etc.).
    try:
        import ui.workers as real_workers  # noqa: F401

        if getattr(real_workers, "__file__", None):
            return
    except Exception:
        pass

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

    class _SearchConfig:
        def __init__(self, *args, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    workers_module.SearchConfig = _SearchConfig
    workers_module.ResourceDownloadWorker = _BaseWorker
    workers_module.SearchWorker = _BaseWorker
    workers_module.SearchWarmupWorker = _BaseWorker
    workers_module.PreviewWarmupWorker = _BaseWorker
    workers_module.LocalVectorDetailsWorker = _BaseWorker
    workers_module.ThumbLoader = _BaseWorker
    workers_module.IndexUpdateWorker = _BaseWorker
    sys.modules["ui.workers"] = workers_module


def _install_pyside_stub():
    for module_name in list(sys.modules):
        if module_name == "PySide6" or module_name.startswith("PySide6."):
            del sys.modules[module_name]

    if "PySide6" in sys.modules:
        return

    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _SignalLocal:
        def __init__(self, *args, **kwargs):
            self._subscribers = []

        def connect(self, callback):
            self._subscribers.append(callback)

        def emit(self, *args, **kwargs):
            for callback in list(self._subscribers):
                callback(*args, **kwargs)

    class _Qt:
        AlignCenter = 0x84
        AlignHCenter = 4
        AlignVCenter = 0x80
        AlignBottom = 64
        WA_NativeWindow = 100
        WA_DontCreateNativeAncestors = 101
        Horizontal = 1
        Key_Space = 32

        class WidgetAttribute:
            WA_NativeWindow = 100
            WA_DontCreateNativeAncestors = 101

        class TextElideMode:
            ElideRight = 2

    class _StubMixin:
        def __getattr__(self, name):
            if name.startswith(("set", "add", "insert", "remove", "clear", "block")):
                return lambda *_args, **_kwargs: None
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    class _QLabel(_StubMixin):
        def __init__(self, *_args, **_kwargs):
            self._text = ""

        def setAlignment(self, *_args, **_kwargs):
            pass

        def setPixmap(self, *_args, **_kwargs):
            pass

        def setText(self, value):
            self._text = value

        def text(self):
            return self._text

        def setWordWrap(self, *_args, **_kwargs):
            pass

        def setObjectName(self, *_args, **_kwargs):
            pass

        def setMinimumHeight(self, *_args, **_kwargs):
            pass

        def setTextInteractionFlags(self, *_args, **_kwargs):
            pass

        def setVisible(self, *_args, **_kwargs):
            pass

    class _QUrl:
        def __init__(self, value=""):
            self.value = value

        @classmethod
        def fromLocalFile(cls, path):
            return cls(path)

    class _QTimer:
        def __init__(self, *_args, **_kwargs):
            self.timeout = _SignalLocal()

        def setInterval(self, *_args, **_kwargs):
            return None

        def start(self):
            return None

        def stop(self):
            return None

        @staticmethod
        def singleShot(*_args, **_kwargs):
            return None

    class _QThread:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            return None

        def isRunning(self):
            return False

    class _WidgetBase(_StubMixin):
        def __init__(self, *_args, **_kwargs):
            self._enabled = True

        def setEnabled(self, value):
            self._enabled = bool(value)

        def isEnabled(self):
            return self._enabled

        def setMinimumHeight(self, *_args, **_kwargs):
            pass

        def setStyleSheet(self, *_args, **_kwargs):
            pass

        def setObjectName(self, *_args, **_kwargs):
            pass

        def setSizePolicy(self, *_args, **_kwargs):
            pass

        def setVisible(self, *_args, **_kwargs):
            pass

    class _QPushButton(_WidgetBase):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            self.clicked = _SignalLocal()
            self._text = ""

        def setText(self, value):
            self._text = value

        def text(self):
            return self._text

    class _QSlider(_WidgetBase):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            self.sliderPressed = _SignalLocal()
            self.sliderReleased = _SignalLocal()
            self._value = 0

        def setRange(self, *_args, **_kwargs):
            pass

        def setValue(self, value):
            self._value = value

        def value(self):
            return self._value

        def blockSignals(self, *_args, **_kwargs):
            pass

    class _QBoxLayout(_StubMixin):
        def __init__(self, *_args, **_kwargs):
            pass

        def addWidget(self, *_args, **_kwargs):
            pass

        def addLayout(self, *_args, **_kwargs):
            pass

        def setContentsMargins(self, *_args, **_kwargs):
            pass

        def setSpacing(self, *_args, **_kwargs):
            pass

    class _QDialog(_WidgetBase):
        def __init__(self, *_args, **_kwargs):
            super().__init__()
            self._fullscreen = False

        def setWindowTitle(self, *_args, **_kwargs):
            pass

        def resize(self, *_args, **_kwargs):
            pass

        def showNormal(self):
            self._fullscreen = False

        def showFullScreen(self):
            self._fullscreen = True

        def isFullScreen(self):
            return self._fullscreen

        def hide(self):
            pass

    class _QSizePolicy:
        class Policy:
            Fixed = 0
            Maximum = 4
            Preferred = 5
            Expanding = 7

    qtcore.QThread = _QThread
    qtcore.QObject = _QObject
    qtcore.Signal = _SignalLocal
    qtcore.Qt = _Qt
    qtcore.QUrl = _QUrl
    qtcore.QTimer = _QTimer
    qtwidgets.QLabel = _QLabel
    qtwidgets.QDialog = _QDialog
    qtwidgets.QFileDialog = type(
        "QFileDialog",
        (),
        {
            "getSaveFileName": staticmethod(lambda *_args, **_kwargs: ("", "")),
            "getOpenFileName": staticmethod(lambda *_args, **_kwargs: ("", "")),
            "getExistingDirectory": staticmethod(lambda *_args, **_kwargs: ""),
        },
    )
    qtwidgets.QHBoxLayout = _QBoxLayout
    qtwidgets.QVBoxLayout = _QBoxLayout
    qtwidgets.QPushButton = _QPushButton
    qtwidgets.QSlider = _QSlider
    qtwidgets.QWidget = _WidgetBase
    qtwidgets.QTableWidget = _WidgetBase
    qtwidgets.QAbstractItemView = type("QAbstractItemView", (), {"SelectRows": 1})
    qtwidgets.QSizePolicy = _QSizePolicy

    class _QApplication:
        @staticmethod
        def instance():
            return None

        @staticmethod
        def clipboard():
            return MagicMock()

    qtwidgets.QApplication = _QApplication
    qtgui.QFontMetrics = _QLabel

    pyside6 = types.ModuleType("PySide6")
    pyside6.__path__ = []
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtWidgets"] = qtwidgets


IndexingController = None
MobileBridgeController = None
PreviewController = None
PreviewDialog = None
RuntimeResourceController = None
SearchController = None
VlcPreviewPlayer = None


def setUpModule():
    global IndexingController, MobileBridgeController, PreviewController
    global PreviewDialog, RuntimeResourceController, SearchController, VlcPreviewPlayer

    for module_name in (
        "ui.controllers.indexing_controller",
        "ui.controllers.mobile_bridge_controller",
        "ui.controllers.runtime_resource_controller",
        "ui.controllers.preview_controller",
        "ui.playback.preview_dialog",
        "ui.controllers.search_controller",
        "ui.playback.vlc_player",
    ):
        sys.modules.pop(module_name, None)

    _install_lightweight_ui_stubs()
    _install_pyside_stub()

    from ui.controllers.indexing_controller import IndexingController as _IndexingController
    from ui.controllers.mobile_bridge_controller import MobileBridgeController as _MobileBridgeController
    from ui.controllers.runtime_resource_controller import RuntimeResourceController as _RuntimeResourceController
    from ui.controllers.preview_controller import PreviewController as _PreviewController
    from ui.playback.preview_dialog import PreviewDialog as _PreviewDialog
    from ui.controllers.search_controller import SearchController as _SearchController
    from ui.playback.vlc_player import VlcPreviewPlayer as _VlcPreviewPlayer

    IndexingController = _IndexingController
    MobileBridgeController = _MobileBridgeController
    RuntimeResourceController = _RuntimeResourceController
    PreviewController = _PreviewController
    PreviewDialog = _PreviewDialog
    SearchController = _SearchController
    VlcPreviewPlayer = _VlcPreviewPlayer


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
    parent.search_page.result_view = MagicMock()
    parent.result_table = MagicMock()
    parent.push_inference_status = MagicMock()
    parent.push_resources_status = MagicMock()
    return parent


class RuntimeResourceControllerTests(unittest.TestCase):
    @patch("ui.controllers.runtime_resource_controller.get_runtime_resource_location_text", return_value="Resources")
    @patch("ui.controllers.runtime_resource_controller.ensure_runtime_resource_dirs")
    @patch("ui.controllers.runtime_resource_controller.get_runtime_resource_status")
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

    @patch("ui.controllers.runtime_resource_controller.get_texts")
    @patch("ui.controllers.runtime_resource_controller.get_runtime_resource_status")
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

    @patch("ui.controllers.runtime_resource_controller.ResourceDownloadWorker")
    @patch("ui.controllers.runtime_resource_controller.get_runtime_resource_status")
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


class IndexingControllerTests(unittest.TestCase):
    @patch("ui.controllers.indexing_controller.IndexUpdateWorker")
    def test_start_passes_rebuild_global_assets_flag_to_worker(self, mock_worker_cls):
        parent = _make_parent_window()
        controller = IndexingController(parent)
        worker = MagicMock()
        worker.isRunning.return_value = False
        mock_worker_cls.return_value = worker

        started = controller.start(target_lib="D:/videos", rebuild_global_assets=False)

        self.assertTrue(started)
        mock_worker_cls.assert_called_once_with(
            target_lib="D:/videos",
            force_cleanup_missing_files=False,
            cleanup_missing_entries=None,
            rebuild_global_assets=False,
            index_from_vectors_only=False,
        )
        worker.start.assert_called_once()


class MobileBridgeControllerTests(unittest.TestCase):
    @patch("ui.controllers.mobile_bridge_controller.MobileBridgeService")
    def test_start_creates_service_once_and_returns_access_url(self, mock_service_cls):
        parent = _make_parent_window()
        service = MagicMock()
        service.is_running.side_effect = [False, True]
        service.get_access_url.return_value = "http://192.168.1.2:8918/?token=abc"
        mock_service_cls.return_value = service
        controller = MobileBridgeController(parent)
        statuses = []
        controller.status_changed.connect(statuses.append)

        url = controller.start()

        mock_service_cls.assert_called_once()
        kwargs = mock_service_cls.call_args.kwargs
        self.assertTrue(callable(kwargs["on_search_requested"]))
        service.start.assert_called_once()
        self.assertEqual(url, "http://192.168.1.2:8918/?token=abc")
        self.assertEqual(statuses, ["running"])

    @patch("ui.controllers.mobile_bridge_controller.MobileBridgeService")
    def test_start_reuses_running_service_without_restarting(self, mock_service_cls):
        parent = _make_parent_window()
        service = MagicMock()
        service.is_running.return_value = True
        service.get_access_url.return_value = "http://192.168.1.2:8918/?token=abc"
        mock_service_cls.return_value = service
        controller = MobileBridgeController(parent)
        statuses = []
        controller.status_changed.connect(statuses.append)

        first_url = controller.start()
        second_url = controller.start()

        self.assertEqual(first_url, "http://192.168.1.2:8918/?token=abc")
        self.assertEqual(second_url, "http://192.168.1.2:8918/?token=abc")
        service.start.assert_not_called()
        self.assertEqual(statuses, [])

    def test_handle_search_requested_emits_payload(self):
        parent = _make_parent_window()
        controller = MobileBridgeController(parent)
        received = []
        controller.search_requested.connect(received.append)

        payload = {
            "search_kind": "compose",
            "query": "night rain",
            "image_path": "D:/Migrated/data/mobile_uploads/query.png",
            "source": "192.168.1.10",
        }
        controller._handle_search_requested(payload)

        self.assertEqual(received, [payload])


class SearchControllerTests(unittest.TestCase):
    @patch("ui.controllers.search_controller.SearchWorker")
    def test_start_search_disables_button_and_starts_worker(self, mock_worker_cls):
        parent = _make_parent_window()
        controller = SearchController(parent)
        worker = MagicMock()
        mock_worker_cls.return_value = worker

        controller.start_search("cat", True)

        parent.search_page.btn_search.setEnabled.assert_called_with(False)
        parent.search_page.lbl_status.setText.assert_called_with("Searching...")
        mock_worker_cls.assert_called_once()
        config = mock_worker_cls.call_args.args[0]
        self.assertEqual(config.query, "cat")
        self.assertTrue(config.is_text)
        self.assertEqual(config.scope_library_paths, [])
        self.assertEqual(config.scope_video_paths, [])
        worker.start.assert_called_once()

    @patch("ui.controllers.search_controller.shutdown_thread")
    @patch("ui.controllers.search_controller.SearchWorker")
    def test_start_search_stops_previous_worker(self, mock_worker_cls, mock_shutdown_thread):
        parent = _make_parent_window()
        controller = SearchController(parent)
        first_worker = MagicMock()
        second_worker = MagicMock()
        mock_worker_cls.side_effect = [first_worker, second_worker]

        controller.start_search("cat", True)
        controller.start_search("dog", True)

        mock_shutdown_thread.assert_called_once_with(first_worker, allow_terminate=False)
        self.assertIs(controller.worker, second_worker)
        second_worker.start.assert_called_once()

    def test_clear_results_resets_table(self):
        parent = _make_parent_window()
        controller = SearchController(parent)
        controller.stop_thumbnail_loading = MagicMock()

        controller.clear_results()

        controller.stop_thumbnail_loading.assert_called_once()
        parent.search_page.result_view.clear.assert_called_once()

    def test_display_results_handles_empty_result(self):
        parent = _make_parent_window()
        controller = SearchController(parent)
        controller.worker = MagicMock()
        controller._is_current_worker = MagicMock(return_value=True)

        controller._display_results([])

        parent.search_page.result_view.clear.assert_called_once()
        parent.search_page.lbl_status.setText.assert_called_with("No results")

    @patch("ui.controllers.search_controller.SearchWarmupWorker")
    def test_start_warmup_starts_once(self, mock_worker_cls):
        parent = _make_parent_window()
        controller = SearchController(parent)
        worker = MagicMock()
        mock_worker_cls.return_value = worker

        controller.start_warmup()
        controller.start_warmup()

        mock_worker_cls.assert_called_once_with()
        worker.start.assert_called_once()

    def test_finish_warmup_refreshes_runtime_backend_hint(self):
        parent = _make_parent_window()
        controller = SearchController(parent)
        controller.warmup_worker = MagicMock()

        controller._finish_warmup()

        self.assertIsNone(controller.warmup_worker)
        parent.push_inference_status.assert_called_once()


class PreviewControllerTests(unittest.TestCase):
    @patch("ui.controllers.preview_controller.warmup_vlc_runtime")
    @patch("ui.controllers.preview_controller.QTimer.singleShot")
    def test_start_warmup_starts_once(self, mock_single_shot, mock_warmup):
        parent = _make_parent_window()
        controller = PreviewController(parent)

        controller.start_warmup()
        controller.start_warmup()

        mock_single_shot.assert_called_once()
        args, _kwargs = mock_single_shot.call_args
        self.assertEqual(args[0], 0)
        args[1]()
        mock_warmup.assert_called_once_with()

    @patch("ui.controllers.preview_controller._resolve_base_clip_window", return_value=(27.0, 6.0))
    @patch("ui.controllers.preview_controller.VlcPreviewPlayer")
    def test_play_prefers_vlc_for_direct_preview(self, mock_vlc_cls, _mock_window):
        parent = _make_parent_window()
        vlc_player = MagicMock()
        vlc_player.play.return_value = True
        mock_vlc_cls.return_value = vlc_player
        controller = PreviewController(parent)

        result = controller.play("D:/videos/clip.mp4", 30.0)

        self.assertTrue(result)
        mock_vlc_cls.assert_called_once_with(parent.video_widget)
        vlc_player.play.assert_called_once_with("D:/videos/clip.mp4", 27.0, stop_sec=33.0)
        parent.media_player.setSource.assert_called_once()

    @patch("ui.controllers.preview_controller._resolve_base_clip_window", return_value=(27.0, 6.0))
    @patch("ui.controllers.preview_controller.VlcPreviewPlayer")
    def test_play_http_prefers_qt_multimedia(self, mock_vlc_cls, _mock_window):
        parent = _make_parent_window()
        controller = PreviewController(parent)
        url = "http://192.168.1.2:18080/videos/lib1/a.mp4"
        controller._play_remote_with_qt = MagicMock(return_value=True)

        result = controller.play(url, 30.0, end_sec=33.0)

        self.assertTrue(result)
        controller._play_remote_with_qt.assert_called_once_with(url, 27.0, 33.0)
        mock_vlc_cls.assert_not_called()

    @patch("ui.controllers.preview_controller.create_preview_clip")
    @patch("ui.controllers.preview_controller.build_preview_cache_path", return_value="D:/cache/preview.mp4")
    @patch("ui.controllers.preview_controller._resolve_base_clip_window", return_value=(27.0, 6.0))
    @patch("ui.controllers.preview_controller.VlcPreviewPlayer")
    def test_play_falls_back_to_generated_clip_when_vlc_playback_fails(
        self,
        mock_vlc_cls,
        _mock_window,
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
        controller.vlc_player.get_time.return_value = -1
        controller.vlc_player.is_available.return_value = False
        controller.current_preview_context = {
            "video_path": "D:/videos/clip.mp4",
            "start_sec": 1.0,
            "end_sec": 3.0,
        }
        controller.cleanup_previous_preview = MagicMock()

        controller.stop_preview()

        controller.vlc_player.suspend.assert_called_once()
        parent.media_player.pause.assert_called_once()
        parent.media_player.setSource.assert_called_once()
        controller.cleanup_previous_preview.assert_called_once()
        self.assertIsNone(controller.current_preview_context)


class VlcPreviewPlayerTests(unittest.TestCase):
    def test_build_vlc_media_options_http_skips_start_time(self):
        from ui.playback.vlc_player import _build_vlc_media_options

        options = _build_vlc_media_options("http://host/videos/lib1/a.mp4", 64.0)
        self.assertIn(":network-caching=800", options)
        self.assertTrue(all(not item.startswith(":start-time=") for item in options))

        local = _build_vlc_media_options(r"D:\videos\a.mp4", 64.0)
        self.assertIn(":start-time=64.000", local)

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

        mock_player.pause.assert_called_once()
        mock_player.stop.assert_called_once()
        mock_player.release.assert_called_once()
        mock_instance.release.assert_called_once()
        self.assertIsNone(player._player)
        self.assertIsNone(player._instance)
        self.assertTrue(player._released)
        # Detach happens after stop/clear, not before.
        if sys.platform == "win32":
            self.assertEqual(mock_player.set_hwnd.call_args_list[-1][0][0], 0)
        elif sys.platform == "darwin":
            self.assertEqual(mock_player.set_nsobject.call_args_list[-1][0][0], 0)
        else:
            self.assertEqual(mock_player.set_xwindow.call_args_list[-1][0][0], 0)

    def test_shutdown_with_shared_instance_does_not_release_instance(self):
        host = MagicMock()
        host.winId.return_value = 123
        shared = MagicMock()
        shared.media_player_new.return_value = MagicMock()
        player = VlcPreviewPlayer(host, shared_instance=shared)
        mock_player = player._player
        player.shutdown()

        mock_player.pause.assert_called_once()
        mock_player.stop.assert_called_once()
        mock_player.release.assert_called_once()
        shared.release.assert_not_called()
        self.assertIsNone(player._player)
        self.assertIsNone(player._instance)
        self.assertTrue(player._released)

    def test_stop_soft_pauses_without_clearing_media(self):
        # Avoid QTimer(host) construction; stub/real PySide6 mix breaks MagicMock parents.
        player = VlcPreviewPlayer.__new__(VlcPreviewPlayer)
        player._released = False
        player._timer = MagicMock()
        player._player = MagicMock()
        player._stop_at_ms = 1000
        player._locked_stop_at_ms = 1000
        player._pending_seek_ms = 0
        old_media = MagicMock()
        player._current_media = old_media

        player.stop()

        # Soft stop avoids native stop()/set_media(None) which hang/spawn D3D windows.
        player._player.stop.assert_not_called()
        player._player.set_media.assert_not_called()
        player._player.pause.assert_called_once()
        player._player.audio_set_mute.assert_called_once_with(True)
        old_media.release.assert_not_called()
        self.assertIs(player._current_media, old_media)

    def test_set_media_releases_previous_media(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()
        old_media = MagicMock()
        new_media = MagicMock()
        player._current_media = old_media

        player._set_media(new_media)

        player._player.set_media.assert_called_once_with(new_media)
        old_media.release.assert_called_once()
        self.assertIs(player._current_media, new_media)

    def test_rebind_output_window_sets_platform_handle(self):
        host = MagicMock()
        host.winId.return_value = 456
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()
        player._released = False

        player.rebind_output_window()

        if sys.platform == "win32":
            player._player.set_hwnd.assert_called_once_with(456)
        elif sys.platform == "darwin":
            player._player.set_nsobject.assert_called_once_with(456)
        else:
            player._player.set_xwindow.assert_called_once_with(456)

    def test_resume_restarts_media_when_playback_has_reached_end(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()
        player._instance = MagicMock()
        player._current_video_path = "D:/videos/clip.mp4"
        player._pending_seek_ms = 12000
        player.get_time = MagicMock(return_value=30000)
        player.get_length = MagicMock(return_value=30000)
        old_media = MagicMock()
        player._current_media = old_media
        new_media = MagicMock()
        player._instance.media_new.return_value = new_media
        player._player.play.return_value = 0

        result = player.resume()

        self.assertTrue(result)
        player._instance.media_new.assert_called_once_with("D:/videos/clip.mp4", ":start-time=12.000")
        player._player.set_media.assert_called_once_with(new_media)
        old_media.release.assert_called_once()
        self.assertIs(player._current_media, new_media)

    def test_resume_restarts_from_zero_when_playback_has_reached_end_without_seek(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()
        player._instance = MagicMock()
        player._current_video_path = "D:/videos/clip.mp4"
        player._pending_seek_ms = None
        player.get_time = MagicMock(return_value=30000)
        player.get_length = MagicMock(return_value=30000)
        player._instance.media_new.return_value = "media"
        player._player.play.return_value = 0

        result = player.resume()

        self.assertTrue(result)
        player._instance.media_new.assert_called_once_with("D:/videos/clip.mp4", ":start-time=0.000")

    def test_resume_prioritizes_pending_seek_position(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        player._player = MagicMock()
        player._instance = MagicMock()
        player._current_video_path = "D:/videos/clip.mp4"
        player._pending_seek_ms = 8000
        player.get_time = MagicMock(return_value=1000)
        player.get_length = MagicMock(return_value=30000)
        player._instance.media_new.return_value = "media"
        player._player.play.return_value = 0

        result = player.resume()

        self.assertTrue(result)
        player._instance.media_new.assert_called_once_with("D:/videos/clip.mp4", ":start-time=8.000")


class PreviewDialogTests(unittest.TestCase):
    def test_expanded_chrome_slider_release_uses_known_duration(self):
        from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome

        chrome = ExpandedPreviewChrome()
        chrome.apply_texts({"preview_dialog_pause": "Pause", "preview_dialog_play": "Play"})
        player = MagicMock()
        player.get_length.return_value = -1
        player.get_time.return_value = 0
        player.is_playing.return_value = False
        player.is_available.return_value = True
        chrome.bind_player(player)
        chrome.attach_clip("D:/videos/clip.mp4", 10.0, 16.0, suggested_sec=12.0)
        chrome._known_total_ms = 120000
        chrome.slider.setValue(500)
        chrome._on_slider_released()
        player.set_time.assert_called_once_with(60000, unlock=True)

    @patch("ui.playback.preview_dialog.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    @patch("ui.playback.preview_dialog.VlcPreviewPlayer")
    def test_slider_release_uses_known_duration_when_vlc_length_is_unavailable(self, mock_vlc_cls, _mock_timer):
        parent = MagicMock()
        player = MagicMock()
        player.play.return_value = True
        player.get_length.return_value = -1
        player.get_time.return_value = 0
        player.is_playing.return_value = False
        player.is_available.return_value = True
        mock_vlc_cls.return_value = player

        dialog = PreviewDialog(parent, "D:/videos/clip.mp4", 10.0, 16.0, {"preview_dialog_pause": "Pause"})
        dialog._known_total_ms = 120000
        dialog.slider.setValue(500)
        dialog._on_slider_released()

        player.set_time.assert_called_once_with(60000, unlock=True)

    @patch("ui.playback.preview_dialog.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    @patch("ui.playback.preview_dialog.VlcPreviewPlayer")
    def test_sync_ui_holds_pending_seek_position_during_zero_time_flash(self, mock_vlc_cls, _mock_timer):
        parent = MagicMock()
        player = MagicMock()
        player.play.return_value = True
        player.get_length.return_value = 120000
        player.get_time.return_value = 0
        player.is_playing.return_value = True
        player.is_available.return_value = True
        mock_vlc_cls.return_value = player

        dialog = PreviewDialog(parent, "D:/videos/clip.mp4", 10.0, 16.0, {"preview_dialog_pause": "Pause"})
        dialog._pending_ui_seek_ms = 8000

        dialog._sync_ui()

        self.assertEqual(dialog.slider.value(), int((8000 / 120000) * 1000))

    @patch("ui.playback.preview_dialog.QTimer.singleShot", side_effect=lambda _ms, fn: fn())
    @patch("ui.playback.preview_dialog.VlcPreviewPlayer")
    def test_load_preview_reuses_player_without_full_teardown(self, mock_vlc_cls, _mock_timer):
        parent = MagicMock()
        player = MagicMock()
        player.play.return_value = True
        player.get_length.return_value = 120000
        player.get_time.return_value = 0
        player.is_playing.return_value = False
        player.is_available.return_value = True
        mock_vlc_cls.return_value = player

        dialog = PreviewDialog(parent, "D:/videos/clip.mp4", 10.0, 16.0, {"preview_dialog_pause": "Pause"})
        self.assertIs(dialog.player, player)

        dialog.load_preview("D:/videos/other.mp4", 20.0, 26.0, suggested_sec=22.0)

        player.shutdown.assert_not_called()
        self.assertIs(dialog.player, player)
        self.assertEqual(player.play.call_count, 2)
        player.play.assert_called_with("D:/videos/other.mp4", 20.0, stop_sec=26.0)
        self.assertEqual(mock_vlc_cls.call_count, 1)
        player.suspend.assert_called()

    def test_shutdown_fast_skips_blocking_stop_and_release(self):
        host = MagicMock()
        host.winId.return_value = 123
        player = VlcPreviewPlayer(host)
        mock_player = MagicMock()
        mock_instance = MagicMock()
        player._player = mock_player
        player._instance = mock_instance
        player._owns_instance = True

        player.shutdown(fast=True)

        mock_player.stop.assert_not_called()
        mock_player.release.assert_not_called()
        mock_instance.release.assert_not_called()
        mock_player.audio_set_mute.assert_called_once_with(True)
        mock_player.pause.assert_called_once()
        mock_player.set_media.assert_called_with(None)
        self.assertTrue(player._released)
        self.assertIsNone(player._player)


if __name__ == "__main__":
    unittest.main()
