import importlib
import os
import sys
import types
import unittest
import json
from contextlib import ExitStack
from unittest.mock import MagicMock, call, patch


def _build_stub_modules():
    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtmultimedia = types.ModuleType("PySide6.QtMultimedia")
    qtmultimediawidgets = types.ModuleType("PySide6.QtMultimediaWidgets")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _Qt:
        WA_NativeWindow = 0
        WA_TransparentForMouseEvents = 0
        ScrollBarAlwaysOff = 0
        AlignCenter = 0
        KeepAspectRatio = 0
        SmoothTransformation = 0

    class _QTimer:
        @staticmethod
        def singleShot(*_args, **_kwargs):
            return None

    class _Widget:
        def __init__(self, *_args, **_kwargs):
            pass

    class _Application:
        @staticmethod
        def instance():
            return MagicMock()

        @staticmethod
        def clipboard():
            return MagicMock()

    class _QEasingCurve:
        InOutQuad = 0

    class _QPropertyAnimation:
        def __init__(self, *_args, **_kwargs):
            pass

        def setDuration(self, *_a, **_k):
            return None

        def setStartValue(self, *_a, **_k):
            return None

        def setEndValue(self, *_a, **_k):
            return None

        def setEasingCurve(self, *_a, **_k):
            return None

        def start(self, *_a, **_k):
            return None

    class _QObject:
        def __init__(self, parent=None):
            pass

    class _QThread(_QObject):
        def start(self, *_a, **_k):
            return None

        def isRunning(self):
            return False

        def run(self):
            return None

        def quit(self):
            return None

        def wait(self, *_a, **_k):
            return True

    class _QUrl:
        def __init__(self, *_a, **_k):
            pass

    def _make_signal(*_types):
        sig = MagicMock()
        sig.connect = MagicMock()
        sig.emit = MagicMock()
        return sig

    qtcore.Qt = _Qt
    qtcore.QTimer = _QTimer
    qtcore.QEasingCurve = _QEasingCurve
    qtcore.QPropertyAnimation = _QPropertyAnimation
    qtcore.QObject = _QObject
    qtcore.QThread = _QThread
    qtcore.QUrl = _QUrl
    qtcore.Signal = _make_signal
    qtgui.QPixmap = _Widget
    qtgui.QImage = _Widget
    qtgui.QColor = _Widget
    qtmultimedia.QAudioOutput = _Widget
    qtmultimedia.QMediaPlayer = _Widget
    qtmultimediawidgets.QVideoWidget = _Widget
    qtwidgets.QApplication = _Application
    qtwidgets.QFileDialog = type(
        "QFileDialog",
        (),
        {
            "getOpenFileName": staticmethod(lambda *_args, **_kwargs: ("", "")),
            "getExistingDirectory": staticmethod(lambda *_args, **_kwargs: ""),
        },
    )
    qtwidgets.QFrame = _Widget
    qtwidgets.QMainWindow = _Widget
    qtwidgets.QMessageBox = _Widget
    qtwidgets.QScrollArea = _Widget
    qtwidgets.QStackedWidget = _Widget
    qtwidgets.QVBoxLayout = _Widget
    qtwidgets.QWidget = _Widget
    qtwidgets.QHBoxLayout = _Widget
    qtwidgets.QAbstractItemView = _Widget
    qtwidgets.QGraphicsOpacityEffect = _Widget
    qtwidgets.QLabel = _Widget
    qtwidgets.QDialog = _Widget
    qtwidgets.QPushButton = _Widget
    qtwidgets.QSlider = _Widget
    qtwidgets.QTableWidget = _Widget
    qtwidgets.QTableWidgetItem = _Widget
    qtwidgets.QHeaderView = _Widget

    config_module = types.ModuleType("src.app.config")
    config_module.DEFAULT_CONFIG = {"data_root": "D:/VideoSeek"}
    config_module.CONFIG_ENUMS = {
        "chunk_similarity_mode": {"chunk", "frame"},
        "search_mode": {"frame", "chunk"},
        "theme": {"dark", "light"},
        "language": {"zh", "en"},
    }
    config_module.get_app_version = lambda: "1.0.0"
    config_module.get_configured_data_root = lambda config=None: "D:/VideoSeek"
    config_module.get_data_storage_paths = lambda config=None: {
        "remote_build_cache_dir": "D:/VideoSeek/data/remote_build_cache",
        "link_cache_dir": "D:/VideoSeek/data/link_cache",
    }
    config_module.load_config = lambda: {}
    config_module.pop_migration_notice = lambda: None
    config_module.save_config = lambda config: None

    i18n_module = types.ModuleType("src.app.i18n")
    i18n_module.get_texts = lambda language="zh": {}

    clip_module = types.ModuleType("src.core.clip_embedding")
    clip_module.get_engine_runtime_status = lambda: {}
    clip_module.get_engine_runtime_warning = lambda: None
    clip_module.reset_engine = lambda: None

    about_module = types.ModuleType("src.services.about_service")
    about_module.get_local_about_payload = lambda language="zh": {}

    library_module = types.ModuleType("src.services.library_service")
    library_module.GLOBAL_INDEX_STATE_STALE = "stale"
    library_module.add_library = lambda path: {}
    library_module.get_global_index_state = lambda: ""
    library_module.list_libraries = lambda: {}
    library_module.list_local_vector_details = lambda validate_contents=False: {}
    library_module.list_partial_libraries = lambda: []
    library_module.remove_library = lambda path, callback=None: True

    notice_module = types.ModuleType("src.services.notice_service")
    notice_module.get_local_notice_payload = lambda language="zh": {}

    indexing_module = types.ModuleType("src.services.indexing_service")
    indexing_module.list_missing_library_files = lambda meta, config, target_lib=None: []

    storage_module = types.ModuleType("src.services.storage_service")
    storage_module.migrate_app_data_root = lambda target_root: {}
    storage_module.migrate_model_root = lambda target_root: {"migrated": True, "old_model_dir": "", "new_model_dir": ""}
    storage_module.cleanup_old_model_dir = lambda pending_root, active_model_dir=None: {"cleaned": True, "old_model_dir": ""}
    storage_module.cleanup_old_data_root = lambda target_root, active_data_root=None: {}

    query_module = types.ModuleType("src.services.query_text_service")
    query_module.prepare_text_query = lambda text: {
        "normalized": text,
        "too_short": False,
        "changed": False,
        "generic": False,
    }

    remote_library_module = types.ModuleType("src.services.remote_library_service")
    remote_library_module.list_remote_link_details = lambda: {}

    precheck_module = types.ModuleType("src.services.remote_link_precheck_service")
    precheck_module.precheck_remote_links = lambda links: {}

    qr_module = types.ModuleType("src.web.display_qr")
    qr_module.build_qr_pixmap = lambda url: None

    workflow_module = types.ModuleType("src.workflows.update_video")
    workflow_module.delete_physical_video_data = lambda video_id, config=None: None

    utils_module = types.ModuleType("src.utils")
    utils_module.get_app_data_dir = lambda: "D:/VideoSeek"
    utils_module.get_ffmpeg_status_text = lambda: "ffmpeg"
    utils_module.get_configured_model_dir = lambda: "D:/VideoSeek/models"
    utils_module.load_meta = lambda path: {"libraries": {}}
    utils_module.save_meta = lambda meta, path: None
    utils_module.normalize_sampling_fps_mode = lambda value: value
    utils_module.normalize_sampling_fps_rules_text = lambda value: value
    utils_module.open_folder_in_explorer = lambda path: None
    utils_module.open_in_explorer = lambda path: None
    utils_module.parse_sampling_fps_rules = lambda text: []
    utils_module.resolve_sampling_fps = lambda *args, **kwargs: 1.0
    utils_module.validate_sampling_fps_rules = lambda text: (True, "")
    utils_module.validate_sampling_fps_rules_full_coverage = lambda text: (True, "")
    utils_module.ensure_sampling_fps_rules_open_tail = lambda text: text
    utils_module.get_configured_ffmpeg_target_path = lambda: ""
    utils_module.get_resource_path = lambda name: ""
    utils_module.sync_ffmpeg_path_to_config = lambda: ""
    utils_module.sync_model_dir_to_config = lambda: ""

    version_module = types.ModuleType("src.services.version_service")
    version_module.get_local_version_status = lambda language="zh": {}

    model_package_module = types.ModuleType("src.services.model_package_service")
    model_package_module.remove_model_profile = lambda *args, **kwargs: None
    model_package_module.ensure_default_clip_manifest = lambda *args, **kwargs: None

    def _stub_class(name):
        return type(name, (), {})

    stubs = {
        "PySide6": pyside6,
        "PySide6.QtCore": qtcore,
        "PySide6.QtGui": qtgui,
        "PySide6.QtMultimedia": qtmultimedia,
        "PySide6.QtMultimediaWidgets": qtmultimediawidgets,
        "PySide6.QtWidgets": qtwidgets,
        "src.services.model_package_service": model_package_module,
        "src.app.config": config_module,
        "src.app.i18n": i18n_module,
        "src.core.clip_embedding": clip_module,
        "src.services.about_service": about_module,
        "src.services.library_service": library_module,
        "src.services.notice_service": notice_module,
        "src.services.indexing_service": indexing_module,
        "src.services.storage_service": storage_module,
        "src.services.query_text_service": query_module,
        "src.services.remote_library_service": remote_library_module,
        "src.services.remote_link_precheck_service": precheck_module,
        "src.web.display_qr": qr_module,
        "src.workflows.update_video": workflow_module,
        "src.utils": utils_module,
        "src.services.version_service": version_module,
    }

    module_specs = {
        "ui.controllers.app_meta_controller": {"AppMetaController": _stub_class("AppMetaController")},
        "ui.widgets.components": {
            "LibraryPage": _stub_class("LibraryPage"),
            "LinkSearchPage": _stub_class("LinkSearchPage"),
            "NavigationSidebar": _stub_class("NavigationSidebar"),
            "SearchPage": _stub_class("SearchPage"),
            "TraceViewerPage": _stub_class("TraceViewerPage"),
        },
        "ui.widgets.settings": {
            "SettingsPage": _stub_class("SettingsPage"),
        },
        "ui.dialogs": {
            "AboutDialog": _stub_class("AboutDialog"),
            "AppMessageDialog": _stub_class("AppMessageDialog"),
            "MobileBridgeDialog": _stub_class("MobileBridgeDialog"),
            "NoticeDialog": _stub_class("NoticeDialog"),
            "ResourceTableDialog": _stub_class("ResourceTableDialog"),
            "SamplingRulesDialog": _stub_class("SamplingRulesDialog"),
        },
        "ui.controllers.indexing_controller": {"IndexingController": _stub_class("IndexingController")},
        "ui.widgets.layout": {"WINDOW_SIZES": {}, "apply_window_size": lambda *args, **kwargs: None},
        "ui.controllers.mobile_bridge_controller": {"MobileBridgeController": _stub_class("MobileBridgeController")},
        "ui.controllers.network_search_controller": {"NetworkSearchController": _stub_class("NetworkSearchController")},
        "ui.playback.preview_dialog": {
            "ExportCancelledError": type("ExportCancelledError", (Exception,), {}),
            "ExportClipWorker": _stub_class("ExportClipWorker"),
            "PreviewDialog": _stub_class("PreviewDialog"),
        },
        "ui.controllers.preview_controller": {"PreviewController": _stub_class("PreviewController")},
        "ui.controllers.runtime_resource_controller": {"RuntimeResourceController": _stub_class("RuntimeResourceController")},
        "ui.controllers.search_controller": {"SearchController": _stub_class("SearchController")},
        "ui.widgets.styles": {
            "DARK_STYLE": "",
            "LIGHT_STYLE": "",
            "set_runtime_banner_warn": lambda *args, **kwargs: None,
        },
        "ui.views.table_views": {
            "populate_library_table": lambda *args, **kwargs: None,
            "populate_result_table": lambda *args, **kwargs: None,
        },
        "ui.workers": {
            "LocalVectorDetailsWorker": _stub_class("LocalVectorDetailsWorker"),
            "ModelPackageImportWorker": _stub_class("ModelPackageImportWorker"),
        },
    }
    for module_name, attributes in module_specs.items():
        module = types.ModuleType(module_name)
        for key, value in attributes.items():
            setattr(module, key, value)
        stubs[module_name] = module

    return stubs


