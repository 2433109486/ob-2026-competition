"""初始化 / 自检 CLI。

    python -m app.cli init --recreate   # 建库建表 + 重建法典索引
    python -m app.cli seed              # 只补齐法典数据
    python -m app.cli check             # 打印条数、标签、样例检索
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import settings
from .db import Store
from .embeddings import Embedder
from .powercontext import PowerContextClient
from .statutes import STATUTES


def build() -> tuple[Store, PowerContextClient]:
    embedder = Embedder(
        settings.embedding_backend,
        settings.embedding_dim,
        settings.embedding_base_url,
        settings.embedding_api_key,
        settings.embedding_model,
    )
    store = Store(settings, embedder)
    return store, PowerContextClient(settings, store)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="absurd-court")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="建库建表并写入法典")
    init.add_argument("--recreate", action="store_true", help="先删表再建（会清空判例与档案）")
    init.add_argument("--force", action="store_true", help="强制重写法典向量")
    sub.add_parser("seed", help="写入法典（已有数据则跳过）")
    sub.add_parser("check", help="自检并打印样例检索")
    args = parser.parse_args(argv)

    store, pc = build()

    if args.command == "init":
        store.init_schema(recreate=args.recreate)
        count = store.seed_statutes(force=args.force or args.recreate)
        print(f"[init] seekdb {settings.seekdb_host}:{settings.seekdb_port}/{settings.seekdb_database}")
        print(f"[init] statutes = {count}")
        print(f"[init] powercontext = {settings.pc_base_url} available={pc.available()}")
        return 0

    if args.command == "seed":
        store.init_schema()
        count = store.seed_statutes()
        print(f"[seed] statutes = {count}")
        return 0

    if args.command == "check":
        stats = store.docket_stats()
        print(f"[check] statutes in code: {len(STATUTES)}")
        print(f"[check] docket stats: {json.dumps(stats, ensure_ascii=False)}")
        rows, tag = store.search_statutes("我的猫每天凌晨三点在我脸上蹦迪，还打翻水杯")
        print(f"[check] inferred tag = {tag}")
        for row in rows:
            print(
                f"  {row['code']} {row['title']} score={row['score']} "
                f"channels={row['channels']} days={row['min_days']}-{row['max_days']}"
            )
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
