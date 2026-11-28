import pytest
from unittest.mock import patch

from src.services import recap_prompts as prompts
from src.services.recap_captions import recap_vo_coverage_ratio
from src.services.recap_runtime import resolve_recap_caption_language
from src.services.recap_vo_pipeline import polish_recap_vo, fit_recap_captions_to_tts
from src.services.understanding_resource_service import (
    normalize_caption_language, resolve_remote_vlm_caption_language,
    get_tag_prompt_for_language, get_motion_prompt_for_language,
)


@pytest.mark.parametrize("raw,expected", [
    ("vi", "vi"), ("vi-VN", "vi"), ("VI_vn", "vi"),
    ("Vietnamese", "vi"), ("Tiếng Việt", "vi"),
    ("en-US", "en"), ("EN_gb", "en"), ("zh-CN", "zh"),
    ("zh-TW", "zh"), ("en", "en"), ("zh", "zh"),
])
def test_language_codes_and_aliases(raw, expected):
    assert normalize_caption_language(raw) == expected
    assert resolve_remote_vlm_caption_language({"caption_language": raw}) == expected
    assert resolve_recap_caption_language({"understanding": {"remote_vlm": {"caption_language": raw}}}) == expected


def test_unknown_language_retains_explicit_fallback():
    assert normalize_caption_language("fr") == "zh"
    assert normalize_caption_language("fr", default="en-US") == "en"
    assert normalize_caption_language("fr", default="vi-VN") == "vi"


@pytest.mark.parametrize("prompt", [
    "Describe this video frame in Vietnamese.", "Mô tả cảnh bằng tiếng Việt.",
    get_tag_prompt_for_language("vi"), get_motion_prompt_for_language("vi"),
])
def test_vietnamese_legacy_prompt_inference(prompt):
    assert resolve_remote_vlm_caption_language({"prompt": prompt}) == "vi"


@pytest.mark.parametrize("name", [
    "default_recap_plan_prompt", "default_recap_plan_act_prompt",
    "default_recap_plan_structure_prompt", "default_recap_match_prompt",
    "default_recap_vo_draft_prompt", "default_recap_caption_prompt",
    "default_recap_polish_prompt", "default_recap_plan_head_prompt",
    "default_recap_plan_tail_prompt", "default_recap_plan_gap_prompt",
    "default_recap_gap_prompt",
])
def test_every_recap_stage_supports_vietnamese(name):
    function = getattr(prompts, name)
    prompt = function("vi-VN")
    assert "tiếng Việt" in prompt
    assert "English" not in prompt
    assert prompt != function("zh")
    assert function("en-US") == function("en")


@pytest.mark.parametrize("text", ["", "Hi.", "Xin chào.", "好。", "!!!", "12345"])
def test_short_or_empty_draft_is_not_covered(text):
    assert recap_vo_coverage_ratio([{"duration": 8, "beat_id": 1, "vo": text}]) == 0


@pytest.mark.parametrize("text", [
    "Mai đặt chiếc chìa khóa lên bàn rồi rời khỏi căn phòng để tìm người bạn.",
    "Mai places the key on the table and leaves the room to find her friend.",
    "少年走进店里递出支票，店长当场拒收，双方因此发生争执。",
])
def test_substantial_vi_en_zh_narration_is_covered(text):
    assert recap_vo_coverage_ratio([{"duration": 5, "beat_id": 1, "vo": text}]) == 1


def test_same_text_must_cover_whole_spanning_beat():
    text = "Mai puts the key down and leaves the room."
    head = {"duration": 4, "beat_id": 1, "vo": text, "vo_draft": text}
    assert recap_vo_coverage_ratio([head]) == 1
    assert recap_vo_coverage_ratio([head, {"duration": 12, "beat_id": 1, "vo": ""}]) == 0


def test_draft_and_final_are_not_double_counted():
    assert recap_vo_coverage_ratio([{"duration": 5, "vo": "Mai leaves now.", "vo_draft": "Mai leaves now."}]) == 0


@pytest.mark.parametrize("function", [polish_recap_vo, fit_recap_captions_to_tts])
def test_one_word_draft_does_not_skip_editor(function):
    clips = [{"duration": 5, "beat_id": 1, "vo": "Hi.", "src_in": 0, "src_out": 5}]
    with patch("src.services.recap_service.call_remote_llm", return_value='{"captions":[]}') as call:
        function(clips, config={})
    call.assert_called_once()
