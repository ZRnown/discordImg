import discord
import aiohttp
import logging
import time
import asyncio
import random
import os
import json
import io
import sqlite3
import re
import sys
from datetime import datetime, timedelta
from functools import partial
from types import SimpleNamespace
from urllib.parse import quote

try:
    from itsdangerous import URLSafeTimedSerializer
except Exception:
    URLSafeTimedSerializer = None

try:
    import discord.state as discord_state
except Exception:
    discord_state = None
try:
    from config import config
except ImportError:
    from .config import config
try:
    from log_utils import format_record_log_entry
except ImportError:
    from .log_utils import format_record_log_entry
try:
    from keyword_reply_window import KeywordReplyWindowManager, build_batched_reply_content
except ImportError:
    from .keyword_reply_window import KeywordReplyWindowManager, build_batched_reply_content
try:
    from keyword_search_filters import _should_ignore_keyword_search_query
except ImportError:
    from .keyword_search_filters import _should_ignore_keyword_search_query
try:
    from keyword_search_terms import (
        build_product_keyword_variants as _shared_build_product_keyword_variants,
        build_query_keyword_candidates as _shared_build_query_keyword_candidates,
        extract_marketplace_item_id_from_text as _shared_extract_marketplace_item_id_from_text,
        find_query_keyword_match as _shared_find_query_keyword_match,
        normalize_keyword_search_text as _shared_normalize_keyword_search_text,
        tokenize_keyword_search_text as _shared_tokenize_keyword_search_text,
    )
except ImportError:
    from .keyword_search_terms import (
        build_product_keyword_variants as _shared_build_product_keyword_variants,
        build_query_keyword_candidates as _shared_build_query_keyword_candidates,
        extract_marketplace_item_id_from_text as _shared_extract_marketplace_item_id_from_text,
        find_query_keyword_match as _shared_find_query_keyword_match,
        normalize_keyword_search_text as _shared_normalize_keyword_search_text,
        tokenize_keyword_search_text as _shared_tokenize_keyword_search_text,
    )

try:
    from rotation_settings import resolve_rotation_settings_update
except ImportError:
    from .rotation_settings import resolve_rotation_settings_update
try:
    from settings_validation import normalize_reply_delay_range
except ImportError:
    from .settings_validation import normalize_reply_delay_range
try:
    from message_filter_utils import (
        filters_block_message,
        resolve_keyword_match_limit,
        should_run_ocr_for_image_reply,
        split_filter_values,
    )
except ImportError:
    from .message_filter_utils import (
        filters_block_message,
        resolve_keyword_match_limit,
        should_run_ocr_for_image_reply,
        split_filter_values,
    )
try:
    from product_reply_settings import apply_effective_product_reply_settings
except ImportError:
    from .product_reply_settings import apply_effective_product_reply_settings
try:
    from product_title_translations import (
        apply_reply_language_template_default,
        get_effective_reply_languages,
        render_reply_template,
    )
except ImportError:
    from .product_title_translations import (
        apply_reply_language_template_default,
        get_effective_reply_languages,
        render_reply_template,
    )
try:
    from ocr_service import ocr_service
except ImportError:
    from .ocr_service import ocr_service


def _apply_discord_presence_compat_patch():
    """兼容部分 discord.py-self 版本缺少 FakeClientPresence.hidden_activities 的问题。"""
    fake_presence_cls = getattr(discord_state, 'FakeClientPresence', None) if discord_state else None
    if fake_presence_cls is None or hasattr(fake_presence_cls, 'hidden_activities'):
        return

    @property
    def hidden_activities(self):
        all_session = getattr(getattr(self, '_state', None), 'all_session', None)
        hidden = getattr(all_session, 'hidden_activities', None)
        if hidden is None:
            return ()
        return hidden

    setattr(fake_presence_cls, 'hidden_activities', hidden_activities)


_apply_discord_presence_compat_patch()
# 全局变量用于多账号机器人管理
bot_clients = []
bot_tasks = []

KEYWORD_REVIEW_ACTION_TOKEN_SALT = "keyword-review-action"
KEYWORD_REVIEW_ACTION_TOKEN_MAX_AGE_SECONDS = 7 * 24 * 3600

# 全局冷却管理器：(account_id, channel_id) -> timestamp (上次发送时间)
account_last_sent = {}

# 用户重复发送过滤缓存：(user_id, product_id, channel_id) -> timestamp
_repeat_reply_cache = {}
_repeat_filter_cache = {'seconds': 0.0, 'ts': 0.0}
_repeat_cache_lock = asyncio.Lock()
_keyword_reply_window_manager = KeywordReplyWindowManager()
_keyword_reply_window_lock = asyncio.Lock()
_keyword_reply_flush_tasks = {}
_keyword_reply_window_configs = {}
_keyword_reply_background_tasks = set()
_image_reply_background_tasks = set()
_auto_reply_thread_ids = {}
SENDER_CHANNEL_ACCESS_CACHE_TTL_SECONDS = max(
    float(getattr(config, 'SENDER_CHANNEL_ACCESS_CACHE_TTL_SECONDS', 300.0) or 300.0),
    10.0,
)
_sender_channel_access_cache = {}
_review_bark_monitor_task = None
_review_bark_notification_lock = asyncio.Lock()

_discord_send_limiter = None
_discord_send_limiter_signature = None
_AUTO_REPLY_THREAD_CACHE_LIMIT = 2048
_BARK_ERROR_LOG_WINDOW_SECONDS = 60.0
_bark_issue_log_state = {}


def _summarize_text_for_log(value, limit=200):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."


def _summarize_exception_for_log(error, limit=200):
    summary = _summarize_text_for_log(error, limit=limit)
    if summary:
        return summary
    return getattr(error, "__class__", type(error)).__name__


def _safe_discord_attr(obj, *names):
    for name in names:
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value is not None and str(value).strip():
            return str(value).strip()
    return ''


def _build_discord_account_profile(client):
    user_obj = getattr(client, 'user', None)
    username = _safe_discord_attr(user_obj, 'name')
    discriminator = _safe_discord_attr(user_obj, 'discriminator')
    discord_username = username
    if discriminator and discriminator != '0':
        discord_username = f'{username}#{discriminator}'

    avatar_url = ''
    if user_obj is not None:
        for avatar_attr in ('display_avatar', 'avatar'):
            avatar = getattr(user_obj, avatar_attr, None)
            if avatar is not None:
                avatar_url = _safe_discord_attr(avatar, 'url')
                if avatar_url:
                    break

    try:
        guild_count = len(getattr(client, 'guilds', []) or [])
    except Exception:
        guild_count = 0

    return {
        'discord_user_id': _safe_discord_attr(user_obj, 'id'),
        'discord_username': discord_username,
        'discord_handle': username,
        'discord_global_name': _safe_discord_attr(user_obj, 'global_name'),
        'discord_display_name': _safe_discord_attr(user_obj, 'display_name', 'global_name', 'name'),
        'discord_avatar_url': avatar_url,
        'runtime_guild_count': guild_count,
    }


def _is_discord_blocked_content_error(error):
    code = getattr(error, "code", None)
    if str(code) == "200000":
        return True

    text = str(error or "")
    return "error code: 200000" in text or "包含本服务器屏蔽的内容" in text


def _is_discord_missing_access_error(error):
    code = getattr(error, "code", None)
    if str(code) in {"50001", "50013"}:
        return True

    text = str(error or "")
    return (
        "error code: 50001" in text
        or "error code: 50013" in text
        or "Missing Access" in text
        or "Missing Permissions" in text
        or "缺少权限" in text
    )


def _log_rate_limited_bark_issue(scene, detail, *, level="error"):
    summary = _summarize_text_for_log(detail, limit=200) or "unknown error"
    now = time.monotonic()
    state = _bark_issue_log_state.get(scene)
    if state is not None and now - state["logged_at"] < _BARK_ERROR_LOG_WINDOW_SECONDS:
        state["suppressed"] += 1
        state["last_summary"] = summary
        return

    if state is not None and state["suppressed"] > 0:
        logger.warning(
            f"{scene} 在过去 {int(_BARK_ERROR_LOG_WINDOW_SECONDS)}s 内重复 {state['suppressed']} 次，最近一次: {state['last_summary']}"
        )

    log_method = getattr(logger, level, logger.error)
    log_method(f"{scene}: {summary}")
    _bark_issue_log_state[scene] = {
        "logged_at": now,
        "suppressed": 0,
        "last_summary": summary,
    }


def _normalize_review_bark_mode(value):
    normalized = str(value or 'count').strip().lower()
    if normalized == 'interval':
        return 'interval'
    return 'count'


def _parse_review_bark_datetime(value):
    if isinstance(value, datetime):
        return value

    text = str(value or '').strip()
    if not text:
        return None

    normalized = text.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _should_send_review_queue_bark_count_notification(pending_count, threshold, last_pending_count):
    current_pending = max(0, _coerce_int(pending_count, 0))
    current_threshold = max(1, _coerce_int(threshold, 5))
    previous_pending = max(0, _coerce_int(last_pending_count, 0))
    if current_pending < current_threshold:
        return False
    return current_pending // current_threshold > previous_pending // current_threshold


def _should_send_review_queue_bark_interval_notification(
    pending_count,
    interval_minutes,
    last_notified_at,
    now=None,
):
    current_pending = max(0, _coerce_int(pending_count, 0))
    if current_pending <= 0:
        return False

    parsed_last = _parse_review_bark_datetime(last_notified_at)
    if parsed_last is None:
        return False

    current_interval = max(1, _coerce_int(interval_minutes, 60))
    current_time = now if isinstance(now, datetime) else datetime.now().astimezone()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return current_time >= parsed_last + timedelta(minutes=current_interval)


def _create_keyword_review_action_token(user_id, item_id):
    if URLSafeTimedSerializer is None:
        return ""
    try:
        secret_key = str(getattr(config, "SECRET_KEY", "") or "")
        if not secret_key:
            return ""
        return URLSafeTimedSerializer(secret_key).dumps(
            {
                "user_id": int(user_id),
                "item_id": int(item_id),
            },
            salt=KEYWORD_REVIEW_ACTION_TOKEN_SALT,
        )
    except Exception as exc:
        _log_rate_limited_bark_issue("生成审核 Bark 链接失败", _summarize_exception_for_log(exc), level="warning")
        return ""


def _get_public_frontend_base_url():
    return str(getattr(config, "PUBLIC_FRONTEND_BASE_URL", "") or "").strip().rstrip("/")


def _build_keyword_review_action_url(user_id, item_id):
    base_url = _get_public_frontend_base_url()
    if not base_url:
        return ""
    token = _create_keyword_review_action_token(user_id, item_id)
    if not token:
        return ""
    return f"{base_url}/review-actions/{quote(token, safe='')}"


def _truncate_bark_text(value, limit=180):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:max(limit - 3, 0)]}..."


def _format_review_item_bark_body(review_item, pending_count=None):
    payload = review_item.get("payload") or {}
    message_payload = payload.get("message") or {}
    website_config = payload.get("website_config") or {}
    website_name = (
        website_config.get("display_name")
        or website_config.get("name")
        or review_item.get("website_name")
        or f"网站 {review_item.get('website_id')}"
    )
    guild_name = review_item.get("guild_name") or message_payload.get("guild_name") or "服务器"
    channel_name = review_item.get("channel_name") or message_payload.get("channel_name") or "频道"
    sender_name = (
        review_item.get("sender_name")
        or message_payload.get("author_display_name")
        or message_payload.get("author_name")
        or "未记录"
    )
    account_names = str(review_item.get("account_names") or "").strip() or "未记录"
    source_content = _truncate_bark_text(
        review_item.get("source_content") or message_payload.get("content") or "",
        220,
    ) or "[无文本内容]"
    reply_content = _truncate_bark_text(review_item.get("content") or "", 220) or "[图片/空文本]"
    image_count = len(payload.get("reply_image_previews") or [])
    created_at = message_payload.get("created_at") or review_item.get("created_at") or ""
    lines = [
        "类型: 单条审核通知",
        f"网站: {website_name}",
        f"位置: {guild_name} / #{channel_name}",
        f"触发用户: {sender_name}",
        f"发送账号: {account_names}",
        f"原始消息: {source_content}",
        f"待发内容: {reply_content}",
    ]
    if image_count:
        lines.append(f"待发图片: {image_count} 张")
    if pending_count is not None:
        lines.append(f"当前待审核: {pending_count} 条")
    if created_at:
        lines.append(f"消息时间: {created_at}")
    return "\n".join(lines)


async def _send_bark_notification_payload(bark_server_url, bark_device_key, title, body, jump_url=None):
    server_url = (bark_server_url or "https://api.day.app").strip().rstrip("/")
    if not server_url:
        server_url = "https://api.day.app"
    if not server_url.startswith(("http://", "https://")):
        server_url = f"https://{server_url}"
    device_key = (bark_device_key or "").strip()
    if not device_key:
        return

    encoded_key = quote(device_key, safe="")
    encoded_title = quote(title or "Discord 通知", safe="")
    encoded_body = quote(body or "", safe="")
    push_url = f"{server_url}/{encoded_key}/{encoded_title}/{encoded_body}"

    params = {
        "group": "LinkRadar 链接雷达",
        "isArchive": "1",
        "sound": "gotosleep",
    }
    if jump_url:
        params["url"] = jump_url

    timeout = aiohttp.ClientTimeout(total=8)
    for attempt in range(2):
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
                async with session.get(push_url, params=params) as response:
                    if response.status < 400:
                        return

                    text = await response.text()
                    retryable = response.status >= 500
                    if retryable and attempt == 0:
                        await asyncio.sleep(0.5)
                        continue

                    _log_rate_limited_bark_issue(
                        "Bark 推送失败",
                        f"status={response.status}, body={text}",
                        level="warning",
                    )
                    return
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            _log_rate_limited_bark_issue("Bark 推送异常", _summarize_exception_for_log(e))


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_sender_channel_access_cache_key(target_client, channel_id):
    account_id = _coerce_int(getattr(target_client, 'account_id', None), None)
    normalized_channel_id = _coerce_int(channel_id, None)
    if account_id is None or normalized_channel_id is None:
        return None
    return account_id, normalized_channel_id


def _sender_channel_access_now():
    return time.monotonic()


def _get_cached_sender_channel_inaccessible(target_client, channel_id):
    cache_key = _get_sender_channel_access_cache_key(target_client, channel_id)
    if cache_key is None:
        return False

    cached_until = _sender_channel_access_cache.get(cache_key)
    if cached_until is None:
        return False

    now = _sender_channel_access_now()
    if cached_until > now:
        return True

    _sender_channel_access_cache.pop(cache_key, None)
    return False


def _store_sender_channel_inaccessible(target_client, channel_id):
    cache_key = _get_sender_channel_access_cache_key(target_client, channel_id)
    if cache_key is None:
        return

    _sender_channel_access_cache[cache_key] = (
        _sender_channel_access_now() + SENDER_CHANNEL_ACCESS_CACHE_TTL_SECONDS
    )
    while len(_sender_channel_access_cache) > 4096:
        oldest_key = next(iter(_sender_channel_access_cache))
        _sender_channel_access_cache.pop(oldest_key, None)


def _clear_sender_channel_access_cache(target_client, channel_id):
    cache_key = _get_sender_channel_access_cache_key(target_client, channel_id)
    if cache_key is None:
        return
    _sender_channel_access_cache.pop(cache_key, None)


def _get_auto_reply_thread_cache_key(message):
    return _coerce_int(getattr(message, 'id', None), None)


def _get_cached_auto_reply_thread_id(message):
    cache_key = _get_auto_reply_thread_cache_key(message)
    if cache_key is None:
        return None
    return _auto_reply_thread_ids.get(cache_key)


def _store_cached_auto_reply_thread_id(message, thread_id):
    cache_key = _get_auto_reply_thread_cache_key(message)
    normalized_thread_id = _coerce_int(thread_id, None)
    if cache_key is None or normalized_thread_id is None:
        return

    _auto_reply_thread_ids[cache_key] = normalized_thread_id
    while len(_auto_reply_thread_ids) > _AUTO_REPLY_THREAD_CACHE_LIMIT:
        oldest_key = next(iter(_auto_reply_thread_ids))
        _auto_reply_thread_ids.pop(oldest_key, None)


def _clear_cached_auto_reply_thread_id(message):
    cache_key = _get_auto_reply_thread_cache_key(message)
    if cache_key is None:
        return
    _auto_reply_thread_ids.pop(cache_key, None)


def build_discord_client_runtime_options(intents=None):
    chunk_guilds_at_startup = bool(
        getattr(config, 'DISCORD_CHUNK_GUILDS_AT_STARTUP', False)
    )
    options = {
        'chunk_guilds_at_startup': chunk_guilds_at_startup,
        'guild_subscriptions': bool(
            getattr(config, 'DISCORD_GUILD_SUBSCRIPTIONS', False)
        ),
        'heartbeat_timeout': float(
            getattr(config, 'DISCORD_HEARTBEAT_TIMEOUT', 120.0) or 120.0
        ),
        'max_messages': max(
            int(getattr(config, 'DISCORD_MAX_MESSAGES', 1000) or 0),
            0,
        ),
    }
    if intents is not None:
        options['intents'] = intents

    member_cache_flags_cls = getattr(discord, 'MemberCacheFlags', None)
    if member_cache_flags_cls is not None:
        try:
            options['member_cache_flags'] = member_cache_flags_cls.none()
        except Exception:
            pass

    # discord.py/self 在无成员缓存时不能开启 startup chunking。
    # 这里做一次兜底，避免配置误填后机器人整体无法启动。
    if options.get('chunk_guilds_at_startup') and 'member_cache_flags' in options:
        options['chunk_guilds_at_startup'] = False

    return options


def get_discord_start_delay_seconds(start_index: int) -> float:
    stagger_seconds = float(
        getattr(config, 'DISCORD_STARTUP_STAGGER_SECONDS', 1.5) or 0.0
    )
    normalized_index = max(int(start_index or 0), 0)
    return max(stagger_seconds, 0.0) * normalized_index


class DiscordSendLimiter:
    def __init__(self, max_inflight=1, interval_seconds=0.75):
        self.max_inflight = max(int(max_inflight or 1), 1)
        self.interval_seconds = max(float(interval_seconds or 0.0), 0.0)
        self._semaphore = asyncio.Semaphore(self.max_inflight)
        self._lock = asyncio.Lock()
        self._last_send_at = 0.0

    async def run(self, send_coro_factory):
        async with self._semaphore:
            async with self._lock:
                if self.interval_seconds > 0 and self._last_send_at > 0:
                    elapsed = time.monotonic() - self._last_send_at
                    wait_seconds = self.interval_seconds - elapsed
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)
                result = await send_coro_factory()
                self._last_send_at = time.monotonic()
                return result


def _get_discord_send_limiter():
    global _discord_send_limiter, _discord_send_limiter_signature

    max_inflight = max(
        int(getattr(config, 'DISCORD_SEND_MAX_INFLIGHT', 1) or 1),
        1,
    )
    interval_seconds = max(
        float(getattr(config, 'DISCORD_SEND_INTERVAL_SECONDS', 0.75) or 0.0),
        0.0,
    )
    signature = (max_inflight, interval_seconds)
    if _discord_send_limiter is None or _discord_send_limiter_signature != signature:
        _discord_send_limiter = DiscordSendLimiter(
            max_inflight=max_inflight,
            interval_seconds=interval_seconds,
        )
        _discord_send_limiter_signature = signature
    return _discord_send_limiter


async def _send_discord_message(channel, *args, **kwargs):
    limiter = _get_discord_send_limiter()
    return await limiter.run(lambda: channel.send(*args, **kwargs))


async def _wait_before_discord_reply(channel, min_delay, max_delay):
    delay_seconds = random.uniform(min_delay, max_delay)
    if _coerce_bool(getattr(config, 'DISCORD_SEND_TYPING_ENABLED', False), False):
        async with channel.typing():
            await asyncio.sleep(delay_seconds)
        return
    await asyncio.sleep(delay_seconds)


async def start_discord_client_with_delay(
    client,
    token,
    reconnect=True,
    start_delay_seconds=0.0,
):
    delay_seconds = max(float(start_delay_seconds or 0.0), 0.0)
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    await client.start(token, reconnect=reconnect)


def _is_managed_account_author_id(author_id):
    normalized_author_id = _coerce_int(author_id, None)
    if normalized_author_id is None:
        return False

    for client in bot_clients:
        managed_user = getattr(client, "user", None)
        managed_user_id = _coerce_int(getattr(managed_user, "id", None), None)
        if managed_user_id is None:
            continue
        if managed_user_id == normalized_author_id:
            return True

    return False


def _normalize_keyword_batch_size(value):
    return max(0, _coerce_int(value, 0))


def _normalize_keyword_batch_dispatch_mode(value):
    normalized = str(value or "immediate").strip().lower()
    if normalized in {"immediate", "window_end"}:
        return normalized
    return "immediate"


def _should_use_keyword_window_mode(sender_count, interval_seconds, batch_size, reply_mode):
    return (
        _coerce_int(sender_count, 0) == 1
        and _coerce_int(interval_seconds, 0) > 0
        and _normalize_keyword_batch_size(batch_size) > 0
        and str(reply_mode or "rotation").strip().lower() == "keyword"
    )


def _should_send_plain_keyword_message(prevalidated_batch, explicit_mentions, reply_mode):
    if prevalidated_batch:
        return True

    return str(reply_mode or "rotation").strip().lower() == "keyword"


def _coerce_product_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _is_product_rule_enabled(product):
    rule_enabled = (product or {}).get('autoReplyEnabled', (product or {}).get('ruleEnabled', True))
    if isinstance(rule_enabled, str):
        return rule_enabled.strip().lower() not in {'0', 'false', 'no', 'off'}
    if isinstance(rule_enabled, (int, float)):
        return bool(rule_enabled)
    return bool(rule_enabled)


def _product_has_custom_reply_images(product):
    image_source = (product or {}).get('imageSource') or (product or {}).get('image_source') or 'product'
    if image_source == 'upload':
        return bool(
            _coerce_product_list((product or {}).get('uploaded_reply_images'))
            or _coerce_product_list((product or {}).get('uploadedReplyImages'))
        )
    if image_source == 'custom':
        return bool(
            _coerce_product_list((product or {}).get('customImageUrls'))
            or _coerce_product_list((product or {}).get('custom_image_urls'))
        )
    if image_source == 'product':
        return bool(
            _coerce_product_list((product or {}).get('selectedImageIndexes'))
            or _coerce_product_list((product or {}).get('custom_reply_images'))
        )
    return False


def _product_prefers_custom_reply_images(product):
    return _product_has_custom_reply_images(product)


def _prepare_effective_product_reply(product, website_config=None, fallback_custom_reply=None):
    resolved_product = apply_effective_product_reply_settings(product, website_config=website_config)
    resolved_product['ruleEnabled'] = _is_product_rule_enabled(product)
    resolved_product['autoReplyEnabled'] = resolved_product['ruleEnabled']

    image_source = resolved_product.get('imageSource') or resolved_product.get('image_source') or 'product'
    if image_source == 'upload':
        uploaded_imgs = (
            _coerce_product_list(resolved_product.get('uploaded_reply_images'))
            or _coerce_product_list(resolved_product.get('uploadedReplyImages'))
        )
        resolved_product['uploaded_reply_images'] = uploaded_imgs
        resolved_product['uploadedReplyImages'] = uploaded_imgs
    elif image_source == 'custom':
        custom_urls = (
            _coerce_product_list(resolved_product.get('customImageUrls'))
            or _coerce_product_list(resolved_product.get('custom_image_urls'))
        )
        resolved_product['customImageUrls'] = custom_urls
        resolved_product['custom_image_urls'] = custom_urls
    elif image_source == 'product':
        selected_indexes = (
            _coerce_product_list(resolved_product.get('selectedImageIndexes'))
            or _coerce_product_list(resolved_product.get('custom_reply_images'))
        )
        resolved_product['selectedImageIndexes'] = selected_indexes
        resolved_product['custom_reply_images'] = selected_indexes

    rule_enabled = _is_product_rule_enabled(resolved_product)
    has_custom_images = _product_has_custom_reply_images(resolved_product)
    custom_reply = fallback_custom_reply

    if not rule_enabled or has_custom_images:
        custom_text = (
            resolved_product.get('custom_reply_text')
            or resolved_product.get('customReplyText')
            or ''
        ).strip()
        custom_reply = {
            'reply_type': 'text' if custom_text else 'custom_only',
            'content': custom_text,
            'product_data': resolved_product,
        }

    return resolved_product, custom_reply, rule_enabled, has_custom_images


def _build_product_reply_channel_scopes(channel_id, website_config=None):
    channel_id_str = str(channel_id)
    channel_scopes = []

    if website_config:
        config_name = (website_config.get('name') or '').strip().lower()
        config_display = (website_config.get('display_name') or '').strip().lower()
        if config_name:
            channel_scopes.append(config_name)
        if config_display and config_display not in channel_scopes:
            channel_scopes.append(config_display)
        config_id = website_config.get('id')
        if config_id is not None:
            channel_scopes.append(str(config_id))

    if channel_scopes:
        return channel_scopes

    if config.CNFANS_CHANNEL_ID and channel_id_str == str(config.CNFANS_CHANNEL_ID):
        return ['cnfans']
    if config.ACBUY_CHANNEL_ID and channel_id_str == str(config.ACBUY_CHANNEL_ID):
        return ['acbuy']
    return ['weidian']


def _parse_product_reply_scopes(product_scope_raw):
    if isinstance(product_scope_raw, str):
        product_scope_raw = product_scope_raw.strip()

    if (
        not product_scope_raw
        or (isinstance(product_scope_raw, str) and product_scope_raw.lower() == 'all')
    ):
        return []

    if isinstance(product_scope_raw, list):
        scopes = product_scope_raw
    elif isinstance(product_scope_raw, str):
        if product_scope_raw.startswith('['):
            try:
                scopes = json.loads(product_scope_raw)
            except json.JSONDecodeError:
                scopes = [product_scope_raw]
        else:
            scopes = [product_scope_raw]
    else:
        scopes = [str(product_scope_raw)]

    return [
        str(scope).strip().lower()
        for scope in scopes
        if str(scope).strip()
    ]


def _product_custom_scope_matches(product, channel_id, website_config=None):
    product_scope_raw = (product or {}).get('replyScope') or (product or {}).get('reply_scope') or 'all'
    normalized_scopes = _parse_product_reply_scopes(product_scope_raw)
    if not normalized_scopes:
        return True

    channel_scopes = _build_product_reply_channel_scopes(channel_id, website_config=website_config)
    return any(scope in channel_scopes for scope in normalized_scopes) if channel_scopes else False


def _should_send_product_custom_images(custom_reply, product, channel_id, website_config=None):
    if not isinstance(custom_reply, dict):
        return True
    if custom_reply.get('product_data') is None:
        return True
    return _product_custom_scope_matches(product, channel_id, website_config=website_config)


def _build_keyword_direct_send_payload(
    author_id,
    reply_content,
    base_custom_reply=None,
    repeat_product_ids=None,
    reply_content_is_final=False,
):
    entry = {
        'reply_content': (reply_content or '').strip(),
        'reply_content_is_final': bool(reply_content_is_final),
    }
    if author_id:
        entry['author_id'] = author_id

    content = build_batched_reply_content([entry]).strip()
    payload = {
        'reply_type': 'custom_only',
        'content': content,
        'explicit_mentions': True,
        'skip_reference': True,
        'final_direct_content': True,
    }

    if isinstance(base_custom_reply, dict):
        if base_custom_reply.get('skip_images'):
            payload['skip_images'] = True
        if base_custom_reply.get('product_data') is not None:
            payload['product_data'] = base_custom_reply.get('product_data')

    if repeat_product_ids:
        payload['repeat_product_ids'] = list(repeat_product_ids)

    return payload


def _strip_review_reply_mentions(reply_content):
    if not reply_content:
        return ''

    cleaned_lines = []
    for raw_line in str(reply_content).splitlines():
        line = re.sub(r'^<@!?\d+>\s*', '', raw_line.strip())
        if line:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines).strip()


def _prepare_review_dispatch_custom_reply(custom_reply):
    if not isinstance(custom_reply, dict):
        return custom_reply

    prepared = dict(custom_reply)
    content = prepared.get('content')
    if isinstance(content, str) and content.strip():
        prepared['content'] = _strip_review_reply_mentions(content)

    return prepared


def _build_message_reference(message, reply_target_channel):
    if message is None or reply_target_channel is None:
        return None

    message_id = _coerce_int(getattr(message, 'id', None), None)
    if message_id is None:
        return None

    get_partial_message = getattr(reply_target_channel, 'get_partial_message', None)
    if callable(get_partial_message):
        try:
            return get_partial_message(message_id)
        except Exception:
            pass

    channel_id = _coerce_int(getattr(reply_target_channel, 'id', None), None)
    if channel_id is None:
        channel_id = _coerce_int(getattr(getattr(message, 'channel', None), 'id', None), None)
    guild_id = _coerce_int(getattr(getattr(reply_target_channel, 'guild', None), 'id', None), None)
    if guild_id is None:
        guild_id = _coerce_int(getattr(getattr(message, 'guild', None), 'id', None), None)

    try:
        return discord.MessageReference(
            message_id=message_id,
            channel_id=channel_id,
            guild_id=guild_id,
            fail_if_not_exists=False,
        )
    except Exception:
        return message


def _resolve_image_reply_threshold(match_context, website_config):
    base_threshold = _coerce_float((match_context or {}).get('base_threshold'))
    if base_threshold is None:
        base_threshold = config.DISCORD_SIMILARITY_THRESHOLD
    website_threshold = _coerce_float((website_config or {}).get('image_similarity_threshold'))
    return website_threshold if website_threshold is not None else base_threshold


def _is_image_match_above_reply_threshold(match_context, website_config):
    if not isinstance(match_context, dict) or match_context.get('type') != 'image':
        return True

    similarity = _coerce_float(match_context.get('similarity')) or 0.0
    threshold_to_use = _resolve_image_reply_threshold(match_context, website_config)
    return similarity >= threshold_to_use


