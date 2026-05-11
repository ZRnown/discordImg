from __future__ import annotations

import argparse
import json
import logging

try:
    from config import config
    from database import db
    from live_retrieval import backfill_product_image_retrieval_cache
except ModuleNotFoundError as e:
    if e.name in {"config", "database", "live_retrieval"}:
        from .config import config
        from .database import db
        from .live_retrieval import backfill_product_image_retrieval_cache
    else:
        raise


logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process one retrieval-cache backfill batch")
    parser.add_argument("--strategy", default=getattr(config, "LIVE_IMAGE_SEARCH_STRATEGY", "siglip2_rerank"))
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--binary-storage", action="store_true", help="Write new cache rows as compact binary blobs")
    args = parser.parse_args()

    limit = max(int(args.limit or 1), 1)
    strategy_name = str(args.strategy or getattr(config, "LIVE_IMAGE_SEARCH_STRATEGY", "siglip2_rerank")).strip()
    if args.binary_storage:
        setattr(config, "RETRIEVAL_CACHE_BINARY_STORAGE_ENABLED", True)
    logger.info("开始执行商品检索缓存补全批次: strategy=%s limit=%s", strategy_name, limit)
    summary = backfill_product_image_retrieval_cache(db, strategy_name, limit=limit)
    print(
        json.dumps(
            {
                "strategy": strategy_name,
                "limit": limit,
                **summary,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
