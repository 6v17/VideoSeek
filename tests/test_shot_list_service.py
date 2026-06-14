import unittest

from src.domain.search_hit import SearchHit
from src.services.shot_list_service import ShotListItem, ShotListStore, shot_list_dedupe_key


class ShotListServiceTests(unittest.TestCase):
    def test_add_and_dedupe(self):
        store = ShotListStore()
        hit = SearchHit(10.0, 15.0, 0.82, "D:/lib/ep01.mp4")
        self.assertTrue(store.add_from_hit(hit, source_query="smile"))
        self.assertFalse(store.add_from_hit(hit))
        self.assertEqual(store.count(), 1)
        item = store.list_items()[0]
        self.assertEqual(item.source_query, "smile")
        self.assertAlmostEqual(item.start_sec, 10.0)

    def test_dedupe_key_rounds_seconds(self):
        key_a = shot_list_dedupe_key("D:/a.mp4", 1.004, 2.004)
        key_b = shot_list_dedupe_key("D:/a.mp4", 1.001, 2.001)
        self.assertEqual(key_a, key_b)

    def test_remove_move_and_clear(self):
        store = ShotListStore()
        store.add_from_hit(SearchHit(1.0, 2.0, 0.5, "D:/a.mp4"))
        store.add_from_hit(SearchHit(3.0, 4.0, 0.6, "D:/b.mp4"))
        store.add_from_hit(SearchHit(5.0, 6.0, 0.7, "D:/c.mp4"))
        items = store.list_items()
        self.assertTrue(store.move_up(items[2].id))
        self.assertEqual(store.list_items()[1].video_path, "D:/c.mp4")
        self.assertFalse(store.move_up(items[0].id))
        self.assertTrue(store.remove(items[0].id))
        self.assertEqual(store.count(), 2)
        store.clear()
        self.assertEqual(store.count(), 0)

    def test_replace_items_skips_duplicates(self):
        store = ShotListStore()
        items = [
            ShotListItem("a", "D:/a.mp4", 1.0, 2.0, 0.5),
            ShotListItem("b", "D:/a.mp4", 1.0, 2.0, 0.5),
            ShotListItem("c", "D:/b.mp4", 3.0, 4.0, 0.6),
        ]
        store.replace_items(items)
        self.assertEqual(store.count(), 2)


if __name__ == "__main__":
    unittest.main()
