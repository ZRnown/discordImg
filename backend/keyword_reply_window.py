from collections import defaultdict, deque
from dataclasses import dataclass
import time
from typing import Any, Callable, Deque, DefaultDict, Dict, Hashable, Iterable, List, Tuple


@dataclass(frozen=True)
class ReservationResult:
    dispatch_now: bool
    queue_size: int
    wait_seconds: float
    ready_payloads: Tuple[Any, ...] = ()
    accepted: bool = True


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
        dispatch_mode: str = "immediate",
    ) -> ReservationResult:
        batch_limit = self._normalize_batch_size(batch_size)
        if batch_limit == 0:
            return ReservationResult(
                dispatch_now=True,
                queue_size=self.get_queue_size(key),
                wait_seconds=0.0,
                ready_payloads=(payload,),
            )

        normalized_dispatch_mode = self._normalize_dispatch_mode(dispatch_mode)
        state = self._get_state(key, interval_seconds)
        queue = self._queues[key]

        if normalized_dispatch_mode == "window_end":
            captured_count = state.used + len(queue)
            if captured_count >= batch_limit:
                return ReservationResult(
                    dispatch_now=False,
                    queue_size=len(queue),
                    wait_seconds=self.seconds_until_next_window(key, interval_seconds),
                    accepted=False,
                )

            queue.append(payload)
            return ReservationResult(
                dispatch_now=False,
                queue_size=len(queue),
                wait_seconds=self.seconds_until_next_window(key, interval_seconds),
            )

        queue.append(payload)

        remaining_capacity = batch_limit - state.used
        if remaining_capacity > 0 and len(queue) >= remaining_capacity:
            released = tuple(self._release_from_queue(key, state, remaining_capacity))
            return ReservationResult(
                dispatch_now=True,
                queue_size=self.get_queue_size(key),
                wait_seconds=0.0,
                ready_payloads=released,
            )

        return ReservationResult(
            dispatch_now=False,
            queue_size=len(queue),
            wait_seconds=self.seconds_until_next_window(key, interval_seconds),
        )

    def release_due_jobs(
        self,
        key: Hashable,
        interval_seconds: int,
        batch_size: int,
        dispatch_mode: str = "immediate",
    ) -> List[Any]:
        queue = self._queues.get(key)
        if not queue:
            return []

        batch_limit = self._normalize_batch_size(batch_size)
        if batch_limit == 0:
            released = list(queue)
            queue.clear()
            self._queues.pop(key, None)
            return released

        now = self._time_fn()
        existing_state = self._states.get(key)
        normalized_dispatch_mode = self._normalize_dispatch_mode(dispatch_mode)
        window_elapsed = bool(
            existing_state and (
                interval_seconds <= 0 or (now - existing_state.started_at) >= interval_seconds
            )
        )

        if normalized_dispatch_mode == "window_end":
            if not window_elapsed:
                return []

            released = list(queue)[:batch_limit]
            queue.clear()
            self._queues.pop(key, None)

            next_started_at = self._get_bucket_start(now, interval_seconds)
            if existing_state is None:
                self._states[key] = _WindowState(started_at=next_started_at)
            else:
                existing_state.started_at = next_started_at
                existing_state.used = 0

            return released

        state = self._get_state(key, interval_seconds)
        remaining_capacity = batch_limit - state.used
        if remaining_capacity <= 0:
            return []
        if not window_elapsed and len(queue) < remaining_capacity:
            return []

        released = self._release_from_queue(key, state, min(len(queue), remaining_capacity))

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
        bucket_started_at = self._get_bucket_start(now, interval_seconds)
        state = self._states.get(key)
        if state is None:
            state = _WindowState(started_at=bucket_started_at)
            self._states[key] = state
            return state

        if interval_seconds <= 0 or state.started_at != bucket_started_at:
            state.started_at = bucket_started_at
            state.used = 0

        return state

    @staticmethod
    def _get_bucket_start(now: float, interval_seconds: int) -> float:
        if interval_seconds <= 0:
            return now
        return now - (now % interval_seconds)

    def _release_from_queue(self, key: Hashable, state: _WindowState, release_count: int) -> List[Any]:
        queue = self._queues.get(key)
        if not queue or release_count <= 0:
            return []

        released: List[Any] = []
        while queue and len(released) < release_count:
            released.append(queue.popleft())
        state.used += len(released)

        if not queue:
            self._queues.pop(key, None)

        return released

    @staticmethod
    def _normalize_batch_size(batch_size: int) -> int:
        try:
            value = int(batch_size)
        except (TypeError, ValueError):
            return 0
        return value if value > 0 else 0

    @staticmethod
    def _normalize_dispatch_mode(dispatch_mode: Any) -> str:
        normalized = str(dispatch_mode or "immediate").strip().lower()
        if normalized in {"immediate", "window_end"}:
            return normalized
        return "immediate"


def build_batched_reply_content(entries: Iterable[dict]) -> str:
    lines: List[str] = []
    for entry in entries or ():
        author_id = entry.get("author_id")
        reply_content = (entry.get("reply_content") or "").strip()
        if not reply_content:
            continue

        if entry.get("reply_content_is_final"):
            lines.extend(
                part.strip()
                for part in reply_content.splitlines()
                if part.strip()
            )
            continue

        if not author_id:
            continue

        mention = f"<@{author_id}>"
        parts = [part.strip() for part in reply_content.splitlines() if part.strip()]
        if not parts:
            lines.append(mention)
            continue

        lines.append(f"{mention} {parts[0]}".strip())
        for extra in parts[1:]:
            lines.append(f"  {extra}")

    return "\n".join(lines)
