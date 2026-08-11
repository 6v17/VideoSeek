import unittest

from src.storage.lance_search_index import (
    _build_scope_where,
    _should_materialize_in_memory,
)


class LanceScopeWhereTests(unittest.TestCase):
    def test_build_scope_where_single_video(self):
        self.assertEqual(_build_scope_where(video_id="vid_a"), "video_id = 'vid_a'")

    def test_build_scope_where_multi_video_uses_in(self):
        where = _build_scope_where(video_ids=["vid_a", "vid_b", "vid_a"])
        self.assertEqual(where, "video_id IN ('vid_a', 'vid_b')")

    def test_build_scope_where_empty_video_ids_is_false(self):
        self.assertEqual(_build_scope_where(video_ids=[]), "1 = 0")

    def test_build_scope_where_escapes_quotes(self):
        where = _build_scope_where(video_ids=["o'brien", "x"])
        self.assertEqual(where, "video_id IN ('o''brien', 'x')")

    def test_multi_video_ids_never_materialize(self):
        self.assertFalse(_should_materialize_in_memory(video_ids=["a", "b"]))
        self.assertFalse(_should_materialize_in_memory(video_ids=[]))
        self.assertTrue(_should_materialize_in_memory(video_id="only"))


if __name__ == "__main__":
    unittest.main()
