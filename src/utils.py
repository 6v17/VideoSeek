import os
import time
import json
import hashlib
import sys
import subprocess
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


def free_memory():
    """
    【ONNX 瘦身版】不再依赖 torch。
    主要通过 Python 自带的垃圾回收来清理内存。
    """
    # 强制进行 Python 层的垃圾回收
    gc.collect()

    print("已清理系统内存残留。")

def ensure_folder_exists(file_path):
    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)

def get_video_hash(video_path):
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        h.update(f.read(10 * 1024 * 1024)) # 只读前10MB
    return h.hexdigest()

def save_meta(meta, meta_file):
    ensure_folder_exists(meta_file)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4, ensure_ascii=False)

def load_meta(meta_file):
    if os.path.exists(meta_file):
        with open(meta_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def create_preview_clip(video_path, time_sec, output_path):
    """生成4秒短片预览"""
    start_time = max(time_sec - 2, 0)
    ffmpeg_bin = get_resource_path("ffmpeg.exe")
    cmd = [
        ffmpeg_bin, "-y", "-ss", str(start_time), "-t", "4",
        "-i", video_path, "-c:v", libx264_param(), "-preset", "superfast", "-an", output_path
    ]
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,creationflags=0x08000000)

def libx264_param():
    return "libx264" # 默认编码器

def open_in_explorer(video_path):
    """资源管理器定位"""
    path = os.path.abspath(video_path)
    if sys.platform == 'win32':
        subprocess.run(['explorer', '/select,', path])
    elif sys.platform == 'darwin':
        subprocess.run(['open', '-R', path])


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


def get_resource_path(relative_path):
    """获取资源绝对路径，兼容开发和打包环境"""
    if hasattr(sys, '_MEIPASS'):
        # 打包后的路径
        return os.path.join(sys._MEIPASS, relative_path)
    # 开发环境的路径
    return os.path.join(os.path.abspath("."), relative_path)