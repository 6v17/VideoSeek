"""Understanding OCR status should narrate frame progress, not a static line."""

from ui.windows.gui_library_indexing import LibraryIndexingGuiMixin
from ui.windows.gui_understanding_asr import UnderstandingAsrGuiMixin


class _Host(UnderstandingAsrGuiMixin, LibraryIndexingGuiMixin):
    texts = {
        "understanding_ocr_extract_running": "正在识别硬字幕…",
        "dialogue_stage_ocr": "识别字幕 {detail}",
        "dialogue_stage_extract": "提取音频",
        "dialogue_stage_merge": "合并字幕",
        "dialogue_stage_done": "完成",
        "build_dialogue_index_progress": "字幕 {current}/{total}：{stage}",
    }


def test_ocr_progress_reports_frame_counts():
    host = _Host()
    text = host._format_understanding_ocr_progress("dialogue_index|1|1|subtitle_ocr|12|400")
    assert text == "识别字幕 12/400"


def test_ocr_progress_keeps_video_counter_for_a_batch():
    host = _Host()
    text = host._format_understanding_ocr_progress("dialogue_index|2|3|subtitle_merge")
    assert text == "字幕 2/3：合并字幕"


def test_ocr_progress_ignores_raw_video_id_token():
    host = _Host()
    text = host._format_understanding_ocr_progress("dialogue_index|1|1|video-abc")
    assert text == "正在识别硬字幕…"
