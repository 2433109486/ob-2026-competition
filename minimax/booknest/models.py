"""Domain model for the BookNest sample catalogue."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    category: str
    price: float
    rating: float
    stock: int
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Product":
        return cls(
            id=str(raw["id"]),
            title=str(raw["title"]),
            category=str(raw["category"]),
            price=float(raw["price"]),
            rating=float(raw["rating"]),
            stock=int(raw["stock"]),
            tags=tuple(str(tag) for tag in raw.get("tags", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data