def _resolve_best_match_image_threshold(match_context, website_config):
    if not isinstance(match_context, dict) or match_context.get('type') != 'image':
        return None

    reply_threshold = _resolve_image_reply_threshold(match_context, website_config)
    base_threshold = _coerce_float((match_context or {}).get('best_match_image_base_threshold'))
    website_threshold = _coerce_float(
        (website_config or {}).get('best_match_image_similarity_threshold')
    )
    threshold_to_use = website_threshold if website_threshold is not None else base_threshold
    if threshold_to_use is None:
        threshold_to_use = reply_threshold
    return max(threshold_to_use, reply_threshold)


def _should_send_best_match_reply_image(match_context, website_config):
    if not isinstance(match_context, dict) or match_context.get('type') != 'image':
        return False

    similarity = _coerce_float(match_context.get('similarity')) or 0.0
    if not _is_image_match_above_reply_threshold(match_context, website_config):
        return False

    threshold_to_use = _resolve_best_match_image_threshold(match_context, website_config)
    if threshold_to_use is None:
        return False
    return similarity >= threshold_to_use


def _extract_image_match_top1_margin(payload):
    if not isinstance(payload, dict):
        return None

    margin = _coerce_float(payload.get('top1_margin'))
    if margin is not None:
        return margin

    score_breakdown = payload.get('scoreBreakdown') or payload.get('score_breakdown') or {}
    if isinstance(score_breakdown, dict):
        margin = _coerce_float(
            score_breakdown.get('top1Margin', score_breakdown.get('top1_margin'))
        )
        if margin is not None:
            return margin

    return None


def _should_allow_below_threshold_link_reply(match_context):
    return bool(
        isinstance(match_context, dict)
        and match_context.get('type') == 'image'
        and match_context.get('allow_below_threshold_link_reply')
    )


def _resolve_image_reply_min_top1_margin():
    configured = _coerce_float(
        getattr(config, 'DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN', 0.0)
    )
    return max(configured or 0.0, 0.0)


def _get_image_match_reply_block_reason(match_context, website_config):
    if not isinstance(match_context, dict) or match_context.get('type') != 'image':
        return None

    similarity = _coerce_float(match_context.get('similarity')) or 0.0
    threshold_to_use = _resolve_image_reply_threshold(match_context, website_config)

    if similarity < threshold_to_use:
        return (
            f"📷 图片相似度 {similarity:.3f} 低于网站阈值 {threshold_to_use:.3f}，跳过回复"
        )

    return None


def _normalize_sender_id_override(sender_ids):
    normalized_ids = []
    for sender_id in sender_ids or []:
        normalized = _coerce_int(sender_id, None)
        if normalized is None or normalized in normalized_ids:
            continue
        normalized_ids.append(normalized)
    return normalized_ids


def _normalize_saved_review_reply_target_payload(payload):
    if not isinstance(payload, dict):
        return {}

    channel_id = _coerce_int(payload.get('channel_id'), None)
    parent_channel_id = _coerce_int(payload.get('parent_channel_id'), None)

    return {
        'used_thread_reply': bool(payload.get('used_thread_reply') and channel_id is not None),
        'channel_id': channel_id,
        'channel_name': str(payload.get('channel_name') or ''),
        'parent_channel_id': parent_channel_id,
        'parent_channel_name': str(payload.get('parent_channel_name') or ''),
    }


def _message_has_existing_thread_hint(message):
    if message is None:
        return False

    channel = getattr(message, 'channel', None)
    if _resolve_forum_parent_channel_id(channel) is not None:
        return True

    thread_obj = getattr(message, 'thread', None)
    if _coerce_int(getattr(thread_obj, 'id', None), None) is not None:
        return True

    flags = getattr(message, 'flags', None)
    return bool(getattr(flags, 'has_thread', False))


def _build_keyword_review_message_proxy(review_item):
    payload = review_item.get('payload') or {}
    message_payload = payload.get('message') or {}
    reply_target_payload = _normalize_saved_review_reply_target_payload(
        payload.get('reply_target_channel') or {}
    )
    use_saved_reply_target = bool(reply_target_payload.get('used_thread_reply'))

    def _parse_message_time(value):
        if isinstance(value, datetime):
            return value
        if not value:
            return datetime.now().astimezone()
        text = str(value).strip()
        if not text:
            return datetime.now().astimezone()
        normalized = text.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now().astimezone()
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed

    guild_id = _coerce_int(message_payload.get('guild_id') or review_item.get('guild_id'), None)
    channel_id = _coerce_int(message_payload.get('channel_id') or review_item.get('channel_id'), None)
    parent_channel_id = _coerce_int(message_payload.get('parent_channel_id'), None)
    message_thread_id = _coerce_int(message_payload.get('thread_id'), None)
    if use_saved_reply_target:
        channel_id = _coerce_int(reply_target_payload.get('channel_id'), channel_id)
        parent_channel_id = _coerce_int(
            reply_target_payload.get('parent_channel_id'),
            parent_channel_id,
        )
        message_thread_id = _coerce_int(
            reply_target_payload.get('channel_id'),
            message_thread_id,
        )
    author_id = _coerce_int(
        message_payload.get('author_id')
        or review_item.get('sender_id')
        or review_item.get('author_id'),
        None,
    )

    guild_name = (
        message_payload.get('guild_name')
        or review_item.get('guild_name')
        or ''
    )
    channel_name = (
        reply_target_payload.get('channel_name') if use_saved_reply_target else None
    ) or (
        message_payload.get('channel_name')
        or review_item.get('channel_name')
        or ''
    )
    parent_channel_name = (
        reply_target_payload.get('parent_channel_name') if use_saved_reply_target else None
    ) or (
        message_payload.get('parent_channel_name')
        or review_item.get('parent_channel_name')
        or ''
    )
    author_name = (
        message_payload.get('author_display_name')
        or message_payload.get('author_name')
        or review_item.get('sender_name')
        or ''
    )

    guild = SimpleNamespace(
        id=guild_id,
        name=guild_name,
    )
    parent_channel = None
    if parent_channel_id is not None:
        parent_channel = SimpleNamespace(
            id=parent_channel_id,
            name=parent_channel_name,
            guild=guild,
        )

    channel = SimpleNamespace(
        id=channel_id,
        name=channel_name,
        guild=guild,
        parent_id=parent_channel_id,
        parent=parent_channel,
    )

    author = SimpleNamespace(
        id=author_id,
        name=message_payload.get('author_name') or author_name,
        display_name=author_name,
        bot=False,
    )

    message_content = (
        message_payload.get('content')
        or review_item.get('source_content')
        or ''
    )
    message_has_thread = bool(
        message_payload.get('has_thread')
        or message_thread_id is not None
        or use_saved_reply_target
    )
    message = SimpleNamespace(
        id=_coerce_int(message_payload.get('id') or review_item.get('message_id'), None),
        content=message_content,
        clean_content=message_payload.get('clean_content') or message_content,
        created_at=_parse_message_time(message_payload.get('created_at')),
        author=author,
        channel=channel,
        guild=guild,
        jump_url=message_payload.get('jump_url') or '',
        mentions=[],
        mention_everyone=False,
        reference=None,
        type=getattr(discord.MessageType, 'default', None),
        thread=SimpleNamespace(id=message_thread_id) if message_thread_id is not None else None,
        flags=SimpleNamespace(has_thread=message_has_thread),
    )
    return message


def _select_keyword_review_dispatch_client(review_item):
    user_id = _coerce_int(review_item.get('user_id'), None)
    if user_id is None:
        return None

    preferred_account_ids = {
        _coerce_int(account_id, None)
        for account_id in (review_item.get('account_ids') or [])
        if _coerce_int(account_id, None) is not None
    }

    running_clients = []
    for client in bot_clients:
        if getattr(client, 'user_id', None) != user_id:
            continue
        if not getattr(client, 'running', False):
            continue
        is_closed = getattr(client, 'is_closed', None)
        if callable(is_closed) and is_closed():
            continue
        running_clients.append(client)
    if not running_clients:
        return None

    for client in running_clients:
        if preferred_account_ids and getattr(client, 'account_id', None) in preferred_account_ids:
            return client

    return running_clients[0]


def _resolve_current_review_dispatch_website_config(review_item, message, payload_website_config):
    website_config = payload_website_config if isinstance(payload_website_config, dict) else {}
    website_id = _coerce_int(website_config.get('id') or review_item.get('website_id'), None)
    user_id = _coerce_int(review_item.get('user_id'), None)
    if website_id is None or user_id is None or message is None:
        return website_config

    try:
        try:
            from database import db
        except ImportError:
            from .database import db

        lookup_ids = DiscordBotClient._resolve_channel_lookup_ids(getattr(message, 'channel', None))
        current_configs = db.get_website_configs_by_channel(lookup_ids, user_id)
        matched_config = next(
            (config for config in (current_configs or []) if _coerce_int(config.get('id'), None) == website_id),
            None,
        )
        if matched_config:
            return matched_config
    except Exception as exc:
        logger.warning(
            f"刷新审核派发网站配置失败: website_id={website_id} user_id={user_id} | {exc}"
        )

    return website_config


async def dispatch_keyword_review_item(review_item):
    """审批通过后，按当前网站配置和账号状态发送待审关键词回复。"""
    item_id = _coerce_int(review_item.get('id'), None)
    try:
        try:
            from database import db
        except ImportError:
            from .database import db

        client = _select_keyword_review_dispatch_client(review_item)
        if client is None:
            raise RuntimeError('没有可用的在线机器人账号来发送审核通过的消息')

        payload = review_item.get('payload') or {}
        message = _build_keyword_review_message_proxy(review_item)
        saved_reply_target_payload = payload.get('reply_target_channel') or {}
        website_config = _resolve_current_review_dispatch_website_config(
            review_item,
            message,
            payload.get('website_config') or {},
        )
        if not isinstance(website_config, dict):
            website_config = {}
        if not website_config.get('id'):
            website_config = {
                'id': review_item.get('website_id'),
            }
        product = payload.get('product') or {}
        custom_reply = _prepare_review_dispatch_custom_reply(payload.get('custom_reply'))
        match_context = payload.get('match_context')

        block_reason = _get_image_match_reply_block_reason(match_context, website_config)
        if block_reason:
            logger.info(f"审批后发送前命中图片阈值拦截: {block_reason}")
            if item_id:
                db.update_keyword_reply_review_item_status(
                    item_id,
                    'failed',
                    error_message=block_reason,
                )
            return False

        success = await client.schedule_reply(
            message,
            product,
            custom_reply,
            match_context,
            website_configs_override=[website_config],
            skip_filters=True,
            skip_repeat_checks=True,
            skip_review_check=True,
            force_reference_reply=True,
            disable_thread_creation=False,
            sender_ids_override=payload.get('selected_sender_ids') or review_item.get('account_ids'),
            saved_reply_target_payload=saved_reply_target_payload,
            strict_saved_reply_target=bool(saved_reply_target_payload.get('used_thread_reply')),
        )
        if item_id:
            db.update_keyword_reply_review_item_status(
                item_id,
                'sent' if success else 'failed',
                error_message=None if success else '审批后发送失败',
            )
        return success
    except Exception as e:
        logger.error(f"审批后发送关键词回复失败: {e}")
        if item_id:
            try:
                from database import db
            except ImportError:
                from .database import db
            try:
                db.update_keyword_reply_review_item_status(
                    item_id,
                    'failed',
                    error_message=str(e),
                )
            except Exception:
                pass
        return False


def _build_multi_reply_content(author_id, reply_contents, reply_mode):
    cleaned_contents = [
        (content or "").strip()
        for content in (reply_contents or ())
        if (content or "").strip()
    ]
    if not cleaned_contents:
        return ""

    normalized_mode = str(reply_mode or "rotation").strip().lower()
    if normalized_mode != "keyword" or not author_id:
        return "\n".join(cleaned_contents)

    entries = [
        {
            'author_id': author_id,
            'reply_content': content,
        }
        for content in cleaned_contents
    ]
    return build_batched_reply_content(entries)


def _should_mention_reply_author(explicit_mentions, reply_mode):
    if explicit_mentions:
        return False
    return str(reply_mode or "rotation").strip().lower() != "default"


def _resolve_runtime_rotation_settings(website_config, user_settings, sender_count):
    website_config = website_config or {}
    user_settings = user_settings or {}
    base_rotation_interval = _coerce_int(website_config.get('rotation_interval', 180), 180)
    current_settings = {
        'rotation_interval': _coerce_int(
            user_settings.get('rotation_interval', base_rotation_interval),
            base_rotation_interval,
        ),
        'rotation_enabled': 1 if _coerce_bool(
            user_settings.get('rotation_enabled', website_config.get('rotation_enabled', 1)),
            True,
        ) else 0,
        'keyword_reply_interval': _coerce_int(
            user_settings.get('keyword_reply_interval', website_config.get('keyword_reply_interval', base_rotation_interval)),
            base_rotation_interval,
        ),
        'keyword_reply_batch_size': _normalize_keyword_batch_size(
            user_settings.get('keyword_reply_batch_size', website_config.get('keyword_reply_batch_size', 0))
        ),
        'keyword_batch_dispatch_mode': _normalize_keyword_batch_dispatch_mode(
            user_settings.get(
                'keyword_batch_dispatch_mode',
                website_config.get('keyword_batch_dispatch_mode', 'immediate'),
            )
        ),
        'reply_mode': user_settings.get('reply_mode', website_config.get('reply_mode', 'rotation')),
    }
    return resolve_rotation_settings_update(
        current_settings=current_settings,
        sender_count=sender_count,
    )


def _coerce_bool(value, default=True):
    if isinstance(value, str):
        return value.strip().lower() not in {'0', 'false', 'no', 'off'}
    if isinstance(value, (int, float, bool)):
        return bool(value)
    return default


def _coerce_float(value):
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_auto_reply_thread_name(message):
    author_name = str(getattr(getattr(message, 'author', None), 'name', '') or '').strip()
    content = re.sub(r'\s+', ' ', str(getattr(message, 'content', '') or '')).strip()
    if content:
        base_name = content[:80]
    elif author_name:
        base_name = f"{author_name} 的消息"
    else:
        base_name = f"自动回复-{getattr(message, 'id', 'thread')}"

    base_name = base_name.strip()[:95].strip()
    return base_name or f"自动回复-{getattr(message, 'id', 'thread')}"


async def _resolve_client_channel(target_client, channel_id):
    normalized_channel_id = _coerce_int(channel_id, None)
    if normalized_channel_id is None or target_client is None:
        return None

    try:
        channel = target_client.get_channel(normalized_channel_id)
    except Exception:
        channel = None
    if channel is not None:
        _clear_sender_channel_access_cache(target_client, normalized_channel_id)
        return channel

    if _get_cached_sender_channel_inaccessible(target_client, normalized_channel_id):
        return None

    fetch_channel = getattr(target_client, 'fetch_channel', None)
    if callable(fetch_channel):
        try:
            channel = await fetch_channel(normalized_channel_id)
            if channel is not None:
                _clear_sender_channel_access_cache(target_client, normalized_channel_id)
                return channel
            _store_sender_channel_inaccessible(target_client, normalized_channel_id)
        except Exception as exc:
            _store_sender_channel_inaccessible(target_client, normalized_channel_id)
            logger.warning(f"获取子分区频道失败: {normalized_channel_id} | {exc}")
    return None


async def _resolve_message_reply_channel(target_client, message):
    if message is None:
        return None
    message_channel = getattr(message, "channel", None)
    message_channel_id = getattr(message_channel, "id", None)
    resolved_channel = await _resolve_client_channel(target_client, message_channel_id)
    if resolved_channel is not None:
        return resolved_channel

    parent_channel_id = getattr(message_channel, "parent_id", None)
    if parent_channel_id is None:
        parent_channel = getattr(message_channel, "parent", None)
        parent_channel_id = getattr(parent_channel, "id", None)
    if parent_channel_id is not None:
        logger.info(
            f"子区频道不可达，当前发送账号不能在该子区回复: "
            f"channel={message_channel_id} parent={parent_channel_id}"
        )
        return None
    return None


async def _filter_channel_accessible_sender_ids(sender_ids, clients, message):
    ordered_sender_ids = []
    seen = set()
    for raw_sender_id in sender_ids or []:
        sender_id = _coerce_int(raw_sender_id, None)
        if sender_id is None or sender_id in seen:
            continue
        ordered_sender_ids.append(sender_id)
        seen.add(sender_id)

    if not ordered_sender_ids:
        return []

    client_by_account_id = {}
    for client in clients or []:
        account_id = _coerce_int(getattr(client, "account_id", None), None)
        if account_id is not None and account_id not in client_by_account_id:
            client_by_account_id[account_id] = client

    async def resolve_sender_access(sender_id):
        client = client_by_account_id.get(sender_id)
        if client is None:
            return sender_id, False
        return sender_id, await _resolve_message_reply_channel(client, message) is not None

    access_results = await asyncio.gather(
        *(resolve_sender_access(sender_id) for sender_id in ordered_sender_ids)
    )

    return [sender_id for sender_id, is_accessible in access_results if is_accessible]


async def _resolve_message_thread_id(message):
    if message is None:
        return None

    message_thread_id = getattr(getattr(message, 'thread', None), 'id', None)
    if message_thread_id is not None:
        return message_thread_id

    message_thread_id = _coerce_int(getattr(message, 'thread_id', None), None)
    if message_thread_id is not None:
        return message_thread_id

    message_flags = getattr(message, 'flags', None)
    has_thread = bool(getattr(message_flags, 'has_thread', False))
    fetch_thread = getattr(message, 'fetch_thread', None)
    if has_thread and callable(fetch_thread):
        try:
            fetched_thread = await fetch_thread()
        except Exception as exc:
            logger.warning(f"获取消息关联子分区失败: {getattr(message, 'id', None)} | {exc}")
        else:
            fetched_thread_id = _coerce_int(getattr(fetched_thread, 'id', None), None)
            if fetched_thread_id is not None:
                return fetched_thread_id

    return None


def _extract_raw_message_thread_id(raw_message):
    if not isinstance(raw_message, dict):
        return None

    raw_thread = raw_message.get('thread') or {}
    raw_thread_id = _coerce_int(raw_thread.get('id'), None)
    if raw_thread_id is not None:
        return raw_thread_id

    raw_message_id = _coerce_int(raw_message.get('id'), None)
    raw_flags = _coerce_int(raw_message.get('flags'), None)
    if raw_message_id is not None and raw_flags is not None and raw_flags & 32:
        return raw_message_id

    return None


async def _resolve_message_thread_id_from_raw_message(target_client, message):
    if target_client is None or message is None:
        return None

    message_id = _coerce_int(getattr(message, 'id', None), None)
    message_channel = getattr(message, 'channel', None)
    channel_id = _coerce_int(getattr(message_channel, 'id', None), None)
    if message_id is None or channel_id is None:
        return None

    http_client = getattr(target_client, 'http', None)
    get_message = getattr(http_client, 'get_message', None)
    if not callable(get_message):
        return None

    try:
        raw_message = await get_message(channel_id, message_id)
    except Exception as exc:
        logger.warning(f"通过原始消息接口获取子分区失败: {message_id} | {exc}")
        return None

    return _extract_raw_message_thread_id(raw_message)


async def _resolve_existing_reply_thread_after_create_failure(
    target_client,
    target_channel,
    message,
):
    message_thread_id = await _resolve_message_thread_id(message)
    if message_thread_id is None:
        message_thread_id = await _resolve_message_thread_id_from_raw_message(
            target_client,
            message,
        )
    if message_thread_id is not None:
        existing_thread = await _resolve_client_channel(target_client, message_thread_id)
        if existing_thread is not None:
            _store_cached_auto_reply_thread_id(message, message_thread_id)
            return existing_thread

    fetch_message = getattr(target_channel, 'fetch_message', None)
    message_id = getattr(message, 'id', None)
    if callable(fetch_message) and message_id is not None:
        try:
            refreshed_message = await fetch_message(message_id)
        except Exception as exc:
            logger.warning(f"刷新消息以获取子分区失败: {message_id} | {exc}")
        else:
            refreshed_thread_id = await _resolve_message_thread_id(refreshed_message)
            if refreshed_thread_id is None:
                refreshed_thread_id = await _resolve_message_thread_id_from_raw_message(
                    target_client,
                    refreshed_message,
                )
            if refreshed_thread_id is not None:
                existing_thread = await _resolve_client_channel(target_client, refreshed_thread_id)
                if existing_thread is not None:
                    _store_cached_auto_reply_thread_id(message, refreshed_thread_id)
                    return existing_thread

    active_threads = getattr(target_channel, 'threads', None)
    if active_threads and message_id is not None:
        for thread in active_threads:
            starter_message_id = getattr(getattr(thread, 'starter_message', None), 'id', None)
            if starter_message_id == message_id:
                thread_id = getattr(thread, 'id', None)
                if thread_id is not None:
                    _store_cached_auto_reply_thread_id(message, thread_id)
                return thread

    return None


async def _resolve_archived_reply_thread(target_client, target_channel, message):
    message_id = getattr(message, 'id', None)
    if target_channel is None or message_id is None:
        return None

    archived_threads = getattr(target_channel, 'archived_threads', None)
    if not callable(archived_threads):
        return None

    for private in (False, True):
        try:
            iterator = archived_threads(private=private, limit=100)
            async for thread in iterator:
                starter_message_id = getattr(getattr(thread, 'starter_message', None), 'id', None)
                if starter_message_id != message_id:
                    continue
                thread_id = getattr(thread, 'id', None)
                resolved_thread = await _resolve_client_channel(target_client, thread_id)
                resolved_thread = resolved_thread or thread
                if thread_id is not None:
                    _store_cached_auto_reply_thread_id(message, thread_id)
                return resolved_thread
        except Exception as exc:
            logger.warning(
                f"查找归档子区失败: message={message_id} channel={getattr(target_channel, 'id', None)} private={private} | {exc}"
            )

    return None


async def _create_reply_thread_for_message(target_channel, message):
    message_id = getattr(message, 'id', None)
    if target_channel is None or message_id is None:
        return None

    create_thread = getattr(target_channel, 'create_thread', None)
    if not callable(create_thread):
        logger.warning(
            f"当前频道不支持创建子区: message={message_id} "
            f"channel={getattr(target_channel, 'id', None)}"
        )
        return None

    try:
        created_thread = await create_thread(
            name=_build_auto_reply_thread_name(message),
            message=message,
        )
    except TypeError:
        try:
            created_thread = await create_thread(
                name=_build_auto_reply_thread_name(message),
                message_id=message_id,
            )
        except TypeError as exc:
            logger.warning(
                f"当前 Discord 库不支持按源消息创建子区: message={message_id} "
                f"channel={getattr(target_channel, 'id', None)} | {exc}"
            )
            return None
    except Exception as exc:
        logger.warning(
            f"创建消息子区失败: message={message_id} "
            f"channel={getattr(target_channel, 'id', None)} | {exc}"
        )
        return None

    thread_id = getattr(created_thread, 'id', None)
    if thread_id is not None:
        _store_cached_auto_reply_thread_id(message, thread_id)
    logger.info(
        f"已创建消息子区用于回复: message={message_id} "
        f"thread={thread_id} channel={getattr(target_channel, 'id', None)}"
    )
    return created_thread


async def _wait_for_reply_thread(
    target_client,
    target_channel,
    message,
    *,
    timeout_seconds=None,
    poll_seconds=None,
):
    message_id = getattr(message, 'id', None)
    timeout = THREAD_REPLY_WAIT_TIMEOUT_SECONDS if timeout_seconds is None else float(timeout_seconds or 0.0)
    poll = THREAD_REPLY_WAIT_POLL_SECONDS if poll_seconds is None else float(poll_seconds or 0.0)
    timeout = max(timeout, 0.0)
    poll = max(poll, 0.25)
    if timeout <= 0:
        return None

    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        existing_thread = await _resolve_existing_reply_thread_after_create_failure(
            target_client,
            target_channel,
            message,
        )
        if existing_thread is not None:
            logger.info(
                f"等待后已找到消息子区: message={message_id} "
                f"thread={getattr(existing_thread, 'id', None)} attempts={attempt}"
            )
            return existing_thread

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning(
                f"等待消息子区超时，当前回复将跳过: message={message_id} "
                f"channel={getattr(target_channel, 'id', None)} timeout={timeout:.1f}s attempts={attempt}"
            )
            return None
        await asyncio.sleep(min(poll, remaining))


async def resolve_reply_target_channel(
    target_client,
    target_channel,
    message,
    thread_reply_enabled=False,
    thread_wait_timeout_seconds=None,
    thread_wait_poll_seconds=None,
):
    if not thread_reply_enabled or target_channel is None or message is None:
        return target_channel, False

    if _resolve_forum_parent_channel_id(target_channel) is not None:
        target_thread_id = getattr(target_channel, 'id', None)
        if target_thread_id is not None:
            _store_cached_auto_reply_thread_id(message, target_thread_id)
        return target_channel, True

    cached_thread_id = _get_cached_auto_reply_thread_id(message)
    if cached_thread_id is not None:
        cached_thread = await _resolve_client_channel(target_client, cached_thread_id)
        if cached_thread is not None:
            return cached_thread, True
        _clear_cached_auto_reply_thread_id(message)

    current_channel = getattr(message, 'channel', None)
    current_channel_parent_id = _resolve_forum_parent_channel_id(current_channel)
    if current_channel_parent_id is not None:
        current_thread = await _resolve_client_channel(target_client, getattr(current_channel, 'id', None))
        if current_thread is not None:
            current_thread_id = getattr(current_thread, 'id', None)
            if current_thread_id is not None:
                _store_cached_auto_reply_thread_id(message, current_thread_id)
            return current_thread, True

    message_thread_id = await _resolve_message_thread_id(message)
    if message_thread_id is None:
        message_thread_id = await _resolve_message_thread_id_from_raw_message(
            target_client,
            message,
        )
    if message_thread_id is not None:
        existing_thread = await _resolve_client_channel(target_client, message_thread_id)
        if existing_thread is not None:
            _store_cached_auto_reply_thread_id(message, message_thread_id)
            return existing_thread, True

    existing_thread = await _resolve_existing_reply_thread_after_create_failure(
        target_client,
        target_channel,
        message,
    )
    if existing_thread is not None:
        return existing_thread, True

    archived_thread = await _resolve_archived_reply_thread(target_client, target_channel, message)
    if archived_thread is not None:
        return archived_thread, True

    created_thread = await _create_reply_thread_for_message(target_channel, message)
    if created_thread is not None:
        return created_thread, True

    existing_thread_after_create = await _resolve_existing_reply_thread_after_create_failure(
        target_client,
        target_channel,
        message,
    )
    if existing_thread_after_create is not None:
        return existing_thread_after_create, True

    waited_thread = await _wait_for_reply_thread(
        target_client,
        target_channel,
        message,
        timeout_seconds=thread_wait_timeout_seconds,
        poll_seconds=thread_wait_poll_seconds,
    )
    if waited_thread is not None:
        return waited_thread, True

    logger.warning(
        f"未找到也未能创建消息子区: message={getattr(message, 'id', None)} "
        f"channel={getattr(target_channel, 'id', None)}"
    )
    return None, False


def _build_keyword_window_key(user_id, website_id, guild_id):
    return (
        _coerce_int(user_id, 0),
        _coerce_int(website_id, 0),
        _coerce_int(guild_id, 0),
    )


def _normalize_keyword_search_text(value: str) -> str:
    return _shared_normalize_keyword_search_text(value)


def _tokenize_keyword_search_text(normalized_text: str):
    return _shared_tokenize_keyword_search_text(normalized_text)


def _build_query_keyword_candidates(normalized_text: str):
    return _shared_build_query_keyword_candidates(normalized_text)


def _resolve_forum_parent_channel_id(channel_like):
    if channel_like is None or not hasattr(channel_like, 'id'):
        return None

    parent_id = getattr(channel_like, 'parent_id', None)
    if parent_id is None:
        parent = getattr(channel_like, 'parent', None)
        parent_id = getattr(parent, 'id', None)
    return parent_id


def filter_forum_channel_configs_for_message(
    channel_like,
    direct_configs,
    parent_configs,
    settings_map,
):
    parent_id = _resolve_forum_parent_channel_id(channel_like)
    if parent_id is None:
        return list(direct_configs or parent_configs or [])

    if direct_configs:
        return list(direct_configs)

    filtered_configs = []
    for config in parent_configs or []:
        website_id = config.get('id')
        website_settings = settings_map.get(website_id) or {}
        if _coerce_bool(website_settings.get('forum_post_reply_enabled', 0), False):
            filtered_configs.append(config)
    return filtered_configs


def _is_forum_post_starter_message(message):
    channel = getattr(message, 'channel', None)
    if _resolve_forum_parent_channel_id(channel) is None:
        return False

    message_id = _coerce_int(getattr(message, 'id', None), None)
    if message_id is None:
        return False

    starter_message = getattr(channel, 'starter_message', None)
    starter_message_id = _coerce_int(getattr(starter_message, 'id', None), None)
    if starter_message_id is not None:
        return starter_message_id == message_id

    starter_message_id = _coerce_int(getattr(channel, 'starter_message_id', None), None)
    if starter_message_id is not None:
        return starter_message_id == message_id

    # Forum post channels are created from the starter message; for many selfbot
    # message objects the post channel id equals the starter message id.
    channel_id = _coerce_int(getattr(channel, 'id', None), None)
    return channel_id == message_id


def _build_forum_post_search_text(message):
    parts = []
    if _is_forum_post_starter_message(message):
        title = str(getattr(getattr(message, 'channel', None), 'name', '') or '').strip()
        if title:
            parts.append(title)

    content = str(
        getattr(message, 'clean_content', None)
        or getattr(message, 'content', None)
        or ''
    ).strip()
    if content:
        parts.append(content)

    search_text = re.sub(r'\s+', ' ', ' '.join(parts)).strip()
    return search_text


def _build_product_keyword_variants(raw_value: str):
    return _shared_build_product_keyword_variants(raw_value)


