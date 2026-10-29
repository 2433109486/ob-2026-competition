"""Regression tests protecting existing BookNest behaviour (BOOK-SPEC-002)."""

from __future__ import annotations

from conftest import get_json
from booknest.service import search_products


def _ids(items):
    return [item.id for item in items]


# spec: BOOK-SPEC-002
# kind: regression
def test_category_filter_is_case_insensitive(products):
    items = search_products(products, category="technology")
    assert {item.id for item in items} == {"BK-1002", "BK-1003", "BK-1004", "BK-1008"}


# spec: BOOK-SPEC-002
# kind: regression
def test_keyword_matches_title_and_tags(products):
    items = search_products(products, keyword="programming")
    assert {item.id for item in items} == {"BK-1002", "BK-1003", "BK-1008"}


# spec: BOOK-SPEC-002
# kind: regression
def test_price_desc_sort_is_unchanged(products):
    items = search_products(products, sort="price_desc", limit=3)
    assert _ids(items) == ["BK-1004", "BK-1008", "BK-1002"]


# spec: BOOK-SPEC-002
# kind: regression
def test_default_search_returns_all_seed_rows(products):
    assert len(search_products(products)) == 10


# spec: BOOK-SPEC-002
# kind: regression
def test_no_price_parameters_keeps_previous_result(products):
    baseline = search_products(products, category="Business", keyword="startup")
    explicit_none = search_products(
        products,
        category="Business",
        keyword="startup",
        min_price=None,
        max_price=None,
    )
    assert _ids(baseline) == _ids(explicit_none)


# spec: BOOK-SPEC-002
# kind: regression
def test_limit_is_validated(products):
    try:
        search_products(products, limit=0)
    except ValueError as error:
        assert "limit" in str(error)
    else:
        raise AssertionError("limit=0 must raise ValueError")


# spec: BOOK-SPEC-002
# kind: regression
def test_unknown_category_returns_empty(products):
    assert search_products(products, category="NoSuchCategory") == []


# spec: BOOK-SPEC-002
# kind: regression
def test_api_health(live_api):
    status, body = get_json(live_api, "/health")
    assert status == 200
    assert body == {"status": "ok"}


# spec: BOOK-SPEC-002
# spec: BOOK-SPEC-003
# kind: regression
def test_api_keeps_existing_query_contract(live_api):
    status, body = get_json(live_api, "/api/products?category=technology&limit=2")
    assert status == 200
    assert body["count"] == 2
    assert all(item["category"] == "Technology" for item in body["items"])
