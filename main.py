import sys

from PySide6.QtWidgets import QApplication

from ui.vs import MainWindow, SearchController

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainWindow()
    search_controller = SearchController(main_window)
    main_window.show()
    app.exec()