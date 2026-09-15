"""Defaults and UI ordering for search accuracy / path polish."""

from __future__ import annotations

import importlib.util
import types
import unittest
from unittest.mock import MagicMock, patch

from src.app.config import DEFAULT_CONFIG
from src.app.i18n import TEXTS

# Keep in sync with SearchPanelStateMixin.IMAGE_SEARCH_MODES
_EXPECTED_IMAGE_SEARCH_MODES = ("frame", "video_discovery", "precise", "chunk")
_HAS_PYSIDE = importlib.util.find_spec("PySide6") is not None


class SearchDefaultPathPolishTests(unittest.TestCase):
    def test_text_default_is_chunk_and_neighbor_rerank_on(self):
        self.assertEqual(DEFAULT_CONFIG["search_mode"], "chunk")
        self.assertEqual(DEFAULT_CONFIG["image_search_mode"], "frame")
        self.assertTrue(DEFAULT_CONFIG["frame_neighbor_rerank_enabled"])
        self.assertFalse(DEFAULT_CONFIG["text_search_enhance_enabled"])

    def test_image_search_mode_order_puts_fast_paths_first(self):
        # Avoid importing gui_search_panel_state here (Qt / stub pollution across suites).
        self.assertEqual(
            _EXPECTED_IMAGE_SEARCH_MODES,
            ("frame", "video_discovery", "precise", "chunk"),
        )
        if _HAS_PYSIDE:
            import ast
            from pathlib import Path

            source = Path(__file__).resolve().parents[1] / "ui" / "windows" / "gui_search_panel_state.py"
            tree = ast.parse(source.read_text(encoding="utf-8"))
            found = None
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == "SearchPanelStateMixin":
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id == "IMAGE_SEARCH_MODES":
                                    found = ast.literal_eval(item.value)
            self.assertEqual(found, _EXPECTED_IMAGE_SEARCH_MODES)

    def test_image_mode_tips_and_deep_locate_hint_present(self):
        for texts in (TEXTS["zh"], TEXTS["en"]):
            for mode in _EXPECTED_IMAGE_SEARCH_MODES:
                self.assertTrue(str(texts.get(f"search_image_mode_{mode}_tip") or "").strip())
            self.assertTrue(str(texts.get("search_done_deep_locate_hint") or "").strip())
            self.assertTrue(str(texts.get("search_text_enhance_hint") or "").strip())
            self.assertTrue(str(texts.get("search_empty_try_text_enhance") or "").strip())
            self.assertTrue(str(texts.get("search_empty_try_image_mode") or "").strip())
            self.assertTrue(str(texts.get("search_empty_try_clearer_image") or "").strip())

    def test_settings_notes_refer_to_image_mode_not_old_toggle(self):
        zh = TEXTS["zh"]
        en = TEXTS["en"]
        self.assertIn("帧级", zh["settings_section_fast_image_search_note"])
        self.assertIn("视频择优", zh["settings_section_fast_image_search_note"])
        self.assertIn("深入搜索", zh["settings_section_precise_search_note"])
        self.assertNotIn("关闭时生效", zh["settings_section_fast_image_search_note"])
        self.assertIn("Frame", en["settings_section_fast_image_search_note"])
        self.assertIn("Best per video", en["settings_section_fast_image_search_note"])
        self.assertIn("Deep search", en["settings_section_precise_search_note"])
        self.assertNotIn("Deep search is OFF", en["settings_section_fast_image_search_note"])


@unittest.skipUnless(_HAS_PYSIDE, "PySide6 required for SearchController method tests")
class ResolveEmptySearchStatusTests(unittest.TestCase):
    def _make_fake(self, *, search_kind="text", is_text=True, precision="fast", discovery=False):
        from ui.controllers.search_controller import SearchController

        parent = types.SimpleNamespace(
            texts={
                "no_results": "No results",
                "search_empty_try_text_enhance": "Try Enhance",
                "search_empty_try_image_mode": "Try Deep search",
                "search_empty_try_clearer_image": "Clearer screenshot",
                "search_index_not_ready": "Index not ready",
                "search_dialogue_no_matches": "No subtitle matches",
            },
            current_img_path="",
        )
        config = types.SimpleNamespace(
            search_kind=search_kind,
            is_text=is_text,
            search_precision_mode=precision,
            video_discovery_enabled=discovery,
        )
        worker = types.SimpleNamespace(config=config, dialogue_status_message="")
        return types.SimpleNamespace(
            parent_window=parent,
            worker=worker,
            _resolve_empty_search_status=SearchController._resolve_empty_search_status,
        )

    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=False)
    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True)
    @patch("src.storage.config_store.get_local_model_asset_dirs", return_value={"base_dir": "x"})
    @patch("src.storage.config_store.get_text_search_enhance_enabled", return_value=False)
    def test_text_empty_hints_enhance_when_off(self, *_mocks):
        fake = self._make_fake()
        status = fake._resolve_empty_search_status(fake)
        self.assertIn("Try Enhance", status)

    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=False)
    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True)
    @patch("src.storage.config_store.get_local_model_asset_dirs", return_value={"base_dir": "x"})
    @patch("src.storage.config_store.get_text_search_enhance_enabled", return_value=True)
    def test_text_empty_skips_enhance_tip_when_on(self, *_mocks):
        fake = self._make_fake()
        status = fake._resolve_empty_search_status(fake)
        self.assertEqual(status, "No results")

    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=False)
    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True)
    @patch("src.storage.config_store.get_local_model_asset_dirs", return_value={"base_dir": "x"})
    def test_image_empty_hints_deep_search_in_fast_mode(self, *_mocks):
        fake = self._make_fake(search_kind="image", is_text=False)
        status = fake._resolve_empty_search_status(fake)
        self.assertIn("Try Deep search", status)

    @patch("src.storage.lance_search_index.lance_search_is_ready", return_value=False)
    @patch("src.storage.video_id_migration.legacy_npy_vectors_present", return_value=False)
    @patch("src.storage.config_store.get_local_model_asset_dirs", return_value={"base_dir": "x"})
    def test_index_not_ready_beats_mode_tips(self, *_mocks):
        fake = self._make_fake()
        status = fake._resolve_empty_search_status(fake)
        self.assertEqual(status, "Index not ready")


if __name__ == "__main__":
    unittest.main()
