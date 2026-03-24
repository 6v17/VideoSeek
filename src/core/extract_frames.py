import subprocess

import cv2
import numpy as np

from src.app.config import load_config
from src.utils import get_ffmpeg_path


def extract_frames_with_ffmpeg(video_path):
    config = load_config()
    fps = config.get("fps", 1)

    cap = cv2.VideoCapture(video_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if width <= 0 or height <= 0:
        return [], []

    ffmpeg_bin = get_ffmpeg_path()
    command = [
        ffmpeg_bin,
        "-i",
        video_path,
        "-vf",
        f"fps={fps}",
        "-sn",
        "-f",
        "image2pipe",
        "-pix_fmt",
        "bgr24",
        "-vcodec",
        "rawvideo",
        "-",
    ]

    creationflags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    frames = []
    timestamps = []
    frame_size = width * height * 3
    count = 0

    while True:
        if not process.stdout:
            break
        in_bytes = process.stdout.read(frame_size)
        if len(in_bytes) != frame_size:
            break

        frame = np.frombuffer(in_bytes, np.uint8).reshape((height, width, 3))
        frames.append(cv2.resize(frame, (224, 224)))
        timestamps.append(count / fps)
        count += 1

    process.terminate()
    print(f"Frame extraction completed: {len(frames)} frames")
    return frames, timestamps
