"""Ratchet: broad except handlers must not return an empty sentinel in silence.

Narrow catches (ValueError while parsing, OSError while deleting a temp file)
may still return a fallback. ``except Exception`` / bare ``except`` that returns
``None`` / ``[]`` / ``0`` / ``""`` must call ``note_swallowed``, log, emit a
failure signal, or raise. A bare ``return`` only leaves the handler; it is not
an empty sentinel.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src", "ui")
SILENT_EXCEPT_BASELINE = 0


def _is_empty_sentinel(node: ast.AST | None) -> bool:
    # ``return`` with no value just exits. ``return None`` is still a sentinel.
    if node is None:
        return False
    if isinstance(node, ast.Constant) and node.value in (None, 0, False, ""):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)) and not node.elts:
        return True
    if isinstance(node, ast.Dict) and not node.keys:
        return True
    return False


def _is_broad(handler: ast.ExceptHandler) -> bool:
    kind = handler.type
    if kind is None:
        return True
    if isinstance(kind, ast.Name) and kind.id in {"Exception", "BaseException"}:
        return True
    if isinstance(kind, ast.Tuple):
        names = [elt.id for elt in kind.elts if isinstance(elt, ast.Name)]
        if len(names) != len(kind.elts):
            return False
        return any(name in {"Exception", "BaseException"} for name in names)
    return False


def _is_log_helper(name: str) -> bool:
    lowered = str(name or "")
    return lowered.startswith("_log") or lowered.startswith("log_")


def _emits_failure(func: ast.Attribute) -> bool:
    if func.attr != "emit":
        return False
    owner = func.value
    signal_name = ""
    if isinstance(owner, ast.Attribute):
        signal_name = owner.attr
    elif isinstance(owner, ast.Name):
        signal_name = owner.id
    lowered = signal_name.lower()
    return "fail" in lowered or "error" in lowered


def _is_visible(handler: ast.ExceptHandler) -> bool:
    if any(isinstance(stmt, ast.Raise) for stmt in handler.body):
        return True
    for node in ast.walk(ast.Module(body=list(handler.body), type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and (func.id == "note_swallowed" or _is_log_helper(func.id)):
            return True
        if isinstance(func, ast.Attribute) and (
            _is_log_helper(func.attr)
            or _emits_failure(func)
            or func.attr
            in {
                "debug",
                "info",
                "warning",
                "error",
                "exception",
                "critical",
                "log",
                "warn",
                "show_error_dialog",
            }
        ):
            return True
    return False


def _returns_sentinel(handler: ast.ExceptHandler) -> bool:
    body = ast.Module(body=list(handler.body), type_ignores=[])
    return any(isinstance(node, ast.Return) and _is_empty_sentinel(node.value) for node in ast.walk(body))


def silent_except_sites() -> list[str]:
    sites: list[str] = []
    for folder in SCAN_ROOTS:
        base = ROOT / folder
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeError):
                continue
            rel = path.relative_to(ROOT).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if _is_broad(node) and _returns_sentinel(node) and not _is_visible(node):
                    sites.append(f"{rel}:{node.lineno}")
    return sites


def test_silent_except_count_does_not_grow():
    sites = silent_except_sites()
    assert len(sites) <= SILENT_EXCEPT_BASELINE, (
        f"{len(sites)} broad except handlers still hide a failure. "
        "Call note_swallowed, log, or raise. Sites:\n" + "\n".join(sites[:40])
    )
