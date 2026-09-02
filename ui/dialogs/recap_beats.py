"""Review and edit a saved recap story plan before matching shots."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from src.services.recap_service import format_recap_clock, parse_recap_clock
from ui.dialogs.shell import VSDialogShell
from ui.widgets.scaffold import VSCard


def _cell(text: str, *, editable: bool = True, align=None) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text or ""))
    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    if editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    item.setFlags(flags)
    if align is not None:
        item.setTextAlignment(align)
    return item


class RecapBeatsDialog(VSDialogShell):
    def __init__(
        self,
        parent=None,
        *,
        texts: Mapping[str, Any],
        title: str = "",
        beats: Sequence[Mapping[str, Any]] | None = None,
        people: Sequence[Mapping[str, Any]] | None = None,
        target_sec: float = 0.0,
    ):
        self.texts = dict(texts or {})
        self._result: dict[str, Any] | None = None
        body = str(
            self.texts.get(
                "understanding_recap_edit_beats_hint",
                "Drop filler beats, fix names, then save and match from stage 2.",
            )
        )
        if target_sec > 0:
            body = body + " " + str(
                self.texts.get(
                    "understanding_recap_edit_target",
                    "Target recap length about {sec:.0f}s.",
                )
            ).format(sec=float(target_sec))
        super().__init__(
            parent,
            title=str(self.texts.get("understanding_recap_edit_beats_title", "Edit story plan")),
            body=body,
            minimum_width=880,
            outer_margins=(14, 14, 14, 14),
            card_margins=(18, 16, 18, 14),
            card_spacing=12,
        )
        self.setMinimumSize(880, 560)
        self.resize(960, 640)

        title_host = QWidget()
        title_row = QHBoxLayout(title_host)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        title_label = QLabel(str(self.texts.get("understanding_recap_edit_title", "Title")))
        title_label.setObjectName("InlineFieldLabel")
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("SearchInput")
        self.title_edit.setText(str(title or "").strip())
        title_row.addWidget(title_label, 0)
        title_row.addWidget(self.title_edit, 1)
        self.content_layout.addWidget(title_host)

        people_card = VSCard(variant="sub", margins=(12, 10, 12, 10), spacing=8)
        people_head = QWidget()
        people_row = QHBoxLayout(people_head)
        people_row.setContentsMargins(0, 0, 0, 0)
        people_row.setSpacing(8)
        people_label = QLabel(str(self.texts.get("understanding_recap_edit_people", "People")))
        people_label.setObjectName("InlineFieldLabel")
        people_row.addWidget(people_label, 0)
        people_row.addStretch(1)
        self.btn_add_person = QPushButton(str(self.texts.get("understanding_recap_edit_add_person", "Add person")))
        self.btn_add_person.setObjectName("GhostButton")
        self.btn_delete_person = QPushButton(str(self.texts.get("understanding_recap_edit_delete", "Delete")))
        self.btn_delete_person.setObjectName("DangerGhostButton")
        people_row.addWidget(self.btn_add_person, 0)
        people_row.addWidget(self.btn_delete_person, 0)
        people_card.content_layout.addWidget(people_head)
        self.people_table = QTableWidget(0, 2)
        self.people_table.setObjectName("DataTable")
        self.people_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.people_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.people_table.verticalHeader().setVisible(False)
        self.people_table.setShowGrid(False)
        self.people_table.setAlternatingRowColors(False)
        self.people_table.setMaximumHeight(140)
        self.people_table.setHorizontalHeaderLabels(
            list(
                self.texts.get("understanding_recap_people_headers", ["Name", "Look"])
                or ["Name", "Look"]
            )
        )
        people_header = self.people_table.horizontalHeader()
        people_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        people_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        people_card.content_layout.addWidget(self.people_table)
        self.content_layout.addWidget(people_card)

        beats_card = VSCard(variant="sub", margins=(12, 10, 12, 10), spacing=8)
        beats_head = QWidget()
        beats_row = QHBoxLayout(beats_head)
        beats_row.setContentsMargins(0, 0, 0, 0)
        beats_row.setSpacing(8)
        beats_label = QLabel(str(self.texts.get("understanding_recap_edit_beats_list", "Beats")))
        beats_label.setObjectName("InlineFieldLabel")
        beats_row.addWidget(beats_label, 0)
        beats_row.addStretch(1)
        self.btn_add_beat = QPushButton(str(self.texts.get("understanding_recap_edit_add_beat", "Add beat")))
        self.btn_add_beat.setObjectName("GhostButton")
        self.btn_move_up = QPushButton(str(self.texts.get("understanding_recap_edit_move_up", "Move up")))
        self.btn_move_up.setObjectName("GhostButton")
        self.btn_move_down = QPushButton(str(self.texts.get("understanding_recap_edit_move_down", "Move down")))
        self.btn_move_down.setObjectName("GhostButton")
        self.btn_delete_beat = QPushButton(str(self.texts.get("understanding_recap_edit_delete", "Delete")))
        self.btn_delete_beat.setObjectName("DangerGhostButton")
        for button in (self.btn_add_beat, self.btn_move_up, self.btn_move_down, self.btn_delete_beat):
            beats_row.addWidget(button, 0)
        beats_card.content_layout.addWidget(beats_head)
        self.beats_table = QTableWidget(0, 6)
        self.beats_table.setObjectName("DataTable")
        self.beats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.beats_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.beats_table.verticalHeader().setVisible(False)
        self.beats_table.setShowGrid(False)
        self.beats_table.setAlternatingRowColors(False)
        self.beats_table.verticalHeader().setDefaultSectionSize(36)
        self.beats_table.setHorizontalHeaderLabels(
            list(
                self.texts.get(
                    "understanding_recap_beats_headers",
                    ["#", "Start", "End", "Weight", "Event", "Needed shot"],
                )
                or ["#", "Start", "End", "Weight", "Event", "Needed shot"]
            )
        )
        beats_header = self.beats_table.horizontalHeader()
        beats_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        beats_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        beats_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        beats_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        beats_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        beats_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.beats_table.setColumnWidth(0, 44)
        self.beats_table.setColumnWidth(1, 72)
        self.beats_table.setColumnWidth(2, 72)
        self.beats_table.setColumnWidth(3, 64)
        beats_card.content_layout.addWidget(self.beats_table, 1)
        self.content_layout.addWidget(beats_card, 1)

        self.error_label = QLabel()
        self.error_label.setObjectName("StatusHint")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.content_layout.addWidget(self.error_label)

        self.btn_add_person.clicked.connect(self._add_person)
        self.btn_delete_person.clicked.connect(self._delete_person)
        self.btn_add_beat.clicked.connect(self._add_beat)
        self.btn_delete_beat.clicked.connect(self._delete_beat)
        self.btn_move_up.clicked.connect(lambda: self._move_beat(-1))
        self.btn_move_down.clicked.connect(lambda: self._move_beat(1))

        self.add_footer_button(
            str(self.texts.get("cancel", "Cancel")),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(self.texts.get("understanding_recap_edit_save", "Save plan")),
            object_name="PrimaryButton",
            on_click=self._accept,
            default=True,
        )

        for person in people or []:
            self._append_person(person)
        for beat in beats or []:
            self._append_beat(beat)
        if self.beats_table.rowCount() <= 0:
            self._add_beat()
        if self.people_table.rowCount() <= 0:
            self._add_person()

    def result_payload(self) -> dict[str, Any] | None:
        return self._result

    def _append_person(self, person: Mapping[str, Any] | None = None) -> None:
        row = self.people_table.rowCount()
        self.people_table.insertRow(row)
        label = _cell(str((person or {}).get("label") or ""))
        label.setData(Qt.ItemDataRole.UserRole, str((person or {}).get("id") or ""))
        self.people_table.setItem(row, 0, label)
        self.people_table.setItem(row, 1, _cell(str((person or {}).get("look") or "")))

    def _append_beat(self, beat: Mapping[str, Any] | None = None) -> None:
        item = dict(beat or {})
        span = item.get("t") if isinstance(item.get("t"), (list, tuple)) else (0.0, 0.0)
        start = float(span[0] if span else 0.0)
        end = float(span[1] if span and len(span) > 1 else start)
        row = self.beats_table.rowCount()
        self.beats_table.insertRow(row)
        order = _cell(str(row + 1), editable=False, align=Qt.AlignmentFlag.AlignCenter)
        try:
            beat_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        order.setData(Qt.ItemDataRole.UserRole, beat_id)
        self.beats_table.setItem(row, 0, order)
        self.beats_table.setItem(
            row, 1, _cell(format_recap_clock(start), align=Qt.AlignmentFlag.AlignCenter)
        )
        self.beats_table.setItem(
            row, 2, _cell(format_recap_clock(end), align=Qt.AlignmentFlag.AlignCenter)
        )
        importance = item.get("importance")
        try:
            weight = f"{float(importance):.2f}" if importance is not None else "0.50"
        except (TypeError, ValueError):
            weight = "0.50"
        self.beats_table.setItem(row, 3, _cell(weight, align=Qt.AlignmentFlag.AlignCenter))
        self.beats_table.setItem(row, 4, _cell(str(item.get("event") or "")))
        self.beats_table.setItem(row, 5, _cell(str(item.get("needed_visual") or "")))
        self._renumber_beats()

    def _add_person(self) -> None:
        self._append_person({})
        self.people_table.selectRow(self.people_table.rowCount() - 1)

    def _delete_person(self) -> None:
        row = self.people_table.currentRow()
        if row >= 0:
            self.people_table.removeRow(row)

    def _add_beat(self) -> None:
        start = 0.0
        selected = self.beats_table.currentRow()
        if selected >= 0:
            end_item = self.beats_table.item(selected, 2)
            try:
                start = parse_recap_clock(end_item.text() if end_item else "")
            except (TypeError, ValueError):
                start = 0.0
        self._append_beat({"t": [start, start + 20.0], "importance": 0.5})
        self.beats_table.selectRow(self.beats_table.rowCount() - 1)

    def _delete_beat(self) -> None:
        row = self.beats_table.currentRow()
        if row >= 0:
            self.beats_table.removeRow(row)
            self._renumber_beats()

    def _move_beat(self, delta: int) -> None:
        row = self.beats_table.currentRow()
        dest = row + int(delta)
        if row < 0 or dest < 0 or dest >= self.beats_table.rowCount():
            return
        self._swap_rows(self.beats_table, row, dest)
        self._renumber_beats()
        self.beats_table.selectRow(dest)

    def _swap_rows(self, table: QTableWidget, left: int, right: int) -> None:
        for column in range(table.columnCount()):
            a = table.takeItem(left, column)
            b = table.takeItem(right, column)
            table.setItem(left, column, b)
            table.setItem(right, column, a)

    def _renumber_beats(self) -> None:
        for row in range(self.beats_table.rowCount()):
            cell = self.beats_table.item(row, 0)
            if cell is None:
                cell = _cell(str(row + 1), editable=False, align=Qt.AlignmentFlag.AlignCenter)
                self.beats_table.setItem(row, 0, cell)
            cell.setText(str(row + 1))

    def _text(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return str(item.text() if item is not None else "").strip()

    def _accept(self) -> None:
        people: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        for row in range(self.people_table.rowCount()):
            label = self._text(self.people_table, row, 0)
            if not label:
                continue
            cell = self.people_table.item(row, 0)
            who_id = str(cell.data(Qt.ItemDataRole.UserRole) if cell is not None else "") or f"p{row + 1}"
            if who_id in used_ids:
                who_id = f"p{row + 1}"
            used_ids.add(who_id)
            people.append(
                {
                    "id": who_id,
                    "label": label[:40],
                    "look": self._text(self.people_table, row, 1)[:60],
                }
            )
        beats: list[dict[str, Any]] = []
        used_beat_ids: set[int] = set()
        next_id = 1
        for row in range(self.beats_table.rowCount()):
            event = self._text(self.beats_table, row, 4)
            if not event:
                continue
            order = self.beats_table.item(row, 0)
            try:
                beat_id = int(order.data(Qt.ItemDataRole.UserRole) if order is not None else 0)
            except (TypeError, ValueError):
                beat_id = 0
            if beat_id <= 0 or beat_id in used_beat_ids:
                while next_id in used_beat_ids:
                    next_id += 1
                beat_id = next_id
            used_beat_ids.add(beat_id)
            next_id = max(next_id, beat_id + 1)
            try:
                start = parse_recap_clock(self._text(self.beats_table, row, 1))
                end = parse_recap_clock(self._text(self.beats_table, row, 2))
            except (TypeError, ValueError):
                self.error_label.setText(
                    str(self.texts.get("understanding_recap_edit_time_invalid", "Enter start/end as mm:ss or seconds."))
                )
                self.error_label.show()
                return
            if end <= start:
                end = start + 4.0
            try:
                importance = float(self._text(self.beats_table, row, 3) or 0.5)
            except (TypeError, ValueError):
                importance = 0.5
            beats.append(
                {
                    "id": beat_id,
                    "event": event[:120],
                    "importance": min(1.0, max(0.05, importance)),
                    "needed_visual": self._text(self.beats_table, row, 5)[:80],
                    "t": [round(start, 2), round(end, 2)],
                }
            )
        if not beats:
            self.error_label.setText(
                str(self.texts.get("understanding_recap_edit_empty", "Keep at least one beat with an event."))
            )
            self.error_label.show()
            return
        self._result = {
            "title": str(self.title_edit.text() or "").strip() or "解说剪辑",
            "people": people,
            "beats": beats,
        }
        self.accept()
