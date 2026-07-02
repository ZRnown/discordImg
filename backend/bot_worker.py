import asyncio
import logging
import os
import signal
import time
from typing import Any, Dict, Iterable, List, Optional, Set

if 'AI_INTRA_THREADS' not in os.environ:
    os.environ['AI_INTRA_THREADS'] = '1'
_ai_threads = os.environ.get('AI_INTRA_THREADS', '1')
os.environ["OMP_NUM_THREADS"] = _ai_threads
os.environ["MKL_NUM_THREADS"] = _ai_threads
os.environ["OPENBLAS_NUM_THREADS"] = _ai_threads
os.environ["VECLIB_MAXIMUM_THREADS"] = _ai_threads
os.environ["NUMEXPR_NUM_THREADS"] = _ai_threads
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("TORCH_CPP_LOG_LEVEL", "ERROR")
os.environ.setdefault("TORCH_SHOW_CPP_STACKTRACES", "0")
os.environ.setdefault("GLOG_minloglevel", "2")

try:
    from dotenv import load_dotenv  # noqa: E402

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except Exception:
    pass

from bot import (  # noqa: E402
    DiscordBotClient,
    bot_clients,
    bot_tasks,
    dispatch_keyword_review_item,
    get_discord_start_delay_seconds,
    start_discord_client_with_delay,
)
from bot_watchdog import build_bot_runtime_entries, collect_watchdog_restart_candidates  # noqa: E402
from database import db  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("bot-worker")

BOT_WATCHDOG_INTERVAL_SECONDS = float(os.environ.get("BOT_WATCHDOG_INTERVAL_SECONDS", "60") or 60)
BOT_WATCHDOG_RESTART_INTERVAL_SECONDS = float(os.environ.get("BOT_WATCHDOG_RESTART_INTERVAL_SECONDS", "180") or 180)
BOT_WATCHDOG_DISCONNECTED_GRACE_SECONDS = float(os.environ.get("BOT_WATCHDOG_DISCONNECTED_GRACE_SECONDS", "90") or 90)
BOT_WATCHDOG_RESTART_START_DELAY_SECONDS = max(
    0.0,
    float(os.environ.get("BOT_WATCHDOG_RESTART_START_DELAY_SECONDS", "20") or 20),
)
REVIEW_DISPATCH_POLL_SECONDS = float(os.environ.get("BOT_REVIEW_DISPATCH_POLL_SECONDS", "2") or 2)
REVIEW_DISPATCH_BATCH_SIZE = max(1, int(os.environ.get("BOT_REVIEW_DISPATCH_BATCH_SIZE", "20") or 20))
REVIEW_DISPATCH_STALE_SECONDS = max(60, int(os.environ.get("BOT_REVIEW_DISPATCH_STALE_SECONDS", "300") or 300))
AUTOSTART_RECONCILE_SECONDS = max(10.0, float(os.environ.get("BOT_AUTOSTART_RECONCILE_SECONDS", "30") or 30))
STATUS_REFRESH_SECONDS = max(10.0, float(os.environ.get("BOT_STATUS_REFRESH_SECONDS", "30") or 30))


def _coerce_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_id_list(value: str) -> Set[int]:
    ids: Set[int] = set()
    for item in str(value or "").replace(";", ",").split(","):
        parsed = _coerce_int(item.strip(), None)
        if parsed is not None:
            ids.add(parsed)
    return ids


def _get_shard_settings() -> tuple[int, int, Set[int]]:
    shard_count = max(1, _coerce_int(os.environ.get("BOT_SHARD_COUNT"), 1) or 1)
    shard_index = _coerce_int(os.environ.get("BOT_SHARD_INDEX"), 0) or 0
    shard_index = max(0, min(shard_index, shard_count - 1))
    explicit_ids = _parse_id_list(os.environ.get("BOT_ACCOUNT_IDS", ""))
    return shard_index, shard_count, explicit_ids


