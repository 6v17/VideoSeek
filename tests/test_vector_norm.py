"""Embedding normalization stays off the faiss import path."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import numpy as np

from src.core.vector_norm import normalize_vectors

_ROOT = Path(__file__).resolve().parents[1]
_SEARCH_MODULES = (
    "src/storage/lance_search_index.py",
    "src/storage/lance_dialogue_search.py",
    "src/services/search_query.py",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


class VectorNormTests(unittest.TestCase):
    def test_rows_are_unit_length(self):
        raw = np.array([[3.0, 0.0], [0.0, 4.0]], dtype=np.float32)
        normalized = normalize_vectors(raw)
        norms = np.linalg.norm(normalized, axis=1)
        np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-6)

    def test_one_dimensional_input_becomes_one_row(self):
        normalized = normalize_vectors(np.array([0.0, 5.0], dtype=np.float32))
        self.assertEqual(normalized.shape, (1, 2))
        self.assertAlmostEqual(float(normalized[0, 1]), 1.0)

    def test_search_modules_do_not_import_faiss_index(self):
        for relative in _SEARCH_MODULES:
            modules = _imported_modules(_ROOT / relative)
            self.assertNotIn("src.core.faiss_index", modules, relative)
            self.assertNotIn("faiss", modules, relative)

    def test_lance_store_normalizes_without_faiss(self):
        source = (_ROOT / "src/storage/lance_store.py").read_text(encoding="utf-8")
        self.assertNotIn("faiss_index import _normalize_vectors", source)
        self.assertIn("vector_norm import normalize_vectors", source)
        preset = (_ROOT / "src/services/search_preset_query.py").read_text(encoding="utf-8")
        self.assertNotIn("faiss_index import _normalize_vectors", preset)
        self.assertIn("vector_norm import normalize_vectors", preset)
