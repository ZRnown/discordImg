import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.bot import (
    DiscordBotClient,
    _build_multi_reply_content,
    _build_keyword_direct_send_payload,
    _should_mention_reply_author,
    _should_send_plain_keyword_message,
    _should_use_keyword_window_mode,
)

class KeywordReplyQueueTestCase(unittest.TestCase):
    def _import_window_manager_class(self):
        try:
            from backend.keyword_reply_window import KeywordReplyWindowManager
        except ImportError as exc:
            self.fail(f"KeywordReplyWindowManager is missing: {exc}")
        return KeywordReplyWindowManager

    def _import_batch_content_builder(self):
        try:
            from backend.keyword_reply_window import build_batched_reply_content
        except ImportError as exc:
            self.fail(f"build_batched_reply_content is missing: {exc}")
        return build_batched_reply_content

    def test_batch_limit_waits_until_batch_is_full(self):
        manager_cls = self._import_window_manager_class()
        now_holder = {'value': 100.0}
        manager = manager_cls(time_fn=lambda: now_holder['value'])
        key = ("user-1", "website-9", "guild-2")

        first = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-1")
        now_holder['value'] = 120.0
        second = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-2")
        now_holder['value'] = 180.0
        third = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-3")

        self.assertFalse(first.dispatch_now)
        self.assertFalse(second.dispatch_now)
        self.assertTrue(third.dispatch_now)
        self.assertEqual(tuple(first.ready_payloads), ())
        self.assertEqual(tuple(second.ready_payloads), ())
        self.assertEqual(tuple(third.ready_payloads), ("msg-1", "msg-2", "msg-3"))
        self.assertEqual(manager.get_queue_size(key), 0)

    def test_partial_batch_flushes_when_interval_rolls(self):
        manager_cls = self._import_window_manager_class()
        now_holder = {'value': 100.0}
        manager = manager_cls(time_fn=lambda: now_holder['value'])
        key = ("user-1", "website-9", "channel-4")

        first = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-1")
        now_holder['value'] = 140.0
        second = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-2")

        self.assertFalse(first.dispatch_now)
        self.assertFalse(second.dispatch_now)
        self.assertEqual(manager.get_queue_size(key), 2)
        self.assertEqual(manager.release_due_jobs(key, interval_seconds=300, batch_size=3), [])

        now_holder['value'] = 405.0
        self.assertEqual(manager.release_due_jobs(key, interval_seconds=300, batch_size=3), ["msg-1", "msg-2"])
        self.assertEqual(manager.get_queue_size(key), 0)

    def test_partial_batch_flushes_at_fixed_window_boundary(self):
        manager_cls = self._import_window_manager_class()
        now_holder = {'value': 15.0}
        manager = manager_cls(time_fn=lambda: now_holder['value'])
        key = ("user-1", "website-9", "channel-4")

        first = manager.reserve_or_enqueue(key, interval_seconds=30, batch_size=3, payload="msg-1")
        now_holder['value'] = 20.0
        second = manager.reserve_or_enqueue(key, interval_seconds=30, batch_size=3, payload="msg-2")

        self.assertFalse(first.dispatch_now)
        self.assertFalse(second.dispatch_now)
        self.assertEqual(manager.seconds_until_next_window(key, interval_seconds=30), 10.0)

        now_holder['value'] = 29.0
        self.assertEqual(manager.release_due_jobs(key, interval_seconds=30, batch_size=3), [])

        now_holder['value'] = 30.0
        self.assertEqual(manager.release_due_jobs(key, interval_seconds=30, batch_size=3), ["msg-1", "msg-2"])
        self.assertEqual(manager.get_queue_size(key), 0)

    def test_overflow_waits_for_next_window_after_full_batch_dispatch(self):
        manager_cls = self._import_window_manager_class()
        now_holder = {'value': 100.0}
        manager = manager_cls(time_fn=lambda: now_holder['value'])
        key = ("user-2", "website-5", "channel-7")

        manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-1")
        now_holder['value'] = 110.0
        manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-2")
        now_holder['value'] = 120.0
        third = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-3")
        now_holder['value'] = 150.0
        fourth = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=3, payload="msg-4")

        self.assertTrue(third.dispatch_now)
        self.assertFalse(fourth.dispatch_now)
        self.assertEqual(tuple(third.ready_payloads), ("msg-1", "msg-2", "msg-3"))
        self.assertEqual(manager.get_queue_size(key), 1)
        self.assertEqual(manager.seconds_until_next_window(key, interval_seconds=300), 150.0)

        now_holder['value'] = 405.0
        self.assertEqual(manager.release_due_jobs(key, interval_seconds=300, batch_size=3), ["msg-4"])
        self.assertEqual(manager.get_queue_size(key), 0)

    def test_zero_batch_size_means_unlimited(self):
        manager_cls = self._import_window_manager_class()
        manager = manager_cls(time_fn=lambda: 100.0)
        key = ("user-2", "website-5", "guild-7")

        first = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=0, payload="msg-1")
        second = manager.reserve_or_enqueue(key, interval_seconds=300, batch_size=0, payload="msg-2")

        self.assertTrue(first.dispatch_now)
        self.assertTrue(second.dispatch_now)
        self.assertEqual(tuple(first.ready_payloads), ("msg-1",))
        self.assertEqual(tuple(second.ready_payloads), ("msg-2",))
        self.assertEqual(manager.get_queue_size(key), 0)
        self.assertEqual(manager.release_due_jobs(key, interval_seconds=300, batch_size=0), [])

    def test_batch_content_mentions_each_author_with_its_reply(self):
        build_content = self._import_batch_content_builder()

        content = build_content([
            {"author_id": 1001, "reply_content": "https://a.example/item-1"},
            {"author_id": 1002, "reply_content": "第一行\n第二行"},
        ])

        self.assertEqual(
            content,
            "<@1001> https://a.example/item-1\n<@1002> 第一行\n  第二行",
        )

    def test_batch_content_keeps_prebuilt_mention_lines_without_double_wrapping(self):
        build_content = self._import_batch_content_builder()

        content = build_content([
            {
                "author_id": 1001,
                "reply_content": "<@1001> https://a.example/item-1\n<@1001> https://b.example/item-2",
                "reply_content_is_final": True,
            },
            {
                "author_id": 1002,
                "reply_content": "https://c.example/item-3",
            },
        ])

        self.assertEqual(
            content,
            "<@1001> https://a.example/item-1\n<@1001> https://b.example/item-2\n<@1002> https://c.example/item-3",
        )


