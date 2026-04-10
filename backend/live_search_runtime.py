from __future__ import annotations

import threading
from typing import Any, Callable, Optional


def should_enable_streaming_live_search(
    strategy_name: str,
    strategy: Any,
    *,
    streaming_enabled: bool,
    force_streaming: bool,
    require_persisted_cache: bool,
) -> bool:
    supports_streaming = getattr(strategy, "supports_streaming_live_search", None)
    if not (
        bool(streaming_enabled)
        and bool(require_persisted_cache)
        and callable(supports_streaming)
        and supports_streaming()
    ):
        return False

    normalized_strategy_name = str(strategy_name or "").strip()
    if normalized_strategy_name == "siglip2_rerank" and not bool(force_streaming):
        return False

    return True


class LiveSearchConcurrencyGate:
    def __init__(self, max_inflight: int):
        normalized_max = max(int(max_inflight or 1), 1)
        self.max_inflight = normalized_max
        self._semaphore = threading.BoundedSemaphore(normalized_max)

    def try_acquire(self, timeout_seconds: float) -> Optional[Callable[[], None]]:
        timeout = max(float(timeout_seconds or 0.0), 0.0)
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            return None

        released = False
        release_lock = threading.Lock()

        def release() -> None:
            nonlocal released
            with release_lock:
                if released:
                    return
                released = True
                self._semaphore.release()

        return release
