import os
import sys
import time

import cv2
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import *
from PySide6.QtMultimediaWidgets import *

from src.config import load_config
# 确保这些 import 路径与你的项目结构一致
from src.core import run_search
from src.utils import create_preview_clip, open_in_explorer, get_single_thumbnail


class SearchWorker(QThread):
    result_ready = Signal(list)
    finished = Signal()

    def __init__(self, folder, query, is_text):
        super().__init__()
        self.folder, self.query, self.is_text = folder, query, is_text

    def run(self):
        # 执行后台搜索
        results = run_search(self.folder, self.query, self.is_text)
        self.result_ready.emit(results)
        self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.lbl_folder = None
        self.btn_search = None
        self.btn_clear = None
        self.btn_upload = None
        self.text_search = None
        self.img_label = None
        self.btn_select_folder = None
        self.worker = None
        self.setWindowTitle("VideoSeek Pro - 智能视频检索")
        self.resize(1240, 850)

        # 1. 初始化目录和路径
        self.cache_dir = os.path.abspath("data/cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_path = os.path.join(self.cache_dir, "preview.mp4")
        self.current_img_path = None

        # 2. 构建界面
        self.setup_ui()

        # 3. 启用拖拽
        self.setAcceptDrops(True)

        # 4. 初始化播放器
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        # 自动加载上次保存的路径
        saved_config = load_config()
        last_path = saved_config.get("video_folder", "")
        if last_path and os.path.exists(last_path):
            self.lbl_folder.setText(last_path)
            self.video_library_path = last_path

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # --- 左侧面板 ---
        left_panel = QVBoxLayout()

        # 图片预览区
        self.img_label = QLabel("将图片拖入此处\n或点击下方上传")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedSize(300, 300)
        self.img_label.setStyleSheet("""
            QLabel {
                border: 2px dashed #555; 
                border-radius: 10px;
                background: #1e1e1e; 
                color: #888;
                font-size: 14px;
            }
        """)

        # 文字搜索框
        self.text_search = QLineEdit()
        self.text_search.setPlaceholderText("或者输入文字描述搜索...")
        self.text_search.setStyleSheet("height: 35px; padding-left: 10px; font-size: 13px;")

        # 按钮组
        self.btn_upload = QPushButton("选择图片")
        self.btn_clear = QPushButton("清空所有内容")  # 补回清空按钮
        self.btn_search = QPushButton("开始检索")

        # 设置按钮样式
        self.btn_upload.setFixedHeight(35)
        self.btn_clear.setFixedHeight(35)
        self.btn_search.setFixedHeight(45)
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: #2E7D32; 
                color: white; 
                font-weight: bold; 
                font-size: 15px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:disabled { background-color: #555; }
        """)

        # 信号连接
        self.btn_upload.clicked.connect(self.upload_file)
        self.btn_clear.clicked.connect(self.clear_all)
        self.btn_search.clicked.connect(self.start_search)

        # --- 视频库选择区 ---
        folder_layout = QHBoxLayout()
        self.lbl_folder = QLineEdit()
        self.lbl_folder.setPlaceholderText("请选择视频库文件夹...")
        self.lbl_folder.setReadOnly(True)  # 只读，防止乱打字
        self.lbl_folder.setStyleSheet("height: 25px; background: #333; color: #ccc;")

        self.btn_select_folder = QPushButton("选择视频库")
        self.btn_select_folder.setFixedWidth(80)
        self.btn_select_folder.clicked.connect(self.select_video_folder)

        folder_layout.addWidget(self.lbl_folder)
        folder_layout.addWidget(self.btn_select_folder)

        # 将它插入到左侧布局的最顶部
        left_panel.insertLayout(0, folder_layout)

        left_panel.addWidget(self.img_label)
        left_panel.addWidget(self.text_search)
        left_panel.addWidget(self.btn_upload)
        left_panel.addWidget(self.btn_clear)  # 加入布局
        left_panel.addWidget(self.btn_search)
        left_panel.addStretch()

        # --- 右侧面板 ---
        right_panel = QVBoxLayout()

        # 视频播放器区域
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(400)
        self.video_widget.setStyleSheet("background-color: black;")

        # 结果表格
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["预览图", "视频名称", "匹配时间", "相似度评分", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 不可编辑
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)  # 整行选择
        # 让表头文字居中
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        # 设置表头字体加粗（好康+1）
        font = self.table.horizontalHeader().font()
        font.setBold(True)
        self.table.horizontalHeader().setFont(font)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b2b;
                color: #dcdcdc;
                gridline-color: #444;
                border: none;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #3c3f41;
                padding: 4px;
                border: 1px solid #222;
                color: #aaa;
            }
            QTableWidget::item:selected {
                background-color: #2E7D32; /* 选中颜色和检索按钮呼应 */
            }
        """)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.video_widget)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 1)  # 播放器和表格比例平衡
        splitter.setStretchFactor(1, 1)

        right_panel.addWidget(splitter)

        layout.addLayout(left_panel, 1)
        layout.addLayout(right_panel, 3)

    def select_video_folder(self):
        """弹出文件夹选择框"""
        selected_dir = QFileDialog.getExistingDirectory(self, "选择视频库文件夹", "")
        if selected_dir:
            self.lbl_folder.setText(selected_dir)
            self.video_library_path = selected_dir
            # 可选：立即保存到配置文件
            self.save_folder_to_config(selected_dir)

    def save_folder_to_config(self, path):
        """将路径存入 config.json (假设你导入了 src.config 里的函数)"""
        from src.config import load_config, save_config
        config = load_config()
        config["video_folder"] = path
        save_config(config)
    # --- 功能函数 ---

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择查询图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self.load_image(file_path)

    def load_image(self, file_path):
        self.current_img_path = file_path
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            self.img_label.setPixmap(pixmap.scaled(
                self.img_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
            # 清除文字框，因为我们现在有了图
            self.text_search.clear()
        else:
            self.img_label.setText("图片加载失败")

    def clear_all(self):
        """清空所有状态的逻辑"""
        # 1. 停止播放
        self.media_player.stop()
        self.media_player.setSource(QUrl(""))

        # 2. 清空 UI
        self.table.setRowCount(0)
        self.text_search.clear()
        self.img_label.clear()
        self.img_label.setText("将图片拖入此处\n或点击下方上传")
        self.current_img_path = None

        # 3. 尝试物理删除缓存文件
        try:
            if os.path.exists(self.cache_path):
                os.remove(self.cache_path)
        except:
            pass
        print("已清空所有检索结果和状态")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                self.load_image(file_path)

    def start_search(self):
        folder = getattr(self, 'video_library_path', self.lbl_folder.text())  # 你的视频存放路径
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "提醒", "请先选择一个有效的视频库文件夹！")
            return
        text = self.text_search.text().strip()
        query = text if text else self.current_img_path

        if not query:
            QMessageBox.information(self, "提示", "请先输入搜索文字或上传一张图片")
            return

        # 锁定 UI
        self.btn_search.setEnabled(False)
        self.btn_search.setText("检索中...")
        self.table.setRowCount(0)

        # 启动工作线程
        self.worker = SearchWorker(folder, query, bool(text))
        self.worker.result_ready.connect(self.display_results)
        self.worker.finished.connect(self.on_search_finished)
        self.worker.start()

    def on_search_finished(self):
        self.btn_search.setEnabled(True)
        self.btn_search.setText("开始检索")

    def display_results(self, results):
        self.table.setRowCount(0)
        self.table.verticalHeader().setDefaultSectionSize(90)  # 行高稍微大点，舒服

        for res in results:
            timestamp, sec, score, video_path = res
            row = self.table.rowCount()
            self.table.insertRow(row)

            # --- 1. 预览图列 (第 0 列) ---
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignCenter)  # 图片在 Label 里居中
            frame_bgr = get_single_thumbnail(video_path, sec)
            if frame_bgr is not None:
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                h, w, ch = frame_rgb.shape
                qt_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888)
                thumb_label.setPixmap(
                    QPixmap.fromImage(qt_img).scaled(120, 75, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.table.setCellWidget(row, 0, thumb_label)

            # --- 2. 文字信息列 (第 1, 2, 3 列) ---
            # 定义一个快速创建居中 Item 的方法
            def create_center_item(text):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(Qt.AlignCenter)  # 核心：文字居中
                return item

            self.table.setItem(row, 1, create_center_item(os.path.basename(video_path)))

            m, s = divmod(int(sec), 60)
            self.table.setItem(row, 2, create_center_item(f"{m:02d}:{s:02d}"))

            self.table.setItem(row, 3, create_center_item(f"{score:.2f}"))

            # --- 3. 操作按钮列 (第 4 列) ---
            btn_box = QWidget()
            btn_layout = QHBoxLayout(btn_box)
            btn_layout.setAlignment(Qt.AlignCenter)  # 核心：让布局里的按钮整体居中
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(10)

            p_btn = QPushButton("预览")
            p_btn.setFixedSize(60, 30)  # 固定大小更好看
            p_btn.clicked.connect(lambda _, p=video_path, t=sec: self.handle_play(p, t))

            l_btn = QPushButton("定位")
            l_btn.setFixedSize(60, 30)
            l_btn.clicked.connect(lambda _, p=video_path: open_in_explorer(p))

            btn_layout.addWidget(p_btn)
            btn_layout.addWidget(l_btn)
            self.table.setCellWidget(row, 4, btn_box)

    def handle_play(self, path, time_sec):
        # 1. 释放文件
        self.media_player.stop()
        self.media_player.setSource(QUrl(""))

        # 给 Windows 磁盘一点点反应时间
        QThread.msleep(150)

        # 2. 调用 FFmpeg 生成切片
        result = create_preview_clip(path, time_sec, self.cache_path)

        if result.returncode == 0:
            # 3. 播放
            self.media_player.setSource(QUrl.fromLocalFile(self.cache_path))
            self.media_player.play()
            print(f"播放成功: {self.cache_path}")
        else:
            QMessageBox.critical(self, "错误", "预览生成失败！请检查 FFmpeg 路径及视频权限。")

