import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend import bot as bot_module
from backend.bot import (
    MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS,
    _auto_reply_thread_ids,
    _get_image_recognition_request_timeout_seconds,
    _resolve_cooldown_channel_id,
    resolve_reply_target_channel,
)


class BotTimeoutHelpersTestCase(unittest.TestCase):
    def test_image_recognition_request_timeout_tracks_stage_timeout(self):
        self.assertEqual(
            _get_image_recognition_request_timeout_seconds(
                MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS
            ),
            85.0,
        )

    def test_image_recognition_request_timeout_never_drops_below_floor(self):
        self.assertEqual(
            _get_image_recognition_request_timeout_seconds(20),
            30.0,
        )

    def test_build_discord_client_runtime_options_disable_startup_chunking_by_default(
        self,
    ):
        with patch.object(
            bot_module.config,
            "DISCORD_CHUNK_GUILDS_AT_STARTUP",
            True,
            create=True,
        ), patch.object(
            bot_module.config,
            "DISCORD_GUILD_SUBSCRIPTIONS",
            False,
            create=True,
        ), patch.object(
            bot_module.config,
            "DISCORD_HEARTBEAT_TIMEOUT",
            120.0,
            create=True,
        ), patch.object(
            bot_module.config,
            "DISCORD_MAX_MESSAGES",
            200,
            create=True,
        ):
            options = bot_module.build_discord_client_runtime_options()

            self.assertFalse(options["chunk_guilds_at_startup"])
            self.assertFalse(options["guild_subscriptions"])
            self.assertEqual(options["heartbeat_timeout"], 120.0)
            self.assertEqual(options["max_messages"], 200)
            if hasattr(bot_module.discord, "MemberCacheFlags"):
                self.assertEqual(
                    options["member_cache_flags"],
                    bot_module.discord.MemberCacheFlags.none(),
                )

    def test_get_discord_start_delay_seconds_uses_configured_stagger(self):
        with patch.object(
            bot_module.config,
            "DISCORD_STARTUP_STAGGER_SECONDS",
            1.75,
            create=True,
        ):
            self.assertEqual(bot_module.get_discord_start_delay_seconds(0), 0.0)
            self.assertEqual(bot_module.get_discord_start_delay_seconds(1), 1.75)
            self.assertEqual(bot_module.get_discord_start_delay_seconds(3), 5.25)

    def test_resolve_cooldown_channel_id_prefers_parent_thread_channel(self):
        thread_channel = SimpleNamespace(id=555001, parent_id=123001)

        self.assertEqual(_resolve_cooldown_channel_id(thread_channel), "123001")

    def test_resolve_cooldown_channel_id_falls_back_to_channel_id(self):
        root_channel = SimpleNamespace(id=123001, parent_id=None)

        self.assertEqual(_resolve_cooldown_channel_id(root_channel), "123001")


class _SlottedMessage:
    __slots__ = ("id", "channel", "thread", "flags", "fetch_thread")

    def __init__(self, *, message_id, channel, thread=None, has_thread=False, fetch_thread=None):
        self.id = message_id
        self.channel = channel
        self.thread = thread
        self.flags = SimpleNamespace(has_thread=has_thread)
        self.fetch_thread = fetch_thread


class ResolveReplyTargetChannelTestCase(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        _auto_reply_thread_ids.clear()

    async def test_creates_thread_without_mutating_message_instance(self):
        created_thread = SimpleNamespace(id=555001, parent_id=123001)
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            create_thread=AsyncMock(return_value=created_thread),
        )
        message = _SlottedMessage(
            message_id=777001,
            channel=SimpleNamespace(id=123001, parent_id=None),
            fetch_thread=AsyncMock(return_value=None),
        )
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: created_thread if channel_id == 555001 else None,
            fetch_channel=AsyncMock(return_value=None),
        )

        reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
            target_client=target_client,
            target_channel=target_channel,
            message=message,
            thread_reply_enabled=True,
        )

        self.assertIs(reply_target_channel, created_thread)
        self.assertTrue(used_thread_reply)
        target_channel.create_thread.assert_awaited_once()
        self.assertEqual(_auto_reply_thread_ids.get(777001), 555001)

    async def test_reuses_cached_thread_when_same_message_hits_again(self):
        existing_thread = SimpleNamespace(id=555001, parent_id=123001)
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            create_thread=AsyncMock(side_effect=AssertionError("should not create a new thread")),
        )
        message = _SlottedMessage(
            message_id=777001,
            channel=SimpleNamespace(id=123001, parent_id=None),
            fetch_thread=AsyncMock(return_value=None),
        )
        _auto_reply_thread_ids[777001] = 555001
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: existing_thread if channel_id == 555001 else None,
            fetch_channel=AsyncMock(return_value=None),
        )

        reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
            target_client=target_client,
            target_channel=target_channel,
            message=message,
            thread_reply_enabled=True,
        )

        self.assertIs(reply_target_channel, existing_thread)
        self.assertTrue(used_thread_reply)
        target_channel.create_thread.assert_not_awaited()
