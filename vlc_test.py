import os
import sys

# ==========================================
# 1️⃣ 强制初始化环境 (必须在 import vlc 之前)
# ==========================================
curr_dir = os.path.dirname(os.path.abspath(__file__))
vlc_dir = os.path.join(curr_dir, "vlc_lib")

# 把 vlc_lib 变成系统第一优先搜索目录
os.environ['PATH'] = vlc_dir + os.pathsep + os.environ['PATH']

if sys.platform == 'win32' and hasattr(os, 'add_dll_directory'):
    # Python 3.8+ 必须调这个
    try:
        os.add_dll_directory(vlc_dir)
    except Exception as e:
        print(f"添加 DLL 目录失败: {e}")

# 设置 python-vlc 专用的环境变量 (有些版本会读这个)
os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(vlc_dir, "libvlc.dll")

# 现在再导入
import vlc
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QSlider, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer


# ==========================================
# 2️⃣ 播放器核心类
# ==========================================
class VideoSeekPlayer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VideoSeek - 匹配片段预览")
        self.resize(1000, 700)
        self.setAttribute(Qt.WA_NativeWindow)  # 确保 winId 稳定

        # --- 变量初始化 ---
        self.auto_stop_time_ms = -1  # 自动停止点
        self.user_unlocked = False  # 是否已解锁全片播放
        self.is_sliding = False  # 是否正在拖动进度条

        # --- UI 布局 ---
        self.layout = QVBoxLayout(self)

        # 视频显示区域
        self.video_frame = QWidget()
        self.video_frame.setStyleSheet("background-color: black;")
        self.layout.addWidget(self.video_frame)

        # 状态提示标签
        self.status_label = QLabel("模式: 待机")
        self.layout.addWidget(self.status_label)

        # 控制栏
        controls = QHBoxLayout()
        self.play_btn = QPushButton("暂停")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider)
        self.layout.addLayout(controls)

        # --- VLC 实例 ---
        vlc_dir = os.path.join(os.path.dirname(__file__), "vlc_lib")
        plugins_path = os.path.join(vlc_dir, "plugins")
        args = [f'--plugin-path={plugins_path}', '--no-xlib', '--quiet', '--no-video-title-show']
        self.instance = vlc.Instance(args)
        self.player = self.instance.media_player_new()

        # --- 事件绑定 ---
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.set_video_position)

        # 定时器：更新进度 + 检查自动停止
        self.timer = QTimer(self)
        self.timer.setInterval(100)  # 100ms 检查一次更精准
        self.timer.timeout.connect(self.handle_timer)
        self.timer.start()

    def load_matched_segment(self, path, start_s, end_s):
        """
        核心方法：加载视频并定位到匹配片段
        """
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            return

        # 1. 设置状态
        self.user_unlocked = False
        self.auto_stop_time_ms = end_s * 1000
        self.status_label.setText(f"模式: 匹配预览 ({start_s}s -> {end_s}s)")
        self.status_label.setStyleSheet("color: #00FF00; font-weight: bold;")

        # 2. 设置起点参数
        options = f":start-time={start_s}"
        media = self.instance.media_new(path, options)
        self.player.set_media(media)

        # 3. 绑定窗口并播放
        # 必须转为 int，VLC 才能识别 HWND
        self.player.set_hwnd(int(self.video_frame.winId()))
        self.player.play()
        self.play_btn.setText("暂停")

    def on_slider_pressed(self):
        """当用户点击/拖动进度条时，立即解锁全片限制"""
        self.is_sliding = True
        if not self.user_unlocked:
            self.user_unlocked = True
            self.auto_stop_time_ms = -1
            self.status_label.setText("模式: 自由探索 (全片已解锁)")
            self.status_label.setStyleSheet("color: white;")

    def set_video_position(self):
        """拖动结束，跳转位置"""
        if self.player.get_length() > 0:
            new_time = int((self.slider.value() / 1000.0) * self.player.get_length())
            self.player.set_time(new_time)
        self.is_sliding = False

    def handle_timer(self):
        """每 100ms 运行一次：负责 UI 更新和自动刹车"""
        if not self.player.is_playing() and not self.is_sliding:
            return

        curr_time = self.player.get_time()

        # 自动刹车逻辑
        if not self.user_unlocked and self.auto_stop_time_ms > 0:
            if curr_time >= self.auto_stop_time_ms:
                self.player.pause()
                self.auto_stop_time_ms = -1  # 刹车只生效一次
                self.status_label.setText("模式: 预览结束 (已到达匹配点)")
                self.play_btn.setText("播放全片")
                return

        # 更新进度条
        if not self.is_sliding and self.player.get_length() > 0:
            pos = curr_time / self.player.get_length()
            self.slider.blockSignals(True)  # 避免更新进度触发 slider 逻辑
            self.slider.setValue(int(pos * 1000))
            self.slider.blockSignals(False)

    def toggle_play(self):
        if self.player.is_playing():
            self.player.pause()
            self.play_btn.setText("播放")
        else:
            # 如果是刹车状态下再次点击播放，自动进入解锁模式
            if not self.user_unlocked:
                self.user_unlocked = True
                self.auto_stop_time_ms = -1
                self.status_label.setText("模式: 自由探索")
            self.player.play()
            self.play_btn.setText("暂停")


# ==========================================
# 3️⃣ 执行测试
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)

    player = VideoSeekPlayer()

    # --- 测试数据 ---
    # 替换为你磁盘上的真实视频路径
    video_file = r"E:\素材库\鸣潮\【3.1】「赠予雪中的你」\3.1【过场动画】\11（男漂）【过场动画】远航星.mp4"

    player.show()

    # 模拟一次匹配结果：从第 30 秒播到第 40 秒
    player.load_matched_segment(video_file, start_s=30, end_s=40)

    sys.exit(app.exec())