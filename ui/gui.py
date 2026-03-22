# src/gui.py
import os, cv2
import tempfile

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import *
from PySide6.QtMultimediaWidgets import *

from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.dialogs import AboutDialog
from ui.workers import SearchWorker, IndexUpdateWorker
from src.config import load_config, save_config
from src.utils import create_preview_clip, open_in_explorer, get_single_thumbnail


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoSeek Pro")
        self.resize(1280, 850)
        # --- 修改这里：从配置加载主题偏好 ---
        cfg = load_config()
        # 如果配置里没有 theme 字段，默认设为 "dark"
        theme_pref = cfg.get("theme", "dark")
        self.is_dark_mode = (theme_pref == "dark")
        # ----------------------------------

        self.cache_path = os.path.abspath("data/cache/preview.mp4")
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

        self.current_img_path = None
        self.video_library_path = None

        self.setup_ui()
        self.apply_theme()

        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)

        cfg = load_config()
        if cfg.get("video_folder"):
            self.video_library_path = cfg["video_folder"]
            self.lbl_folder.setText(self.video_library_path)

    def apply_theme(self):
        self.setStyleSheet(DARK_STYLE if self.is_dark_mode else LIGHT_STYLE)

    def toggle_theme(self):
        """切换主题并保存偏好"""
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()

        # 更新按钮文字
        self.btn_theme.setText("🌙 深色模式" if not self.is_dark_mode else "☀️ 浅色模式")

        # --- 新增：保存到配置文件 ---
        cfg = load_config()
        cfg["theme"] = "dark" if self.is_dark_mode else "light"
        save_config(cfg)
        # -------------------------

    def show_about(self):
        AboutDialog(self, self.is_dark_mode).exec()

    def setup_ui(self):
        # 1. 顶部菜单栏
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("关于")
        about_act = QAction("关于 VideoSeek", self)
        about_act.triggered.connect(self.show_about)
        help_menu.addAction(about_act)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 2. 侧边栏
        side_panel = QWidget();
        side_panel.setObjectName("SidePanel")
        left_layout = QVBoxLayout(side_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)

        # 头部
        header = QHBoxLayout()
        title = QLabel("VideoSeek");
        title.setStyleSheet("font-size: 20px; font-weight: 900;")
        # 修改这里：根据当前模式初始化按钮文字
        btn_text = "☀️ 浅色模式" if self.is_dark_mode else "🌙 深色模式"
        self.btn_theme = QPushButton(btn_text)
        self.btn_theme.setFixedWidth(85)
        self.btn_theme.clicked.connect(self.toggle_theme)
        header.addWidget(title);
        header.addStretch();
        header.addWidget(self.btn_theme)
        left_layout.addLayout(header)

        # 路径选择
        left_layout.addWidget(QLabel("媒体库路径:"))
        p_lay = QHBoxLayout()
        self.lbl_folder = QLineEdit();
        self.lbl_folder.setReadOnly(True)
        btn_browse = QPushButton("浏览");
        btn_browse.setFixedWidth(50)
        btn_browse.clicked.connect(self.select_video_folder)
        p_lay.addWidget(self.lbl_folder);
        p_lay.addWidget(btn_browse)
        left_layout.addLayout(p_lay)

        # 同步
        self.btn_sync_db = QPushButton("🔄 同步视频库索引")
        self.btn_sync_db.setObjectName("PrimaryButton");
        self.btn_sync_db.setFixedHeight(40)
        self.btn_sync_db.clicked.connect(self.start_update_index)
        left_layout.addWidget(self.btn_sync_db)

        # 图片预览区
        self.img_label = QLabel("📷\n拖入图片检索");
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter);
        self.img_label.setFixedSize(280, 200)
        left_layout.addWidget(self.img_label)

        # 文字搜索
        self.text_search = QLineEdit();
        self.text_search.setPlaceholderText("🔍 输入画面语义描述...")
        left_layout.addWidget(self.text_search)

        # 【上传与清空按钮】
        action_lay = QHBoxLayout()
        self.btn_upload = QPushButton("上传参考图")
        self.btn_clear = QPushButton("清空当前")
        self.btn_upload.clicked.connect(self.upload_file)
        self.btn_clear.clicked.connect(self.clear_all)
        action_lay.addWidget(self.btn_upload);
        action_lay.addWidget(self.btn_clear)
        left_layout.addLayout(action_lay)

        # 搜索按钮
        self.btn_search = QPushButton("开始智能检索")
        self.btn_search.setObjectName("SearchButton");
        self.btn_search.setFixedHeight(45)
        self.btn_search.clicked.connect(self.start_search)
        left_layout.addWidget(self.btn_search)

        # 状态反馈
        self.progress_bar = QProgressBar();
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("");
        self.lbl_status.setObjectName("StatusLabel");
        self.lbl_status.setWordWrap(True)
        left_layout.addWidget(self.progress_bar)
        left_layout.addWidget(self.lbl_status)

        left_layout.addStretch()

        # 底部关于入口
        btn_about_bottom = QPushButton("ⓘ 了解 VideoSeek Pro")
        btn_about_bottom.setStyleSheet("background:transparent; color:#666; text-align:left; font-size:11px;")
        btn_about_bottom.setCursor(Qt.PointingHandCursor)
        btn_about_bottom.clicked.connect(self.show_about)
        left_layout.addWidget(btn_about_bottom)

        # 3. 右侧面板
        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(15, 15, 15, 15)

        # 1. 为播放器创建一个容器 QWidget
        self.video_container = QWidget()
        self.video_container.setObjectName("VideoContainer")
        self.video_container.setStyleSheet("background-color: black; border-radius: 8px;")

        # 2. 给容器设置一个布局，确保播放器在里面始终填满
        video_layout = QVBoxLayout(self.video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)  # 间距设为0

        self.video_widget = QVideoWidget()
        # 关键：设置尺寸策略，让它在水平和垂直方向都积极扩展
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 给它一个保底高度，防止被压得完全消失
        self.video_widget.setMinimumHeight(150)
        self.video_widget.setMinimumHeight(380)
        self.video_widget.setStyleSheet("background: black; border-radius: 8px;")
        video_layout.setContentsMargins(2, 2, 2, 2)  # 留出2像素的容器背景
        video_layout.addWidget(self.video_widget)

        self.table = QTableWidget(0, 5)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)  # 选中整行
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)  # 只能选一行
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 禁止双击编辑文字
        self.table.setFocusPolicy(Qt.NoFocus)  # 移除单元格虚线框
        self.table.setHorizontalHeaderLabels(["预览", "视频名称", "时间点", "相似度", "操作"])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 140)

        # 4. 修改 Splitter，添加的是容器而不是直接添加 video_widget
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)  # 稍微加粗分割线，方便操作
        splitter.addWidget(self.video_container)  # 添加容器
        splitter.addWidget(self.table)

        # 设置初始分配比例：播放器占 40%，表格占 60%
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        right_panel.addWidget(splitter)

        main_layout.addWidget(side_panel)
        main_layout.addLayout(right_panel, 1)
        self.setAcceptDrops(True)

    # --- 逻辑处理 (省略具体实现，与之前代码逻辑一致) ---
    def select_video_folder(self):
        p = QFileDialog.getExistingDirectory(self, "选择视频库")
        if p:
            self.lbl_folder.setText(p);
            self.video_library_path = p
            c = load_config()
            c["video_folder"] = p
            save_config(c)

    def upload_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.jpg *.png)")
        if p: self.load_image(p)

    def load_image(self, p):
        self.current_img_path = p
        self.img_label.setPixmap(QPixmap(p).scaled(280, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.text_search.clear()

    def clear_all(self):
        self.table.setRowCount(0)
        self.text_search.clear()
        self.current_img_path = None
        self.img_label.clear()
        self.img_label.setText("📷\n拖入图片检索")
        self.media_player.stop()
        self.lbl_status.clear()

    def start_search(self):
        if not self.video_library_path: return QMessageBox.warning(self, "提示", "请先选择库")
        query = self.text_search.text().strip() or self.current_img_path
        if not query: return

        self.btn_search.setEnabled(False)
        self.btn_search.setText("正在搜索向量空间...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        self.worker = SearchWorker(self.video_library_path, query, bool(self.text_search.text().strip()))
        self.worker.result_ready.connect(self.display_results)
        self.worker.finished.connect(self.on_search_done)
        self.worker.start()

    def on_search_done(self):
        self.btn_search.setEnabled(True)
        self.btn_search.setText("开始智能检索")
        self.progress_bar.setVisible(False)

    def display_results(self, results):
        self.table.setRowCount(0)
        if not results: self.lbl_status.setText("未匹配到结果"); return
        self.lbl_status.setText(f"匹配成功: 找到 {len(results)} 个片段")
        self.table.verticalHeader().setDefaultSectionSize(90)
        for ts, sec, score, v_path in results:
            r = self.table.rowCount();
            self.table.insertRow(r)

            thumb = QLabel()
            thumb.setAlignment(Qt.AlignCenter)
            f = get_single_thumbnail(v_path, sec)
            if f is not None:
                rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
                thumb.setPixmap(QPixmap.fromImage(qimg).scaled(120, 80, Qt.KeepAspectRatio))
            self.table.setCellWidget(r, 0, thumb)

            self.table.setItem(r, 1, QTableWidgetItem(os.path.basename(v_path)))
            self.table.setItem(r, 2, QTableWidgetItem(f"{int(sec // 60):02d}:{int(sec % 60):02d}"))
            self.table.setItem(r, 3, QTableWidgetItem(f"{score:.2f}"))

            btn_box = QWidget()
            lay = QHBoxLayout(btn_box)
            lay.setContentsMargins(5, 5, 5, 5)
            p_btn = QPushButton("预览")
            l_btn = QPushButton("定位")
            p_btn.clicked.connect(lambda _, p=v_path, s=sec: self.handle_play(p, s))
            l_btn.clicked.connect(lambda _, p=v_path: open_in_explorer(p))
            lay.addWidget(p_btn)
            lay.addWidget(l_btn)
            self.table.setCellWidget(r, 4, btn_box)

    # 在 MainWindow 的 __init__ 或者 handle_play 里修改

    def handle_play(self, path, sec):
        self.media_player.stop()
        self.media_player.setSource(QUrl(""))
        QThread.msleep(100)

        # 【核心修改】将缓存路径设为系统临时文件夹或 AppData
        # 这样无论软件装在哪，都有权写入
        cache_dir = os.path.join(os.environ["LOCALAPPDATA"], "VideoSeek", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        self.cache_path = os.path.join(cache_dir, "preview.mp4")

        # 生成剪辑
        res = create_preview_clip(path, sec, self.cache_path)

        # --- 调试大法：如果还是不行，把报错写进日志 ---
        if res.returncode != 0:
            log_path = os.path.join(os.path.dirname(self.cache_path), "error.log")
            with open(log_path, "w") as f:
                f.write(res.stderr.decode(errors='ignore'))
            self.lbl_status.setText(f"预览失败，日志已生成在: {log_path}")
            return

        if os.path.exists(self.cache_path) and os.path.getsize(self.cache_path) > 0:
            self.media_player.setSource(QUrl.fromLocalFile(self.cache_path))
            self.media_player.play()

    def on_update_progress(self, val, text):
        self.progress_bar.setValue(val)
        # 如果文件名太长，截断显示，防止 UI 抖动
        if len(text) > 50:
            text = text[:47] + "..."
        self.lbl_status.setText(text)
    def start_update_index(self):
        if not self.video_library_path:
            return QMessageBox.warning(self, "错误", "请先选择视频库")

        self.btn_sync_db.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.up_worker = IndexUpdateWorker(self.video_library_path)

        # 优化信号连接：确保跨线程通信更稳定
        self.up_worker.progress_signal.connect(self.on_update_progress, Qt.QueuedConnection)
        self.up_worker.finished_signal.connect(self.on_update_finished, Qt.QueuedConnection)

        self.up_worker.start()

    def on_update_finished(self, success):
        self.btn_sync_db.setEnabled(True)
        if success:
            self.lbl_status.setText("✅ 索引更新成功！")
            self.progress_bar.setValue(100)
        else:
            self.lbl_status.setText("❌ 索引更新失败，请检查视频库是否存在！")

        # 3秒后隐藏进度条
        QTimer.singleShot(3000, lambda: self.progress_bar.setVisible(False))
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls: self.load_image(urls[0].toLocalFile())