import unittest

from src.services.mobile_search_service import (
    build_mobile_search_payload,
    get_mobile_search_defaults,
    normalize_mobile_search_kind,
    parse_mobile_fusion,
)


class MobileSearchServiceTests(unittest.TestCase):
    def test_normalize_search_kind(self):
        self.assertEqual(normalize_mobile_search_kind("compose"), "compose")
        with self.assertRaises(ValueError):
            normalize_mobile_search_kind("invalid")

    def test_build_image_payload(self):
        payload = build_mobile_search_payload(
            search_kind="image",
            image_path="D:/uploads/a.jpg",
        )
        self.assertEqual(payload["search_kind"], "image")
        self.assertEqual(payload["image_path"], "D:/uploads/a.jpg")

    def test_build_text_payload_rejects_image(self):
        with self.assertRaises(ValueError):
            build_mobile_search_payload(
                search_kind="text",
                query="rainy night",
                image_path="D:/uploads/a.jpg",
            )

    def test_build_compose_payload_with_fusion(self):
        fusion = parse_mobile_fusion("70", has_text=True, has_image=True)
        payload = build_mobile_search_payload(
            search_kind="compose",
            query="neon city",
            image_paths=["D:/uploads/a.jpg", "D:/uploads/b.jpg"],
            fusion=fusion,
        )
        self.assertEqual(payload["search_kind"], "compose")
        self.assertEqual(len(payload["image_paths"]), 2)
        self.assertAlmostEqual(payload["fusion"]["text_weight"], 0.7, places=3)

    def test_compose_rejects_too_many_images(self):
        paths = [f"D:/uploads/{index}.jpg" for index in range(13)]
        with self.assertRaises(ValueError):
            build_mobile_search_payload(search_kind="compose", image_paths=paths, query="x")

    def test_defaults_include_mode_and_scope(self):
        defaults = get_mobile_search_defaults()
        self.assertTrue(defaults["ok"])
        self.assertIn(defaults["search_mode"], {"frame", "chunk"})
        self.assertIn(defaults["scope_mode"], {"all", "selected"})
        self.assertGreaterEqual(defaults["max_compose_images"], 1)


if __name__ == "__main__":
    unittest.main()
