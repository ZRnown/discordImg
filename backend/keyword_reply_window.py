from collections import defaultdict, deque
from dataclasses import dataclass
import time
from typing import Any, Callable, Deque, DefaultDict, Dict, Hashable, List


@dataclass(frozen=True)
class ReservationResult:
    dispatch_now: bool
    queue_size: int
    wait_seconds: float


@dataclass
class _WindowState:
    started_at: float
    used: int = 0


class KeywordReplyWindowManager:
    def __init__(self, time_fn: Callable[[], float] | None = None):
        self._time_fn = time_fn or time.time
        self._states: Dict[Hashable, _WindowState] = {}
        self._queues: DefaultDict[Hashable, Deque[Any]] = defaultdict(deque)

    def reserve_or_enqueue(
        self,
        key: Hashable,
        interval_seconds: int,
        batch_size: int,
        payload: Any,
    ) -> ReservationResult:
        batch_limit = self._normalize_batch_size(batch_size)
        if batch_limit == 0:
            return ReservationResult(dispatch_now=True, queue_size=self.get_queue_size(key), wait_seconds=0.0)

        state = self._get_state(key, interval_seconds)
        if state.used < batch_limit:
            state.used += 1
            return ReservationResult(dispatch_now=True, queue_size=self.get_queue_size(key), wait_seconds=0.0)

        queue = self._queues[key]
        queue.append(payload)
        return ReservationResult(
            dispatch_now=False,
            queue_size=len(queue),
            wait_seconds=self.seconds_until_next_window(key, interval_seconds),
        )

    def release_due_jobs(self, key: Hashable, interval_seconds: int, batch_size: int) -> List[Any]:
        queue = self._queues.get(key)
        if not queue:
            return []

        batch_limit = self._normalize_batch_size(batch_size)
        if batch_limit == 0:
            released = list(queue)
            queue.clear()
            self._queues.pop(key, None)
            return released

        state = self._get_state(key, interval_seconds)
        released: List[Any] = []
        while queue and state.used < batch_limit:
            state.used += 1
            released.append(queue.popleft())

        if not queue:
            self._queues.pop(key, None)

        return released

    def get_queue_size(self, key: Hashable) -> int:
        return len(self._queues.get(key) or ())

    def seconds_until_next_window(self, key: Hashable, interval_seconds: int) -> float:
        if interval_seconds <= 0:
            return 0.0
        state = self._states.get(key)
        if not state:
            return 0.0
        elapsed = max(0.0, self._time_fn() - state.started_at)
        remaining = interval_seconds - elapsed
        return remaining if remaining > 0 else 0.0

    def _get_state(self, key: Hashable, interval_seconds: int) -> _WindowState:
        now = self._time_fn()
        state = self._states.get(key)
        if state is None:
            state = _WindowState(started_at=now)
            self._states[key] = state
            return state

        if interval_seconds <= 0 or (now - state.started_at) >= interval_seconds:
            state.started_at = now
            state.used = 0

        return state

    @staticmethod
    def _normalize_batch_size(batch_size: int) -> int:
        try:
            value = int(batch_size)
        except (TypeError, ValueError):
            return 0
        return value if value > 0 else 0
