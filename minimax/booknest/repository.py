"""JSON-backed product repository used by the sample service."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import Product

_SEED_PATH = Path(__file__).resolve().parent / "seed" / "products.json"


def load_products(path: Path | None = None) -> list[Product]:
    seed_path = path or _SEED_PATH
    with seed_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        raise ValueError("product seed must be a JSON array")
    return [Product.from_dict(item) for item in raw]


def find_by_id(products: Iterable[Product], product_id: str) -> Product | None:
    for product in products:
        if product.id == product_id:
            return product
    return None