class ReplyScopeFallbackTestCase(unittest.TestCase):
    def setUp(self):
        self.client = SimpleNamespace(user_id=42)
        self.website_config = {
            "id": 7,
            "name": "target-site",
            "display_name": "Target Site",
            "reply_template": "网站模板 {url}",
        }

    @patch("backend.bot.get_response_url_for_channel", return_value="https://fallback.example/item-1")
    def test_scope_miss_falls_back_to_plain_link(self, mocked_get_url):
        product = {"id": 101, "replyScope": '["other-site"]'}
        custom_reply = {
            "reply_type": "text_and_link",
            "content": "自定义 {url}",
            "product_data": {"id": 101},
        }

        reply_content = DiscordBotClient._generate_reply_content(
            self.client,
            product,
            channel_id="123",
            custom_reply=custom_reply,
            website_config=self.website_config,
        )

        self.assertEqual(reply_content, "https://fallback.example/item-1")
        mocked_get_url.assert_called_once()

    @patch("backend.bot.get_response_url_for_channel", return_value="https://fallback.example/item-1")
    def test_scope_match_uses_product_custom_reply(self, mocked_get_url):
        product = {"id": 102, "replyScope": '["target-site"]'}
        custom_reply = {
            "reply_type": "text_and_link",
            "content": "自定义 {url}",
            "product_data": {"id": 102},
        }

        reply_content = DiscordBotClient._generate_reply_content(
            self.client,
            product,
            channel_id="123",
            custom_reply=custom_reply,
            website_config=self.website_config,
        )

        self.assertEqual(reply_content, "自定义 https://fallback.example/item-1")
        mocked_get_url.assert_called_once()


class MultiProductMentionFormatTestCase(unittest.TestCase):
    def test_multi_product_content_mentions_same_author_on_each_line(self):
        content = DiscordBotClient._build_explicit_mention_reply_content(
            SimpleNamespace(),
            author_id=1001,
            reply_contents=[
                "https://a.example/item-1",
                "https://b.example/item-2",
                "第一行\n第二行",
            ],
        )

        self.assertEqual(
            content,
            "<@1001> https://a.example/item-1\n"
            "<@1001> https://b.example/item-2\n"
            "<@1001> 第一行\n"
            "  第二行",
        )


