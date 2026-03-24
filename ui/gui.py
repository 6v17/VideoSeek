# src/gui.py
import os, cv2, time
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import *
from PySide6.QtMultimediaWidgets import QVideoWidget

from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.dialogs import AboutDialog, NoticeDialog
from ui.components import SidePanel, ResultTable
from ui.workers import SearchWorker, IndexUpdateWorker, ThumbLoader
from src.config import load_config, save_config
from src.utils import *

CONFIG = load_config()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_img_path = None
        self.worker = None
        self.up_worker = None
        self.thumb_thread = None
        self.current_search_id = 0

        cfg = load_config()
        self.is_dark_mode = (cfg.get("theme", "dark") == "dark")

        self.init_ui()
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        self.refresh_library_table()
        self.apply_theme()

    def init_ui(self):
        self.setWindowTitle(f"VideoSeek v{CONFIG.get('version', '1.0.0')}")
        self.resize(1200, 750)  # 更大窗口
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        self.side = SidePanel()
        main_layout.addWidget(self.side)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(15, 15, 15, 15)

        self.video_container = QWidget(objectName="VideoContainer")
        self.video_container.setMinimumHeight(380)
        v_lay = QVBoxLayout(self.video_container)
        v_lay.setContentsMargins(2, 2, 2, 2)
        self.video_widget = QVideoWidget()
        v_lay.addWidget(self.video_widget)

        self.result_table = ResultTable()
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.video_container)
        splitter.addWidget(self.result_table)
        splitter.setStretchFactor(0, 2)  # 视频区稍微高一点
        splitter.setStretchFactor(1, 3)  # 表格区
        right_layout.addWidget(splitter)
        main_layout.addWidget(right_container, 1)

        # 信号绑定
        self.side.btn_theme.clicked.connect(self.toggle_theme)
        self.side.btn_about.clicked.connect(self.show_about)
        self.side.btn_notice.clicked.connect(self.show_notice)
        self.side.btn_add_lib.clicked.connect(self.select_video_folder)
        self.side.btn_search.clicked.connect(self.start_search)
        self.side.btn_clear.clicked.connect(self.clear_all_content)
        self.side.btn_sync_db.clicked.connect(self.start_update_index)
        self.side.img_label.mousePressEvent = lambda e: self.upload_file()
        self.setAcceptDrops(True)

    # --- 添加显示公告的方法 ---
    def show_notice(self):
        NoticeDialog(self, self.is_dark_mode).exec()

    # --- 完善显示关于的方法 ---
    def show_about(self):
        AboutDialog(self, self.is_dark_mode).exec()
    def refresh_library_table(self):
        meta = load_meta(CONFIG["meta_file"])
        libs = meta.get("libraries", {})
        self.side.lib_table.setRowCount(0)
        is_indexing = self.up_worker is not None and self.up_worker.isRunning()

        for i, (path, data) in enumerate(libs.items()):
            row = self.side.lib_table.rowCount()
            self.side.lib_table.insertRow(row)

            # 0:序号 1:路径 2:状态 3:按钮
            it0 = QTableWidgetItem(str(i + 1));
            it0.setTextAlignment(Qt.AlignCenter)
            self.side.lib_table.setItem(row, 0, it0)

            name = os.path.basename(path) or path
            it1 = QTableWidgetItem(name);
            it1.setTextAlignment(Qt.AlignCenter);
            it1.setToolTip(path)
            self.side.lib_table.setItem(row, 1, it1)

            exists = os.path.exists(path)
            has_idx = len(data.get("files", {})) > 0
            color, txt = ("#52c41a", "正常") if exists and has_idx else (
                ("#faad14", "未同步") if exists else ("#ff4d4f", "变更"))
            it2 = QTableWidgetItem(txt);
            it2.setForeground(QColor(color));
            it2.setTextAlignment(Qt.AlignCenter)
            self.side.lib_table.setItem(row, 2, it2)

            # --- 优化后的按钮区域 ---
            btns = QWidget()
            lay = QHBoxLayout(btns)
            lay.setContentsMargins(8, 0, 8, 0)
            lay.setSpacing(10)  # 按钮之间拉开距离
            lay.setAlignment(Qt.AlignCenter)

            r_btn = QPushButton("🔄")
            r_btn.setProperty("class", "TableBtn")  # 应用样式类
            r_btn.setFixedSize(50, 28)
            r_btn.setCursor(Qt.PointingHandCursor)
            r_btn.clicked.connect(self.refresh_library_table)

            d_btn = QPushButton("🗑️")
            d_btn.setProperty("class", "TableDeleteBtn")  # 应用删除样式类
            d_btn.setFixedSize(50, 28)
            d_btn.setCursor(Qt.PointingHandCursor)
            d_btn.setEnabled(not is_indexing)
            d_btn.clicked.connect(lambda _, p=path: self.remove_library(p))

            lay.addWidget(r_btn)
            lay.addWidget(d_btn)
            self.side.lib_table.setCellWidget(row, 3, btns)

    def start_search(self):
        if self.thumb_thread and self.thumb_thread.isRunning():
            self.thumb_thread.stop();
            self.thumb_thread.wait()

        self.start_time = time.time()
        t_query = self.side.text_search.text().strip()
        query = t_query if t_query else self.current_img_path
        if not query: return

        self.side.btn_search.setEnabled(False)
        self.side.lbl_status.setText("🔍 正在检索...")
        self.worker = SearchWorker(query, bool(t_query))
        self.worker.result_ready.connect(self.display_results)
        self.worker.finished.connect(lambda: self.side.btn_search.setEnabled(True))
        self.worker.start()

    def display_results(self, results):
        self.result_table.setRowCount(0)
        if not results:
            self.side.lbl_status.setText("❌ 未找到结果");
            return

        self.result_table.setUpdatesEnabled(False)
        for i, (ts, sec, score, v_path) in enumerate(results):
            self.result_table.insertRow(i)
            # 0:序号 1:预览 2:名称 3:时间 4:匹配 5:按钮
            it0 = QTableWidgetItem(str(i + 1));
            it0.setTextAlignment(Qt.AlignCenter)
            self.result_table.setItem(i, 0, it0)

            lbl = QLabel("⌛");
            lbl.setAlignment(Qt.AlignCenter)
            self.result_table.setCellWidget(i, 1, lbl)

            it2 = QTableWidgetItem(os.path.basename(v_path));
            it2.setTextAlignment(Qt.AlignCenter)
            self.result_table.setItem(i, 2, it2)

            it3 = QTableWidgetItem(f"{int(sec // 60):02d}:{int(sec % 60):02d}");
            it3.setTextAlignment(Qt.AlignCenter)
            self.result_table.setItem(i, 3, it3)

            it4 = QTableWidgetItem(f"{int(score * 100)}%");
            it4.setTextAlignment(Qt.AlignCenter)
            self.result_table.setItem(i, 4, it4)

            btns = QWidget()
            lay = QHBoxLayout(btns)
            lay.setContentsMargins(10, 0, 10, 0)
            lay.setSpacing(12)
            lay.setAlignment(Qt.AlignCenter)

            # --- 预览按钮 ---
            p_btn = QPushButton("▶ 预览")
            p_btn.setProperty("class", "TableBtn")
            p_btn.setFixedSize(70, 32)  # 稍微调宽一点，方便点击
            p_btn.setCursor(Qt.PointingHandCursor)
            p_btn.setToolTip("播放当前片段")

            # --- 定位按钮 ---
            l_btn = QPushButton("📂 定位")
            l_btn.setProperty("class", "TableLocateBtn")
            l_btn.setFixedSize(70, 32)
            l_btn.setCursor(Qt.PointingHandCursor)
            l_btn.setToolTip("在文件夹中显示")

            # 绑定信号
            p_btn.clicked.connect(lambda _, p=v_path, s=sec: self.handle_play(p, s))
            l_btn.clicked.connect(lambda _, p=v_path: open_in_explorer(p))

            # 把它们加进布局
            lay.addWidget(p_btn)
            lay.addWidget(l_btn)
            self.result_table.setCellWidget(i, 5, btns)

        self.result_table.setUpdatesEnabled(True)
        duration = time.time() - self.start_time
        self.side.lbl_status.setText(f"✅ 耗时 {duration:.2f}s | 找到 {len(results)} 个结果")

        self.thumb_thread = ThumbLoader(results)
        self.thumb_thread.thumb_ready.connect(self.update_row_thumb)
        self.thumb_thread.start()

    def update_row_thumb(self, row, pixmap):
        lbl = QLabel();
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(pixmap)
        self.result_table.setCellWidget(row, 1, lbl)

    def clear_all_content(self):
        self.current_img_path = None
        self.side.text_search.clear()
        self.side.img_label.clear()
        self.side.img_label.setText("📷\n点击或拖入图片检索")
        self.result_table.setRowCount(0)
        self.media_player.stop()
        if self.thumb_thread: self.thumb_thread.stop()
        self.side.lbl_status.setText("系统就绪（已清空）")

    # --- 基础功能逻辑 ---
    def select_video_folder(self):
        p = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if p:
            p = os.path.normpath(p)
            meta = load_meta(CONFIG["meta_file"])
            if p not in meta["libraries"]:
                meta["libraries"][p] = {"files": {}, "last_scan": ""}
                save_meta(meta, CONFIG["meta_file"]);
                self.refresh_library_table()

    def remove_library(self, path):
        if self.show_custom_msg("确认", f"移除库及其索引数据？\n{path}", QMessageBox.Question,
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            meta = load_meta(CONFIG["meta_file"])
            if path in meta["libraries"]:
                from src.update_video import delete_physical_video_data
                for info in meta["libraries"][path].get("files", {}).values():
                    delete_physical_video_data(info.get("vid"), CONFIG)
                del meta["libraries"][path]
                save_meta(meta, CONFIG["meta_file"]);
                self.refresh_library_table()

    def start_update_index(self):
        self.side.btn_sync_db.setEnabled(False);
        self.side.btn_add_lib.setEnabled(False)
        self.side.progress_bar.setVisible(True)
        self.up_worker = IndexUpdateWorker()
        self.up_worker.progress_signal.connect(
            lambda v, t: (self.side.progress_bar.setValue(v), self.side.lbl_status.setText(t)))
        self.up_worker.finished_signal.connect(self.on_update_finished)
        self.up_worker.start()

    def on_update_finished(self, success):
        self.side.btn_sync_db.setEnabled(True);
        self.side.btn_add_lib.setEnabled(True)
        self.side.progress_bar.setVisible(False);
        self.refresh_library_table()
        self.side.lbl_status.setText("✅ 同步完成" if success else "❌ 同步失败")

    def handle_play(self, path, sec):
        self.media_player.stop()
        cache = os.path.join(os.environ["LOCALAPPDATA"], "VideoSeek", "cache", "preview.mp4")
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        if create_preview_clip(path, sec, cache).returncode == 0:
            self.media_player.setSource(QUrl.fromLocalFile(cache));
            self.media_player.play()

    def upload_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.jpg *.png)")
        if p:
            self.current_img_path = p
            self.side.img_label.setPixmap(QPixmap(p).scaled(280, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.side.text_search.clear()

    def apply_theme(self):
        style = DARK_STYLE if self.is_dark_mode else LIGHT_STYLE
        self.setStyleSheet(style)
        # 强制刷新子控件样式
        self.side.style().unpolish(self.side)
        self.side.style().polish(self.side)
        self.side.btn_theme.setText("☀️" if self.is_dark_mode else "🌙")

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()
        cfg = load_config();
        cfg["theme"] = "dark" if self.is_dark_mode else "light"
        save_config(cfg)

    def show_custom_msg(self, title, text, icon, buttons=QMessageBox.Ok):
        msg = QMessageBox(self);
        msg.setWindowTitle(title);
        msg.setText(text);
        msg.setIcon(icon);
        msg.setStandardButtons(buttons)
        msg.setStyleSheet(DARK_STYLE if self.is_dark_mode else LIGHT_STYLE)
        return msg.exec()


    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls: self.upload_file_path(urls[0].toLocalFile())

    def upload_file_path(self, p):
        self.current_img_path = p
        self.side.img_label.setPixmap(QPixmap(p).scaled(280, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def closeEvent(self, event):
        if self.worker: self.worker.quit()
        if self.up_worker: self.up_worker.quit()
        if self.thumb_thread: self.thumb_thread.stop()
        event.accept()