def _filter_accounts_for_shard(accounts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    shard_index, shard_count, explicit_ids = _get_shard_settings()
    normalized_accounts = [dict(account) for account in accounts or []]
    normalized_accounts.sort(key=lambda account: _coerce_int(account.get("id"), 0) or 0)

    if explicit_ids:
        return [
            account
            for account in normalized_accounts
            if _coerce_int(account.get("id"), None) in explicit_ids
        ]

    return [
        account
        for index, account in enumerate(normalized_accounts)
        if index % shard_count == shard_index
    ]


def _build_user_shop_scope(user_id: Optional[int]) -> Optional[List[str]]:
    if user_id is None:
        return None

    user = db.get_user_by_id(user_id)
    if not user:
        return []

    allowed_shops: Set[str] = set()
    for shop_id in user.get("shops", []) or []:
        if not shop_id:
            continue
        allowed_shops.add(str(shop_id))
        shop_info = db.get_shop_by_id(str(shop_id))
        if shop_info and shop_info.get("name"):
            allowed_shops.add(str(shop_info["name"]))

    return list(allowed_shops)


def _resolve_account_role(account_id: int) -> str:
    bindings = db.get_account_website_bindings(account_id)
    if not bindings:
        return "both"

    has_sender = any(binding.get("role") in ["sender", "both"] for binding in bindings)
    has_listener = any(binding.get("role") in ["listener", "both"] for binding in bindings)
    if has_sender and has_listener:
        return "both"
    if has_sender:
        return "sender"
    if has_listener:
        return "listener"
    return "both"


def _local_account_ids() -> Set[int]:
    return {
        account_id
        for account_id in (_coerce_int(getattr(client, "account_id", None), None) for client in bot_clients)
        if account_id is not None
    }


async def _stop_account(account_id: int, reason: str = "") -> bool:
    runtime_entries = build_bot_runtime_entries(bot_clients, bot_tasks)
    runtime_entry = runtime_entries.get(account_id)
    if not runtime_entry:
        return False

    runtime_index = _coerce_int(runtime_entry.get("index"), None)
    if runtime_index is None or runtime_index < 0 or runtime_index >= len(bot_clients):
        return False

    old_client = bot_clients.pop(runtime_index)
    old_task = bot_tasks.pop(runtime_index) if runtime_index < len(bot_tasks) else None
    if old_task and not old_task.done():
        old_task.cancel()

    try:
        db.update_account_status(account_id, "offline")
    except Exception:
        pass

    try:
        if old_client and not old_client.is_closed():
            await old_client.close()
    except Exception as exc:
        logger.warning("failed closing account id=%s reason=%s: %s", account_id, reason, exc)

    logger.info("stopped Discord account id=%s reason=%s", account_id, reason)
    return True


def _log_finished_account_task(task: asyncio.Task, account_id: int) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception as task_error:
        logger.warning("account task state read failed id=%s: %s", account_id, task_error)
        return

    if exc is not None:
        logger.warning(
            "Discord account task ended id=%s error=%s: %s",
            account_id,
            type(exc).__name__,
            exc,
        )


async def _start_accounts(
    accounts: List[Dict[str, Any]],
    shutdown_event: asyncio.Event,
    min_start_delay_seconds: float = 0.0,
) -> None:
    for start_index, account in enumerate(accounts):
        if shutdown_event.is_set():
            break

        account_id = _coerce_int(account.get("id"), None)
        token = account.get("token")
        if account_id is None or not token:
            continue

        username = account.get("username") or f"account_{account_id}"
        user_id = _coerce_int(account.get("user_id"), None)
        user_shops = _build_user_shop_scope(user_id)
        role = _resolve_account_role(account_id)
        client = DiscordBotClient(account_id=account_id, user_id=user_id, user_shops=user_shops, role=role)
        bot_clients.append(client)

        start_delay_seconds = max(
            get_discord_start_delay_seconds(start_index),
            float(min_start_delay_seconds or 0.0),
        )
        task = asyncio.create_task(
            start_discord_client_with_delay(
                client,
                token,
                reconnect=True,
                start_delay_seconds=start_delay_seconds,
            ),
            name=f"discord-account-{account_id}",
        )
        task.add_done_callback(
            lambda finished_task, finished_account_id=account_id: _log_finished_account_task(
                finished_task,
                finished_account_id,
            )
        )
        bot_tasks.append(task)
        logger.info(
            "started Discord account %s id=%s user_id=%s role=%s shard_delay=%.2fs",
            username,
            account_id,
            user_id,
            role,
            start_delay_seconds,
        )


async def _watchdog_loop(shard_accounts: List[Dict[str, Any]], shutdown_event: asyncio.Event) -> None:
    restart_attempts: Dict[int, float] = {}
    await asyncio.sleep(min(BOT_WATCHDOG_INTERVAL_SECONDS, 5.0))

    while not shutdown_event.is_set():
        try:
            runtime_entries = build_bot_runtime_entries(bot_clients, bot_tasks)
            candidates = collect_watchdog_restart_candidates(
                shard_accounts,
                runtime_entries,
                now_monotonic=time.monotonic(),
                restart_attempt_timestamps=restart_attempts,
                min_restart_interval_seconds=BOT_WATCHDOG_RESTART_INTERVAL_SECONDS,
                disconnected_grace_seconds=BOT_WATCHDOG_DISCONNECTED_GRACE_SECONDS,
            )
            for candidate in candidates:
                account_id = _coerce_int(candidate.get("account_id"), None)
                account = candidate.get("account")
                if account_id is not None and account:
                    restart_attempts[account_id] = time.monotonic()
                    logger.warning(
                        "watchdog restarting account id=%s reason=%s",
                        account_id,
                        candidate.get("reason"),
                    )
                    if account_id is not None:
                        await _stop_account(account_id, reason=str(candidate.get("reason") or "watchdog"))
                    await _start_accounts(
                        [account],
                        shutdown_event,
                        min_start_delay_seconds=BOT_WATCHDOG_RESTART_START_DELAY_SECONDS,
                    )
        except Exception as exc:
            logger.error("watchdog loop failed: %s", exc)

        await asyncio.sleep(BOT_WATCHDOG_INTERVAL_SECONDS)


async def _autostart_reconcile_loop(shard_accounts: List[Dict[str, Any]], shutdown_event: asyncio.Event) -> None:
    while not shutdown_event.is_set():
        try:
            desired_accounts = _filter_accounts_for_shard(db.get_discord_accounts_marked_for_autostart())
            desired_by_id = {
                account_id: account
                for account in desired_accounts
                for account_id in [_coerce_int(account.get("id"), None)]
                if account_id is not None
            }
            local_ids = _local_account_ids()

            for account_id in sorted(local_ids - set(desired_by_id)):
                await _stop_account(account_id, reason="autostart_disabled")

            missing_accounts = [
                account
                for account_id, account in sorted(desired_by_id.items())
                if account_id not in _local_account_ids()
            ]
            if missing_accounts:
                logger.info("starting %s newly enabled accounts: %s", len(missing_accounts), list(desired_by_id))
                await _start_accounts(missing_accounts, shutdown_event)

            shard_accounts[:] = desired_accounts
        except Exception as exc:
            logger.error("autostart reconcile loop failed: %s", exc)

        await asyncio.sleep(AUTOSTART_RECONCILE_SECONDS)


async def _status_refresh_loop(shutdown_event: asyncio.Event) -> None:
    while not shutdown_event.is_set():
        try:
            for client in list(bot_clients):
                account_id = _coerce_int(getattr(client, "account_id", None), None)
                if account_id is None:
                    continue

                is_closed = False
                try:
                    is_closed = bool(client.is_closed())
                except Exception:
                    pass

                is_ready = False
                try:
                    is_ready = bool(client.is_ready())
                except Exception:
                    pass

                if is_ready and not is_closed and getattr(client, "running", False):
                    db.update_account_status(account_id, "online", min_update_interval_seconds=20)
                elif is_closed:
                    db.update_account_status(account_id, "offline", min_update_interval_seconds=20)
        except Exception as exc:
            logger.error("status refresh loop failed: %s", exc)

        await asyncio.sleep(STATUS_REFRESH_SECONDS)


def _fetch_approved_review_items(limit: int) -> List[Dict[str, Any]]:
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE keyword_reply_review_items
                SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'dispatching'
                  AND updated_at <= datetime('now', ?)
                """,
                (f"-{REVIEW_DISPATCH_STALE_SECONDS} seconds",),
            )
            cursor.execute(
                """
                SELECT *
                FROM keyword_reply_review_items
                WHERE status = 'approved'
                ORDER BY updated_at ASC, id ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            conn.commit()
            return [db._parse_keyword_reply_review_item_row(row) for row in rows]
    except Exception as exc:
        logger.error("fetch approved review items failed: %s", exc)
        return []


def _review_item_belongs_to_local_shard(item: Dict[str, Any]) -> bool:
    local_ids = _local_account_ids()
    if not local_ids:
        return False

    account_ids = {
        account_id
        for account_id in (_coerce_int(value, None) for value in (item.get("account_ids") or []))
        if account_id is not None
    }
    if account_ids:
        return bool(account_ids & local_ids)

    item_user_id = _coerce_int(item.get("user_id"), None)
    return any(_coerce_int(getattr(client, "user_id", None), None) == item_user_id for client in bot_clients)


def _claim_review_item(item_id: int) -> bool:
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE keyword_reply_review_items
                SET status = 'dispatching', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'approved'
                """,
                (item_id,),
            )
            conn.commit()
            return cursor.rowcount == 1
    except Exception as exc:
        logger.error("claim review item failed id=%s: %s", item_id, exc)
        return False


async def _review_dispatch_loop(shutdown_event: asyncio.Event) -> None:
    while not shutdown_event.is_set():
        try:
            for item in _fetch_approved_review_items(REVIEW_DISPATCH_BATCH_SIZE):
                item_id = _coerce_int(item.get("id"), None)
                if item_id is None or not _review_item_belongs_to_local_shard(item):
                    continue
                if not _claim_review_item(item_id):
                    continue

                claimed_item = db.get_keyword_reply_review_item(item_id) or item
                logger.info("dispatching approved review item id=%s", item_id)
                await dispatch_keyword_review_item(claimed_item)
        except Exception as exc:
            logger.error("review dispatch loop failed: %s", exc)

        await asyncio.sleep(REVIEW_DISPATCH_POLL_SECONDS)


async def _shutdown_accounts() -> None:
    for client in list(bot_clients):
        try:
            if client and not client.is_closed():
                if getattr(client, "account_id", None):
                    db.update_account_status(client.account_id, "offline")
                await client.close()
        except Exception as exc:
            logger.warning("failed closing account id=%s: %s", getattr(client, "account_id", None), exc)

    for task in list(bot_tasks):
        if task and not task.done():
            task.cancel()


async def main() -> None:
    shard_index, shard_count, explicit_ids = _get_shard_settings()
    accounts = _filter_accounts_for_shard(db.get_discord_accounts_marked_for_autostart())
    account_ids = [_coerce_int(account.get("id"), None) for account in accounts]
    logger.info(
        "bot worker starting shard=%s/%s explicit_ids=%s account_count=%s account_ids=%s",
        shard_index,
        shard_count,
        sorted(explicit_ids),
        len(accounts),
        account_ids,
    )

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            pass

    await _start_accounts(accounts, shutdown_event)
    background_tasks = [
        asyncio.create_task(_watchdog_loop(accounts, shutdown_event), name="bot-worker-watchdog"),
        asyncio.create_task(_autostart_reconcile_loop(accounts, shutdown_event), name="bot-worker-reconcile"),
        asyncio.create_task(_status_refresh_loop(shutdown_event), name="bot-worker-status-refresh"),
        asyncio.create_task(_review_dispatch_loop(shutdown_event), name="review-dispatch"),
    ]

    try:
        await shutdown_event.wait()
    finally:
        logger.info("bot worker shutting down")
        for task in background_tasks:
            task.cancel()
        await _shutdown_accounts()


if __name__ == "__main__":
    asyncio.run(main())
