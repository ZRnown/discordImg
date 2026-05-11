#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import config
from database import db
from live_retrieval import backfill_product_image_retrieval_cache


def _count_binary_rows(strategy_name: str) -> int:
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM product_image_retrieval_cache
            WHERE strategy_name = ?
              AND embedding_blob IS NOT NULL
            """,
            (strategy_name,),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def _clear_legacy_json_for_binary_rows(strategy_name: str) -> int:
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE product_image_retrieval_cache
            SET embedding_json = NULL,
                color_hist_json = NULL
            WHERE strategy_name = ?
              AND embedding_blob IS NOT NULL
              AND (embedding_json IS NOT NULL OR color_hist_json IS NOT NULL)
            """,
            (strategy_name,),
        )
        changed = int(cursor.rowcount or 0)
        conn.commit()
    return changed


def _maybe_vacuum() -> None:
    db_path = getattr(db, "db_path", "")
    if not db_path:
        return
    with sqlite3.connect(db_path, timeout=60) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build compact binary retrieval cache ahead of image-search traffic")
    parser.add_argument("--strategy", default=getattr(config, "LIVE_IMAGE_SEARCH_STRATEGY", "siglip2_rerank"))
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--clear-legacy-json", action="store_true")
    parser.add_argument("--vacuum", action="store_true")
    args = parser.parse_args()

    strategy_name = str(args.strategy or "siglip2_rerank").strip()
    batch_size = max(int(args.batch_size or 1), 1)
    sleep_seconds = max(float(args.sleep or 0), 0.0)
    max_batches = max(int(args.max_batches or 0), 0)

    setattr(config, "RETRIEVAL_CACHE_BINARY_STORAGE_ENABLED", True)
    started_at = time.time()
    total_processed = 0
    total_skipped = 0
    total_failed = 0
    batches = 0

    while True:
        missing = db.count_missing_product_image_retrieval_cache(strategy_name)
        if missing <= 0:
            break
        if max_batches and batches >= max_batches:
            break

        summary = backfill_product_image_retrieval_cache(db, strategy_name, limit=batch_size)
        batches += 1
        processed = int(summary.get("processed") or 0)
        skipped = int(summary.get("skipped") or 0)
        failed = int(summary.get("failed") or 0)
        total_processed += processed
        total_skipped += skipped
        total_failed += failed
        remaining = db.count_missing_product_image_retrieval_cache(strategy_name)
        print(
            json.dumps(
                {
                    "batch": batches,
                    "processed": processed,
                    "skipped": skipped,
                    "failed": failed,
                    "remaining": remaining,
                    "binary_cached": _count_binary_rows(strategy_name),
                    "elapsed_seconds": round(time.time() - started_at, 1),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        if processed <= 0 and skipped <= 0:
            break
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    cleared_json_rows = 0
    if args.clear_legacy_json:
        cleared_json_rows = _clear_legacy_json_for_binary_rows(strategy_name)

    if args.vacuum:
        _maybe_vacuum()

    final = {
        "strategy": strategy_name,
        "batches": batches,
        "processed": total_processed,
        "skipped": total_skipped,
        "failed": total_failed,
        "remaining": db.count_missing_product_image_retrieval_cache(strategy_name),
        "cached": db.count_product_image_retrieval_cache(strategy_name),
        "binary_cached": _count_binary_rows(strategy_name),
        "cleared_json_rows": cleared_json_rows,
        "elapsed_seconds": round(time.time() - started_at, 1),
    }
    print(json.dumps(final, ensure_ascii=False), flush=True)
    return 0 if final["remaining"] <= 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
