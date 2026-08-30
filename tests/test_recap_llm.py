from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.media.fcpxml import fps_fraction, layout_clips_on_timeline, merge_vo_cues, write_fcpxml, write_srt
from src.services.llm_settings import (
    finalize_remote_llm_settings,
    migrate_remote_llm_model,
    pick_available_text_llm_model,
)
from src.services.recap_service import (
    apply_caption_cues,
    apply_gap_fills,
    allocate_beat_budgets,
    apply_recap_duration,
    beat_evidence_score,
    beats_cover_ending,
    beats_cover_opening,
    story_beat_gaps,
    compact_motion_chunks,
    compact_ocr_cues,
    people_from_dialogue_speakers,
    export_saved_recap_fcpxml,
    fit_recap_captions_to_tts,
    load_recap_cuts,
    load_recap_beats,
    write_recap_beats_file,
    generate_recap_timeline,
    recap_cuts_path_for_video,
    recap_beats_path_for_video,
    drop_op_ed_beats,
    ensure_recap_dialogue_cues,
    looks_like_op_ed_text,
    missing_match_beats,
    normalize_caption_cues,
    normalize_cut_list,
    pack_captions_for_tts,
    _join_vo,
    pad_cuts_for_tts,
    restore_recap_vo_text,
    stretch_recap_clips_for_vo,
    parse_caption_cues,
    parse_cut_list,
    parse_story_beats,
    parse_story_plan,
    merge_story_people,
    recap_caption_user_prompt,
    recap_gap_user_prompt,
    recap_gap_clip_indices,
    parse_gap_fills,
    recap_cuts_duration,
    recap_dialogue_status,
    recap_story_window,
    recap_user_prompt,
    recap_plan_user_prompt,
    resolve_recap_system_prompt,
    resolve_recap_prompt,
    normalize_recap_start_from,
    sample_timeline_items,
    split_beats_for_match,
    trim_vo_to_budget,
    tts_char_budget,
    vo_needed_sec,
    vo_sec,
    RECAP_GAP_SYSTEM,
    RECAP_PLAN_SYSTEM,
    RECAP_SYSTEM,
    TTS_SPEED,
)
from src.services.understanding_resource_service import normalize_understanding_config


