# SDD Context — BOOK-001: 为 BookNest 商品搜索增加价格区间筛选

- Context run: `ctx-20261029164214-58839c`
- Code version: `sha256:ed92b9380923766f0b0f779ae89131d08249d3aa3b5b879fda0244ff42f56f04`
- Assembled: 2026-10-29T08:42:14.604168+00:00

## 1. Task

Source: `tasks/BOOK-001.md`

# 任务 BOOK-001

## 要改什么

为 `booknest.service.search_products` 增加 `min_price` / `max_price` 两个可选
参数，按闭区间过滤商品；在 `GET /api/products` 暴露同名查询参数，非法价格
或倒置区间返回 HTTP 400。

## 必须保持什么

1. 分类筛选仍大小写不敏感，关键词仍匹配标题/分类/标签。
2. `price_asc`、`price_desc`、`rating_desc` 的既有排序不变。
3. 不传价格参数时，结果与改动前逐项一致。
4. `limit` 仍校验 1..100，`/health` 仍返回 200。

## 验收命令

```bash
python -m pytest -q
```

## 2. Applicable specifications

### BOOK-SPEC-001 — 商品价格区间筛选 (v2)

- Source: `specs/BOOK-SPEC-001-price-filter.md`
- Status: `active`
- Why selected: vector=0.916, text=1.000, tags=api,filter,price,search, symbol=booknest.service.search_products
- Applies to: `booknest.service.search_products`, `booknest.api.ProductRequestHandler`

#### REQ-001 区间上下界都包含

`search_products` MUST 接受可选参数 `min_price` 与 `max_price`，并按**闭区间**
过滤：`min_price <= product.price <= max_price`。

#### REQ-002 只给一侧边界

只给 `min_price` 时 MUST 过滤掉更低价格的商品；只给 `max_price` 时 MUST
过滤掉更高价格的商品。两个参数都为空时结果 MUST 与引入该功能前完全一致。

#### REQ-003 非法价格区间

`min_price` 或 `max_price` 为负数，或 `min_price > max_price` 时 MUST 抛出
`ValueError`，错误信息中 MUST 含 `min_price`。

#### REQ-004 边界与空结果

`min_price == max_price` MUST 返回恰好等于该价格的商品；区间内没有商品时
MUST 返回空列表，不得抛出异常，也不得回退到未过滤结果。价格 `0` MUST 被当作
合法边界值，不得解释为“未设置”。

#### REQ-005 过滤、排序、截断的顺序

实现 MUST 先按价格与既有条件过滤，再执行排序，最后应用 `limit`；不得先截断
再过滤，否则分页结果会漏掉命中项。

### BOOK-SPEC-003 — 商品查询 HTTP 接口行为 (v1)

- Source: `specs/BOOK-SPEC-003-api-contract.md`
- Status: `active`
- Why selected: vector=0.834, text=1.000, tags=api,filter,price, symbol=booknest.api.ProductRequestHandler
- Applies to: `booknest.api.ProductRequestHandler`, `booknest.api.create_server`

#### REQ-001 查询参数

`GET /api/products` MUST 接受 `min_price` 与 `max_price` 查询参数，并把它们
传给 `search_products`。

#### REQ-002 参数校验

`min_price` / `max_price` 不是数字、为负数或区间倒置时，接口 MUST 返回
HTTP 400，响应体 MUST 是含 `error` 字段的 JSON。

#### REQ-003 成功响应

成功时 MUST 返回 HTTP 200，响应体为 `{"items": [...], "count": N}`；空结果
MUST 是 200 且 `count` 为 0。

#### REQ-004 健康检查

`GET /health` MUST 返回 HTTP 200 与 `{"status": "ok"}`。

### BOOK-SPEC-002 — 既有搜索行为兼容约束 (v1)

- Source: `specs/BOOK-SPEC-002-search-compatibility.md`
- Status: `active`
- Why selected: vector=0.856, text=1.000, tags=regression,search, symbol=booknest.service.search_products
- Applies to: `booknest.service.search_products`, `booknest.api.ProductRequestHandler`

#### REQ-001 分类筛选

`category` MUST 大小写不敏感地精确匹配商品分类。

#### REQ-002 关键词筛选

`keyword` MUST 在标题、分类和标签中做大小写不敏感的子串匹配。

#### REQ-003 排序与数量

`price_asc`、`price_desc`、`rating_desc` MUST 保持原有排序；`limit` MUST
维持在 1 到 100 之间，越界时抛出 `ValueError`。

#### REQ-004 无价格参数时结果不变

不传 `min_price` / `max_price` 时，搜索结果 MUST 与改动前逐项一致。

### BOOK-DEC-001 — 价格边界与空结果决策 (v1)

- Source: `specs/BOOK-DEC-001-price-boundaries.md`
- Status: `active`
- Why selected: vector=0.599, text=1.000, tags=filter,price, symbol=booknest.service.search_products
- Applies to: `booknest.service.search_products`

#### DEC-001 闭区间

价格筛选采用闭区间，`max_price=99` 必须包含价格为 99 的商品。

#### DEC-002 零价商品

