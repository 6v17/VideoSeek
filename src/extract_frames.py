import subprocess
import numpy as np
import cv2


def extract_frames_with_ffmpeg(video_path):
    """
    【进化版】直接从内存读取视频帧进行向量化，不产生任何临时图片
    """
    fps = 1  # 依然每秒抽1帧

    # 获取视频分辨率
    cap = cv2.VideoCapture(video_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if width == 0 or height == 0:
        return [], []

    command = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps={fps}",
        "-f", "image2pipe",
        "-pix_fmt", "bgr24",
        "-vcodec", "rawvideo", "-"
    ]

    # 启动异步管道
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    frames = []
    timestamps = []
    frame_size = width * height * 3  # BGR24 每像素3字节

    count = 0
    while True:
        in_bytes = process.stdout.read(frame_size)
        if len(in_bytes) != frame_size:
            break

        # 1. 转换并存入内存
        frame = np.frombuffer(in_bytes, np.uint8).reshape((height, width, 3))

        # --- 【关键优化：立即缩放】 ---
        # 缩放到 224x224 (CLIP的标准尺寸)，这样每帧只有 150KB，而不是 6MB
        small_frame = cv2.resize(frame, (224, 224))

        frames.append(small_frame)  # 只存缩小的图
        timestamps.append(count / fps)
        count += 1

    process.terminate()
    print(f"内存抽帧完成: {len(frames)} 帧")
    return frames, timestamps