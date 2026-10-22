# main.py
import sys
import time
from src.app.logging_utils import get_logger, setup_logging

if __name__ == "__main__":
    setup_logging()
    logger = get_logger("main")
    t_app = time.perf_counter()
    logger.info("Application starting")

    if "--gpu-probe" in sys.argv:
        # Heavy ONNX/cv2 import only for the isolated GPU probe child process.
        from src.core.clip_embedding import gpu_probe_cli_main

        sys.exit(gpu_probe_cli_main())

    if "--bootstrap-runtime" in sys.argv:
        from src.storage.migration_runner import ensure_config_schema_v2_bootstrap

        ensure_config_schema_v2_bootstrap()
        from src.services.bundled_runtime_service import bootstrap_bundled_runtime

        result = bootstrap_bundled_runtime()
        if result.get("ok"):
            sys.exit(0)
        skipped = str(result.get("skipped") or "")
        if skipped in {"already_ready", "no_manifest"}:
            sys.exit(0 if skipped == "already_ready" else 2)
        logger.error("Bundled runtime bootstrap failed: %s", result.get("error") or result)
        sys.exit(1)

    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QApplication
    from src.app.single_instance import SingleInstanceServer, try_activate_existing_instance

    # The picture host is a native window for VLC. Without this, Qt also turns
    # the transport beside it into a native window that keeps the first frame:
    # seeks still land, but the slider and times never move on screen.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)
    app = QApplication(sys.argv)
    from ui.widgets.tooltip_utils import install_wrapped_tooltips

    install_wrapped_tooltips()

    if try_activate_existing_instance():
        logger.info("Another instance is running; activating existing window")
        sys.exit(0)

    single_instance_server = SingleInstanceServer(parent=app)
    app._videoseek_single_instance = single_instance_server

    # 设置全局字体
    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    app.setFont(font)

    from src.storage.migration_runner import ensure_config_schema_v2_bootstrap

    ensure_config_schema_v2_bootstrap()
    logger.info("Loading plugins")
    t_plugins = time.perf_counter()
    from src.app.plugins import load_plugins

    try:
        loaded = load_plugins()
        if loaded.loaded_modules:
            logger.info("Loaded plugins: %s", ", ".join(loaded.loaded_modules))
    except Exception:
        logger.exception("Failed to load plugins")
        raise
    logger.info("Loading plugins done in %.2fs", time.perf_counter() - t_plugins)

    logger.info("Loading main window")
    t_import = time.perf_counter()
    from ui.windows.gui import MainWindow

    logger.info("import MainWindow done in %.2fs", time.perf_counter() - t_import)

    t_ctor = time.perf_counter()
    window = MainWindow()
    logger.info("MainWindow() done in %.2fs", time.perf_counter() - t_ctor)

    single_instance_server.set_activate_handler(window._show_main_window_from_tray)
    if getattr(window, "startup_cancelled", False):
        logger.info("Startup cancelled before main window was shown")
        single_instance_server.close()
        sys.exit(0)

    class _FirstPaintProbe(QObject):
        def __init__(self, started_at: float):
            super().__init__()
            self._started_at = started_at
            self._done = False

        def eventFilter(self, obj, event):
            if not self._done and event.type() == QEvent.Type.Paint:
                self._done = True
                logger.info(
                    "first paint done (%.2fs since show, %.2fs since app start)",
                    time.perf_counter() - self._started_at,
                    time.perf_counter() - t_app,
                )
                obj.removeEventFilter(self)
            return False

    t_show = time.perf_counter()
    window.show()
    logger.info("window.show() returned in %.2fs", time.perf_counter() - t_show)
    paint_probe = _FirstPaintProbe(t_show)
    window.installEventFilter(paint_probe)
    # Keep a reference so the probe is not GC'd before first paint.
    window._startup_first_paint_probe = paint_probe

    t_migrate = time.perf_counter()
    window.begin_startup_migration()
    logger.info(
        "begin_startup_migration returned in %.2fs (%.2fs since show)",
        time.perf_counter() - t_migrate,
        time.perf_counter() - t_show,
    )
    logger.info(
        "entering app.exec() (%.2fs since app start, %.2fs since show)",
        time.perf_counter() - t_app,
        time.perf_counter() - t_show,
    )

    exit_code = app.exec()
    try:
        single_instance_server.close()
    except Exception:
        pass
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)
