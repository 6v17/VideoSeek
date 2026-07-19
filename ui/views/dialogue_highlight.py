"""UI-only dialogue match highlighting (cheap; runs on the visible result page)."""

from __future__ import annotations

from html import escape

from src.storage.dialogue_transcript_store import (
    _nfkc_casefold,
    build_dialogue_scatter_keys,
    normalize_dialogue_query,
)


def _highlight_color() -> str:
    try:
        from PySide6.QtWidgets import QApplication

        from ui.widgets.styles import THEME_COLORS_DARK, THEME_COLORS_LIGHT

        app = QApplication.instance()
        if app is not None:
            bg = app.palette().color(app.palette().ColorRole.Window)
            colors = THEME_COLORS_DARK if bg.lightness() < 128 else THEME_COLORS_LIGHT
            return str(colors.get("WARN") or colors.get("ACCENT") or "#e67e22")
    except Exception:
        pass
    return "#e67e22"


def _paint_flags(text: str, flags: list[bool], *, color: str) -> str:
    if not text:
        return ""
    if len(flags) != len(text):
        return escape(text)
    parts: list[str] = []
    index = 0
    while index < len(text):
        mark = flags[index]
        end = index + 1
        while end < len(text) and flags[end] == mark:
            end += 1
        chunk = escape(text[index:end])
        if mark:
            parts.append(
                f'<span style="color:{color};font-weight:700">{chunk}</span>'
            )
        else:
            parts.append(chunk)
        index = end
    return "".join(parts)


def _exact_flags(text: str, query: str) -> list[bool]:
    flags = [False] * len(text)
    needle = normalize_dialogue_query(query)
    if not needle or not text:
        return flags
    hay = text.casefold()
    needle_cf = needle.casefold()
    start = 0
    while True:
        at = hay.find(needle_cf, start)
        if at < 0:
            break
        for i in range(at, at + len(needle_cf)):
            if 0 <= i < len(flags):
                flags[i] = True
        start = at + max(1, len(needle_cf))
    return flags


def _fuzzy_flags(text: str, query: str) -> list[bool]:
    keys = set(build_dialogue_scatter_keys(query))
    flags = [False] * len(text)
    if not keys:
        return flags
    for i, ch in enumerate(text):
        folded = _nfkc_casefold(ch)
        if folded and folded in keys:
            flags[i] = True
    return flags


def highlight_dialogue_html(
    text: str,
    query: str,
    *,
    match_mode: str = "fuzzy",
    max_len: int = 40,
    color: str | None = None,
) -> str:
    """Escape ``text`` and color matched characters/spans for rich-text labels."""
    raw = str(text or "")
    if max_len > 0 and len(raw) > max_len:
        display = f"{raw[: max(1, max_len - 1)]}…"
    else:
        display = raw
    needle = str(query or "").strip()
    if not display or not needle:
        return escape(display)

    mode = str(match_mode or "exact").strip().lower()
    if mode in {"fuzzy", "tolerant", "approx", "keyword_fuzzy"}:
        flags = _fuzzy_flags(display, needle)
    else:
        flags = _exact_flags(display, needle)
        # Trailing ellipsis is never part of the match.
        if display.endswith("…") and flags:
            flags[-1] = False

    paint = color or _highlight_color()
    return _paint_flags(display, flags, color=paint)
