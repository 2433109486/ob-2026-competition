"""Shared fixtures for the BookNest acceptance tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from booknest.api import create_server
from booknest.models import Product
from booknest.repository import load_products


@pytest.fixture(scope="session")
def products() -> list[Product]:
    return load_products()


@pytest.fixture()
def live_api() -> Iterator[str]:
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def get_json(base_url: str, path: str) -> tuple[int, dict[str, Any]]:
    request = Request(base_url + path, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))
