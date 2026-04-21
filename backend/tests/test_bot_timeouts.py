import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend import bot as bot_module
from backend.bot import (
    MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS,
    _auto_reply_thread_ids,
    filter_forum_channel_configs_for_message,
    _get_image_recognition_request_timeout_seconds,
    _is_image_match_above_reply_threshold,
    _resolve_message_reply_channel,
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

    def test_resolve_channel_lookup_ids_include_parent_for_forum_post(self):
        lookup_ids = bot_module.DiscordBotClient._resolve_channel_lookup_ids(
            SimpleNamespace(id=555001, parent_id=123001)
        )

        self.assertEqual(lookup_ids, ["555001", "123001"])

    def test_forum_parent_configs_require_forum_post_reply_toggle(self):
        channel = SimpleNamespace(id=555001, parent_id=123001)
        parent_configs = [{"id": 7, "name": "oopbuy"}]

        filtered = filter_forum_channel_configs_for_message(
            channel,
            direct_configs=[],
            parent_configs=parent_configs,
            settings_map={7: {"forum_post_reply_enabled": 0}},
        )

        self.assertEqual(filtered, [])

    def test_direct_thread_binding_is_not_blocked_by_forum_post_reply_toggle(self):
        channel = SimpleNamespace(id=555001, parent_id=123001)
        direct_configs = [{"id": 8, "name": "kakobuy"}]

        filtered = filter_forum_channel_configs_for_message(
            channel,
            direct_configs=direct_configs,
            parent_configs=[],
            settings_map={8: {"forum_post_reply_enabled": 0}},
        )

        self.assertEqual(filtered, direct_configs)

    def test_forum_parent_configs_pass_when_forum_post_reply_enabled(self):
        channel = SimpleNamespace(id=555001, parent_id=123001)
        parent_configs = [{"id": 9, "name": "hipobuy"}]

        filtered = filter_forum_channel_configs_for_message(
            channel,
            direct_configs=[],
            parent_configs=parent_configs,
            settings_map={9: {"forum_post_reply_enabled": 1}},
        )

        self.assertEqual(filtered, parent_configs)

    def test_image_match_threshold_uses_website_override(self):
        self.assertFalse(
            _is_image_match_above_reply_threshold(
                {"type": "image", "similarity": 0.72, "base_threshold": 0.6},
                {"image_similarity_threshold": 0.8},
            )
        )
        self.assertTrue(
            _is_image_match_above_reply_threshold(
                {"type": "image", "similarity": 0.72, "base_threshold": 0.6},
                {"image_similarity_threshold": None},
            )
        )

    def test_summarize_exception_for_log_collapses_whitespace_and_truncates(self):
        error = RuntimeError("429 Too Many Requests\n\n" + ("x" * 260))

        summary = bot_module._summarize_exception_for_log(error, limit=80)

        self.assertNotIn("\n", summary)
        self.assertLessEqual(len(summary), 80)
        self.assertTrue(summary.endswith("..."))

    def test_log_rate_limited_bark_issue_suppresses_duplicates_within_window(self):
        with patch.object(bot_module.time, "monotonic", side_effect=[100.0, 110.0, 180.0]), patch.object(
            bot_module.logger, "error"
        ) as mock_error, patch.object(bot_module.logger, "warning") as mock_warning:
            bot_module._log_rate_limited_bark_issue("表情互动 Bark 通知失败", RuntimeError("first failure"))
            bot_module._log_rate_limited_bark_issue("表情互动 Bark 通知失败", RuntimeError("second failure"))
            bot_module._log_rate_limited_bark_issue("表情互动 Bark 通知失败", RuntimeError("third failure"))

        self.assertEqual(mock_error.call_count, 2)
        self.assertEqual(mock_warning.call_count, 1)
        self.assertIn("重复 1 次", mock_warning.call_args.args[0])


class RecognizeImageRetryPolicyTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_recognize_image_does_not_retry_on_backend_busy_503(self):
        class FakeResponse:
            def __init__(self, status, body):
                self.status = status
                self._body = body

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def text(self):
                return self._body

        class FakeSession:
            def __init__(self, responses):
                self._responses = list(responses)
                self.post_calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                response = self._responses[self.post_calls]
                self.post_calls += 1
                return response

        fake_session = FakeSession(
            [FakeResponse(503, '{"error":"search busy","retryable":true}')]
        )

        with patch.object(
            bot_module.aiohttp,
            "ClientSession",
            return_value=fake_session,
        ) as _mock_client_session, patch.object(
            bot_module.asyncio,
            "sleep",
            AsyncMock(),
        ) as mock_sleep, patch.object(
            bot_module.config,
            "BACKEND_API_URL",
            "http://127.0.0.1:5001",
            create=True,
        ):
            result = await bot_module.DiscordBotClient.recognize_image(
                SimpleNamespace(user_id=None),
                b"fake-image-bytes",
                user_shops=["Vibeo"],
            )

        self.assertIsNone(result)
        self.assertEqual(fake_session.post_calls, 1)
        mock_sleep.assert_not_awaited()


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

    async def test_does_not_create_thread_when_no_existing_message_thread(self):
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            fetch_message=AsyncMock(return_value=SimpleNamespace(id=777001, flags=SimpleNamespace(has_thread=False))),
            threads=[],
            create_thread=AsyncMock(side_effect=AssertionError("should not create a thread")),
        )
        message = _SlottedMessage(
            message_id=777001,
            channel=SimpleNamespace(id=123001, parent_id=None),
            fetch_thread=AsyncMock(return_value=None),
        )
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(return_value=None),
        )

        reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
            target_client=target_client,
            target_channel=target_channel,
            message=message,
            thread_reply_enabled=True,
        )

        self.assertIs(reply_target_channel, target_channel)
        self.assertFalse(used_thread_reply)
        target_channel.create_thread.assert_not_awaited()
        self.assertNotIn(777001, _auto_reply_thread_ids)

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


class ResolveMessageReplyChannelTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_cached_channel_when_available(self):
        thread_channel = SimpleNamespace(id=555001, parent_id=123001)
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: thread_channel if channel_id == 555001 else None,
            fetch_channel=AsyncMock(side_effect=AssertionError("should not fetch when cached")),
        )
        message = SimpleNamespace(channel=SimpleNamespace(id=555001, parent_id=123001))

        resolved = await _resolve_message_reply_channel(target_client, message)

        self.assertIs(resolved, thread_channel)

    async def test_fetches_forum_post_channel_when_not_cached(self):
        fetched_thread = SimpleNamespace(id=555001, parent_id=123001)
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(return_value=fetched_thread),
        )
        message = SimpleNamespace(channel=SimpleNamespace(id=555001, parent_id=123001))

        resolved = await _resolve_message_reply_channel(target_client, message)

        self.assertIs(resolved, fetched_thread)
        target_client.fetch_channel.assert_awaited_once_with(555001)


class KeywordReviewMessageProxyTestCase(unittest.TestCase):
    def test_saved_thread_reply_target_wins_over_original_parent_channel(self):
        review_item = {
            "channel_id": "123001",
            "message_id": "777001",
            "sender_id": "42",
            "payload": {
                "message": {
                    "id": 777001,
                    "channel_id": 123001,
                    "channel_name": "parent-channel",
                    "guild_id": 9001,
                    "author_id": 42,
                    "author_name": "buyer",
                    "content": "keyword",
                },
                "reply_target_channel": {
                    "used_thread_reply": True,
                    "channel_id": 555001,
                    "channel_name": "auto-reply-thread",
                    "parent_channel_id": 123001,
                    "parent_channel_name": "parent-channel",
                },
            },
        }

        message = bot_module._build_keyword_review_message_proxy(review_item)

        self.assertEqual(message.channel.id, 555001)
        self.assertEqual(message.channel.name, "auto-reply-thread")
        self.assertEqual(message.channel.parent_id, 123001)
        self.assertEqual(message.channel.parent.name, "parent-channel")
