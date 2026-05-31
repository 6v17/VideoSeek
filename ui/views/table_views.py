import os
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.services.library_service import resolve_library_card_status
from src.storage.asset_store import load_model_metadata
from src.app.config import load_config
from src.domain.remote_search_hit import coerce_remote_search_hit
from src.domain.search_hit import coerce_search_hit
from ui.widgets.table_specs import LocalSearchCol, NetworkLinkCol
from ui.widgets.thumb_cell import make_thumb_label
from ui.widgets.styles import repolish_widget

def _fallback_text(texts, key, zh_text, en_text):
    if key in texts:
        return texts[key]
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


def populate_library_table(library_list_host, libraries, is_indexing, on_sync, on_remove, on_open, texts):
    layout = library_list_host.layout()
    if layout is None:
        return

    header_labels = getattr(library_list_host, "_column_headers", None)
    hdr_texts = texts.get("library_headers") or ["#", "Path", "State", "Actions"]
    if header_labels:
        for i, lab in enumerate(header_labels):
            lab.setText(hdr_texts[i] if i < len(hdr_texts) else "")

    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()

    if not libraries:
        empty = QLabel(texts.get("library_list_empty", "No library folders yet."))
        empty.setObjectName("LibraryEmptyHint")
        empty.setAlignment(Qt.AlignCenter)
        empty.setWordWrap(True)
        layout.addWidget(empty)
        layout.addStretch(1)
        return

    config = load_config()
    meta = load_model_metadata(config=config)

    for index, (path, data) in enumerate(libraries.items(), start=1):
        layout.addWidget(
            _build_library_row_card(
                index,
                path,
                data,
                is_indexing,
                on_sync,
                on_remove,
                on_open,
                texts,
                meta=meta,
                config=config,
            )
        )
    layout.addStretch(1)


