"""Tests for VLM tag parsing helpers."""

from __future__ import annotations

import unittest

from src.services.understanding_tags import format_tags_for_display, parse_vlm_tag_list


class UnderstandingTagsTests(unittest.TestCase):
    def test_parse_json_object(self):
        tags = parse_vlm_tag_list('{"tags":["海边","跑车","日落"]}')
        self.assertEqual(tags, ["海边", "跑车", "日落"])

    def test_parse_json_fence(self):
        tags = parse_vlm_tag_list('```json\n{"tags":["ocean","car"]}\n```')
        self.assertEqual(tags, ["ocean", "car"])

    def test_parse_comma_fallback(self):
        tags = parse_vlm_tag_list("海边，跑车、日落")
        self.assertEqual(tags, ["海边", "跑车", "日落"])

    def test_parse_json_with_chinese_commas(self):
        tags = parse_vlm_tag_list('{"tags":["工人"，"工地"，"管道"]}')
        self.assertEqual(tags, ["工人", "工地", "管道"])

    def test_parse_recovers_broken_json_comma_split_shape(self):
        # Real failure mode: JSON parse failed and naive comma-split left debris.
        raw = '{"tags":["工人","工地","管道","拧螺丝","专注","建设中","工业风","劳动"]}'
        tags = parse_vlm_tag_list(raw)
        self.assertEqual(
            tags,
            ["工人", "工地", "管道", "拧螺丝", "专注", "建设中", "工业风", "劳动"],
        )

    def test_parse_strips_json_debris_fragments(self):
        tags = parse_vlm_tag_list(
            '{"tags":["工人","\\"工地\\"","\\"管道\\"","\\"劳动\\"]}"}'
        )
        # Even messy near-JSON should not keep brace/quote debris as tags.
        self.assertTrue(tags)
        self.assertFalse(any("{" in tag or "}" in tag or "\\" in tag for tag in tags))

    def test_dedupe_and_limit(self):
        tags = parse_vlm_tag_list('{"tags":["A","a","B","B","C"]}', max_tags=2)
        self.assertEqual(tags, ["A", "B"])

    def test_format_display(self):
        self.assertEqual(format_tags_for_display(["海边", "跑车"]), "海边 · 跑车")


if __name__ == "__main__":
    unittest.main()
