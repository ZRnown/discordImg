from __future__ import annotations

import queue
import threading
from time import perf_counter
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
    if (
        normalized_strategy_name == "siglip2_rerank"
        and not bool(force_streaming)
        and not bool(getattr(strategy, "image_only_enabled", False))
    ):
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


class LiveSearchQueueTimeoutError(TimeoutError):
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = max(float(timeout_seconds or 0.0), 0.0)
        super().__init__(f"live search queue timed out after {self.timeout_seconds:.2f}s")


class _LiveSearchTask:
    def __init__(
        self,
        func: Callable[[], Any],
        *,
        cancel_event: threading.Event | None = None,
    ):
        self.func = func
        self.cancel_event = cancel_event
        self.enqueued_at = perf_counter()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.started = threading.Event()
        self.finished = threading.Event()
        self.cancelled = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None

    def cancel(self) -> None:
        self.cancelled.set()
        if self.cancel_event is not None:
            self.cancel_event.set()

    def mark_started(self) -> bool:
        if self.cancelled.is_set():
            self.finished_at = perf_counter()
            self.finished.set()
            return False
        self.started_at = perf_counter()
        self.started.set()
        return True

    def mark_finished(self) -> None:
        self.finished_at = perf_counter()
        self.finished.set()

    def wait(
        self,
        *,
        queue_timeout_seconds: float,
        execution_timeout_seconds: float,
    ) -> Any:
        queue_timeout = max(float(queue_timeout_seconds or 0.0), 0.0)
        if queue_timeout > 0:
            started = self.started.wait(queue_timeout)
        else:
            self.started.wait()
            started = True
        if not started:
            self.cancel()
            raise LiveSearchQueueTimeoutError(queue_timeout)

        execution_timeout = max(float(execution_timeout_seconds or 0.0), 0.0)
        if execution_timeout > 0:
            finished = self.finished.wait(execution_timeout)
        else:
            self.finished.wait()
            finished = True
        if not finished:
            self.cancel()
            raise TimeoutError(f"live search execution timed out after {execution_timeout:.2f}s")

        if self.error is not None:
            raise self.error
        return self.result


class LiveSearchTaskRunner:
    def __init__(self, max_workers: int, max_queue_size: int):
        self.max_workers = max(int(max_workers or 1), 1)
        self.max_queue_size = max(int(max_queue_size or 0), 0)
        queue_capacity = 0 if self.max_queue_size <= 0 else self.max_queue_size
        self._queue: queue.Queue[_LiveSearchTask] = queue.Queue(maxsize=queue_capacity)
        self._workers: list[threading.Thread] = []
        for worker_index in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name=f"live-search-worker-{worker_index + 1}",
            )
            worker.start()
            self._workers.append(worker)

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if not task.mark_started():
                    continue
                try:
                    task.result = task.func()
                except BaseException as exc:  # noqa: BLE001
                    task.error = exc
                finally:
                    task.mark_finished()
            finally:
                self._queue.task_done()

    def submit(
        self,
        func: Callable[[], Any],
        *,
        cancel_event: threading.Event | None = None,
    ) -> Optional[_LiveSearchTask]:
        task = _LiveSearchTask(func, cancel_event=cancel_event)
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            return None
        return task
