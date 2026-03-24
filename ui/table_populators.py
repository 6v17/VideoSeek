import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QWidget


def populate_library_table(table, libraries, is_indexing, on_refresh, on_remove):
    table.setRowCount(0)

    for index, (path, data) in enumerate(libraries.items(), start=1):
        row = table.rowCount()
        table.insertRow(row)

        order_item = QTableWidgetItem(str(index))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, order_item)

        name_item = QTableWidgetItem(os.path.basename(path) or path)
        name_item.setTextAlignment(Qt.AlignCenter)
        name_item.setToolTip(path)
        table.setItem(row, 1, name_item)

        status_item = QTableWidgetItem(_library_status_text(path, data))
        status_item.setForeground(QColor(_library_status_color(path, data)))
        status_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, status_item)

        table.setCellWidget(row, 3, _build_library_actions(path, is_indexing, on_refresh, on_remove))


def populate_result_table(table, results, on_preview, on_locate):
    table.setRowCount(0)
    table.setUpdatesEnabled(False)

    for row, (_, sec, score, video_path) in enumerate(results):
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, order_item)

        preview_placeholder = QLabel("...")
        preview_placeholder.setAlignment(Qt.AlignCenter)
        table.setCellWidget(row, 1, preview_placeholder)

        name_item = QTableWidgetItem(os.path.basename(video_path))
        name_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, name_item)

        time_item = QTableWidgetItem(f"{int(sec // 60):02d}:{int(sec % 60):02d}")
        time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, time_item)

        score_item = QTableWidgetItem(f"{int(score * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 4, score_item)

        table.setCellWidget(row, 5, _build_result_actions(video_path, sec, on_preview, on_locate))

    table.setUpdatesEnabled(True)


def _library_status_text(path, data):
    exists = os.path.exists(path)
    has_index = len(data.get("files", {})) > 0
    if exists and has_index:
        return "正常"
    if exists:
        return "未同步"
    return "变更"


def _library_status_color(path, data):
    exists = os.path.exists(path)
    has_index = len(data.get("files", {})) > 0
    if exists and has_index:
        return "#52c41a"
    if exists:
        return "#faad14"
    return "#ff4d4f"


def _build_library_actions(path, is_indexing, on_refresh, on_remove):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignCenter)

    refresh_button = QPushButton("刷新")
    refresh_button.setProperty("class", "TableBtn")
    refresh_button.setFixedSize(50, 28)
    refresh_button.setCursor(Qt.PointingHandCursor)
    refresh_button.clicked.connect(on_refresh)

    delete_button = QPushButton("删除")
    delete_button.setProperty("class", "TableDeleteBtn")
    delete_button.setFixedSize(50, 28)
    delete_button.setCursor(Qt.PointingHandCursor)
    delete_button.setEnabled(not is_indexing)
    delete_button.clicked.connect(lambda _, target=path: on_remove(target))

    layout.addWidget(refresh_button)
    layout.addWidget(delete_button)
    return container


def _build_result_actions(video_path, sec, on_preview, on_locate):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(12)
    layout.setAlignment(Qt.AlignCenter)

    preview_button = QPushButton("预览")
    preview_button.setProperty("class", "TableBtn")
    preview_button.setFixedSize(70, 32)
    preview_button.setCursor(Qt.PointingHandCursor)
    preview_button.setToolTip("播放当前片段")
    preview_button.clicked.connect(lambda _, path=video_path, start_sec=sec: on_preview(path, start_sec))

    locate_button = QPushButton("定位")
    locate_button.setProperty("class", "TableLocateBtn")
    locate_button.setFixedSize(70, 32)
    locate_button.setCursor(Qt.PointingHandCursor)
    locate_button.setToolTip("在文件夹中显示")
    locate_button.clicked.connect(lambda _, path=video_path: on_locate(path))

    layout.addWidget(preview_button)
    layout.addWidget(locate_button)
    return container
