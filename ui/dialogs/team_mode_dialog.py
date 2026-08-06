"""Team mode dialogs: employee URL entry and server share/copy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


def prompt_team_client_url(parent, texts: dict, *, initial_url: str = "") -> str | None:
    """Ask for the team server URL. Returns stripped URL, or None if cancelled."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(str(texts.get("setting_team_client_dialog_title", "连接服务机")))
    dialog.setModal(True)
    dialog.setMinimumWidth(420)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)
    hint = QLabel(
        str(
            texts.get(
                "setting_team_client_dialog_hint",
                "填写服务机 API 地址即可。完整 URL（http://192.168.1.5:8765）或 IP:端口（192.168.1.5:8765）都可以；只填 IP 时默认端口 8765。保存设置后才会真正连接。",
            )
        )
    )
    hint.setWordWrap(True)
    layout.addWidget(hint)

    url_edit = QLineEdit()
    url_edit.setPlaceholderText(
        str(
            texts.get(
                "setting_team_client_dialog_placeholder",
                "http://192.168.1.5:8765 或 192.168.1.5:8765",
            )
        )
    )
    url_edit.setText(str(initial_url or "").strip())
    layout.addWidget(url_edit)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
        str(texts.get("ok", texts.get("confirm", "确定")))
    )
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
        str(texts.get("cancel", "取消"))
    )
    layout.addWidget(buttons)

    result: dict[str, str | None] = {"url": None}

    def _accept() -> None:
        text = str(url_edit.text() or "").strip()
        if not text:
            QMessageBox.warning(
                dialog,
                str(texts.get("error_title", "Error")),
                str(texts.get("setting_team_client_url_required", "请填写服务机地址。")),
            )
            return
        result["url"] = text
        dialog.accept()

    buttons.accepted.connect(_accept)
    buttons.rejected.connect(dialog.reject)
    url_edit.returnPressed.connect(_accept)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return str(result["url"] or "").strip() or None


def show_team_server_share_dialog(
    parent,
    texts: dict,
    *,
    api_url: str,
    media_url: str = "",
    pending: bool = False,
) -> None:
    """Show API/media URLs with one-click copy for sharing to employee PCs."""
    dialog = QDialog(parent)
    title_key = (
        "setting_team_server_share_pending_title"
        if pending
        else "setting_team_server_share_title"
    )
    dialog.setWindowTitle(
        str(
            texts.get(
                title_key,
                "分享给员工机" if not pending else "服务机地址（保存后生效）",
            )
        )
    )
    dialog.setModal(True)
    dialog.setMinimumWidth(460)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)

    if pending:
        body = str(
            texts.get(
                "setting_team_server_share_pending_hint",
                "保存设置后本机将作为服务机启动。可先复制下面地址发给员工机：",
            )
        )
    else:
        body = str(
            texts.get(
                "setting_team_server_share_hint",
                "服务机已启动。把下面地址发给员工机填写即可连接：",
            )
        )
    hint = QLabel(body)
    hint.setWordWrap(True)
    layout.addWidget(hint)

    def _add_row(label_text: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        row = QHBoxLayout()
        lab = QLabel(label_text)
        lab.setMinimumWidth(72)
        edit = QLineEdit(text)
        edit.setReadOnly(True)
        btn = QPushButton(str(texts.get("copy", texts.get("setting_copy", "复制"))))
        btn.setObjectName("GhostButton")

        def _copy(_checked=False, payload=text, button=btn) -> None:
            QApplication.clipboard().setText(payload)
            button.setText(str(texts.get("copied", "已复制")))

        btn.clicked.connect(_copy)
        row.addWidget(lab, 0)
        row.addWidget(edit, 1)
        row.addWidget(btn, 0)
        layout.addLayout(row)

    _add_row(str(texts.get("setting_team_share_api_label", "API 地址")), api_url)
    _add_row(str(texts.get("setting_team_share_media_label", "视频地址")), media_url)

    note = QLabel(
        str(
            texts.get(
                "setting_team_share_note",
                "员工机团队模式选「员工机」后粘贴 API 地址。需同一局域网，并放行防火墙端口。",
            )
        )
    )
    note.setWordWrap(True)
    note.setObjectName("StatusHint")
    layout.addWidget(note)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
        str(texts.get("ok", texts.get("confirm", "确定")))
    )
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()
