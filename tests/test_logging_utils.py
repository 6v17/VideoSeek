import os
import tempfile
import time
import unittest

from src.app.logging_utils import cleanup_old_logs


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


if __name__ == "__main__":
    unittest.main()
