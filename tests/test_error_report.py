"""Copyable error reports name the action, the function, and recent logs."""

from __future__ import annotations

import logging
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QPushButton

from src.app.error_report import build_error_report
from src.app.logging_utils import recent_log_handler
from ui.dialogs.app_message import AppMessageDialog


class ErrorReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_exception_report_names_the_raising_function(self):
        def explode():
            raise RuntimeError("disk full")

        try:
            explode()
        except RuntimeError as exc:
            report = build_error_report("保存设置失败", exc, language="zh", page="settings")
        self.assertIn("VideoSeek 错误报告", report)
        self.assertIn("操作: 保存设置失败", report)
        self.assertIn("页面: settings", report)
        self.assertIn("异常: RuntimeError", report)
        self.assertIn("信息: disk full", report)
        self.assertIn("explode()", report)
        self.assertIn("堆栈:", report)
        self.assertIn("模式:", report)

    def test_string_error_names_the_caller(self):
        report = _report_from_here()
        self.assertIn("Operation: 导出失败", report)
        self.assertIn("Message: encoder missing", report)
        self.assertIn("_report_from_here()", report)
        self.assertNotIn("build_error_report()", report)

    def test_report_includes_recent_log_line(self):
        record = logging.LogRecord(
            "videoseek.test",
            logging.ERROR,
            __file__,
            1,
            "probe-token-xyz",
            (),
            None,
        )
        recent_log_handler().emit(record)
        report = build_error_report("搜索失败", "boom", language="zh")
        self.assertIn("probe-token-xyz", report)
        self.assertIn("最近日志:", report)

    def test_error_dialog_copies_the_report(self):
        dialog = AppMessageDialog(
            "出错了",
            "搜索失败",
            kind="error",
            language="zh",
            report="REPORT-BODY-TOKEN",
        )
        editor = dialog.findChild(QPlainTextEdit, "ErrorReportText")
        self.assertIsNotNone(editor)
        self.assertEqual(editor.toPlainText(), "REPORT-BODY-TOKEN")
        copy = next(button for button in dialog.findChildren(QPushButton) if button.text() == "复制错误信息")
        copy.click()
        self.assertEqual(QGuiApplication.clipboard().text(), "REPORT-BODY-TOKEN")
        self.assertEqual(copy.text(), "已复制")
        dialog.deleteLater()


def _report_from_here():
    return build_error_report("导出失败", "encoder missing", language="en")


if __name__ == "__main__":
    unittest.main()
