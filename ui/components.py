# ui/components.py
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *



class SidePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setFixedWidth(360)                     # 加宽
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 24)   # 边距更舒适
        layout.setSpacing(18)                       # 间距稍大

        # 头部标题
        header = QHBoxLayout()
        self.title = QLabel("VideoSeek")
        self.title.setStyleSheet("font-size: 24px; font-weight: 800; color: #0078D4;")
        self.btn_theme = QPushButton("🌙")
        self.btn_theme.setFixedSize(42, 42)
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.btn_theme)
        layout.addLayout(header)

        # 库管理表格
        layout.addWidget(QLabel("视频库管理"))
        # 库管理表格
        self.lib_table = QTableWidget(0, 4)
        self.lib_table.setObjectName("LibTable")
        self.lib_table.setHorizontalHeaderLabels(["序号", "文件夹名", "状态", "操作"])
        self.lib_table.verticalHeader().setVisible(False)
        self.lib_table.setFixedHeight(180)

        # 设置各列宽度
        self.lib_table.setColumnWidth(0, 50)  # 序号列，加宽到50像素
        self.lib_table.setColumnWidth(1, 0)  # 路径列设为0，稍后设Stretch
        self.lib_table.setColumnWidth(2, 50)  # 状态列，固定70像素
        self.lib_table.setColumnWidth(3, 150)   # 操作列
        # 设置拉伸策略
        self.lib_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.lib_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # 路径列拉伸
        self.lib_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.lib_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.lib_table.verticalHeader().setDefaultSectionSize(60)  # 行高
        # =================================

        self.lib_table.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.lib_table)

        self.btn_add_lib = QPushButton("➕ 添加文件夹")
        self.btn_add_lib.setObjectName("SecondaryButton")
        layout.addWidget(self.btn_add_lib)

        layout.addWidget(QFrame(frameShape=QFrame.HLine, objectName="Separator"))

        # 搜索与清空区
        layout.addWidget(QLabel("智能检索条件"))
        self.img_label = QLabel("📷\n点击或拖入图片检索")
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedHeight(200)          # 拖放区更高
        layout.addWidget(self.img_label)

        self.text_search = QLineEdit()
        self.text_search.setPlaceholderText("描述画面内容...")
        self.text_search.setFixedHeight(44)          # 输入框稍高
        layout.addWidget(self.text_search)

        search_lay = QHBoxLayout()
        search_lay.setSpacing(8)  # 按钮之间间距
        self.btn_search = QPushButton("🚀 开始检索")
        self.btn_search.setObjectName("SearchButton")
        self.btn_search.setFixedHeight(48)
        self.btn_search.setFixedWidth(200)
        self.btn_clear = QPushButton("清理🧹")
        self.btn_clear.setFixedSize(100, 48)
        self.btn_clear.setMinimumWidth(48)  # 确保最小宽度
        search_lay.addWidget(self.btn_search, 1)  # 伸缩
        search_lay.addWidget(self.btn_clear, 0)  # 固定
        layout.addLayout(search_lay)

        self.btn_sync_db = QPushButton("🔄 更新全量索引")
        self.btn_sync_db.setFixedSize(308,48)
        self.btn_sync_db.setObjectName("PrimaryButton")
        layout.addWidget(self.btn_sync_db)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("系统就绪")
        self.lbl_status.setObjectName("StatusLabel")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.lbl_status)
        layout.addStretch()


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setHorizontalHeaderLabels(["序号", "预览", "视频名称", "时间点", "匹配度", "操作"])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(95)
        self.setAlternatingRowColors(True)
        self.setFocusPolicy(Qt.NoFocus)

        # 启用水平滚动条，确保所有列可见
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.horizontalHeader().setStretchLastSection(False)  # 不让最后一列自动拉伸

        # 设置固定宽度的列
        self.setColumnWidth(0, 45)    # 序号
        self.setColumnWidth(1, 180)   # 预览
        self.setColumnWidth(3, 80)    # 时间点
        self.setColumnWidth(4, 80)    # 匹配度
        self.setColumnWidth(5, 160)   # 操作

        # 视频名称列设为可拉伸，填充剩余宽度
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        # 其他列设为固定
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)