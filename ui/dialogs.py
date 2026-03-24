
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QFrame, QTextEdit
from PySide6.QtCore import Qt

from src.config import load_config

CONFIG = load_config()

# ui/dialogs.py

class AboutDialog(QDialog):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("关于 VideoSeek")
        self.setFixedSize(360, 500)

        # 动态颜色配置
        bg = "#1e1e1e" if is_dark else "#ffffff"
        text = "#eeeeee" if is_dark else "#333333"
        btn_bg = "#0078D4"
        link_color = "#4dabff" if is_dark else "#005a9e"
        border = "#333333" if is_dark else "#dddddd"

        self.setStyleSheet(f"""
            QDialog {{ 
                background-color: {bg}; 
                color: {text}; 
                border: 1px solid {border};
            }}
            QLabel {{ 
                color: {text}; 
                background: transparent;
            }}
            QPushButton {{ 
                background-color: {btn_bg}; 
                color: white; 
                border-radius: 4px; 
                font-weight: bold; 
                padding: 5px;
            }}
            QPushButton:hover {{ background-color: #106ebe; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 40, 30, 30)

        icon = QLabel("🔍")
        icon.setStyleSheet("font-size: 50px; margin-bottom: 10px;")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("VideoSeek")
        title.setStyleSheet("font-size: 24px; font-weight: 900;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        version = QLabel(f"Version {CONFIG.get('version', '1.0.0')}")
        version.setStyleSheet("color: #888; font-size: 12px;")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; margin: 15px 0;")
        layout.addWidget(line)

        desc_text = (
            "<b>智能视频内容检索工具</b><br><br>"
            "• 支持自然语言描述搜索<br>"
            "• 支持以图搜影（视频帧）<br>"
            "• 本地化向量数据库，隐私安全<br>"
            "• 本地向量动态更新<br><br>"
            f"源码：<a href='https://github.com/liuvgg/VideoSeek' style='color: {link_color}; text-decoration: none;'>"
            "GitHub / VideoSeek</a>"
        )

        desc = QLabel(desc_text)
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.RichText)
        desc.setOpenExternalLinks(True)
        desc.setStyleSheet("font-size: 13px; line-height: 150%;")
        layout.addWidget(desc)
        layout.addStretch()

        btn_close = QPushButton("我知道了")
        btn_close.setFixedSize(120, 35)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        btn_lay.addStretch()
        layout.addLayout(btn_lay)
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("关于 VideoSeek")
        self.setFixedSize(360, 500)

        # 动态颜色配置
        bg = "#1e1e1e" if is_dark else "#ffffff"
        text = "#eeeeee" if is_dark else "#333333"
        btn_bg = "#0078D4"
        link_color = "#4dabff" if is_dark else "#005a9e"
        border = "#333333" if is_dark else "#dddddd"

        # 强化样式表，确保所有子控件都受控
        self.setStyleSheet(f"""
            QDialog {{ 
                background-color: {bg}; 
                color: {text}; 
                border: 1px solid {border};
            }}
            QLabel {{ 
                color: {text}; 
                background: transparent;
            }}
            QPushButton {{ 
                background-color: {btn_bg}; 
                color: white; 
                border-radius: 4px; 
                font-weight: bold; 
                padding: 5px;
            }}
            QPushButton:hover {{ background-color: #106ebe; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 40, 30, 30)

        icon = QLabel("🔍")
        icon.setStyleSheet("font-size: 50px; margin-bottom: 10px;")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("VideoSeek")
        title.setStyleSheet("font-size: 24px; font-weight: 900;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        version = QLabel(f"Version {CONFIG.get('version', '1.0.0')}")
        version.setStyleSheet("color: #888; font-size: 12px;")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {border}; margin: 15px 0;")
        layout.addWidget(line)

        # 描述文本，动态插入链接颜色
        desc_text = (
            "<b>智能视频内容检索工具</b><br><br>"
            "• 支持自然语言描述搜索<br>"
            "• 支持以图搜影（视频帧）<br>"
            "• 本地化向量数据库，隐私安全<br>"
            "• 本地向量动态更新<br><br>"
            f"源码：<a href='https://github.com/liuvgg/VideoSeek' style='color: {link_color}; text-decoration: none;'>"
            "GitHub / VideoSeek</a>"
        )

        desc = QLabel(desc_text)
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.RichText)
        desc.setOpenExternalLinks(True)
        desc.setStyleSheet("font-size: 13px; line-height: 150%;")
        layout.addWidget(desc)
        layout.addStretch()

        btn_close = QPushButton("我知道了")
        btn_close.setFixedSize(120, 35)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)

        btn_lay = QHBoxLayout()
        btn_lay.addStretch()
        btn_lay.addWidget(btn_close)
        btn_lay.addStretch()
        layout.addLayout(btn_lay)


class NoticeDialog(QDialog):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("系统公告")
        self.setFixedSize(400, 300)

        bg = "#1e1e1e" if is_dark else "#ffffff"
        text = "#eeeeee" if is_dark else "#333333"
        border = "#333333" if is_dark else "#dddddd"

        self.setStyleSheet(f"background-color: {bg}; color: {text};")

        layout = QVBoxLayout(self)

        title = QLabel("📢 最新公告")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # 这里可以写你的公告内容
        notice_text = (
            "1. 欢迎使用 VideoSeek v1.0.0！\n"
            "2. 本地索引更新后，检索速度将大幅提升。\n"
            "3. 如遇预览卡顿，请检查 ffmpeg 环境配置。\n"
            "4. 更多功能开发中，敬请期待..."
        )

        content = QTextEdit()
        content.setPlainText(notice_text)
        content.setReadOnly(True)
        content.setStyleSheet(f"border: 1px solid {border}; padding: 10px; border-radius: 5px;")
        layout.addWidget(content)

        btn_close = QPushButton("关闭")
        btn_close.setFixedWidth(80)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignCenter)