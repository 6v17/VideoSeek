# src/workers.py
import numpy as np
from PySide6.QtCore import QThread, Signal, QCoreApplication
from src.core import run_search

class SearchWorker(QThread):
    result_ready = Signal(list)
    finished = Signal()

    def __init__(self, folder, query, is_text):
        super().__init__()
        self.folder, self.query, self.is_text = folder, query, is_text

    def run(self):
        try:
            results = run_search(self.folder, self.query, self.is_text)

            # 修复：确保发射的是 list 类型，避免 NumPy 歧义
            if results is None:
                self.result_ready.emit([])
            elif isinstance(results, np.ndarray):
                self.result_ready.emit(results.tolist())
            else:
                self.result_ready.emit(list(results))

        except Exception as e:
            import traceback
            traceback.print_exc()  # 打印完整堆栈，方便调试
            print(f"Search Error Details: {e}")
        finally:
            self.finished.emit()


class IndexUpdateWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool)

    def __init__(self, video_folder):
        super().__init__()
        self.video_folder = video_folder

    def run(self):
        try:
            # 延迟导入，防止启动时太慢
            from src.update_video import (get_video_files, process_single_video,
                                          load_meta, save_meta, merge_and_save_all_vectors)
            from src.config import load_config

            config = load_config()
            meta = load_meta(config["meta_file"])
            video_files = get_video_files(self.video_folder)

            all_v, all_t, all_p = [], [], []
            total = len(video_files)

            if total == 0:
                self.finished_signal.emit(True)
                return

            for i, (f, p) in enumerate(video_files):
                # 计算当前百分比（保留到 90%，留 10% 给最后的索引合并）
                current_percent = int((i / total) * 90)
                self.progress_signal.emit(current_percent, f"正在分析 ({i + 1}/{total}): {f}")

                # 执行核心处理
                v, t = process_single_video(p, f, meta, config)

                if v is not None:
                    all_v.append(v)
                    all_t.extend(t)
                    all_p.extend([p] * len(t))

                # --- 关键：给主线程留点喘息机会 ---
                # 如果连续处理小视频太快，稍微休眠 1ms 让 UI 有机会刷新
                QCoreApplication.processEvents()

                # 进入最后阶段
            self.progress_signal.emit(92, "正在写入元数据文件...")
            save_meta(meta, config["meta_file"])

            self.progress_signal.emit(95, "正在构建多维空间索引 (这可能需要几秒)...")
            merge_and_save_all_vectors(all_v, all_t, all_p, config)

            self.progress_signal.emit(100, "同步完成！")
            self.finished_signal.emit(True)

        except Exception as e:
            print(f"Index Worker Error: {e}")
            self.finished_signal.emit(False)