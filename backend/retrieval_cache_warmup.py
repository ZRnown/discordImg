from __future__ import annotations

from typing import Any, Optional


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def normalize_backfill_limit(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def get_backfill_limit(config_obj: Any, attr_name: str) -> Optional[int]:
    return normalize_backfill_limit(getattr(config_obj, attr_name, None))


def should_run_startup_cache_warmup(config_obj: Any, strategy_name: str) -> bool:
    try:
        from .live_retrieval import strategy_requires_persisted_catalog_cache
    except ImportError:
        from live_retrieval import strategy_requires_persisted_catalog_cache

    if not strategy_requires_persisted_catalog_cache(strategy_name):
        return False

    return _to_bool(getattr(config_obj, "RETRIEVAL_CACHE_STARTUP_WARMUP", False), False)
