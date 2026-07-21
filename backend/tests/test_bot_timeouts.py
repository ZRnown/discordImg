import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend import bot as bot_module
from backend.bot import (
    MESSAGE_IMAGE_REPLY_TIMEOUT_SECONDS,
    _auto_reply_thread_ids,
    _send_discord_message,
    _get_image_match_reply_block_reason,
    dispatch_keyword_review_item,
    filter_forum_channel_configs_for_message,
    _get_image_recognition_request_timeout_seconds,
    _is_discord_missing_access_error,
    _is_image_match_above_reply_threshold,
    _is_discord_blocked_content_error,
    _resolve_best_match_image_threshold,
    _resolve_message_reply_channel,
    _resolve_cooldown_channel_id,
    _should_send_best_match_reply_image,
    _match_products_for_keyword_reply,
    resolve_reply_target_channel,
)


class BotTimeoutHelpersTestCase(unittest.TestCase):
    def test_detects_discord_blocked_content_error_by_code(self):
        error = SimpleNamespace(code=200000)

        self.assertTrue(_is_discord_blocked_content_error(error))

    def test_detects_discord_blocked_content_error_by_message(self):
        error = RuntimeError("400 Bad Request (error code: 200000): 无法发布")

        self.assertTrue(_is_discord_blocked_content_error(error))

    def test_ignores_unrelated_discord_error(self):
        error = RuntimeError("50001 Missing Access")

        self.assertFalse(_is_discord_blocked_content_error(error))

    def test_detects_discord_missing_access_error_by_code(self):
        error = SimpleNamespace(code=50001)

        self.assertTrue(_is_discord_missing_access_error(error))

    def test_detects_discord_missing_access_error_by_message(self):
        error = RuntimeError("403 Forbidden (error code: 50001): 缺少权限")

        self.assertTrue(_is_discord_missing_access_error(error))

    def test_detects_discord_missing_permissions_error(self):
        error = RuntimeError("403 Forbidden (error code: 50013): Missing Permissions")

        self.assertTrue(_is_discord_missing_access_error(error))

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

    def test_marketplace_link_search_result_is_keyword_reply_match(self):
        products = [
            {
                "id": 123,
                "title": "F50 football boots",
                "englishTitle": "F50",
            }
        ]

        matched_products, match_reasons, matched_keyword_set = _match_products_for_keyword_reply(
            products,
            {},
            ["en"],
            "https://www.kakobuy.com/item/details?url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D7658860695",
            linked_item_id="7658860695",
        )

        self.assertEqual(matched_products, products)
        self.assertEqual(matched_keyword_set, {"7658860695"})
        self.assertEqual(match_reasons[123]["source"], "marketplace_link")
        self.assertEqual(match_reasons[123]["rule"], "linked_item_id")


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

    def test_best_match_image_threshold_uses_website_override(self):
        threshold = _resolve_best_match_image_threshold(
            {
                "type": "image",
                "similarity": 0.76,
                "base_threshold": 0.63,
                "best_match_image_base_threshold": 0.78,
            },
            {"best_match_image_similarity_threshold": 0.74},
        )

        self.assertEqual(threshold, 0.74)

    def test_best_match_image_send_requires_second_threshold(self):
        self.assertFalse(
            _should_send_best_match_reply_image(
                {
                    "type": "image",
                    "similarity": 0.72,
                    "base_threshold": 0.63,
                    "best_match_image_base_threshold": 0.78,
                },
                {"best_match_image_similarity_threshold": None},
            )
        )
        self.assertTrue(
            _should_send_best_match_reply_image(
                {
                    "type": "image",
                    "similarity": 0.79,
                    "base_threshold": 0.63,
                    "best_match_image_base_threshold": 0.78,
                },
                {"best_match_image_similarity_threshold": None},
            )
        )

    def test_image_match_block_reason_rejects_when_below_first_threshold(self):
        with patch.object(
            bot_module.config,
            "DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN",
            0.03,
            create=True,
        ):
            reason = _get_image_match_reply_block_reason(
                {
                    "type": "image",
                    "similarity": 0.58,
                    "base_threshold": 0.63,
                    "top1_margin": 0.01,
                },
                {"image_similarity_threshold": None},
            )

        self.assertIn("低于网站阈值", reason)

    def test_image_match_block_reason_accepts_when_top1_margin_is_small(self):
        with patch.object(
            bot_module.config,
            "DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN",
            0.03,
            create=True,
        ):
            reason = _get_image_match_reply_block_reason(
                {
                    "type": "image",
                    "similarity": 0.72,
                    "base_threshold": 0.63,
                    "top1_margin": 0.01,
                },
                {"image_similarity_threshold": None},
            )

        self.assertIsNone(reason)

    def test_image_match_block_reason_accepts_when_margin_is_large_enough(self):
        with patch.object(
            bot_module.config,
            "DISCORD_IMAGE_REPLY_MIN_TOP1_MARGIN",
            0.03,
            create=True,
        ):
            reason = _get_image_match_reply_block_reason(
                {
                    "type": "image",
                    "similarity": 0.72,
                    "base_threshold": 0.63,
                    "top1_margin": 0.06,
                },
                {"image_similarity_threshold": None},
            )

        self.assertIsNone(reason)

    def test_below_threshold_image_match_records_skip_then_stops_reply(self):
        source = Path(bot_module.__file__).read_text(encoding="utf-8")

        self.assertIn("图片命中未过阈值，记录略过历史并跳过回复", source)
        self.assertNotIn("图片命中未过阈值，记录略过历史并继续发送链接", source)

    def test_image_recognition_requests_only_top1_result(self):
        source = Path(bot_module.__file__).read_text(encoding="utf-8")

        self.assertTrue(
            "form.add_field('limit', '1')" in source,
            "image recognition should only request the best match",
        )
        self.assertTrue(
            "form.add_field('limit', '2')" not in source,
            "image recognition should not request top2 for margin comparison",
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


class SenderChannelAccessTestCase(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        bot_module._sender_channel_access_cache.clear()

    async def test_filters_online_senders_that_cannot_access_message_channel(self):
        message_channel = SimpleNamespace(id=123001, parent_id=None)
        message = SimpleNamespace(channel=message_channel)

        inaccessible_client = SimpleNamespace(
            account_id=1,
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(return_value=None),
        )
        accessible_channel = SimpleNamespace(id=123001, parent_id=None)
        accessible_client = SimpleNamespace(
            account_id=2,
            get_channel=lambda channel_id: accessible_channel if channel_id == 123001 else None,
            fetch_channel=AsyncMock(side_effect=AssertionError("cached channel should be used")),
        )

        filtered = await bot_module._filter_channel_accessible_sender_ids(
            [1, 2],
            [inaccessible_client, accessible_client],
            message,
        )

        self.assertEqual(filtered, [2])


class DiscordSendThrottleTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_reply_delay_skips_typing_when_disabled(self):
        typing_calls = 0

        class TypingContext:
            async def __aenter__(self):
                nonlocal typing_calls
                typing_calls += 1

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class Channel:
            def typing(self):
                return TypingContext()

        with patch.object(bot_module.config, "DISCORD_SEND_TYPING_ENABLED", False, create=True), patch.object(
            bot_module.random, "uniform", return_value=0.01
        ), patch.object(bot_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            await bot_module._wait_before_discord_reply(Channel(), 0.1, 0.2)

        self.assertEqual(typing_calls, 0)
        sleep_mock.assert_awaited_once_with(0.01)

    async def test_reply_delay_uses_typing_when_enabled(self):
        typing_calls = 0

        class TypingContext:
            async def __aenter__(self):
                nonlocal typing_calls
                typing_calls += 1

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class Channel:
            def typing(self):
                return TypingContext()

        with patch.object(bot_module.config, "DISCORD_SEND_TYPING_ENABLED", True, create=True), patch.object(
            bot_module.random, "uniform", return_value=0.01
        ), patch.object(bot_module.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            await bot_module._wait_before_discord_reply(Channel(), 0.1, 0.2)

        self.assertEqual(typing_calls, 1)
        sleep_mock.assert_awaited_once_with(0.01)

    async def test_send_discord_message_serializes_concurrent_sends(self):
        active_sends = 0
        max_active_sends = 0
        sent_payloads = []

        class Channel:
            async def send(self, **kwargs):
                nonlocal active_sends, max_active_sends
                active_sends += 1
                max_active_sends = max(max_active_sends, active_sends)
                await bot_module.asyncio.sleep(0.01)
                sent_payloads.append(kwargs)
                active_sends -= 1
                return kwargs

        with patch.object(bot_module.config, "DISCORD_SEND_MAX_INFLIGHT", 1, create=True), patch.object(
            bot_module.config, "DISCORD_SEND_INTERVAL_SECONDS", 0.0, create=True
        ):
            results = await bot_module.asyncio.gather(
                _send_discord_message(Channel(), content="one"),
                _send_discord_message(Channel(), content="two"),
            )

        self.assertEqual(max_active_sends, 1)
        self.assertEqual([item["content"] for item in sent_payloads], ["one", "two"])
        self.assertEqual([item["content"] for item in results], ["one", "two"])

    async def test_thread_message_requires_access_to_thread_not_parent(self):
        message = SimpleNamespace(channel=SimpleNamespace(id=555001, parent_id=123001))
        parent_channel = SimpleNamespace(id=123001, parent_id=None)

        async def fetch_channel(channel_id):
            if channel_id == 555001:
                raise RuntimeError("50001 Missing Access")
            if channel_id == 123001:
                return parent_channel
            return None

        client = SimpleNamespace(
            account_id=1,
            get_channel=lambda channel_id: parent_channel if channel_id == 123001 else None,
            fetch_channel=AsyncMock(side_effect=fetch_channel),
        )

        filtered = await bot_module._filter_channel_accessible_sender_ids(
            [1],
            [client],
            message,
        )

        self.assertEqual(filtered, [])

    async def test_inaccessible_sender_channel_is_cached_briefly(self):
        message = SimpleNamespace(channel=SimpleNamespace(id=555001, parent_id=123001))

        async def fetch_channel(channel_id):
            raise RuntimeError("50001 Missing Access")

        client = SimpleNamespace(
            account_id=1,
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(side_effect=fetch_channel),
        )

        with patch.object(bot_module, "_sender_channel_access_now", return_value=100.0):
            first = await bot_module._filter_channel_accessible_sender_ids([1], [client], message)
        with patch.object(bot_module, "_sender_channel_access_now", return_value=101.0):
            second = await bot_module._filter_channel_accessible_sender_ids([1], [client], message)

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        client.fetch_channel.assert_awaited_once_with(555001)

    async def test_inaccessible_sender_channel_cache_expires(self):
        message = SimpleNamespace(channel=SimpleNamespace(id=555001, parent_id=123001))
        target_channel = SimpleNamespace(id=555001, parent_id=123001)

        client = SimpleNamespace(
            account_id=1,
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(
                side_effect=[
                    RuntimeError("50001 Missing Access"),
                    target_channel,
                ]
            ),
        )

        with patch.object(bot_module, "_sender_channel_access_now", return_value=100.0):
            first = await bot_module._filter_channel_accessible_sender_ids([1], [client], message)
        with patch.object(
            bot_module,
            "_sender_channel_access_now",
            return_value=100.0 + bot_module.SENDER_CHANNEL_ACCESS_CACHE_TTL_SECONDS + 1.0,
        ):
            second = await bot_module._filter_channel_accessible_sender_ids([1], [client], message)

        self.assertEqual(first, [])
        self.assertEqual(second, [1])
        self.assertEqual(client.fetch_channel.await_count, 2)


class RecognizeImageRetryPolicyTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_recognize_image_retries_on_backend_busy_503(self):
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

            async def json(self):
                import json

                return json.loads(self._body)

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
            [
                FakeResponse(503, '{"error":"search busy","retryable":true}'),
                FakeResponse(200, '{"ok": true}'),
            ]
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

        self.assertEqual(result, {"ok": True})
        self.assertEqual(fake_session.post_calls, 2)
        mock_sleep.assert_awaited_once()

    async def test_recognize_image_does_not_retry_search_warming_503(self):
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
            [
                FakeResponse(
                    503,
                    '{"error":"search warming up","message":"图搜服务预热中，请稍后重试","retryable":true}',
                ),
            ]
        )

        with patch.object(
            bot_module.aiohttp,
            "ClientSession",
            return_value=fake_session,
        ), patch.object(
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
                user_shops=["1771550301", "TIP"],
            )

        self.assertIsNone(result)
        self.assertEqual(fake_session.post_calls, 1)
        mock_sleep.assert_not_awaited()


class KeywordSearchEntryTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_marketplace_link_message_reaches_keyword_text_search(self):
        client = object.__new__(bot_module.DiscordBotClient)
        client.search_products_by_keyword = AsyncMock(
            return_value={"success": True, "products": []}
        )
        message = SimpleNamespace(
            clean_content=(
                "https://www.kakobuy.com/item/details?"
                "url=https%3A%2F%2Fweidian.com%2Fitem.html%3FitemID%3D7704997828"
            ),
            content="",
        )

        result = await bot_module.DiscordBotClient.handle_keyword_search(client, message)

        self.assertFalse(result)
        client.search_products_by_keyword.assert_awaited_once()


class DiscordClientEventSchedulingTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_event_drops_event_when_discord_loop_is_unavailable(self):
        client = object.__new__(bot_module.DiscordBotClient)
        client.account_id = 221
        client.user_id = 3
        client.loop = SimpleNamespace()
        event_ran = False

        async def event_handler():
            nonlocal event_ran
            event_ran = True

        task = bot_module.DiscordBotClient._schedule_event(
            client,
            event_handler,
            "disconnect",
        )

        self.assertIsNone(task)
        self.assertFalse(event_ran)


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

    async def test_creates_thread_when_no_existing_message_thread(self):
        created_thread = SimpleNamespace(id=888001, parent_id=123001)
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            fetch_message=AsyncMock(return_value=SimpleNamespace(id=777001, flags=SimpleNamespace(has_thread=False))),
            threads=[],
            create_thread=AsyncMock(return_value=created_thread),
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

        self.assertIs(reply_target_channel, created_thread)
        self.assertTrue(used_thread_reply)
        target_channel.create_thread.assert_awaited_once()
        self.assertEqual(_auto_reply_thread_ids[777001], 888001)

    async def test_reuses_existing_thread_when_thread_create_races(self):
        existing_thread = SimpleNamespace(id=888002, parent_id=123001)
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            fetch_message=AsyncMock(
                return_value=SimpleNamespace(id=777002, flags=SimpleNamespace(has_thread=False))
            ),
            threads=[],
            create_thread=AsyncMock(side_effect=RuntimeError("thread already exists")),
        )
        message = _SlottedMessage(
            message_id=777002,
            channel=SimpleNamespace(id=123001, parent_id=None),
            fetch_thread=AsyncMock(return_value=None),
        )
        lookup_count = {"count": 0}

        async def fetch_channel(channel_id):
            return existing_thread if channel_id == 888002 else None

        async def resolve_after_failure(target_client, target_channel_arg, message_arg):
            lookup_count["count"] += 1
            return None if lookup_count["count"] == 1 else existing_thread

        target_client = SimpleNamespace(
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(side_effect=fetch_channel),
        )

        with patch.object(
            bot_module,
            "_resolve_existing_reply_thread_after_create_failure",
            side_effect=resolve_after_failure,
        ):
            reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
                target_client=target_client,
                target_channel=target_channel,
                message=message,
                thread_reply_enabled=True,
            )

        self.assertIs(reply_target_channel, existing_thread)
        self.assertTrue(used_thread_reply)
        target_channel.create_thread.assert_awaited_once()

    async def test_waits_for_thread_after_create_failure_before_replying(self):
        existing_thread = SimpleNamespace(id=888003, parent_id=123001)
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            fetch_message=AsyncMock(return_value=SimpleNamespace(id=777003, flags=SimpleNamespace(has_thread=False))),
            threads=[],
            create_thread=AsyncMock(side_effect=RuntimeError("discord still creating thread")),
        )
        message = _SlottedMessage(
            message_id=777003,
            channel=SimpleNamespace(id=123001, parent_id=None),
            fetch_thread=AsyncMock(return_value=None),
        )
        lookup_count = {"count": 0}

        async def resolve_after_failure(target_client, target_channel_arg, message_arg):
            lookup_count["count"] += 1
            return existing_thread if lookup_count["count"] >= 4 else None

        target_client = SimpleNamespace(
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(return_value=None),
        )

        with patch.object(
            bot_module,
            "_resolve_existing_reply_thread_after_create_failure",
            side_effect=resolve_after_failure,
        ), patch.object(bot_module.asyncio, "sleep", new=AsyncMock()) as mock_sleep:
            reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
                target_client=target_client,
                target_channel=target_channel,
                message=message,
                thread_reply_enabled=True,
                thread_wait_timeout_seconds=5,
                thread_wait_poll_seconds=1,
            )

        self.assertIs(reply_target_channel, existing_thread)
        self.assertTrue(used_thread_reply)
        target_channel.create_thread.assert_awaited_once()
        mock_sleep.assert_awaited()

    async def test_returns_none_when_thread_is_unavailable_until_timeout(self):
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            fetch_message=AsyncMock(return_value=SimpleNamespace(id=777004, flags=SimpleNamespace(has_thread=False))),
            threads=[],
            create_thread=AsyncMock(return_value=None),
        )
        message = _SlottedMessage(
            message_id=777004,
            channel=SimpleNamespace(id=123001, parent_id=None),
            fetch_thread=AsyncMock(return_value=None),
        )
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: None,
            fetch_channel=AsyncMock(return_value=None),
        )

        with patch.object(
            bot_module,
            "_resolve_existing_reply_thread_after_create_failure",
            new=AsyncMock(return_value=None),
        ), patch.object(
            bot_module,
            "_resolve_archived_reply_thread",
            new=AsyncMock(return_value=None),
        ), patch.object(
            bot_module.time,
            "monotonic",
            side_effect=[0, 10],
        ), patch.object(bot_module.asyncio, "sleep", new=AsyncMock()):
            reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
                target_client=target_client,
                target_channel=target_channel,
                message=message,
                thread_reply_enabled=True,
                thread_wait_timeout_seconds=5,
                thread_wait_poll_seconds=1,
            )

        self.assertIsNone(reply_target_channel)
        self.assertFalse(used_thread_reply)

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

    async def test_uses_raw_message_thread_when_library_message_lacks_thread_object(self):
        existing_thread = SimpleNamespace(id=777001, parent_id=123001)
        target_channel = SimpleNamespace(
            id=123001,
            parent_id=None,
            fetch_message=AsyncMock(
                return_value=SimpleNamespace(
                    id=777001,
                    channel=SimpleNamespace(id=123001, parent_id=None),
                    thread=None,
                    flags=SimpleNamespace(has_thread=False),
                )
            ),
            threads=[],
        )
        message = _SlottedMessage(
            message_id=777001,
            channel=SimpleNamespace(id=123001, parent_id=None),
            has_thread=True,
            fetch_thread=None,
        )
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: existing_thread if channel_id == 777001 else None,
            fetch_channel=AsyncMock(return_value=existing_thread),
            http=SimpleNamespace(
                get_message=AsyncMock(
                    return_value={
                        "id": "777001",
                        "channel_id": "123001",
                        "flags": 32,
                        "thread": {
                            "id": "777001",
                        },
                    }
                )
            ),
        )

        reply_target_channel, used_thread_reply = await resolve_reply_target_channel(
            target_client=target_client,
            target_channel=target_channel,
            message=message,
            thread_reply_enabled=True,
        )

        self.assertIs(reply_target_channel, existing_thread)
        self.assertTrue(used_thread_reply)
        target_client.http.get_message.assert_awaited_once_with(123001, 777001)


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

    async def test_returns_none_when_thread_channel_is_unavailable(self):
        parent_channel = SimpleNamespace(id=123001, parent_id=None)
        target_client = SimpleNamespace(
            get_channel=lambda channel_id: parent_channel if channel_id == 123001 else None,
            fetch_channel=AsyncMock(side_effect=RuntimeError("thread gone")),
        )
        message = SimpleNamespace(channel=SimpleNamespace(id=555001, parent_id=123001))

        resolved = await _resolve_message_reply_channel(target_client, message)

        self.assertIsNone(resolved)
        target_client.fetch_channel.assert_awaited_once_with(555001)


class DispatchKeywordReviewItemTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_uses_current_website_thresholds_when_dispatching_review_item(self):
        review_item = {
            "id": 77,
            "user_id": 9,
            "website_id": 12,
            "payload": {
                "website_config": {
                    "id": 12,
                    "name": "old-site",
                    "image_similarity_threshold": 0.63,
                    "best_match_image_similarity_threshold": 0.75,
                },
                "message": {
                    "id": 7001,
                    "channel_id": 123001,
                    "channel_name": "parent-channel",
                    "guild_id": 9001,
                    "author_id": 42,
                    "author_name": "buyer",
                    "content": "keyword",
                },
                "product": {"id": 1001},
                "match_context": {
                    "type": "image",
                    "similarity": 0.99,
                    "base_threshold": 0.63,
                    "best_match_image_base_threshold": 0.97,
                    "top1_margin": 0.08,
                },
            },
        }
        fake_client = SimpleNamespace(
            schedule_reply=AsyncMock(return_value=True),
        )

        from backend.database import db as database_db

        with patch.object(
            bot_module,
            "_select_keyword_review_dispatch_client",
            return_value=fake_client,
        ), patch.object(
            database_db,
            "get_website_configs_by_channel",
            return_value=[
                {
                    "id": 12,
                    "name": "new-site",
                    "image_similarity_threshold": 0.93,
                    "best_match_image_similarity_threshold": 0.97,
                    "keyword_review_enabled": 1,
                }
            ],
        ), patch.object(
            database_db,
            "update_keyword_reply_review_item_status",
        ):
            success = await dispatch_keyword_review_item(review_item)

        self.assertTrue(success)
        fake_client.schedule_reply.assert_awaited_once()
        website_configs_override = fake_client.schedule_reply.await_args.kwargs["website_configs_override"]
        self.assertEqual(website_configs_override[0]["image_similarity_threshold"], 0.93)
        self.assertEqual(
            website_configs_override[0]["best_match_image_similarity_threshold"],
            0.97,
        )

    async def test_blocks_review_dispatch_when_current_threshold_rejects_image_match(self):
        review_item = {
            "id": 78,
            "user_id": 9,
            "website_id": 12,
            "payload": {
                "website_config": {
                    "id": 12,
                    "name": "old-site",
                    "image_similarity_threshold": 0.63,
                },
                "message": {
                    "id": 7002,
                    "channel_id": 123001,
                    "channel_name": "parent-channel",
                    "guild_id": 9001,
                    "author_id": 42,
                    "author_name": "buyer",
                    "content": "keyword",
                },
                "product": {"id": 1002},
                "match_context": {
                    "type": "image",
                    "similarity": 0.91,
                    "base_threshold": 0.63,
                    "top1_margin": 0.08,
                },
            },
        }
        fake_client = SimpleNamespace(
            schedule_reply=AsyncMock(return_value=True),
        )

        from backend.database import db as database_db

        with patch.object(
            bot_module,
            "_select_keyword_review_dispatch_client",
            return_value=fake_client,
        ), patch.object(
            database_db,
            "get_website_configs_by_channel",
            return_value=[
                {
                    "id": 12,
                    "name": "new-site",
                    "image_similarity_threshold": 0.93,
                    "keyword_review_enabled": 1,
                }
            ],
        ), patch.object(
            database_db,
            "update_keyword_reply_review_item_status",
        ) as mock_update_status:
            success = await dispatch_keyword_review_item(review_item)

        self.assertFalse(success)
        fake_client.schedule_reply.assert_not_awaited()
        mock_update_status.assert_called_once()
        self.assertEqual(mock_update_status.call_args.args[1], "failed")


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
        self.assertEqual(message.thread.id, 555001)
        self.assertTrue(message.flags.has_thread)
