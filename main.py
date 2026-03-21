import sys

import qdarktheme
from PySide6.QtWidgets import QApplication

from ui.vs import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    qdarktheme.setup_theme()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())