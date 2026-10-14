"""Ratchet: MainWindow gui*.py cross-file ``self._`` coupling must not grow.

DeepSeek-style scans of the whole repo exaggerate coupling. Inside
``ui/windows/gui*.py`` almost all multi-file ``self._`` names are intentional
mixin hooks (``_refresh_*`` / ``_sync_*``) or a handful of shared flags/queues.

This ratchet freezes:
- how many attrs are touched from 2+ gui mixin files (B+C+D)
- how many are C (3–4 files) or D (5+ files)

A-class (single-file) attrs are ignored — moving them is cosmetics.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI_DIR = ROOT / "ui" / "windows"
# Recomputed when the detector ships; must not grow afterward.
CROSS_FILE_ATTR_BASELINE = 120  # B+C+D
C_ATTR_BASELINE = 24
D_ATTR_BASELINE = 3

_OWNER_NAMES = frozenset({"self", "parent_window", "window", "main_window", "host", "owner"})
_INDIRECT_OWNERS = frozenset({"parent_window", "window", "main_window"})


class _AttrVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: dict[str, int] = defaultdict(int)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_") and not node.attr.startswith("__"):
            base = node.value
            name = None
            if isinstance(base, ast.Name) and base.id in _OWNER_NAMES:
                name = node.attr
            elif (
                isinstance(base, ast.Attribute)
                and base.attr in _INDIRECT_OWNERS
                and isinstance(base.value, ast.Name)
                and base.value.id == "self"
            ):
                name = node.attr
            if name:
                self.hits[name] += 1
        self.generic_visit(node)


def _bucket(file_count: int) -> str:
    if file_count <= 1:
        return "A"
    if file_count == 2:
        return "B"
    if file_count <= 4:
        return "C"
    return "D"


def classify_gui_mixin_attrs() -> dict[str, list[dict]]:
    access: dict[str, set[str]] = defaultdict(set)
    for path in sorted(GUI_DIR.glob("gui*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _AttrVisitor()
        visitor.visit(tree)
        for attr in visitor.hits:
            access[attr].add(path.name)

    buckets: dict[str, list[dict]] = defaultdict(list)
    for attr, files in access.items():
        buckets[_bucket(len(files))].append(
            {"attr": attr, "files": sorted(files), "file_count": len(files)}
        )
    for key in buckets:
        buckets[key].sort(key=lambda row: (-row["file_count"], row["attr"]))
    return dict(buckets)


def test_gui_mixin_cross_file_attrs_do_not_grow():
    buckets = classify_gui_mixin_attrs()
    cross = len(buckets.get("B", [])) + len(buckets.get("C", [])) + len(buckets.get("D", []))
    c_count = len(buckets.get("C", []))
    d_count = len(buckets.get("D", []))
    assert cross <= CROSS_FILE_ATTR_BASELINE, (
        f"cross-file gui mixin attrs grew: {cross} > {CROSS_FILE_ATTR_BASELINE}; "
        f"C={c_count} D={d_count}. Prefer feature-local state; do not add new "
        f"shared self._ fields across gui*.py without lowering another."
    )
    assert c_count <= C_ATTR_BASELINE, (
        f"C-class (3–4 file) attrs grew: {c_count} > {C_ATTR_BASELINE}: "
        f"{[row['attr'] for row in buckets.get('C', [])]}"
    )
    assert d_count <= D_ATTR_BASELINE, (
        f"D-class (5+ file) attrs grew: {d_count} > {D_ATTR_BASELINE}: "
        f"{[row['attr'] for row in buckets.get('D', [])]}"
    )


def test_deepseek_claimed_d_attrs_are_not_mainwindow_mixin_hotspots():
    """Those names were whole-repo noise, not MainWindow mixin D-class."""
    buckets = classify_gui_mixin_attrs()
    known = {row["attr"] for key in "ABCD" for row in buckets.get(key, [])}
    for name in ("_result", "_texts", "_is_dark"):
        assert name not in known or name in {row["attr"] for row in buckets.get("A", [])}, (
            f"{name} unexpectedly became a cross-file MainWindow mixin attr"
        )
