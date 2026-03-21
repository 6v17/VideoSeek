import os
import sys
import time
import cv2
import numpy as np
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import *
from PySide6.QtMultimediaWidgets import *

from src.config import load_config
from src.core import run_search
from src.utils import create_preview_clip, open_in_explorer, get_single_thumbnail


# --- 后台搜索线程 ---
class SearchWorker(QThread):
    result_ready = Signal(list)
    finished = Signal()

    def __init__(self, folder, query, is_text):
        super().__init__()
        self.folder, self.query, self.is_text = folder, query, is_text

    def run(self):
        try:
            results = run_search(self.folder, self.query, self.is_text)
            self.result_ready.emit(results)
        except Exception as e:
            print(f"搜索线程出错: {e}")
        self.finished.emit()


# --- 后台同步索引线程 ---
class IndexUpdateWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool)

    def __init__(self, video_folder):
        super().__init__()
        self.video_folder = video_folder

    def run(self):
        try:
            from src.update_video import get_video_files, process_single_video, load_meta, load_config, save_meta, \
                merge_and_save_all_vectors

            config = load_config()
            meta = load_meta(config["meta_file"])
            video_files = get_video_files(self.video_folder)

            all_v, all_t, all_p = [], [], []
            total = len(video_files)
            if total == 0:
                self.finished_signal.emit(True)
                return

            for i, (f, p) in enumerate(video_files):
                self.progress_signal.emit(int(i / total * 100), f"正在处理: {f}")
                v, t = process_single_video(p, f, meta, config)
                if v is not None:
                    all_v.append(v)
                    all_t.extend(t)
                    all_p.extend([p] * len(t))

            self.progress_signal.emit(95, "正在合并全局索引...")
            save_meta(meta, config["meta_file"])
            merge_and_save_all_vectors(all_v, all_t, all_p, config)

            self.progress_signal.emit(100, "同步完成")
            self.finished_signal.emit(True)
        except Exception as e:
            print(f"Worker Error: {e}")
            self.finished_signal.emit(False)


