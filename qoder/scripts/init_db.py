"""Initialise seekdb, import the seed corpus, and seed PowerContext memories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory import client as memory_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop and recreate all seekdb tables")
    parser.add_argument("--no-memory", action="store_true", help="skip PowerContext seed")
    args = parser.parse_args()

    settings.ensure_runtime_dirs()
    result = db.seed_database(force=args.reset)
    print("seekdb:", json.dumps(result, ensure_ascii=False))
    if not args.no_memory:
        papers = db.fetch_papers(limit=100)
        memory_result = memory_client.seed_demo_memories(papers)
        print("powercontext:", json.dumps(memory_result, ensure_ascii=False, default=str))
    counts = db.table_counts()
    print("counts:", json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
