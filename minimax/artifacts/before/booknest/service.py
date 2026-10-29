"""Product search service.

The price-range parameters are intentionally a stub in the baseline snapshot:
the task's target tests fail until the feature is implemented.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .models import Product

_SORT_CHOICES = {"relevance", "price_asc", "price_desc", "rating_desc"}


def search_products(
    products: Iterable[Product],
    *,
    category: str | None = None,
    keyword: str | None = None,
    sort: str = "relevance",
    limit: int = 20,
    min_price: float | None = None,
    max_price: float | None = None,
) -> list[Product]:
    """Return products matching the supported filters.

    Existing behaviour: category matching is case-insensitive, keyword matching
    covers title/tags/category, and ``limit`` must be between 1 and 100.
    """

    if min_price is not None or max_price is not None:
        raise NotImplementedError("price-range filtering is not implemented yet")

    if sort not in _SORT_CHOICES:
        raise ValueError(f"unsupported sort: {sort}")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    items = list(products)

    if category:
        needle = category.strip().lower()
        items = [item for item in items if item.category.lower() == needle]

    if keyword:
        needle = keyword.strip().lower()
        items = [
            item
            for item in items
            if needle in item.title.lower()
            or needle in item.category.lower()
            or any(needle in tag.lower() for tag in item.tags)
        ]

    if sort == "price_asc":
        items.sort(key=lambda item: (item.price, item.id))
    elif sort == "price_desc":
        items.sort(key=lambda item: (-item.price, item.id))
    elif sort == "rating_desc":
        items.sort(key=lambda item: (-item.rating, item.id))
    else:
        items = _relevance_order(items, keyword)

    return items[:limit]


def _relevance_order(items: Sequence[Product], keyword: str | None) -> list[Product]:
    needle = (keyword or "").strip().lower()

    def key(item: Product) -> tuple[int, int, str]:
        title = item.title.lower()
        if needle and title.startswith(needle):
            rank = 0
        elif needle and needle in title:
            rank = 1
        elif needle:
            rank = 2
        else:
            rank = 3
        return (rank, -round(item.rating, 4), item.id)

    return sorted(items, key=key)
