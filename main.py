# main.py
import sys
from PySide6.QtWidgets import QApplication
from src.app.logging_utils import get_logger, setup_logging
from src.core.clip_embedding import gpu_probe_cli_main
from ui.gui import MainWindow

if __name__ == "__main__":
    setup_logging()
    logger = get_logger("main")

    if "--gpu-probe" in sys.argv:
        sys.exit(gpu_probe_cli_main())

    app = QApplication(sys.argv)

    # 设置全局字体
    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    app.setFont(font)

    logger.info("Application starting")
    window = MainWindow()
    if getattr(window, "startup_cancelled", False):
        logger.info("Startup cancelled before main window was shown")
        sys.exit(0)
    window.show()

    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)