def _load_gui_module():
    stubs = _build_stub_modules()
    stack = ExitStack()
    stack.enter_context(patch.dict(sys.modules, stubs))
    sys.modules.pop("ui.windows.gui", None)
    try:
        gui_module = importlib.import_module("ui.windows.gui")
        return gui_module, stack
    except Exception:
        stack.close()
        raise


class GuiSettingsPathTests(unittest.TestCase):
    def test_build_runtime_issue_summary_prefers_missing_dll_names(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "setting_runtime_issue_directx": "DirectML / DirectX 12",
                "setting_runtime_issue_unknown": "DirectML runtime",
            }
        )
        dummy._get_runtime_issue_text = lambda issue: gui_module.MainWindow._get_runtime_issue_text(dummy, issue)

        summary = gui_module.MainWindow._build_runtime_issue_summary(
            dummy,
            {
                "issue": "directx",
                "diagnostics": {"missing_dlls": ["DirectML.dll", "d3d12.dll"]},
            },
        )

        self.assertEqual(summary, "DirectML / DirectX 12: DirectML.dll, d3d12.dll")

    def test_build_runtime_diagnostics_detail_includes_structured_evidence(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "setting_runtime_issue_probe_timeout": "GPU probe timed out",
                "setting_runtime_issue_unknown": "DirectML runtime",
                "setting_runtime_detail_missing_dlls": "Missing DLLs: {items}",
                "setting_runtime_detail_missing_msvc_dlls": "Missing VC++ DLLs: {items}",
                "setting_runtime_detail_available_providers": "Available providers: {items}",
                "setting_runtime_detail_windows_build": "Windows build: {value}",
                "setting_runtime_detail_probe_stage": "Failure stage: {value}",
                "setting_runtime_detail_probe_exception": "Exception: {value}",
                "setting_runtime_probe_stage_subprocess": "probe subprocess",
            }
        )
        dummy._get_runtime_issue_text = lambda issue: gui_module.MainWindow._get_runtime_issue_text(dummy, issue)
        dummy._build_runtime_issue_summary = lambda status: gui_module.MainWindow._build_runtime_issue_summary(dummy, status)

        detail = gui_module.MainWindow._build_runtime_diagnostics_detail(
            dummy,
            {
                "issue": "probe_timeout",
                "diagnostics": {
                    "available_providers": ["CPUExecutionProvider"],
                    "windows_build": 22631,
                    "probe_stage": "subprocess",
                    "probe_exception_type": "TimeoutExpired",
                    "probe_exception_message": "GPU runtime probe timed out.",
                },
            },
        )

        self.assertIn("GPU probe timed out", detail)
        self.assertIn("Available providers: CPUExecutionProvider", detail)
        self.assertIn("Windows build: 22631", detail)
        self.assertIn("Failure stage: probe subprocess", detail)
        self.assertIn("Exception: TimeoutExpired: GPU runtime probe timed out.", detail)

    def test_build_runtime_diagnostics_payload_includes_summary_and_raw_diagnostics(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "setting_runtime_issue_directx": "DirectML / DirectX 12",
                "setting_runtime_issue_unknown": "DirectML runtime",
                "setting_runtime_detail_missing_dlls": "Missing DLLs: {items}",
            }
        )
        dummy._get_runtime_issue_text = lambda issue: gui_module.MainWindow._get_runtime_issue_text(dummy, issue)
        dummy._build_runtime_issue_summary = lambda status: gui_module.MainWindow._build_runtime_issue_summary(dummy, status)
        dummy._build_runtime_diagnostics_detail = lambda status: gui_module.MainWindow._build_runtime_diagnostics_detail(dummy, status)

        payload = gui_module.MainWindow._build_runtime_diagnostics_payload(
            dummy,
            {
                "backend": "CPU",
                "initialized": True,
                "prefer_gpu": True,
                "issue": "directx",
                "warning": "fallback",
                "diagnostics": {"missing_dlls": ["DirectML.dll"]},
            },
        )

        self.assertEqual(payload["summary"], "DirectML / DirectX 12: DirectML.dll")
        self.assertIn("Missing DLLs: DirectML.dll", payload["detail"])
        self.assertEqual(payload["diagnostics"], {"missing_dlls": ["DirectML.dll"]})

    def test_copy_runtime_diagnostics_copies_json_and_updates_status(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)

        clipboard = types.SimpleNamespace(setText=MagicMock())
        status_label = MagicMock()
        dummy = types.SimpleNamespace(
            texts={
                "setting_copy_runtime_diagnostics_done": "GPU diagnostics copied to clipboard.",
            },
            settings_page=types.SimpleNamespace(lbl_status=status_label),
        )
        dummy._build_runtime_diagnostics_payload = lambda status: gui_module.MainWindow._build_runtime_diagnostics_payload(dummy, status)
        dummy._build_runtime_issue_summary = lambda status: "DirectML / DirectX 12: DirectML.dll"
        dummy._build_runtime_diagnostics_detail = lambda status: "Missing DLLs: DirectML.dll"

        with (
            patch("ui.windows.gui_runtime.get_engine_runtime_status", return_value={"backend": "CPU", "diagnostics": {"missing_dlls": ["DirectML.dll"]}}),
            patch("ui.windows.gui.QApplication.clipboard", return_value=clipboard),
        ):
            gui_module.MainWindow.copy_runtime_diagnostics(dummy)

        clipboard.setText.assert_called_once()
        copied_payload = json.loads(clipboard.setText.call_args.args[0])
        self.assertEqual(copied_payload["backend"], "CPU")
        self.assertEqual(copied_payload["diagnostics"], {"missing_dlls": ["DirectML.dll"]})
        status_label.setText.assert_called_once_with("GPU diagnostics copied to clipboard.")

    def test_show_runtime_diagnostics_uses_summary_and_detail_dialog(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "setting_show_runtime_diagnostics_title": "GPU diagnostics",
                "close": "Close",
                "setting_copy_runtime_diagnostics": "Copy",
            },
            is_dark_mode=False,
            language="zh",
        )
        dummy._build_runtime_diagnostics_payload = lambda status: {
            "summary": "DirectML / DirectX 12: DirectML.dll",
            "detail": "Missing DLLs: DirectML.dll",
            "warning": "GPU execution is unavailable.",
        }

        dialog_inst = MagicMock()
        dialog_inst.exec = MagicMock(return_value=0)
        dialog_inst.confirmed = MagicMock(return_value=False)

        with (
            patch("ui.windows.gui_runtime.get_engine_runtime_status", return_value={"backend": "CPU"}),
            patch("ui.windows.gui_runtime.AppMessageDialog") as mock_dialog,
        ):
            mock_dialog.return_value = dialog_inst
            gui_module.MainWindow.show_runtime_diagnostics(dummy)

        mock_dialog.assert_called_once()
        args, kwargs = mock_dialog.call_args
        self.assertEqual(args[0], "GPU diagnostics")
        self.assertIn("DirectML / DirectX 12: DirectML.dll", args[1])
        self.assertIn("Missing DLLs: DirectML.dll", args[1])
        self.assertIn("GPU execution is unavailable.", args[1])
        self.assertEqual(kwargs.get("kind"), "info")
        self.assertTrue(kwargs.get("confirm"))
        dialog_inst.exec.assert_called_once()

    def test_migrate_data_root_if_needed_requests_confirmation_and_calls_service(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "data_root_move_confirm": "Move to {path}",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(lbl_status=MagicMock()),
            show_confirm_dialog=MagicMock(return_value=True),
        )

        with patch("ui.windows.gui_settings.migrate_app_data_root", return_value={"migrated": True, "new_data_root": "D:/new"}) as mock_migrate:
            result = gui_module.MainWindow._migrate_data_root_if_needed(dummy, "D:/old", "D:/new")

        self.assertEqual(result["new_data_root"], "D:/new")
        dummy.show_confirm_dialog.assert_called_once_with("Confirm", "Move to D:/new")
        mock_migrate.assert_called_once_with("D:/new")

    def test_migrate_data_root_if_needed_stops_when_user_cancels(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "data_root_move_confirm": "Move to {path}",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(lbl_status=MagicMock()),
            show_confirm_dialog=MagicMock(return_value=False),
        )

        with patch("ui.windows.gui_settings.migrate_app_data_root") as mock_migrate:
            result = gui_module.MainWindow._migrate_data_root_if_needed(dummy, "D:/old", "D:/new")

        self.assertFalse(result)
        dummy.show_confirm_dialog.assert_called_once_with("Confirm", "Move to D:/new")
        dummy.settings_page.lbl_status.setText.assert_called_once_with("Settings hint")
        mock_migrate.assert_not_called()

    def test_build_data_root_migration_message_uses_old_and_new_paths(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "data_root_move_success": "Moved to {path}",
                "data_root_move_success_detail": "Old: {old_path} | New: {new_path} | Manual cleanup later",
            }
        )

        message = gui_module.MainWindow._build_data_root_migration_message(
            dummy,
            {
                "old_data_root": "D:/old",
                "new_data_root": "D:/new",
            },
            "D:/fallback",
        )

        self.assertEqual(message, "Old: D:/old | New: D:/new | Manual cleanup later")

    def test_build_data_storage_status_text_uses_only_data_root(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "setting_data_active": "Root={data_root}",
            }
        )

        message = gui_module.MainWindow._build_data_storage_status_text(
            dummy,
            {
                "data_root": "D:/store",
                "meta_file": "D:/store/data/meta.json",
            },
        )

        self.assertEqual(message, f"Root={os.path.normpath('D:/store')}")

    def test_start_index_update_refreshes_library_table_after_disabling_toolbar_actions(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "model_features_disabled": "Disabled",
                "index_start_failed": "Index failed",
            },
            library_page=types.SimpleNamespace(
                lbl_status=MagicMock(),
                btn_sync_db=MagicMock(),
                btn_stop_index=MagicMock(),
                btn_add_lib=MagicMock(),
                btn_cleanup_missing=MagicMock(),
                progress_bar=MagicMock(),
            ),
            check_runtime_resources=MagicMock(return_value=True),
            switch_page=MagicMock(),
            indexing_controller=types.SimpleNamespace(
                is_running=MagicMock(return_value=False),
                start=MagicMock(),
            ),
            _apply_index_issue_button_state=MagicMock(),
            refresh_library_table=MagicMock(),
            show_error_dialog=MagicMock(),
            _refresh_search_session_hint=MagicMock(),
            _last_index_issues=["old issue"],
            _last_index_issue_target="old",
        )

        gui_module.MainWindow._start_index_update(dummy, target_lib="D:/videos", rebuild_global_assets=False)

        dummy.library_page.btn_sync_db.setEnabled.assert_called_once_with(False)
        dummy.library_page.btn_add_lib.setEnabled.assert_called_once_with(False)
        dummy.refresh_library_table.assert_called_once_with()
        dummy.indexing_controller.start.assert_called_once_with(
            target_lib="D:/videos",
            force_cleanup_missing_files=False,
            cleanup_missing_entries=None,
            rebuild_global_assets=False,
        )

    def test_cleanup_old_data_root_calls_service_and_reports_success(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        saved_configs = []
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "cleanup_old_data_root_confirm": "Clean {path}",
                "cleanup_old_data_root_confirm_again": "Clean again {path} active {active_path}",
                "cleanup_old_data_root_done": "Cleaned {path}",
                "cleanup_old_data_root_missing": "Missing {path}",
                "cleanup_old_data_root_failed": "Failed",
                "cleanup_old_data_root_active_error": "Active {path}",
                "cleanup_old_data_root_unavailable": "Unavailable",
                "cleanup_old_data_root_pending": "Pending {path}",
                "success_title": "Done",
                "warning_title": "Warn",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(
                lbl_status=MagicMock(),
                btn_cleanup_old_data_root=types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock()),
            ),
            _normalize_requested_data_root=lambda value: value.replace("\\", "/"),
            _get_pending_cleanup_data_root=lambda config=None: "D:/old",
            _refresh_pending_cleanup_actions=MagicMock(),
            show_confirm_dialog=MagicMock(return_value=True),
            show_info_dialog=MagicMock(),
            show_error_dialog=MagicMock(),
        )

        with (
            patch("ui.windows.gui_settings.load_config", return_value={"data_root": "D:/new", "pending_cleanup_data_root": "D:/old"}),
            patch("ui.windows.gui_settings.save_config", side_effect=saved_configs.append),
            patch("ui.windows.gui_settings.get_configured_data_root", return_value="D:/new"),
            patch("ui.windows.gui_settings.cleanup_old_data_root_service", return_value={"cleaned": True, "old_data_dir": "D:/old/data"}) as mock_cleanup,
        ):
            gui_module.MainWindow.cleanup_old_data_root(dummy)

        self.assertEqual(
            dummy.show_confirm_dialog.call_args_list,
            [
                call("Confirm", "Clean D:/old", kind="warning"),
                call("Confirm", "Clean again D:/old active D:/new", kind="warning"),
            ],
        )
        mock_cleanup.assert_called_once_with("D:/old", active_data_root="D:/new")
        self.assertEqual(saved_configs[-1]["data_root"], "D:/new")
        self.assertNotIn("pending_cleanup_data_root", saved_configs[-1])
        dummy._refresh_pending_cleanup_actions.assert_called_once()
        dummy.settings_page.lbl_status.setText.assert_called_once_with("Cleaned D:/old/data")
        dummy.show_info_dialog.assert_called_once_with("Done", "Cleaned D:/old/data", kind="success")

    def test_cleanup_old_data_root_rejects_active_root_before_service_call(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        dummy = types.SimpleNamespace(
            texts={
                "confirm_title": "Confirm",
                "cleanup_old_data_root_confirm": "Clean {path}",
                "cleanup_old_data_root_confirm_again": "Clean again {path} active {active_path}",
                "cleanup_old_data_root_done": "Cleaned {path}",
                "cleanup_old_data_root_missing": "Missing {path}",
                "cleanup_old_data_root_failed": "Failed",
                "cleanup_old_data_root_active_error": "Active {path}",
                "cleanup_old_data_root_unavailable": "Unavailable",
                "cleanup_old_data_root_pending": "Pending {path}",
                "success_title": "Done",
                "warning_title": "Warn",
                "settings_hint": "Settings hint",
            },
            settings_page=types.SimpleNamespace(
                lbl_status=MagicMock(),
                btn_cleanup_old_data_root=types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock()),
            ),
            _normalize_requested_data_root=lambda value: value.replace("\\", "/"),
            _get_pending_cleanup_data_root=lambda config=None: "D:/same",
            _refresh_pending_cleanup_actions=MagicMock(),
            show_confirm_dialog=MagicMock(return_value=True),
            show_info_dialog=MagicMock(),
            show_error_dialog=MagicMock(),
        )

        with (
            patch("ui.windows.gui_settings.load_config", return_value={"data_root": "D:/same", "pending_cleanup_data_root": "D:/same"}),
            patch("ui.windows.gui_settings.get_configured_data_root", return_value="D:/same"),
            patch("ui.windows.gui_settings.cleanup_old_data_root_service") as mock_cleanup,
        ):
            gui_module.MainWindow.cleanup_old_data_root(dummy)

        dummy.show_confirm_dialog.assert_not_called()
        mock_cleanup.assert_not_called()
        dummy.settings_page.lbl_status.setText.assert_called_once_with("Active D:/same")
        dummy.show_info_dialog.assert_called_once_with("Warn", "Active D:/same", kind="warning")

    def test_refresh_pending_cleanup_action_hides_button_without_recorded_old_root(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        button = types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock())
        dummy = types.SimpleNamespace(
            texts={"cleanup_old_data_root_pending": "Pending {path}"},
            settings_page=types.SimpleNamespace(btn_cleanup_old_data_root=button),
            _get_pending_cleanup_data_root=lambda config=None: "",
        )

        result = gui_module.MainWindow._refresh_pending_cleanup_action(dummy, {"data_root": "D:/new"})

        self.assertEqual(result, "")
        button.setVisible.assert_called_once_with(False)
        button.setToolTip.assert_called_once_with("")

    def test_refresh_pending_cleanup_action_shows_button_for_recorded_old_root(self):
        gui_module, stack = _load_gui_module()
        self.addCleanup(stack.close)
        button = types.SimpleNamespace(setVisible=MagicMock(), setToolTip=MagicMock())
        dummy = types.SimpleNamespace(
            texts={"cleanup_old_data_root_pending": "Pending {path}"},
            settings_page=types.SimpleNamespace(btn_cleanup_old_data_root=button),
            _get_pending_cleanup_data_root=lambda config=None: "D:/old",
        )

        result = gui_module.MainWindow._refresh_pending_cleanup_action(dummy, {"data_root": "D:/new"})

        self.assertEqual(result, "D:/old")
        button.setVisible.assert_called_once_with(True)
        button.setToolTip.assert_called_once_with("Pending D:/old")


if __name__ == "__main__":
    unittest.main()