# --- 主界面 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoSeek Pro - 智能视频检索")
        self.resize(1240, 850)

        # 1. 初始化路径
        self.cache_dir = os.path.abspath("data/cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_path = os.path.join(self.cache_dir, "preview.mp4")
        self.current_img_path = None
        self.video_library_path = None

        # 2. 构建 UI
        self.setup_ui()
        self.setAcceptDrops(True)

        # 3. 初始化播放器
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)

        # 4. 加载配置
        saved_config = load_config()
        last_path = saved_config.get("video_folder", "")
        if last_path and os.path.exists(last_path):
            self.lbl_folder.setText(last_path)
            self.video_library_path = last_path

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # --- 左侧面板 ---
        left_panel = QVBoxLayout()

        # 1. 视频库选择
        folder_layout = QHBoxLayout()
        self.lbl_folder = QLineEdit()
        self.lbl_folder.setPlaceholderText("请选择视频库文件夹...")
        self.lbl_folder.setReadOnly(True)
        self.lbl_folder.setStyleSheet("height: 30px; background: #333; color: #ccc;")
        self.btn_select_folder = QPushButton("选择库")
        self.btn_select_folder.setFixedWidth(80)
        self.btn_select_folder.clicked.connect(self.select_video_folder)
        folder_layout.addWidget(self.lbl_folder)
        folder_layout.addWidget(self.btn_select_folder)
        left_panel.addLayout(folder_layout)

        # 2. 同步索引区
        self.btn_sync_db = QPushButton("🔄 同步视频库索引")
        self.btn_sync_db.setFixedHeight(35)
        self.btn_sync_db.setStyleSheet("background-color: #1976D2; color: white; font-weight: bold;")
        self.btn_sync_db.clicked.connect(self.start_update_index)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #aaa; font-size: 11px;")
        left_panel.addWidget(self.btn_sync_db)
        left_panel.addWidget(self.progress_bar)
        left_panel.addWidget(self.lbl_status)

        # 3. 图片预览区
        self.img_label = QLabel("将图片拖入此处或上传")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setFixedSize(300, 300)
        self.img_label.setStyleSheet("border: 2px dashed #555; border-radius: 10px; background: #1e1e1e; color: #888;")
        left_panel.addWidget(self.img_label)

        # 4. 搜索控制
        self.text_search = QLineEdit()
        self.text_search.setPlaceholderText("输入文字描述检索...")
        self.text_search.setStyleSheet("height: 35px; padding-left: 10px;")
        left_panel.addWidget(self.text_search)

        self.btn_upload = QPushButton("上传查询图片")
        self.btn_clear = QPushButton("清空所有内容")
        self.btn_search = QPushButton("开始检索")
        self.btn_search.setFixedHeight(45)
        self.btn_search.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold; font-size: 15px;")

        self.btn_upload.clicked.connect(self.upload_file)
        self.btn_clear.clicked.connect(self.clear_all)
        self.btn_search.clicked.connect(self.start_search)

        left_panel.addWidget(self.btn_upload)
        left_panel.addWidget(self.btn_clear)
        left_panel.addWidget(self.btn_search)
        left_panel.addStretch()

        # --- 右侧面板 ---
        right_panel = QVBoxLayout()
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(350)
        self.video_widget.setStyleSheet("background-color: black;")

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["预览图", "视频名称", "时间", "相似度", "操作"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #2b2b2b; color: #dcdcdc; gridline-color: #444; border: none; }
            QHeaderView::section { background-color: #3c3f41; padding: 4px; border: 1px solid #222; color: #aaa; font-weight: bold; }
            QTableWidget::item:selected { background-color: #2E7D32; }
        """)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.video_widget)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        right_panel.addWidget(splitter)

        main_layout.addLayout(left_panel, 1)
        main_layout.addLayout(right_panel, 3)

    # --- 核心逻辑 ---
    def on_search_finished(self):
        # --- 【新增效果点 2】 ---
        self.btn_search.setEnabled(True)
        self.btn_search.setText("开始检索")

        self.progress_bar.setRange(0, 100)  # 恢复正常的进度模式
        self.progress_bar.setVisible(False)
        self.lbl_status.setText("检索完成")
        # ------------------------
    def start_update_index(self):
        folder = self.video_library_path
        if not folder: return
        self.btn_sync_db.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.update_worker = IndexUpdateWorker(folder)
        self.update_worker.progress_signal.connect(self.on_update_progress)
        self.update_worker.finished_signal.connect(self.on_update_finished)
        self.update_worker.start()

    def on_update_progress(self, val, text):
        self.progress_bar.setValue(val)
        self.lbl_status.setText(text)

    def on_update_finished(self, success):
        self.btn_sync_db.setEnabled(True)
        self.lbl_status.setText("同步完成" if success else "同步失败")
        QTimer.singleShot(3000, lambda: self.progress_bar.setVisible(False))

    def select_video_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择库")
        if path:
            self.lbl_folder.setText(path)
            self.video_library_path = path
            from src.config import save_config
            cfg = load_config();
            cfg["video_folder"] = path;
            save_config(cfg)

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg)")
        if path: self.load_image(path)

    def load_image(self, path):
        self.current_img_path = path
        pix = QPixmap(path)
        self.img_label.setPixmap(pix.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.text_search.clear()

    def clear_all(self):
        self.table.setRowCount(0)
        self.img_label.clear()
        self.text_search.clear()
        self.img_label.setText("将图片拖入此处\n或点击下方上传")
        self.current_img_path = None
        self.media_player.stop()

    def start_search(self):
        folder = self.video_library_path
        if not folder:
            QMessageBox.warning(self, "错误", "请先选择视频库文件夹")
            return

        query = self.text_search.text().strip() or self.current_img_path
        if not query:
            QMessageBox.warning(self, "提示", "请输入描述文字或上传图片")
            return

        # --- 【新增效果点 1】 ---
        self.btn_search.setEnabled(False)
        self.btn_search.setText("🔍 正在全力检索...")

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 设置为 0-0，进度条会变成来回跑的“跑马灯”效果
        self.lbl_status.setText("正在多维向量空间进行语义匹配...")

        self.table.setRowCount(0)
        # ------------------------

        self.worker = SearchWorker(folder, query, bool(self.text_search.text().strip()))
        self.worker.result_ready.connect(self.display_results)
        # 注意：这里连接的是我们下面新写的结束函数
        self.worker.finished.connect(self.on_search_finished)
        self.worker.start()

    def display_results(self, results):
        self.table.setRowCount(0)
        self.table.verticalHeader().setDefaultSectionSize(90)
        if not results:
            self.lbl_status.setText("未发现匹配片段，请尝试更换关键词或图片")
            return
        self.lbl_status.setText(f"匹配成功：找到 {len(results)} 个最相似片段")
        for res in results:
            timestamp, sec, score, video_path = res
            row = self.table.rowCount();
            self.table.insertRow(row)

            # 1. 预览图 (居中)
            thumb_label = QLabel();
            thumb_label.setAlignment(Qt.AlignCenter)
            frame_bgr = get_single_thumbnail(video_path, sec)
            if frame_bgr is not None:
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.shape[1] * 3, QImage.Format_RGB888)
                thumb_label.setPixmap(
                    QPixmap.fromImage(img).scaled(120, 75, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.table.setCellWidget(row, 0, thumb_label)

            # 2. 文字 (全居中)
            def create_centered(text):
                it = QTableWidgetItem(str(text));
                it.setTextAlignment(Qt.AlignCenter);
                return it

            self.table.setItem(row, 1, create_centered(os.path.basename(video_path)))
            self.table.setItem(row, 2, create_centered(f"{int(sec // 60):02d}:{int(sec % 60):02d}"))
            self.table.setItem(row, 3, create_centered(f"{score:.2f}"))

            # 3. 按钮 (居中)
            btn_box = QWidget();
            btn_layout = QHBoxLayout(btn_box);
            btn_layout.setAlignment(Qt.AlignCenter)
            btn_layout.setContentsMargins(0, 0, 0, 0);
            btn_layout.setSpacing(10)
            p_btn = QPushButton("预览");
            p_btn.setFixedSize(60, 30)
            p_btn.clicked.connect(lambda _, p=video_path, t=sec: self.handle_play(p, t))
            l_btn = QPushButton("定位");
            l_btn.setFixedSize(60, 30)
            l_btn.clicked.connect(lambda _, p=video_path: open_in_explorer(p))
            btn_layout.addWidget(p_btn);
            btn_layout.addWidget(l_btn)
            self.table.setCellWidget(row, 4, btn_box)

    def handle_play(self, path, time_sec):
        self.media_player.stop();
        self.media_player.setSource(QUrl(""))
        QThread.msleep(100)
        if create_preview_clip(path, time_sec, self.cache_path).returncode == 0:
            self.media_player.setSource(QUrl.fromLocalFile(self.cache_path))
            self.media_player.play()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls: self.load_image(urls[0].toLocalFile())

