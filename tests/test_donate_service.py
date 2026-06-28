import unittest

from src.app import app_meta
from src.services.donate_service import get_donate_payload


class DonateServiceTests(unittest.TestCase):
    def test_get_donate_payload_reads_app_meta(self):
        original = dict(app_meta.APP_META)
        try:
            app_meta.APP_META.update(
                {
                    "donate_image_url": "https://cdn.example.com/wechat-reward.png",
                    "donate_github_url": "https://github.com/test/repo",
                    "donate_bilibili_url": "https://space.bilibili.com/test",
                    "donate_qq_url": "https://qm.qq.com/q/test",
                }
            )
            payload = get_donate_payload()
        finally:
            app_meta.APP_META.clear()
            app_meta.APP_META.update(original)

        self.assertEqual(payload["image_url"], "https://cdn.example.com/wechat-reward.png")
        self.assertEqual(payload["github_url"], "https://github.com/test/repo")
        self.assertEqual(payload["bilibili_url"], "https://space.bilibili.com/test")
        self.assertEqual(payload["qq_url"], "https://qm.qq.com/q/test")


if __name__ == "__main__":
    unittest.main()
