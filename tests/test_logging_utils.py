import os
import tempfile
import time
import unittest
import zipfile

from src.app.logging_utils import cleanup_old_logs, export_logs_zip


class LoggingUtilsTests(unittest.TestCase):
    def test_cleanup_old_logs_keeps_recent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = time.time()
            fresh = os.path.join(tmp, "app.log")
            old = os.path.join(tmp, "app.log.1")
            other = os.path.join(tmp, "notes.txt")
            for path in (fresh, old, other):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("x")
            os.utime(fresh, (now - 3600, now - 3600))
            os.utime(old, (now - 10 * 24 * 3600, now - 10 * 24 * 3600))
            os.utime(other, (now - 10 * 24 * 3600, now - 10 * 24 * 3600))

            removed = cleanup_old_logs(tmp, retention_days=7, now=now)
            self.assertEqual(removed, 1)
            self.assertTrue(os.path.exists(fresh))
            self.assertFalse(os.path.exists(old))
            self.assertTrue(os.path.exists(other))

    def test_export_logs_zip_packs_only_log_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            with open(os.path.join(src, "app.log"), "w", encoding="utf-8") as handle:
                handle.write("hello-log")
            with open(os.path.join(src, "app.log.1"), "w", encoding="utf-8") as handle:
                handle.write("older")
            with open(os.path.join(src, "notes.txt"), "w", encoding="utf-8") as handle:
                handle.write("skip")
            dest = os.path.join(dst, "out.zip")
            count = export_logs_zip(dest, log_dir=src)
            self.assertEqual(count, 2)
            with zipfile.ZipFile(dest) as archive:
                self.assertEqual(set(archive.namelist()), {"app.log", "app.log.1"})
                self.assertEqual(archive.read("app.log").decode("utf-8"), "hello-log")

    def test_export_logs_zip_rejects_an_empty_folder(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            dest = os.path.join(dst, "out.zip")
            with self.assertRaises(FileNotFoundError):
                export_logs_zip(dest, log_dir=src)


if __name__ == "__main__":
    unittest.main()
