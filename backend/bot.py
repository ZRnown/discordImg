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
from datetime import datetime
from urllib.parse import quote
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
        find_query_keyword_match as _shared_find_query_keyword_match,
        normalize_keyword_search_text as _shared_normalize_keyword_search_text,
        tokenize_keyword_search_text as _shared_tokenize_keyword_search_text,
    )
except ImportError:
    from .keyword_search_terms import (
        build_product_keyword_variants as _shared_build_product_keyword_variants,
        build_query_keyword_candidates as _shared_build_query_keyword_candidates,
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
        split_filter_values,
    )
except ImportError:
    from .message_filter_utils import (
        filters_block_message,
        resolve_keyword_match_limit,
        split_filter_values,
    )
# 全局变量用于多账号机器人管理
bot_clients = []
bot_tasks = []

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


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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

    margin_threshold = _resolve_image_reply_min_top1_margin()
    if margin_threshold <= 0:
        return None

    top1_margin = _extract_image_match_top1_margin(match_context)
    if top1_margin is None:
        return None

    if top1_margin < margin_threshold:
        return (
            f"📷 图片命中分差过小: top1-top2分差 {top1_margin:.3f} < {margin_threshold:.3f}，跳过回复"
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
        return channel

    fetch_channel = getattr(target_client, 'fetch_channel', None)
    if callable(fetch_channel):
        try:
            return await fetch_channel(normalized_channel_id)
        except Exception as exc:
            logger.warning(f"获取子分区频道失败: {normalized_channel_id} | {exc}")
    return None


async def _resolve_message_reply_channel(target_client, message):
    if message is None:
        return None
    message_channel = getattr(message, "channel", None)
    message_channel_id = getattr(message_channel, "id", None)
    return await _resolve_client_channel(target_client, message_channel_id)


async def _resolve_message_thread_id(message):
    if message is None:
        return None

    message_thread_id = getattr(getattr(message, 'thread', None), 'id', None)
    if message_thread_id is not None:
        return message_thread_id

    message_flags = getattr(message, 'flags', None)
    has_thread = bool(getattr(message_flags, 'has_thread', False))
    fetch_thread = getattr(message, 'fetch_thread', None)
    if not has_thread or not callable(fetch_thread):
        return None

    try:
        fetched_thread = await fetch_thread()
    except Exception as exc:
        logger.warning(f"获取消息关联子分区失败: {getattr(message, 'id', None)} | {exc}")
        return None

    return getattr(fetched_thread, 'id', None)


async def _resolve_existing_reply_thread_after_create_failure(
    target_client,
    target_channel,
    message,
):
    message_thread_id = await _resolve_message_thread_id(message)
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


async def resolve_reply_target_channel(
    target_client,
    target_channel,
    message,
    thread_reply_enabled=False,
):
    if not thread_reply_enabled or target_channel is None or message is None:
        return target_channel, False

    if getattr(target_channel, 'parent_id', None) is not None:
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
    current_channel_parent_id = getattr(current_channel, 'parent_id', None)
    if current_channel_parent_id is not None:
        current_thread = await _resolve_client_channel(target_client, getattr(current_channel, 'id', None))
        if current_thread is not None:
            current_thread_id = getattr(current_thread, 'id', None)
            if current_thread_id is not None:
                _store_cached_auto_reply_thread_id(message, current_thread_id)
            return current_thread, True

    message_thread_id = await _resolve_message_thread_id(message)
    if message_thread_id is not None:
        existing_thread = await _resolve_client_channel(target_client, message_thread_id)
        if existing_thread is not None:
            _store_cached_auto_reply_thread_id(message, message_thread_id)
            return existing_thread, True

    create_thread = getattr(target_channel, 'create_thread', None)
    if not callable(create_thread):
        return target_channel, False

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

    logger.warning(
        f"未找到也未能创建消息子区: message={getattr(message, 'id', None)} "
        f"channel={getattr(target_channel, 'id', None)}"
    )
    return target_channel, False


def _build_keyword_window_key(user_id, website_id, guild_id):
    return (
        _coerce_int(user_id, 0),
        _coerce_int(website_id, 0),
        _coerce_int(guild_id, 0),
    )


def get_discord_start_delay_seconds(start_index: int) -> float:
    stagger_seconds = float(
        getattr(config, 'DISCORD_STARTUP_STAGGER_SECONDS', 1.5) or 0.0
    )
    return max(stagger_seconds, 0.0) * max(int(start_index or 0), 0)


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


def _build_product_keyword_variants(raw_value: str):
    return _shared_build_product_keyword_variants(raw_value)


def _find_query_keyword_match(query_keyword_candidates, english_title=None, title=None):
    return _shared_find_query_keyword_match(query_keyword_candidates, english_title, title)


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

# 【新增】AI并发限制：最多同时2个AI推理任务，防止CPU饱和导致Flask阻塞
ai_concurrency_limit = asyncio.Semaphore(2)

# 冷却等待保护：避免在高并发下长时间占用消息处理链路
MAX_COOLDOWN_WAIT_SECONDS = 3.0

# 单条消息各阶段的超时保护，避免某一步卡死拖住后续消息
MESSAGE_FORWARD_TIMEOUT_SECONDS = 15.0
MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS = 45.0
MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS = 90.0
MESSAGE_STAGE_SLOW_SECONDS = 5.0

# 关键词搜索候选上限（覆盖每页200商品的测试场景）
KEYWORD_SEARCH_LIMIT = 600


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

def is_account_on_cooldown(account_id, channel_id, interval):
    """检查账号在指定频道是否在冷却中"""
    key = (int(account_id), str(channel_id))

    last = account_last_sent.get(key, 0)
    time_passed = time.time() - last
    is_cooldown = time_passed < interval

    if is_cooldown:
        logger.info(f"❄️ [冷却中] 账号ID:{account_id} 频道:{channel_id} | 剩余: {interval - time_passed:.1f}秒")

    return is_cooldown

def set_account_cooldown(account_id, channel_id):
    """设置账号在指定频道的冷却时间"""
    key = (int(account_id), str(channel_id))
    account_last_sent[key] = time.time()
    logger.info(f"🔥 [设置冷却] 账号ID:{account_id} 频道:{channel_id} | Key: {key}")

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
logging.basicConfig(level=logging.INFO)

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
    _cache_ttl = 60  # 缓存有效期（秒）

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
            super().__init__(intents=intents)
        except AttributeError:
            # 如果 Intents 不存在，直接初始化（discord.py-self 可能不需要）
            super().__init__()
        self.current_token = None
        self.running = False
        self.account_id = account_id
        self.user_id = user_id  # 用户ID，用于获取个性化设置
        self.user_shops = user_shops  # 用户管理的店铺列表
        self.role = role  # 'listener', 'sender', 'both' - 账号角色
        # DM 会话提醒去重：避免“会话创建 + 首条DM消息”重复推送
        self._dm_alert_cache = {}

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
        current_id = getattr(channel_or_id, 'id', channel_or_id)
        parent = getattr(channel_or_id, 'parent', None)
        parent_id = getattr(channel_or_id, 'parent_id', None) or getattr(parent, 'id', None)
        result = []
        for value in (current_id, parent_id):
            value = str(value or '').strip()
            if value and value not in result:
                result.append(value)
        return result

    async def _run_message_stage_with_timeout(self, message, stage_name, coro, timeout_seconds):
        start_time = time.monotonic()
        try:
            await asyncio.wait_for(coro, timeout=timeout_seconds)
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
        return True

    async def _refresh_channel_cache(self):
        """【新增】刷新频道白名单缓存（60秒TTL）

        从数据库获取所有已绑定的频道ID，更新类级别缓存。
        使用TTL机制避免频繁查询数据库。
        """
        current_time = time.time()

        # 检查缓存是否过期
        if current_time - DiscordBotClient._last_cache_update < DiscordBotClient._cache_ttl:
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
            logger.info(f"商品 {product.get('id')} 回复范围不匹配，跳过网站 {website_config.get('name')}")
            return None

        website_id = website_config.get('id')
        user_settings = await self._get_user_website_settings_safe(website_id)
        website_filters = self._parse_message_filters(user_settings.get('message_filters', '[]') if user_settings else '[]')

        if website_filters and self._filters_block_message(message, website_filters, match_context=match_context):
            logger.info(f"消息被过滤(网站规则): {website_config.get('name')}")
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
                    f for f in (global_filters or []) if f.get('filter_type') == 'image_similarity'
                ]
            except Exception as e:
                logger.error(f"获取全局过滤规则失败: {e}")
                global_image_filters = []

            if global_image_filters and self._filters_block_message(
                message,
                global_image_filters,
                match_context=match_context,
            ):
                logger.info("消息被过滤(全局图片相似度)")
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

            similarity = _coerce_float(match_context.get('similarity')) or 0.0
            base_threshold = _coerce_float(match_context.get('base_threshold'))
            if base_threshold is None:
                base_threshold = config.DISCORD_SIMILARITY_THRESHOLD
            website_threshold = _coerce_float(website_config.get('image_similarity_threshold'))
            threshold_to_use = website_threshold if website_threshold is not None else base_threshold

            if similarity < threshold_to_use:
                logger.info(
                    f"📷 图片相似度 {similarity:.3f} 低于网站阈值 {threshold_to_use:.3f}，跳过回复"
                )
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
            current_configs = await listener_client.get_website_configs_by_channel_async(message.channel.id)
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
            )

        if batch_size <= 0:
            return await self.schedule_reply(
                message,
                product,
                custom_reply,
                match_context,
                website_configs_override=[website_config],
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

                        logger.warning(f"Bark 推送失败: status={response.status}, body={text[:200]}")
                        return
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                logger.error(f"Bark 推送异常: {e}")

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

    async def schedule_reply(
        self,
        message,
        product,
        custom_reply=None,
        match_context=None,
        website_configs_override=None,
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

            # 获取用户设置以确定全局延迟时间
            user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
            global_min_delay = user_settings.get('global_reply_min_delay', 1.0)
            global_max_delay = user_settings.get('global_reply_max_delay', 3.0)

            website_configs = website_configs_override or await self.get_website_configs_by_channel_async(message.channel.id)
            if not website_configs:
                logger.info(f"频道 {message.channel.id} 未绑定网站配置，跳过回复")
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

            if not prevalidated_batch and channel_repeat_window and author_id and repeat_product_ids:
                for pid in repeat_product_ids:
                    if await _is_recent_repeat(author_id, pid, message.channel.id, channel_repeat_window):
                        logger.info(
                            f"🚫 用户重复发送过滤: user={author_id} 商品={pid} 频道={message.channel.id} "
                            f"窗口={int(channel_repeat_window)}秒"
                        )
                        return False

            global_image_filters = []
            if not prevalidated_batch and match_context and match_context.get('type') == 'image':
                try:
                    global_filters = await asyncio.get_event_loop().run_in_executor(None, db.get_message_filters)
                    global_image_filters = [
                        f for f in (global_filters or []) if f.get('filter_type') == 'image_similarity'
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
                    logger.info("消息被过滤(全局图片相似度)")
                    return False
                if not prevalidated_batch and match_context and match_context.get('type') == 'image':
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
                                logger.info(
                                    f"🚫 网站图片过滤命中: 网站 {website_config.get('name')} "
                                    f"规则 {matched_filter.get('filter_id')} 相似度 {sim:.3f} >= {threshold_val:.3f}"
                                )
                                continue
                        except Exception:
                            continue
                if not prevalidated_batch and match_context and match_context.get('type') == 'image':
                    similarity = _coerce_float(match_context.get('similarity')) or 0.0
                    base_threshold = _coerce_float(match_context.get('base_threshold'))
                    if base_threshold is None:
                        base_threshold = config.DISCORD_SIMILARITY_THRESHOLD
                    website_threshold = _coerce_float(website_config.get('image_similarity_threshold'))
                    threshold_to_use = website_threshold if website_threshold is not None else base_threshold

                    if similarity < threshold_to_use:
                        logger.info(
                            f"📷 图片相似度 {similarity:.3f} 低于网站阈值 {threshold_to_use:.3f}，跳过回复"
                        )
                        continue

                active_custom_reply = custom_reply
                if isinstance(custom_reply, dict):
                    per_website_content = custom_reply.get('per_website_content')
                    if isinstance(per_website_content, dict):
                        scoped_content = per_website_content.get(str(website_config.get('id')))
                        if scoped_content:
                            active_custom_reply = dict(custom_reply)
                            active_custom_reply['content'] = scoped_content
                response_content = self._generate_reply_content(
                    product,
                    message.channel.id,
                    active_custom_reply,
                    website_config=website_config
                )
                if response_content is None:
                    logger.info(f"商品 {product.get('id')} 回复范围不匹配，跳过发送")
                    continue

                # 2. 获取数据库配置的发送者 ID
                db_sender_ids = await asyncio.get_event_loop().run_in_executor(
                    None, db.get_website_senders, website_config['id'], self.user_id
                )

                if not db_sender_ids:
                    logger.warning(
                        f"❌ [配置错误] 网站配置 '{website_config.get('name')}' 未绑定任何【发送】账号。请在网站配置中绑定账号。"
                    )
                    continue

                logger.info(f"配置账号ID: {db_sender_ids} | 在线账号ID: {online_client_ids}")

                valid_senders = [uid for uid in db_sender_ids if uid in online_client_ids]

                if not valid_senders:
                    logger.warning("❌ [状态错误] 配置的发送账号均不在线。请检查 Discord 账号连接状态。")
                    continue

                skip_sender_cooldown = bool(
                    isinstance(active_custom_reply, dict)
                    and active_custom_reply.get('skip_sender_cooldown')
                )

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
                rotation_interval = _coerce_int(
                    effective_settings.get('rotation_interval', website_config.get('rotation_interval', 180)),
                    _coerce_int(website_config.get('rotation_interval', 180), 180),
                )

                if user_website_settings:
                    logger.info(
                        f"📋 使用用户级别设置: rotation_interval={rotation_interval}秒, "
                        f"rotation_enabled={rotation_enabled}, reply_mode={reply_mode}"
                    )
                    if (
                        not prevalidated_batch
                        and website_filters
                        and self._filters_block_message(message, website_filters, match_context=match_context)
                    ):
                        logger.info(f"消息被过滤(网站规则): {website_config.get('name')}")
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

                if skip_sender_cooldown:
                    available_senders = list(valid_senders)
                else:
                    available_senders = [
                        uid for uid in valid_senders
                        if not is_account_on_cooldown(uid, message.channel.id, rotation_interval)
                    ]

                if not available_senders and not skip_sender_cooldown:
                    now_ts = time.time()
                    wait_candidates = []
                    channel_id_str = str(message.channel.id)
                    for uid in valid_senders:
                        key = (int(uid), channel_id_str)
                        last_sent = account_last_sent.get(key, 0)
                        remain = rotation_interval - (now_ts - last_sent)
                        if remain > 0:
                            wait_candidates.append(remain)

                    wait_seconds = min(wait_candidates) if wait_candidates else 0.0
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
                        available_senders = [
                            uid for uid in valid_senders
                            if not is_account_on_cooldown(uid, message.channel.id, rotation_interval)
                        ]

                if not available_senders:
                    logger.warning(
                        f"⏳ [重试后仍冷却] 频道 {message.channel.id} 在线账号 ({len(valid_senders)}个) "
                        f"均不可用，跳过当前网站配置"
                    )
                    continue

                if rotation_enabled:
                    selected_id = random.choice(available_senders)
                else:
                    available_set = set(available_senders)
                    selected_id = next((uid for uid in db_sender_ids if uid in available_set), None)
                    if selected_id is None:
                        selected_id = available_senders[0]

                target_client = next((c for c in bot_clients if c.account_id == selected_id), None)
                if not target_client:
                    logger.warning("❌ 逻辑异常：有可用发送账号但无法找到客户端")
                    continue

                logger.info(
                    f"✅ 本次选中发送账号: {target_client.user.name if target_client else selected_id} (ID: {selected_id})"
                )

                try:
                    target_channel = target_client.get_channel(message.channel.id)

                    if target_channel:
                        async with target_channel.typing():
                            await asyncio.sleep(random.uniform(min_delay, max_delay))

                        # 【关键修复】
                        # 不要使用 message.reply()，因为 message 绑定的是监听者(Listener)客户端
                        # 必须用 target_channel.send(..., reference=message) 才会使用 target_client(Sender) 的 token
                        try:
                            # === 1. 收集所有要发送的图片文件 ===
                            files = []
                            image_download_timeout = aiohttp.ClientTimeout(total=10)

                            # 检查是否是自定义模式，且有图片
                            skip_images = bool(active_custom_reply and active_custom_reply.get('skip_images'))
                            is_custom_mode = active_custom_reply and (
                                active_custom_reply.get('reply_type') == 'custom_only' or
                                active_custom_reply.get('reply_type') == 'text'
                            )
                            if is_custom_mode and not _should_send_product_custom_images(
                                active_custom_reply,
                                product,
                                message.channel.id,
                                website_config=website_config,
                            ):
                                skip_images = True

                            if is_custom_mode and not skip_images:
                                # 获取图片信息
                                # 注意：如果是从 search_similar_text 返回的 product，字段名可能已经格式化
                                # 需要兼容处理

                                # 1. 尝试获取自定义图片链接
                                custom_urls = product.get('customImageUrls', []) or product.get('custom_image_urls', [])
                                if isinstance(custom_urls, str):
                                    try:
                                        custom_urls = json.loads(custom_urls)
                                    except Exception:
                                        custom_urls = []

                                image_source = product.get('imageSource') or product.get('image_source') or 'product'

                                # 收集图片文件（Discord限制最多10个文件）
                                if image_source == 'custom' and custom_urls:
                                    for url in custom_urls[:10]:  # 限制最多10张
                                        if len(files) >= 10:
                                            break
                                        try:
                                            async with aiohttp.ClientSession(timeout=image_download_timeout) as session:
                                                async with session.get(url) as resp:
                                                    if resp.status == 200:
                                                        data = await resp.read()
                                                        filename = url.split('/')[-1] or 'image.jpg'
                                                        files.append(discord.File(io.BytesIO(data), filename))
                                        except Exception as e:
                                            logger.error(f"下载自定义图片失败: {e}")

                                elif image_source == 'upload':
                                    # 处理上传的自定义回复图片
                                    pid = product.get('id')

                                    # 从 uploaded_reply_images 字段获取上传的图片文件名列表
                                    uploaded_filenames = product.get('uploaded_reply_images', [])
                                    if isinstance(uploaded_filenames, str):
                                        try:
                                            uploaded_filenames = json.loads(uploaded_filenames)
                                        except Exception:
                                            # 如果解析失败，且它本身就是列表，则保持原样，否则置空
                                            uploaded_filenames = uploaded_filenames if isinstance(uploaded_filenames, list) else []

                                    if pid and uploaded_filenames:
                                        # 使用新的API端点获取上传的自定义回复图片
                                        for filename in uploaded_filenames[:10]:  # 限制最多10张
                                            if len(files) >= 10:
                                                break
                                            img_url = f"{config.BACKEND_API_URL}/api/custom_reply_image/{pid}/{filename}"
                                            try:
                                                async with aiohttp.ClientSession(timeout=image_download_timeout) as session:
                                                    async with session.get(img_url) as resp:
                                                        if resp.status == 200:
                                                            data = await resp.read()
                                                            files.append(discord.File(io.BytesIO(data), filename))
                                            except Exception as e:
                                                logger.error(f"下载上传的自定义回复图片失败: {e}")

                                elif image_source == 'product':
                                    # 处理商品图集中的图片
                                    pid = product.get('id')
                                    indexes = product.get('selectedImageIndexes', []) or product.get('custom_reply_images', [])

                                    if isinstance(indexes, str):
                                        try:
                                            indexes = json.loads(indexes)
                                        except Exception:
                                            indexes = []

                                    if pid and indexes:
                                        image_path_map = {}
                                        try:
                                            product_images = db.get_product_images(pid)
                                            image_path_map = {
                                                img.get('image_index'): img.get('image_path')
                                                for img in product_images
                                            }
                                        except Exception as e:
                                            logger.error(f"获取商品图片路径失败: {e}")

                                        # 优先使用本地图片路径，失败再回退到HTTP获取
                                        for idx in indexes[:10]:  # 限制最多10张
                                            if len(files) >= 10:
                                                break
                                            idx_key = idx
                                            try:
                                                idx_key = int(idx)
                                            except (TypeError, ValueError):
                                                idx_key = idx

                                            image_path = image_path_map.get(idx_key)
                                            if image_path and os.path.exists(image_path):
                                                files.append(discord.File(image_path, f"{pid}_{idx_key}.jpg"))
                                                continue

                                            img_url = f"{config.BACKEND_API_URL}/api/image/{pid}/{idx_key}"
                                            try:
                                                async with aiohttp.ClientSession(timeout=image_download_timeout) as session:
                                                    async with session.get(img_url) as resp:
                                                        if resp.status == 200:
                                                            data = await resp.read()
                                                            files.append(discord.File(io.BytesIO(data), f"{pid}_{idx_key}.jpg"))
                                            except Exception as e:
                                                logger.error(f"下载商品图片失败: {e}")

                            # === 2. 发送文字和所有图片（合并为一条消息） ===
                            if not response_content and not files:
                                logger.warning(
                                    f"⚠️ 无可发送内容: 商品ID={product.get('id')}，未生成文字且无图片"
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
                                send_kwargs['reference'] = message
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

                            await target_channel.send(**send_kwargs)
                            sent_any = True

                            if prevalidated_batch:
                                for repeat_user_id, repeat_pid in batch_repeat_records:
                                    await _record_repeat(repeat_user_id, repeat_pid, message.channel.id)
                            elif author_id and repeat_product_ids:
                                for pid in repeat_product_ids:
                                    await _record_repeat(author_id, pid, message.channel.id)

                            if (
                                not skip_sender_cooldown
                                and hasattr(target_client, 'account_id')
                                and target_client.account_id
                            ):
                                set_account_cooldown(target_client.account_id, message.channel.id)

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
                                f"✅ [回复成功] {target_client.user.name} -> {author_label} | 频道: {message.channel.name}: "
                                f"{reply_preview} | 商品ID: {product.get('id')}"
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
                                    await target_channel.send(response_content, **fallback_kwargs)
                                    fallback_sent = True
                                except Exception as fallback_error:
                                    logger.error(f"文本兜底发送失败: {fallback_error}")
                                    continue
                            elif files:
                                logger.error(
                                    f"图片消息发送失败且无法复用附件重试，跳过本次发送。商品ID: {product.get('id')}"
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
                                set_account_cooldown(target_client.account_id, message.channel.id)
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
                                f"✅ [发送成功] {target_client.user.name} -> {author_label} | 频道: {message.channel.name}: "
                                f"{reply_preview} | 商品ID: {product.get('id')}"
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

        except Exception as e:
            logger.error(f"❌ 严重错误: {e}")
            return sent_any

        return sent_any

    def _generate_reply_content(self, product, channel_id, custom_reply=None, website_config=None):
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

            if force_link_only:
                return response_url

            def apply_template(template: str, append_link: bool) -> str:
                if not template:
                    return ''
                if '{url}' in template:
                    return template.replace('{url}', response_url).strip()
                if append_link:
                    return f"{template}\n{response_url}".strip()
                return template.strip()

            # 1) 商品级自定义回复（优先级最高）
            if is_product_custom or force_custom_reply:
                reply_type = custom_reply.get('reply_type')
                content = custom_reply.get('content', '') or ''
                if reply_type == 'custom_only' or reply_type == 'text':
                    return apply_template(content, append_link=False)
                if reply_type == 'text_and_link':
                    return apply_template(content, append_link=True)

            # 2) 网站级回复模板（默认 {url}）
            if website_config:
                website_template = (website_config.get('reply_template') or '{url}').strip()
                if website_template:
                    return apply_template(website_template, append_link=True)

            # 3) 原有自定义回复（全局随机）
            if custom_reply and not is_product_custom:
                reply_type = custom_reply.get('reply_type')
                content = custom_reply.get('content', '') or ''

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

    def _should_filter_message(self, message):
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
                                logger.info(
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
                        logger.info(f'消息被过滤: 包含 "{filter_value}"')
                        return True
                elif filter_type == 'starts_with':
                    if message_content.startswith(filter_value):
                        logger.info(f'消息被过滤: 以 "{filter_value}" 开头')
                        return True
                elif filter_type == 'ends_with':
                    if message_content.endswith(filter_value):
                        logger.info(f'消息被过滤: 以 "{filter_value}" 结尾')
                        return True
                elif filter_type == 'regex':
                    try:
                        if re.search(filter_value, message_content, re.IGNORECASE):
                            logger.info(f'消息被过滤: 匹配正则 "{filter_value}"')
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
                                logger.info(
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
                            logger.info(f'消息被过滤: 用户 {message.author.name} (ID: {sender_id}) 在过滤列表中')
                            return True
                elif filter_type == 'role_id':
                    role_ids = split_filter_values(filter_value)
                    if role_ids and getattr(message, 'guild', None):
                        author_roles = getattr(message.author, 'roles', []) or []
                        author_role_ids = {str(role.id) for role in author_roles if getattr(role, 'id', None) is not None}
                        if author_role_ids.intersection(set(role_ids)):
                            logger.info(f'消息被过滤: 用户 {message.author.name} 命中身份组过滤')
                            return True
                elif filter_type == 'image':
                    if self._message_has_image(message):
                        logger.info('消息被过滤: 图片消息')
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
                            logger.info(f'消息被过滤: 用户 {message.author.name} 在黑名单中')
                            return True

                # 检查关键词过滤
                keyword_filters = user_settings.get('keyword_filters', '')
                if keyword_filters:
                    filter_keywords = [k.strip().lower() for k in keyword_filters.split(',') if k.strip()]

                    for keyword in filter_keywords:
                        if keyword in message_content:
                            logger.info(f'消息被过滤: 包含关键词 "{keyword}"')
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
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            bound_channels = await asyncio.get_event_loop().run_in_executor(None, db.get_all_bound_channel_ids)
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

        # 更新数据库中的账号状态为在线
        try:
            try:
                from database import db
            except ImportError:
                from .database import db
            if hasattr(self, 'account_id'):
                db.update_account_status(self.account_id, 'online')
                logger.info(f'账号 {self.account_id} 状态已更新为在线')
        except Exception as e:
            logger.error(f'更新账号状态失败: {e}')

    async def on_message(self, message):
        if not self.running:
            return

        # 忽略自己的消息
        if message.author == self.user:
            return

        # 忽略机器人和webhook的消息
        if message.author.bot or message.webhook_id:
            return

        # 他人发起私信（DM）立即通知；DM 不进入自动回复链路
        if getattr(message, "guild", None) is None:
            try:
                await self._notify_dm_interaction_if_needed(message)
            except Exception as e:
                logger.error(f"处理私信 Bark 通知失败: {e}")
            return

        # 屏蔽活动通知/系统消息以及 @everyone/@here 广播
        if self._should_ignore_mass_or_activity_message(message):
            return

        # 1. 所有账号都可触发互动通知（无需频道绑定）
        try:
            await self._notify_direct_interaction_if_needed(message)
        except Exception as e:
            logger.error(f"处理 @/回复 Bark 通知失败: {e}")

        # 2. 纯 sender 账号只负责互动通知，不参与自动回复链路
        if self.role == 'sender':
            return

        # 3. 仅监听角色进入自动回复链路（sender-only 绑定不会进入）
        try:
            listener_allowed, _ = await self._is_account_bound_in_channel(message.channel.id)
            if not listener_allowed:
                return
        except Exception as e:
            logger.error(f"检查监听权限失败: {e}")
            return

        # 4. 忽略 @别人的信息（避免进入商品回复链路）
        if message.mentions:
            return

        # 5. 忽略回复别人的信息（避免进入商品回复链路）
        if message.reference is not None:
            return

        try:
            if not mark_message_as_processed(message.id, self.user_id):
                logger.info(f"消息 {message.id} 已被其他(合法的)Bot处理，跳过")
                return
        except Exception as e:
            logger.error(f"消息去重检查失败: {e}")
            return

        # 6. 触发内容过滤规则
        if self._should_filter_message(message):
            return

        logger.info(f'📨 [接收] 账号:{self.user.name} | 频道:{message.channel.name} | 内容: "{message.content[:50]}..."')

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

        # 处理关键词搜索
        if keyword_reply_enabled:
            await self._run_message_stage_with_timeout(
                message,
                'keyword_search',
                self.handle_keyword_search(message),
                MESSAGE_KEYWORD_SEARCH_TIMEOUT_SECONDS,
            )

        # 处理图片
        if image_reply_enabled and message.attachments:
            for attachment in message.attachments:
                content_type = (getattr(attachment, 'content_type', '') or '').lower()
                filename = (getattr(attachment, 'filename', '') or '').lower()
                is_image = False
                if content_type.startswith('image/'):
                    is_image = True
                elif filename.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.heic', '.heif')):
                    is_image = True

                if is_image:
                    logger.debug(f"📷 检测到图片，开始处理: {attachment.filename}")
                    await self._run_message_stage_with_timeout(
                        message,
                        f'image_reply:{attachment.filename}',
                        self.handle_image(message, attachment),
                        MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS,
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

            message = await channel.fetch_message(message_id)
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
            logger.error(f"处理表情互动 Bark 通知失败: {e}")

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
            logger.error(f"处理好友请求 Bark 通知失败: {e}")

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
            logger.error(f"处理添加好友 Bark 通知失败: {e}")

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

    async def handle_image(self, message, attachment):
        try:
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
                return  # 静默失败，不发送错误消息

            # 【新增】AI并发限制：最多同时2个AI推理任务
            # 使用Semaphore控制并发，防止CPU饱和导致Flask主线程阻塞
            async with ai_concurrency_limit:
                logger.debug(f"🔒 获取AI并发锁，当前等待队列: {ai_concurrency_limit._value}")

                # 传入用户店铺权限，避免 A 店铺命中结果串到 B 店铺
                scoped_user_shops = self.user_shops if self.user_shops else None
                result = await self.recognize_image(
                    image_data,
                    user_shops=scoped_user_shops,
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
                            return
                except Exception:
                    pass

            if result and result.get('success') and result.get('results'):
                # 获取最佳匹配结果
                best_match = result['results'][0]
                similarity = best_match.get('similarity', 0)

                # 获取用户个性化相似度阈值，如果没有则使用全局默认值
                user_threshold = config.DISCORD_SIMILARITY_THRESHOLD  # 默认值
                if self.user_id:
                    try:
                        try:
                            from database import db
                        except ImportError:
                            from .database import db
                        # 异步获取用户设置
                        user_settings = await asyncio.get_event_loop().run_in_executor(None, db.get_user_settings, self.user_id)
                        if user_settings:
                            if user_settings.get('discord_similarity_threshold') is not None:
                                user_threshold = user_settings['discord_similarity_threshold']
                    except Exception as e:
                        logger.error(f'获取用户相似度设置失败: {e}')

                logger.debug(f'最佳匹配相似度: {similarity:.4f}, 用户阈值: {user_threshold:.4f}')

                product = best_match.get('product', {})
                product_title = (product.get('title') or '').strip()
                logger.info(
                    f'📷 图片匹配: 商品 {product.get("id")} {product_title} | 相似度 {similarity:.2f} | 频道: {message.channel.name}'
                )

                product_rule_enabled = product.get('ruleEnabled', True)
                if isinstance(product_rule_enabled, str):
                    product_rule_enabled = product_rule_enabled.strip().lower() not in {'0', 'false', 'no', 'off'}
                elif isinstance(product_rule_enabled, (int, float)):
                    product_rule_enabled = bool(product_rule_enabled)

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

                custom_reply = None
                image_source = product.get('imageSource') or product.get('image_source') or 'product'
                has_custom_images = False

                if image_source == 'upload':
                    uploaded_imgs = _coerce_list(product.get('uploaded_reply_images'))
                    product['uploaded_reply_images'] = uploaded_imgs
                    has_custom_images = bool(uploaded_imgs)
                elif image_source == 'custom':
                    custom_urls = _coerce_list(product.get('customImageUrls') or product.get('custom_image_urls'))
                    if custom_urls:
                        product['customImageUrls'] = custom_urls
                    has_custom_images = bool(custom_urls)
                elif image_source == 'product':
                    selected_indexes = _coerce_list(product.get('selectedImageIndexes') or product.get('custom_reply_images'))
                    if selected_indexes:
                        product['selectedImageIndexes'] = selected_indexes
                    has_custom_images = bool(selected_indexes)

                if not product_rule_enabled or has_custom_images:
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

                await self.schedule_reply(
                    message,
                    product,
                    custom_reply,
                    match_context={
                        'type': 'image',
                        'similarity': similarity,
                        'base_threshold': user_threshold,
                        'website_filter_matches': blocked_website_filter_matches
                    }
                )

                logger.debug(f'图片识别完成，相似度: {similarity:.4f}')

        except Exception as e:
            logger.error(f'Error handling image: {e}')
            # 不发送错误消息到Discord，只记录日志

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

                    await target_channel.send(embed=forward_embed)
                    logger.info(f"转发了包含关键词的消息: {message.content[:100]}...")
                else:
                    logger.warning(f"找不到目标频道: {config.FORWARD_TARGET_CHANNEL_ID}")

        except Exception as e:
            logger.error(f'Error handling keyword forward: {e}')

    async def handle_keyword_search(self, message):
        """处理关键词商品搜索"""
        try:
            # 只处理纯文字消息（不包含图片的）
            if not message.content or message.attachments:
                return

            search_query = message.content.strip()
            if not search_query:
                return

            # 移除自定义表情，避免表情ID/名称误触发关键词
            cleaned_query = re.sub(r'<a?:\w+:\d+>', ' ', search_query)
            cleaned_query = re.sub(r'\s+', ' ', cleaned_query).strip()
            if not cleaned_query:
                return
            if not re.search(r'\w', cleaned_query):
                return
            search_query = cleaned_query

            if _should_ignore_keyword_search_query(search_query):
                return

            # 调用搜索API
            result = await self.search_products_by_keyword(search_query)

            all_products = []
            if result and result.get('success') and result.get('products'):
                all_products = result['products']

            if not all_products:
                logger.info(f'关键词搜索无结果: {search_query}')
                return

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
                        logger.info(f'关键词搜索结果被店铺权限过滤: {search_query}')
                        return

            query_normalized = _normalize_keyword_search_text(search_query)
            query_keyword_candidates = _build_query_keyword_candidates(query_normalized)

            def _product_matches_query(product):
                reason = _find_query_keyword_match(
                    query_keyword_candidates,
                    product.get('english_title') or product.get('englishTitle') or '',
                    product.get('title') or '',
                )
                return bool(reason), reason

            matched_products = []
            match_reasons = {}
            for product in all_products:
                matched, reason = _product_matches_query(product)
                if matched:
                    matched_products.append(product)
                    product_id = product.get('id')
                    if reason and product_id is not None:
                        match_reasons[product_id] = reason
            if not matched_products:
                logger.info(f'关键词搜索无精确匹配: {search_query}')
                return

            matched_keyword_set = {
                str(reason.get('canonical_keyword')).strip()
                for reason in match_reasons.values()
                if str(reason.get('canonical_keyword') or '').strip()
            }

            db = None
            global_filters = []
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

            legacy_global_keyword_match_limit = max(
                0,
                _coerce_int((user_settings or {}).get('keyword_match_limit', 0), 0),
            )
            global_keyword_match_limit = resolve_keyword_match_limit(
                global_filters,
                fallback_limit=legacy_global_keyword_match_limit,
            )

            logger.info(f'关键词搜索成功: "{search_query}" -> 匹配 {len(matched_products)} 个商品')
            for product in matched_products:
                product_id = product.get('id')
                reason = match_reasons.get(product_id)
                if not reason:
                    continue
                rule_desc = '关键词出现在消息中'
                logger.info(
                    f'关键词命中: query="{search_query}" | 商品 {product_id} | 命中词 "{reason.get("phrase")}" '
                    f'({reason.get("source")}) | 原因: {rule_desc}'
                )

            # 检查频道是否绑定了网站配置（必须绑定才能回复）
            website_configs = await self.get_website_configs_by_channel_async(message.channel.id)
            if not website_configs:
                logger.info(f"频道 {message.channel.id} 未绑定网站配置，跳过关键词回复")
                return

            user_website_settings_map = {}
            if self.user_id:
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

            # 单个商品时保留原有发送逻辑（支持自定义图片）
            if len(matched_products) == 1:
                product = matched_products[0]

                # === 关键修复逻辑 ===
                # 检查规则是否启用（兼容字符串/数字）
                # 注意：后端API返回的 autoReplyEnabled 即 ruleEnabled
                rule_enabled = product.get('autoReplyEnabled', product.get('ruleEnabled', True))
                if isinstance(rule_enabled, str):
                    rule_enabled = rule_enabled.strip().lower() not in {'0', 'false', 'no', 'off'}
                elif isinstance(rule_enabled, (int, float)):
                    rule_enabled = bool(rule_enabled)

                custom_reply = None

                # 检查是否配置了自定义图片
                def _coerce_list(value):
                    if not value:
                        return []
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                        except json.JSONDecodeError:
                            return []
                        return parsed if isinstance(parsed, list) else []
                    if isinstance(value, list):
                        return value
                    return []

                has_custom_images = False
                image_source = product.get('imageSource') or product.get('image_source')

                if image_source == 'upload':
                    uploaded_imgs = _coerce_list(product.get('uploaded_reply_images'))
                    product['uploaded_reply_images'] = uploaded_imgs
                    has_custom_images = bool(uploaded_imgs)
                elif image_source == 'custom':
                    custom_urls = _coerce_list(product.get('customImageUrls')) or _coerce_list(product.get('custom_image_urls'))
                    if custom_urls:
                        product['customImageUrls'] = custom_urls
                    has_custom_images = bool(custom_urls)
                elif image_source == 'product':
                    selected_indexes = _coerce_list(product.get('selectedImageIndexes')) or _coerce_list(product.get('custom_reply_images'))
                    if selected_indexes:
                        product['selectedImageIndexes'] = selected_indexes
                    has_custom_images = bool(selected_indexes)

                # 如果规则禁用了，或者配置了自定义图片，都需要创建 custom_reply
                if not rule_enabled or has_custom_images:
                    # 构造 custom_reply 对象供 schedule_reply 使用
                    custom_text = (product.get('custom_reply_text') or '').strip()

                    # 即使没有文本，只要是要发图片，也需要传递 custom_reply 信号
                    # schedule_reply 会进一步处理图片逻辑
                    custom_reply = {
                        'reply_type': 'text' if custom_text else 'custom_only',  # custom_only 表示不发默认链接
                        'content': custom_text,
                        # 传递图片信息供 schedule_reply 内部处理
                        'product_data': product
                    }
                    if not rule_enabled:
                        logger.info(f"商品 {product['id']} 规则已禁用，准备发送自定义回复")
                    elif has_custom_images:
                        logger.info(f"商品 {product['id']} 配置了自定义图片，准备发送自定义回复")

                for website_config in website_configs:
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
                    if website_keyword_match_limit > 0 and len(matched_keyword_set) > website_keyword_match_limit:
                        logger.info(
                            f'关键词搜索命中过多，跳过网站 {website_config.get("id")}: query="{search_query}" | '
                            f'命中关键词 {len(matched_keyword_set)} 个 | 上限 {website_keyword_match_limit}'
                        )
                        continue
                    self._start_keyword_reply_background_task(
                        self._enqueue_or_dispatch_keyword_reply(
                            message,
                            product,
                            custom_reply,
                            website_config,
                        ),
                        task_name=(
                            f"keyword-single website={website_config.get('id')} "
                            f"channel={getattr(message.channel, 'id', 'unknown')}"
                        ),
                    )
                return

            # 多商品合并回复
            reply_entries = []

            for product in matched_products:
                if len(reply_entries) >= 5:
                    break

                rule_enabled = product.get('autoReplyEnabled', product.get('ruleEnabled', True))
                if isinstance(rule_enabled, str):
                    rule_enabled = rule_enabled.strip().lower() not in {'0', 'false', 'no', 'off'}
                elif isinstance(rule_enabled, (int, float)):
                    rule_enabled = bool(rule_enabled)

                custom_reply = None
                if not rule_enabled:
                    custom_text = (product.get('custom_reply_text') or '').strip()
                    custom_reply = {
                        'reply_type': 'text' if custom_text else 'custom_only',
                        'content': custom_text,
                        'product_data': product,
                        'skip_images': True
                    }

                reply_entries.append({
                    'product': product,
                    'custom_reply': custom_reply
                })

            per_website_content = {}
            per_website_reply_modes = {}
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
            for website_config in website_configs:
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
                if website_keyword_match_limit > 0 and len(matched_keyword_set) > website_keyword_match_limit:
                    logger.info(
                        f'关键词搜索命中过多，跳过网站 {website_config.get("id")}: query="{search_query}" | '
                        f'命中关键词 {len(matched_keyword_set)} 个 | 上限 {website_keyword_match_limit}'
                    )
                    continue
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
                per_website_reply_modes[str(website_config.get('id'))] = reply_mode
                website_lines = []
                for entry in reply_entries:
                    reply_text = self._generate_reply_content(
                        entry['product'],
                        message.channel.id,
                        entry['custom_reply'],
                        website_config=website_config
                    )
                    if reply_text:
                        website_lines.append(reply_text)
                if website_lines:
                    per_website_content[str(website_config.get('id'))] = _build_multi_reply_content(
                        author_id=getattr(message.author, 'id', None),
                        reply_contents=website_lines,
                        reply_mode=reply_mode,
                    )

            if per_website_content:
                base_product = reply_entries[0]['product']
                max_lines = max(content.count('\n') + 1 for content in per_website_content.values())
                logger.info(f"发送合并回复，最多包含 {max_lines} 条内容")
                repeat_product_ids = [
                    entry['product'].get('id')
                    for entry in reply_entries
                    if entry['product'].get('id')
                ]

                for website_config in website_configs:
                    website_key = str(website_config.get('id'))
                    website_content = per_website_content.get(website_key)
                    if not website_content:
                        continue
                    reply_mode = per_website_reply_modes.get(website_key, 'rotation')
                    agg_custom_reply = {
                        'reply_type': 'custom_only',
                        'content': website_content,
                        'product_data': base_product,
                        'skip_images': True,
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
                        ),
                        task_name=(
                            f"keyword-aggregate website={website_config.get('id')} "
                            f"channel={getattr(message.channel, 'id', 'unknown')}"
                        ),
                    )
            else:
                logger.info(f'关键词搜索无可用回复内容: {search_query}')

        except Exception as e:
            logger.error(f'Error handling keyword search: {e}')
            # 不发送错误消息到Discord，只记录日志

    async def search_products_by_keyword(self, keyword):
        """根据关键词搜索商品"""
        try:
            # 设置超时时间
            timeout = aiohttp.ClientTimeout(total=10)  # 10秒超时
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

                # 调用后端搜索API
                async with session.post(f'{config.BACKEND_API_URL}/api/search_similar_text',
                                      json=search_data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result
                    else:
                        logger.error(f'Keyword search API error: {resp.status}')
                        return None

        except Exception as e:
            logger.error(f'Error searching products by keyword: {e}')
            return None

    async def recognize_image(self, image_data, user_shops=None):
        try:
            # 增加超时时间，首轮商品缓存预热或大 catalog 检索可能需要更长时间
            timeout = aiohttp.ClientTimeout(total=30)  # 30秒超时
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 准备图片数据
                form_data = aiohttp.FormData()
                form_data.add_field('image', image_data, filename='image.jpg', content_type='image/jpeg')
                # 使用配置的阈值
                # 使用用户个性化阈值，如果没有则使用全局默认值
                api_threshold = config.DISCORD_SIMILARITY_THRESHOLD
                if self.user_id:
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

                form_data.add_field('threshold', str(api_threshold))
                form_data.add_field('limit', '1')  # Discord只返回最相似的一个结果
                if self.user_id:
                    form_data.add_field('user_id', str(self.user_id))

                # 如果指定了用户店铺权限，添加到请求中
                if user_shops:
                    form_data.add_field('user_shops', json.dumps(user_shops))

                # 调用后端实时图片检索服务。
                async with session.post(f'{config.BACKEND_API_URL.replace("/api", "")}/search_similar', data=form_data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result
                    else:
                        return None

        except asyncio.TimeoutError:
            logger.error('Error recognizing image: Request timeout (30s)')
            return None
        except aiohttp.ClientError as e:
            logger.error(f'Error recognizing image: Network error - {type(e).__name__}: {e}')
            return None
        except Exception as e:
            logger.error(f'Error recognizing image: {type(e).__name__}: {e}')
            return None

async def get_all_accounts_from_backend():
    """从后端 API 获取所有可用的 Discord 账号"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'{config.BACKEND_API_URL}/accounts') as resp:
                if resp.status == 200:
                    result = await resp.json()
                    accounts = result.get('accounts', [])
                    # 只返回状态为online的账号
                    return [account for account in accounts if account.get('status') == 'online']
    except Exception as e:
        logger.error(f'Failed to get accounts from backend: {e}')
    return []

async def bot_loop(client):
    """主循环，定期检查并重连"""
    while True:
        try:
            token = await get_token_from_backend()
            if token:
                if not client.is_ready():
                    logger.info('Starting Discord bot with token from database...')
                    await client.start(token, reconnect=True)
                elif client.current_token != token:
                    logger.info('Token changed, reconnecting...')
                    await client.close()
                    await asyncio.sleep(2)
                    client.current_token = token
                    await client.start(token, reconnect=True)
            else:
                logger.warning('No active token found in database, waiting...')
                if client.is_ready():
                    await client.close()
                client.current_token = None

        except Exception as e:
            logger.error(f'Bot loop error: {e}')
            if client.is_ready():
                await client.close()

        # 等待 30 秒后再次检查
        await asyncio.sleep(30)

async def start_multi_bot_loop():
    """启动多账号机器人循环，定期检查账号状态"""
    global bot_clients, bot_tasks

    while True:
        try:
            # 获取当前所有账号
            accounts = await get_all_accounts_from_backend()
            current_account_ids = {account['id'] for account in accounts}

            # 停止已删除账号的机器人
            to_remove = []
            for i, client in enumerate(bot_clients):
                if client.account_id not in current_account_ids:
                    logger.info(f'停止已删除账号的机器人: {client.account_id}')
                    try:
                        if not client.is_closed():
                            await client.close()
                    except Exception as e:
                        logger.error(f'停止机器人时出错: {e}')

                    # 取消对应的任务
                    if i < len(bot_tasks) and bot_tasks[i] and not bot_tasks[i].done():
                        bot_tasks[i].cancel()

                    to_remove.append(i)

            # 从列表中移除已停止的机器人
            for i in reversed(to_remove):
                bot_clients.pop(i)
                if i < len(bot_tasks):
                    bot_tasks.pop(i)

            # 为新账号启动机器人
            existing_account_ids = {client.account_id for client in bot_clients}
            for account in accounts:
                account_id = account['id']
                if account_id not in existing_account_ids:
                    token = account['token']
                    username = account.get('username', f'account_{account_id}')

                    logger.info(f'启动新账号机器人: {username}')

                    # 创建机器人实例
                    client = DiscordBotClient(account_id=account_id)

                    # 启动机器人
                    try:
                        task = asyncio.create_task(client.start(token, reconnect=True))
                        bot_clients.append(client)
                        bot_tasks.append(task)
                        logger.info(f'机器人启动成功: {username}')
                    except Exception as e:
                        logger.error(f'启动机器人失败 {username}: {e}')

            # 等待一段时间后再次检查
            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f'多账号机器人循环错误: {e}')
            await asyncio.sleep(30)

async def main():
    client = DiscordBotClient()

    # 启动主循环
    await bot_loop(client)

if __name__ == '__main__':
    asyncio.run(main())
