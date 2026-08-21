"""Smoke tests for the thin VideoSeek plugin registry."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app import plugins as plugin_mod
from src.app.plugins import (
    FeatureHooks,
    discover_plugin_module_names,
    get_registry,
    load_plugins,
    reset_registry_for_tests,
    resolve_nav_page_order,
)


class _DummyFeature(FeatureHooks):
    def __init__(self):
        self.inited = False

    def on_init(self, window):
        self.inited = True


class PluginRegistryTests(unittest.TestCase):
    def setUp(self):
        reset_registry_for_tests()

    def tearDown(self):
        reset_registry_for_tests()

    def test_resolve_nav_inserts_after_anchor(self):
        registry = get_registry()
        registry.register_page(
            "clone",
            label_key="nav_clone",
            factory=lambda: object(),
            insert_after="understanding",
        )
        order = resolve_nav_page_order(registry=registry)
        self.assertEqual(
            order,
            ("search", "library", "understanding", "clone", "link", "settings"),
        )

    def test_package_kind_reserved_names_rejected(self):
        with self.assertRaises(ValueError):
            get_registry().register_package_kind(
                "search",
                detect_fn=lambda _p: False,
                import_fn=lambda *_a, **_k: {},
            )

    def test_load_plugins_calls_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "videoseek_plugin_dummy"
            pkg.mkdir()
            (pkg / "__init__.py").write_text(
                "def register(registry):\n"
                "    registry.register_i18n({'nav_dummy': 'Dummy'}, {'nav_dummy': 'Dummy'})\n"
                "    registry.register_page('dummy', label_key='nav_dummy', factory=lambda: object())\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"VIDEOSEEK_PLUGINS": "videoseek_plugin_dummy"}, clear=False):
                import sys

                sys.path.insert(0, tmp)
                try:
                    reset_registry_for_tests()
                    loaded = load_plugins(["videoseek_plugin_dummy"])
                finally:
                    sys.path.remove(tmp)
            self.assertIn("videoseek_plugin_dummy", loaded.loaded_modules)
            self.assertTrue(any(p.page_id == "dummy" for p in loaded.pages))

    def test_discover_from_env(self):
        with patch.dict(os.environ, {"VIDEOSEEK_PLUGINS": "a,b;c"}, clear=False):
            with patch.object(plugin_mod, "_profile_plugins_path", return_value=""):
                with patch.object(plugin_mod, "_module_importable", return_value=False):
                    with patch.object(plugin_mod, "ensure_plugin_search_paths", return_value=[]):
                        self.assertEqual(discover_plugin_module_names(), ["a", "b", "c"])

    def test_classify_uses_plugin_kind(self):
        from src.services.understanding_import_service import classify_package_zip

        get_registry().register_package_kind(
            "clone",
            detect_fn=lambda path: str(path).endswith("clone.zip"),
            import_fn=lambda *_a, **_k: {"component_id": "x"},
        )
        with patch(
            "src.services.understanding_import_service.zip_has_root_file",
            return_value=False,
        ), patch(
            "src.services.understanding_import_service.zip_contains_file_suffix",
            return_value=False,
        ):
            self.assertEqual(classify_package_zip("foo-clone.zip"), "clone")
            self.assertEqual(classify_package_zip("other.zip"), "unknown")

    def test_get_texts_merges_overlay(self):
        from src.app.i18n import get_texts

        get_registry().register_i18n({"nav_clone": "视频克隆"}, {"nav_clone": "Video Clone"})
        zh = get_texts("zh")
        en = get_texts("en")
        self.assertEqual(zh.get("nav_clone"), "视频克隆")
        self.assertEqual(en.get("nav_clone"), "Video Clone")


if __name__ == "__main__":
    unittest.main()
