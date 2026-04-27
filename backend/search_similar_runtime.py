from __future__ import annotations

import threading
from typing import Any, Callable, Sequence


class SearchExecutionTimeoutError(TimeoutError):
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = max(float(timeout_seconds or 0.0), 0.0)
        super().__init__(f"search execution timed out after {self.timeout_seconds:.2f}s")


def run_with_timeout(
    func: Callable[[], Any],
    timeout_seconds: float,
    cancel_event: threading.Event | None = None,
) -> Any:
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, BaseException] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result_holder["value"] = func()
        except BaseException as exc:  # noqa: BLE001 - keep the original failure for the caller
            error_holder["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    timeout = max(float(timeout_seconds or 0.0), 0.0)
    if not done.wait(timeout):
        if cancel_event is not None:
            cancel_event.set()
        raise SearchExecutionTimeoutError(timeout)

    if "error" in error_holder:
        raise error_holder["error"]

    return result_holder.get("value")


def log_search_similar_no_match(
    logger,
    *,
    total_elapsed: float,
    filter_stage_elapsed: float,
    retrieval_elapsed: float,
    has_global_filter_images: bool,
    has_user_website_filter_images: bool,
    result_count: int,
    threshold: float,
    user_id: int | None,
    user_shops: Sequence[str] | None,
    timed_out: bool = False,
    timeout_seconds: float | None = None,
) -> None:
    normalized_shops = list(user_shops) if user_shops is not None else None

    if timed_out:
        logger.warning(
            "search_similar 请求超时: total=%.2fs timeout=%.2fs filter_stage=%.2fs retrieval=%.2fs "
            "threshold=%.3f result_count=%s has_global_filter_images=%s has_user_website_filter_images=%s "
            "user_id=%s shops=%s",
            total_elapsed,
            max(float(timeout_seconds or 0.0), 0.0),
            filter_stage_elapsed,
            retrieval_elapsed,
            threshold,
            result_count,
            has_global_filter_images,
            has_user_website_filter_images,
            user_id,
            normalized_shops,
        )
        return

    if result_count <= 0:
        logger.info(
            "search_similar 未找到相似度超过阈值的商品: total=%.2fs filter_stage=%.2fs retrieval=%.2fs "
            "threshold=%.3f has_global_filter_images=%s has_user_website_filter_images=%s user_id=%s shops=%s",
            total_elapsed,
            filter_stage_elapsed,
            retrieval_elapsed,
            threshold,
            has_global_filter_images,
            has_user_website_filter_images,
            user_id,
            normalized_shops,
        )