class LlmSettingsTests(unittest.TestCase):
    def test_deepseek_preset_fills_url(self):
        settings = finalize_remote_llm_settings(
            {"provider_mode": "cloud", "provider_preset": "deepseek", "api_keys": {"deepseek": "sk-test"}}
        )
        self.assertEqual(settings["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(settings["model"], "deepseek-v4-flash")
        self.assertEqual(settings["api_keys"]["deepseek"], "sk-test")

    def test_migrates_retired_deepseek_chat(self):
        settings = finalize_remote_llm_settings(
            {"provider_mode": "cloud", "provider_preset": "deepseek", "model": "deepseek-chat"}
        )
        self.assertEqual(settings["model"], "deepseek-v4-flash")
        self.assertEqual(migrate_remote_llm_model("deepseek-reasoner"), "deepseek-v4-flash")

    def test_keeps_deepseek_pro_override(self):
        settings = finalize_remote_llm_settings(
            {"provider_mode": "cloud", "provider_preset": "deepseek", "model": "deepseek-v4-pro"}
        )
        self.assertEqual(settings["model"], "deepseek-v4-pro")

    def test_picks_text_model_not_vision(self):
        chosen = pick_available_text_llm_model(
            "deepseek-chat",
            ["deepseek-v4-flash-vision-exp", "deepseek-v4-pro", "deepseek-v4-flash"],
        )
        self.assertEqual(chosen, "deepseek-v4-flash")

    def test_custom_keeps_url(self):
        settings = finalize_remote_llm_settings(
            {
                "provider_mode": "cloud",
                "provider_preset": "custom",
                "base_url": "https://example.com/v1",
                "model": "my-model",
            }
        )
        self.assertEqual(settings["base_url"], "https://example.com/v1")
        self.assertEqual(settings["model"], "my-model")


class RecapPackTests(unittest.TestCase):
    def test_compact_motion_strips_json_tags(self):
        evidence = {
            "chunks": [
                {
                    "chunk_index": 2,
                    "start_sec": 4.0,
                    "end_sec": 8.0,
                    "tags": ["对话", "这是一句特别长不应该当标签的台词内容"],
                    "evidence": {
                        "vision": {
                            "image_caption": {
                                "text": "考官微笑特写。\n{\"tags\":[\"对话\"]}"
                            }
                        }
                    },
                }
            ]
        }
        chunks = compact_motion_chunks(evidence)
        self.assertEqual(chunks[0]["i"], 2)
        self.assertEqual(chunks[0]["t"], [4.0, 8.0])
        self.assertEqual(chunks[0]["dur"], 4.0)
        self.assertEqual(chunks[0]["cap"], "考官微笑特写。")
        self.assertEqual(chunks[0]["tags"], ["对话"])

    def test_normalize_trims_long_clip_to_vo(self):
        pack = {
            "duration_sec": 200.0,
            "chunks": [{"i": 8, "t": [107.0, 124.0], "tags": [], "cap": ""}],
        }
        clips = normalize_cut_list(
            {
                "clips": [
                    {
                        "name": "不咏唱",
                        "chunk_index": 8,
                        "src_in": 107.0,
                        "src_out": 124.0,
                        "vo": "那家伙不咏唱也能放魔法吗？",
                    }
                ]
            },
            pack,
        )
        self.assertEqual(len(clips), 1)
        self.assertLessEqual(clips[0]["src_out"] - clips[0]["src_in"], 12.0)
        self.assertGreater(clips[0]["src_in"], 107.0)
        self.assertAlmostEqual(clips[0]["duration"], clips[0]["src_out"] - clips[0]["src_in"], places=3)

    def test_normalize_accepts_duration_field(self):
        pack = {
            "duration_sec": 20.0,
            "chunks": [{"i": 0, "t": [0.0, 12.0], "tags": [], "cap": ""}],
        }
        clips = normalize_cut_list(
            {
                "clips": [
                    {
                        "name": "01",
                        "chunk_index": 0,
                        "src_in": 1.0,
                        "duration": 6.5,
                        "vo": "开场。",
                        "reason": "建立场面",
                    }
                ]
            },
            pack,
        )
        self.assertAlmostEqual(clips[0]["src_out"], 7.5, places=2)
        self.assertAlmostEqual(clips[0]["duration"], 6.5, places=2)

    def test_parse_cut_list_from_fenced_json(self):
        pack = {"duration_sec": 20.0, "chunks": [{"i": 0, "t": [0.0, 8.0], "tags": [], "cap": ""}]}
        raw = """```json
{"title":"试水","clips":[{"name":"01","chunk_index":0,"src_in":0.2,"src_out":4.0,"vo":"开场。"}]}
```"""
        title, clips = parse_cut_list(raw, pack)
        self.assertEqual(title, "试水")
        self.assertEqual(clips[0]["vo"], "开场。")

    def test_parse_cut_list_repairs_missing_commas(self):
        pack = {"duration_sec": 20.0, "chunks": [{"i": 0, "t": [0.0, 8.0], "tags": [], "cap": ""}]}
        raw = """{"title":"试水","clips":[
{"name":"01","chunk_index":0,"src_in":0.2,"src_out":3.0,"vo":"第一句。"}
{"name":"02","chunk_index":0,"src_in":3.0,"src_out":6.0,"vo":"第二句。"}
]}"""
        title, clips = parse_cut_list(raw, pack)
        self.assertEqual(title, "试水")
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[1]["vo"], "第二句。")

    def test_parse_cut_list_salvages_truncated_tail(self):
        pack = {"duration_sec": 20.0, "chunks": [{"i": 0, "t": [0.0, 8.0], "tags": [], "cap": ""}]}
        raw = '{"title":"试水","clips":[{"name":"01","chunk_index":0,"src_in":0.2,"src_out":4.0,"vo":"开场。"},{"name":"02","chunk_index":0,"src_in":4.0,"src_out":7.0,"vo":"下一'
        title, clips = parse_cut_list(raw, pack)
        self.assertEqual(title, "试水")
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["vo"], "开场。")

    def test_vo_sec(self):
        self.assertAlmostEqual(vo_sec("一二三四五", chars_per_sec=5.0), 1.0)
        self.assertAlmostEqual(vo_sec("一二三四五"), round(5.0 / (5.0 * TTS_SPEED), 2))
        self.assertAlmostEqual(TTS_SPEED, 1.35)

    def test_tts_budget_keeps_more_at_1_35(self):
        vo = "一二三四五" * 5 + "一二三"  # 28 counted chars
        self.assertEqual(trim_vo_to_budget(vo, tts_char_budget(6.0)), vo)
        trimmed = trim_vo_to_budget(vo, tts_char_budget(6.0, speed=1.0))
        self.assertLess(len(trimmed), len(vo))

    def test_pack_captions_span_empty_follow_shots(self):
        vo = "一二三四五" * 8  # longer than the first 4s shot
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": vo, "beat_id": 1},
            {"tl_in": 4.0, "tl_out": 9.0, "vo": "", "beat_id": 1},
            {"tl_in": 9.0, "tl_out": 13.0, "vo": "全场瞬间安静下来。", "beat_id": 2},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["to"], 2)
        self.assertAlmostEqual(captions[0]["tl_out"], 9.0)
        self.assertEqual(captions[1]["from"], 3)
        self.assertAlmostEqual(captions[1]["tl_in"], 9.0)

    def test_pack_captions_skips_full_shot_empty_follow(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "监考官宣布考试开始。", "beat_id": 1},
            {"tl_in": 6.0, "tl_out": 11.0, "vo": "", "beat_id": 1},
            {"tl_in": 11.0, "tl_out": 15.0, "vo": "全场瞬间安静下来。", "beat_id": 2},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["to"], 1)
        self.assertAlmostEqual(captions[0]["tl_out"], 6.0)
        self.assertEqual(captions[1]["from"], 3)
        self.assertAlmostEqual(captions[1]["tl_in"], 11.0)
        self.assertLessEqual(vo_needed_sec("监考官宣布考试开始。"), 6.0 * 0.8)

    def test_pack_captions_keeps_distinct_vo_shots(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 5.0, "vo": "监考官宣布考试开始。", "beat_id": 1},
            {"tl_in": 5.0, "tl_out": 10.0, "vo": "全场瞬间安静下来。", "beat_id": 1},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["text"], "监考官宣布考试开始。")
        self.assertEqual(captions[0]["to"], 1)
        self.assertEqual(captions[1]["text"], "全场瞬间安静下来。")
        self.assertEqual(captions[1]["from"], 2)

    def test_pack_captions_does_not_spill_into_next_beat(self):
        vo = "一二三四五" * 8  # longer than the first 4s shot
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": vo, "beat_id": 1},
            {"tl_in": 4.0, "tl_out": 8.0, "vo": "下一拍自己的解说。", "beat_id": 2},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[0]["to"], 1)
        self.assertLessEqual(captions[0]["tl_out"], 4.01)
        self.assertEqual(captions[1]["from"], 2)
        self.assertAlmostEqual(captions[1]["tl_in"], 4.0)
        self.assertGreater(vo_needed_sec(vo), 4.0)

    def test_pad_cuts_does_not_expand_into_op(self):
        vo = "一二三四五" * 8
        pack = {
            "duration_sec": 400.0,
            "chunks": [
                {"i": 0, "t": [0.0, 90.0], "skip": "op_ed", "cap": "片头曲标题动画", "tags": ["片头曲"]},
                {"i": 1, "t": [90.0, 200.0], "skip": "", "cap": "教室上课", "tags": []},
            ],
        }
        beats = [{"id": 1, "budget_sec": 20.0, "t": [100.0, 160.0]}]
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "chunk_index": 1,
                "src_in": 100.0,
                "src_out": 104.0,
                "vo": vo,
            }
        ]
        out = pad_cuts_for_tts(cuts, pack, beats)
        for clip in out:
            self.assertGreaterEqual(float(clip["src_in"]), 90.0)
            self.assertGreaterEqual(float(clip["src_in"]), 99.9)

    def test_pad_cuts_grows_or_bridges_short_picture(self):
        vo = "一二三四五" * 8
        pack = {
            "duration_sec": 80.0,
            "chunks": [{"i": 0, "t": [10.0, 50.0], "skip": ""}],
        }
        beats = [{"id": 1, "budget_sec": 20.0, "t": [10.0, 50.0]}]
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 20.0,
                "src_out": 24.0,
                "vo": vo,
            }
        ]
        out = pad_cuts_for_tts(cuts, pack, beats)
        self.assertGreaterEqual(recap_cuts_duration(out), vo_needed_sec(vo) - 0.35)

    def test_pad_cuts_can_grow_past_twelve_seconds(self):
        vo = "一二三四五" * 20  # ~16.5s at 1.35x
        pack = {
            "duration_sec": 80.0,
            "chunks": [{"i": 0, "t": [10.0, 70.0], "skip": ""}],
        }
        beats = [{"id": 1, "budget_sec": 36.0, "t": [10.0, 70.0]}]
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 20.0,
                "src_out": 24.0,
                "vo": vo,
            }
        ]
        out = pad_cuts_for_tts(cuts, pack, beats)
        self.assertGreater(recap_cuts_duration(out), 12.0)
        self.assertGreaterEqual(recap_cuts_duration(out), vo_needed_sec(vo) - 0.35)

    def test_pack_captions_keeps_full_line(self):
        vo = "监考官宣布考试开始。" + "全场瞬间安静下来。" * 3
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": vo, "beat_id": 1},
            {"tl_in": 4.0, "tl_out": 8.0, "vo": "下一拍。", "beat_id": 2},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(captions[0]["text"], vo)

    def test_pack_captions_does_not_repeat_same_line(self):
        line = "监考官宣布考试开始。"
        clips = [
            {"tl_in": 0.0, "tl_out": 5.0, "vo": line, "beat_id": 1},
            {"tl_in": 5.0, "tl_out": 10.0, "vo": line, "beat_id": 1},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0]["text"], line)
        self.assertEqual(captions[0]["from"], 1)
        self.assertEqual(captions[0]["to"], 2)
        self.assertEqual(_join_vo(line, line), line)

    def test_stretch_prefers_untrimmed_draft(self):
        clips = [
            {
                "src_in": 10.0,
                "src_out": 14.0,
                "vo": "砍过的半句",
                "vo_draft": "一二三四五" * 10,
            }
        ]
        restored = restore_recap_vo_text(clips)
        self.assertEqual(restored[0]["vo"], "一二三四五" * 10)
        stretched = stretch_recap_clips_for_vo(clips, media_duration=80.0)
        self.assertGreaterEqual(
            float(stretched[0]["src_out"]) - float(stretched[0]["src_in"]),
            vo_needed_sec("一二三四五" * 10) - 0.35,
        )

    def test_apply_and_parse_caption_cues(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": "草稿一", "name": "01"},
            {"tl_in": 4.0, "tl_out": 8.0, "vo": "", "name": "02"},
        ]
        parsed = parse_caption_cues('{"captions":[{"text":"跨镜旁白","from":1,"to":2}]}', clips)
        self.assertEqual(parsed[0]["to"], 2)
        stamped = apply_caption_cues(clips, parsed)
        self.assertEqual(stamped[0]["vo"], "跨镜旁白")
        self.assertEqual(stamped[1]["vo"], "")
        self.assertEqual(stamped[0]["vo_draft"], "草稿一")
        snapped = normalize_caption_cues([{"text": "时间对齐", "tl_in": 0.2, "tl_out": 7.8}], clips)
        self.assertEqual(snapped[0]["from"], 1)
        self.assertEqual(snapped[0]["to"], 2)

    def test_gap_clips_skip_covered_and_bridges(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "name": "01", "reason": "开场"},
            {"tl_in": 6.0, "tl_out": 9.0, "vo": "", "name": "过渡", "reason": "过渡"},
            {"tl_in": 9.0, "tl_out": 13.0, "vo": "", "name": "03", "reason": "关键动作"},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(recap_gap_clip_indices(clips, captions), [2])

    def test_parse_and_apply_gap_fills(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "vo_draft": "开场。"},
            {"tl_in": 6.0, "tl_out": 10.0, "vo": "", "reason": "关键动作"},
        ]
        fills = parse_gap_fills(
            '{"fills":[{"i":2,"text":"他直接出手了。","skip":false}]}',
            clips,
            allowed={1},
        )
        self.assertEqual(fills, [{"index": 1, "text": "他直接出手了。"}])
        out = apply_gap_fills(clips, fills)
        self.assertEqual(out[0]["vo"], "开场。")
        self.assertEqual(out[1]["vo"], "他直接出手了。")
        self.assertEqual(out[1]["vo_draft"], "他直接出手了。")

    def test_parse_gap_fills_skips_existing_and_duplicate(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "监考官宣布考试开始。"},
            {"tl_in": 6.0, "tl_out": 10.0, "vo": ""},
        ]
        fills = parse_gap_fills(
            '{"fills":[{"i":1,"text":"不要覆盖。"},{"i":2,"text":"监考官宣布考试开始。"}]}',
            clips,
            allowed={0, 1},
        )
        self.assertEqual(fills, [])

    def test_fit_recap_fills_gaps_via_llm(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "beat_id": 1, "reason": "开场"},
            {"tl_in": 6.0, "tl_out": 10.0, "vo": "", "beat_id": 1, "reason": "关键动作"},
        ]
        with patch(
            "src.services.recap_service.call_remote_llm",
            return_value='{"fills":[{"i":2,"text":"他出手了。"}]}',
        ) as mock_llm:
            out = fit_recap_captions_to_tts(clips)
        mock_llm.assert_called_once()
        self.assertEqual(out[1]["vo"], "他出手了。")

    def test_fit_recap_skips_llm_when_no_gaps(self):
        clips = [{"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "beat_id": 1}]
        with patch("src.services.recap_service.call_remote_llm") as mock_llm:
            out = fit_recap_captions_to_tts(clips)
        mock_llm.assert_not_called()
        self.assertEqual(out[0]["vo"], "开场。")

    def test_recap_prompt_asks_for_narration_not_translation(self):
        self.assertIn("第三人称", RECAP_SYSTEM)
        self.assertIn("budget_sec", RECAP_SYSTEM)
        self.assertIn("reason", RECAP_SYSTEM)
        self.assertIn("不要为了碎而碎", RECAP_SYSTEM)
        self.assertIn("不写剪辑表", RECAP_PLAN_SYSTEM)
        self.assertIn("宁多勿跳", RECAP_PLAN_SYSTEM)
        self.assertIn("14–20", RECAP_PLAN_SYSTEM)
        self.assertIn("5 分半", RECAP_PLAN_SYSTEM)
        self.assertIn("设定/空间", RECAP_PLAN_SYSTEM)
        self.assertIn("角色侧面", RECAP_PLAN_SYSTEM)
        self.assertIn("换场", RECAP_PLAN_SYSTEM)
        self.assertIn("importance", RECAP_PLAN_SYSTEM)
        self.assertIn("片尾", RECAP_PLAN_SYSTEM)
        self.assertIn("收尾", RECAP_SYSTEM)
        self.assertIn("片头曲", RECAP_PLAN_SYSTEM)
        self.assertIn("叙事真相", RECAP_SYSTEM)
        self.assertIn("2–4 句", RECAP_SYSTEM)
        self.assertIn("新的视觉信息", RECAP_SYSTEM)
        self.assertIn("反应或设定", RECAP_SYSTEM)
        self.assertIn("不要单独一刀", RECAP_SYSTEM)
        self.assertIn("duration", RECAP_SYSTEM)
        self.assertIn("1.35", RECAP_SYSTEM)
        self.assertIn("同一个「他」", RECAP_SYSTEM)
        self.assertIn("禁止男主", RECAP_SYSTEM)
        self.assertIn("稳定称呼", RECAP_SYSTEM)
        self.assertIn("people", RECAP_PLAN_SYSTEM)
        self.assertIn("同一个「他」", RECAP_PLAN_SYSTEM)
        self.assertIn("禁止男主", RECAP_PLAN_SYSTEM)
        self.assertIn("speaker", RECAP_PLAN_SYSTEM)
        self.assertIn("asr[].speaker", recap_plan_user_prompt({"duration_sec": 100.0, "chunks": [], "ocr": []}))
        self.assertIn("同一个「他」", RECAP_GAP_SYSTEM)
        self.assertIn("禁止男主", RECAP_GAP_SYSTEM)
        for body in (RECAP_PLAN_SYSTEM, RECAP_SYSTEM, RECAP_GAP_SYSTEM):
            self.assertNotIn("考号", body)
            self.assertNotIn("特别待遇", body)
            self.assertNotIn("监考", body)
        plan_prompt = recap_plan_user_prompt({"duration_sec": 100.0, "chunks": [], "ocr": []})
        self.assertNotIn("考号", plan_prompt)
        self.assertNotIn("考试", plan_prompt)
        self.assertIn("1.35", RECAP_GAP_SYSTEM)
        self.assertIn("查漏", RECAP_GAP_SYSTEM)
        self.assertIn("fills", RECAP_GAP_SYSTEM)
        cap_prompt = recap_caption_user_prompt(
            [{"name": "01", "tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "beat_id": 1, "reason": "开场"}]
        )
        self.assertIn("1.35", cap_prompt)
        self.assertIn("seed", cap_prompt)
        gap_prompt = recap_gap_user_prompt(
            [
                {"name": "01", "tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "beat_id": 1, "reason": "开场"},
                {"name": "02", "tl_in": 6.0, "tl_out": 10.0, "vo": "", "beat_id": 1, "reason": "关键动作"},
            ],
            [{"text": "开场。", "from": 1, "to": 1}],
            [1],
        )
        self.assertIn("gaps", gap_prompt)
        self.assertIn("fills", RECAP_GAP_SYSTEM)
        prompt = recap_user_prompt(
            {
                "duration_sec": 100.0,
                "chunks": [],
                "ocr": [],
                "people": [{"id": "p1", "label": "红衣女人", "look": "长发红裙"}],
            },
            [{"id": 1, "event": "四连魔法", "budget_sec": 18.0, "shots": 4}],
        )
        self.assertIn("budget_sec", prompt)
        self.assertIn("四连魔法", prompt)
        self.assertIn("5 分半", prompt)
        self.assertIn("片头曲", prompt)
        self.assertIn("2–4 句", prompt)
        self.assertIn("叙事真相", prompt)
        self.assertIn("people", prompt)
        self.assertIn("同一个他", prompt)
        self.assertIn("speaker", prompt)
        self.assertIn("禁止男主", prompt)
        self.assertIn("红衣女人", prompt)
        self.assertNotIn("考号", prompt)
        self.assertIn("高权重才加", prompt)

    def test_apply_recap_duration_fills_beat_budget(self):
        pack = {
            "duration_sec": 80.0,
            "chunks": [{"i": 0, "t": [10.0, 50.0], "skip": ""}],
        }
        beats = [{"id": 1, "budget_sec": 20.0, "t": [10.0, 50.0]}]
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 20.0,
                "src_out": 24.0,
                "vo": "他直接出手了，这一下把全场都打懵了。",
            },
            {
                "name": "02",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 30.0,
                "src_out": 33.0,
                "vo": "",
            },
        ]
        out = apply_recap_duration(cuts, pack, beats, target_sec=20.0, min_sec=18.0)
        self.assertGreaterEqual(recap_cuts_duration(out), 18.0)

    def test_apply_recap_duration_trims_over_budget(self):
        pack = {
            "duration_sec": 80.0,
            "chunks": [{"i": 0, "t": [10.0, 70.0], "skip": ""}],
        }
        beats = [{"id": 1, "budget_sec": 12.0, "t": [10.0, 70.0]}]
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 12.0,
                "src_out": 20.0,
                "vo": "第一场考试开始。",
            },
            {
                "name": "02",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 22.0,
                "src_out": 34.0,
                "vo": "",
            },
            {
                "name": "03",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 36.0,
                "src_out": 46.0,
                "vo": "",
            },
        ]
        out = apply_recap_duration(cuts, pack, beats)
        self.assertLessEqual(recap_cuts_duration(out), 13.0)
        self.assertTrue(any(str(clip.get("vo") or "").strip() for clip in out))

    def test_parse_story_beats(self):
        raw = """```json
{"title":"入学篇","people":[{"id":"p1","label":"黑发少年","look":"短发黑衣"},{"id":"p2","label":"监考官"}],"beats":[
  {"id":1,"event":"监考官宣布开考","importance":0.95,"needed_visual":"讲台","t":[140.0,151.0]},
  {"id":2,"event":"黑发少年找不到考号","importance":0.85,"needed_visual":"座位","t":[160.0,175.0]}
]}
```"""
        title, beats = parse_story_beats(raw)
        self.assertEqual(title, "入学篇")
        self.assertEqual(len(beats), 2)
        self.assertEqual(beats[0]["event"], "监考官宣布开考")
        self.assertAlmostEqual(beats[0]["importance"], 0.95)
        plan_title, plan_beats, people = parse_story_plan(raw)
        self.assertEqual(plan_title, title)
        self.assertEqual(plan_beats[1]["event"], "黑发少年找不到考号")
        self.assertEqual([item["label"] for item in people], ["黑发少年", "监考官"])
        merged = merge_story_people(people, [{"label": "黑发少年"}, {"label": "戴眼镜的女生"}])
        self.assertEqual([item["label"] for item in merged], ["黑发少年", "监考官", "戴眼镜的女生"])

    def test_allocate_beat_budgets_prefers_plot_weight_not_source_duration(self):
        fillers = [
            {
                "id": index,
                "event": f"过渡{index}",
                "importance": 0.45,
                "needed_visual": "过场",
                "t": [float(index * 10), float(index * 10 + 6)],
            }
            for index in range(3, 11)
        ]
        beats = [
            {"id": 1, "event": "四连魔法", "importance": 0.95, "needed_visual": "魔法阵", "t": [140.0, 151.0]},
            {"id": 2, "event": "走廊走路", "importance": 0.2, "needed_visual": "走路", "t": [200.0, 280.0]},
            *fillers,
        ]
        chunks = [
            {"i": 1, "t": [140.0, 151.0], "dur": 11.0, "cap": "四连"},
            {"i": 2, "t": [200.0, 280.0], "dur": 80.0, "cap": "走路"},
        ]
        allocated = allocate_beat_budgets(beats, chunks=chunks, target_sec=180.0)
        four = next(item for item in allocated if item["event"] == "四连魔法")
        walk = next(item for item in allocated if item["event"] == "走廊走路")
        self.assertGreater(four["budget_sec"], walk["budget_sec"])
        self.assertGreaterEqual(four["budget_sec"], 16.0)
        self.assertAlmostEqual(sum(item["budget_sec"] for item in allocated), 180.0, delta=1.5)
        self.assertEqual(beat_evidence_score(80.0), beat_evidence_score(12.0))

    def test_allocate_keeps_ending_beat_even_if_low_weight(self):
        early = [
            {
                "id": index,
                "event": f"前段{index}",
                "importance": 0.9,
                "needed_visual": "推进",
                "t": [float(index * 8), float(index * 8 + 5)],
            }
            for index in range(1, 13)
        ]
        ending = {
            "id": 99,
            "event": "结局对决",
            "importance": 0.16,
            "needed_visual": "决战",
            "t": [900.0, 940.0],
        }
        allocated = allocate_beat_budgets(early + [ending], chunks=[], target_sec=180.0)
        events = [item["event"] for item in allocated]
        self.assertIn("结局对决", events)
        self.assertEqual(len(allocated), 13)

    def test_sample_timeline_keeps_tail(self):
        items = [{"i": index} for index in range(40)]
        picked = sample_timeline_items(items, 10)
        self.assertEqual(len(picked), 10)
        self.assertEqual(picked[0]["i"], 0)
        self.assertEqual(picked[-1]["i"], 39)
        self.assertTrue(any(item["i"] > 20 for item in picked))

    def test_split_and_missing_beats(self):
        beats = [{"id": index, "event": str(index), "t": [float(index * 10), float(index * 10 + 4)]} for index in range(1, 13)]
        waves = split_beats_for_match(beats)
        self.assertEqual(len(waves), 2)
        self.assertEqual(len(waves[0]), 7)
        self.assertEqual(waves[-1][-1]["id"], 12)
        cuts = [{"beat_id": 1, "src_in": 10.0, "src_out": 14.0}]
        missing = missing_match_beats(beats, cuts)
        self.assertTrue(any(item["id"] == 12 for item in missing))
        self.assertFalse(any(item["id"] == 1 for item in missing))
        self.assertFalse(beats_cover_ending([{"t": [10.0, 40.0]}], 200.0))
        self.assertTrue(beats_cover_ending([{"t": [10.0, 40.0]}, {"t": [160.0, 190.0]}], 200.0))
        self.assertTrue(beats_cover_opening([{"t": [8.0, 40.0], "event": "冷开场"}], 1440.0))
        self.assertFalse(beats_cover_opening([{"t": [400.0, 440.0], "event": "中段"}], 1440.0))

    def test_story_beat_gaps_finds_middle_hole(self):
        beats = [
            {"id": 1, "event": "开场", "t": [10.0, 40.0]},
            {"id": 2, "event": "收尾", "t": [1200.0, 1280.0]},
        ]
        gaps = story_beat_gaps(beats, 1440.0)
        self.assertTrue(gaps)
        self.assertGreaterEqual(gaps[0][1] - gaps[0][0], 100.0)
        self.assertLess(gaps[0][0], 50.0)
        packed = [
            {"id": 1, "event": "开场", "t": [0.0, 80.0]},
            {"id": 2, "event": "中段", "t": [200.0, 280.0]},
            {"id": 3, "event": "收尾", "t": [1200.0, 1300.0]},
        ]
        still = story_beat_gaps(packed, 1440.0)
        self.assertTrue(any(lo < 200 and hi > 80 for lo, hi in still))

    def test_allocate_keeps_high_importance_middle_without_evidence(self):
        fillers = [
            {
                "id": index,
                "event": f"注水{index}",
                "importance": 0.45,
                "needed_visual": "过场",
                "t": [float(index * 8), float(index * 8 + 6)],
            }
            for index in range(1, 17)
        ]
        chunks = [
            {"i": index, "t": [float(index * 8), float(index * 8 + 6)], "dur": 6.0, "cap": "过场"}
            for index in range(1, 17)
        ]
        chunks.append({"i": 90, "t": [900.0, 920.0], "dur": 20.0, "cap": "决战"})
        middle = {
            "id": 99,
            "event": "关键对质",
            "importance": 0.85,
            "needed_visual": "对质",
            "t": [500.0, 530.0],
        }
        ending = {
            "id": 100,
            "event": "结局",
            "importance": 0.9,
            "needed_visual": "决战",
            "t": [900.0, 920.0],
        }
        allocated = allocate_beat_budgets(fillers + [middle, ending], chunks=chunks, target_sec=180.0)
        events = [item["event"] for item in allocated]
        self.assertIn("关键对质", events)
        self.assertIn("结局", events)
        self.assertEqual(len(allocated), 18)

    def test_allocate_keeps_setting_and_character_beats(self):
        fillers = [
            {
                "id": index,
                "event": f"对质{index}",
                "importance": 0.55,
                "needed_visual": "冲突",
                "t": [float(index * 8), float(index * 8 + 6)],
            }
            for index in range(1, 14)
        ]
        chunks = [
            {"i": index, "t": [float(index * 8), float(index * 8 + 6)], "dur": 6.0, "cap": "冲突"}
            for index in range(1, 14)
        ]
        setting = {
            "id": 80,
            "event": "考场规则设定",
            "importance": 0.3,
            "needed_visual": "教室布置和规则说明",
            "t": [200.0, 220.0],
        }
        character = {
            "id": 81,
            "event": "角色侧面：监考官的态度",
            "importance": 0.28,
            "needed_visual": "表情习惯",
            "t": [400.0, 412.0],
        }
        allocated = allocate_beat_budgets(fillers + [setting, character], chunks=chunks, target_sec=180.0)
        events = [item["event"] for item in allocated]
        self.assertEqual(len(allocated), 15)
        self.assertTrue(any("设定" in event for event in events))
        self.assertTrue(any("角色侧面" in event for event in events))

    def test_allocate_keeps_every_planned_beat(self):
        beats = [
            {
                "id": index,
                "event": f"节拍{index}",
                "importance": 0.4 if index % 3 else 0.8,
                "needed_visual": "场面",
                "t": [float(index * 40), float(index * 40 + 12)],
            }
            for index in range(1, 23)
        ]
        allocated = allocate_beat_budgets(beats, target_sec=330.0)
        self.assertEqual(len(allocated), 22)
        self.assertEqual([item["id"] for item in allocated], list(range(1, 23)))
        self.assertAlmostEqual(sum(item["budget_sec"] for item in allocated), 330.0, delta=2.0)
        self.assertLessEqual(max(item["budget_sec"] for item in allocated), 24.0)
        self.assertGreaterEqual(min(item["budget_sec"] for item in allocated), 6.0)

    def test_skips_op_ed_not_story_opening(self):
        self.assertEqual(recap_story_window(200.0), (0.0, 200.0))
        start, end = recap_story_window(1440.0)
        self.assertEqual(start, 0.0)
        self.assertLessEqual(end, 1360.0)
        self.assertGreaterEqual(end, 1300.0)
        self.assertTrue(looks_like_op_ed_text("片尾曲，演职员表滚动"))
        self.assertFalse(looks_like_op_ed_text("教室里开始点名"))
        beats = drop_op_ed_beats(
            [
                {"id": 1, "event": "冷开场打架", "needed_visual": "对打", "t": [8.0, 40.0]},
                {"id": 2, "event": "片头曲", "needed_visual": "歌词", "t": [50.0, 140.0]},
                {"id": 3, "event": "片尾曲", "needed_visual": "演职员表", "t": [1360.0, 1440.0]},
                {"id": 4, "event": "决战收束", "needed_visual": "对决", "t": [1200.0, 1280.0]},
            ],
            1440.0,
        )
        events = [item["event"] for item in beats]
        self.assertIn("冷开场打架", events)
        self.assertIn("决战收束", events)
        self.assertNotIn("片头曲", events)
        self.assertNotIn("片尾曲", events)

    def test_parse_cut_list_keeps_beat_id(self):
        pack = {"duration_sec": 20.0, "chunks": [{"i": 0, "t": [0.0, 8.0], "tags": [], "cap": ""}]}
        raw = '{"title":"试水","clips":[{"name":"01","beat_id":3,"chunk_index":0,"src_in":0.2,"src_out":4.0,"vo":"开场。","reason":"建立场景"}]}'
        _title, clips = parse_cut_list(raw, pack)
        self.assertEqual(clips[0]["beat_id"], 3)
        self.assertEqual(clips[0]["reason"], "建立场景")
        self.assertAlmostEqual(clips[0]["duration"], clips[0]["src_out"] - clips[0]["src_in"], places=3)

    def test_resolve_recap_system_prompt_falls_back_to_default(self):
        self.assertEqual(resolve_recap_system_prompt("  "), RECAP_SYSTEM)
        self.assertEqual(resolve_recap_system_prompt("只输出 JSON"), "只输出 JSON")
        self.assertEqual(resolve_recap_prompt("", RECAP_PLAN_SYSTEM), RECAP_PLAN_SYSTEM)
        self.assertEqual(resolve_recap_prompt("自定义规划", RECAP_PLAN_SYSTEM), "自定义规划")
        self.assertEqual(normalize_recap_start_from("matching"), "match")
        self.assertEqual(normalize_recap_start_from("3"), "captions")
        self.assertEqual(normalize_recap_start_from(""), "plan")

    def test_write_and_load_recap_beats(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "ep01.mp4"
            video.write_bytes(b"x")
            written = write_recap_beats_file(
                recap_beats_path_for_video(str(video)),
                title="入学",
                video_id="v1",
                allocated=[{"id": 1, "event": "开场", "budget_sec": 12.0, "t": [0.0, 8.0]}],
                people=[{"id": "p1", "label": "监考官", "look": "讲台"}],
            )
            self.assertEqual(written.name, "ep01_recap_beats.json")
            loaded = load_recap_beats(str(video))
            self.assertEqual(loaded["title"], "入学")
            self.assertEqual(loaded["beats"][0]["event"], "开场")
            self.assertEqual(loaded["people"][0]["label"], "监考官")
            self.assertEqual(loaded["stage"], "plan")

    def test_generate_resume_requires_saved_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "ep.mp4"
            video.write_bytes(b"x")
            pack = {"video_path": str(video), "duration_sec": 20.0, "chunks": []}
            with patch("src.services.recap_service.get_remote_llm_settings", return_value={"model": "x"}):
                with patch("src.services.recap_service.build_recap_pack", return_value=pack):
                    with self.assertRaisesRegex(RuntimeError, "剧情规划"):
                        generate_recap_timeline("vid", tmp, start_from="match")
                    with self.assertRaisesRegex(RuntimeError, "选镜表"):
                        generate_recap_timeline("vid", tmp, start_from="captions")

    def test_recap_requires_dialogue_cues(self):
        with self.assertRaises(RuntimeError) as raised:
            ensure_recap_dialogue_cues([])
        self.assertIn("语音", str(raised.exception))
        self.assertEqual(len(ensure_recap_dialogue_cues([{"text": "你好"}])), 1)

    def test_compact_ocr_cues_keeps_speech_only(self):
        rows = [
            {"start": 1.0, "end": 2.0, "text": "画面字幕", "asr_source": "vision/ocr/rapidocr-zh"},
            {"start": 3.0, "end": 4.5, "text": "他说开始", "asr_source": "asr"},
            {"start": 8.0, "end": 9.0, "text": "空白来源", "asr_source": ""},
        ]
        with patch(
            "src.storage.dialogue_transcript_store.iter_shared_transcript_segment_rows",
            return_value=rows,
        ):
            cues = compact_ocr_cues("vid", limit=20)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "他说开始")

    def test_compact_ocr_cues_keeps_speaker(self):
        rows = [
            {"start": 1.0, "end": 2.0, "text": "开考", "asr_source": "asr", "speaker": "柜台职员"},
            {"start": 2.0, "end": 3.0, "text": "开考", "asr_source": "asr", "speaker": "红衣女人"},
        ]
        with patch(
            "src.storage.dialogue_transcript_store.iter_shared_transcript_segment_rows",
            return_value=rows,
        ):
            cues = compact_ocr_cues("vid", limit=20)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["speaker"], "柜台职员")
        self.assertEqual(cues[1]["speaker"], "红衣女人")
        people = people_from_dialogue_speakers(cues)
        self.assertEqual([item["label"] for item in people], ["柜台职员", "红衣女人"])

    def test_recap_dialogue_status_rejects_hardsub(self):
        with patch(
            "src.storage.dialogue_transcript_store.list_dialogue_transcript_summaries",
            return_value=[{"segment_count": 12, "asr_source": "vision/ocr/rapidocr-zh"}],
        ):
            status = recap_dialogue_status("vid")
        self.assertFalse(status["ready"])
        with patch(
            "src.storage.dialogue_transcript_store.list_dialogue_transcript_summaries",
            return_value=[{"segment_count": 8, "asr_source": "asr"}],
        ):
            status = recap_dialogue_status("vid")
        self.assertTrue(status["ready"])
        self.assertEqual(status["count"], 8)

    def test_normalize_understanding_config_includes_llm(self):
        cfg = normalize_understanding_config({"understanding": {}})
        self.assertIn("remote_llm", cfg["understanding"])
        self.assertEqual(cfg["understanding"]["remote_llm"]["provider_preset"], "deepseek")
        self.assertIn("remote_asr", cfg["understanding"])
        self.assertEqual(cfg["understanding"]["remote_asr"]["provider_preset"], "openai")


