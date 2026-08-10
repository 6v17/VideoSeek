"""Team mode dialogs: employee URL entry and server share/copy."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ui.dialogs.app_message import AppMessageDialog
from ui.dialogs.shell import VSDialogShell


def prompt_team_client_url(parent, texts: dict, *, initial_url: str = "") -> str | None:
    """Ask for the team server URL. Returns stripped URL, or None if cancelled."""
    dialog = VSDialogShell(
        parent,
        title=str(texts.get("setting_team_client_dialog_title", "连接服务机")),
        body=str(
            texts.get(
                "setting_team_client_dialog_hint",
                "填写服务机 API 地址即可。完整 URL（http://192.168.1.5:8765）或 IP:端口（192.168.1.5:8765）都可以；只填 IP 时默认端口 8765。保存设置后才会真正连接。",
            )
        ),
        minimum_width=460,
    )

    url_edit = QLineEdit()
    url_edit.setObjectName("SearchInput")
    url_edit.setPlaceholderText(
        str(
            texts.get(
                "setting_team_client_dialog_placeholder",
                "http://192.168.1.5:8765 或 192.168.1.5:8765",
            )
        )
    )
    url_edit.setText(str(initial_url or "").strip())
    dialog.content_layout.addWidget(url_edit)

    result: dict[str, str | None] = {"url": None}

    def _accept() -> None:
        text = str(url_edit.text() or "").strip()
        if not text:
            language = str(getattr(parent, "language", "") or "").strip() or "zh"
            AppMessageDialog(
                str(texts.get("error_title", "Error")),
                str(texts.get("setting_team_client_url_required", "请填写服务机地址。")),
                kind="warning",
                parent=dialog,
                language=language,
                is_dark=bool(getattr(parent, "is_dark_mode", True)),
            ).exec()
            return
        result["url"] = text
        dialog.accept()

    dialog.add_footer_button(
        str(texts.get("cancel", "取消")),
        object_name="GhostButton",
        on_click=dialog.reject,
    )
    dialog.add_footer_button(
        str(texts.get("ok", texts.get("confirm", "确定"))),
        object_name="PrimaryButton",
        on_click=_accept,
        default=True,
    )
    url_edit.returnPressed.connect(_accept)

    if dialog.exec() != VSDialogShell.DialogCode.Accepted:
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
    title_key = (
        "setting_team_server_share_pending_title"
        if pending
        else "setting_team_server_share_title"
    )
    if pending:
        body = str(
            texts.get(
                "setting_team_server_share_pending_hint",
                "保存设置后本机将作为服务机启动。可先复制下面地址发给用户机：",
            )
        )
    else:
        body = str(
            texts.get(
                "setting_team_server_share_hint",
                "服务机已启动。把下面地址发给用户机填写即可连接：",
            )
        )

    dialog = VSDialogShell(
        parent,
        title=str(
            texts.get(
                title_key,
                "分享给用户机" if not pending else "服务机地址（保存后生效）",
            )
        ),
        body=body,
        minimum_width=500,
    )

    def _add_row(label_text: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        row_host = QWidget()
        row = QHBoxLayout(row_host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QLabel(label_text)
        lab.setObjectName("DialogMetaLabel")
        lab.setMinimumWidth(72)
        edit = QLineEdit(text)
        edit.setObjectName("SearchInput")
        edit.setReadOnly(True)
        btn = QPushButton(str(texts.get("copy", texts.get("setting_copy", "复制"))))
        btn.setObjectName("GhostButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _copy(_checked=False, payload=text, button=btn) -> None:
            QApplication.clipboard().setText(payload)
            button.setText(str(texts.get("copied", "已复制")))

        btn.clicked.connect(_copy)
        row.addWidget(lab, 0)
        row.addWidget(edit, 1)
        row.addWidget(btn, 0)
        dialog.content_layout.addWidget(row_host)

    _add_row(str(texts.get("setting_team_share_api_label", "API 地址")), api_url)
    _add_row(str(texts.get("setting_team_share_media_label", "视频地址")), media_url)

    note = QLabel(
        str(
            texts.get(
                "setting_team_share_note",
                "用户机团队模式选「用户机」后粘贴 API 地址。需同一局域网，并放行防火墙端口。",
            )
        )
    )
    note.setWordWrap(True)
    note.setObjectName("StatusHint")
    dialog.content_layout.addWidget(note)

    dialog.add_footer_button(
        str(texts.get("ok", texts.get("confirm", "确定"))),
        object_name="PrimaryButton",
        on_click=dialog.accept,
        default=True,
    )
    dialog.exec()
