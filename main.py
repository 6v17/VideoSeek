from src.extract_frames import extract_frames_dynamic
from src.faiss_index import create_clip_index, search_vector, load_clip_index
from src.clip_embedding import get_clip_embedding, save_vectors, load_vectors

if __name__ == "__main__":
    # 视频路径和保存帧的目录
    video_path = r"D:\PycharmProjects\VideoSeek\videos\12月30日.mp4"
    output_dir = "frames"  # 保存帧的目录

    # 加载已保存的索引
    index = load_clip_index("data/index/video_index.faiss")

    # 加载已保存的向量和时间戳
    data = load_vectors("data/vector/frame_vectors.npy")
    print(data)
    print(index)
    if data is not None:
        vectors_list, timestamps = data['vector'], data['timestamps']
    else:
        vectors_list, timestamps = None, None

    if not index or len(vectors_list) == 0 or len(timestamps) == 0: #都不为空，索引和向量已经存在
        # 如果没有索引或向量或时间戳，则重新抽帧、生成向量并创建索引
        frame_timestamps = extract_frames_dynamic(video_path, output_dir)

        # 打印前5帧的文件路径和时间戳
        for frame_filename, timestamp in frame_timestamps[:5]:  # 只打印前5帧
            print(f"帧: {frame_filename}, 时间: {timestamp} 秒")

        # 遍历所有帧，获取 CLIP 向量
        vectors_list = []
        timestamps = []  # 用来保存时间戳

        for frame_filename, timestamp in frame_timestamps:
            # 获取 CLIP 向量
            vec = get_clip_embedding(frame_filename)

            # 直接使用 `frame_timestamps` 中的时间戳
            vectors_list.append(vec[0])  # vec shape: (1,512)
            timestamps.append(timestamp)  # 使用 `frame_timestamps` 中的时间戳

        # 保存向量和时间戳
        save_vectors(vectors_list, timestamps, "data/vector/frame_vectors.npy")

        # 创建索引
        index = create_clip_index(vectors_list, "data/index/video_index.faiss")  # 这里只需要传入向量，不需要帧路径

    if vectors_list is not None:
        # 执行查询
        query_image_path = "img/img.png"  # 你的查询图像路径
        query_vector = get_clip_embedding(query_image_path)

        # 查找最匹配的帧
        fps = 30  # 这里可以是从视频文件获取的帧率，例如通过 cv2 获取
        matched_frames = search_vector(query_vector, index, timestamps, fps)

        # 打印匹配的时间戳
        for timestamp, frame_idx, i in matched_frames:
            print(f"匹配的时间戳: {timestamp} 秒 (帧索引: {frame_idx}, 帧数：{i})")