def _find_query_keyword_match(
    query_keyword_candidates,
    english_title=None,
    title=None,
    title_translations=None,
    allowed_languages=None,
    query_text=None,
    partition_match_enabled=False,
    partition_match_rules=None,
):
    return _shared_find_query_keyword_match(
        query_keyword_candidates,
        english_title,
        title,
        title_translations=title_translations,
        allowed_languages=allowed_languages,
        query_text=query_text,
        partition_match_enabled=partition_match_enabled,
        partition_match_rules=partition_match_rules,
    )


def _get_repeat_seconds_from_filters(filters):
    max_seconds = 0.0
    for rule in filters or []:
        if rule.get('filter_type') != 'user_repeat':
            continue
        try:
            seconds_val = float(rule.get('filter_value') or 0)
        except (TypeError, ValueError):
            continue
        if seconds_val > max_seconds:
            max_seconds = seconds_val
    return max_seconds if max_seconds > 0 else 0.0

def _get_repeat_filter_seconds():
    now = time.time()
    cached = _repeat_filter_cache.get('seconds', 0.0)
    cached_ts = _repeat_filter_cache.get('ts', 0.0)
    if cached_ts and (now - cached_ts) < 30:
        return cached

    try:
        try:
            from database import db
        except ImportError:
            from .database import db
        filters = db.get_message_filters()
        max_seconds = 0.0
        for rule in filters:
            if rule.get('filter_type') != 'user_repeat':
                continue
            try:
                seconds_val = float(rule.get('filter_value') or 0)
            except (TypeError, ValueError):
                continue
            if seconds_val > max_seconds:
                max_seconds = seconds_val
        seconds = max_seconds if max_seconds > 0 else 0.0
    except Exception as e:
        logger.error(f"获取重复发送过滤配置失败: {e}")
        seconds = 0.0

    _repeat_filter_cache['seconds'] = seconds
    _repeat_filter_cache['ts'] = now
    return seconds

async def _is_recent_repeat(user_id: str, product_id: str, channel_id: str, window_seconds: float) -> bool:
    if not window_seconds or window_seconds <= 0:
        return False
    now = time.time()
    key = (str(user_id), str(product_id), str(channel_id))
    async with _repeat_cache_lock:
        last = _repeat_reply_cache.get(key)
        if last and (now - last) < window_seconds:
            return True
        # 清理过期记录
        expiry = now - (window_seconds * 2)
        for cached_key, ts in list(_repeat_reply_cache.items()):
            if ts < expiry:
                _repeat_reply_cache.pop(cached_key, None)
    return False

async def _record_repeat(user_id: str, product_id: str, channel_id: str):
    key = (str(user_id), str(product_id), str(channel_id))
    async with _repeat_cache_lock:
        _repeat_reply_cache[key] = time.time()

IMAGE_RECOGNITION_MAX_INFLIGHT = max(
    int(getattr(config, 'DISCORD_IMAGE_RECOGNITION_MAX_INFLIGHT', 2) or 2),
    1,
)
# 图片识别已经由后端队列控制；这里限制同账号并发，避免单个 worker 瞬时压满后端。
ai_concurrency_limit = asyncio.Semaphore(IMAGE_RECOGNITION_MAX_INFLIGHT)

# 冷却等待保护：避免在高并发下长时间占用消息处理链路
MAX_COOLDOWN_WAIT_SECONDS = 3.0

# 单条消息各阶段的超时保护，避免某一步卡死拖住后续消息
MESSAGE_FORWARD_TIMEOUT_SECONDS = 15.0
THREAD_REPLY_WAIT_TIMEOUT_SECONDS = max(
    _coerce_float(getattr(config, 'DISCORD_THREAD_REPLY_WAIT_TIMEOUT_SECONDS', 180.0)) or 180.0,
    0.0,
)
THREAD_REPLY_WAIT_POLL_SECONDS = max(
    _coerce_float(getattr(config, 'DISCORD_THREAD_REPLY_WAIT_POLL_SECONDS', 2.0)) or 2.0,
    0.25,
)
MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS = max(
    _coerce_float(getattr(config, 'DISCORD_MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS', 45.0)) or 45.0,
    THREAD_REPLY_WAIT_TIMEOUT_SECONDS + 30.0,
)
MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS = max(
    _coerce_float(getattr(config, 'DISCORD_MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS', 130.0)) or 130.0,
    30.0,
)
MESSAGE_IMAGE_REPLY_MAX_ATTACHMENTS = max(
    int(getattr(config, 'DISCORD_IMAGE_REPLY_MAX_ATTACHMENTS_PER_MESSAGE', 2) or 2),
    1,
)
MESSAGE_STAGE_SLOW_SECONDS = max(float(getattr(config, 'DISCORD_MESSAGE_STAGE_SLOW_SECONDS', 5.0) or 5.0), 1.0)
KEYWORD_TEXT_SEARCH_TIMEOUT_SECONDS = max(
    float(getattr(config, 'KEYWORD_TEXT_SEARCH_TIMEOUT_SECONDS', 8.0) or 8.0),
    1.0,
)
KEYWORD_TEXT_SEARCH_MAX_INFLIGHT = max(
    int(getattr(config, 'KEYWORD_TEXT_SEARCH_MAX_INFLIGHT', 3) or 3),
    1,
)
keyword_text_search_concurrency_limit = asyncio.Semaphore(KEYWORD_TEXT_SEARCH_MAX_INFLIGHT)

# 关键词搜索候选上限（覆盖每页200商品的测试场景）
KEYWORD_SEARCH_LIMIT = 600


def _get_image_recognition_request_timeout_seconds(stage_timeout_seconds) -> float:
    configured_timeout = _coerce_float(
        getattr(config, 'DISCORD_IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS', None)
    )
    if configured_timeout is not None and configured_timeout > 0:
        return max(1.0, configured_timeout)
    try:
        stage_timeout = float(stage_timeout_seconds)
    except (TypeError, ValueError):
        return 30.0
    if stage_timeout <= 0:
        return 30.0
    return max(30.0, stage_timeout - 5.0)


IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS = _get_image_recognition_request_timeout_seconds(
    MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS
)
IMAGE_RECOGNITION_MAX_ATTEMPTS = max(
    int(getattr(config, 'DISCORD_IMAGE_RECOGNITION_MAX_ATTEMPTS', 1) or 1),
    1,
)
IMAGE_RECOGNITION_RETRY_DELAY_SECONDS = max(
    float(getattr(config, 'DISCORD_IMAGE_RECOGNITION_RETRY_DELAY_SECONDS', 1.0) or 1.0),
    0.0,
)


def get_all_cooldowns():
    """获取所有活跃的冷却状态（供 API 查询）"""
    current_time = time.time()
    cooldowns = []

    snapshot = account_last_sent.copy()

    for key, last_sent in snapshot.items():
        try:
            acc_id, ch_id = key
            time_passed = current_time - last_sent

            if time_passed < 86400:
                cooldowns.append({
                    'account_id': int(acc_id),
                    'channel_id': str(ch_id),
                    'last_sent': last_sent,
                    'time_passed': time_passed
                })
        except Exception:
            continue

    return cooldowns


def _resolve_cooldown_channel_id(channel_like):
    """把子区/线程消息的冷却统一归到主频道，便于前端按绑定频道展示"""
    if channel_like is None:
        return ""

    if isinstance(channel_like, (str, int)):
        return str(channel_like)

    parent_id = getattr(channel_like, "parent_id", None)
    if parent_id is not None:
        return str(parent_id)

    channel_id = getattr(channel_like, "id", channel_like)
    return str(channel_id)

def get_account_cooldown_remaining(account_id, channel_id, interval):
    """返回账号在频道中的剩余冷却秒数"""
    try:
        normalized_interval = float(interval or 0)
    except (TypeError, ValueError):
        return 0.0

    if normalized_interval <= 0:
        return 0.0

    key = (int(account_id), str(channel_id))
    last = account_last_sent.get(key, 0)
    remaining = normalized_interval - (time.time() - last)
    return remaining if remaining > 0 else 0.0

def build_sender_dispatch_plan(
    db_sender_ids,
    valid_senders,
    channel_id,
    rotation_interval,
    rotation_enabled,
    skip_sender_cooldown,
    reply_mode,
):
    """根据回复模式和冷却状态决定本轮应该由哪些发送账号执行"""
    ordered_valid_senders = []
    seen = set()
    valid_sender_set = {uid for uid in valid_senders}

    for raw_uid in db_sender_ids or []:
        uid = _coerce_int(raw_uid, None)
        if uid is None or uid not in valid_sender_set or uid in seen:
            continue
        ordered_valid_senders.append(uid)
        seen.add(uid)

    for raw_uid in valid_senders or []:
        uid = _coerce_int(raw_uid, None)
        if uid is None or uid in seen:
            continue
        ordered_valid_senders.append(uid)
        seen.add(uid)

    if not ordered_valid_senders:
        return {'selected_ids': [], 'wait_seconds': 0.0}

    normalized_mode = str(reply_mode or "rotation").strip().lower()
    if skip_sender_cooldown:
        if normalized_mode == 'all':
            return {'selected_ids': ordered_valid_senders, 'wait_seconds': 0.0}
        should_spread_senders = bool(rotation_enabled) or len(ordered_valid_senders) > 1
        selected_id = random.choice(ordered_valid_senders) if should_spread_senders else ordered_valid_senders[0]
        return {'selected_ids': [selected_id], 'wait_seconds': 0.0}

    if normalized_mode == 'all':
        wait_seconds = 0.0
        for uid in ordered_valid_senders:
            wait_seconds = max(
                wait_seconds,
                get_account_cooldown_remaining(uid, channel_id, rotation_interval),
            )
        if wait_seconds > 0:
            return {'selected_ids': [], 'wait_seconds': wait_seconds}
        return {'selected_ids': ordered_valid_senders, 'wait_seconds': 0.0}

    available_senders = [
        uid for uid in ordered_valid_senders
        if get_account_cooldown_remaining(uid, channel_id, rotation_interval) <= 0
    ]
    if not available_senders:
        wait_candidates = [
            get_account_cooldown_remaining(uid, channel_id, rotation_interval)
            for uid in ordered_valid_senders
        ]
        wait_seconds = min((remain for remain in wait_candidates if remain > 0), default=0.0)
        return {'selected_ids': [], 'wait_seconds': wait_seconds}

    if rotation_enabled:
        selected_id = random.choice(available_senders)
    else:
        available_set = set(available_senders)
        selected_id = next((uid for uid in ordered_valid_senders if uid in available_set), available_senders[0])

    return {'selected_ids': [selected_id], 'wait_seconds': 0.0}

def is_account_on_cooldown(account_id, channel_id, interval):
    """检查账号在指定频道是否在冷却中"""
    remaining = get_account_cooldown_remaining(account_id, channel_id, interval)
    is_cooldown = remaining > 0

    if is_cooldown:
        logger.info(f"❄️ [冷却中] 账号ID:{account_id} 频道:{channel_id} | 剩余: {remaining:.1f}秒")

    return is_cooldown

def set_account_cooldown(account_id, channel_id):
    """设置账号在指定频道的冷却时间"""
    key = (int(account_id), str(channel_id))
    account_last_sent[key] = time.time()
    logger.info(f"🔥 [设置冷却] 账号ID:{account_id} 频道:{channel_id} | Key: {key}")

def apply_reply_mode_cooldown(reply_mode, sender_ids, channel_id):
    """按回复模式应用冷却，all 模式会为整组发送账号统一落冷却"""
    normalized_mode = str(reply_mode or "rotation").strip().lower()
    unique_sender_ids = []
    seen = set()
    for raw_uid in sender_ids or []:
        uid = _coerce_int(raw_uid, None)
        if uid is None or uid in seen:
            continue
        unique_sender_ids.append(uid)
        seen.add(uid)

    if normalized_mode == 'all':
        for uid in unique_sender_ids:
            set_account_cooldown(uid, channel_id)
        return

    if unique_sender_ids:
        set_account_cooldown(unique_sender_ids[0], channel_id)

def cleanup_expired_cooldowns():
    """清理过期的冷却状态"""
    current_time = time.time()
    expired_keys = []
    for key, last_sent in account_last_sent.items():
        # 如果冷却时间超过24小时，清理掉（防止内存泄漏）
        if current_time - last_sent > 86400:  # 24小时
            expired_keys.append(key)

    for key in expired_keys:
        del account_last_sent[key]
        logger.debug(f"清理过期冷却: {key}")

    if expired_keys:
        logger.info(f"清理了 {len(expired_keys)} 个过期的冷却状态")

def mark_message_as_processed(message_id, user_id=None):
    """检查消息是否已处理（按用户隔离的原子去重）"""
    try:
        from database import db
        scoped_message_id = str(message_id)
        if user_id is not None:
            scoped_message_id = f"{user_id}:{message_id}"
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO processed_messages (message_id) VALUES (?)", (scoped_message_id,))
            conn.commit()
        return True  # 抢锁成功
    except sqlite3.IntegrityError:
        return False  # 已经被其他Bot抢锁

def get_response_url_for_channel(product, channel_id, user_id=None, website_config=None):
    """根据频道ID和网站配置决定发送哪个链接"""
    import re
    try:
        from database import db
    except ImportError:
        from .database import db

    channel_id_str = str(channel_id)

    # 1. 首先尝试根据频道绑定获取网站配置
    if not website_config:
        website_config = db.get_website_config_by_channel(channel_id_str, user_id)

    if website_config and website_config.get('url_template'):
        # 从商品URL中提取微店ID
        weidian_url = product.get('weidianUrl') or product.get('product_url') or ''
        weidian_id = None

        # 尝试从URL中提取itemID
        match = re.search(r'itemID=(\d+)', weidian_url)
        if match:
            weidian_id = match.group(1)
        else:
            # 尝试从weidianId字段获取
            weidian_id = product.get('weidianId')

        if weidian_id:
            # 使用URL模板生成链接
            url = website_config['url_template'].replace('{id}', weidian_id)
            logger.info(f"使用网站配置 '{website_config['name']}' 的URL模板生成链接: {url[:50]}...")
            return url

    # 2. 回退到旧的硬编码逻辑（兼容性）
    if config.CNFANS_CHANNEL_ID and channel_id_str == config.CNFANS_CHANNEL_ID:
        if product.get('cnfansUrl'):
            return product['cnfansUrl']
        elif product.get('acbuyUrl'):
            return product['acbuyUrl']
        else:
            return product.get('weidianUrl', '未找到相关商品')

    elif config.ACBUY_CHANNEL_ID and channel_id_str == config.ACBUY_CHANNEL_ID:
        if product.get('acbuyUrl'):
            return product['acbuyUrl']
        elif product.get('cnfansUrl'):
            return product['cnfansUrl']
        else:
            return product.get('weidianUrl', '未找到相关商品')

    # 3. 默认发送CNFans链接
    else:
        if product.get('cnfansUrl'):
            return product['cnfansUrl']
        else:
            return product.get('weidianUrl', '未找到相关商品')

