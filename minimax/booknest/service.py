"""Product search service."""

from __future__ import annotations

import math
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
    Price filtering uses inclusive lower and upper bounds.
    """

    if min_price is not None or max_price is not None:
        if any(
            value is not None and not math.isfinite(value)
            for value in (min_price, max_price)
        ):
            raise ValueError("min_price and max_price must be finite numbers")
        if (min_price is not None and min_price < 0) or (
            max_price is not None and max_price < 0
        ):
            raise ValueError("min_price and max_price must be non-negative")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError("min_price must be less than or equal to max_price")

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

    if min_price is not None:
        items = [item for item in items if item.price >= min_price]

    if max_price is not None:
        items = [item for item in items if item.price <= max_price]

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
