"""Nested search keeps the outer stop hook, and a failed index read is not an empty library."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from src.services.search_progress import (
    bind_search_callbacks,
    get_search_progress_callback,
    get_search_stop_callback,
    restore_search_callbacks,
    set_search_progress_callback,
    set_search_stop_callback,
)
from src.storage.lance_search_index import LanceTableSearchIndex
from src.storage.meta_io import commit_temp_file


class SearchRuntimeGuardTests(unittest.TestCase):
    def tearDown(self):
        set_search_progress_callback(None)
        set_search_stop_callback(None)

    def test_nested_bind_keeps_outer_callbacks_when_inner_passes_none(self):
        def outer_stop():
            return False

        def outer_progress(_phase, _message):
            return None

        set_search_stop_callback(outer_stop)
        set_search_progress_callback(outer_progress)
        token = bind_search_callbacks(None, None)
        self.assertIs(get_search_stop_callback(), outer_stop)
        self.assertIs(get_search_progress_callback(), outer_progress)
        restore_search_callbacks(token)
        self.assertIs(get_search_stop_callback(), outer_stop)

    def test_inner_stop_callback_is_restored_to_the_outer_one(self):
        def outer_stop():
            return False

        def inner_stop():
            return True

        set_search_stop_callback(outer_stop)
        token = bind_search_callbacks(None, inner_stop)
        self.assertIs(get_search_stop_callback(), inner_stop)
        restore_search_callbacks(token)
        self.assertIs(get_search_stop_callback(), outer_stop)

    def test_lance_row_count_failure_is_not_an_empty_index(self):
        class _BrokenTable:
            def count_rows(self, filter=None):
                raise RuntimeError("lance locked")

        with self.assertRaises(RuntimeError):
            LanceTableSearchIndex(_BrokenTable())

    def test_commit_temp_file_does_not_copy_over_a_locked_dest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dest_path = os.path.join(temp_dir, "meta.json")
            temp_path = os.path.join(temp_dir, "meta.json.tmp")
            with open(dest_path, "w", encoding="utf-8") as handle:
                handle.write('{"ok": true}')
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write('{"ok": false}')
            with patch("src.storage.meta_io.os.replace", side_effect=PermissionError("locked")):
                with patch("src.storage.meta_io.time.sleep"):
                    with self.assertRaises(PermissionError):
                        commit_temp_file(temp_path, dest_path)
            with open(dest_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}')