class HTTPLogHandler(logging.Handler):
    """通过HTTP发送日志到Flask应用"""
    def __init__(self):
        super().__init__()
        self.pending_logs = []
        self.is_sending = False

    def emit(self, record):
        try:
            # 只发送我们关心的日志级别
            if record.levelno >= logging.INFO:
                log_data = format_record_log_entry(record, formatter=self.formatter)

                # 添加到待发送队列
                self.pending_logs.append(log_data)

                # 如果没有正在发送，启动发送任务
                if not self.is_sending:
                    # 在机器人的事件循环中创建任务
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(self.send_pending_logs())
                        else:
                            # 如果循环没有运行，直接发送（同步方式）
                            self.send_sync(log_data)
                    except RuntimeError:
                        # 没有事件循环，直接同步发送
                        self.send_sync(log_data)

        except Exception as e:
            print(f"HTTP日志处理器错误: {e}")

    def send_sync(self, log_data):
        """同步发送日志（作为fallback）"""
        try:
            import requests
            # 【修复】强制使用 127.0.0.1，因为这是进程间通信，不应走公网
            local_api_url = 'http://127.0.0.1:5001/api'
            response = requests.post(f'{local_api_url}/logs/add',
                                   json=log_data, timeout=2, proxies={'http': None, 'https': None, 'all': None})
            if response.status_code != 200:
                print(f"同步发送日志失败: {response.status_code}")
        except Exception as e:
            # 这里的 print 可能会被重定向，但至少不会抛出 ConnectionRefusedError 炸断流程
            pass

    async def send_pending_logs(self):
        """异步发送待处理的日志"""
        if self.is_sending:
            return

        self.is_sending = True

        # 【修复】强制使用 127.0.0.1
        local_api_url = 'http://127.0.0.1:5001/api'

        try:
            while self.pending_logs:
                log_data = self.pending_logs.pop(0)

                try:
                    async with aiohttp.ClientSession(trust_env=False) as session:
                        async with session.post(f'{local_api_url}/logs/add',
                                              json=log_data, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                            if resp.status != 200:
                                print(f"发送日志失败: {resp.status}")
                except Exception as e:
                    # 队列满了就丢弃，不要无限堆积
                    if len(self.pending_logs) < 1000:
                        self.pending_logs.insert(0, log_data)
                    break

                # 小延迟避免发送太快
                await asyncio.sleep(0.01) # 加快发送速度，减少积压

        finally:
            self.is_sending = False

# 配置日志
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# 添加HTTP日志处理器
http_handler = HTTPLogHandler()
http_handler.setLevel(logging.INFO)
root_handlers = logging.getLogger().handlers
if root_handlers and getattr(root_handlers[0], "formatter", None) is not None:
    http_handler.setFormatter(root_handlers[0].formatter)
logging.getLogger().addHandler(http_handler)

logger = logging.getLogger(__name__)

# 确保discord库也使用我们的日志配置
logging.getLogger('discord').setLevel(logging.INFO)

class DiscordBotClient(discord.Client):
    # 【新增】频道白名单缓存（类级别共享，所有Bot实例共用）
    _bound_channels_cache = set()  # 已绑定的频道ID集合
    _last_cache_update = 0  # 上次缓存更新时间戳
    _cache_ttl = max(
        _coerce_float(getattr(config, 'DISCORD_BOUND_CHANNEL_CACHE_TTL_SECONDS', 60.0)) or 60.0,
        1.0,
    )  # 缓存有效期（秒）

    def __init__(self, account_id=None, user_id=None, user_shops=None, role='both'):
        # discord.py-self 可能不需要 intents，或者使用不同的语法
        try:
            # 尝试使用标准的 intents
            intents = discord.Intents.default()
            intents.message_content = True
            intents.messages = True
            intents.guilds = True
            if hasattr(intents, "reactions"):
                intents.reactions = True
            if hasattr(intents, "guild_reactions"):
                intents.guild_reactions = True
            if hasattr(intents, "dm_reactions"):
                intents.dm_reactions = True
            super().__init__(**build_discord_client_runtime_options(intents=intents))
        except (AttributeError, TypeError):
            # 如果 Intents 不存在，直接初始化（discord.py-self 可能不需要）
            super().__init__(**build_discord_client_runtime_options())
        self.current_token = None
        self.running = False
        self.account_id = account_id
        self.user_id = user_id  # 用户ID，用于获取个性化设置
        self.user_shops = user_shops  # 用户管理的店铺列表
        self.role = role  # 'listener', 'sender', 'both' - 账号角色
        self.last_ready_at = 0.0
        self.last_disconnect_at = 0.0
        self.disconnect_count = 0
        self._gateway_disconnect_events = []
        self._offline_status_task = None
        # DM 会话提醒去重：避免“会话创建 + 首条DM消息”重复推送
        self._dm_alert_cache = {}

    def _schedule_event(self, coro, event_name, *args, **kwargs):
        loop = getattr(self, 'loop', None)
        create_task = getattr(loop, 'create_task', None)
        if not callable(create_task):
            logger.warning(
                'Discord事件已忽略，客户端事件循环不可用: event=%s account_id=%s user_id=%s loop_type=%s',
                event_name,
                self.account_id,
                self.user_id,
                type(loop).__name__,
            )
            try:
                wrapped = self._run_event(coro, event_name, *args, **kwargs)
                wrapped.close()
            except Exception:
                logger.debug('关闭未调度Discord事件协程失败', exc_info=True)
            return None
        return super()._schedule_event(coro, event_name, *args, **kwargs)

    def _mark_dm_alert(self, channel_id):
        if channel_id is None:
            return
        now = time.time()
        self._dm_alert_cache[int(channel_id)] = now
        expiry = now - 120
        for cid, ts in list(self._dm_alert_cache.items()):
            if ts < expiry:
                self._dm_alert_cache.pop(cid, None)

    def _is_dm_alert_recent(self, channel_id, window_seconds=20):
        if channel_id is None:
            return False
        ts = self._dm_alert_cache.get(int(channel_id))
        if not ts:
            return False
        return (time.time() - ts) < window_seconds

    @staticmethod
    def _resolve_channel_lookup_ids(channel_or_id):
        if channel_or_id is None:
            return []

        if hasattr(channel_or_id, 'id'):
            current_id = getattr(channel_or_id, 'id', None)
            parent_id = getattr(channel_or_id, 'parent_id', None)
            if parent_id is None:
                parent = getattr(channel_or_id, 'parent', None)
                parent_id = getattr(parent, 'id', None)

            lookup_ids = []
            for candidate in (current_id, parent_id):
                normalized = str(candidate or '').strip()
                if normalized and normalized not in lookup_ids:
                    lookup_ids.append(normalized)
            return lookup_ids

        normalized = str(channel_or_id or '').strip()
        return [normalized] if normalized else []

    async def _run_message_stage_with_timeout(self, message, stage_name, coro, timeout_seconds):
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.error(
                f"⏱️ 消息处理超时: stage={stage_name} | message_id={message.id} "
                f"| channel_id={message.channel.id} | timeout={timeout_seconds:.1f}s"
            )
            return False
        except Exception as e:
            logger.error(
                f"消息处理阶段失败: stage={stage_name} | message_id={message.id} "
                f"| channel_id={message.channel.id} | error={e}"
            )
            return False

        elapsed = time.monotonic() - start_time
        if elapsed >= MESSAGE_STAGE_SLOW_SECONDS:
            logger.warning(
                f"🐢 消息处理耗时较长: stage={stage_name} | message_id={message.id} "
                f"| channel_id={message.channel.id} | elapsed={elapsed:.2f}s"
            )
        return True if result is None else result

    async def _refresh_channel_cache(self, force=False):
        """【新增】刷新频道白名单缓存（60秒TTL）

        从数据库获取所有已绑定的频道ID，更新类级别缓存。
        使用TTL机制避免频繁查询数据库。
        """
        current_time = time.time()

        # 检查缓存是否过期
        if not force and current_time - DiscordBotClient._last_cache_update < DiscordBotClient._cache_ttl:
            return  # 缓存仍然有效，无需刷新

        try:
            # 在线程池中执行数据库查询（避免阻塞事件循环）
            try:
                from database import db
            except ImportError:
                from .database import db

            channel_ids = await asyncio.get_event_loop().run_in_executor(
                None, db.get_all_bound_channel_ids
            )

            # 更新类级别缓存
            DiscordBotClient._bound_channels_cache = channel_ids
            DiscordBotClient._last_cache_update = current_time

            logger.debug(f"✅ 频道白名单缓存已刷新，共 {len(channel_ids)} 个频道")

        except Exception as e:
            logger.error(f"❌ 刷新频道白名单缓存失败: {e}")
            # 失败时不更新时间戳，下次会重试

    async def _get_user_settings_safe(self):
        if not self.user_id:
            return {}
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            return await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
        except Exception as e:
            logger.error(f"获取用户设置失败(user_id={self.user_id}): {e}")
            return {}

    async def _get_user_website_settings_safe(self, website_id):
        if not self.user_id or not website_id:
            return {}
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            return await asyncio.get_event_loop().run_in_executor(
                None, db.get_user_website_settings, self.user_id, website_id
            )
        except Exception as e:
            logger.error(f"获取用户网站设置失败(user_id={self.user_id}, website_id={website_id}): {e}")
            return {}

    def _parse_message_filters(self, raw_filters):
        if not raw_filters:
            return []
        if isinstance(raw_filters, list):
            return raw_filters
        if isinstance(raw_filters, str):
            try:
                parsed = json.loads(raw_filters)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []

    def _filters_block_message(self, message, filters, match_context=None):
        return filters_block_message(
            message,
            filters,
            match_context=match_context,
            message_has_image=self._message_has_image,
        )

    @staticmethod
    def _get_message_author_name(message):
        author = getattr(message, 'author', None)
        return (
            getattr(author, 'display_name', None)
            or getattr(author, 'name', None)
            or str(getattr(author, 'id', '未知用户'))
        )

    @staticmethod
    def _find_filter_keyword_match(source_text, filters, filter_type):
        normalized_source = str(source_text or '').strip().lower()
        if not normalized_source:
            return None

        for filter_rule in filters or []:
            if (filter_rule or {}).get('filter_type') != filter_type:
                continue
            for keyword in split_filter_values((filter_rule or {}).get('filter_value')):
                normalized_keyword = str(keyword or '').strip().lower()
                if normalized_keyword and normalized_keyword in normalized_source:
                    return normalized_keyword
        return None

    async def _get_user_website_settings_map_for_configs(self, website_configs):
        if not self.user_id:
            return {}

        website_ids = [
            website_config.get('id')
            for website_config in (website_configs or [])
            if website_config.get('id')
        ]
        if not website_ids:
            return {}

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            return await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: db.get_user_website_settings_map(self.user_id, website_ids),
            )
        except Exception as e:
            logger.error(f"获取网站设置映射失败(user_id={self.user_id}): {e}")
            return {}

    async def _exclude_blocked_website_configs(self, message, website_configs):
        if not self.user_id or not website_configs:
            return list(website_configs or [])

        author_id = getattr(getattr(message, 'author', None), 'id', None)
        if author_id is None:
            return list(website_configs)

        candidate_website_ids = [
            website_config.get('id')
            for website_config in website_configs
            if website_config.get('id') is not None
        ]
        if not candidate_website_ids:
            return list(website_configs)

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            blocked_website_ids = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: db.get_blocked_website_ids_for_discord_user(
                    user_id=self.user_id,
                    discord_user_id=str(author_id),
                    candidate_website_ids=candidate_website_ids,
                ),
            )
        except Exception as e:
            logger.error(f"查询网站拉黑用户失败(user_id={self.user_id}, author_id={author_id}): {e}")
            return list(website_configs)

        if not blocked_website_ids:
            return list(website_configs)

        blocked_names = [
            website_config.get('display_name') or website_config.get('name') or str(website_config.get('id'))
            for website_config in website_configs
            if website_config.get('id') in blocked_website_ids
        ]
        logger.info(
            "🚫 网站拉黑用户命中: 作者=%s(%s) | 网站=%s",
            self._get_message_author_name(message),
            author_id,
            ', '.join(blocked_names) or ', '.join(str(item) for item in blocked_website_ids),
        )
        return [
            website_config
            for website_config in website_configs
            if website_config.get('id') not in blocked_website_ids
        ]

    async def _apply_website_block_user_triggers(
        self,
        message,
        website_configs,
        user_website_settings_map=None,
    ):
        if not self.user_id or not website_configs:
            return set()

        message_content = str(getattr(message, 'content', None) or '').strip().lower()
        if not message_content:
            return set()

        author = getattr(message, 'author', None)
        author_id = getattr(author, 'id', None)
        if author_id is None:
            return set()

        if user_website_settings_map is None:
            user_website_settings_map = await self._get_user_website_settings_map_for_configs(website_configs)

        author_name = self._get_message_author_name(message)
        triggered_website_ids = set()

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
        except Exception as e:
            logger.error(f"导入数据库模块失败，无法写入网站拉黑用户: {e}")
            return set()

        for website_config in website_configs:
            website_id = website_config.get('id')
            if not website_id:
                continue
            website_settings = user_website_settings_map.get(website_id) or {}
            website_filters = self._parse_message_filters(website_settings.get('message_filters', '[]'))
            matched_keyword = self._find_filter_keyword_match(
                message_content,
                website_filters,
                'website_block_user_trigger',
            )
            if not matched_keyword:
                continue

            try:
                saved = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: db.upsert_website_blocked_user(
                        user_id=self.user_id,
                        website_id=website_id,
                        discord_user_id=str(author_id),
                        discord_username=author_name,
                        trigger_keyword=matched_keyword,
                    ),
                )
            except Exception as e:
                logger.error(
                    f"写入网站拉黑用户失败(user_id={self.user_id}, website_id={website_id}, author_id={author_id}): {e}"
                )
                continue

            if not saved:
                continue

            triggered_website_ids.add(website_id)
            logger.info(
                "🚫 网站拉黑触发: 作者=%s(%s) | 网站=%s | 触发词=%s",
                author_name,
                author_id,
                website_config.get('display_name') or website_config.get('name') or website_id,
                matched_keyword,
            )

        return triggered_website_ids

    async def _is_globally_blocked_author(self, message):
        author_id = getattr(getattr(message, 'author', None), 'id', None)
        if author_id is None:
            return False

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            global_filters = await asyncio.get_event_loop().run_in_executor(None, db.get_message_filters)
        except Exception as e:
            logger.error(f"获取全局拉黑触发规则失败(author_id={author_id}): {e}")
            return False

        candidate_filter_ids = [
            int(filter_rule.get('id'))
            for filter_rule in (global_filters or [])
            if filter_rule.get('filter_type') == 'website_block_user_trigger'
            and filter_rule.get('id') is not None
        ]
        if not candidate_filter_ids:
            return False

        try:
            blocked_filter_ids = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: db.get_blocked_message_filter_ids_for_discord_user(
                    discord_user_id=str(author_id),
                    candidate_filter_ids=candidate_filter_ids,
                ),
            )
        except Exception as e:
            logger.error(f"查询全局拉黑用户失败(author_id={author_id}): {e}")
            return False

        if not blocked_filter_ids:
            return False

        logger.info(
            "🚫 全局拉黑用户命中: 作者=%s(%s) | 规则=%s",
            self._get_message_author_name(message),
            author_id,
            ', '.join(str(item) for item in sorted(blocked_filter_ids)),
        )
        return True

    async def _apply_global_block_user_triggers(self, message):
        message_content = str(getattr(message, 'content', None) or '').strip().lower()
        if not message_content:
            return set()

        author = getattr(message, 'author', None)
        author_id = getattr(author, 'id', None)
        if author_id is None:
            return set()

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            global_filters = await asyncio.get_event_loop().run_in_executor(None, db.get_message_filters)
        except Exception as e:
            logger.error(f"获取全局拉黑触发规则失败(author_id={author_id}): {e}")
            return set()

        author_name = self._get_message_author_name(message)
        triggered_filter_ids = set()

        for filter_rule in global_filters or []:
            if filter_rule.get('filter_type') != 'website_block_user_trigger':
                continue

            filter_id = filter_rule.get('id')
            if filter_id is None:
                continue

            matched_keyword = self._find_filter_keyword_match(
                message_content,
                [filter_rule],
                'website_block_user_trigger',
            )
            if not matched_keyword:
                continue

            try:
                saved = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: db.upsert_message_filter_blocked_user(
                        filter_id=int(filter_id),
                        discord_user_id=str(author_id),
                        discord_username=author_name,
                        trigger_keyword=matched_keyword,
                    ),
                )
            except Exception as e:
                logger.error(
                    f"写入全局拉黑用户失败(filter_id={filter_id}, author_id={author_id}): {e}"
                )
                continue

            if not saved:
                continue

            triggered_filter_ids.add(int(filter_id))
            logger.info(
                "🚫 全局拉黑触发: 作者=%s(%s) | 规则=%s | 触发词=%s",
                author_name,
                author_id,
                filter_id,
                matched_keyword,
            )

        return triggered_filter_ids

    def _get_repeat_product_ids(self, product, custom_reply=None):
        product_id = product.get('id') if isinstance(product, dict) else None
        repeat_product_ids = []
        if custom_reply and isinstance(custom_reply, dict):
            repeat_product_ids = custom_reply.get('repeat_product_ids') or []
        if not repeat_product_ids and product_id:
            repeat_product_ids = [product_id]
        return [pid for pid in repeat_product_ids if pid]

    async def _get_keyword_window_settings(self, website_config, sender_count):
        website_id = website_config.get('id') if website_config else None
        effective_settings = _resolve_runtime_rotation_settings(
            website_config,
            user_settings={},
            sender_count=sender_count,
        )

        if not website_id:
            return (
                max(1, effective_settings['keyword_reply_interval']),
                effective_settings['keyword_reply_batch_size'],
                effective_settings['rotation_enabled'],
                effective_settings['reply_mode'],
                effective_settings['keyword_batch_dispatch_mode'],
            )

        try:
            user_settings = await self._get_user_website_settings_safe(website_id)
            effective_settings = _resolve_runtime_rotation_settings(
                website_config,
                user_settings=user_settings,
                sender_count=sender_count,
            )
        except Exception as e:
            logger.error(f"获取关键词窗口设置失败(user_id={self.user_id}, website_id={website_id}): {e}")

        return (
            max(1, effective_settings['keyword_reply_interval']),
            effective_settings['keyword_reply_batch_size'],
            effective_settings['rotation_enabled'],
            effective_settings['reply_mode'],
            effective_settings['keyword_batch_dispatch_mode'],
        )

    def _build_explicit_mention_reply_content(self, author_id, reply_contents):
        return _build_multi_reply_content(
            author_id=author_id,
            reply_contents=reply_contents,
            reply_mode="keyword",
        )

    async def _build_keyword_reply_job(
        self,
        message,
        product,
        custom_reply,
        website_config,
        match_context=None,
        skip_review_check=False,
    ):
        if not website_config or not website_config.get('id'):
            return None

        reply_content = self._generate_reply_content(
            product,
            message.channel.id,
            custom_reply,
            website_config=website_config,
        )
        if reply_content is None:
            logger.debug(f"商品 {product.get('id')} 回复范围不匹配，跳过网站 {website_config.get('name')}")
            return None

        website_id = website_config.get('id')
        user_settings = await self._get_user_website_settings_safe(website_id)
        website_filters = self._parse_message_filters(user_settings.get('message_filters', '[]') if user_settings else '[]')

        if website_filters and self._filters_block_message(message, website_filters, match_context=match_context):
            logger.debug(f"消息被过滤(网站规则): {website_config.get('name')}")
            return None

        reply_content_is_final = bool(custom_reply and custom_reply.get('explicit_mentions'))
        repeat_product_ids = self._get_repeat_product_ids(product, custom_reply)
        repeat_window = max(
            _get_repeat_filter_seconds(),
            _get_repeat_seconds_from_filters(website_filters),
        )
        author_id = getattr(message.author, 'id', None)
        if repeat_window and author_id and repeat_product_ids:
            for pid in repeat_product_ids:
                if await _is_recent_repeat(author_id, pid, message.channel.id, repeat_window):
                    logger.info(
                        f"🚫 用户重复发送过滤: user={author_id} 商品={pid} 频道={message.channel.id} "
                        f"窗口={int(repeat_window)}秒"
                    )
                    return None

        if match_context and match_context.get('type') == 'image':
            try:
                try:
                    from database import db
                except ImportError:
                    from .database import db
                global_filters = await asyncio.get_event_loop().run_in_executor(None, db.get_message_filters)
                global_image_filters = [
                    f
                    for f in (global_filters or [])
                    if f.get('filter_type') in {'image_similarity', 'ocr_contains'}
                ]
            except Exception as e:
                logger.error(f"获取全局过滤规则失败: {e}")
                global_image_filters = []

            if global_image_filters and self._filters_block_message(
                message,
                global_image_filters,
                match_context=match_context,
            ):
                logger.debug("消息被过滤(全局图片相似度)")
                return None

            website_filter_matches = match_context.get('website_filter_matches') or []
            matched_filter = next(
                (m for m in website_filter_matches if str(m.get('website_id')) == str(website_id)),
                None
            )
            if matched_filter:
                try:
                    sim = float(matched_filter.get('similarity', 0))
                    threshold_val = float(matched_filter.get('threshold', 0))
                    if sim >= threshold_val:
                        logger.info(
                            f"🚫 网站图片过滤命中: 网站 {website_config.get('name')} "
                            f"规则 {matched_filter.get('filter_id')} 相似度 {sim:.3f} >= {threshold_val:.3f}"
                        )
                        return None
                except Exception:
                    return None

            block_reason = _get_image_match_reply_block_reason(match_context, website_config)
            if block_reason:
                logger.info(block_reason)
                return None

        rotation_interval = _coerce_int(
            user_settings.get('rotation_interval', website_config.get('rotation_interval', 180)),
            _coerce_int(website_config.get('rotation_interval', 180), 180),
        )
        keyword_reply_interval = _coerce_int(
            user_settings.get('keyword_reply_interval', website_config.get('keyword_reply_interval', rotation_interval)),
            rotation_interval,
        )
        batch_size = _normalize_keyword_batch_size(
            user_settings.get('keyword_reply_batch_size', website_config.get('keyword_reply_batch_size', 0))
        )

        if not reply_content_is_final and author_id and reply_content:
            direct_payload = _build_keyword_direct_send_payload(author_id, reply_content)
            reply_content = direct_payload['content']
            reply_content_is_final = bool(direct_payload.get('final_direct_content'))

        return {
            'client': self,
            'message': message,
            'product': product,
            'custom_reply': custom_reply,
            'website_id': website_id,
            'website_config': website_config,
            'match_context': match_context,
            'reply_content': reply_content,
            'reply_content_is_final': reply_content_is_final,
            'author_id': author_id,
            'repeat_product_ids': repeat_product_ids,
            'keyword_reply_interval': max(1, keyword_reply_interval),
            'batch_size': batch_size,
        }

    async def _dispatch_keyword_reply_batch(self, jobs):
        if not jobs:
            return False

        listener_client = next(
            (
                job.get('client')
                for job in jobs
                if job.get('client') is not None and getattr(job.get('client'), 'running', False)
            ),
            None,
        )
        if listener_client is None or not getattr(listener_client, 'running', False):
            logger.warning("⏭️ [关键词排队] 监听账号已离线，跳过队列中的关键词回复")
            return False

        message = next((job.get('message') for job in jobs if job.get('message') is not None), None)
        if message is None:
            logger.warning("⏭️ [关键词排队] 消息对象不存在，跳过队列中的关键词回复")
            return False

        website_id = jobs[0].get('website_id')
        website_config = jobs[0].get('website_config') or {}
        try:
            current_configs = await listener_client.get_website_configs_by_channel_async(message.channel)
            matched_config = next((cfg for cfg in current_configs if cfg.get('id') == website_id), None)
            if not matched_config:
                logger.info(
                    f"⏭️ [关键词排队] 网站配置 {website_id} 已不再绑定频道 {message.channel.id}，跳过批量回复"
                )
                return False
            website_config = matched_config
        except Exception as e:
            logger.error(f"刷新关键词队列网站配置失败(website_id={website_id}): {e}")

        combined_content = build_batched_reply_content(jobs)
        if not combined_content:
            logger.info("⏭️ [关键词排队] 批量回复内容为空，跳过发送")
            return False

        repeat_records = []
        for job in jobs:
            author_id = job.get('author_id')
            for product_id in job.get('repeat_product_ids') or []:
                if author_id and product_id:
                    repeat_records.append((str(author_id), str(product_id)))
        repeat_records = list(dict.fromkeys(repeat_records))

        batch_custom_reply = {
            'reply_type': 'custom_only',
            'content': combined_content,
            'skip_images': True,
            'batched_reply': True,
            'skip_sender_cooldown': True,
            'repeat_records': repeat_records,
        }

        return await listener_client.schedule_reply(
            message,
            jobs[0].get('product'),
            batch_custom_reply,
            None,
            website_configs_override=[website_config],
        )

    def _start_keyword_reply_background_task(self, coro, task_name):
        task = asyncio.create_task(coro, name=task_name)
        _keyword_reply_background_tasks.add(task)

        def _on_done(completed_task):
            _keyword_reply_background_tasks.discard(completed_task)
            try:
                completed_task.result()
            except asyncio.CancelledError:
                logger.info(f"⏭️ [关键词后台任务已取消] {task_name}")
            except Exception as e:
                logger.error(f"关键词后台任务失败({task_name}): {e}")

        task.add_done_callback(_on_done)
        return task

    def _start_keyword_search_background_task(self, message, website_configs_to_process):
        keyword_search_message_id = f"keyword_search:{self.user_id}:{message.id}"
        try:
            if not mark_message_as_processed(keyword_search_message_id):
                logger.debug(
                    f"关键词搜索后台已由其他账号处理: message_id={message.id} "
                    f"| user_id={self.user_id} | channel_id={message.channel.id}"
                )
                return None
        except Exception as e:
            logger.error(
                f"关键词搜索后台去重失败: message_id={message.id} "
                f"| user_id={self.user_id} | channel_id={message.channel.id} | error={e}"
            )
            return None

        task_name = (
            f"keyword-search message={getattr(message, 'id', 'unknown')} "
            f"channel={getattr(getattr(message, 'channel', None), 'id', 'unknown')}"
        )

        async def _runner():
            start_time = time.monotonic()
            try:
                await asyncio.wait_for(
                    self.handle_keyword_search(
                        message,
                        website_configs_override=website_configs_to_process,
                        allow_keyword_image_search=False,
                    ),
                    timeout=MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"⏱️ 关键词搜索后台超时: message_id={message.id} "
                    f"| channel_id={message.channel.id} | timeout={MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS:.1f}s"
                )
                return
            except Exception as e:
                logger.error(
                    f"关键词搜索后台失败: message_id={message.id} "
                    f"| channel_id={message.channel.id} | error={e}"
                )
                return

            elapsed = time.monotonic() - start_time
            if elapsed >= MESSAGE_STAGE_SLOW_SECONDS:
                logger.warning(
                    f"关键词搜索后台耗时较长: message_id={message.id} "
                    f"| channel_id={message.channel.id} | elapsed={elapsed:.2f}s"
                )

        return self._start_keyword_reply_background_task(_runner(), task_name)

    def _start_image_reply_background_task(self, message, attachment, website_configs_to_process):
        filename = getattr(attachment, 'filename', 'unknown')
        task_name = (
            f"image-reply message={getattr(message, 'id', 'unknown')} "
            f"attachment={filename}"
        )
        task = asyncio.create_task(
            self._run_message_stage_with_timeout(
                message,
                f'image_reply:{filename}',
                self.handle_image(
                    message,
                    attachment,
                    website_configs_override=website_configs_to_process,
                ),
                MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS,
            ),
            name=task_name,
        )
        _image_reply_background_tasks.add(task)

        def _on_done(completed_task):
            _image_reply_background_tasks.discard(completed_task)
            try:
                completed_task.result()
            except asyncio.CancelledError:
                logger.info(f"⏭️ [图片后台任务已取消] {task_name}")
            except Exception as e:
                logger.error(f"图片后台任务失败({task_name}): {e}")

        task.add_done_callback(_on_done)
        return task

    async def _flush_keyword_reply_queue(self, window_key):
        try:
            while True:
                async with _keyword_reply_window_lock:
                    queue_size = _keyword_reply_window_manager.get_queue_size(window_key)
                    config = _keyword_reply_window_configs.get(window_key, {})
                    interval_seconds = max(1, _coerce_int(config.get('interval_seconds', 180), 180))
                    batch_size = _normalize_keyword_batch_size(config.get('batch_size', 0))
                    dispatch_mode = _normalize_keyword_batch_dispatch_mode(
                        config.get('keyword_batch_dispatch_mode', 'immediate')
                    )

                    if queue_size <= 0:
                        _keyword_reply_window_configs.pop(window_key, None)
                        return

                    wait_seconds = _keyword_reply_window_manager.seconds_until_next_window(
                        window_key,
                        interval_seconds,
                    )

                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                async with _keyword_reply_window_lock:
                    config = _keyword_reply_window_configs.get(window_key, config)
                    interval_seconds = max(1, _coerce_int(config.get('interval_seconds', 180), 180))
                    batch_size = _normalize_keyword_batch_size(config.get('batch_size', 0))
                    dispatch_mode = _normalize_keyword_batch_dispatch_mode(
                        config.get('keyword_batch_dispatch_mode', 'immediate')
                    )
                    jobs = _keyword_reply_window_manager.release_due_jobs(
                        window_key,
                        interval_seconds,
                        batch_size,
                        dispatch_mode=dispatch_mode,
                    )
                    remaining = _keyword_reply_window_manager.get_queue_size(window_key)

                    if not jobs and remaining <= 0:
                        _keyword_reply_window_configs.pop(window_key, None)
                        return

                if jobs:
                    try:
                        await self._dispatch_keyword_reply_batch(jobs)
                    except Exception as e:
                        logger.error(f"队列中的关键词批量回复发送失败: {e}")

        finally:
            async with _keyword_reply_window_lock:
                current_task = asyncio.current_task()
                if _keyword_reply_flush_tasks.get(window_key) is current_task:
                    _keyword_reply_flush_tasks.pop(window_key, None)
                if _keyword_reply_window_manager.get_queue_size(window_key) <= 0:
                    _keyword_reply_window_configs.pop(window_key, None)

    async def _enqueue_or_dispatch_keyword_reply(
        self,
        message,
        product,
        custom_reply,
        website_config,
        match_context=None,
        skip_review_check=False,
    ):
        if not website_config or not website_config.get('id'):
            return False

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            sender_ids = await asyncio.get_event_loop().run_in_executor(
                None, db.get_website_senders, website_config.get('id'), self.user_id
            )
        except Exception as e:
            logger.error(f"获取关键词窗口发送账号失败(website_id={website_config.get('id')}): {e}")
            sender_ids = []

        interval_seconds, batch_size, rotation_enabled, reply_mode, dispatch_mode = await self._get_keyword_window_settings(
            website_config,
            sender_count=len(sender_ids),
        )
        use_keyword_window_mode = _should_use_keyword_window_mode(
            len(sender_ids),
            interval_seconds,
            batch_size,
            reply_mode,
        )

        if reply_mode == 'keyword' and not use_keyword_window_mode:
            job = await self._build_keyword_reply_job(
                message,
                product,
                custom_reply,
                website_config,
                match_context=match_context,
            )
            if job is None:
                return False

            direct_custom_reply = _build_keyword_direct_send_payload(
                author_id=job.get('author_id'),
                reply_content=job.get('reply_content'),
                base_custom_reply=custom_reply,
                repeat_product_ids=job.get('repeat_product_ids'),
                reply_content_is_final=job.get('reply_content_is_final'),
            )
            return await self.schedule_reply(
                message,
                product,
                direct_custom_reply,
                match_context,
                website_configs_override=[website_config],
                skip_review_check=skip_review_check,
            )

        if batch_size <= 0:
            return await self.schedule_reply(
                message,
                product,
                custom_reply,
                match_context,
                website_configs_override=[website_config],
                skip_review_check=skip_review_check,
            )

        if not use_keyword_window_mode:
            if batch_size > 0:
                logger.info(
                    f"⏭️ [关键词窗口未启用] 网站:{website_config.get('name')} "
                    f"发送账号数:{len(sender_ids)} 批次上限:{batch_size} 模式:{reply_mode} 轮换启用:{rotation_enabled}"
                )
            return await self.schedule_reply(
                message,
                product,
                custom_reply,
                match_context,
                website_configs_override=[website_config],
                skip_review_check=skip_review_check,
            )

        job = await self._build_keyword_reply_job(
            message,
            product,
            custom_reply,
            website_config,
            match_context=match_context,
        )
        if job is None:
            return False

        channel_id = getattr(message.channel, 'id', None)
        window_key = _build_keyword_window_key(self.user_id, website_config.get('id'), channel_id)

        should_dispatch_now = False
        queue_size = 0
        wait_seconds = 0.0
        ready_jobs = ()
        async with _keyword_reply_window_lock:
            _keyword_reply_window_configs[window_key] = {
                'interval_seconds': interval_seconds,
                'batch_size': batch_size,
                'keyword_batch_dispatch_mode': dispatch_mode,
            }
            reservation = _keyword_reply_window_manager.reserve_or_enqueue(
                window_key,
                interval_seconds,
                batch_size,
                job,
                dispatch_mode=dispatch_mode,
            )
            should_dispatch_now = reservation.dispatch_now
            queue_size = reservation.queue_size
            wait_seconds = reservation.wait_seconds
            ready_jobs = reservation.ready_payloads

            if not should_dispatch_now:
                flush_task = _keyword_reply_flush_tasks.get(window_key)
                if flush_task is None or flush_task.done():
                    _keyword_reply_flush_tasks[window_key] = asyncio.create_task(
                        self._flush_keyword_reply_queue(window_key)
                    )

        if should_dispatch_now:
            return await self._dispatch_keyword_reply_batch(list(ready_jobs))

        if not reservation.accepted:
            logger.info(
                f"⏭️ [关键词窗口已满] 网站:{website_config.get('name')} 频道:{channel_id} "
                f"批次上限:{batch_size} 策略:{dispatch_mode}，本轮忽略新增关键词"
            )
            return False

        logger.info(
            f"⏳ [关键词排队] 网站:{website_config.get('name')} 频道:{channel_id} "
            f"队列:{queue_size} 等待:{wait_seconds:.1f}秒 批次上限:{batch_size} 策略:{dispatch_mode}"
        )
        return False

    def _build_review_reply_image_previews(self, product, custom_reply, match_context=None):
        previews = []
        seen = set()

        def add_preview(url, label):
            url = str(url or '').strip()
            if not url or url in seen:
                return
            seen.add(url)
            previews.append({'url': url, 'label': label})

        product = product if isinstance(product, dict) else {}
        product_id = product.get('id')
        if isinstance(match_context, dict) and match_context.get('type') == 'image':
            matched_index = match_context.get('best_match_image_index')
            if product_id is not None and matched_index is not None:
                add_preview(f"/api/image/{product_id}/{matched_index}", '图片命中')

        active_product = product
        if isinstance(custom_reply, dict) and isinstance(custom_reply.get('product_data'), dict):
            active_product = custom_reply.get('product_data') or product
            product_id = active_product.get('id') or product_id

        if isinstance(custom_reply, dict) and custom_reply.get('skip_images'):
            return previews

        image_source = active_product.get('imageSource') or active_product.get('image_source') or 'product'
        if image_source == 'custom':
            for index, url in enumerate(self._coerce_list(active_product.get('customImageUrls') or active_product.get('custom_image_urls'))[:10], start=1):
                add_preview(url, f'自定义图片 {index}')
        elif image_source == 'upload':
            for filename in self._coerce_list(active_product.get('uploaded_reply_images'))[:10]:
                if product_id is not None:
                    add_preview(f"/api/custom_reply_image/{product_id}/{filename}", str(filename))
        else:
            for index in self._coerce_list(active_product.get('selectedImageIndexes') or active_product.get('custom_reply_images'))[:10]:
                if product_id is not None:
                    add_preview(f"/api/image/{product_id}/{index}", f'商品图片 {index}')

        return previews[:10]

    def _queue_keyword_review_item(
        self,
        *,
        message,
        product,
        custom_reply,
        website_config,
        reply_content,
        target_clients,
        selected_sender_ids,
        reply_mode,
        files=None,
        match_context=None,
        prevalidated_batch=False,
        broadcast_mode=False,
        thread_reply_enabled=False,
        reply_target_channel=None,
        used_thread_reply=False,
        cooldown_channel_id=None,
        batch_repeat_records=None,
        repeat_product_ids=None,
    ) -> int:
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            channel = getattr(message, 'channel', None)
            guild = getattr(message, 'guild', None)
            author = getattr(message, 'author', None)
            parent_channel = getattr(channel, 'parent', None)
            reply_parent_channel = getattr(reply_target_channel, 'parent', None)
            reply_parent_channel_id = (
                getattr(reply_target_channel, 'parent_id', None)
                or getattr(reply_parent_channel, 'id', None)
            )
            if (
                used_thread_reply
                and reply_parent_channel_id is None
                and reply_target_channel is not None
                and getattr(reply_target_channel, 'id', None) != getattr(channel, 'id', None)
            ):
                reply_parent_channel_id = getattr(channel, 'id', None)

            account_names = []
            for client in target_clients or []:
                client_user = getattr(client, 'user', None)
                client_name = getattr(client_user, 'name', None) or getattr(client, 'account_id', None)
                if client_name is not None:
                    account_names.append(str(client_name))

            if not account_names and selected_sender_ids:
                account_names = [str(item) for item in selected_sender_ids if item is not None]

            reply_image_previews = self._build_review_reply_image_previews(
                product,
                custom_reply,
                match_context,
            )

            preview_text = (reply_content or '').strip()
            if not preview_text:
                file_count = len(files or []) or len(reply_image_previews)
                preview_text = f"[图片 {file_count}]" if file_count else ''

            message_time = getattr(message, 'created_at', None)
            if isinstance(message_time, datetime):
                try:
                    message_time = message_time.astimezone()
                except Exception:
                    pass
                message_time_text = message_time.isoformat()
            else:
                message_time_text = ''

            payload = {
                'product': product,
                'custom_reply': custom_reply,
                'website_config': website_config,
                'match_context': match_context,
                'selected_sender_ids': list(selected_sender_ids or []),
                'reply_mode': reply_mode,
                'files_count': len(files or []),
                'reply_image_previews': reply_image_previews,
                'prevalidated_batch': bool(prevalidated_batch),
                'broadcast_mode': bool(broadcast_mode),
                'thread_reply_enabled': bool(thread_reply_enabled),
                'reply_target_channel': {
                    'used_thread_reply': bool(used_thread_reply),
                    'channel_id': getattr(reply_target_channel, 'id', None),
                    'channel_name': getattr(reply_target_channel, 'name', None) or '',
                    'parent_channel_id': reply_parent_channel_id,
                    'parent_channel_name': getattr(reply_parent_channel, 'name', None) or getattr(parent_channel, 'name', None) or '',
                } if reply_target_channel is not None else {},
                'cooldown_channel_id': cooldown_channel_id,
                'batch_repeat_records': [
                    list(item)
                    for item in (batch_repeat_records or [])
                ],
                'repeat_product_ids': list(repeat_product_ids or []),
                'message': {
                    'id': getattr(message, 'id', None),
                    'content': getattr(message, 'content', None) or '',
                    'created_at': message_time_text,
                    'author_id': getattr(author, 'id', None),
                    'author_name': getattr(author, 'name', None) or '',
                    'author_display_name': getattr(author, 'display_name', None) or getattr(author, 'name', None) or '',
                    'channel_id': getattr(channel, 'id', None),
                    'channel_name': getattr(channel, 'name', None) or '',
                    'parent_channel_id': getattr(channel, 'parent_id', None) or getattr(parent_channel, 'id', None),
                    'parent_channel_name': getattr(parent_channel, 'name', None) or '',
                    'guild_id': getattr(guild, 'id', None),
                    'guild_name': getattr(guild, 'name', None) or '',
                },
            }

            review_item = {
                'user_id': self.user_id,
                'website_id': website_config.get('id'),
                'channel_id': str(getattr(channel, 'id', '') or ''),
                'guild_id': str(getattr(guild, 'id', '') or ''),
                'guild_name': str(getattr(guild, 'name', '') or ''),
                'channel_name': str(getattr(channel, 'name', '') or ''),
                'account_ids': list(selected_sender_ids or []),
                'account_names': account_names,
                'sender_id': getattr(author, 'id', None),
                'sender_name': (
                    getattr(author, 'display_name', None)
                    or getattr(author, 'name', None)
                    or ''
                ),
                'content': preview_text,
                'source_content': getattr(message, 'content', None) or '',
                'message_id': getattr(message, 'id', None),
                'reply_mode': reply_mode,
                'status': 'pending',
                'payload': payload,
            }
            existing_review_item = db.get_active_keyword_reply_review_item_by_message(
                self.user_id,
                website_config.get('id'),
                getattr(message, 'id', None),
            )
            if existing_review_item:
                logger.info(
                    "同一消息已存在待审项，跳过重复入队: "
                    f"user={self.user_id} website={website_config.get('id')} "
                    f"message={getattr(message, 'id', None)} "
                    f"existing_item={existing_review_item.get('id')}"
                )
                return int(existing_review_item.get('id') or 0)
            return db.add_keyword_reply_review_item(review_item)
        except Exception as e:
            logger.error(f"写入关键词人工审核队列失败: {e}")
            return 0

    def _should_ignore_mass_or_activity_message(self, message):
        """屏蔽 @everyone/@here 与 Discord 活动/系统类消息。"""
        if message is None:
            return True

        if getattr(message, "mention_everyone", False):
            return True

        content_text = (getattr(message, "clean_content", None) or message.content or "").lower()
        if "@everyone" in content_text or "@here" in content_text:
            return True

        message_type = getattr(message, "type", None)
        allowed_types = {
            getattr(discord.MessageType, "default", None),
            getattr(discord.MessageType, "reply", None),
        }
        if any(message_type == allowed_type for allowed_type in allowed_types):
            return False

        message_type_name = str(
            getattr(message_type, "name", None)
            or getattr(message_type, "value", None)
            or message_type
            or ""
        ).strip().lower()
        if message_type_name in {
            "thread_starter_message",
            "forum_topic_created",
            "guild_forum_thread_created",
        }:
            return False

        return True

    async def _is_reply_to_self(self, message):
        """判断当前消息是否在回复当前账号发出的消息。"""
        if message.reference is None or not self.user:
            return False

        referenced_message = None
        try:
            referenced_message = getattr(message.reference, "cached_message", None)
            if referenced_message is None:
                resolved = getattr(message.reference, "resolved", None)
                if isinstance(resolved, discord.Message):
                    referenced_message = resolved

            if referenced_message is None and getattr(message.reference, "message_id", None):
                referenced_message = await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            return False

        if not referenced_message or not getattr(referenced_message, "author", None):
            return False

        return getattr(referenced_message.author, "id", None) == self.user.id

    async def _classify_direct_interaction(self, message):
        """识别是否出现对当前账号的直接互动（@ 或回复）。"""
        if not self.user:
            return None

        # 回复优先级高于@，避免“回复 + @”时被误判为仅@提及
        if await self._is_reply_to_self(message):
            return "reply"

        mentions = getattr(message, "mentions", None) or []
        if any(getattr(user, "id", None) == self.user.id for user in mentions):
            return "mention"

        return None

    async def _send_bark_notification(self, bark_server_url, bark_device_key, title, body, jump_url=None):
        await _send_bark_notification_payload(
            bark_server_url=bark_server_url,
            bark_device_key=bark_device_key,
            title=title,
            body=body,
            jump_url=jump_url,
        )

    async def _sync_review_bark_state(
        self,
        user_id,
        *,
        pending_count=None,
        last_notified_at=None,
    ):
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            payload = {
                'user_id': user_id,
            }
            if pending_count is not None:
                payload['review_bark_last_pending_count'] = max(0, _coerce_int(pending_count, 0))
            if last_notified_at is not None:
                payload['review_bark_last_notified_at'] = str(last_notified_at or '')

            if len(payload) > 1:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    partial(db.update_user_settings, **payload),
                )
        except Exception as e:
            logger.error(f"同步审核 Bark 状态失败(user_id={user_id}): {e}")

    async def _maybe_send_review_queue_bark_notification(self, user_id, *, trigger):
        if user_id is None:
            return

        try:
            async with _review_bark_notification_lock:
                try:
                    from database import db
                except ImportError:
                    from .database import db

                user_settings = await asyncio.get_event_loop().run_in_executor(
                    None,
                    db.get_user_settings,
                    user_id,
                )
                if not user_settings:
                    return

                review_bark_enabled = user_settings.get("review_bark_enabled", 0) in (1, True, "1", "true", "True")
                bark_device_key = (user_settings.get("bark_device_key") or "").strip()
                if not review_bark_enabled or not bark_device_key:
                    return

                pending_count = await asyncio.get_event_loop().run_in_executor(
                    None,
                    db.count_pending_keyword_reply_review_items,
                    user_id,
                )
                bark_mode = _normalize_review_bark_mode(user_settings.get("review_bark_mode"))
                now = datetime.now().astimezone()

                if trigger == "count":
                    if bark_mode != "count":
                        if pending_count > 0 and not _parse_review_bark_datetime(user_settings.get("review_bark_last_notified_at")):
                            await self._sync_review_bark_state(
                                user_id,
                                pending_count=pending_count,
                                last_notified_at=now.isoformat(),
                            )
                        return

                    threshold = max(1, _coerce_int(user_settings.get("review_bark_count_threshold"), 5))
                    last_pending_count = max(0, _coerce_int(user_settings.get("review_bark_last_pending_count"), 0))
                    if not _should_send_review_queue_bark_count_notification(
                        pending_count=pending_count,
                        threshold=threshold,
                        last_pending_count=last_pending_count,
                    ):
                        return

                    title = f"待审核消息 {pending_count} 条"
                    body = (
                        f"类型: 待审数量通知\n"
                        f"当前待审核: {pending_count} 条\n"
                        f"触发阈值: {threshold} 条\n"
                        f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await self._send_bark_notification(
                        bark_server_url=user_settings.get("bark_server_url"),
                        bark_device_key=bark_device_key,
                        title=title,
                        body=body,
                    )
                    await self._sync_review_bark_state(
                        user_id,
                        pending_count=pending_count,
                        last_notified_at=now.isoformat(),
                    )
                    logger.info(
                        f"📱 审核 Bark 通知已发送: user_id={user_id} | 类型=数量 | 待审核={pending_count}"
                    )
                    return

                if bark_mode != "interval":
                    return

                interval_minutes = max(1, _coerce_int(user_settings.get("review_bark_interval_minutes"), 60))
                if not _should_send_review_queue_bark_interval_notification(
                    pending_count=pending_count,
                    interval_minutes=interval_minutes,
                    last_notified_at=user_settings.get("review_bark_last_notified_at"),
                    now=now,
                ):
                    return

                title = f"待审核消息 {pending_count} 条"
                body = (
                    f"类型: 时间通知\n"
                    f"当前待审核: {pending_count} 条\n"
                    f"通知间隔: {interval_minutes} 分钟\n"
                    f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await self._send_bark_notification(
                    bark_server_url=user_settings.get("bark_server_url"),
                    bark_device_key=bark_device_key,
                    title=title,
                    body=body,
                )
                await self._sync_review_bark_state(
                    user_id,
                    pending_count=pending_count,
                    last_notified_at=now.isoformat(),
                )
                logger.info(
                    f"📱 审核 Bark 通知已发送: user_id={user_id} | 类型=时间 | 待审核={pending_count}"
                )
        except Exception as e:
            _log_rate_limited_bark_issue("处理审核 Bark 通知失败", _summarize_exception_for_log(e))

    async def _send_keyword_review_item_bark_notification(self, review_item_id):
        item_id = _coerce_int(review_item_id, None)
        if item_id is None:
            return

        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            review_item = await asyncio.get_event_loop().run_in_executor(
                None,
                db.get_keyword_reply_review_item,
                item_id,
                self.user_id,
            )
            if not review_item:
                return

            user_settings = await asyncio.get_event_loop().run_in_executor(
                None,
                db.get_user_settings,
                self.user_id,
            )
            if not user_settings:
                return

            review_bark_enabled = user_settings.get("review_bark_enabled", 0) in (1, True, "1", "true", "True")
            bark_device_key = (user_settings.get("bark_device_key") or "").strip()
            if not review_bark_enabled or not bark_device_key:
                return

            pending_count = await asyncio.get_event_loop().run_in_executor(
                None,
                db.count_pending_keyword_reply_review_items,
                self.user_id,
            )
            title = f"待审核: {review_item.get('sender_name') or '新消息'}"
            body = _format_review_item_bark_body(review_item, pending_count=pending_count)
            action_url = _build_keyword_review_action_url(self.user_id, item_id)
            if not action_url:
                body = f"{body}\n\n未配置 PUBLIC_FRONTEND_BASE_URL，手机通知暂不能直接打开审批页。"

            await self._send_bark_notification(
                bark_server_url=user_settings.get("bark_server_url"),
                bark_device_key=bark_device_key,
                title=title,
                body=body,
                jump_url=action_url or None,
            )
            await self._sync_review_bark_state(
                self.user_id,
                pending_count=pending_count,
                last_notified_at=datetime.now().astimezone().isoformat(),
            )
            logger.info(
                f"📱 审核 Bark 单条通知已发送: user_id={self.user_id} item_id={item_id} "
                f"has_action_url={bool(action_url)}"
            )
        except Exception as e:
            _log_rate_limited_bark_issue("发送单条审核 Bark 通知失败", _summarize_exception_for_log(e))

    async def _review_bark_monitor_loop(self):
        while True:
            try:
                try:
                    from database import db
                except ImportError:
                    from .database import db

                user_ids = await asyncio.get_event_loop().run_in_executor(
                    None,
                    db.get_pending_keyword_reply_review_user_ids,
                )
                for user_id in user_ids:
                    await self._maybe_send_review_queue_bark_notification(
                        user_id,
                        trigger="interval",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"审核 Bark 轮询任务失败: {e}")

            await asyncio.sleep(60)

    def _ensure_review_bark_monitor_task(self):
        global _review_bark_monitor_task
        if _review_bark_monitor_task is not None and not _review_bark_monitor_task.done():
            return

        _review_bark_monitor_task = asyncio.create_task(
            self._review_bark_monitor_loop(),
            name="review-bark-monitor",
        )

        def _on_done(task):
            global _review_bark_monitor_task
            if _review_bark_monitor_task is task:
                _review_bark_monitor_task = None
            try:
                task.result()
            except asyncio.CancelledError:
                logger.info("审核 Bark 轮询任务已取消")
            except Exception as e:
                logger.error(f"审核 Bark 轮询任务异常退出: {e}")

        _review_bark_monitor_task.add_done_callback(_on_done)

    async def _notify_direct_interaction_if_needed(self, message):
        interaction_type = await self._classify_direct_interaction(message)
        if not interaction_type:
            return

        user_settings = await self._get_user_settings_safe()
        bark_enabled = user_settings.get("bark_enabled", 0) in (1, True, "1", "true", "True")
        bark_device_key = (user_settings.get("bark_device_key") or "").strip()
        if not bark_enabled or not bark_device_key:
            return

        bark_server_url = (user_settings.get("bark_server_url") or "https://api.day.app").strip()
        interaction_label = "被@提及" if interaction_type == "mention" else "被回复"
        account_name = getattr(self.user, "name", None) or f"账号#{self.account_id}"
        sender_name = (
            getattr(message.author, "display_name", None)
            or getattr(message.author, "name", None)
            or "未知用户"
        )
        guild_name = message.guild.name if message.guild else "私信"
        channel_name = getattr(message.channel, "name", str(getattr(message.channel, "id", "")))

        # 优先使用 clean_content；若仍有原始 mention token，再兜底替换成 @名称
        preview_source = getattr(message, "clean_content", None) or message.content or ""
        if "<@" in preview_source:
            for mentioned_user in (getattr(message, "mentions", None) or []):
                mention_id = getattr(mentioned_user, "id", None)
                if mention_id is None:
                    continue
                mention_name = (
                    getattr(mentioned_user, "display_name", None)
                    or getattr(mentioned_user, "name", None)
                    or str(mention_id)
                )
                preview_source = preview_source.replace(f"<@{mention_id}>", f"@{mention_name}")
                preview_source = preview_source.replace(f"<@!{mention_id}>", f"@{mention_name}")

        content_preview = preview_source.replace("\n", " ").strip()
        if not content_preview:
            content_preview = "[无文本内容]"
        if len(content_preview) > 120:
            content_preview = f"{content_preview[:120]}..."

        message_time = getattr(message, "created_at", None)
        if isinstance(message_time, datetime):
            try:
                message_time = message_time.astimezone()
            except Exception:
                pass
            time_text = message_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            time_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        title = content_preview
        if title == "[无文本内容]":
            title = f"{sender_name} {interaction_label}"
        if len(title) > 60:
            title = f"{title[:60]}..."

        body = (
            f"账号: {account_name}\n"
            f"类型: {interaction_label}\n"
            f"发送者: {sender_name}\n"
            f"位置: {guild_name} / #{channel_name}\n"
            f"内容: {content_preview}\n"
            f"时间: {time_text}"
        )

        await self._send_bark_notification(
            bark_server_url=bark_server_url,
            bark_device_key=bark_device_key,
            title=title,
            body=body,
            jump_url=getattr(message, "jump_url", None),
        )

        logger.info(
            f"📱 Bark通知已发送: 账号:{account_name} | 类型:{interaction_label} | 发送者:{sender_name} | 频道:{channel_name}"
        )

    async def _is_account_bound_in_channel(self, channel_id, include_sender=False):
        """检查当前账号是否在当前用户的该频道配置中具备可监听权限。"""
        try:
            website_configs = await self.get_website_configs_by_channel_async(channel_id)
            if not website_configs:
                return False, None

            try:
                from database import db
            except ImportError:
                from .database import db

            for config in website_configs:
                listener_ids = await asyncio.get_event_loop().run_in_executor(
                    None, db.get_website_listeners, config['id'], self.user_id
                )
                if self.account_id in listener_ids:
                    return True, website_configs

                if include_sender:
                    sender_ids = await asyncio.get_event_loop().run_in_executor(
                        None, db.get_website_senders, config['id'], self.user_id
                    )
                    if self.account_id in sender_ids:
                        return True, website_configs

            return False, website_configs
        except Exception as e:
            logger.error(f"检查频道账号绑定权限失败: {e}")
            return False, None

    async def _notify_reaction_interaction_if_needed(self, message, reactor, emoji_text):
        """当他人对当前账号发出的消息添加表情时发送 Bark 通知。"""
        if not self.running or not self.user:
            return
        if not message or not reactor:
            return

        # 只通知“别人给当前账号消息加表情”
        if getattr(reactor, "id", None) == getattr(self.user, "id", None):
            return
        if getattr(reactor, "bot", False):
            return
        if getattr(message.author, "id", None) != getattr(self.user, "id", None):
            return

        user_settings = await self._get_user_settings_safe()
        bark_enabled = user_settings.get("bark_enabled", 0) in (1, True, "1", "true", "True")
        bark_device_key = (user_settings.get("bark_device_key") or "").strip()
        if not bark_enabled or not bark_device_key:
            return

        bark_server_url = (user_settings.get("bark_server_url") or "https://api.day.app").strip()
        account_name = getattr(self.user, "name", None) or f"账号#{self.account_id}"
        reactor_name = (
            getattr(reactor, "display_name", None)
            or getattr(reactor, "name", None)
            or "未知用户"
        )
        guild_name = message.guild.name if message.guild else "私信"
        channel_name = getattr(message.channel, "name", str(getattr(message.channel, "id", "")))
        emoji_text = (emoji_text or "").strip() or "👍"

        preview_source = getattr(message, "clean_content", None) or message.content or ""
        content_preview = preview_source.replace("\n", " ").strip() or "[无文本内容]"
        if len(content_preview) > 120:
            content_preview = f"{content_preview[:120]}..."

        now_text = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        title = f"{reactor_name} {emoji_text}"
        if len(title) > 60:
            title = f"{title[:60]}..."

        body = (
            f"账号: {account_name}\n"
            f"类型: 被表情互动\n"
            f"发送者: {reactor_name}\n"
            f"位置: {guild_name} / #{channel_name}\n"
            f"表情: {emoji_text}\n"
            f"内容: {content_preview}\n"
            f"时间: {now_text}"
        )

        await self._send_bark_notification(
            bark_server_url=bark_server_url,
            bark_device_key=bark_device_key,
            title=title,
            body=body,
            jump_url=getattr(message, "jump_url", None),
        )

        logger.info(
            f"📱 Bark互动通知已发送: 账号:{account_name} | 类型:被表情互动 | 发送者:{reactor_name} | 频道:{channel_name} | 表情:{emoji_text}"
        )

    async def _notify_dm_interaction_if_needed(self, message):
        """当他人发起私信（DM）时发送 Bark 通知。"""
        if not self.running or not self.user:
            return
        if not message or getattr(message, "guild", None) is not None:
            return
        if getattr(message.author, "id", None) == getattr(self.user, "id", None):
            return
        if getattr(message.author, "bot", False):
            return
        channel_id = getattr(message.channel, "id", None)
        if self._is_dm_alert_recent(channel_id):
            return

        user_settings = await self._get_user_settings_safe()
        bark_enabled = user_settings.get("bark_enabled", 0) in (1, True, "1", "true", "True")
        bark_device_key = (user_settings.get("bark_device_key") or "").strip()
        if not bark_enabled or not bark_device_key:
            return

        bark_server_url = (user_settings.get("bark_server_url") or "https://api.day.app").strip()
        account_name = getattr(self.user, "name", None) or f"账号#{self.account_id}"
        sender_name = (
            getattr(message.author, "display_name", None)
            or getattr(message.author, "name", None)
            or "未知用户"
        )

        content_preview = (getattr(message, "clean_content", None) or message.content or "").replace("\n", " ").strip()
        if not content_preview:
            content_preview = "[无文本内容]"
        if len(content_preview) > 120:
            content_preview = f"{content_preview[:120]}..."

        message_time = getattr(message, "created_at", None)
        if isinstance(message_time, datetime):
            try:
                message_time = message_time.astimezone()
            except Exception:
                pass
            time_text = message_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            time_text = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

        title = content_preview if content_preview != "[无文本内容]" else f"{sender_name} 发起私信"
        if len(title) > 60:
            title = f"{title[:60]}..."

        body = (
            f"账号: {account_name}\n"
            f"类型: 发起私信\n"
            f"发送者: {sender_name}\n"
            f"位置: 私信\n"
            f"内容: {content_preview}\n"
            f"时间: {time_text}"
        )

        await self._send_bark_notification(
            bark_server_url=bark_server_url,
            bark_device_key=bark_device_key,
            title=title,
            body=body,
            jump_url=getattr(message, "jump_url", None),
        )
        self._mark_dm_alert(channel_id)

        logger.info(
            f"📱 Bark通知已发送: 账号:{account_name} | 类型:发起私信 | 发送者:{sender_name}"
        )

    async def _notify_relationship_interaction_if_needed(self, user_obj, interaction_label, detail_text):
        """当发生好友相关互动（好友请求/添加好友）时发送 Bark 通知。"""
        if not self.running or not self.user:
            return
        if user_obj is None:
            return
        if getattr(user_obj, "id", None) == getattr(self.user, "id", None):
            return

        user_settings = await self._get_user_settings_safe()
        bark_enabled = user_settings.get("bark_enabled", 0) in (1, True, "1", "true", "True")
        bark_device_key = (user_settings.get("bark_device_key") or "").strip()
        if not bark_enabled or not bark_device_key:
            return

        bark_server_url = (user_settings.get("bark_server_url") or "https://api.day.app").strip()
        account_name = getattr(self.user, "name", None) or f"账号#{self.account_id}"
        sender_name = (
            getattr(user_obj, "display_name", None)
            or getattr(user_obj, "name", None)
            or "未知用户"
        )
        time_text = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

        title = f"{sender_name} {interaction_label}"
        if len(title) > 60:
            title = f"{title[:60]}..."

        body = (
            f"账号: {account_name}\n"
            f"类型: {interaction_label}\n"
            f"发送者: {sender_name}\n"
            f"位置: 好友系统\n"
            f"内容: {detail_text}\n"
            f"时间: {time_text}"
        )

        await self._send_bark_notification(
            bark_server_url=bark_server_url,
            bark_device_key=bark_device_key,
            title=title,
            body=body,
            jump_url=None,
        )

        logger.info(
            f"📱 Bark通知已发送: 账号:{account_name} | 类型:{interaction_label} | 发送者:{sender_name}"
        )

    @staticmethod
    def _coerce_list(value):
        if not value:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []

    async def _download_file_to_discord(
        self,
        session,
        url,
        *,
        filename=None,
        error_label='下载图片失败',
    ):
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        except Exception as e:
            logger.error(f"{error_label}: {e}")
            return None

        safe_filename = filename or (url.split('/')[-1] or 'image.jpg')
        return discord.File(io.BytesIO(data), safe_filename)

    async def _build_product_image_file(
        self,
        session,
        product_id,
        image_index,
        image_path_map=None,
    ):
        if product_id is None or image_index is None:
            return None

        idx_key = image_index
        try:
            idx_key = int(image_index)
        except (TypeError, ValueError):
            idx_key = image_index

        if image_path_map is None:
            image_path_map = {}
            try:
                try:
                    from database import db
                except ImportError:
                    from .database import db
                product_images = db.get_product_images(product_id)
                image_path_map = {
                    img.get('image_index'): img.get('image_path')
                    for img in product_images
                }
            except Exception as e:
                logger.error(f"获取商品图片路径失败: {e}")

        image_path = image_path_map.get(idx_key)
        if image_path and os.path.exists(image_path):
            return discord.File(image_path, f"{product_id}_{idx_key}.jpg")

        img_url = f"{config.BACKEND_API_URL}/api/image/{product_id}/{idx_key}"
        return await self._download_file_to_discord(
            session,
            img_url,
            filename=f"{product_id}_{idx_key}.jpg",
            error_label='下载商品图片失败',
        )

    async def _collect_best_match_reply_files(self, session, product, match_context):
        if not isinstance(match_context, dict) or match_context.get('type') != 'image':
            return []

        product_id = product.get('id') if isinstance(product, dict) else None
        matched_index = match_context.get('best_match_image_index')
        if product_id is None or matched_index is None:
            return []

        best_file = await self._build_product_image_file(session, product_id, matched_index)
        return [best_file] if best_file is not None else []

    async def _collect_custom_reply_files(
        self,
        session,
        product,
        custom_reply,
        website_config,
        channel_id,
    ):
        files = []
        skip_images = bool(custom_reply and custom_reply.get('skip_images'))
        reply_type = custom_reply.get('reply_type') if isinstance(custom_reply, dict) else None
        is_custom_mode = bool(custom_reply) and reply_type in {
            'custom_only',
            'text',
            'text_and_link',
            'image',
        }
        is_product_custom_mode = bool(
            isinstance(custom_reply, dict) and custom_reply.get('product_data') is not None
        )

        if is_custom_mode and not _should_send_product_custom_images(
            custom_reply,
            product,
            channel_id,
            website_config=website_config,
        ):
            skip_images = True

        if not is_custom_mode or skip_images:
            return files

        if not is_product_custom_mode:
            image_url = str(custom_reply.get('image_url') or '').strip()
            if not image_url:
                return files
            downloaded = await self._download_file_to_discord(
                session,
                image_url,
                error_label='下载全局自定义回复图片失败',
            )
            return [downloaded] if downloaded is not None else []

        image_source = product.get('imageSource') or product.get('image_source') or 'product'
        product_id = product.get('id')

        if image_source == 'custom':
            for url in self._coerce_list(product.get('customImageUrls') or product.get('custom_image_urls'))[:10]:
                downloaded = await self._download_file_to_discord(
                    session,
                    url,
                    error_label='下载自定义图片失败',
                )
                if downloaded is not None:
                    files.append(downloaded)
            return files

        if image_source == 'upload':
            for filename in self._coerce_list(product.get('uploaded_reply_images'))[:10]:
                img_url = f"{config.BACKEND_API_URL}/api/custom_reply_image/{product_id}/{filename}"
                downloaded = await self._download_file_to_discord(
                    session,
                    img_url,
                    filename=filename,
                    error_label='下载上传的自定义回复图片失败',
                )
                if downloaded is not None:
                    files.append(downloaded)
            return files

        indexes = self._coerce_list(product.get('selectedImageIndexes') or product.get('custom_reply_images'))
        if not product_id or not indexes:
            return files

        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            product_images = db.get_product_images(product_id)
            image_path_map = {
                img.get('image_index'): img.get('image_path')
                for img in product_images
            }
        except Exception as e:
            logger.error(f"获取商品图片路径失败: {e}")
            image_path_map = {}

        for index in indexes[:10]:
            downloaded = await self._build_product_image_file(
                session,
                product_id,
                index,
                image_path_map=image_path_map,
            )
            if downloaded is not None:
                files.append(downloaded)

        return files

    async def _collect_reply_files(
        self,
        *,
        product,
        custom_reply,
        website_config,
        channel_id,
        match_context,
        user_settings,
    ):
        image_download_timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=image_download_timeout) as session:
            if _product_prefers_custom_reply_images(product):
                custom_files = await self._collect_custom_reply_files(
                    session,
                    product,
                    custom_reply,
                    website_config,
                    channel_id,
                )
                if custom_files:
                    return custom_files

            if (
                isinstance(match_context, dict)
                and match_context.get('type') == 'image'
            ):
                if not _is_image_match_above_reply_threshold(match_context, website_config):
                    return []

                if not bool(user_settings.get('keyword_reply_send_best_match_image')):
                    return []

                if not _should_send_best_match_reply_image(match_context, website_config):
                    return []

                best_match_files = await self._collect_best_match_reply_files(
                    session,
                    product,
                    match_context,
                )
                if best_match_files:
                    return best_match_files

            return await self._collect_custom_reply_files(
                session,
                product,
                custom_reply,
                website_config,
                channel_id,
            )

    def _resolve_image_skip_threshold(self, website_configs, base_threshold):
        thresholds = []
        for website_config in website_configs or []:
            website_threshold = _coerce_float(website_config.get('image_similarity_threshold'))
            thresholds.append(website_threshold if website_threshold is not None else base_threshold)
        thresholds = [value for value in thresholds if value is not None]
        return min(thresholds) if thresholds else base_threshold

    def _store_skipped_query_image(self, image_bytes, filename):
        ext = os.path.splitext(filename or '')[1].lower()
        if not ext:
            ext = '.jpg'
        target_dir = getattr(
            config,
            'SEARCH_QUERY_IMAGE_DIR',
            os.path.join(config.DATA_DIR, 'search_query_images'),
        )
        os.makedirs(target_dir, exist_ok=True)
        basename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{random.randint(1000, 9999)}{ext}"
        target_path = os.path.join(target_dir, basename)
        with open(target_path, 'wb') as f:
            f.write(image_bytes)
        return target_path

    async def _record_image_search_history(
        self,
        *,
        image_data,
        attachment,
        message,
        similarity,
        threshold,
        best_match=None,
        is_skipped=False,
        add_skipped_image_history=False,
    ):
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            query_image_path = await asyncio.to_thread(
                self._store_skipped_query_image,
                image_data,
                getattr(attachment, 'filename', 'query.jpg'),
            )
            matched_product = best_match.get('product') if isinstance(best_match, dict) else None
            matched_product_id = matched_product.get('id') if isinstance(matched_product, dict) else None
            matched_image_index = None
            if isinstance(best_match, dict):
                matched_image_index = best_match.get('imageIndex', best_match.get('image_index'))

            if add_skipped_image_history:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    db.add_skipped_image_history,
                    query_image_path,
                    float(similarity),
                    float(threshold),
                    str(getattr(message, 'id', '') or ''),
                    str(getattr(getattr(message, 'channel', None), 'id', '') or ''),
                    str(getattr(getattr(message, 'channel', None), 'name', '') or ''),
                    str(getattr(getattr(message, 'author', None), 'id', '') or ''),
                    self._get_message_author_name(message),
                    str(getattr(message, 'content', '') or ''),
                    matched_product_id,
                    matched_image_index,
                )
            await asyncio.to_thread(
                db.add_search_history,
                query_image_path=query_image_path,
                matched_product_id=matched_product_id,
                matched_image_index=matched_image_index,
                similarity=float(similarity),
                threshold=float(threshold),
                is_skipped=bool(is_skipped),
                discord_message_id=str(getattr(message, 'id', '') or ''),
                discord_channel_id=str(getattr(getattr(message, 'channel', None), 'id', '') or ''),
                discord_channel_name=str(getattr(getattr(message, 'channel', None), 'name', '') or ''),
                discord_author_id=str(getattr(getattr(message, 'author', None), 'id', '') or ''),
                discord_author_name=self._get_message_author_name(message),
                message_content=str(getattr(message, 'content', '') or ''),
            )
        except Exception as e:
            logger.error(f"记录图片搜索历史失败: {e}")

    async def _record_skipped_image_history(
        self,
        *,
        image_data,
        attachment,
        message,
        similarity,
        threshold,
        best_match=None,
    ):
        await self._record_image_search_history(
            image_data=image_data,
            attachment=attachment,
            message=message,
            similarity=similarity,
            threshold=threshold,
            best_match=best_match,
            is_skipped=True,
            add_skipped_image_history=True,
        )

    async def schedule_reply(
        self,
        message,
        product,
        custom_reply=None,
        match_context=None,
        website_configs_override=None,
        skip_filters=False,
        skip_repeat_checks=False,
        skip_review_check=False,
        force_plain_send=False,
        force_reference_reply=False,
        disable_thread_creation=False,
        sender_ids_override=None,
        saved_reply_target_payload=None,
        strict_saved_reply_target=False,
    ):
        """调度回复到合适的发送账号 (增强版：带详细状态诊断)"""

        sent_any = False
        try:
            # 清理过期的冷却状态
            cleanup_expired_cooldowns()

            try:
                from database import db
            except ImportError:
                from .database import db

            sender_ids_override = _normalize_sender_id_override(sender_ids_override)
            saved_reply_target_payload = _normalize_saved_review_reply_target_payload(
                saved_reply_target_payload
            )
            strict_saved_reply_target = bool(
                strict_saved_reply_target and saved_reply_target_payload.get('used_thread_reply')
            )

            # 获取用户设置以确定全局延迟时间
            user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
            global_min_delay = user_settings.get('global_reply_min_delay', 1.0)
            global_max_delay = user_settings.get('global_reply_max_delay', 3.0)

            website_configs = (
                website_configs_override
                if website_configs_override is not None
                else await self.get_website_configs_by_channel_async(message.channel)
            )
            if not website_configs:
                logger.info(f"频道 {message.channel.id} 未绑定网站配置，跳过回复")
                return False

            website_configs = await self._exclude_blocked_website_configs(message, website_configs)
            if not website_configs:
                logger.info(
                    "作者 %s(%s) 当前网站均已拉黑，跳过回复",
                    self._get_message_author_name(message),
                    getattr(getattr(message, 'author', None), 'id', None),
                )
                return False

            prevalidated_batch = bool(
                isinstance(custom_reply, dict) and custom_reply.get('batched_reply')
            )
            author_id = getattr(message.author, 'id', None)
            repeat_product_ids = self._get_repeat_product_ids(product, custom_reply)
            batch_repeat_records = []
            if prevalidated_batch:
                raw_repeat_records = custom_reply.get('repeat_records') or []
                batch_repeat_records = list(
                    dict.fromkeys(
                        (
                            str(item[0]),
                            str(item[1]),
                        )
                        for item in raw_repeat_records
                        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] and item[1]
                    )
                )
            global_repeat_window = _get_repeat_filter_seconds()
            user_website_settings_map = {}
            user_website_filters_map = {}
            channel_repeat_window = global_repeat_window

            if self.user_id:
                for website_config in website_configs:
                    website_id = website_config.get('id')
                    if not website_id:
                        continue
                    settings = await asyncio.get_event_loop().run_in_executor(
                        None, db.get_user_website_settings, self.user_id, website_id
                    )
                    if not settings:
                        continue
                    user_website_settings_map[website_id] = settings
                    website_filters = self._parse_message_filters(settings.get('message_filters', '[]'))
                    user_website_filters_map[website_id] = website_filters
                    website_repeat_window = _get_repeat_seconds_from_filters(website_filters)
                    if website_repeat_window > channel_repeat_window:
                        channel_repeat_window = website_repeat_window

            if (
                not skip_repeat_checks
                and not prevalidated_batch
                and channel_repeat_window
                and author_id
                and repeat_product_ids
            ):
                for pid in repeat_product_ids:
                    if await _is_recent_repeat(author_id, pid, message.channel.id, channel_repeat_window):
                        logger.info(
                            f"🚫 用户重复发送过滤: user={author_id} 商品={pid} 频道={message.channel.id} "
                            f"窗口={int(channel_repeat_window)}秒"
                        )
                        return False

            global_image_filters = []
            if not skip_filters and not prevalidated_batch and match_context and match_context.get('type') == 'image':
                try:
                    global_filters = await asyncio.get_event_loop().run_in_executor(None, db.get_message_filters)
                    global_image_filters = [
                        f
                        for f in (global_filters or [])
                        if f.get('filter_type') in {'image_similarity', 'ocr_contains'}
                    ]
                except Exception as e:
                    logger.error(f"获取全局过滤规则失败: {e}")

            # === 获取当前真正在线的机器人账号 ID ===
            online_client_ids = [c.account_id for c in bot_clients if c.is_ready() and not c.is_closed()]

            for website_config in website_configs:
                if global_image_filters and self._filters_block_message(
                    message,
                    global_image_filters,
                    match_context=match_context,
                ):
                    logger.debug("消息被过滤(全局图片相似度)")
                    return False
                if not skip_filters and not prevalidated_batch and match_context and match_context.get('type') == 'image':
                    website_filter_matches = match_context.get('website_filter_matches') or []
                    matched_filter = next(
                        (m for m in website_filter_matches if str(m.get('website_id')) == str(website_config.get('id'))),
                        None
                    )
                    if matched_filter:
                        try:
                            sim = float(matched_filter.get('similarity', 0))
                            threshold_val = float(matched_filter.get('threshold', 0))
                            if sim >= threshold_val:
                                logger.debug(
                                    f"🚫 网站图片过滤命中: 网站 {website_config.get('name')} "
                                    f"规则 {matched_filter.get('filter_id')} 相似度 {sim:.3f} >= {threshold_val:.3f}"
                                )
                                continue
                        except Exception:
                            continue
                if not skip_filters and not prevalidated_batch and match_context and match_context.get('type') == 'image':
                    block_reason = _get_image_match_reply_block_reason(match_context, website_config)
                    if block_reason:
                        logger.info(block_reason)
                        continue

                active_product, website_product_custom_reply, _, _ = _prepare_effective_product_reply(
                    product,
                    website_config=website_config,
                )

                active_custom_reply = custom_reply
                if isinstance(custom_reply, dict):
                    per_website_content = custom_reply.get('per_website_content')
                    if isinstance(per_website_content, dict):
                        scoped_content = per_website_content.get(str(website_config.get('id')))
                        if scoped_content:
                            active_custom_reply = dict(custom_reply)
                            active_custom_reply['content'] = scoped_content
                    if active_custom_reply.get('product_data') is not None:
                        active_custom_reply = dict(active_custom_reply)
                        active_custom_reply['product_data'] = active_product

                forced_custom_payload = bool(
                    isinstance(active_custom_reply, dict)
                    and (
                        active_custom_reply.get('explicit_mentions')
                        or active_custom_reply.get('batched_reply')
                        or active_custom_reply.get('prebuilt_content')
                        or active_custom_reply.get('final_direct_content')
                    )
                )
                if website_product_custom_reply and not forced_custom_payload:
                    active_custom_reply = website_product_custom_reply
                elif (
                    not website_product_custom_reply
                    and isinstance(active_custom_reply, dict)
                    and active_custom_reply.get('product_data') is not None
                    and not forced_custom_payload
                ):
                    active_custom_reply = None

                response_content = self._generate_reply_content(
                    active_product,
                    message.channel.id,
                    active_custom_reply,
                    website_config=website_config
                )
                if response_content is None:
                    logger.debug(f"商品 {active_product.get('id')} 回复范围不匹配，跳过发送")
                    continue

                # 2. 获取数据库配置的发送者 ID
                db_sender_ids = await asyncio.get_event_loop().run_in_executor(
                    None, db.get_website_senders, website_config['id'], self.user_id
                )

                if not db_sender_ids and not sender_ids_override:
                    logger.warning(
                        f"❌ [配置错误] 网站配置 '{website_config.get('name')}' 未绑定任何【发送】账号。请在网站配置中绑定账号。"
                    )
                    continue

                logger.info(f"配置账号ID: {db_sender_ids} | 在线账号ID: {online_client_ids}")

                valid_senders = [uid for uid in db_sender_ids if uid in online_client_ids]
                override_sender_ids = [uid for uid in sender_ids_override if uid in online_client_ids]

                if sender_ids_override and not override_sender_ids:
                    logger.warning(
                        f"❌ [审核发送失败] 审核记录指定的发送账号当前均不在线: {sender_ids_override}"
                    )
                    continue

                valid_senders_before_access = list(valid_senders)
                valid_senders = await _filter_channel_accessible_sender_ids(
                    valid_senders,
                    bot_clients,
                    message,
                )
                if valid_senders_before_access and not valid_senders:
                    logger.warning(
                        f"❌ [频道权限错误] 网站 '{website_config.get('name')}' 的在线发送账号均无法访问频道 "
                        f"{message.channel.id}，跳过当前网站配置。在线发送账号: {valid_senders_before_access}"
                    )
                    continue
                if len(valid_senders) < len(valid_senders_before_access):
                    blocked_senders = [
                        uid for uid in valid_senders_before_access if uid not in set(valid_senders)
                    ]
                    logger.info(
                        f"⏭️ [跳过无频道权限发送账号] 网站:{website_config.get('name')} "
                        f"频道:{message.channel.id} 账号:{blocked_senders}"
                    )

                override_senders_before_access = list(override_sender_ids)
                override_sender_ids = await _filter_channel_accessible_sender_ids(
                    override_sender_ids,
                    bot_clients,
                    message,
                )
                if override_senders_before_access and not override_sender_ids:
                    logger.warning(
                        f"❌ [审核发送失败] 审核记录指定的发送账号无法访问频道 {message.channel.id}: "
                        f"{override_senders_before_access}"
                    )
                    continue

                if not valid_senders and not override_sender_ids:
                    logger.warning("❌ [状态错误] 配置的发送账号均不在线。请检查 Discord 账号连接状态。")
                    continue

                skip_sender_cooldown = bool(
                    isinstance(active_custom_reply, dict)
                    and active_custom_reply.get('skip_sender_cooldown')
                )
                if override_sender_ids:
                    skip_sender_cooldown = True

                # 3. 冷却逻辑：始终生效，轮换开关仅控制选人策略
                website_id = website_config.get('id')
                user_website_settings = user_website_settings_map.get(website_id)
                website_filters = user_website_filters_map.get(website_id, [])
                effective_settings = _resolve_runtime_rotation_settings(
                    website_config,
                    user_settings=user_website_settings,
                    sender_count=len(db_sender_ids),
                )
                reply_mode = str(effective_settings.get('reply_mode', 'rotation')).strip().lower()
                rotation_enabled = _coerce_bool(effective_settings.get('rotation_enabled', 0), False)
                thread_reply_enabled = _coerce_bool(
                    (user_website_settings or {}).get('thread_reply_enabled', 0),
                    False,
                )
                rotation_interval = _coerce_int(
                    effective_settings.get('rotation_interval', website_config.get('rotation_interval', 180)),
                    _coerce_int(website_config.get('rotation_interval', 180), 180),
                )

                if user_website_settings:
                    logger.info(
                        f"📋 使用用户级别设置: rotation_interval={rotation_interval}秒, "
                        f"rotation_enabled={rotation_enabled}, reply_mode={reply_mode}, "
                        f"thread_reply_enabled={1 if thread_reply_enabled else 0}"
                    )
                    if (
                        not skip_filters
                        and not prevalidated_batch
                        and website_filters
                        and self._filters_block_message(message, website_filters, match_context=match_context)
                    ):
                        logger.debug(f"消息被过滤(网站规则): {website_config.get('name')}")
                        continue

                if reply_mode == 'default':
                    skip_sender_cooldown = True

                website_min_delay = _coerce_float(user_website_settings.get('reply_min_delay')) if user_website_settings else None
                website_max_delay = _coerce_float(user_website_settings.get('reply_max_delay')) if user_website_settings else None
                if website_min_delay is not None and website_max_delay is not None:
                    min_delay, max_delay = normalize_reply_delay_range(website_min_delay, website_max_delay)
                else:
                    min_delay = global_min_delay
                    max_delay = global_max_delay

                cooldown_channel_id = _resolve_cooldown_channel_id(message.channel)

                if override_sender_ids:
                    selected_sender_ids = list(override_sender_ids)
                else:
                    dispatch_plan = build_sender_dispatch_plan(
                        db_sender_ids=db_sender_ids,
                        valid_senders=valid_senders,
                        channel_id=cooldown_channel_id,
                        rotation_interval=rotation_interval,
                        rotation_enabled=rotation_enabled,
                        skip_sender_cooldown=skip_sender_cooldown,
                        reply_mode=reply_mode,
                    )
                    selected_sender_ids = list(dispatch_plan.get('selected_ids') or [])

                    if not selected_sender_ids and not skip_sender_cooldown:
                        wait_seconds = float(dispatch_plan.get('wait_seconds') or 0.0)
                        if wait_seconds > 0:
                            if wait_seconds > MAX_COOLDOWN_WAIT_SECONDS:
                                logger.info(
                                    f"⏭️ [跳过长等待] 频道 {message.channel.id} 冷却等待 {wait_seconds:.1f} 秒，"
                                    f"超过阈值 {MAX_COOLDOWN_WAIT_SECONDS:.1f} 秒，跳过本次发送"
                                )
                                continue
                            logger.info(
                                f"⏳ [排队等待] 频道 {message.channel.id} 暂无可用发送账号，"
                                f"等待 {wait_seconds:.1f} 秒后重试"
                            )
                            await asyncio.sleep(wait_seconds + 0.05)
                            dispatch_plan = build_sender_dispatch_plan(
                                db_sender_ids=db_sender_ids,
                                valid_senders=valid_senders,
                                channel_id=cooldown_channel_id,
                                rotation_interval=rotation_interval,
                                rotation_enabled=rotation_enabled,
                                skip_sender_cooldown=skip_sender_cooldown,
                                reply_mode=reply_mode,
                            )
                            selected_sender_ids = list(dispatch_plan.get('selected_ids') or [])

                    if not selected_sender_ids:
                        logger.warning(
                            f"⏳ [重试后仍冷却] 频道 {message.channel.id} 在线账号 ({len(valid_senders)}个) "
                            f"均不可用，跳过当前网站配置"
                        )
                        continue

                target_clients = [
                    c for c in bot_clients
                    if c.account_id in set(selected_sender_ids)
                ]
                target_clients.sort(
                    key=lambda client: selected_sender_ids.index(client.account_id)
                )

                if not target_clients:
                    logger.warning("❌ 逻辑异常：有可用发送账号但无法找到客户端")
                    continue

                if reply_mode == 'all':
                    selected_labels = ', '.join(
                        f"{getattr(client.user, 'name', client.account_id)}({client.account_id})"
                        for client in target_clients
                    )
                    logger.info(f"✅ 本次选中全部发送账号: {selected_labels}")
                else:
                    target_client = target_clients[0]
                    logger.info(
                        f"✅ 本次选中发送账号: {target_client.user.name if target_client else selected_sender_ids[0]} "
                        f"(ID: {selected_sender_ids[0]})"
                    )

                broadcast_mode = reply_mode == 'all'
                successful_sender_ids = []

                for target_index, target_client in enumerate(target_clients):
                    try:
                        used_thread_reply = False
                        saved_reply_target_requested = bool(
                            saved_reply_target_payload.get('used_thread_reply')
                        )
                        saved_reply_target_id = _coerce_int(
                            saved_reply_target_payload.get('channel_id'),
                            None,
                        )
                        target_channel = None
                        reply_target_channel = None

                        if saved_reply_target_requested and saved_reply_target_id is not None:
                            # 审核通过后的补发必须优先命中入队时保存的子区目标。
                            reply_target_channel = await _resolve_client_channel(
                                target_client,
                                saved_reply_target_id,
                            )
                            if reply_target_channel is not None:
                                target_channel = reply_target_channel
                                used_thread_reply = True

                        if target_channel is None:
                            target_channel = await _resolve_message_reply_channel(target_client, message)

                        if target_channel:
                            if not used_thread_reply:
                                reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
                                    target_client=target_client,
                                    target_channel=target_channel,
                                    message=message,
                                    thread_reply_enabled=thread_reply_enabled or saved_reply_target_requested,
                                )

                            if reply_target_channel is None:
                                logger.warning(
                                    "子区回复目标为空，当前回复将跳过，避免发到外面: "
                                    f"message={getattr(message, 'id', None)} "
                                    f"channel={getattr(target_channel, 'id', None)} "
                                    f"account_id={getattr(target_client, 'account_id', None)}"
                                )
                                continue

                            if strict_saved_reply_target:
                                resolved_reply_target_id = _coerce_int(
                                    getattr(reply_target_channel, 'id', None),
                                    None,
                                )
                                if (
                                    not used_thread_reply
                                    or saved_reply_target_id is None
                                    or resolved_reply_target_id != saved_reply_target_id
                                ):
                                    logger.warning(
                                        "审批后发送必须命中已保存子区，拒绝回退到原频道: "
                                        f"message={getattr(message, 'id', None)} "
                                        f"saved_target={saved_reply_target_id} "
                                        f"resolved_target={resolved_reply_target_id} "
                                        f"account_id={getattr(target_client, 'account_id', None)}"
                                    )
                                    continue

                            if (
                                thread_reply_enabled
                                and _message_has_existing_thread_hint(message)
                                and not used_thread_reply
                            ):
                                logger.warning(
                                    "源消息声明存在子区，但当前发送账号无法进入，拒绝回退到原频道: "
                                    f"message={getattr(message, 'id', None)} "
                                    f"channel={getattr(target_channel, 'id', None)} "
                                    f"account_id={getattr(target_client, 'account_id', None)}"
                                )
                                continue

                            if thread_reply_enabled and not used_thread_reply:
                                logger.warning(
                                    f"子区回复失败，当前回复将跳过，避免发到外面: "
                                    f"message={getattr(message, 'id', None)} "
                                    f"channel={getattr(target_channel, 'id', None)}"
                                )
                                continue

                            if (
                                website_config
                                and _coerce_bool(website_config.get('keyword_review_enabled', 0), False)
                                and not skip_review_check
                            ):
                                queued_review_id = await asyncio.to_thread(
                                    self._queue_keyword_review_item,
                                    message=message,
                                    product=active_product,
                                    custom_reply=active_custom_reply,
                                    website_config=website_config,
                                    reply_content=response_content,
                                    target_clients=[target_client],
                                    selected_sender_ids=selected_sender_ids,
                                    reply_mode=reply_mode,
                                    files=None,
                                    match_context=match_context,
                                    prevalidated_batch=prevalidated_batch,
                                    broadcast_mode=broadcast_mode,
                                    thread_reply_enabled=thread_reply_enabled,
                                    reply_target_channel=reply_target_channel,
                                    used_thread_reply=used_thread_reply,
                                    cooldown_channel_id=cooldown_channel_id,
                                    batch_repeat_records=batch_repeat_records,
                                    repeat_product_ids=repeat_product_ids,
                                )
                                if queued_review_id:
                                    self._start_keyword_reply_background_task(
                                        self._send_keyword_review_item_bark_notification(
                                            queued_review_id,
                                        ),
                                        task_name=f"review-bark-item user={self.user_id} item={queued_review_id}",
                                    )
                                    logger.info(
                                        f"📝 [进入人工审核] 网站:{website_config.get('name')} "
                                        f"频道:{message.channel.id} 队列ID:{queued_review_id}"
                                    )
                                    sent_any = True
                                    continue

                            should_apply_delay = not (broadcast_mode and target_index > 0)
                            if should_apply_delay:
                                await _wait_before_discord_reply(
                                    reply_target_channel,
                                    min_delay,
                                    max_delay,
                                )

                            # 【关键修复】
                            # 不要使用 message.reply()，因为 message 绑定的是监听者(Listener)客户端
                            # 必须用 target_channel.send(..., reference=message) 才会使用 target_client(Sender) 的 token
                            try:
                                # === 1. 收集所有要发送的图片文件 ===
                                files = await self._collect_reply_files(
                                    product=active_product,
                                    custom_reply=active_custom_reply,
                                    website_config=website_config,
                                    channel_id=message.channel.id,
                                    match_context=match_context,
                                    user_settings=user_settings,
                                )
    
                                # === 2. 发送文字和所有图片（合并为一条消息） ===
                                if not response_content and not files:
                                    logger.warning(
                                        f"⚠️ 无可发送内容: 商品ID={active_product.get('id')}，未生成文字且无图片"
                                    )
                                    continue
    
                                explicit_mentions = bool(active_custom_reply and active_custom_reply.get('explicit_mentions'))
                                send_plain_message = False
                                if not force_reference_reply:
                                    send_plain_message = force_plain_send or _should_send_plain_keyword_message(
                                        prevalidated_batch=prevalidated_batch,
                                        explicit_mentions=explicit_mentions,
                                        reply_mode=reply_mode,
                                    )
                                if (
                                    send_plain_message
                                    and response_content
                                    and not prevalidated_batch
                                    and author_id
                                ):
                                    direct_payload = _build_keyword_direct_send_payload(
                                        author_id,
                                        response_content,
                                    )
                                    response_content = direct_payload['content']

                                send_kwargs = {
                                    'content': response_content if response_content else None,
                                    'files': files if files else None,
                                }
                                if send_plain_message:
                                    send_kwargs['allowed_mentions'] = discord.AllowedMentions(
                                        users=True,
                                        roles=False,
                                        everyone=False,
                                        replied_user=False,
                                    )
                                else:
                                    if not used_thread_reply:
                                        message_reference = _build_message_reference(message, reply_target_channel)
                                        if message_reference is not None:
                                            send_kwargs['reference'] = message_reference
                                        send_kwargs['mention_author'] = _should_mention_reply_author(
                                            explicit_mentions=explicit_mentions,
                                            reply_mode=reply_mode,
                                        )
                                    if explicit_mentions:
                                        send_kwargs['allowed_mentions'] = discord.AllowedMentions(
                                            users=True,
                                            roles=False,
                                            everyone=False,
                                            replied_user=False,
                                        )

                                await _send_discord_message(reply_target_channel, **send_kwargs)
                                sent_any = True
    
                                if prevalidated_batch:
                                    for repeat_user_id, repeat_pid in batch_repeat_records:
                                        await _record_repeat(repeat_user_id, repeat_pid, message.channel.id)
                                elif author_id and repeat_product_ids:
                                    for pid in repeat_product_ids:
                                        await _record_repeat(author_id, pid, message.channel.id)
    
                                if hasattr(target_client, 'account_id') and target_client.account_id:
                                    successful_sender_ids.append(target_client.account_id)
                                if (
                                    not skip_sender_cooldown
                                    and not broadcast_mode
                                    and hasattr(target_client, 'account_id')
                                    and target_client.account_id
                                ):
                                    apply_reply_mode_cooldown(
                                        reply_mode,
                                        [target_client.account_id],
                                        cooldown_channel_id,
                                    )
    
                                reply_preview = (response_content or '').replace('\n', ' ').strip()
                                if not reply_preview and files:
                                    reply_preview = f"[图片 {len(files)}]"
                                if len(reply_preview) > 120:
                                    reply_preview = f"{reply_preview[:120]}..."
                                author_label = (
                                    f"批量{len(batch_repeat_records)}条"
                                    if prevalidated_batch
                                    else f"{message.author.name}({message.author.id})"
                                )
                                logger.info(
                                    f"✅ [回复成功] {target_client.user.name} -> {author_label} | 频道: "
                                    f"{getattr(reply_target_channel, 'name', message.channel.name)}: "
                                    f"{reply_preview} | 商品ID: {active_product.get('id')}"
                                )
                                try:
                                    has_text = bool(response_content)
                                    has_image = bool(files)
                                    if website_config and website_config.get('id') and (has_text or has_image):
                                        await asyncio.get_event_loop().run_in_executor(
                                            None,
                                            db.increment_website_stats,
                                            website_config['id'],
                                            has_text,
                                            has_image,
                                            self.user_id
                                        )
                                except Exception as stat_error:
                                    logger.error(f"统计更新失败: {stat_error}")

                            except Exception as reply_error:
                                if _is_discord_blocked_content_error(reply_error):
                                    logger.error(
                                        "回复被 Discord 内容策略拒绝，跳过直接发送重试，避免触发长时间限流等待: "
                                        f"{_summarize_exception_for_log(reply_error)}"
                                    )
                                    continue
                                if _is_discord_missing_access_error(reply_error):
                                    _store_sender_channel_inaccessible(
                                        target_client,
                                        getattr(reply_target_channel, 'id', None),
                                    )
                                    logger.warning(
                                        "回复频道权限不足，跳过直接发送重试: "
                                        f"account_id={getattr(target_client, 'account_id', None)} "
                                        f"channel={getattr(reply_target_channel, 'id', None)} "
                                        f"{_summarize_exception_for_log(reply_error)}"
                                    )
                                    continue

                                logger.warning(f"回复失败，尝试直接发送: {reply_error}")
                                fallback_sent = False
                                if response_content:
                                    try:
                                        fallback_kwargs = {}
                                        if send_plain_message:
                                            fallback_kwargs['allowed_mentions'] = discord.AllowedMentions(
                                                users=True,
                                                roles=False,
                                                everyone=False,
                                                replied_user=False,
                                            )
                                        elif active_custom_reply and active_custom_reply.get('explicit_mentions'):
                                            fallback_kwargs['allowed_mentions'] = discord.AllowedMentions(
                                                users=True,
                                                roles=False,
                                                everyone=False,
                                                replied_user=False,
                                            )
                                        await _send_discord_message(reply_target_channel, response_content, **fallback_kwargs)
                                        fallback_sent = True
                                    except Exception as fallback_error:
                                        logger.error(f"文本兜底发送失败: {fallback_error}")
                                        continue
                                elif files:
                                    logger.error(
                                        f"图片消息发送失败且无法复用附件重试，跳过本次发送。商品ID: {active_product.get('id')}"
                                    )
                                    continue
    
                                if not fallback_sent:
                                    continue
    
                                if prevalidated_batch:
                                    for repeat_user_id, repeat_pid in batch_repeat_records:
                                        await _record_repeat(repeat_user_id, repeat_pid, message.channel.id)
                                elif author_id and repeat_product_ids:
                                    for pid in repeat_product_ids:
                                        await _record_repeat(author_id, pid, message.channel.id)
    
                                if hasattr(target_client, 'account_id') and target_client.account_id:
                                    successful_sender_ids.append(target_client.account_id)
                                if (
                                    not skip_sender_cooldown
                                    and not broadcast_mode
                                    and hasattr(target_client, 'account_id')
                                    and target_client.account_id
                                ):
                                    apply_reply_mode_cooldown(
                                        reply_mode,
                                        [target_client.account_id],
                                        cooldown_channel_id,
                                    )
                                sent_any = True
    
                                reply_preview = (response_content or '').replace('\n', ' ').strip()
                                if len(reply_preview) > 120:
                                    reply_preview = f"{reply_preview[:120]}..."
                                author_label = (
                                    f"批量{len(batch_repeat_records)}条"
                                    if prevalidated_batch
                                    else f"{message.author.name}({message.author.id})"
                                )
                                logger.info(
                                    f"✅ [发送成功] {target_client.user.name} -> {author_label} | 频道: "
                                    f"{getattr(reply_target_channel, 'name', message.channel.name)}: "
                                    f"{reply_preview} | 商品ID: {active_product.get('id')}"
                                )
                                try:
                                    if website_config and website_config.get('id') and response_content:
                                        await asyncio.get_event_loop().run_in_executor(
                                            None,
                                            db.increment_website_stats,
                                            website_config['id'],
                                            True,
                                            False,
                                            self.user_id
                                        )
                                except Exception as stat_error:
                                    logger.error(f"统计更新失败: {stat_error}")
    
                        else:
                            logger.warning(
                                f"❌ 选中的账号 {target_client.user.name} 无法访问频道 {message.channel.id} (可能不在该服务器)"
                            )
                            continue
    
                    except Exception as e:
                        logger.error(f"❌ 发送异常: {e}")

                if broadcast_mode and not skip_sender_cooldown and successful_sender_ids:
                    apply_reply_mode_cooldown(
                        reply_mode,
                        selected_sender_ids or successful_sender_ids,
                        cooldown_channel_id,
                    )

        except Exception as e:
            logger.error(f"❌ 严重错误: {e}")
            return sent_any

        return sent_any

    def _generate_reply_content(
        self,
        product,
        channel_id,
        custom_reply=None,
        website_config=None,
        reply_languages=None,
    ):
        """生成回复内容（支持 {url}、范围与全局模板）"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            if not website_config:
                website_config = db.get_website_config_by_channel(str(channel_id), self.user_id)

            is_product_custom = bool(custom_reply and custom_reply.get('product_data'))
            force_custom_reply = bool(
                custom_reply and (
                    custom_reply.get('explicit_mentions')
                    or custom_reply.get('batched_reply')
                    or custom_reply.get('prebuilt_content')
                    or custom_reply.get('final_direct_content')
                )
            )
            force_link_only = False
            if is_product_custom and not force_custom_reply:
                if not _product_custom_scope_matches(product, channel_id, website_config=website_config):
                    force_link_only = True
                    logger.info(
                        f"商品 {product.get('id')} 回复范围未命中当前网站 "
                        f"({website_config.get('name') if website_config else channel_id})，回退为链接回复"
                    )

            response_url = get_response_url_for_channel(
                product,
                channel_id,
                self.user_id,
                website_config=website_config
            )
            active_reply_languages = get_effective_reply_languages(
                reply_languages if reply_languages is not None else (
                    website_config.get('reply_language') if website_config else None
                )
            )

            if force_link_only:
                return response_url

            def apply_template(template: str, append_link: bool, allow_language_default: bool = False) -> str:
                template_text = str(template or '').strip()
                if allow_language_default:
                    template_text = apply_reply_language_template_default(
                        template_text,
                        reply_languages=active_reply_languages,
                    )
                if not template_text:
                    return ''
                rendered = render_reply_template(
                    template_text,
                    response_url,
                    product,
                    reply_languages=active_reply_languages,
                )
                if '{url}' in template_text:
                    return rendered
                if append_link:
                    return f"{rendered}\n{response_url}".strip()
                return rendered

            # 1) 商品级自定义回复（优先级最高）
            if is_product_custom or force_custom_reply:
                reply_type = custom_reply.get('reply_type')
                content = custom_reply.get('content', '') or ''
                if reply_type == 'image':
                    return ''
                if reply_type == 'custom_only' or reply_type == 'text':
                    return apply_template(content, append_link=False)
                if reply_type == 'text_and_link':
                    return apply_template(content, append_link=True)

            # 2) 网站级回复模板（默认 {url}）
            if website_config:
                website_template = (website_config.get('reply_template') or '{url}').strip()
                if website_template:
                    return apply_template(
                        website_template,
                        append_link=True,
                        allow_language_default=True,
                    )

            # 3) 原有自定义回复（全局随机）
            if custom_reply and not is_product_custom:
                reply_type = custom_reply.get('reply_type')
                content = custom_reply.get('content', '') or ''

                if reply_type == 'image':
                    return ''
                if reply_type == 'custom_only' or reply_type == 'text':
                    return apply_template(content, append_link=False)
                if reply_type == 'text_and_link':
                    return apply_template(content, append_link=True)

            # 4) 默认行为：发送链接
            return response_url

        except Exception as e:
            logger.error(f"生成回复内容失败: {e}")
            return get_response_url_for_channel(product, channel_id, self.user_id, website_config=website_config)

    def get_website_configs_by_channel(self, channel_id):
        """根据频道ID获取对应的网站配置列表"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            lookup_ids = self._resolve_channel_lookup_ids(channel_id)
            if len(lookup_ids) <= 1:
                return db.get_website_configs_by_channel(lookup_ids, self.user_id)

            direct_configs = db.get_website_configs_by_channel(lookup_ids[0], self.user_id)
            parent_configs = db.get_website_configs_by_channel(lookup_ids[1], self.user_id)
            if direct_configs:
                return direct_configs
            if not parent_configs:
                return []

            settings_map = db.get_user_website_settings_map(
                self.user_id,
                [config.get('id') for config in parent_configs if config.get('id') is not None],
            )
            return filter_forum_channel_configs_for_message(
                channel_id,
                direct_configs=direct_configs,
                parent_configs=parent_configs,
                settings_map=settings_map,
            )
        except Exception as e:
            logger.error(f"获取频道网站配置失败: {e}")
            return []

    def get_website_config_by_channel(self, channel_id):
        """根据频道ID获取对应的网站配置（兼容单个返回）"""
        try:
            configs = self.get_website_configs_by_channel(channel_id)
            return configs[0] if configs else None
        except Exception as e:
            logger.error(f"获取频道网站配置失败: {e}")
            return None

    async def get_website_configs_by_channel_async(self, channel_id):
        """异步版本：根据频道ID获取对应的网站配置列表"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            lookup_ids = self._resolve_channel_lookup_ids(channel_id)
            if len(lookup_ids) <= 1:
                return await asyncio.get_event_loop().run_in_executor(
                    None, db.get_website_configs_by_channel, lookup_ids, self.user_id
                )

            direct_configs = await asyncio.get_event_loop().run_in_executor(
                None, db.get_website_configs_by_channel, lookup_ids[0], self.user_id
            )
            parent_configs = await asyncio.get_event_loop().run_in_executor(
                None, db.get_website_configs_by_channel, lookup_ids[1], self.user_id
            )
            if direct_configs:
                return direct_configs
            if not parent_configs:
                return []

            website_ids = [
                config.get('id')
                for config in parent_configs
                if config.get('id') is not None
            ]
            settings_map = await asyncio.get_event_loop().run_in_executor(
                None, db.get_user_website_settings_map, self.user_id, website_ids
            )
            return filter_forum_channel_configs_for_message(
                channel_id,
                direct_configs=direct_configs,
                parent_configs=parent_configs,
                settings_map=settings_map,
            )
        except Exception as e:
            logger.error(f"异步获取频道网站配置失败: {e}")
            return []

    async def get_website_config_by_channel_async(self, channel_id):
        """异步版本：根据频道ID获取对应的网站配置（兼容单个返回）"""
        configs = await self.get_website_configs_by_channel_async(channel_id)
        return configs[0] if configs else None

    def _message_has_image(self, message) -> bool:
        """判断消息是否包含图片附件"""
        try:
            attachments = getattr(message, 'attachments', None) or []
            for att in attachments:
                content_type = (getattr(att, 'content_type', '') or '').lower()
                if content_type.startswith('image/'):
                    return True
                filename = (getattr(att, 'filename', '') or '').lower()
                if filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.heic', '.heif')):
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def _message_preview(message, limit=120) -> str:
        content = ((getattr(message, 'content', None) or '') or '').replace('\n', ' ').strip()
        if content:
            return content[:limit] + ('...' if len(content) > limit else '')

        attachments = getattr(message, 'attachments', None) or []
        if attachments:
            labels = []
            for att in attachments[:3]:
                filename = (getattr(att, 'filename', None) or '').strip()
                content_type = (getattr(att, 'content_type', None) or '').strip()
                labels.append(filename or content_type or '[附件]')
            preview = ', '.join(labels)
            if len(attachments) > 3:
                preview = f'{preview} 等{len(attachments)}个附件'
            return f'[附件] {preview}'

        return '[空消息]'

    def _is_plain_text_keyword_trigger_candidate(self, message) -> bool:
        if getattr(message, 'guild', None) is None:
            return False
        if getattr(message, 'attachments', None):
            return False
        if getattr(message, 'reference', None) is not None:
            return False
        if getattr(message, 'mentions', None):
            return False

        content = (getattr(message, 'content', None) or '').strip()
        if not content:
            return False

        cleaned_query = re.sub(r'<a?:\w+:\d+>', ' ', content)
        cleaned_query = re.sub(r'\s+', ' ', cleaned_query).strip()
        if not cleaned_query or not re.search(r'\w', cleaned_query):
            return False
        if re.search(r'https?://|www\.', cleaned_query, re.IGNORECASE):
            return False

        return True

    def _should_process_self_authored_message(self, message) -> bool:
        return self._is_plain_text_keyword_trigger_candidate(message)

    def _should_allow_managed_account_trigger(self, message) -> bool:
        return self._is_plain_text_keyword_trigger_candidate(message)

    def _log_message_skip(self, message, reason):
        author = getattr(message, 'author', None)
        author_name = getattr(author, 'name', None) or '未知作者'
        author_id = getattr(author, 'id', None)
        channel = getattr(message, 'channel', None)
        channel_name = getattr(channel, 'name', None) or str(getattr(channel, 'id', '未知频道'))
        account_name = getattr(getattr(self, 'user', None), 'name', None) or f'账号#{self.account_id}'
        preview = self._message_preview(message)
        logger.debug(
            f'⏭️ [跳过] 账号:{account_name} | 原因:{reason} | 作者:{author_name}({author_id}) '
            f'| 频道:{channel_name} | 内容:"{preview}"'
        )

    def _should_filter_message(self, message, ignore_image_filters=False):
        """检查消息是否应该被过滤"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db

            user_settings = None

            # 0. 数字范围过滤逻辑（可配置关键词）
            filter_keyword = ''
            min_value = 35
            max_value = 46

            if self.user_id:
                user_settings = db.get_user_settings(self.user_id)
                if user_settings:
                    filter_keyword = (user_settings.get('numeric_filter_keyword') or '').strip()
                    min_value = user_settings.get('filter_size_min', 35)
                    max_value = user_settings.get('filter_size_max', 46)

            if filter_keyword:
                try:
                    min_value = int(min_value)
                    max_value = int(max_value)
                except (TypeError, ValueError):
                    min_value = None
                    max_value = None

                if min_value is not None and max_value is not None and min_value < max_value:
                    pattern = rf'(?i){re.escape(filter_keyword)}\s*[:=-]?\s*(\d+)'
                    value_matches = re.findall(pattern, message.content or '')
                    for value_str in value_matches:
                        try:
                            value = int(value_str)
                            if value < min_value or value > max_value:
                                logger.debug(
                                    f'🚫 消息被过滤: {filter_keyword} {value} 超出范围 ({min_value}-{max_value})'
                                )
                                return True
                        except ValueError:
                            continue

            # 1. 检查全局消息过滤规则
            filters = db.get_message_filters()
            message_content = (message.content or '').lower()

            for filter_rule in filters:
                raw_filter_value = filter_rule.get('filter_value') or ''
                filter_value = raw_filter_value.lower()
                filter_type = filter_rule['filter_type']

                if filter_type == 'contains':
                    if filter_value in message_content:
                        logger.debug(f'消息被过滤: 包含 "{filter_value}"')
                        return True
                elif filter_type == 'starts_with':
                    if message_content.startswith(filter_value):
                        logger.debug(f'消息被过滤: 以 "{filter_value}" 开头')
                        return True
                elif filter_type == 'ends_with':
                    if message_content.endswith(filter_value):
                        logger.debug(f'消息被过滤: 以 "{filter_value}" 结尾')
                        return True
                elif filter_type == 'regex':
                    try:
                        if re.search(filter_value, message_content, re.IGNORECASE):
                            logger.debug(f'消息被过滤: 匹配正则 "{filter_value}"')
                            return True
                    except re.error:
                        logger.warning(f'无效的正则表达式: {filter_value}')
                elif filter_type == 'numeric_range':
                    try:
                        rule = json.loads(raw_filter_value) if raw_filter_value else {}
                    except json.JSONDecodeError:
                        rule = {}

                    keyword = str(rule.get('keyword') or '').strip()
                    min_value = rule.get('min')
                    max_value = rule.get('max')

                    if not keyword:
                        continue

                    try:
                        min_value = int(min_value)
                        max_value = int(max_value)
                    except (TypeError, ValueError):
                        continue

                    if min_value >= max_value:
                        continue

                    pattern = rf'(?i){re.escape(keyword)}\s*[:=-]?\s*(\d+)'
                    value_matches = re.findall(pattern, message.content or '')
                    for value_str in value_matches:
                        try:
                            value = int(value_str)
                            if value < min_value or value > max_value:
                                logger.debug(
                                    f'消息被过滤: {keyword} {value} 超出范围 ({min_value}-{max_value})'
                                )
                                return True
                        except ValueError:
                            continue
                elif filter_type == 'user_id':
                    # 检查用户ID过滤
                    filter_user_ids = split_filter_values(filter_value)
                    sender_id = str(message.author.id)
                    sender_name = str(message.author.name).lower()

                    for blocked_id in filter_user_ids:
                        blocked_id = blocked_id.strip()
                        if blocked_id == sender_id or blocked_id.lower() in sender_name:
                            logger.debug(f'消息被过滤: 用户 {message.author.name} (ID: {sender_id}) 在过滤列表中')
                            return True
                elif filter_type == 'role_id':
                    role_ids = split_filter_values(filter_value)
                    if role_ids and getattr(message, 'guild', None):
                        author_roles = getattr(message.author, 'roles', []) or []
                        author_role_ids = {str(role.id) for role in author_roles if getattr(role, 'id', None) is not None}
                        if author_role_ids.intersection(set(role_ids)):
                            logger.debug(f'消息被过滤: 用户 {message.author.name} 命中身份组过滤')
                            return True
                elif filter_type == 'image':
                    if ignore_image_filters:
                        continue
                    if self._message_has_image(message):
                        logger.debug('消息被过滤: 图片消息')
                        return True

            # 2. 检查用户个性化设置的过滤规则
            if user_settings:
                # 检查用户黑名单
                user_blacklist = user_settings.get('user_blacklist', '')
                if user_blacklist:
                    blacklist_users = [u.strip().lower() for u in user_blacklist.split(',') if u.strip()]
                    sender_name = str(message.author.name).lower()
                    sender_id = str(message.author.id).lower()

                    for blocked_user in blacklist_users:
                        blocked_user = blocked_user.lower()
                        if blocked_user in sender_name or blocked_user == sender_id:
                            logger.debug(f'消息被过滤: 用户 {message.author.name} 在黑名单中')
                            return True

                # 检查关键词过滤
                keyword_filters = user_settings.get('keyword_filters', '')
                if keyword_filters:
                    filter_keywords = [k.strip().lower() for k in keyword_filters.split(',') if k.strip()]

                    for keyword in filter_keywords:
                        if keyword in message_content:
                            logger.debug(f'消息被过滤: 包含关键词 "{keyword}"')
                            return True

        except Exception as e:
            logger.error(f'检查消息过滤失败: {e}')

        return False

    def _get_custom_reply(self):
        """获取自定义回复内容"""
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            replies = db.get_custom_replies()

            if replies:
                # 返回优先级最高的活跃回复
                return replies[0]
        except Exception as e:
            logger.error(f'获取自定义回复失败: {e}')

        return None

    async def on_ready(self):
        logger.info(f'Discord机器人已登录: {self.user} (ID: {self.user.id})')
        logger.info(f'机器人已就绪，开始监听消息')
        self._ensure_review_bark_monitor_task()
        try:
            await self._refresh_channel_cache()
            bound_channels = DiscordBotClient._bound_channels_cache
            if bound_channels:
                bound_list = sorted(bound_channels)
                preview = ", ".join(bound_list[:5])
                suffix = " ..." if len(bound_list) > 5 else ""
                logger.info(f'监听频道: 已绑定 {len(bound_list)} 个 ({preview}{suffix})')
            else:
                logger.info('监听频道: 未绑定频道')
        except Exception as e:
            logger.error(f'获取监听频道失败: {e}')
        self.running = True
        self.last_ready_at = time.monotonic()

        # 更新数据库中的账号状态为在线
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            if hasattr(self, 'account_id'):
                updated = db.update_account_status(
                    self.account_id,
                    'online',
                    min_update_interval_seconds=60,
                )
                db.update_discord_account_profile(
                    self.account_id,
                    **_build_discord_account_profile(self),
                )
                if updated:
                    logger.info(f'账号 {self.account_id} 状态已更新为在线')
        except Exception as e:
            logger.error(f'更新账号状态失败: {e}')

    async def on_disconnect(self):
        self.running = False
        now_monotonic = time.monotonic()
        self.last_disconnect_at = now_monotonic
        window_seconds = max(
            float(getattr(config, 'DISCORD_GATEWAY_FLAP_WINDOW_SECONDS', 600.0) or 600.0),
            30.0,
        )
        flap_threshold = max(
            int(getattr(config, 'DISCORD_GATEWAY_FLAP_THRESHOLD', 5) or 5),
            2,
        )
        self._gateway_disconnect_events = [
            timestamp
            for timestamp in getattr(self, '_gateway_disconnect_events', [])
            if timestamp >= now_monotonic - window_seconds
        ]
        self._gateway_disconnect_events.append(now_monotonic)
        self.disconnect_count = len(self._gateway_disconnect_events)
        logger.warning(
            'Discord连接已断开，等待自动恢复: account_id=%s user_id=%s recent_disconnects=%s',
            self.account_id,
            self.user_id,
            self.disconnect_count,
        )
        if self.disconnect_count >= flap_threshold:
            logger.warning(
                'Discord连接频繁断开，关闭账号等待worker冷却重启: account_id=%s user_id=%s recent_disconnects=%s window=%.0fs',
                self.account_id,
                self.user_id,
                self.disconnect_count,
                window_seconds,
            )
            try:
                await self.close()
            except Exception as e:
                logger.error(f'关闭频繁断开账号失败: {e}')
            return

        async def _mark_offline_if_still_disconnected(disconnect_at):
            grace_seconds = max(
                float(getattr(config, 'DISCORD_DISCONNECT_OFFLINE_GRACE_SECONDS', 45.0) or 45.0),
                5.0,
            )
            await asyncio.sleep(grace_seconds)
            if self.running or self.last_ready_at >= disconnect_at:
                return
            try:
                try:
                    from database import db
                except ImportError:
                    from .database import db
                if hasattr(self, 'account_id') and self.account_id:
                    db.update_account_status(self.account_id, 'offline')
            except Exception as e:
                logger.error(f'更新账号离线状态失败: {e}')

        old_offline_task = getattr(self, '_offline_status_task', None)
        if old_offline_task and not old_offline_task.done():
            old_offline_task.cancel()
        self._offline_status_task = asyncio.create_task(
            _mark_offline_if_still_disconnected(now_monotonic)
        )

    async def on_resumed(self):
        self.running = True
        self.last_ready_at = time.monotonic()
        old_offline_task = getattr(self, '_offline_status_task', None)
        if old_offline_task and not old_offline_task.done():
            old_offline_task.cancel()
        logger.info(
            'Discord连接已恢复: account_id=%s user_id=%s',
            self.account_id,
            self.user_id,
        )
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            if hasattr(self, 'account_id') and self.account_id:
                db.update_account_status(self.account_id, 'online')
                db.update_discord_account_profile(
                    self.account_id,
                    **_build_discord_account_profile(self),
                )
        except Exception as e:
            logger.error(f'更新账号恢复在线状态失败: {e}')

    async def on_message(self, message):
        if not self.running:
            return

        is_self_authored = message.author == self.user

        # 默认忽略自己的消息；仅顶层纯文本关键词允许监听/两者账号自触发
        if is_self_authored and not self._should_process_self_authored_message(message):
            return

        # 忽略机器人和webhook的消息
        if message.author.bot or message.webhook_id:
            return

        # 托管账号之间默认不互相触发；仅放行顶层纯文本关键词，方便绑定账号手动测试/触发
        if _is_managed_account_author_id(getattr(message.author, "id", None)) and not is_self_authored:
            if not self._should_allow_managed_account_trigger(message):
                if (
                    getattr(message, 'reference', None) is None
                    and not getattr(message, 'attachments', None)
                    and (getattr(message, 'content', None) or '').strip()
                ):
                    self._log_message_skip(message, '托管账号消息已忽略')
                return

        # 他人发起私信（DM）立即通知；DM 不进入自动回复链路
        if getattr(message, "guild", None) is None:
            try:
                await self._notify_dm_interaction_if_needed(message)
            except Exception as e:
                _log_rate_limited_bark_issue("处理私信 Bark 通知失败", _summarize_exception_for_log(e))
            return

        # 屏蔽活动通知/系统消息以及 @everyone/@here 广播
        if self._should_ignore_mass_or_activity_message(message):
            return

        # 1. 所有账号都可触发互动通知（无需频道绑定）
        try:
            await self._notify_direct_interaction_if_needed(message)
        except Exception as e:
            _log_rate_limited_bark_issue("处理 @/回复 Bark 通知失败", _summarize_exception_for_log(e))

        # 2. 所有绑定账号都可进入自动回复链路；真正执行搜索的账号由去重锁选出
        website_configs = None
        try:
            listener_allowed, website_configs = await self._is_account_bound_in_channel(message.channel, include_sender=True)
            if not listener_allowed:
                if self._is_plain_text_keyword_trigger_candidate(message):
                    self._log_message_skip(message, '当前账号未绑定该频道')
                return
        except Exception as e:
            logger.error(f"检查监听权限失败: {e}")
            return

        # 3. 忽略 @别人的信息（避免进入商品回复链路）
        if message.mentions:
            self._log_message_skip(message, '消息包含@提及')
            return

        # 4. 忽略回复别人的信息（避免进入商品回复链路）
        if message.reference is not None:
            self._log_message_skip(message, '回复消息不进入商品搜索')
            return

        try:
            if not mark_message_as_processed(message.id, self.user_id):
                logger.debug(f"消息 {message.id} 已被其他(合法的)Bot处理，跳过")
                return
        except Exception as e:
            logger.error(f"消息去重检查失败: {e}")
            return

        website_configs_to_process = list(website_configs or [])
        if not website_configs_to_process:
            website_configs_to_process = await self.get_website_configs_by_channel_async(message.channel)

        if await self._is_globally_blocked_author(message):
            return

        triggered_global_filter_ids = await self._apply_global_block_user_triggers(message)
        if triggered_global_filter_ids:
            return

        user_website_settings_map = {}
        website_configs_to_process = await self._exclude_blocked_website_configs(
            message,
            website_configs_to_process,
        )

        if website_configs_to_process:
            user_website_settings_map = await self._get_user_website_settings_map_for_configs(
                website_configs_to_process
            )
            triggered_website_ids = await self._apply_website_block_user_triggers(
                message,
                website_configs_to_process,
                user_website_settings_map=user_website_settings_map,
            )
            if triggered_website_ids:
                website_configs_to_process = [
                    website_config
                    for website_config in website_configs_to_process
                    if website_config.get('id') not in triggered_website_ids
                ]

        if not website_configs_to_process:
            logger.info(
                "⏭️ [跳过] 作者 %s(%s) 当前网站均已被过滤或拉黑",
                self._get_message_author_name(message),
                getattr(getattr(message, 'author', None), 'id', None),
            )
            return

        # 6. 触发内容过滤规则
        if self._should_filter_message(message, ignore_image_filters=True):
            return

        logger.debug(
            f'📨 [接收] 账号:{self.user.name} | 频道:{message.channel.name} | 内容: "{self._message_preview(message, limit=50)}"'
        )

        # 获取用户设置
        keyword_reply_enabled = True
        image_reply_enabled = True
        if self.user_id:
            try:
                user_settings = await self._get_user_settings_safe()
                keyword_reply_enabled = user_settings.get('keyword_reply_enabled', 1) in (1, True, "1", "true", "True")
                image_reply_enabled = user_settings.get('image_reply_enabled', 1) in (1, True, "1", "true", "True")
            except Exception as e:
                logger.error(f'获取用户回复开关设置失败: {e}')

        # 处理关键词消息转发
        await self._run_message_stage_with_timeout(
            message,
            'keyword_forward',
            self.handle_keyword_forward(message),
            MESSAGE_FORWARD_TIMEOUT_SECONDS,
        )

        # 处理关键词搜索。图文同发时仍继续处理附件图片，避免错过以图搜图。
        if keyword_reply_enabled:
            self._start_keyword_search_background_task(
                message,
                website_configs_to_process,
            )

        # 处理图片
        if image_reply_enabled and message.attachments:
            if self._should_filter_message(message):
                return
            scheduled_image_replies = 0
            for attachment in message.attachments:
                content_type = (getattr(attachment, 'content_type', '') or '').lower()
                filename = (getattr(attachment, 'filename', '') or '').lower()
                is_image = False
                if content_type.startswith('image/'):
                    is_image = True
                elif filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.heic', '.heif')):
                    is_image = True

                if is_image:
                    if scheduled_image_replies >= MESSAGE_IMAGE_REPLY_MAX_ATTACHMENTS:
                        logger.info(
                            f"⏭️ 跳过多余图片附件: message_id={message.id} "
                            f"limit={MESSAGE_IMAGE_REPLY_MAX_ATTACHMENTS} filename={attachment.filename}"
                        )
                        continue
                    scheduled_image_replies += 1
                    logger.debug(f"📷 检测到图片，开始处理: {attachment.filename}")
                    self._start_image_reply_background_task(
                        message,
                        attachment,
                        website_configs_to_process,
                    )

    async def on_raw_reaction_add(self, payload):
        """监听他人给当前账号消息添加表情（包含点赞）并发送 Bark 通知。"""
        if not self.running:
            return
        if not self.user:
            return

        channel_id = getattr(payload, "channel_id", None)
        message_id = getattr(payload, "message_id", None)
        reactor_id = getattr(payload, "user_id", None)
        if not channel_id or not message_id or not reactor_id:
            return
        if reactor_id == getattr(self.user, "id", None):
            return

        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if channel is None:
                return

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                return
            if message is None:
                return
            if getattr(message.author, "id", None) != getattr(self.user, "id", None):
                return

            reactor = getattr(payload, "member", None)
            if reactor is None:
                reactor = self.get_user(reactor_id) or await self.fetch_user(reactor_id)
            if reactor is None:
                return

            emoji_obj = getattr(payload, "emoji", None)
            emoji_text = str(emoji_obj) if emoji_obj is not None else ""

            await self._notify_reaction_interaction_if_needed(message, reactor, emoji_text)
        except Exception as e:
            _log_rate_limited_bark_issue("处理表情互动 Bark 通知失败", _summarize_exception_for_log(e))

    async def on_relationship_add(self, relationship):
        """监听好友关系新增（重点：收到好友请求）。"""
        if not self.running or not self.user:
            return
        if relationship is None:
            return

        rel_type = getattr(relationship, "type", None)
        incoming_type = getattr(discord.RelationshipType, "incoming_request", None)
        friend_type = getattr(discord.RelationshipType, "friend", None)
        if rel_type not in (incoming_type, friend_type):
            return

        user_obj = getattr(relationship, "user", None)
        try:
            if rel_type == friend_type:
                await self._notify_relationship_interaction_if_needed(
                    user_obj=user_obj,
                    interaction_label="添加好友",
                    detail_text="双方已建立好友关系",
                )
                return

            await self._notify_relationship_interaction_if_needed(
                user_obj=user_obj,
                interaction_label="收到好友请求",
                detail_text="对方向该账号发起了好友请求",
            )
        except Exception as e:
            _log_rate_limited_bark_issue("处理好友请求 Bark 通知失败", _summarize_exception_for_log(e))

    async def on_relationship_update(self, before, after):
        """监听好友关系更新（例如：请求通过后成为好友）。"""
        if not self.running or not self.user:
            return
        if before is None or after is None:
            return

        friend_type = getattr(discord.RelationshipType, "friend", None)
        before_type = getattr(before, "type", None)
        after_type = getattr(after, "type", None)
        if after_type != friend_type or before_type == friend_type:
            return

        user_obj = getattr(after, "user", None) or getattr(before, "user", None)
        try:
            await self._notify_relationship_interaction_if_needed(
                user_obj=user_obj,
                interaction_label="添加好友",
                detail_text="双方已建立好友关系",
            )
        except Exception as e:
            _log_rate_limited_bark_issue("处理添加好友 Bark 通知失败", _summarize_exception_for_log(e))

    async def on_private_channel_create(self, channel):
        """监听新私信会话创建并提醒（兜底）。"""
        if not self.running or not self.user:
            return
        if channel is None:
            return

        channel_id = getattr(channel, "id", None)
        if self._is_dm_alert_recent(channel_id):
            return

        recipient = getattr(channel, "recipient", None)
        if recipient is None:
            return
        if getattr(recipient, "id", None) == getattr(self.user, "id", None):
            return

        user_settings = await self._get_user_settings_safe()
        bark_enabled = user_settings.get("bark_enabled", 0) in (1, True, "1", "true", "True")
        bark_device_key = (user_settings.get("bark_device_key") or "").strip()
        if not bark_enabled or not bark_device_key:
            return

        bark_server_url = (user_settings.get("bark_server_url") or "https://api.day.app").strip()
        account_name = getattr(self.user, "name", None) or f"账号#{self.account_id}"
        sender_name = (
            getattr(recipient, "display_name", None)
            or getattr(recipient, "name", None)
            or "未知用户"
        )
        time_text = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        title = f"{sender_name} 发起私信"
        if len(title) > 60:
            title = f"{title[:60]}..."

        body = (
            f"账号: {account_name}\n"
            f"类型: 发起私信\n"
            f"发送者: {sender_name}\n"
            f"位置: 私信\n"
            f"内容: [新私信会话]\n"
            f"时间: {time_text}"
        )

        await self._send_bark_notification(
            bark_server_url=bark_server_url,
            bark_device_key=bark_device_key,
            title=title,
            body=body,
            jump_url=None,
        )
        self._mark_dm_alert(channel_id)
        logger.info(f"📱 Bark通知已发送: 账号:{account_name} | 类型:发起私信 | 发送者:{sender_name}")

    async def handle_image(self, message, attachment, website_configs_override=None):
        try:
            website_configs = (
                website_configs_override
                if website_configs_override is not None
                else await self.get_website_configs_by_channel_async(message.channel)
            )
            if not website_configs:
                return False

            user_website_settings_map = await self._get_user_website_settings_map_for_configs(
                website_configs
            )
            website_filters_map = {}
            for website_config in website_configs:
                website_id = website_config.get('id')
                if not website_id:
                    continue
                website_settings = user_website_settings_map.get(website_id) or {}
                website_filters = self._parse_message_filters(website_settings.get('message_filters', '[]'))
                website_filters_map[int(website_id)] = website_filters

            # 【增强稳定性】增加超时时间，添加代理支持
            timeout = aiohttp.ClientTimeout(total=30, connect=10)  # 30秒总超时，10秒连接超时
            image_data = None

            # 【代理配置】从环境变量获取代理（支持国内网络环境）
            proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None

            # 【伪装头】添加 User-Agent 防止被 Discord CDN 拒绝
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            # 重试最多3次
            for attempt in range(3):
                try:
                    logger.debug(f"下载Discord图片 (尝试 {attempt + 1}/3): {attachment.filename}")
                    # 【关键修复】trust_env=True 允许使用系统代理
                    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
                        async with session.get(attachment.url, proxy=proxy_url) as resp:
                            if resp.status == 200:
                                image_data = await resp.read()
                                logger.debug(f"图片下载成功，大小: {len(image_data)} bytes")
                                break
                            else:
                                logger.debug(f"图片下载失败，状态码: {resp.status}")
                except aiohttp.ClientError as e:
                    logger.debug(f"图片下载网络错误 (尝试 {attempt + 1}/3): {e}")
                    if attempt < 2:  # 不是最后一次尝试
                        await asyncio.sleep(2)  # 【增强】等待2秒后重试
                except Exception as e:
                    logger.error(f"图片下载未知错误 (尝试 {attempt + 1}/3): {e}")
                    break

            if image_data is None:
                logger.error("图片下载失败，已达到最大重试次数")
                return False  # 静默失败，不发送错误消息

            user_settings = {}
            user_threshold = config.DISCORD_SIMILARITY_THRESHOLD
            best_match_image_threshold = 0.75
            if self.user_id:
                try:
                    try:
                        from database import db
                    except ImportError:
                        from .database import db
                    user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
                    if user_settings and user_settings.get('discord_similarity_threshold') is not None:
                        user_threshold = user_settings['discord_similarity_threshold']
                    if user_settings and user_settings.get('keyword_reply_best_match_image_threshold') is not None:
                        best_match_image_threshold = user_settings['keyword_reply_best_match_image_threshold']
                except Exception as e:
                    logger.error(f'获取用户相似度设置失败: {e}')

            skip_threshold = self._resolve_image_skip_threshold(website_configs, user_threshold)

            # 【新增】AI并发限制：最多同时2个AI推理任务
            # 使用Semaphore控制并发，防止CPU饱和导致Flask主线程阻塞
            async with ai_concurrency_limit:
                logger.debug(f"🔒 获取AI并发锁，当前等待队列: {ai_concurrency_limit._value}")

                # 传入用户店铺权限，避免 A 店铺命中结果串到 B 店铺
                scoped_user_shops = self.user_shops if self.user_shops else None
                image_query_text = _build_forum_post_search_text(message)
                result = await self.recognize_image(
                    image_data,
                    user_shops=scoped_user_shops,
                    threshold=0.0,
                    query_text=image_query_text,
                )

                logger.debug(f"🔓 释放AI并发锁")

            logger.debug(
                f'图片识别结果: success={result.get("success") if result else False}, '
                f'results_count={len(result.get("results", [])) if result else 0}'
            )

            if result:
                blocked_filter_match = result.get('blocked_filter_match')
                blocked_website_filter_matches = result.get('blocked_website_filter_matches') or []
                try:
                    if blocked_filter_match:
                        sim = float(blocked_filter_match.get('similarity', 0))
                        threshold_val = float(blocked_filter_match.get('threshold', 0))
                        if sim >= threshold_val:
                            logger.info(
                                f'🚫 命中图片过滤: 规则 {blocked_filter_match.get("filter_id")} '
                                f'相似度 {sim:.3f} >= {threshold_val:.3f} | 频道: {message.channel.name}'
                            )
                            return False
                except Exception:
                    pass

            if result and result.get('success') and result.get('results'):
                # 获取最佳匹配结果
                best_match = result['results'][0]
                similarity = best_match.get('similarity', 0)
                top1_margin = _extract_image_match_top1_margin(best_match)

                logger.debug(f'最佳匹配相似度: {similarity:.4f}, 用户阈值: {user_threshold:.4f}')

                image_match_context = {
                    'type': 'image',
                    'similarity': similarity,
                    'base_threshold': user_threshold,
                    'best_match_image_base_threshold': best_match_image_threshold,
                    'top1_margin': top1_margin,
                    'website_filter_matches': blocked_website_filter_matches,
                }

                below_reply_threshold = similarity < skip_threshold
                if below_reply_threshold:
                    await self._record_skipped_image_history(
                        image_data=image_data,
                        attachment=attachment,
                        message=message,
                        similarity=similarity,
                        threshold=skip_threshold,
                        best_match=best_match,
                    )
                    logger.info(
                        f'⏭️ 图片命中未过阈值，记录略过历史并跳过回复: '
                        f'相似度 {similarity:.3f} < {skip_threshold:.3f} | 频道: {message.channel.name}'
                    )
                    return False
                else:
                    confidence_block_reason = _get_image_match_reply_block_reason(
                        image_match_context,
                        {'image_similarity_threshold': skip_threshold},
                    )
                    if confidence_block_reason:
                        await self._record_skipped_image_history(
                            image_data=image_data,
                            attachment=attachment,
                            message=message,
                            similarity=similarity,
                            threshold=skip_threshold,
                            best_match=best_match,
                        )
                        logger.info(
                            f'⏭️ 图片命中不够稳，记录略过历史并跳过回复: '
                            f'{confidence_block_reason} | 频道: {message.channel.name}'
                        )
                        return False

                product = best_match.get('product', {})
                product_title = (product.get('title') or '').strip()
                logger.info(
                    f'📷 图片匹配: 商品 {product.get("id")} {product_title} | 相似度 {similarity:.2f} | 频道: {message.channel.name}'
                )

                ocr_text = ''
                global_filters = []
                try:
                    try:
                        from database import db
                    except ImportError:
                        from .database import db
                    global_filters = await asyncio.get_event_loop().run_in_executor(None, db.get_message_filters)
                except Exception as e:
                    logger.error(f'获取全局 OCR 过滤规则失败: {e}')

                should_run_ocr = should_run_ocr_for_image_reply(
                    website_configs,
                    website_filters_map,
                    global_filters=global_filters,
                    similarity=similarity,
                    base_threshold=user_threshold,
                )
                if should_run_ocr:
                    ocr_text = await asyncio.to_thread(ocr_service.extract_text, image_data)
                    if ocr_text:
                        logger.debug(
                            "📝 图片 OCR 文本: %s",
                            ocr_text.replace('\n', ' ')[:200],
                        )

                product_rule_enabled = product.get('ruleEnabled', True)
                if isinstance(product_rule_enabled, str):
                    product_rule_enabled = product_rule_enabled.strip().lower() not in {'0', 'false', 'no', 'off'}
                elif isinstance(product_rule_enabled, (int, float)):
                    product_rule_enabled = bool(product_rule_enabled)

                custom_reply = None
                image_source = product.get('imageSource') or product.get('image_source') or 'product'
                has_custom_images = False

                if image_source == 'upload':
                    uploaded_imgs = self._coerce_list(product.get('uploaded_reply_images'))
                    product['uploaded_reply_images'] = uploaded_imgs
                    has_custom_images = bool(uploaded_imgs)
                elif image_source == 'custom':
                    custom_urls = self._coerce_list(product.get('customImageUrls') or product.get('custom_image_urls'))
                    if custom_urls:
                        product['customImageUrls'] = custom_urls
                    has_custom_images = bool(custom_urls)
                elif image_source == 'product':
                    selected_indexes = self._coerce_list(product.get('selectedImageIndexes') or product.get('custom_reply_images'))
                    if selected_indexes:
                        product['selectedImageIndexes'] = selected_indexes
                    has_custom_images = bool(selected_indexes)

                if below_reply_threshold:
                    custom_reply = None
                elif not product_rule_enabled or has_custom_images:
                    custom_text = (product.get('custom_reply_text') or '').strip()
                    custom_reply = {
                        'reply_type': 'text' if custom_text else 'custom_only',
                        'content': custom_text,
                        'product_data': product
                    }
                    if not product_rule_enabled:
                        logger.info(f"商品 {product.get('id')} 规则已禁用，准备发送自定义回复")
                    elif has_custom_images:
                        logger.info(f"商品 {product.get('id')} 配置了自定义图片，准备发送自定义回复")
                elif product_rule_enabled:
                    custom_reply = self._get_custom_reply()

                reply_sent = await self.schedule_reply(
                    message,
                    product,
                    custom_reply,
                    match_context={
                        **image_match_context,
                        'best_match_image_index': best_match.get('imageIndex', best_match.get('image_index')),
                        'ocr_text': ocr_text,
                    },
                    website_configs_override=website_configs,
                )

                if reply_sent:
                    await self._record_image_search_history(
                        image_data=image_data,
                        attachment=attachment,
                        message=message,
                        similarity=similarity,
                        threshold=skip_threshold,
                        best_match=best_match,
                        is_skipped=False,
                    )

                logger.debug(f'图片识别完成，相似度: {similarity:.4f}')
                return bool(reply_sent)
            elif result and result.get('success'):
                await self._record_skipped_image_history(
                    image_data=image_data,
                    attachment=attachment,
                    message=message,
                    similarity=0.0,
                    threshold=skip_threshold,
                    best_match=None,
                )
                logger.info(
                    f'⏭️ 图片未命中任何商品，已记录历史: 阈值 {skip_threshold:.3f} | 频道: {message.channel.name}'
                )
                return False

        except Exception as e:
            logger.error(f'Error handling image: {e}')
            # 不发送错误消息到Discord，只记录日志
            return False

    async def handle_keyword_forward(self, message):
        """处理关键词消息转发"""
        try:
            # 检查消息内容是否包含关键词
            message_content = message.content.lower() if message.content else ""
            has_keyword = any(keyword.strip().lower() in message_content for keyword in config.FORWARD_KEYWORDS)

            if has_keyword and config.FORWARD_TARGET_CHANNEL_ID:
                # 获取目标频道
                target_channel = self.get_channel(config.FORWARD_TARGET_CHANNEL_ID)
                if target_channel:
                    # 构建转发消息
                    forward_embed = discord.Embed(
                        title="📢 商品相关消息转发",
                        description=f"**原始消息:** {message.content[:500]}{'...' if len(message.content) > 500 else ''}",
                        color=0x00ff00,
                        timestamp=message.created_at
                    )

                    forward_embed.add_field(
                        name="发送者",
                        value=f"{message.author.name}#{message.author.discriminator}",
                        inline=True
                    )

                    forward_embed.add_field(
                        name="来源频道",
                        value=f"#{message.channel.name}",
                        inline=True
                    )

                    forward_embed.add_field(
                        name="服务器",
                        value=message.guild.name if message.guild else "DM",
                        inline=True
                    )

                    # 如果有附件，添加到embed中
                    if message.attachments:
                        attachment_urls = [att.url for att in message.attachments]
                        forward_embed.add_field(
                            name="附件",
                            value="\n".join(attachment_urls),
                            inline=False
                        )

                    forward_embed.set_footer(text=f"消息ID: {message.id}")

                    await _send_discord_message(target_channel, embed=forward_embed)
                    logger.info(f"转发了包含关键词的消息: {message.content[:100]}...")
                else:
                    logger.warning(f"找不到目标频道: {config.FORWARD_TARGET_CHANNEL_ID}")

        except Exception as e:
            logger.error(f'Error handling keyword forward: {e}')

    async def handle_keyword_search(
        self,
        message,
        website_configs_override=None,
        allow_keyword_image_search=True,
    ):
        """处理关键词商品搜索"""
        keyword_triggered = False
        keyword_stage_started_at = time.perf_counter()
        keyword_stage_timings = {}

        def _record_keyword_stage(stage_name, started_at):
            elapsed = time.perf_counter() - started_at
            keyword_stage_timings[stage_name] = keyword_stage_timings.get(stage_name, 0.0) + elapsed
            return time.perf_counter()

        def _log_keyword_stage_timings(reason):
            total_elapsed = time.perf_counter() - keyword_stage_started_at
            if total_elapsed < MESSAGE_STAGE_SLOW_SECONDS:
                return
            stage_summary = ' '.join(
                f'{name}={elapsed:.2f}s'
                for name, elapsed in keyword_stage_timings.items()
            ) or 'none'
            logger.warning(
                f"关键词搜索步骤耗时: reason={reason} message_id={getattr(message, 'id', 'unknown')} "
                f"| channel_id={getattr(getattr(message, 'channel', None), 'id', 'unknown')} "
                f"| total={total_elapsed:.2f}s | allow_keyword_image_search={allow_keyword_image_search} "
                f"| stages={stage_summary} | query={str(search_query)[:120] if 'search_query' in locals() else '<unset>'}"
            )

        try:
            search_query = _build_forum_post_search_text(message)
            if not search_query:
                return False

            search_query = search_query.strip()
            if not search_query:
                return False

            # 移除自定义表情，避免表情ID/名称误触发关键词
            cleaned_query = re.sub(r'<a?:\w+:\d+>', ' ', search_query)
            cleaned_query = re.sub(r'\s+', ' ', cleaned_query).strip()
            if not cleaned_query:
                return False
            if not re.search(r'\w', cleaned_query):
                return False
            search_query = cleaned_query

            linked_item_id = _shared_extract_marketplace_item_id_from_text(search_query)
            if not linked_item_id and _should_ignore_keyword_search_query(search_query):
                return False

            # 调用搜索API
            stage_started = time.perf_counter()
            result = await self.search_products_by_keyword(search_query)
            stage_started = _record_keyword_stage('text_search', stage_started)

            all_products = []
            if result and result.get('success') and result.get('products'):
                all_products = result['products']

            if not all_products:
                logger.debug(f'关键词搜索无结果: {search_query}')
                _log_keyword_stage_timings('no_products')
                return False

            if self.user_shops:
                allowed_shops = {_normalize_keyword_search_text(s) for s in self.user_shops if s}

                def _shop_matches(shop_value: str) -> bool:
                    normalized = _normalize_keyword_search_text(shop_value)
                    if not normalized:
                        return False
                    # 店铺权限必须严格命中，避免 A 店铺商品误落到 B 店铺
                    return normalized in allowed_shops

                if allowed_shops:
                    filtered_products = []
                    for product in all_products:
                        shop_value = product.get('shop_name') or product.get('shopName') or ''
                        if _shop_matches(shop_value):
                            filtered_products.append(product)
                    if filtered_products:
                        all_products = filtered_products
                    else:
                        logger.debug(f'关键词搜索结果被店铺权限过滤: {search_query}')
                        _record_keyword_stage('shop_filter', stage_started)
                        _log_keyword_stage_timings('shop_filter_empty')
                        return
            stage_started = _record_keyword_stage('shop_filter', stage_started)

            query_normalized = _normalize_keyword_search_text(search_query)
            query_keyword_candidates = _build_query_keyword_candidates(query_normalized)

            # 检查频道是否绑定了网站配置（必须绑定才能回复）
            stage_started = time.perf_counter()
            website_configs = (
                website_configs_override
                if website_configs_override is not None
                else await self.get_website_configs_by_channel_async(message.channel)
            )
            stage_started = _record_keyword_stage('website_configs', stage_started)
            if not website_configs:
                logger.info(f"频道 {message.channel.id} 未绑定网站配置，跳过关键词回复: {search_query}")
                _log_keyword_stage_timings('no_website_configs')
                return False

            def _match_products_for_languages(allowed_languages):
                matched_products = []
                match_reasons = {}
                for product in all_products:
                    reason = _find_query_keyword_match(
                        query_keyword_candidates,
                        product.get('english_title') or product.get('englishTitle') or '',
                        product.get('title') or '',
                        title_translations=product.get('title_translations') or product.get('titleTranslations'),
                        allowed_languages=allowed_languages,
                        query_text=search_query,
                        partition_match_enabled=product.get('partition_match_enabled') or product.get('partitionMatchEnabled'),
                        partition_match_rules=product.get('partition_match_rules') or product.get('partitionMatchRules'),
                    )
                    if not reason:
                        continue
                    matched_products.append(product)
                    product_id = product.get('id')
                    if product_id is not None:
                        match_reasons[product_id] = reason

                matched_keyword_set = {
                    str(reason.get('canonical_keyword')).strip()
                    for reason in match_reasons.values()
                    if str(reason.get('canonical_keyword') or '').strip()
                }
                return matched_products, match_reasons, matched_keyword_set

            website_match_contexts = []
            matched_product_ids = set()
            keyword_triggered = False
            stage_started = time.perf_counter()
            for website_config in website_configs:
                reply_languages = get_effective_reply_languages(
                    website_config.get('reply_language')
                )
                matched_products, match_reasons, matched_keyword_set = _match_products_for_languages(
                    reply_languages
                )
                if not matched_products:
                    logger.debug(
                        f'关键词搜索未命中网站 {website_config.get("id")}: '
                        f'query="{search_query}" | languages={",".join(reply_languages)}'
                    )
                    continue

                website_match_contexts.append({
                    'website_config': website_config,
                    'reply_languages': reply_languages,
                    'matched_products': matched_products,
                    'match_reasons': match_reasons,
                    'matched_keyword_set': matched_keyword_set,
                })
                keyword_triggered = True
                matched_product_ids.update(
                    product.get('id')
                    for product in matched_products
                    if product.get('id') is not None
                )
            stage_started = _record_keyword_stage('website_match', stage_started)

            matched_website_ids = {
                context['website_config'].get('id')
                for context in website_match_contexts
                if context.get('website_config')
            }
            db = None
            global_filters = []
            stage_started = time.perf_counter()
            try:
                try:
                    from database import db as imported_db
                except ImportError:
                    from .database import db as imported_db
                db = imported_db
                global_filters = await asyncio.get_event_loop().run_in_executor(
                    None, db.get_message_filters
                )
            except Exception as filter_error:
                logger.error(f'获取全局过滤规则失败: {filter_error}')
                global_filters = []

            user_settings = {}
            if self.user_id:
                try:
                    user_settings = await self._get_user_settings_safe()
                except Exception as settings_error:
                    logger.error(f'获取全局关键词命中上限失败: {settings_error}')
                    user_settings = {}
            stage_started = _record_keyword_stage('global_settings', stage_started)

            legacy_global_keyword_match_limit = max(
                0,
                _coerce_int((user_settings or {}).get('keyword_match_limit', 0), 0),
            )
            global_keyword_match_limit = resolve_keyword_match_limit(
                global_filters,
                fallback_limit=legacy_global_keyword_match_limit,
            )

            logger.debug(
                f'关键词搜索成功: "{search_query}" -> 网站命中 {len(website_match_contexts)} 个, '
                f'商品命中 {len(matched_product_ids)} 个'
            )
            for website_context in website_match_contexts:
                website_config = website_context['website_config']
                for product in website_context['matched_products']:
                    product_id = product.get('id')
                    reason = website_context['match_reasons'].get(product_id)
                    if not reason:
                        continue
                    logger.debug(
                        f'关键词命中: query="{search_query}" | 网站 {website_config.get("id")} '
                        f'| 语言 {",".join(website_context["reply_languages"])} | 商品 {product_id} '
                        f'| 命中词 "{reason.get("phrase")}" ({reason.get("source")})'
                    )

            user_website_settings_map = {}
            if self.user_id:
                stage_started = time.perf_counter()
                try:
                    for website_config in website_configs:
                        website_id = website_config.get('id')
                        if not website_id:
                            continue
                        settings = await asyncio.get_event_loop().run_in_executor(
                            None, db.get_user_website_settings, self.user_id, website_id
                        )
                        if settings:
                            user_website_settings_map[website_id] = settings
                except Exception as settings_error:
                    logger.error(f'获取网站关键词命中上限失败: {settings_error}')
                stage_started = _record_keyword_stage('website_settings', stage_started)

            def _website_keyword_limit_exceeded(website_context):
                website_config = website_context['website_config']
                website_settings = user_website_settings_map.get(website_config.get('id')) or {}
                website_filter_rules = self._parse_message_filters(website_settings.get('message_filters', '[]'))
                website_keyword_match_limit = max(
                    0,
                    _coerce_int(
                        website_settings.get('keyword_match_limit', global_keyword_match_limit),
                        global_keyword_match_limit,
                    ),
                )
                website_keyword_match_limit = resolve_keyword_match_limit(
                    website_filter_rules,
                    fallback_limit=website_keyword_match_limit,
                )
                matched_keyword_set = website_context['matched_keyword_set']
                if website_keyword_match_limit > 0 and len(matched_keyword_set) > website_keyword_match_limit:
                    logger.info(
                        f'关键词搜索命中过多，跳过网站 {website_config.get("id")}: query="{search_query}" | '
                        f'命中关键词 {len(matched_keyword_set)} 个 | 上限 {website_keyword_match_limit}'
                    )
                    return True
                return False

            def _log_product_reply_mode(prepared_product, rule_enabled, has_custom_images):
                if not rule_enabled:
                    logger.info(f"商品 {prepared_product.get('id')} 规则已禁用，准备发送自定义回复")
                elif has_custom_images:
                    logger.info(f"商品 {prepared_product.get('id')} 配置了自定义图片，准备发送自定义回复")

            any_reply_scheduled = False
            keyword_image_job_created = False
            skip_keyword_review_check = False

            try:
                if db is None:
                    try:
                        from database import db as imported_db
                    except ImportError:
                        from .database import db as imported_db
                    db = imported_db
            except Exception as db_import_error:
                logger.error(f"导入数据库模块失败: {db_import_error}")
                db = None

            async def _run_keyword_image_search_for_context(website_context):
                if not allow_keyword_image_search:
                    return False, False

                if db is None or not self.user_id:
                    return False, False

                website_config = website_context['website_config']
                website_id = website_config.get('id')
                website_settings = user_website_settings_map.get(website_id) or {}
                try:
                    enabled = bool(int(website_settings.get('keyword_image_search_enabled', 0) or 0))
                except (TypeError, ValueError):
                    enabled = False
                if not enabled:
                    return False, False

                mode = str(website_settings.get('keyword_image_search_mode') or 'manual').strip().lower()
                if mode not in {'manual', 'auto'}:
                    mode = 'manual'
                max_images = _coerce_int(website_settings.get('keyword_image_search_max_images', 3), 3)
                max_images = max(1, min(max_images, 10))

                try:
                    try:
                        from keyword_image_search import keyword_image_search_service
                    except ImportError:
                        from .keyword_image_search import keyword_image_search_service

                    def _search_candidates():
                        return keyword_image_search_service.search_candidates(
                            query_text=search_query,
                            website_config=website_config,
                            user_id=self.user_id,
                            user_shops=(self.user_shops if self.user_shops else None),
                            max_images=max_images,
                            user_settings=user_settings,
                        )

                    search_result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        _search_candidates,
                    )
                    candidates = list(search_result.get('candidates') or [])
                    matched_count = int(search_result.get('matched_result_count') or 0)
                    status = 'ready' if matched_count > 0 else 'no_match'
                    error_message = None
                    provider = search_result.get('provider') or 'searchapi_google_images'
                    external_count = int(search_result.get('external_result_count') or 0)
                except Exception as search_error:
                    logger.error(
                        f"关键词搜图失败: query={search_query} website={website_id} error={search_error}"
                    )
                    candidates = []
                    matched_count = 0
                    status = 'failed'
                    error_message = str(search_error)
                    provider = getattr(config, 'KEYWORD_IMAGE_SEARCH_PROVIDER', 'searchapi_google_maps')
                    external_count = 0

                job_id = await asyncio.get_event_loop().run_in_executor(
                    None,
                    partial(
                        db.create_keyword_image_search_job,
                        user_id=self.user_id,
                        website_id=website_id,
                        query_text=search_query,
                        channel_id=str(getattr(message.channel, 'id', '')),
                        message_id=str(getattr(message, 'id', '')),
                        guild_id=str(getattr(getattr(message, 'guild', None), 'id', '') or ''),
                        author_id=str(getattr(message.author, 'id', '') or ''),
                        mode=mode,
                        provider=provider,
                        status=status,
                        error_message=error_message,
                        candidates=candidates,
                        external_result_count=external_count,
                        matched_result_count=matched_count,
                    ),
                )
                job_created = bool(job_id)
                if job_created:
                    logger.info(
                        f"关键词搜图任务已创建: job={job_id} mode={mode} query={search_query} "
                        f"website={website_id} matched={matched_count}/{external_count}"
                    )

                if mode != 'auto' or status != 'ready':
                    return job_created, False

                matched_candidates = [
                    (index, candidate)
                    for index, candidate in enumerate(candidates)
                    if candidate.get('match_found') and isinstance(candidate.get('product'), dict)
                ]
                if not matched_candidates:
                    return job_created, False

                selected_index, selected_candidate = max(
                    matched_candidates,
                    key=lambda item: _coerce_float(item[1].get('similarity')) or 0.0,
                )
                product = selected_candidate.get('product') or {}
                prepared_product, custom_reply, _, _ = _prepare_effective_product_reply(
                    product,
                    website_config=website_config,
                    fallback_custom_reply=self._get_custom_reply(),
                )
                internal_match = selected_candidate.get('search_result') or {}
                similarity = _coerce_float(selected_candidate.get('similarity')) or 0.0
                best_match_index = internal_match.get('imageIndex', internal_match.get('image_index'))
                match_context = {
                    'type': 'image',
                    'similarity': similarity,
                    'base_threshold': _resolve_image_reply_threshold(
                        {
                            'type': 'image',
                            'similarity': similarity,
                            'base_threshold': user_settings.get(
                                'discord_similarity_threshold',
                                config.DISCORD_SIMILARITY_THRESHOLD,
                            ),
                        },
                        website_config,
                    ),
                    'best_match_image_base_threshold': user_settings.get(
                        'keyword_reply_best_match_image_threshold',
                        0.75,
                    ),
                    'best_match_image_index': best_match_index,
                    'top1_margin': _extract_image_match_top1_margin(internal_match),
                    'keyword_image_search_job_id': job_id,
                    'external_image_url': selected_candidate.get('external_image_url'),
                }
                sent = await self._enqueue_or_dispatch_keyword_reply(
                    message,
                    prepared_product,
                    custom_reply,
                    website_config,
                    match_context=match_context,
                    skip_review_check=skip_keyword_review_check,
                )
                if sent and job_id:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        partial(
                            db.update_keyword_image_search_job,
                            job_id,
                            user_id=self.user_id,
                            status='sent',
                            selected_candidate_index=selected_index,
                            sent_product_id=prepared_product.get('id'),
                            error_message=None,
                        ),
                    )
                return job_created, bool(sent)

            reply_loop_started = time.perf_counter()
            for website_context in website_match_contexts:
                website_config = website_context['website_config']
                if _website_keyword_limit_exceeded(website_context):
                    continue

                image_stage_started = time.perf_counter()
                image_job_created, image_reply_sent = await _run_keyword_image_search_for_context(
                    website_context
                )
                _record_keyword_stage('keyword_image_search', image_stage_started)
                if image_job_created:
                    keyword_image_job_created = True
                if image_reply_sent:
                    any_reply_scheduled = True
                    continue

                matched_products = website_context['matched_products']
                sender_count = 0
                if db is not None:
                    try:
                        sender_ids = await asyncio.get_event_loop().run_in_executor(
                            None, db.get_website_senders, website_config.get('id'), self.user_id
                        )
                        sender_count = len(sender_ids or [])
                    except Exception as sender_error:
                        logger.error(
                            f"获取合并回复发送账号失败(website_id={website_config.get('id')}): {sender_error}"
                        )
                _, _, _, reply_mode, _ = await self._get_keyword_window_settings(
                    website_config,
                    sender_count=sender_count,
                )

                if len(matched_products) == 1:
                    product = matched_products[0]
                    prepared_product, custom_reply, rule_enabled, has_custom_images = _prepare_effective_product_reply(
                        product,
                        website_config=website_config,
                        fallback_custom_reply=self._get_custom_reply(),
                    )
                    _log_product_reply_mode(prepared_product, rule_enabled, has_custom_images)
                    any_reply_scheduled = True
                    self._start_keyword_reply_background_task(
                        self._enqueue_or_dispatch_keyword_reply(
                            message,
                            prepared_product,
                            custom_reply,
                            website_config,
                            skip_review_check=skip_keyword_review_check,
                        ),
                        task_name=(
                            f"keyword-single website={website_config.get('id')} "
                            f"channel={getattr(message.channel, 'id', 'unknown')}"
                        ),
                    )
                    continue

                limited_products = matched_products[:5]
                prepared_entries = []
                products_with_custom_images = []
                for product in limited_products:
                    prepared_product, custom_reply, rule_enabled, has_custom_images = _prepare_effective_product_reply(
                        product,
                        website_config=website_config,
                        fallback_custom_reply=self._get_custom_reply(),
                    )
                    prepared_entries.append({
                        'product': prepared_product,
                        'custom_reply': custom_reply,
                    })
                    if has_custom_images:
                        products_with_custom_images.append(prepared_product)

                if len(products_with_custom_images) > 1:
                    logger.info(
                        f"关键词搜索命中多个带自定义图片的商品，网站 {website_config.get('id')} 改为逐商品发送以保留图片"
                    )
                    for entry in prepared_entries:
                        any_reply_scheduled = True
                        self._start_keyword_reply_background_task(
                            self._enqueue_or_dispatch_keyword_reply(
                                message,
                                entry['product'],
                                entry['custom_reply'],
                                website_config,
                                skip_review_check=skip_keyword_review_check,
                            ),
                            task_name=(
                                f"keyword-single website={website_config.get('id')} "
                                f"channel={getattr(message.channel, 'id', 'unknown')}"
                            ),
                        )
                    continue

                website_lines = []
                reply_entries = []
                for entry in prepared_entries:
                    reply_text = self._generate_reply_content(
                        entry['product'],
                        message.channel.id,
                        entry['custom_reply'],
                        website_config=website_config
                    )
                    if not reply_text:
                        continue
                    website_lines.append(reply_text)
                    reply_entries.append(entry)

                if not website_lines or not reply_entries:
                    continue

                any_reply_scheduled = True
                aggregate_image_product = products_with_custom_images[0] if len(products_with_custom_images) == 1 else None
                base_product = aggregate_image_product or reply_entries[0]['product']
                if aggregate_image_product is not None:
                    logger.info(
                        f"关键词搜索命中单个带自定义图片的商品，网站 {website_config.get('id')} 合并文字并复用商品 "
                        f"{aggregate_image_product.get('id')} 的图片"
                    )

                website_content = _build_multi_reply_content(
                    author_id=getattr(message.author, 'id', None),
                    reply_contents=website_lines,
                    reply_mode=reply_mode,
                )
                repeat_product_ids = [
                    entry['product'].get('id')
                    for entry in reply_entries
                    if entry['product'].get('id')
                ]
                agg_custom_reply = {
                    'reply_type': 'custom_only',
                    'content': website_content,
                    'product_data': base_product,
                    'skip_images': aggregate_image_product is None,
                    'prebuilt_content': True,
                    'explicit_mentions': reply_mode == 'keyword',
                    'repeat_product_ids': repeat_product_ids,
                }
                self._start_keyword_reply_background_task(
                    self._enqueue_or_dispatch_keyword_reply(
                        message,
                        base_product,
                        agg_custom_reply,
                        website_config,
                        skip_review_check=skip_keyword_review_check,
                    ),
                    task_name=(
                        f"keyword-aggregate website={website_config.get('id')} "
                        f"channel={getattr(message.channel, 'id', 'unknown')}"
                    ),
                )
            _record_keyword_stage('reply_loop', reply_loop_started)

            if not any_reply_scheduled and not keyword_image_job_created:
                if keyword_triggered:
                    logger.info(f'关键词已命中但无可用回复内容: {search_query}')
                else:
                    logger.info(f'关键词搜索无可用回复内容: {search_query}')
            _log_keyword_stage_timings('completed')
            return keyword_triggered or any_reply_scheduled or keyword_image_job_created

        except Exception as e:
            logger.error(f'Error handling keyword search: {e}')
            _log_keyword_stage_timings('exception')
            # 不发送错误消息到Discord，只记录日志
            return keyword_triggered

    async def search_products_by_keyword(self, keyword):
        """根据关键词搜索商品"""
        request_started_at = time.perf_counter()
        try:
            # 设置超时时间
            timeout = aiohttp.ClientTimeout(total=KEYWORD_TEXT_SEARCH_TIMEOUT_SECONDS)
            async with keyword_text_search_concurrency_limit:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # 构建搜索请求
                    search_data = {
                        'query': keyword,
                        'limit': KEYWORD_SEARCH_LIMIT
                    }
                    if self.user_id:
                        search_data['user_id'] = self.user_id
                    if self.user_shops:
                        search_data['user_shops'] = self.user_shops

                    # 调用后端搜索API。限制并发，避免同一条消息被多账号同时处理时压垮 SQLite。
                    async with session.post(f'{config.BACKEND_API_URL}/api/search_similar_text',
                                          json=search_data) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            return result
                        else:
                            response_text = (await resp.text()).strip()
                            logger.error(
                                'Keyword search API error: status=%s elapsed=%.2fs user_id=%s query=%r body=%s',
                                resp.status,
                                time.perf_counter() - request_started_at,
                                self.user_id,
                                str(keyword)[:120],
                                re.sub(r'\s+', ' ', response_text)[:300] or '<empty>',
                            )
                            return None

        except asyncio.TimeoutError:
            logger.warning(
                'Keyword search timeout: timeout=%.2fs elapsed=%.2fs user_id=%s query=%r limit=%s',
                KEYWORD_TEXT_SEARCH_TIMEOUT_SECONDS,
                time.perf_counter() - request_started_at,
                self.user_id,
                str(keyword)[:120],
                KEYWORD_SEARCH_LIMIT,
            )
            return None
        except aiohttp.ClientError as e:
            logger.error(
                'Keyword search network error: type=%s elapsed=%.2fs user_id=%s query=%r error=%s',
                type(e).__name__,
                time.perf_counter() - request_started_at,
                self.user_id,
                str(keyword)[:120],
                e,
            )
            return None
        except Exception as e:
            logger.exception(
                'Error searching products by keyword: type=%s elapsed=%.2fs user_id=%s query=%r',
                type(e).__name__,
                time.perf_counter() - request_started_at,
                self.user_id,
                str(keyword)[:120],
            )
            return None

    async def recognize_image(self, image_data, user_shops=None, threshold=None, query_text=None):
        try:
            # 与图片消息阶段超时保持一致，避免内部请求先于外层保护提前中断。
            timeout = aiohttp.ClientTimeout(total=IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 使用配置的阈值
                # 使用用户个性化阈值，如果没有则使用全局默认值
                api_threshold = _coerce_float(threshold)
                if api_threshold is None:
                    api_threshold = config.DISCORD_SIMILARITY_THRESHOLD

                if threshold is None and self.user_id:
                    try:
                        try:
                            from database import db
                        except ImportError:
                            from .database import db
                        # 异步获取用户设置
                        user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
                        if user_settings and 'discord_similarity_threshold' in user_settings:
                            api_threshold = user_settings['discord_similarity_threshold']
                    except Exception as e:
                        logger.error(f'获取用户相似度设置失败: {e}')

                # 调用后端实时图片检索服务。
                request_url = f'{config.BACKEND_API_URL.replace("/api", "")}/search_similar'
                max_attempts = IMAGE_RECOGNITION_MAX_ATTEMPTS
                retry_delay = IMAGE_RECOGNITION_RETRY_DELAY_SECONDS

                def _build_form_data():
                    form = aiohttp.FormData()
                    form.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
                    form.add_field('threshold', str(api_threshold))
                    form.add_field('limit', '1')
                    if self.user_id:
                        form.add_field('user_id', str(self.user_id))
                    if user_shops:
                        form.add_field('user_shops', json.dumps(user_shops))
                    form.add_field('suppress_search_history', '1')
                    normalized_query_text = re.sub(r'\s+', ' ', str(query_text or '')).strip()
                    if normalized_query_text:
                        form.add_field('query_text', normalized_query_text[:500])
                    return form

                for attempt in range(max_attempts):
                    async with session.post(request_url, data=_build_form_data()) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            return result

                        response_text = (await resp.text()).strip()
                        compact_response_text = re.sub(r'\s+', ' ', response_text)[:300]
                        logger.warning(
                            'recognize_image backend status=%s attempt=%s body=%s',
                            resp.status,
                            attempt + 1,
                            compact_response_text or '<empty>',
                        )
                        if resp.status == 503 and attempt >= max_attempts - 1 and (
                            'search warming up' in compact_response_text
                            or '图搜服务预热中' in compact_response_text
                            or '预热中' in compact_response_text
                        ):
                            logger.warning(
                                'recognize_image search service still warming up after retries; skip image reply for this message'
                            )
                            return None
                        # 后端繁忙/预热时短暂退避，避免一次队列抖动就放弃这张图。
                        if resp.status in {429, 503} and attempt < max_attempts - 1:
                            await asyncio.sleep(retry_delay)
                            retry_delay = min(retry_delay * 1.8, 6.0)
                            continue
                        return None

        except asyncio.TimeoutError:
            logger.error(
                f'Error recognizing image: Request timeout ({IMAGE_RECOGNITION_REQUEST_TIMEOUT_SECONDS:.0f}s)'
            )
            return None
        except aiohttp.ClientError as e:
            logger.error(f'Error recognizing image: Network error - {type(e).__name__}: {e}')
            return None
        except Exception as e:
            logger.error(f'Error recognizing image: {type(e).__name__}: {e}')
            return None

if __name__ == '__main__':
    raise SystemExit('bot.py 已改为由 app.py 统一托管，请运行: python app.py')
