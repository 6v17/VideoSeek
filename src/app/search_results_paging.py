"""Client-side pagination helpers for local search results."""

from __future__ import annotations

SEARCH_RESULTS_PAGE_SIZE = 20


def search_results_page_count(total_count: int, page_size: int = SEARCH_RESULTS_PAGE_SIZE) -> int:
    total = max(0, int(total_count))
    size = max(1, int(page_size))
    if total <= 0:
        return 0
    return (total + size - 1) // size


def visible_end_index(
    count: int,
    scroll_value: int,
    scroll_maximum: int,
    viewport_h: int,
    row_h: int,
    cols: int = 1,
) -> int:
    """Furthest 0-based row inside the viewport.

    A scroll value of 0 is the first screen, even when the scrollbar range is
    still settling after a view rebuild. That rebuild used to look like the
    user had jumped to the end.
    """
    total = max(0, int(count))
    if total <= 0:
        return -1
    columns = max(1, int(cols))
    view_h = max(1, int(viewport_h))
    if int(scroll_maximum) <= 0 or int(scroll_value) <= 0:
        rows = max(1, view_h // max(1, int(row_h)))
        return min(total - 1, columns * rows - 1)
    span = int(scroll_maximum) + view_h
    end = int(scroll_value) + view_h
    return min(total - 1, max(0, int(end / max(1, span) * total) - 1))


def slice_search_results_page(
    results,
    page_index: int,
    page_size: int = SEARCH_RESULTS_PAGE_SIZE,
):
    page = max(0, int(page_index))
    size = max(1, int(page_size))
    start = page * size
    end = start + size
    return list(results or [])[start:end]