`max_price=0` 是合法输入，必须能筛出价格为 0 的商品；不得把 0 当成“未设置”。

#### DEC-003 空结果

没有命中商品是正常业务结果，服务返回空列表，HTTP 返回 200 与 `count=0`。

## 3. Code to inspect or modify

### `booknest/api.py` :: `booknest.api.create_server`

- Lines: 103-113 · kind: `function`
- Why selected: declared in spec applies_to via seekdb.links

```python
def create_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    products: list[Product] | None = None,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundProductRequestHandler",
        (ProductRequestHandler,),
        {"products": list(products if products is not None else load_products())},
    )
    return ThreadingHTTPServer((host, port), handler)
```

### `booknest/api.py` :: `booknest.api.ProductRequestHandler`

- Lines: 20-70 · kind: `class`
- Why selected: declared in spec applies_to via seekdb.links

```python
class ProductRequestHandler(BaseHTTPRequestHandler):
    """Serve two read-only routes: /health and /api/products."""

    products: list[Product] = []
    server_version = "BookNest/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path != "/api/products":
            self._send_json(404, {"error": "not found"})
            return

        params = parse_qs(parsed.query, keep_blank_values=True)
        try:
            category = _single(params, "category")
            keyword = _single(params, "keyword")
            sort = _single(params, "sort") or "relevance"
            limit = _parse_int(_single(params, "limit"), default=20, field="limit")
            min_price = _parse_float(_single(params, "min_price"), field="min_price")
            max_price = _parse_float(_single(params, "max_price"), field="max_price")
            items = search_products(
                self.products,
                category=category,
                keyword=keyword,
                sort=sort,
                limit=limit,
                min_price=min_price,
                max_price=max_price,
            )
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
            return
        except NotImplementedError as error:
            self._send_json(500, {"error": str(error)})
            return

        self._send_json(200, {"items": [item.to_dict() for item in items], "count": len(items)})

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Keep test output clean."""
```

### `booknest/service.py` :: `booknest.service.search_products`

- Lines: 13-79 · kind: `function`
- Why selected: declared in spec applies_to via seekdb.links

```python
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
```

## 4. Tests for functional and compatibility verification

### `tests/test_api_price_filter.py::test_api_accepts_zero_upper_bound` (target)

- Specs: BOOK-SPEC-003, BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_api_accepts_zero_upper_bound(live_api):
    status, body = get_json(live_api, "/api/products?max_price=0")
    assert status == 200
    assert body["count"] == 1
    assert body["items"][0]["id"] == "BK-1007"
```

### `tests/test_api_price_filter.py::test_api_filters_by_price_range` (target)

- Specs: BOOK-SPEC-003, BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_api_filters_by_price_range(live_api):
    status, body = get_json(live_api, "/api/products?min_price=58&max_price=99&sort=price_asc")
    assert status == 200
    assert body["count"] == 4
    assert [item["id"] for item in body["items"]] == ["BK-1005", "BK-1001", "BK-1006", "BK-1003"]
```

### `tests/test_api_price_filter.py::test_api_rejects_inverted_range` (target)

- Specs: BOOK-SPEC-003, BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_api_rejects_inverted_range(live_api):
    status, body = get_json(live_api, "/api/products?min_price=100&max_price=50")
    assert status == 400
    assert "min_price" in body["error"]
```

### `tests/test_api_price_filter.py::test_api_rejects_non_numeric_price` (target)

- Specs: BOOK-SPEC-003, BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_api_rejects_non_numeric_price(live_api):
    status, body = get_json(live_api, "/api/products?min_price=cheap")
    assert status == 400
    assert "min_price" in body["error"]
```

### `tests/test_price_filter.py::test_empty_range_returns_empty_list` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_empty_range_returns_empty_list(products):
    assert search_products(products, min_price=500.0) == []
```

### `tests/test_price_filter.py::test_equal_min_and_max_selects_exact_boundary` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_equal_min_and_max_selects_exact_boundary(products):
    items = search_products(products, min_price=99.0, max_price=99.0)
    assert _ids(items) == ["BK-1003"]
```

### `tests/test_price_filter.py::test_inverted_range_is_rejected` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_inverted_range_is_rejected(products):
    with pytest.raises(ValueError, match="min_price"):
        search_products(products, min_price=100.0, max_price=50.0)
```

### `tests/test_price_filter.py::test_max_price_zero_selects_free_item` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_max_price_zero_selects_free_item(products):
    items = search_products(products, max_price=0.0)
    assert _ids(items) == ["BK-1007"]
```

### `tests/test_price_filter.py::test_min_price_only_filters_lower_bound` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_min_price_only_filters_lower_bound(products):
    items = search_products(products, min_price=128.0, sort="price_asc")
    assert _ids(items) == ["BK-1002", "BK-1008", "BK-1004"]
```

### `tests/test_price_filter.py::test_negative_price_is_rejected` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_negative_price_is_rejected(products):
    with pytest.raises(ValueError, match="min_price"):
        search_products(products, min_price=-0.01)
```

### `tests/test_price_filter.py::test_price_range_is_inclusive` (target)

