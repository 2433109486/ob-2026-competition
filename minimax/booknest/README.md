# BookNest sample service

A tiny, dependency-free catalogue service used to validate the SDD context
module with a real, local code change.

## Run

```bash
python -m booknest.cli search --keyword programming --sort rating_desc
python -m booknest.cli serve --port 8080
curl "http://127.0.0.1:8080/api/products?category=technology&sort=price_asc"
```

## Test

```bash
python -m pytest -q
```

The baseline snapshot intentionally leaves price-range filtering unimplemented:
`tests/test_price_filter.py` and `tests/test_api_price_filter.py` fail, while
`tests/test_search_existing.py` passes. After the MiniMax-assisted change all
three files pass.
