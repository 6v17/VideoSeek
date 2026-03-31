# main.py
import sys
from PySide6.QtWidgets import QApplication
from ui.gui import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 设置全局字体
    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    app.setFont(font)

    window = MainWindow()
    if getattr(window, "startup_cancelled", False):
        sys.exit(0)
    window.show()

    sys.exit(app.exec())