- Specs: BOOK-SPEC-001
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_price_range_is_inclusive(products):
    items = search_products(
        products,
        min_price=58.0,
        max_price=99.0,
        sort="price_asc",
    )
    assert _ids(items) == ["BK-1005", "BK-1001", "BK-1006", "BK-1003"]
```

### `tests/test_search_existing.py::test_api_health` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_api_health(live_api):
    status, body = get_json(live_api, "/health")
    assert status == 200
    assert body == {"status": "ok"}
```

### `tests/test_search_existing.py::test_api_keeps_existing_query_contract` (regression)

- Specs: BOOK-SPEC-002, BOOK-SPEC-003
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_api_keeps_existing_query_contract(live_api):
    status, body = get_json(live_api, "/api/products?category=technology&limit=2")
    assert status == 200
    assert body["count"] == 2
    assert all(item["category"] == "Technology" for item in body["items"])
```

### `tests/test_search_existing.py::test_category_filter_is_case_insensitive` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_category_filter_is_case_insensitive(products):
    items = search_products(products, category="technology")
    assert {item.id for item in items} == {"BK-1002", "BK-1003", "BK-1004", "BK-1008"}
```

### `tests/test_search_existing.py::test_default_search_returns_all_seed_rows` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_default_search_returns_all_seed_rows(products):
    assert len(search_products(products)) == 10
```

### `tests/test_search_existing.py::test_keyword_matches_title_and_tags` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_keyword_matches_title_and_tags(products):
    items = search_products(products, keyword="programming")
    assert {item.id for item in items} == {"BK-1002", "BK-1003", "BK-1008"}
```

### `tests/test_search_existing.py::test_limit_is_validated` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_limit_is_validated(products):
    try:
        search_products(products, limit=0)
    except ValueError as error:
        assert "limit" in str(error)
    else:
        raise AssertionError("limit=0 must raise ValueError")
```

### `tests/test_search_existing.py::test_no_price_parameters_keeps_previous_result` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
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
```

### `tests/test_search_existing.py::test_price_desc_sort_is_unchanged` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_price_desc_sort_is_unchanged(products):
    items = search_products(products, sort="price_desc", limit=3)
    assert _ids(items) == ["BK-1004", "BK-1008", "BK-1002"]
```

### `tests/test_search_existing.py::test_unknown_category_returns_empty` (regression)

- Specs: BOOK-SPEC-002
- Why selected: linked from an applicable spec via seekdb.links

```python
def test_unknown_category_returns_empty(products):
    assert search_products(products, category="NoSuchCategory") == []
```

## 5. Saved task state (PowerContext)

- Source: `powercontext` · status: `loaded`
- Artifact: `art_95eea80d85e4419bbb706164b51f5d8e` revision `1` state_version `0`
- Checkpoint seq: 3

### Completed
- [x] ingested v1 specs, code, and tests into seekdb
- [x] built the first SDD context bundle
- [x] applied the MiniMax-generated patch to service.py and api.py
- [x] all functional and regression tests pass
- [x] updated BOOK-SPEC-001 to v2, re-ingested it, and confirmed the context uses REQ-005

### Todo
- (none)

### Verification results
- `D:\agent\sandbox\comp\comp\minimax\.venv\Scripts\python.exe -m pytest -q` → exit `1` · 11 failed, 9 passed in 3.18s
- `D:\agent\sandbox\comp\comp\minimax\.venv\Scripts\python.exe -m pytest -q` → exit `0` · 20 passed in 3.13s
- `sdd_context context --task tasks/BOOK-001.md` → exit `0` · context returned BOOK-SPEC-001 v2 with REQ-005

## 6. Retrieval provenance

- Engine: `seekdb` database `sdd_context`
- Embedding provider: `minimax` (296 tokens)
- Queries executed against seekdb:
  - rows=4 · SELECT doc_key, doc_type, source_path, title, version, status, tags, metadata_json, content, cosine_distance(embedding, %s) AS vector_distance, MATCH(search_text) AGAINST(%s) AS te
  - rows=7 · SELECT d.doc_key, d.doc_type, d.source_path, d.title, d.version, d.status, d.tags, d.metadata_json, d.content, 0.0 AS vector_distance, 0.0 AS text_score FROM documents d JOIN links
  - rows=7 · SELECT doc_key, doc_type, source_path, title, version, status, tags, metadata_json, content, cosine_distance(embedding, %s) AS vector_distance, MATCH(search_text) AGAINST(%s) AS te
  - rows=25 · SELECT d.doc_key, d.doc_type, d.source_path, d.title, d.version, d.status, d.tags, d.metadata_json, d.content, 0.0 AS vector_distance, 0.0 AS text_score FROM documents d JOIN links
  - rows=14 · SELECT d.doc_key, d.doc_type, d.source_path, d.title, d.version, d.status, d.tags, d.metadata_json, d.content, 0.0 AS vector_distance, 0.0 AS text_score FROM documents d JOIN links
  - rows=20 · SELECT doc_key, doc_type, source_path, title, version, status, tags, metadata_json, content, cosine_distance(embedding, %s) AS vector_distance, MATCH(search_text) AGAINST(%s) AS te
