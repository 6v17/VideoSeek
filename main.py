# main.py
import sys
from src.app.logging_utils import get_logger, setup_logging
from src.core.clip_embedding import gpu_probe_cli_main
from src.core.inference_providers import apply_cuda_experiment_defaults

if __name__ == "__main__":
    setup_logging()
    apply_cuda_experiment_defaults()
    logger = get_logger("main")

    if "--gpu-probe" in sys.argv:
        sys.exit(gpu_probe_cli_main())

    from PySide6.QtWidgets import QApplication
    from src.app.single_instance import SingleInstanceServer, try_activate_existing_instance
    from ui.windows.gui import MainWindow

    app = QApplication(sys.argv)

    if try_activate_existing_instance():
        logger.info("Another instance is running; activating existing window")
        sys.exit(0)

    single_instance_server = SingleInstanceServer(parent=app)

    # 设置全局字体
    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    app.setFont(font)

    logger.info("Application starting")
    from src.storage.migration_runner import ensure_config_schema_v2_bootstrap

    ensure_config_schema_v2_bootstrap()
    window = MainWindow()
    single_instance_server.set_activate_handler(window._show_main_window_from_tray)
    if getattr(window, "startup_cancelled", False):
        logger.info("Startup cancelled before main window was shown")
        sys.exit(0)
    window.show()
    window.begin_startup_migration()

    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)
