"""Minimal HTTP JSON API for the BookNest catalogue.

Only the Python standard library is used so the sample can run in a clean
environment. ``create_server`` is used by the acceptance tests with port 0.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .models import Product
from .repository import load_products
from .service import search_products


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
            items = search_products(
                self.products,
                category=category,
                keyword=keyword,
                sort=sort,
                limit=limit,
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


def _single(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"{name} must be supplied at most once")
    return values[0]


def _parse_int(raw: str | None, *, default: int, field: str) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{field} must be an integer") from error


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
