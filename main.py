# main.py
import sys
from src.app.logging_utils import get_logger, setup_logging

if __name__ == "__main__":
    setup_logging()
    logger = get_logger("main")
    logger.info("Application starting")

    if "--gpu-probe" in sys.argv:
        # Heavy ONNX/cv2 import only for the isolated GPU probe child process.
        from src.core.clip_embedding import gpu_probe_cli_main

        sys.exit(gpu_probe_cli_main())

    from PySide6.QtWidgets import QApplication
    from src.app.single_instance import SingleInstanceServer, try_activate_existing_instance

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
    logger.info("Loading main window")
    from ui.windows.gui import MainWindow

    window = MainWindow()
    single_instance_server.set_activate_handler(window._show_main_window_from_tray)
    if getattr(window, "startup_cancelled", False):
        logger.info("Startup cancelled before main window was shown")
        single_instance_server.close()
        sys.exit(0)
    window.show()
    window.begin_startup_migration()

    exit_code = app.exec()
    try:
        single_instance_server.close()
    except Exception:
        pass
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)