def populate_result_table(table, results, on_preview, on_locate, on_export, texts, on_deep_locate=None):
    table.setRowCount(0)
    if hasattr(table, "apply_header_labels"):
        table.apply_header_labels(texts)
    else:
        table.setHorizontalHeaderLabels(texts["result_headers"])
    table.setUpdatesEnabled(False)

    for row, raw in enumerate(results):
        hit = coerce_search_hit(raw)
        start_sec, end_sec, score, video_path = (
            hit.start_sec,
            hit.end_sec,
            hit.score,
            hit.video_path,
        )
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        order_item.setData(
            Qt.UserRole,
            {
                "video_path": video_path,
                "start_sec": float(start_sec),
                "end_sec": float(end_sec),
                "score": float(score),
                "match_kind": str(getattr(hit, "match_kind", "frame") or "frame"),
            },
        )
        table.setItem(row, LocalSearchCol.ORDER, order_item)

        table.setCellWidget(row, LocalSearchCol.PREVIEW, make_thumb_label(text=texts["thumb_loading"]))

        name_item = QTableWidgetItem(os.path.basename(video_path))
        name_item.setTextAlignment(Qt.AlignCenter)
        name_item.setToolTip(video_path)
        table.setItem(row, LocalSearchCol.VIDEO, name_item)

        time_item = QTableWidgetItem(_format_time_range(start_sec, end_sec, texts, match_kind=getattr(hit, "match_kind", "frame")))
        time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, LocalSearchCol.RANGE, time_item)

        mode_item = QTableWidgetItem(_result_mode_label(start_sec, end_sec, texts, match_kind=getattr(hit, "match_kind", "frame")))
        mode_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, LocalSearchCol.MODE, mode_item)

        score_item = QTableWidgetItem(f"{int(score * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, LocalSearchCol.SCORE, score_item)

        table.setCellWidget(
            row,
            LocalSearchCol.ACTIONS,
            _build_result_actions(
                video_path,
                start_sec,
                end_sec,
                on_preview,
                on_locate,
                on_export,
                texts,
                match_kind=getattr(hit, "match_kind", "frame"),
                on_deep_locate=on_deep_locate,
            ),
        )

    table.setUpdatesEnabled(True)
def populate_link_result_table(table, results, source_link, on_preview, on_locate, texts):
    table.setRowCount(0)
    table.setHorizontalHeaderLabels(texts["link_result_headers"])
    table.setUpdatesEnabled(False)

    for row, result in enumerate(results):
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, order_item)

        source_time_text = _format_time_value(result["source_time"])
        source_time_item = QTableWidgetItem(source_time_text)
        source_time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 1, source_time_item)

        name_item = QTableWidgetItem(os.path.basename(result["video_path"]))
        name_item.setToolTip(result["video_path"])
        name_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, name_item)

        match_time_item = QTableWidgetItem(_format_time_value(result["match_time"]))
        match_time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, match_time_item)

        score_item = QTableWidgetItem(f"{int(result['score'] * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 4, score_item)

        link_item = QTableWidgetItem(source_link)
        link_item.setToolTip(source_link)
        table.setItem(row, 5, link_item)

        table.setCellWidget(
            row,
            6,
            _build_link_result_actions(
                video_path=result["video_path"],
                match_sec=result["match_time"],
                source_link=source_link,
                on_preview=on_preview,
                on_locate=on_locate,
                texts=texts,
            ),
        )

    table.setUpdatesEnabled(True)


def populate_network_result_table(table, results, texts):
    table.setRowCount(0)
    if hasattr(table, "apply_header_labels"):
        table.apply_header_labels(texts)
    else:
        table.setHorizontalHeaderLabels(texts["network_result_headers"])
    table.setUpdatesEnabled(False)

    for row, raw in enumerate(results):
        hit = coerce_remote_search_hit(raw)
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, NetworkLinkCol.ORDER, order_item)

        title_item = QTableWidgetItem(hit.title)
        title_item.setToolTip(hit.title)
        table.setItem(row, NetworkLinkCol.TITLE, title_item)

        time_item = QTableWidgetItem(_format_time_value(hit.time_sec))
        time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, NetworkLinkCol.TIME, time_item)

        score_item = QTableWidgetItem(f"{int(hit.score * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, NetworkLinkCol.SCORE, score_item)

        source_link = hit.source_link
        source_item = QTableWidgetItem(source_link)
        source_item.setToolTip(source_link)
        table.setItem(row, NetworkLinkCol.SOURCE, source_item)

        table.setCellWidget(row, NetworkLinkCol.ACTIONS, _build_network_result_actions(source_link, texts))

    table.setUpdatesEnabled(True)


def _build_library_row_card(
    index, path, data, is_indexing, on_sync, on_remove, on_open, texts, meta=None, config=None
):
    card = QFrame()
    card.setObjectName("LibraryCard")
    root = QHBoxLayout(card)
    root.setContentsMargins(16, 14, 16, 14)
    root.setSpacing(14)

    idx = QLabel(str(index))
    idx.setObjectName("LibraryCardIndex")
    idx.setAlignment(Qt.AlignCenter)
    idx.setFixedSize(40, 40)
    idx.setMinimumHeight(40)

    path_wrap = QWidget()
    path_col = QVBoxLayout(path_wrap)
    path_col.setContentsMargins(0, 0, 0, 0)
    path_col.setSpacing(4)
    norm = os.path.normpath(path)
    base = os.path.basename(norm.rstrip(os.sep)) or norm
    parent_dir = os.path.dirname(norm)
    title = QLabel(base)
    title.setObjectName("LibraryCardTitle")
    title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
    title.setWordWrap(True)
    path_col.addWidget(title)
    if parent_dir:
        sub = QLabel(norm)
        sub.setObjectName("LibraryCardSubpath")
        sub.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        sub.setWordWrap(True)
        sub.setToolTip(norm)
        path_col.addWidget(sub)

    status_text, lib_state = resolve_library_card_status(path, data, texts, meta=meta, config=config)
    status = QLabel(status_text)
    status.setObjectName("LibraryCardStatus")
    status.setProperty("libState", lib_state)
    repolish_widget(status)
    status.setAlignment(Qt.AlignCenter)
    status.setWordWrap(True)
    status.setMinimumWidth(88)
    status.setMaximumWidth(118)

    actions = _build_library_actions(path, is_indexing, on_sync, on_remove, on_open, texts)
    actions.setMinimumWidth(196)

    root.addWidget(idx, 0, Qt.AlignVCenter)
    root.addWidget(path_wrap, 1)
    root.addWidget(status, 0, Qt.AlignVCenter)
    root.addWidget(actions, 0, Qt.AlignVCenter)
    return card


def _build_library_actions(path, is_indexing, on_sync, on_remove, on_open, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(4, 2, 4, 2)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignCenter)

    refresh_button = QPushButton(texts["sync"])
    refresh_button.setProperty("class", "TableBtn")
    refresh_button.setFixedSize(56, 30)
    refresh_button.setCursor(Qt.PointingHandCursor)
    refresh_button.setEnabled(not is_indexing)
    refresh_button.clicked.connect(lambda _, target=path: on_sync(target))

    delete_button = QPushButton(texts["delete"])
    delete_button.setProperty("class", "TableDeleteBtn")
    delete_button.setFixedSize(56, 30)
    delete_button.setCursor(Qt.PointingHandCursor)
    delete_button.setEnabled(not is_indexing)
    delete_button.clicked.connect(lambda _, target=path: on_remove(target))

    open_button = QPushButton(texts["open_folder"])
    open_button.setProperty("class", "TableLocateBtn")
    open_button.setFixedSize(56, 30)
    open_button.setCursor(Qt.PointingHandCursor)
    open_button.clicked.connect(lambda _, target=path: on_open(target))

    layout.addWidget(refresh_button)
    layout.addWidget(open_button)
    layout.addWidget(delete_button)
    return container


def _build_result_actions(
    video_path,
    start_sec,
    end_sec,
    on_preview,
    on_locate,
    on_export,
    texts,
    match_kind="frame",
    on_deep_locate=None,
):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(12)
    layout.setAlignment(Qt.AlignCenter)

    preview_button = QPushButton(texts["preview"])
    preview_button.setProperty("class", "TableBtn")
    preview_button.setFixedSize(74, 32)
    preview_button.setCursor(Qt.PointingHandCursor)
    preview_button.setToolTip(texts["preview_tip"])
    preview_button.clicked.connect(
        lambda _, path=video_path, clip_start=start_sec, clip_end=end_sec: on_preview(path, clip_start, clip_end)
    )

    locate_button = QPushButton(texts["locate"])
    locate_button.setProperty("class", "TableLocateBtn")
    locate_button.setFixedSize(74, 32)
    locate_button.setCursor(Qt.PointingHandCursor)
    locate_button.setToolTip(texts["locate_tip"])
    locate_button.clicked.connect(lambda _, path=video_path: on_locate(path))

    layout.addWidget(preview_button)

    if str(match_kind or "") == "video" and on_deep_locate is not None:
        deep_button = QPushButton(_fallback_text(texts, "deep_locate", "定位镜头", "Find shot"))
        deep_button.setProperty("class", "TableBtn")
        deep_button.setFixedSize(80, 32)
        deep_button.setCursor(Qt.PointingHandCursor)
        deep_button.setToolTip(_fallback_text(texts, "deep_locate_tip", "", ""))
        deep_button.clicked.connect(
            lambda _, path=video_path, anchor=start_sec: on_deep_locate(path, anchor)
        )
        layout.addWidget(deep_button)
        layout.addWidget(locate_button)
        return container

    export_button = QPushButton(_fallback_text(texts, "export_clip", "导出", "Export"))
    export_button.setProperty("class", "TableBtn")
    export_button.setFixedSize(74, 32)
    export_button.setCursor(Qt.PointingHandCursor)
    export_button.setToolTip(_fallback_text(texts, "export_clip_tip", "导出原画质片段", "Export original-quality clip"))
    export_button.clicked.connect(
        lambda _, path=video_path, clip_start=start_sec, clip_end=end_sec: on_export(path, clip_start, clip_end)
    )

    layout.addWidget(locate_button)
    layout.addWidget(export_button)
    return container

def _format_time_range(start_sec, end_sec, texts=None, match_kind="frame"):
    start_text = f"{int(start_sec // 60):02d}:{int(start_sec % 60):02d}"
    if str(match_kind or "") == "video":
        template = (texts or {}).get("time_preview_label", "Preview ~{time}")
        return template.format(time=start_text)
    end_text = f"{int(end_sec // 60):02d}:{int(end_sec % 60):02d}"
    if abs(float(end_sec) - float(start_sec)) < 1e-3:
        return start_text
    return f"{start_text}-{end_text}"


def _result_mode_label(start_sec, end_sec, texts, match_kind="frame"):
    if str(match_kind or "") == "video":
        return texts.get("result_mode_video", texts["result_mode_frame"])
    if abs(float(end_sec) - float(start_sec)) < 1e-3:
        return texts["result_mode_frame"]
    return texts["result_mode_chunk"]


def _build_link_result_actions(video_path, match_sec, source_link, on_preview, on_locate, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignCenter)

    preview_button = QPushButton(texts["preview"])
    preview_button.setProperty("class", "TableBtn")
    preview_button.setFixedSize(58, 30)
    preview_button.setCursor(Qt.PointingHandCursor)
    preview_button.clicked.connect(lambda _, path=video_path, sec=match_sec: on_preview(path, sec))

    locate_button = QPushButton(texts["locate"])
    locate_button.setProperty("class", "TableLocateBtn")
    locate_button.setFixedSize(58, 30)
    locate_button.setCursor(Qt.PointingHandCursor)
    locate_button.clicked.connect(lambda _, path=video_path: on_locate(path))

    source_button = QPushButton(texts["open_link"])
    source_button.setProperty("class", "TableBtn")
    source_button.setFixedSize(58, 30)
    source_button.setCursor(Qt.PointingHandCursor)
    source_button.clicked.connect(lambda _, link=source_link: webbrowser.open(link))

    layout.addWidget(preview_button)
    layout.addWidget(locate_button)
    layout.addWidget(source_button)
    return container


def _build_network_result_actions(source_link, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignCenter)

    open_button = QPushButton(texts["open_link"])
    open_button.setProperty("class", "TableBtn")
    open_button.setFixedSize(90, 30)
    open_button.setCursor(Qt.PointingHandCursor)
    open_button.clicked.connect(lambda _, link=source_link: webbrowser.open(link))
    layout.addWidget(open_button)
    return container


def _format_time_value(seconds):
    seconds = max(0.0, float(seconds))
    total = int(seconds)
    mins = total // 60
    secs = total % 60
    return f"{mins:02d}:{secs:02d}"