class FcpxmlTests(unittest.TestCase):
    def test_layout_and_srt(self):
        num, den = fps_fraction(23.976)
        self.assertEqual((num, den), (24000, 1001))
        clips = layout_clips_on_timeline(
            [{"name": "01", "src_in": 0.0, "src_out": 2.0, "vo": "你好"}],
            fps=23.976,
        )
        self.assertAlmostEqual(clips[0]["tl_out"], clips[0]["src_out"], places=2)
        self.assertAlmostEqual(clips[0]["duration"], clips[0]["src_out"] - clips[0]["src_in"], places=2)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "demo.mp4"
            video.write_bytes(b"x")
            srt = write_srt(clips, root / "demo.srt")
            xml = write_fcpxml(
                clips,
                video_path=video,
                info={"fps": 23.976, "width": 1920, "height": 1080, "duration": 10.0},
                dest_path=root / "demo.fcpxml",
            )
            self.assertIn("你好", srt.read_text(encoding="utf-8"))
            body = xml.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE fcpxml>", body)
            self.assertIn('srcEnable="video"', body)

    def test_load_recap_cuts_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "ep01.mp4"
            video.write_bytes(b"x")
            self.assertIsNone(load_recap_cuts(str(video)))
            payload = {
                "title": "t",
                "video": str(video),
                "clips": [{"name": "01", "src_in": 1.0, "src_out": 5.0, "vo": "hello"}],
            }
            recap_cuts_path_for_video(str(video)).write_text(
                json.dumps(payload), encoding="utf-8"
            )
            loaded = load_recap_cuts(str(video))
            self.assertEqual(loaded["clips"][0]["name"], "01")

    def test_export_saved_recap_fcpxml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "ep01.mp4"
            video.write_bytes(b"x")
            payload = {
                "title": "Demo",
                "video": str(video),
                "fps": 24,
                "clips": [{"name": "01", "src_in": 1.0, "src_out": 5.0, "vo": "你好"}],
            }
            with patch(
                "src.services.recap_service._probe_media",
                return_value={"fps": 24.0, "width": 1920, "height": 1080, "duration": 20.0},
            ):
                xml = export_saved_recap_fcpxml(payload, root / "out.fcpxml", video_path=str(video))
            self.assertTrue(xml.is_file())
            self.assertIn("<!DOCTYPE fcpxml>", xml.read_text(encoding="utf-8"))

    def test_srt_uses_explicit_tts_span(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": "跨镜旁白", "vo_tl_in": 0.0, "vo_tl_out": 6.6},
            {"tl_in": 4.0, "tl_out": 8.0, "vo": "下一句", "vo_tl_in": 6.6, "vo_tl_out": 8.0},
        ]
        cues = merge_vo_cues(clips)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0]["tl_out"], 6.6)
        self.assertAlmostEqual(cues[1]["tl_in"], 6.6)

    def test_srt_locked_span_does_not_cover_extra_empty(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": "第一句", "vo_tl_in": 0.0, "vo_tl_out": 4.0},
            {"tl_in": 4.0, "tl_out": 8.0, "vo": ""},
            {"tl_in": 8.0, "tl_out": 12.0, "vo": "下一句", "vo_tl_in": 8.0, "vo_tl_out": 12.0},
        ]
        cues = merge_vo_cues(clips)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0]["tl_out"], 4.0)
        self.assertAlmostEqual(cues[1]["tl_in"], 8.0)


if __name__ == "__main__":
    unittest.main()
