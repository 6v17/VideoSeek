"""Tests for Windows long-path expansion used by embedded nginx."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.infra.paths import resolve_windows_long_path


class WindowsLongPathTests(unittest.TestCase):
    def test_non_empty_abspath_on_any_os(self):
        resolved = resolve_windows_long_path(".")
        self.assertTrue(os.path.isabs(resolved))
        self.assertTrue(os.path.isdir(resolved))

    def test_existing_dir_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = resolve_windows_long_path(tmp)
            self.assertEqual(Path(resolved).resolve(), Path(tmp).resolve())

    @unittest.skipUnless(os.name == "nt", "Windows-only short-path expansion")
    def test_get_long_path_name_used_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Exercise the ctypes branch; result should still point at the same dir.
            long_path = resolve_windows_long_path(tmp)
            self.assertTrue(os.path.isdir(long_path))
            self.assertEqual(os.path.normcase(os.path.abspath(long_path)), os.path.normcase(os.path.abspath(tmp)))

    def test_fallback_when_get_long_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("ctypes.windll.kernel32.GetLongPathNameW", side_effect=OSError("boom"), create=True):
                if os.name != "nt":
                    resolved = resolve_windows_long_path(tmp)
                else:
                    # Force except path by breaking import-time kernel32 access pattern
                    # via patching the function after module load in resolve itself.
                    resolved = resolve_windows_long_path(tmp)
            self.assertTrue(os.path.isdir(resolved))


if __name__ == "__main__":
    unittest.main()
