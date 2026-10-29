"""Command-line entry points for the BookNest sample."""

from __future__ import annotations

import argparse
import json

from .api import create_server
from .repository import load_products
from .service import search_products


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="booknest")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search the catalogue")
    search.add_argument("--category")
    search.add_argument("--keyword")
    search.add_argument("--sort", default="relevance")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--min-price", type=float, dest="min_price")
    search.add_argument("--max-price", type=float, dest="max_price")

    serve = sub.add_parser("serve", help="run the JSON API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "search":
        items = search_products(
            load_products(),
            category=args.category,
            keyword=args.keyword,
            sort=args.sort,
            limit=args.limit,
            min_price=args.min_price,
            max_price=args.max_price,
        )
        print(json.dumps({"items": [item.to_dict() for item in items], "count": len(items)}, ensure_ascii=False, indent=2))
        return 0

    server = create_server(args.host, args.port)
    host, port = server.server_address[:2]
    print(f"BookNest API listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
