"""Target acceptance tests for the HTTP price-range contract (BOOK-SPEC-003)."""

from __future__ import annotations

from conftest import get_json


# spec: BOOK-SPEC-003
# spec: BOOK-SPEC-001
# kind: target
def test_api_filters_by_price_range(live_api):
    status, body = get_json(live_api, "/api/products?min_price=58&max_price=99&sort=price_asc")
    assert status == 200
    assert body["count"] == 4
    assert [item["id"] for item in body["items"]] == ["BK-1005", "BK-1001", "BK-1006", "BK-1003"]


# spec: BOOK-SPEC-003
# kind: target
def test_api_rejects_non_numeric_price(live_api):
    status, body = get_json(live_api, "/api/products?min_price=cheap")
    assert status == 400
    assert "min_price" in body["error"]


# spec: BOOK-SPEC-003
# kind: target
def test_api_rejects_inverted_range(live_api):
    status, body = get_json(live_api, "/api/products?min_price=100&max_price=50")
    assert status == 400
    assert "min_price" in body["error"]


# spec: BOOK-SPEC-003
# spec: BOOK-SPEC-001
# kind: target
def test_api_accepts_zero_upper_bound(live_api):
    status, body = get_json(live_api, "/api/products?max_price=0")
    assert status == 200
    assert body["count"] == 1
    assert body["items"][0]["id"] == "BK-1007"
