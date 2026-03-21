
from src.utils import measure_time

import subprocess
import os
import cv2
# 抽帧
@measure_time("抽帧耗时:")
def extract_frames_with_ffmpeg(video_path, output_dir="frames", fps=1):
    """
    使用 ffmpeg 从视频中提取帧并保存为图像文件，并返回帧数据和时间戳。
    :param video_path: 视频文件路径
    :param output_dir: 输出文件夹
    :param fps: 每秒提取的帧数
    :return: 提取的帧和对应时间戳
    """
    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 构造ffmpeg命令
    command = [
        "ffmpeg", "-i", video_path,  # 输入视频文件
        "-vf", f"fps={fps}",  # 每秒提取 fps 帧
        os.path.join(output_dir, "frame_%04d.png")  # 输出帧文件名格式
    ]

    # 执行命令，提取帧
    subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 读取提取的帧并返回
    frames = []
    timestamps = []

    for filename in os.listdir(output_dir):
        if filename.endswith(".png"):
            frame = cv2.imread(os.path.join(output_dir, filename))
            if frame is not None:
                frames.append(frame)
                # 计算时间戳（假设以帧为单位）
                timestamp = int(filename.split("_")[1].split(".")[0]) / fps
                timestamps.append(timestamp)

    return frames, timestamps

