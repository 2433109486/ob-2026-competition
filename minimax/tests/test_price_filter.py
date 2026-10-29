"""Target acceptance tests for price-range filtering (BOOK-SPEC-001).

These tests MUST fail before the feature is implemented and pass afterwards.
"""

from __future__ import annotations

import pytest

from booknest.service import search_products


def _ids(items):
    return [item.id for item in items]


# spec: BOOK-SPEC-001
# kind: target
def test_price_range_is_inclusive(products):
    items = search_products(
        products,
        min_price=58.0,
        max_price=99.0,
        sort="price_asc",
    )
    assert _ids(items) == ["BK-1005", "BK-1001", "BK-1006", "BK-1003"]


# spec: BOOK-SPEC-001
# kind: target
def test_max_price_zero_selects_free_item(products):
    items = search_products(products, max_price=0.0)
    assert _ids(items) == ["BK-1007"]


# spec: BOOK-SPEC-001
# kind: target
def test_min_price_only_filters_lower_bound(products):
    items = search_products(products, min_price=128.0, sort="price_asc")
    assert _ids(items) == ["BK-1002", "BK-1008", "BK-1004"]


# spec: BOOK-SPEC-001
# kind: target
def test_equal_min_and_max_selects_exact_boundary(products):
    items = search_products(products, min_price=99.0, max_price=99.0)
    assert _ids(items) == ["BK-1003"]


# spec: BOOK-SPEC-001
# kind: target
def test_empty_range_returns_empty_list(products):
    assert search_products(products, min_price=500.0) == []


# spec: BOOK-SPEC-001
# kind: target
def test_negative_price_is_rejected(products):
    with pytest.raises(ValueError, match="min_price"):
        search_products(products, min_price=-0.01)


# spec: BOOK-SPEC-001
# kind: target
def test_inverted_range_is_rejected(products):
    with pytest.raises(ValueError, match="min_price"):
        search_products(products, min_price=100.0, max_price=50.0)
