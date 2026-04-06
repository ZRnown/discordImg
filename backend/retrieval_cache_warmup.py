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


def get_auto_backfill_limit(config_obj: Any, default: int = 24) -> int:
    limit = get_backfill_limit(config_obj, "RETRIEVAL_CACHE_AUTO_BATCH_LIMIT")
    return limit or max(int(default or 1), 1)


def get_auto_backfill_max_missing(config_obj: Any, default: int = 5000) -> int:
    value = getattr(config_obj, "RETRIEVAL_CACHE_AUTO_BACKFILL_MAX_MISSING", default)
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(0, limit)


def should_run_startup_cache_warmup(config_obj: Any, strategy_name: str) -> bool:
    try:
        from .live_retrieval import strategy_requires_persisted_catalog_cache
    except ImportError:
        from live_retrieval import strategy_requires_persisted_catalog_cache

    if not strategy_requires_persisted_catalog_cache(strategy_name):
        return False

    return _to_bool(getattr(config_obj, "RETRIEVAL_CACHE_STARTUP_WARMUP", False), False)


def should_run_startup_cache_compaction(config_obj: Any, strategy_name: str) -> bool:
    try:
        from .live_retrieval import strategy_requires_persisted_catalog_cache
    except ImportError:
        from live_retrieval import strategy_requires_persisted_catalog_cache

    if not strategy_requires_persisted_catalog_cache(strategy_name):
        return False

    return _to_bool(getattr(config_obj, "RETRIEVAL_CACHE_STARTUP_COMPACTION", False), False)


def should_run_auto_backfill(config_obj: Any, strategy_name: str) -> bool:
    try:
        from .live_retrieval import strategy_requires_persisted_catalog_cache
    except ImportError:
        from live_retrieval import strategy_requires_persisted_catalog_cache

    if not strategy_requires_persisted_catalog_cache(strategy_name):
        return False

    return _to_bool(getattr(config_obj, "RETRIEVAL_CACHE_AUTO_BACKFILL", True), True)


def get_backfill_interval_seconds(config_obj: Any, attr_name: str, default: int) -> int:
    value = getattr(config_obj, attr_name, default)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = default
    return max(5, seconds)


def get_backfill_cooldown_seconds(config_obj: Any, attr_name: str, default: int) -> int:
    value = getattr(config_obj, attr_name, default)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = default
    return max(1, seconds)


def get_backfill_timeout_seconds(config_obj: Any, attr_name: str, default: int) -> int:
    value = getattr(config_obj, attr_name, default)
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = default
    return max(30, seconds)


def reduce_backfill_limit_after_failure(limit: Any) -> int:
    try:
        normalized = int(limit)
    except (TypeError, ValueError):
        normalized = 1
    return max(1, normalized // 2)


def should_continue_auto_backfill_burst(
    summary: Any,
    remaining_count: Any,
    burst_enabled: bool = False,
) -> bool:
    if not _to_bool(burst_enabled, False):
        return False
    if not isinstance(summary, dict):
        return False
    try:
        processed = int(summary.get("processed") or 0)
    except (TypeError, ValueError):
        processed = 0
    try:
        remaining = int(remaining_count or 0)
    except (TypeError, ValueError):
        remaining = 0
    return processed > 0 and remaining > 0


def should_pause_auto_backfill(missing_count: Any, max_missing: Any) -> bool:
    try:
        missing = int(missing_count or 0)
    except (TypeError, ValueError):
        missing = 0
    try:
        limit = int(max_missing or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return False
    return missing > limit
