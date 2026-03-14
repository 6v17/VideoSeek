import cv2
import os
import numpy as np


def extract_frames_dynamic(video_path, output_dir, base_threshold=1000):
    """
    提取具有显著变化的帧作为关键帧，并动态调整阈值。

    :param video_path: 视频文件路径
    :param output_dir: 保存帧的文件夹路径
    :param base_threshold: 基准阈值，根据视频帧率动态调整
    :return: 帧文件路径与时间戳的列表
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 打开视频文件
    cap = cv2.VideoCapture(video_path)

    fps = cap.get(cv2.CAP_PROP_FPS)  # 获取视频的帧率
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))  # 获取总帧数
    frame_timestamps = []  # 存储帧的文件路径和时间戳
    prev_frame_gray = None
    frame_id = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 转换为灰度图像
        curr_frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if prev_frame_gray is not None:
            # 计算帧差
            diff = cv2.absdiff(prev_frame_gray, curr_frame_gray)
            diff_sum = np.sum(diff)

            # 动态调整阈值：根据帧率，帧率越高，阈值越大
            dynamic_threshold = base_threshold * (fps / 30)  # 以 30fps 为基准进行缩放

            if diff_sum > dynamic_threshold:  # 如果帧差超过动态阈值，认为是关键帧
                timestamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000  # 获取当前帧的时间戳（单位：秒）
                frame_filename = os.path.join(output_dir, f"frame_{frame_id:04d}.jpg")
                cv2.imwrite(frame_filename, frame)  # 保存帧为 JPG 文件

                # 将帧文件路径与时间戳保存
                frame_timestamps.append((frame_filename, timestamp))

        prev_frame_gray = curr_frame_gray
        frame_id += 1

    cap.release()
    print(f"Total key frames extracted: {frame_id}")
    return frame_timestamps



video_path = r"D:\PycharmProjects\VideoSeek\videos\12月30日.mp4"
output_dir = "frames"  # 保存帧的目录
frame_timestamps = extract_frames_dynamic(video_path, output_dir)

# 打印帧的文件路径和时间戳
for frame_filename, timestamp in frame_timestamps[:5]:  # 只打印前5帧
    print(f"Frame: {frame_filename}, Timestamp: {timestamp} seconds")
