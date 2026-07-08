import unittest

from src.services.indexing_runtime_status import (
    clear_index_sync_running,
    get_index_sync_status,
    library_sync_in_progress,
    set_index_sync_running,
)


class IndexingRuntimeStatusTests(unittest.TestCase):
    def tearDown(self):
        clear_index_sync_running()

    def test_sync_status_roundtrip(self):
        clear_index_sync_running()
        self.assertFalse(get_index_sync_status()["index_sync_in_progress"])

        set_index_sync_running("D:/Anime")
        status = get_index_sync_status()
        self.assertTrue(status["index_sync_in_progress"])
        self.assertEqual(status["index_sync_target_library_path"], "D:/Anime")
        self.assertTrue(library_sync_in_progress("D:/Anime", sync_status=status))
        self.assertFalse(library_sync_in_progress("D:/Other", sync_status=status))

        clear_index_sync_running()
        self.assertFalse(get_index_sync_status()["index_sync_in_progress"])

    def test_sync_all_libraries_when_target_missing(self):
        set_index_sync_running(None)
        status = get_index_sync_status()
        self.assertTrue(library_sync_in_progress("D:/Any", sync_status=status))


if __name__ == "__main__":
    unittest.main()
