"""Client-side pagination helpers for local search results."""

from __future__ import annotations

SEARCH_RESULTS_PAGE_SIZE = 20


def search_results_page_count(total_count: int, page_size: int = SEARCH_RESULTS_PAGE_SIZE) -> int:
    total = max(0, int(total_count))
    size = max(1, int(page_size))
    if total <= 0:
        return 0
    return (total + size - 1) // size


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
