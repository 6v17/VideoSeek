from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, \
    QWidget, QTableWidget, QTableWidgetItem
from PySide6.QtCore import QUrl, Qt,Signal,Slot
import sys
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QSplitter

class MainWindow(QMainWindow):
    upload_signal = Signal(str)
    clear_signal = Signal()
    search_signal = Signal()
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoSeek")
        self.resize(1080, 600)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.setAcceptDrops(True)
        #主布局
        main_layout = QHBoxLayout(self.central_widget)

        #左侧布局
        self.left_layout = QVBoxLayout()
        self.upload_btn = QPushButton("上传")
        self.clear_btn = QPushButton("清空")
        self.search_btn = QPushButton("开始检索")
        # 2. 创建 QLabel 用于显示图片
        self.img_label = QLabel("暂无图片")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setMinimumSize(400, 200)
        self.img_label.setStyleSheet("border: 1px solid gray;")

        self.upload_btn.clicked.connect(self.upload_file)
        self.clear_btn.clicked.connect(self.clear_file)
        self.search_btn.clicked.connect(self.start_search)


        self.btn_layout = QVBoxLayout()
        self.btn_layout.addWidget(self.upload_btn)
        self.btn_layout.addWidget(self.clear_btn)
        self.btn_layout.addWidget(self.search_btn)
        self.left_layout.addWidget(self.img_label)
        self.left_layout.addLayout(self.btn_layout)

         # 创建右侧垂直布局并添加示例控件
        self.right_layout = QVBoxLayout()
        # 创建控件
        self.video_widget = QVideoWidget()
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "序号", "视频名", "时间", "相似度", "操作"
        ])

        # ⭐ 关键：只用 splitter 管理 video + table
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.video_widget)
        splitter.addWidget(self.table)

        # ⭐ 布局顺序
        self.right_layout.addWidget(splitter)

        self.add_result(1,r"C:\Users\LiuWei\Desktop\12月30日.mp4",2,0.99)

        # 5. 将左右布局添加到主布局，设置拉伸因子（两者宽度比例相等）
        main_layout.addLayout(self.left_layout, 1)   # 拉伸因子为1
        main_layout.addLayout(self.right_layout, 1)  # 拉伸因子为1
    #播放视频
    def play_result(self, video, time_sec):
        print(f"播放: {video} @ {time_sec}")
        self.media_player.setSource(QUrl.fromLocalFile(video))
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.play()

    #添加一条匹配数据
    def add_result(self, index, video, time_sec, score):
        row = self.table.rowCount()
        self.table.insertRow(row)
        # 序号
        item0 = QTableWidgetItem(str(index))
        item0.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, item0)
        # 视频名（一般左对齐更好看，也可以居中）
        item1 = QTableWidgetItem(video)
        item1.setTextAlignment(Qt.AlignCenter)  # 想左对齐就删掉这行
        self.table.setItem(row, 1, item1)
        # 时间
        m = int(time_sec // 60)
        s = int(time_sec % 60)
        time_str = f"{m:02d}:{s:02d}"
        item2 = QTableWidgetItem(time_str)
        item2.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 2, item2)
        # 相似度
        item3 = QTableWidgetItem(f"{score:.2f}")
        item3.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 3, item3)

        # 播放按钮（默认就是居中的）
        btn = QPushButton("播放")
        btn.clicked.connect(lambda _, v=video, t=time_sec: self.play_result(v, t))
        self.table.setCellWidget(row, 4, btn)

    @Slot()
    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self.load_image(file_path)
    @Slot()
    def clear_file(self):
        self.clear_signal.emit()
    @Slot()
    def start_search(self):
        self.search_signal.emit()
    
    def load_image(self, file_path):
        pixmap = QPixmap(file_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.img_label.size(),
                                        Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation)
            self.img_label.setPixmap(scaled_pixmap)
            print(f"加载图片: {file_path}")
            self.upload_signal.emit(file_path)
        else:
            self.img_label.setText("无法加载图片")
    def dragEnterEvent(self, event):
    # 检查拖拽数据中是否有 URL（即文件路径）
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()
                # 检查文件扩展名是否为图片格式
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            # 调用已有的加载图片逻辑（复用 upload_file 中的代码）
            self.load_image(file_path)

class SearchController:
    def __init__(self,ui):
        self.ui = ui
        self.ui.search_signal.connect(self.handle_search)
        self.ui.clear_signal.connect(self.handle_clear)
        self.ui.upload_signal.connect(self.handle_upload)
        self.file_path = None
    def handle_upload(self,file_path):
        self.file_path = file_path
    def handle_clear(self):
        self.file_path = None
        self.ui.img_label.clear()
    def handle_search(self):
        if self.file_path:
            print(f"开始检索图片: {self.file_path}")
        else:
            print("请先上传图片")
    
    
class SearchService:
    def __init__(self):
        pass
        

