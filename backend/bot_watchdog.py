import time
from typing import Any, Dict, Iterable, List, Mapping, Optional


def build_bot_runtime_entries(
    bot_clients: Iterable[Any],
    bot_tasks: Iterable[Any],
) -> Dict[int, Dict[str, Any]]:
    entries: Dict[int, Dict[str, Any]] = {}
    task_list = list(bot_tasks or [])

    for index, client in enumerate(bot_clients or []):
        try:
            account_id = int(getattr(client, "account_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if account_id <= 0:
            continue

        entries[account_id] = {
            "index": index,
            "client": client,
            "task": task_list[index] if index < len(task_list) else None,
        }

    return entries


def _task_done(task: Any) -> bool:
    if task is None:
        return False
    done = getattr(task, "done", None)
    if not callable(done):
        return False
    try:
        return bool(done())
    except Exception:
        return False


def _client_closed(client: Any) -> bool:
    if client is None:
        return False
    is_closed = getattr(client, "is_closed", None)
    if not callable(is_closed):
        return False
    try:
        return bool(is_closed())
    except Exception:
        return False


def _client_ready(client: Any) -> Optional[bool]:
    if client is None:
        return None
    is_ready = getattr(client, "is_ready", None)
    if not callable(is_ready):
        return None
    try:
        return bool(is_ready())
    except Exception:
        return None


def _client_reconnect_stalled(
    client: Any,
    *,
    now_monotonic: float,
    disconnected_grace_seconds: float,
) -> bool:
    if client is None:
        return False

    ready_state = _client_ready(client)
    if ready_state is True:
        return False

    try:
        last_disconnect_at = float(getattr(client, "last_disconnect_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        last_disconnect_at = 0.0

    try:
        last_ready_at = float(getattr(client, "last_ready_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        last_ready_at = 0.0

    if last_disconnect_at <= 0 or last_disconnect_at <= last_ready_at:
        return False

    grace_seconds = max(float(disconnected_grace_seconds or 0.0), 0.0)
    if grace_seconds <= 0:
        return True

    return (now_monotonic - last_disconnect_at) >= grace_seconds


def collect_watchdog_restart_candidates(
    accounts: Iterable[Mapping[str, Any]],
    runtime_entries: Mapping[int, Mapping[str, Any]],
    *,
    now_monotonic: Optional[float] = None,
    restart_attempt_timestamps: Optional[Mapping[int, float]] = None,
    suspended_until_timestamps: Optional[Mapping[int, float]] = None,
    min_restart_interval_seconds: float = 30.0,
    task_done_restart_interval_seconds: Optional[float] = None,
    disconnected_grace_seconds: float = 10.0,
) -> List[Dict[str, Any]]:
    now = float(time.monotonic() if now_monotonic is None else now_monotonic)
    restart_attempt_timestamps = restart_attempt_timestamps or {}
    suspended_until_timestamps = suspended_until_timestamps or {}
    cooldown_seconds = max(float(min_restart_interval_seconds or 0.0), 0.0)
    task_done_cooldown_seconds = max(
        float(
            task_done_restart_interval_seconds
            if task_done_restart_interval_seconds is not None
            else cooldown_seconds
        ),
        cooldown_seconds,
    )

    candidates: List[Dict[str, Any]] = []
    for account in accounts or []:
        try:
            account_id = int((account or {}).get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if account_id <= 0:
            continue

        suspended_until = float(suspended_until_timestamps.get(account_id, 0.0) or 0.0)
        if suspended_until > now:
            continue

        runtime_entry = runtime_entries.get(account_id)
        reason = None
        if runtime_entry is None:
            reason = "missing_runtime"
        else:
            client = runtime_entry.get("client")
            client_ready = _client_ready(client)
            if _client_closed(client):
                reason = "client_closed"
            elif _task_done(runtime_entry.get("task")) and client_ready is not True:
                reason = "task_done"
            elif _client_reconnect_stalled(
                client,
                now_monotonic=now,
                disconnected_grace_seconds=disconnected_grace_seconds,
            ):
                reason = "disconnected_stalled"

        if reason is None:
            continue

        reason_cooldown_seconds = (
            task_done_cooldown_seconds if reason == "task_done" else cooldown_seconds
        )
        last_attempt_at = float(restart_attempt_timestamps.get(account_id, 0.0) or 0.0)
        if reason_cooldown_seconds > 0 and now - last_attempt_at < reason_cooldown_seconds:
            continue

        candidates.append(
            {
                "account_id": account_id,
                "account": dict(account),
                "reason": reason,
                "runtime_entry": dict(runtime_entry) if runtime_entry else None,
            }
        )

    return candidates
