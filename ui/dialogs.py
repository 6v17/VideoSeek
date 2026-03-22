
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QFrame
from PySide6.QtCore import Qt


class AboutDialog(QDialog):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("关于 VideoSeek")
        self.setFixedSize(360, 480)

        bg = "#252525" if is_dark else "#ffffff"
        text = "#eee" if is_dark else "#333"
        self.setStyleSheet(f"background-color: {bg}; color: {text}; border-radius: 12px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(35, 40, 35, 35)

        icon = QLabel("🔍")
        icon.setStyleSheet("font-size: 60px; margin-bottom: 10px;")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("VideoSeek")
        title.setStyleSheet("font-size: 24px; font-weight: 900;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        version = QLabel("Version 1.0.0")
        version.setStyleSheet("color: #888; font-size: 12px;")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {'#444' if is_dark else '#eee'}; margin: 15px 0;")
        layout.addWidget(line)

        # 描述文本 (支持 HTML)
        desc_text = (
            "<b>智能视频内容检索工具</b><br><br>"
            "• 支持自然语言描述搜索<br>"
            "• 支持以图搜图（视频帧）<br>"
            "• 本地化向量数据库，隐私安全<br>"
            "• 毫秒级片段定位<br><br>"
            "源码地址：<a href='https://github.com/liuvgg/VideoSeek' style='color: #0078D4;'>GitHub Repository</a>"
        )

        desc = QLabel(desc_text)
        desc.setWordWrap(True)
        # 关键设置 1: 允许识别 HTML 超链接
        desc.setTextFormat(Qt.RichText)
        # 关键设置 2: 点击链接时自动调用系统浏览器打开
        desc.setOpenExternalLinks(True)

        desc.setStyleSheet("font-size: 13px; line-height: 150%;")
        layout.addWidget(desc)
        layout.addStretch()

        btn_close = QPushButton("我知道了")
        btn_close.setFixedSize(120, 35)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        btn_close.setStyleSheet("background-color: #0078D4; color: white; font-weight: bold;")

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        btn_lay.addStretch()
        layout.addLayout(btn_lay)