import os
import time
import json
import hashlib
import sys
import subprocess
import cv2
import numpy as np
def measure_time(message=""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            s = time.time()
            res = func(*args, **kwargs)
            print(f"{message} {func.__name__} 耗时: {time.time()-s:.2f}s")
            return res
        return wrapper
    return decorator


import gc

#获取ffmpeg路径
def get_ffmpeg_path():
    # 获取 VideoSeek.exe 所在的文件夹
    if getattr(sys, 'frozen', False) or "__file__" not in globals():
        # 打包环境 (Nuitka / PyInstaller)
        base_dir = os.path.dirname(sys.executable)
    else:
        # 源码环境
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    ffmpeg_exe = os.path.join(base_dir, "ffmpeg.exe")

    # 如果根目录找不到，就尝试找默认环境（保底）
    if not os.path.exists(ffmpeg_exe):
        ffmpeg_exe = "ffmpeg"

    return ffmpeg_exe


#内存清理
def free_memory():
    """
    【ONNX 瘦身版】不再依赖 torch。
    主要通过 Python 自带的垃圾回收来清理内存。
    """
    # 强制进行 Python 层的垃圾回收
    gc.collect()

    print("已清理系统内存残留。")
#检查路径是否存在
def ensure_folder_exists(file_path):
    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
#获取视频hash
def get_video_hash(video_path):
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        h.update(f.read(10 * 1024 * 1024)) # 只读前10MB
    return h.hexdigest()
#保存mata文件
def save_meta(meta, meta_file):
    ensure_folder_exists(meta_file)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4, ensure_ascii=False)

#生成预览视频
def create_preview_clip(input_path, start_sec, output_path):
    ffmpeg = get_ffmpeg_path()
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except:
            pass

    cmd = [
        ffmpeg, "-y",
        "-ss", str(max(0, start_sec - 1)),
        "-t", "6",  # 预览没必要太长，6秒足够
        "-i", input_path,
        "-s", "640x360",  # 【关键】强制缩小预览分辨率，极大地减轻播放卡顿
        "-c:v", "libx264",
        "-preset", "ultrafast",  # 最快编码
        "-tune", "zerolatency",  # 零延迟优化
        "-crf", "32",  # 降低画质提高速度
        "-an", output_path
    ]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        # 修复此处的常量名：STARTF_USESHOWWINDOW
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # 配合使用 SW_HIDE (值为 0)，确保窗口完全隐藏
        startupinfo.wShowWindow = 0

    # 记得 startupinfo 必须作为关键字参数传递
    return subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)

def libx264_param():
    return "libx264" # 默认编码器

#文件资源管理器打开并选择该视频
def open_in_explorer(video_path):
    """资源管理器定位：增强版"""
    if not os.path.exists(video_path):
        print(f"错误：文件不存在 {video_path}")
        return

    # 1. 路径标准化（关键：将 / 转为 Windows 的 \）
    # 使用 normpath 可以确保路径格式符合当前系统要求
    path = os.path.normpath(os.path.abspath(video_path))

    if sys.platform == 'win32':
        # 2. Windows 这里的逗号后面【不要加空格】
        # 很多时候失败是因为写成了 '/select, ', path
        # 这种写法在处理带空格的路径时最稳妥
        try:
            # 使用 shell=False 配合列表传参，由 Python 处理引号转义
            subprocess.run(['explorer', f'/select,{path}'], check=False)
        except Exception as e:
            print(f"Windows 定位失败: {e}")
            # 备选方案：如果上面的失败，尝试直接打开文件夹
            os.startfile(os.path.dirname(path))

    elif sys.platform == 'darwin':  # macOS
        subprocess.run(['open', '-R', path])

    else:  # Linux (通常是 open 或 xdg-open)
        # Linux 并没有通用的“选择并定位”命令，通常只能打开所在目录
        folder = os.path.dirname(path)
        subprocess.run(['xdg-open', folder])

#预览图生成
def get_single_thumbnail(video_path, time_sec):
    """
    【内存流版】实时从视频扣一张图，不产生任何临时文件
    """

    ffmpeg_bin = get_resource_path("ffmpeg.exe")
    # -ss 在 -i 前面表示极速定位。抽取 1 帧，输出到管道 pipe:1
    cmd = [
        ffmpeg_bin, "-ss", str(time_sec), "-i", video_path,
        "-vframes", "1", "-f", "image2", "-vcodec", "mjpeg", "pipe:1"
    ]
    try:
        # capture_output 获取标准输出的内容
        process = subprocess.run(cmd, capture_output=True, check=True, timeout=3,creationflags=0x08000000)
        # 将二进制流转为 OpenCV 图片格式
        nparr = np.frombuffer(process.stdout, np.uint8)
        if len(nparr) > 0:
            return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"截取缩略图失败: {e}")
    return None

# --- src/utils.py ---
def load_meta(meta_file):
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 强制初始化库结构
                if "libraries" not in data:
                    data["libraries"] = {}
                return data
        except:
            return {"libraries": {}}
    return {"libraries": {}}

def get_resource_path(relative_path):
    """获取资源绝对路径，兼容 PyInstaller 和 Nuitka"""
    # PyInstaller 打包后，资源在 _MEIPASS 中
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)

    # Nuitka 打包后，可执行文件可能位于 dist 目录中
    # 获取可执行文件所在目录
    if getattr(sys, 'frozen', False) and hasattr(sys, 'executable'):
        # Nuitka 在打包后会设置 sys.frozen 为 True，sys.executable 为可执行文件路径
        base_path = os.path.dirname(sys.executable)
    else:
        # 开发环境
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)