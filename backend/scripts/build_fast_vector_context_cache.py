#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import config
from database import db
from live_retrieval import get_live_image_retriever


def build_user_shop_scope(user_id: int) -> list[str]:
    user = db.get_user_by_id(user_id)
    if not user:
        return []

    allowed_shops: set[str] = set()
    for shop_id in user.get("shops", []) or []:
        if not shop_id:
            continue
        normalized_shop_id = str(shop_id).strip()
        if not normalized_shop_id:
            continue
        allowed_shops.add(normalized_shop_id)
        shop_info = db.get_shop_by_id(normalized_shop_id)
        if shop_info and shop_info.get("name"):
            allowed_shops.add(str(shop_info["name"]).strip())

    return sorted(shop for shop in allowed_shops if shop)


def _scope_key(scope: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(item).strip() for item in scope if str(item).strip()}))


def _collect_autostart_scopes() -> list[tuple[str, ...]]:
    scopes: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for account in db.get_discord_accounts_marked_for_autostart():
        user_id = account.get("user_id")
        try:
            normalized_user_id = int(user_id)
        except (TypeError, ValueError):
            continue
        scope = _scope_key(build_user_shop_scope(normalized_user_id))
        if scope and scope not in seen:
            seen.add(scope)
            scopes.append(scope)
    return scopes


def _collect_user_scopes(user_ids: list[int]) -> list[tuple[str, ...]]:
    scopes: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for user_id in user_ids:
        scope = _scope_key(build_user_shop_scope(user_id))
        if scope and scope not in seen:
            seen.add(scope)
            scopes.append(scope)
    return scopes


def _parse_shop_scope(raw_values: list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for raw_value in raw_values:
        values.extend(str(raw_value or "").split(","))
    return _scope_key(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build disk-backed vector contexts for image search")
    parser.add_argument("--strategy", default=getattr(config, "LIVE_IMAGE_SEARCH_STRATEGY", "siglip2_rerank"))
    parser.add_argument("--autostart-scopes", action="store_true", help="Build scopes used by autostart bot accounts")
    parser.add_argument("--user-id", action="append", type=int, default=[], help="Build a scope for one user id")
    parser.add_argument("--shop", action="append", default=[], help="Build one explicit shop scope; repeat or comma-separate")
    parser.add_argument("--max-scopes", type=int, default=0)
    args = parser.parse_args()

    strategy_name = str(args.strategy or "siglip2_rerank").strip()
    scopes: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()

    requested_autostart = bool(args.autostart_scopes or not args.user_id and not args.shop)
    if requested_autostart:
        for scope in _collect_autostart_scopes():
            if scope not in seen:
                seen.add(scope)
                scopes.append(scope)

    for scope in _collect_user_scopes(args.user_id):
        if scope not in seen:
            seen.add(scope)
            scopes.append(scope)

    explicit_scope = _parse_shop_scope(args.shop)
    if explicit_scope and explicit_scope not in seen:
        scopes.append(explicit_scope)

    max_scopes = max(int(args.max_scopes or 0), 0)
    if max_scopes:
        scopes = scopes[:max_scopes]

    retriever = get_live_image_retriever(db, strategy_name)
    started_at = time.time()
    built = 0
    failed = 0
    skipped = 0

    if not scopes:
        print(json.dumps({"strategy": strategy_name, "scopes": 0, "built": 0}, ensure_ascii=False))
        return 0

    for index, scope in enumerate(scopes, start=1):
        scope_started_at = time.time()
        try:
            ok = retriever.prepare_fast_vector_context_for_warmup(scope)
            if ok:
                built += 1
            else:
                skipped += 1
            print(
                json.dumps(
                    {
                        "scope_index": index,
                        "scope_count": len(scopes),
                        "shops": list(scope),
                        "built": ok,
                        "elapsed_seconds": round(time.time() - scope_started_at, 1),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except Exception as exc:
            failed += 1
            print(
                json.dumps(
                    {
                        "scope_index": index,
                        "scope_count": len(scopes),
                        "shops": list(scope),
                        "error": str(exc),
                        "elapsed_seconds": round(time.time() - scope_started_at, 1),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    summary = {
        "strategy": strategy_name,
        "scopes": len(scopes),
        "built": built,
        "skipped": skipped,
        "failed": failed,
        "elapsed_seconds": round(time.time() - started_at, 1),
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
