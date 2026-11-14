from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit

from src.app.i18n import get_texts
from ui.dialogs.shell import VSDialogShell
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width


class AppMessageDialog(VSDialogShell):
    def __init__(
        self,
        title,
        text,
        kind="info",
        parent=None,
        is_dark=True,
        language="zh",
        confirm=False,
        cancel_text="",
        confirm_text="",
        report="",
    ):
        texts = get_texts(language)
        self._report = str(report or "").strip()
        self._copy_button = None
        self._copy_label = str(texts.get("error_copy_report") or "复制错误信息")
        self._copied_label = str(texts.get("error_copied") or "已复制")
        super().__init__(
            parent,
            title=str(title or ""),
            body=str(text or ""),
            kind=str(kind or "info"),
            minimum_width=message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"],
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            ),
        )
        self._result = False
        if self._report:
            self._build_report_box(texts)
        else:
            # Message dialogs are header-only; keep content host empty/collapsed.
            self.set_content_visible(False)

        if confirm:
            cancel_label = str(cancel_text or "").strip() or texts["cancel"]
            confirm_label = str(confirm_text or "").strip() or texts["confirm_action"]
            self.add_footer_button(cancel_label, object_name="GhostButton", on_click=self.reject)
            self.add_footer_button(
                confirm_label,
                object_name="PrimaryButton",
                on_click=self._accept_confirm,
                default=True,
            )
        else:
            if self._report:
                self._copy_button = self.add_footer_button(
                    self._copy_label,
                    object_name="GhostButton",
                    on_click=self._copy_report,
                )
            self.add_footer_button(
                texts["close"],
                object_name="PrimaryButton",
                on_click=self.accept,
                default=True,
            )

    def _build_report_box(self, texts: dict) -> None:
        hint = QLabel(str(texts.get("error_report_hint") or ""))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.content_layout.addWidget(hint)
        editor = QPlainTextEdit()
        editor.setObjectName("ErrorReportText")
        editor.setReadOnly(True)
        editor.setPlainText(self._report)
        editor.setMinimumHeight(180)
        editor.setMaximumHeight(280)
        font = QFont("Consolas")
        font.setPointSize(9)
        editor.setFont(font)
        self.content_layout.addWidget(editor)
        self.setMinimumHeight(420)

    def _copy_report(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None and self._report:
            clipboard.setText(self._report)
        if self._copy_button is None:
            return
        self._copy_button.setText(self._copied_label)
        QTimer.singleShot(1600, self._restore_copy_label)

    def _restore_copy_label(self) -> None:
        if self._copy_button is not None:
            self._copy_button.setText(self._copy_label)

    def _accept_confirm(self):
        self._result = True
        self.accept()

    def confirmed(self):
        return self._result


def present_error_dialog(
    parent,
    message,
    exc=None,
    *,
    language: str = "zh",
    is_dark: bool = True,
    page: str = "",
    title: str = "",
) -> None:
    """The one error popup: short text plus a report the user can copy."""
    from src.app.error_report import build_error_report
    from src.app.logging_utils import get_logger, note_swallowed

    texts = get_texts(language)
    summary = str(message or "").strip()
    detail = ""
    if exc is not None and str(exc).strip():
        line = str(exc).strip().splitlines()[0]
        if len(line) > 240:
            line = line[:240] + "…"
        detail = str(texts.get("generic_detail") or "详情：{detail}").format(detail=line)
    text = f"{summary}\n\n{detail}".strip()
    try:
        get_logger("error_dialog").error("%s | %s", summary or "-", exc)
    except Exception as log_exc:
        note_swallowed(log_exc, "ui/dialogs/app_message.py:present_error_dialog")
    report = ""
    try:
        report = build_error_report(summary, exc, language=language, page=page)
    except Exception as report_exc:
        note_swallowed(report_exc, "ui/dialogs/app_message.py:present_error_dialog_report")
    AppMessageDialog(
        str(title or texts.get("error_title") or ""),
        text,
        kind="error",
        parent=parent,
        is_dark=is_dark,
        language=language,
        report=report,
    ).exec()