class KeywordWindowModeActivationTestCase(unittest.TestCase):
    def test_keyword_window_mode_only_applies_with_single_sender(self):
        self.assertTrue(
            _should_use_keyword_window_mode(
                sender_count=1,
                interval_seconds=30,
                batch_size=2,
                reply_mode="keyword",
            )
        )
        self.assertFalse(
            _should_use_keyword_window_mode(
                sender_count=1,
                interval_seconds=30,
                batch_size=2,
                reply_mode="rotation",
            )
        )
        self.assertFalse(
            _should_use_keyword_window_mode(
                sender_count=0,
                interval_seconds=30,
                batch_size=2,
                reply_mode="keyword",
            )
        )
        self.assertFalse(
            _should_use_keyword_window_mode(
                sender_count=2,
                interval_seconds=30,
                batch_size=2,
                reply_mode="keyword",
            )
        )
        self.assertFalse(
            _should_use_keyword_window_mode(
                sender_count=1,
                interval_seconds=30,
                batch_size=0,
                reply_mode="keyword",
            )
        )
        self.assertFalse(
            _should_use_keyword_window_mode(
                sender_count=1,
                interval_seconds=30,
                batch_size=2,
                reply_mode="default",
            )
        )


class KeywordSendStyleTestCase(unittest.TestCase):
    def test_default_mode_multi_reply_content_stays_plain(self):
        content = _build_multi_reply_content(
            author_id=1001,
            reply_contents=[
                "https://a.example/item-1",
                "https://b.example/item-2",
            ],
            reply_mode="default",
        )

        self.assertEqual(
            content,
            "https://a.example/item-1\nhttps://b.example/item-2",
        )

    def test_keyword_mode_multi_reply_content_mentions_each_line(self):
        content = _build_multi_reply_content(
            author_id=1001,
            reply_contents=[
                "https://a.example/item-1",
                "https://b.example/item-2",
            ],
            reply_mode="keyword",
        )

        self.assertEqual(
            content,
            "<@1001> https://a.example/item-1\n<@1001> https://b.example/item-2",
        )

    def test_keyword_mode_single_link_builds_direct_mention_payload(self):
        payload = _build_keyword_direct_send_payload(
            author_id=1001,
            reply_content="https://a.example/item-1",
        )

        self.assertEqual(payload["content"], "<@1001> https://a.example/item-1")
        self.assertTrue(payload["explicit_mentions"])
        self.assertTrue(payload["skip_reference"])
        self.assertTrue(payload["final_direct_content"])
        self.assertEqual(payload["reply_type"], "custom_only")

    def test_keyword_explicit_mentions_send_plain_message(self):
        self.assertTrue(
            _should_send_plain_keyword_message(
                prevalidated_batch=False,
                explicit_mentions=True,
                reply_mode="keyword",
            )
        )

    def test_rotation_explicit_mentions_still_reply(self):
        self.assertFalse(
            _should_send_plain_keyword_message(
                prevalidated_batch=False,
                explicit_mentions=True,
                reply_mode="rotation",
            )
        )

    def test_default_mode_still_reply(self):
        self.assertFalse(
            _should_send_plain_keyword_message(
                prevalidated_batch=False,
                explicit_mentions=True,
                reply_mode="default",
            )
        )

    def test_default_mode_reply_does_not_ping_author(self):
        self.assertFalse(
            _should_mention_reply_author(
                explicit_mentions=False,
                reply_mode="default",
            )
        )

    def test_rotation_reply_still_pings_author_when_not_using_inline_mentions(self):
        self.assertTrue(
            _should_mention_reply_author(
                explicit_mentions=False,
                reply_mode="rotation",
            )
        )

    def test_inline_mentions_disable_reply_ping(self):
        self.assertFalse(
            _should_mention_reply_author(
                explicit_mentions=True,
                reply_mode="rotation",
            )
        )

    def test_prevalidated_batch_always_sends_plain_message(self):
        self.assertTrue(
            _should_send_plain_keyword_message(
                prevalidated_batch=True,
                explicit_mentions=False,
                reply_mode="rotation",
            )
        )


if __name__ == "__main__":
    unittest.main()
