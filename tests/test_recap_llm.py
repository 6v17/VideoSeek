from __future__ import annotations

import json
import os
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
    build_recap_pack,
    export_saved_recap_fcpxml,
    fit_recap_captions_to_tts,
    load_recap_cuts,
    load_recap_beats,
    write_recap_beats_file,
    generate_recap_timeline,
    recap_cuts_path_for_video,
    recap_beats_path_for_video,
    recap_speaker_stats,
    recap_target_sec,
    save_recap_plan_edits,
    format_recap_clock,
    parse_recap_clock,
    drop_op_ed_beats,
    ensure_recap_dialogue_cues,
    looks_like_op_ed_text,
    missing_match_beats,
    normalize_caption_cues,
    normalize_cut_list,
    pack_captions_for_tts,
    _join_vo,
    pad_cuts_for_tts,
    coalesce_recap_cuts,
    clamp_recap_vo_to_picture,
    restore_recap_vo_text,
    stretch_recap_clips_for_vo,
    fit_recap_vo_picture,
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
    stash_match_vo_as_draft,
    normalize_recap_start_from,
    sample_timeline_items,
    split_beats_for_match,
    trim_vo_to_budget,
    tts_char_budget,
    vo_needed_sec,
    vo_sec,
    RECAP_CAPTION_SYSTEM,
    RECAP_GAP_SYSTEM,
    RECAP_PLAN_GAP_SYSTEM,
    RECAP_PLAN_HEAD_SYSTEM,
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

    def test_apply_recap_skip_marks_op_ed_from_asr_and_tail(self):
        from src.services.recap_service import apply_recap_skip_marks

        chunks = [
            {"i": 0, "t": [0.0, 20.0], "cap": "", "skip": ""},
            {"i": 1, "t": [90.0, 140.0], "cap": "对峙", "skip": ""},
            {"i": 2, "t": [1360.0, 1440.0], "cap": "", "skip": ""},
        ]
        asr = [
            {"start": 2.0, "end": 8.0, "text": "片头曲 作词 作曲"},
            {"start": 100.0, "end": 104.0, "text": "把支票放下"},
        ]
        out = apply_recap_skip_marks(chunks, asr, 1440.0)
        self.assertEqual(out[0]["skip"], "op_ed")
        self.assertEqual(out[1]["skip"], "")
        self.assertEqual(out[2]["skip"], "op_ed")

    def test_recap_motion_gap_indices_skip_op_ed_and_existing_cap(self):
        from src.services.recap_service import recap_motion_gap_chunk_indices

        pack = {
            "chunks": [
                {"i": 0, "t": [0.0, 20.0], "cap": "", "skip": "op_ed"},
                {"i": 1, "t": [90.0, 140.0], "cap": "对峙", "skip": ""},
                {"i": 2, "t": [200.0, 240.0], "cap": "", "skip": ""},
                {"i": 3, "t": [800.0, 840.0], "cap": "", "skip": ""},
            ]
        }
        beats = [{"id": 1, "t": [90.0, 230.0]}]
        self.assertEqual(recap_motion_gap_chunk_indices(pack, beats), [2])
        padded = {
            "chunks": pack["chunks"]
            + [{"i": 4, "t": [68.0, 86.0], "cap": "", "skip": ""}]
        }
        self.assertEqual(recap_motion_gap_chunk_indices(padded, beats), [2, 4])
        self.assertEqual(recap_motion_gap_chunk_indices(padded, beats, pad_sec=0.0), [2])

    def test_fill_recap_motion_for_beats_skips_when_no_gaps(self):
        from src.services.recap_service import fill_recap_motion_for_beats

        pack = {
            "chunks": [
                {"i": 1, "t": [90.0, 140.0], "cap": "对峙", "skip": ""},
            ]
        }
        beats = [{"id": 1, "t": [90.0, 140.0]}]
        with patch("src.services.understanding_service.generate_evidence_for_video") as generate:
            out, warns, filled = fill_recap_motion_for_beats("v", pack, beats)
        generate.assert_not_called()
        self.assertEqual(warns, [])
        self.assertEqual(filled, 0)
        self.assertEqual(out["chunks"][0]["cap"], "对峙")

    def test_fill_recap_motion_for_beats_emits_chunk_progress(self):
        from src.services.recap_service import fill_recap_motion_for_beats

        pack = {
            "chunks": [
                {"i": 2, "t": [200.0, 240.0], "cap": "", "skip": ""},
            ]
        }
        beats = [{"id": 1, "t": [200.0, 240.0]}]
        seen: list[tuple[int, int]] = []

        def fake_generate(*_args, chunk_completed_callback=None, chunk_indices=None, **_kwargs):
            for index in list(chunk_indices or []):
                if chunk_completed_callback:
                    chunk_completed_callback(index, 99, {})
            return {}

        filled_pack = {
            "chunks": [
                {"i": 2, "t": [200.0, 240.0], "cap": "补上了", "skip": ""},
            ]
        }
        with (
            patch("src.services.understanding_service.generate_evidence_for_video", side_effect=fake_generate),
            patch("src.services.recap_service.build_recap_pack", return_value=filled_pack),
        ):
            out, warns, filled = fill_recap_motion_for_beats(
                "v",
                pack,
                beats,
                on_progress=lambda done, total: seen.append((done, total)),
            )
        self.assertEqual(warns, [])
        self.assertEqual(filled, 1)
        self.assertEqual(out["chunks"][0]["cap"], "补上了")
        self.assertEqual(seen[0], (0, 1))
        self.assertEqual(seen[-1], (1, 1))

    def test_build_recap_pack_without_motion_uses_index_and_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            living = Path(tmp) / "ep.mp4"
            living.write_bytes(b"x")
            with (
                patch("src.services.understanding_service.load_evidence_bundle", return_value=None),
                patch(
                    "src.services.indexing_service.load_video_chunks_by_id",
                    return_value=[{"start": 0.0, "end": 12.0}, {"start": 12.0, "end": 24.0}],
                ),
                patch(
                    "src.services.recap_service.compact_ocr_cues",
                    return_value=[{"start": 1.0, "end": 2.0, "text": "开考", "asr_source": "asr"}],
                ),
                patch(
                    "src.services.understanding_service.resolve_current_media_path",
                    return_value=str(living),
                ),
                patch(
                    "src.services.understanding_service.resolve_video_context",
                    return_value={"video_path": str(living), "duration_sec": 24.0},
                ),
            ):
                pack = build_recap_pack("vid-1")
            self.assertEqual(len(pack["chunks"]), 2)
            self.assertEqual(pack["chunks"][0]["cap"], "")
            self.assertEqual(pack["ocr"][0]["text"], "开考")

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

    def test_normalize_keeps_insert_role(self):
        pack = {
            "duration_sec": 20.0,
            "chunks": [{"i": 0, "t": [0.0, 12.0], "tags": [], "cap": ""}],
        }
        clips = normalize_cut_list(
            {
                "clips": [
                    {
                        "name": "特写",
                        "chunk_index": 0,
                        "src_in": 1.0,
                        "src_out": 4.2,
                        "role": "insert",
                        "reason": "拍下支票后的表情反应",
                    }
                ]
            },
            pack,
        )
        self.assertEqual(clips[0]["role"], "insert")
        self.assertLess(clips[0]["src_out"] - clips[0]["src_in"], 5.0)

    def test_parse_cut_list_from_fenced_json(self):
        pack = {"duration_sec": 20.0, "chunks": [{"i": 0, "t": [0.0, 8.0], "tags": [], "cap": ""}]}
        raw = """```json
{"title":"试水","clips":[{"name":"01","chunk_index":0,"src_in":0.2,"src_out":4.0,"vo":"开场。"}]}
```"""
        title, clips = parse_cut_list(raw, pack)
        self.assertEqual(title, "试水")
        self.assertEqual(clips[0]["vo"], "开场。")

    def test_stash_match_vo_as_draft(self):
        stashed = stash_match_vo_as_draft(
            [
                {"name": "01", "vo": "不该留下的口播", "src_in": 1.0, "src_out": 8.0},
                {"name": "02", "vo": "", "vo_draft": "已有草稿", "src_in": 10.0, "src_out": 16.0},
            ]
        )
        self.assertEqual(stashed[0]["vo"], "")
        self.assertEqual(stashed[0]["vo_draft"], "不该留下的口播")
        self.assertEqual(stashed[1]["vo"], "")
        self.assertEqual(stashed[1]["vo_draft"], "已有草稿")

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

    def test_tts_budget_keeps_whole_sentences(self):
        vo = "一二三四五" * 5 + "一二三"
        self.assertEqual(trim_vo_to_budget(vo, tts_char_budget(6.0)), vo)
        long = "监考官宣布考试开始。全场瞬间安静下来。她没有动笔。"
        trimmed = trim_vo_to_budget(long, 8)
        self.assertEqual(trimmed, "监考官宣布考试开始。")
        self.assertTrue(trimmed.endswith("。"))

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
        self.assertLessEqual(vo_needed_sec("监考官宣布考试开始。"), 6.0 * 0.87)

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

    def test_pack_captions_does_not_absorb_insert_follow(self):
        vo = "一二三四五" * 8  # longer than the first 4s shot
        clips = [
            {"tl_in": 0.0, "tl_out": 4.0, "vo": vo, "beat_id": 1, "name": "动作"},
            {
                "tl_in": 4.0,
                "tl_out": 7.0,
                "vo": "",
                "beat_id": 1,
                "name": "特写",
                "role": "insert",
                "reason": "表情反应",
            },
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(captions[0]["to"], 1)
        self.assertAlmostEqual(captions[0]["tl_out"], 4.0)

    def test_pack_captions_keeps_short_insert_line(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "她把支票拍在柜台上。", "beat_id": 1},
            {
                "tl_in": 6.0,
                "tl_out": 8.2,
                "vo": "职员愣住了。",
                "beat_id": 1,
                "role": "insert",
                "name": "特写",
            },
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 2)
        self.assertEqual(captions[1]["text"], "职员愣住了。")
        self.assertEqual(captions[1]["from"], 2)

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

    def test_coalesce_cuts_to_overlapping_closeup(self):
        cuts = [
            {
                "name": "教室",
                "beat_id": 1,
                "src_in": 100.0,
                "src_out": 108.0,
                "vo": "教室里突然安静下来。",
            },
            {
                "name": "特写",
                "beat_id": 1,
                "reason": "特写",
                "src_in": 105.0,
                "src_out": 114.0,
                "vo": "",
            },
        ]
        out = coalesce_recap_cuts(cuts)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0]["src_in"], 100.0)
        self.assertAlmostEqual(out[0]["src_out"], 105.0)
        self.assertAlmostEqual(out[1]["src_in"], 105.0)
        self.assertAlmostEqual(out[1]["src_out"], 114.0)
        self.assertEqual(out[0]["vo"], "教室里突然安静下来。")
        self.assertEqual(out[1]["name"], "特写")

    def test_coalesce_keeps_separate_closeup_cut(self):
        cuts = [
            {
                "name": "动作",
                "beat_id": 1,
                "src_in": 100.0,
                "src_out": 108.0,
                "vo": "她把支票拍在柜台上。",
            },
            {
                "name": "特写",
                "beat_id": 1,
                "reason": "表情特写",
                "src_in": 109.0,
                "src_out": 116.0,
                "vo": "",
            },
        ]
        out = coalesce_recap_cuts(cuts)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0]["src_out"], 108.0)
        self.assertAlmostEqual(out[1]["src_in"], 109.0)
        self.assertEqual(out[1]["name"], "特写")

    def test_coalesce_keeps_contained_closeup(self):
        cuts = [
            {
                "name": "动作",
                "beat_id": 1,
                "src_in": 100.0,
                "src_out": 108.0,
                "vo": "",
            },
            {
                "name": "特写",
                "beat_id": 1,
                "role": "insert",
                "reason": "表情反应",
                "src_in": 105.0,
                "src_out": 107.2,
                "vo": "",
            },
        ]
        out = coalesce_recap_cuts(cuts)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0]["src_out"], 105.0)
        self.assertAlmostEqual(out[1]["src_in"], 105.0)
        self.assertAlmostEqual(out[1]["src_out"], 107.2)
        self.assertEqual(out[1]["role"], "insert")

    def test_coalesce_absorbs_short_insert_between_neighbors(self):
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "src_in": 100.0,
                "src_out": 108.0,
                "vo": "监考官宣布考试开始。",
            },
            {
                "name": "闪一下",
                "beat_id": 2,
                "src_in": 108.4,
                "src_out": 110.0,
                "vo": "她愣住了。",
            },
            {
                "name": "03",
                "beat_id": 3,
                "src_in": 110.2,
                "src_out": 118.0,
                "vo": "全场瞬间安静下来。",
            },
        ]
        out = coalesce_recap_cuts(cuts)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0]["src_in"], 100.0)
        self.assertAlmostEqual(out[0]["src_out"], 110.0)
        self.assertIn("她愣住了。", out[0]["vo"])
        self.assertEqual(out[1]["vo"], "全场瞬间安静下来。")
        self.assertGreaterEqual(out[1]["src_in"], 110.0)

    def test_coalesce_attaches_isolated_short_vo_to_previous(self):
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "src_in": 20.0,
                "src_out": 28.0,
                "vo": "监考官宣布考试开始。",
            },
            {
                "name": "碎镜头",
                "beat_id": 2,
                "src_in": 80.0,
                "src_out": 81.6,
                "vo": "他没有回答。",
            },
            {
                "name": "03",
                "beat_id": 3,
                "src_in": 140.0,
                "src_out": 148.0,
                "vo": "全场瞬间安静下来。",
            },
        ]
        out = coalesce_recap_cuts(cuts)
        self.assertEqual(len(out), 2)
        self.assertIn("他没有回答。", out[0]["vo"])
        self.assertEqual(out[1]["vo"], "全场瞬间安静下来。")
        self.assertAlmostEqual(out[0]["src_out"], 28.0)
        self.assertAlmostEqual(out[1]["src_in"], 140.0)

    def test_coalesce_keeps_separated_full_shots(self):
        cuts = [
            {
                "name": "01",
                "beat_id": 1,
                "src_in": 20.0,
                "src_out": 28.0,
                "vo": "监考官宣布考试开始。",
            },
            {
                "name": "02",
                "beat_id": 2,
                "src_in": 40.0,
                "src_out": 48.0,
                "vo": "全场瞬间安静下来。",
            },
        ]
        out = coalesce_recap_cuts(cuts)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["vo"], "监考官宣布考试开始。")
        self.assertEqual(out[1]["vo"], "全场瞬间安静下来。")

    def test_pack_captions_folds_flash_vo_into_neighbor(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "监考官宣布考试开始。", "beat_id": 1},
            {"tl_in": 6.0, "tl_out": 7.5, "vo": "她愣住了。", "beat_id": 2},
            {"tl_in": 7.5, "tl_out": 13.0, "vo": "全场瞬间安静下来。", "beat_id": 3},
        ]
        captions = pack_captions_for_tts(clips)
        self.assertEqual(len(captions), 2)
        self.assertIn("她愣住了。", captions[0]["text"])
        self.assertEqual(captions[0]["to"], 2)
        self.assertAlmostEqual(captions[0]["tl_out"], 7.5)
        self.assertEqual(captions[1]["text"], "全场瞬间安静下来。")

    def test_parse_gap_fills_skips_flash_clips(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。"},
            {"tl_in": 6.0, "tl_out": 7.4, "vo": ""},
        ]
        fills = parse_gap_fills(
            '{"fills":[{"i":2,"text":"他直接出手了。"}]}',
            clips,
            allowed={1},
        )
        self.assertEqual(fills, [])

    def test_parse_gap_fills_keeps_insert(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "她把支票拍在柜台上。"},
            {
                "tl_in": 6.0,
                "tl_out": 8.2,
                "vo": "",
                "role": "insert",
                "name": "特写",
            },
        ]
        fills = parse_gap_fills(
            '{"fills":[{"i":2,"text":"职员愣住了。"}]}',
            clips,
            allowed={1},
        )
        self.assertEqual(fills, [{"index": 1, "text": "职员愣住了。"}])

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

    def test_join_vo_keeps_two_sentences(self):
        self.assertEqual(_join_vo("教室安静下来", "她没有动笔。"), "教室安静下来。她没有动笔。")

    def test_clamp_does_not_chop_match_vo(self):
        vo = "监考官宣布考试开始。" + "全场瞬间安静下来。" * 6
        clips = [
            {
                "src_in": 10.0,
                "src_out": 16.0,
                "vo": vo,
                "vo_draft": vo,
                "beat_id": 1,
            }
        ]
        out = clamp_recap_vo_to_picture(clips)
        self.assertEqual(out[0]["vo"], vo)

    def test_fit_does_not_edit_match_vo(self):
        vo = "一二三四五" * 11
        clips = [
            {
                "src_in": 10.0,
                "src_out": 32.0,
                "vo": vo,
                "beat_id": 1,
            }
        ]
        out = fit_recap_vo_picture(clips)
        self.assertEqual(out[0]["vo"], vo)
        self.assertAlmostEqual(out[0]["src_out"], 32.0)

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

    def test_fit_recap_rewrites_captions_via_llm(self):
        clips = [
            {"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "beat_id": 1, "reason": "开场"},
            {"tl_in": 6.0, "tl_out": 10.0, "vo": "", "beat_id": 1, "reason": "关键动作"},
        ]
        with patch(
            "src.services.recap_service.call_remote_llm",
            return_value='{"captions":[{"text":"考试开始，全场安静下来。","from":1,"to":2}]}',
        ) as mock_llm:
            out = fit_recap_captions_to_tts(clips)
        mock_llm.assert_called_once()
        self.assertEqual(out[0]["vo"], "考试开始，全场安静下来。")
        self.assertEqual(out[1]["vo"], "")
        self.assertEqual(out[0]["vo_draft"], "开场。")

    def test_fit_recap_keeps_seed_when_llm_fails(self):
        clips = [{"tl_in": 0.0, "tl_out": 6.0, "vo": "开场。", "beat_id": 1}]
        with patch(
            "src.services.recap_service.call_remote_llm",
            side_effect=RuntimeError("boom"),
        ):
            out = fit_recap_captions_to_tts(clips)
        self.assertEqual(out[0]["vo"], "开场。")

    def test_recap_prompt_asks_for_narration_not_translation(self):
        self.assertIn("不要写 vo", RECAP_SYSTEM)
        self.assertNotIn("85–90%", RECAP_SYSTEM)
        self.assertIn("budget_sec", RECAP_SYSTEM)
        self.assertIn("reason", RECAP_SYSTEM)
        self.assertIn("不要为了碎而碎", RECAP_SYSTEM)
        self.assertIn("不写剪辑表", RECAP_PLAN_SYSTEM)
        self.assertIn("宁多勿跳", RECAP_PLAN_SYSTEM)
        self.assertIn("14–20", RECAP_PLAN_SYSTEM)
        self.assertIn("3–8 分钟", RECAP_PLAN_SYSTEM)
        self.assertNotIn("5 分半", RECAP_PLAN_SYSTEM)
        self.assertIn("设定/空间", RECAP_PLAN_SYSTEM)
        self.assertIn("角色侧面", RECAP_PLAN_SYSTEM)
        self.assertIn("换场", RECAP_PLAN_SYSTEM)
        self.assertIn("importance", RECAP_PLAN_SYSTEM)
        self.assertIn("片尾", RECAP_PLAN_SYSTEM)
        self.assertIn("叙事骨架", RECAP_PLAN_SYSTEM)
        self.assertIn("needed_visual", RECAP_PLAN_SYSTEM)
        self.assertIn("收尾", RECAP_SYSTEM)
        self.assertIn("片头曲", RECAP_PLAN_SYSTEM)
        self.assertIn("叙事真相", RECAP_SYSTEM)
        self.assertIn("85–90%", RECAP_CAPTION_SYSTEM)
        self.assertIn("禁止照读", RECAP_CAPTION_SYSTEM)
        self.assertIn("看图说话", RECAP_CAPTION_SYSTEM)
        self.assertNotIn("按 reason、beat 和 people 写旁白", RECAP_CAPTION_SYSTEM)
        self.assertNotIn("连续空镜特写", RECAP_CAPTION_SYSTEM)
        self.assertIn("role=insert", RECAP_CAPTION_SYSTEM)
        self.assertIn("单独一句", RECAP_CAPTION_SYSTEM)
        self.assertIn("换场/过场空镜可以并进前一句", RECAP_CAPTION_SYSTEM)
        self.assertIn("特写", RECAP_SYSTEM)
        self.assertIn('"role":"insert"', RECAP_SYSTEM.replace(" ", ""))
        self.assertIn("新的视觉信息", RECAP_SYSTEM)
        self.assertIn("单独切一刀", RECAP_SYSTEM)
        self.assertIn("不要单独一刀", RECAP_SYSTEM)
        self.assertIn("duration", RECAP_SYSTEM)
        self.assertIn("1.35", RECAP_CAPTION_SYSTEM)
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
        for body in (RECAP_PLAN_SYSTEM, RECAP_SYSTEM, RECAP_GAP_SYSTEM, RECAP_CAPTION_SYSTEM):
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
            [
                {
                    "name": "01",
                    "tl_in": 0.0,
                    "tl_out": 6.0,
                    "vo": "开场。",
                    "beat_id": 1,
                    "reason": "红衣女人走进店里，柜台后面站着职员。",
                }
            ],
            beats=[{"id": 1, "event": "柜台职员拒收"}],
        )
        self.assertIn("1.35", cap_prompt)
        self.assertIn("seed", cap_prompt)
        self.assertIn("根据 event", cap_prompt)
        self.assertIn("柜台职员拒收", cap_prompt)
        self.assertNotIn("红衣女人走进店里，柜台后面站着职员。", cap_prompt)
        self.assertIn("禁止朗读 reason", cap_prompt)
        self.assertIn("role=insert", cap_prompt)
        cap_insert = recap_caption_user_prompt(
            [
                {
                    "name": "特写",
                    "tl_in": 0.0,
                    "tl_out": 3.0,
                    "vo": "",
                    "beat_id": 1,
                    "role": "insert",
                    "reason": "VLM说她的瞳孔放大、镜头推进",
                }
            ],
            beats=[{"id": 1, "event": "她意识到被骗了"}],
        )
        self.assertIn('"role": "insert"', cap_insert)
        self.assertIn("她意识到被骗了", cap_insert)
        self.assertNotIn("瞳孔放大", cap_insert)
        self.assertIn("完整句子", RECAP_CAPTION_SYSTEM)
        self.assertIn("禁止半句", RECAP_CAPTION_SYSTEM)
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
        self.assertIn("换场/过场空镜填 skip", gap_prompt)
        self.assertNotIn("特写/反应/过渡填 skip", gap_prompt)
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
        self.assertIn("3–8 分钟", prompt)
        self.assertNotIn("5 分半", prompt)
        self.assertIn("片头曲", prompt)
        self.assertIn("不要写 vo", prompt)
        self.assertNotIn("85–90%", prompt)
        self.assertIn("特写", prompt)
        self.assertIn("叙事骨架", recap_plan_user_prompt(
            {"duration_sec": 100.0, "chunks": [], "ocr": []},
        ))
        self.assertIn("叙事真相", prompt)
        self.assertIn("people", prompt)
        self.assertIn("同一个他", prompt)
        self.assertIn("speaker", prompt)
        self.assertIn("禁止男主", prompt)
        self.assertIn("红衣女人", prompt)
        self.assertNotIn("考号", prompt)
        self.assertIn("单独一刀", prompt)
        self.assertIn("role=insert", prompt)

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

    def test_apply_recap_duration_keeps_insert_cut(self):
        pack = {
            "duration_sec": 80.0,
            "chunks": [{"i": 0, "t": [10.0, 70.0], "skip": ""}],
        }
        beats = [{"id": 1, "budget_sec": 8.0, "t": [10.0, 70.0]}]
        cuts = [
            {
                "name": "动作",
                "beat_id": 1,
                "chunk_index": 0,
                "src_in": 12.0,
                "src_out": 20.0,
                "vo": "",
            },
            {
                "name": "特写",
                "beat_id": 1,
                "chunk_index": 0,
                "role": "insert",
                "reason": "表情反应",
                "src_in": 22.0,
                "src_out": 25.0,
                "vo": "",
            },
        ]
        out = apply_recap_duration(cuts, pack, beats)
        self.assertEqual(len(out), 2)
        self.assertTrue(any(clip.get("role") == "insert" or "特写" in str(clip.get("name") or "") for clip in out))
        self.assertLessEqual(recap_cuts_duration(out), 9.0)

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
        self.assertEqual(normalize_recap_start_from("match_only"), "match")
        self.assertEqual(normalize_recap_start_from("3"), "captions")
        self.assertEqual(normalize_recap_start_from("plan_only"), "plan_only")
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

    def test_recap_target_sec_scales_and_clamps(self):
        self.assertAlmostEqual(recap_target_sec(480.0), 180.0)
        self.assertAlmostEqual(recap_target_sec(1440.0), 243.0)
        self.assertAlmostEqual(recap_target_sec(3600.0), 480.0)
        self.assertEqual(format_recap_clock(125.0), "02:05")
        self.assertAlmostEqual(parse_recap_clock("02:05"), 125.0)
        self.assertAlmostEqual(parse_recap_clock("90"), 90.0)

    def test_save_recap_plan_edits_reallocates(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "ep.mp4"
            video.write_bytes(b"x")
            written = save_recap_plan_edits(
                str(video),
                video_id="vid",
                title="改过",
                beats=[
                    {"id": 1, "event": "开场", "importance": 0.9, "needed_visual": "门口", "t": [0.0, 20.0]},
                    {"id": 2, "event": "过场", "importance": 0.2, "needed_visual": "走路", "t": [40.0, 50.0]},
                ],
                people=[{"id": "p1", "label": "店长", "look": "工装"}],
                duration_sec=1440.0,
                target_sec=20.0,
            )
            loaded = load_recap_beats(str(video))
            self.assertEqual(written.name, "ep_recap_beats.json")
            self.assertEqual(loaded["title"], "改过")
            self.assertEqual(len(loaded["beats"]), 2)
            self.assertGreater(loaded["beats"][0]["budget_sec"], loaded["beats"][1]["budget_sec"])
            self.assertAlmostEqual(
                loaded["target_sec"],
                sum(float(item["budget_sec"]) for item in loaded["beats"]),
                delta=0.2,
            )

    def test_people_from_dialogue_skips_auto_labels(self):
        people = people_from_dialogue_speakers(
            [
                {"speaker": "声线1", "text": "你好"},
                {"speaker": "店长", "text": "请进"},
                {"speaker": "", "text": "嗯"},
                {"speaker": "Voice 2", "text": "走"},
            ]
        )
        self.assertEqual([item["label"] for item in people], ["店长"])
        stats = recap_speaker_stats(
            [
                {"speaker": "声线1"},
                {"speaker": "店长"},
                {"speaker": ""},
                {"speaker": "Voice 2"},
            ]
        )
        self.assertEqual(stats["named"], 1)
        self.assertEqual(stats["auto"], 2)
        self.assertEqual(stats["blank"], 1)
        self.assertEqual(stats["unnamed"], 3)
        self.assertTrue(stats["needs_naming"])

    def test_load_recap_beats_finds_old_stem_after_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_video = Path(tmp) / "old.mp4"
            new_video = Path(tmp) / "renamed.mp4"
            new_video.write_bytes(b"x")
            write_recap_beats_file(
                recap_beats_path_for_video(str(old_video)),
                title="旧名规划",
                video_id="vid-1",
                allocated=[{"id": 1, "event": "开场", "budget_sec": 12.0, "t": [0.0, 8.0]}],
            )
            loaded = load_recap_beats(str(new_video), video_id="vid-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["title"], "旧名规划")

    def test_build_recap_pack_uses_living_path_after_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            living = Path(tmp) / "renamed.mp4"
            living.write_bytes(b"x")
            stale = str(Path(tmp) / "old.mp4")
            evidence = {
                "video": {"video_path": stale, "duration_sec": 12.0},
                "chunks": [
                    {
                        "chunk_index": 0,
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "evidence": {"vision": {"image_caption": {"text": "教室"}}},
                    }
                ],
            }
            with (
                patch("src.services.understanding_service.load_evidence_bundle", return_value=evidence),
                patch(
                    "src.services.indexing_service.load_video_chunks_by_id",
                    return_value=[],
                ),
                patch(
                    "src.services.recap_service.compact_ocr_cues",
                    return_value=[{"start": 0.0, "end": 1.0, "text": "开考", "asr_source": "asr"}],
                ),
                patch(
                    "src.services.understanding_service.resolve_current_media_path",
                    return_value=str(living),
                ),
            ):
                pack = build_recap_pack("vid-1")
            self.assertEqual(os.path.normcase(pack["video_path"]), os.path.normcase(str(living)))

    def test_generate_timeline_resolves_renamed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            living = Path(tmp) / "renamed.mp4"
            living.write_bytes(b"x")
            pack = {"video_path": str(Path(tmp) / "old.mp4"), "duration_sec": 20.0, "chunks": []}
            with patch("src.services.recap_service.get_remote_llm_settings", return_value={"model": "x"}):
                with patch("src.services.recap_service.build_recap_pack", return_value=pack):
                    with patch(
                        "src.services.understanding_service.resolve_current_media_path",
                        return_value=str(living),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "剧情规划"):
                            generate_recap_timeline("vid", tmp, start_from="match")

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

    def _generate_long_recap(self, *, fail_gap=False, fail_head=False, fail_close=False, cover_opening=True, start_from="plan"):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "ep.mp4"
            video.write_bytes(b"x")
            pack = {
                "video_path": str(video),
                "duration_sec": 1440.0,
                "chunks": [
                    {"i": 0, "t": [0.0, 50.0], "dur": 50.0, "cap": "开场", "tags": []},
                    {"i": 1, "t": [400.0, 460.0], "dur": 60.0, "cap": "对峙", "tags": []},
                    {"i": 2, "t": [1200.0, 1280.0], "dur": 80.0, "cap": "收尾", "tags": []},
                ],
                "ocr": [{"start": 10.0, "end": 12.0, "text": "你好", "speaker": "店长"}],
                "people": [{"id": "s1", "label": "店长", "look": "对白说话人"}],
            }
            systems: list[str] = []
            match_calls = {"n": 0}
            caption_in: list[dict] = []

            def fake_llm(*, system, user, **kwargs):
                del user, kwargs
                systems.append(system)
                if system == RECAP_PLAN_SYSTEM:
                    first = [10.0, 40.0] if cover_opening else [400.0, 460.0]
                    return json.dumps(
                        {
                            "title": "试水",
                            "people": [{"id": "s1", "label": "店长", "look": "对白说话人"}],
                            "beats": [
                                {
                                    "id": 1,
                                    "event": "开场对峙" if cover_opening else "中段对峙",
                                    "importance": 0.9,
                                    "needed_visual": "店内",
                                    "t": first,
                                },
                                {
                                    "id": 2,
                                    "event": "收尾",
                                    "importance": 0.9,
                                    "needed_visual": "门外",
                                    "t": [1200.0, 1280.0],
                                },
                            ],
                        }
                    )
                if system == RECAP_PLAN_HEAD_SYSTEM:
                    if fail_head:
                        raise RuntimeError("head boom")
                    return json.dumps(
                        {
                            "title": "试水",
                            "beats": [
                                {
                                    "id": 9,
                                    "event": "冷开场",
                                    "importance": 0.8,
                                    "needed_visual": "门口",
                                    "t": [8.0, 30.0],
                                }
                            ],
                        }
                    )
                if system == RECAP_PLAN_GAP_SYSTEM:
                    if fail_gap:
                        raise RuntimeError("gap boom")
                    return json.dumps(
                        {
                            "title": "试水",
                            "beats": [
                                {
                                    "id": 3,
                                    "event": "中段对峙",
                                    "importance": 0.85,
                                    "needed_visual": "柜台",
                                    "t": [400.0, 460.0],
                                }
                            ],
                        }
                    )
                if system == RECAP_SYSTEM:
                    match_calls["n"] += 1
                    if fail_close and match_calls["n"] > 1:
                        raise RuntimeError("close boom")
                    clips = [
                        {
                            "name": "01",
                            "beat_id": 1,
                            "chunk_index": 0 if cover_opening else 1,
                            "src_in": 10.0 if cover_opening else 410.0,
                            "src_out": 18.0 if cover_opening else 418.0,
                            "vo": "不该留下的口播",
                            "reason": "开场",
                        }
                    ]
                    if not fail_close:
                        clips.extend(
                            [
                                {
                                    "name": "02",
                                    "beat_id": 3 if cover_opening and not fail_gap else 2,
                                    "chunk_index": 1,
                                    "src_in": 410.0,
                                    "src_out": 418.0,
                                    "vo": "",
                                    "reason": "对峙",
                                },
                                {
                                    "name": "03",
                                    "beat_id": 2,
                                    "chunk_index": 2,
                                    "src_in": 1210.0,
                                    "src_out": 1218.0,
                                    "vo": "",
                                    "reason": "收尾",
                                },
                            ]
                        )
                    return json.dumps({"title": "试水", "clips": clips})
                return json.dumps({"captions": [{"text": "店长开口。", "from": 1, "to": 1}]})

            def fake_captions(clips, **kwargs):
                del kwargs
                caption_in.extend(dict(item) for item in clips)
                out = [dict(item) for item in clips]
                for item in out:
                    item["vo"] = str(item.get("vo") or "旁白。")
                return out

            with (
                patch("src.services.recap_service.get_remote_llm_settings", return_value={"model": "x"}),
                patch("src.services.recap_service.build_recap_pack", return_value=pack),
                patch("src.services.recap_service.call_remote_llm", side_effect=fake_llm),
                patch(
                    "src.services.recap_service._probe_media",
                    return_value={"fps": 24.0, "width": 1920, "height": 1080, "duration": 1440.0},
                ),
                patch("src.services.recap_service.fit_recap_captions_to_tts", side_effect=fake_captions),
                patch(
                    "src.services.understanding_service.resolve_current_media_path",
                    return_value=str(video),
                ),
            ):
                if start_from in {"match", "captions"}:
                    generate_recap_timeline("vid", tmp, start_from="plan_only")
                    systems.clear()
                if start_from == "captions":
                    generate_recap_timeline("vid", tmp, start_from="match")
                    systems.clear()
                    caption_in.clear()
                result = generate_recap_timeline("vid", tmp, start_from=start_from)
            return result, systems, caption_in

    def test_generate_fills_story_gaps_and_stashes_match_vo(self):
        result, systems, caption_in = self._generate_long_recap()
        self.assertIn(RECAP_PLAN_GAP_SYSTEM, systems)
        self.assertNotIn(RECAP_PLAN_HEAD_SYSTEM, systems)
        self.assertEqual(result.get("warnings"), [])
        self.assertGreaterEqual(int(result.get("clip_count") or 0), 1)
        self.assertTrue(any(str(item.get("vo") or "") == "" for item in caption_in))
        self.assertTrue(any(str(item.get("vo_draft") or "") == "不该留下的口播" for item in caption_in))

    def test_generate_records_plan_gap_warning(self):
        result, systems, _caption_in = self._generate_long_recap(fail_gap=True)
        self.assertIn(RECAP_PLAN_GAP_SYSTEM, systems)
        self.assertIn("recap_warn_plan_gaps", result.get("warnings") or [])

    def test_generate_records_plan_head_warning(self):
        result, systems, _caption_in = self._generate_long_recap(fail_head=True, cover_opening=False)
        self.assertIn(RECAP_PLAN_HEAD_SYSTEM, systems)
        self.assertIn("recap_warn_plan_head", result.get("warnings") or [])

    def test_generate_records_match_close_warning(self):
        result, _systems, _caption_in = self._generate_long_recap(fail_close=True)
        self.assertIn("recap_warn_match_close", result.get("warnings") or [])

    def test_generate_plan_only_stops_before_match(self):
        result, systems, caption_in = self._generate_long_recap(start_from="plan_only")
        self.assertEqual(result.get("stage"), "plan")
        self.assertGreaterEqual(int(result.get("beat_count") or 0), 2)
        self.assertFalse(result.get("cuts_path"))
        self.assertIn(RECAP_PLAN_GAP_SYSTEM, systems)
        self.assertNotIn(RECAP_SYSTEM, systems)
        self.assertEqual(caption_in, [])

    def test_generate_match_stops_before_captions(self):
        result, systems, caption_in = self._generate_long_recap(start_from="match")
        self.assertEqual(result.get("stage"), "match")
        self.assertTrue(result.get("cuts_path"))
        self.assertFalse(result.get("srt_path"))
        self.assertGreaterEqual(int(result.get("clip_count") or 0), 1)
        self.assertIn(RECAP_SYSTEM, systems)
        self.assertNotIn(RECAP_PLAN_SYSTEM, systems)
        self.assertEqual(caption_in, [])

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
            [{"name": "01", "src_in": 0.0, "src_out": 2.0, "vo": "你好", "vo_draft": "草稿"}],
            fps=23.976,
        )
        self.assertEqual(clips[0]["vo"], "你好")
        self.assertEqual(clips[0]["vo_draft"], "草稿")
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
