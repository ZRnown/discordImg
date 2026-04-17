import unittest
import os
import tempfile
import uuid
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot import (
    DiscordBotClient,
    _build_multi_reply_content,
    _build_keyword_direct_send_payload,
    _should_mention_reply_author,
    _should_send_plain_keyword_message,
    _should_use_keyword_window_mode,
)
from backend import database as database_module
from backend.database import Database


class TestDatabase(Database):
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_sqlite_database()

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

    def test_window_end_mode_keeps_first_batch_until_boundary(self):
        manager_cls = self._import_window_manager_class()
        now_holder = {'value': 15.0}
        manager = manager_cls(time_fn=lambda: now_holder['value'])
        key = ("user-1", "website-9", "channel-4")

        first = manager.reserve_or_enqueue(
            key,
            interval_seconds=30,
            batch_size=3,
            payload="msg-1",
            dispatch_mode="window_end",
        )
        now_holder['value'] = 20.0
        second = manager.reserve_or_enqueue(
            key,
            interval_seconds=30,
            batch_size=3,
            payload="msg-2",
            dispatch_mode="window_end",
        )
        now_holder['value'] = 25.0
        third = manager.reserve_or_enqueue(
            key,
            interval_seconds=30,
            batch_size=3,
            payload="msg-3",
            dispatch_mode="window_end",
        )
        now_holder['value'] = 26.0
        overflow = manager.reserve_or_enqueue(
            key,
            interval_seconds=30,
            batch_size=3,
            payload="msg-4",
            dispatch_mode="window_end",
        )

        self.assertFalse(first.dispatch_now)
        self.assertFalse(second.dispatch_now)
        self.assertFalse(third.dispatch_now)
        self.assertFalse(overflow.dispatch_now)
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertTrue(third.accepted)
        self.assertFalse(overflow.accepted)
        self.assertEqual(manager.get_queue_size(key), 3)

        now_holder['value'] = 30.0
        self.assertEqual(
            manager.release_due_jobs(key, interval_seconds=30, batch_size=3, dispatch_mode="window_end"),
            ["msg-1", "msg-2", "msg-3"],
        )
        self.assertEqual(manager.get_queue_size(key), 0)


class KeywordReplyBackgroundTaskTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_start_keyword_reply_task_returns_immediately(self):
        completed = []

        async def slow_job():
            await asyncio.sleep(0.05)
            completed.append("done")
            return True

        task = DiscordBotClient._start_keyword_reply_background_task(
            SimpleNamespace(),
            slow_job(),
            task_name="keyword-task-test",
        )

        self.assertIsInstance(task, asyncio.Task)
        self.assertFalse(task.done())
        self.assertEqual(completed, [])

        await asyncio.sleep(0.08)

        self.assertEqual(completed, ["done"])
        self.assertTrue(task.done())
        self.assertTrue(task.result())


class WebsiteBindingIntegrityTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = TestDatabase(os.path.join(self.temp_dir.name, "metadata.db"))
        self.user_id = self._create_user()
        self.website_id = self._create_website()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_user(self):
        username = f"user_{uuid.uuid4().hex[:8]}"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active)
                VALUES (?, ?, 'user', 1)
                """,
                (username, "hashed_password"),
            )
            conn.commit()
            return cursor.lastrowid

    def _create_website(self):
        name = f"site_{uuid.uuid4().hex[:8]}"
        self.assertTrue(
            self.db.add_website_config(
                name=name,
                display_name="Test Site",
                url_template="https://example.com/{id}",
                id_pattern=r"\d+",
            )
        )
        website = next(item for item in self.db.get_website_configs() if item["name"] == name)
        return website["id"]

    def _create_account(self, username):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO discord_accounts (username, token, user_id, status)
                VALUES (?, ?, ?, 'online')
                """,
                (username, f"token_{uuid.uuid4().hex}", self.user_id),
            )
            conn.commit()
            return cursor.lastrowid

    def test_sender_and_listener_counts_ignore_orphaned_bindings(self):
        real_account_id = self._create_account("tip_888666#0")
        self.assertTrue(
            self.db.add_website_account_binding(
                self.website_id,
                real_account_id,
                "both",
                self.user_id,
            )
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF")
            cursor.execute(
                """
                INSERT INTO website_account_bindings (website_id, account_id, user_id, role)
                VALUES (?, ?, ?, 'both')
                """,
                (self.website_id, 99999, self.user_id),
            )
            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()

        self.assertEqual(self.db.get_website_senders(self.website_id, self.user_id), [real_account_id])
        self.assertEqual(self.db.get_website_listeners(self.website_id, self.user_id), [real_account_id])


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

    @patch("backend.bot.get_response_url_for_channel", return_value="https://fallback.example/item-1")
    def test_keyword_direct_reply_bypasses_website_template(self, mocked_get_url):
        product = {"id": 103}
        custom_reply = {
            "reply_type": "custom_only",
            "content": "<@1001> https://a.example/item-1",
            "explicit_mentions": True,
        }

        reply_content = DiscordBotClient._generate_reply_content(
            self.client,
            product,
            channel_id="123",
            custom_reply=custom_reply,
            website_config=self.website_config,
        )

        self.assertEqual(reply_content, "<@1001> https://a.example/item-1")
        mocked_get_url.assert_called_once()

    @patch("backend.bot.get_response_url_for_channel", return_value="https://fallback.example/item-1")
    def test_keyword_batched_reply_bypasses_website_template(self, mocked_get_url):
        product = {"id": 104}
        custom_reply = {
            "reply_type": "custom_only",
            "content": "<@1001> https://a.example/item-1\n<@1002> https://b.example/item-2",
            "batched_reply": True,
        }

        reply_content = DiscordBotClient._generate_reply_content(
            self.client,
            product,
            channel_id="123",
            custom_reply=custom_reply,
            website_config=self.website_config,
        )

        self.assertEqual(
            reply_content,
            "<@1001> https://a.example/item-1\n<@1002> https://b.example/item-2",
        )
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


class KeywordSearchMatchingTestCase(unittest.IsolatedAsyncioTestCase):
    class _Author:
        def __init__(self, author_id):
            self.id = author_id

    class _Channel:
        def __init__(self, channel_id):
            self.id = channel_id

    class _Message:
        def __init__(self, content, channel_id=1001, author_id=2002):
            self.content = content
            self.attachments = []
            self.channel = KeywordSearchMatchingTestCase._Channel(channel_id)
            self.author = KeywordSearchMatchingTestCase._Author(author_id)

    async def test_keyword_search_still_schedules_reply_when_message_has_images(self):
        scheduled_jobs = []
        background_tasks = []

        async def search_products_by_keyword(_query):
            return {
                "success": True,
                "products": [
                    {
                        "id": 1,
                        "english_title": "B22",
                        "weidianUrl": "https://weidian.com/item.html?itemID=111",
                        "autoReplyEnabled": True,
                    },
                ],
            }

        async def get_website_configs_by_channel_async(_channel_id):
            return [
                {
                    "id": 21,
                    "name": "acbuy",
                    "display_name": "ACBUY",
                    "reply_template": "{url}",
                    "url_template": "https://www.acbuy.com/product/?id={id}",
                }
            ]

        async def get_keyword_window_settings(_website_config, sender_count=0):
            self.assertEqual(sender_count, 1)
            return (180, 0, 0, "rotation", "immediate")

        async def enqueue_or_dispatch_keyword_reply(_message, product, custom_reply, website_config):
            scheduled_jobs.append(
                {
                    "website_id": website_config["id"],
                    "product_id": product["id"],
                    "content": (custom_reply or {}).get("content", ""),
                }
            )
            return True

        def start_keyword_reply_background_task(coro, task_name):
            task = asyncio.create_task(coro, name=task_name)
            background_tasks.append(task)
            return task

        client = SimpleNamespace(
            user_id=456,
            user_shops=[],
            search_products_by_keyword=search_products_by_keyword,
            get_website_configs_by_channel_async=get_website_configs_by_channel_async,
            _get_keyword_window_settings=get_keyword_window_settings,
            _enqueue_or_dispatch_keyword_reply=enqueue_or_dispatch_keyword_reply,
            _start_keyword_reply_background_task=start_keyword_reply_background_task,
            _get_custom_reply=lambda: None,
        )
        client._generate_reply_content = MethodType(DiscordBotClient._generate_reply_content, client)
        client._get_user_settings_safe = MethodType(DiscordBotClient._get_user_settings_safe, client)
        client._parse_message_filters = MethodType(DiscordBotClient._parse_message_filters, client)

        fake_db = SimpleNamespace(
            get_user_settings=lambda _user_id: {"keyword_match_limit": 0},
            get_website_senders=lambda _website_id, _user_id: [999],
            get_message_filters=lambda: [],
            get_user_website_settings=lambda _user_id, _website_id: {},
        )

        message = self._Message("b22")
        message.attachments = [SimpleNamespace(filename="sample.jpg")]

        with patch.object(database_module, "db", fake_db):
            await DiscordBotClient.handle_keyword_search(client, message)
            if background_tasks:
                await asyncio.gather(*background_tasks)

        self.assertEqual(len(scheduled_jobs), 1)
        self.assertEqual(scheduled_jobs[0]["product_id"], 1)

    async def test_keyword_search_hit_without_generated_reply_still_counts_as_hit(self):
        scheduled_jobs = []

        async def search_products_by_keyword(_query):
            return {
                "success": True,
                "products": [
                    {
                        "id": 1,
                        "english_title": "B22",
                        "weidianUrl": "https://weidian.com/item.html?itemID=111",
                        "autoReplyEnabled": True,
                    },
                    {
                        "id": 2,
                        "english_title": "B30",
                        "weidianUrl": "https://weidian.com/item.html?itemID=222",
                        "autoReplyEnabled": True,
                    },
                ],
            }

        async def get_website_configs_by_channel_async(_channel_id):
            return [
                {
                    "id": 21,
                    "name": "acbuy",
                    "display_name": "ACBUY",
                    "reply_template": "{url}",
                    "url_template": "https://www.acbuy.com/product/?id={id}",
                }
            ]

        async def get_keyword_window_settings(_website_config, sender_count=0):
            return (180, 0, 0, "rotation", "immediate")

        def start_keyword_reply_background_task(coro, task_name):
            scheduled_jobs.append(task_name)
            coro.close()
            return None

        client = SimpleNamespace(
            user_id=456,
            user_shops=[],
            search_products_by_keyword=search_products_by_keyword,
            get_website_configs_by_channel_async=get_website_configs_by_channel_async,
            _get_keyword_window_settings=get_keyword_window_settings,
            _start_keyword_reply_background_task=start_keyword_reply_background_task,
            _get_custom_reply=lambda: None,
        )
        client._generate_reply_content = MethodType(lambda self, *args, **kwargs: "", client)
        client._get_user_settings_safe = MethodType(DiscordBotClient._get_user_settings_safe, client)
        client._parse_message_filters = MethodType(DiscordBotClient._parse_message_filters, client)

        fake_db = SimpleNamespace(
            get_user_settings=lambda _user_id: {"keyword_match_limit": 0},
            get_website_senders=lambda _website_id, _user_id: [999],
            get_message_filters=lambda: [],
            get_user_website_settings=lambda _user_id, _website_id: {},
        )

        with patch.object(database_module, "db", fake_db), patch(
            "backend.bot._find_query_keyword_match",
            return_value={
                "phrase": "match",
                "source": "title",
                "canonical_keyword": "match",
            },
        ):
            result = await DiscordBotClient.handle_keyword_search(client, self._Message("match"))

        self.assertTrue(result)
        self.assertEqual(scheduled_jobs, [])

    async def test_keyword_match_limit_blocks_when_distinct_keyword_count_exceeds_limit(self):
        scheduled = []

        async def search_products_by_keyword(_query):
            return {
                "success": True,
                "products": [
                    {"id": 1, "english_title": "B30", "weidianUrl": "https://weidian.com/item.html?itemID=111"},
                    {"id": 2, "english_title": "B22", "weidianUrl": "https://weidian.com/item.html?itemID=222"},
                    {"id": 3, "english_title": "B44", "weidianUrl": "https://weidian.com/item.html?itemID=333"},
                ],
            }

        async def get_website_configs_by_channel_async(_channel_id):
            return [{"id": 11, "name": "acbuy", "url_template": "https://www.acbuy.com/product/?id={id}"}]

        async def enqueue_or_dispatch_keyword_reply(*_args, **_kwargs):
            scheduled.append("unexpected")
            return True

        def start_keyword_reply_background_task(coro, task_name):
            coro.close()
            scheduled.append(task_name)
            return None

        client = SimpleNamespace(
            user_id=123,
            user_shops=[],
            search_products_by_keyword=search_products_by_keyword,
            get_website_configs_by_channel_async=get_website_configs_by_channel_async,
            _enqueue_or_dispatch_keyword_reply=enqueue_or_dispatch_keyword_reply,
            _start_keyword_reply_background_task=start_keyword_reply_background_task,
        )
        client._get_user_settings_safe = MethodType(DiscordBotClient._get_user_settings_safe, client)
        client._parse_message_filters = MethodType(DiscordBotClient._parse_message_filters, client)

        fake_db = SimpleNamespace(
            get_user_settings=lambda _user_id: {"keyword_match_limit": 2},
            get_message_filters=lambda: [],
            get_user_website_settings=lambda _user_id, _website_id: {},
        )

        with patch.object(database_module, "db", fake_db):
            await DiscordBotClient.handle_keyword_search(client, self._Message("B30 B22 B44"))

        self.assertEqual(scheduled, [])

    async def test_multi_product_reply_keeps_two_links_for_unselected_platform(self):
        scheduled_jobs = []
        background_tasks = []

        async def search_products_by_keyword(_query):
            return {
                "success": True,
                "products": [
                    {
                        "id": 1,
                        "english_title": "B22",
                        "weidianUrl": "https://weidian.com/item.html?itemID=111",
                        "autoReplyEnabled": True,
                    },
                    {
                        "id": 2,
                        "english_title": "B 22",
                        "weidianUrl": "https://weidian.com/item.html?itemID=222",
                        "autoReplyEnabled": False,
                        "custom_reply_text": "仅 OOPBUY 自定义内容",
                        "replyScope": '["oopbuy"]',
                    },
                ],
            }

        async def get_website_configs_by_channel_async(_channel_id):
            return [
                {
                    "id": 21,
                    "name": "acbuy",
                    "display_name": "ACBUY",
                    "reply_template": "{url}",
                    "url_template": "https://www.acbuy.com/product/?id={id}",
                }
            ]

        async def get_keyword_window_settings(_website_config, sender_count=0):
            self.assertEqual(sender_count, 1)
            return (180, 0, 0, "rotation", "immediate")

        async def enqueue_or_dispatch_keyword_reply(_message, _product, custom_reply, website_config):
            scheduled_jobs.append(
                {
                    "website_id": website_config["id"],
                    "content": custom_reply.get("content", ""),
                }
            )
            return True

        def start_keyword_reply_background_task(coro, task_name):
            task = asyncio.create_task(coro, name=task_name)
            background_tasks.append(task)
            return task

        client = SimpleNamespace(
            user_id=456,
            user_shops=[],
            search_products_by_keyword=search_products_by_keyword,
            get_website_configs_by_channel_async=get_website_configs_by_channel_async,
            _get_keyword_window_settings=get_keyword_window_settings,
            _enqueue_or_dispatch_keyword_reply=enqueue_or_dispatch_keyword_reply,
            _start_keyword_reply_background_task=start_keyword_reply_background_task,
            _get_custom_reply=lambda: None,
        )
        client._generate_reply_content = MethodType(DiscordBotClient._generate_reply_content, client)
        client._get_user_settings_safe = MethodType(DiscordBotClient._get_user_settings_safe, client)
        client._parse_message_filters = MethodType(DiscordBotClient._parse_message_filters, client)

        fake_db = SimpleNamespace(
            get_user_settings=lambda _user_id: {"keyword_match_limit": 0},
            get_website_senders=lambda _website_id, _user_id: [999],
            get_message_filters=lambda: [],
            get_user_website_settings=lambda _user_id, _website_id: {},
        )

        with patch.object(database_module, "db", fake_db):
            await DiscordBotClient.handle_keyword_search(client, self._Message("b22"))
            if background_tasks:
                await asyncio.gather(*background_tasks)

        self.assertEqual(len(scheduled_jobs), 1)
        content = scheduled_jobs[0]["content"]
        self.assertIn("https://www.acbuy.com/product/?id=111", content)
        self.assertIn("https://www.acbuy.com/product/?id=222", content)
        self.assertNotIn("仅 OOPBUY 自定义内容", content)

    async def test_b30_query_does_not_schedule_plain_30_product(self):
        scheduled_payloads = []
        background_tasks = []

        async def search_products_by_keyword(_query):
            return {
                "success": True,
                "products": [
                    {
                        "id": 304,
                        "english_title": "Dior B30, B30,B 30,Dior b30s",
                        "weidianUrl": "https://weidian.com/item.html?itemID=7653365800",
                        "autoReplyEnabled": True,
                    },
                    {
                        "id": 365,
                        "english_title": "Dior B30, B30,B 30,Dior b30s",
                        "weidianUrl": "https://weidian.com/item.html?itemID=7653304418",
                        "autoReplyEnabled": True,
                    },
                    {
                        "id": 581,
                        "english_title": "Asics Gel Kayano 30",
                        "weidianUrl": "https://weidian.com/item.html?itemID=7681248139",
                        "autoReplyEnabled": True,
                    },
                ],
            }

        async def get_website_configs_by_channel_async(_channel_id):
            return [
                {
                    "id": 21,
                    "name": "weidian",
                    "display_name": "WEIDIAN",
                    "reply_template": "{url}",
                    "url_template": "https://weidian.com/item.html?itemID={id}",
                }
            ]

        async def get_keyword_window_settings(_website_config, sender_count=0):
            self.assertEqual(sender_count, 1)
            return (180, 0, 0, "rotation", "immediate")

        async def enqueue_or_dispatch_keyword_reply(_message, product, custom_reply, _website_config):
            scheduled_payloads.append(
                {
                    "product_id": product["id"],
                    "content": custom_reply.get("content", ""),
                }
            )
            return True

        def start_keyword_reply_background_task(coro, task_name):
            task = asyncio.create_task(coro, name=task_name)
            background_tasks.append(task)
            return task

        client = SimpleNamespace(
            user_id=456,
            user_shops=[],
            search_products_by_keyword=search_products_by_keyword,
            get_website_configs_by_channel_async=get_website_configs_by_channel_async,
            _get_keyword_window_settings=get_keyword_window_settings,
            _enqueue_or_dispatch_keyword_reply=enqueue_or_dispatch_keyword_reply,
            _start_keyword_reply_background_task=start_keyword_reply_background_task,
            _get_custom_reply=lambda: None,
        )
        client._generate_reply_content = MethodType(DiscordBotClient._generate_reply_content, client)
        client._get_user_settings_safe = MethodType(DiscordBotClient._get_user_settings_safe, client)
        client._parse_message_filters = MethodType(DiscordBotClient._parse_message_filters, client)

        fake_db = SimpleNamespace(
            get_user_settings=lambda _user_id: {"keyword_match_limit": 0},
            get_website_senders=lambda _website_id, _user_id: [999],
            get_message_filters=lambda: [],
            get_user_website_settings=lambda _user_id, _website_id: {},
        )

        with patch.object(database_module, "db", fake_db):
            await DiscordBotClient.handle_keyword_search(client, self._Message("b 30"))
            if background_tasks:
                await asyncio.gather(*background_tasks)

        self.assertEqual(len(scheduled_payloads), 1)
        self.assertEqual(scheduled_payloads[0]["product_id"], 304)
        self.assertIn("7653365800", scheduled_payloads[0]["content"])
        self.assertIn("7653304418", scheduled_payloads[0]["content"])
        self.assertNotIn("7681248139", scheduled_payloads[0]["content"])


class OnMessageKeywordImagePriorityTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_on_message_skips_image_stage_when_keyword_reply_already_matched(self):
        website_configs = [{"id": 7, "name": "finds"}]
        client = SimpleNamespace(
            running=True,
            user=SimpleNamespace(id=999999, name="listener"),
            user_id=42,
            account_id=3,
            role='both',
            _is_plain_text_keyword_trigger_candidate=lambda message: True,
            _should_ignore_mass_or_activity_message=lambda message: False,
            _notify_direct_interaction_if_needed=AsyncMock(),
            _is_account_bound_in_channel=AsyncMock(return_value=(True, website_configs)),
            _should_filter_message=lambda message: False,
            _get_user_settings_safe=AsyncMock(
                return_value={"keyword_reply_enabled": 1, "image_reply_enabled": 1}
            ),
            get_website_configs_by_channel_async=AsyncMock(return_value=website_configs),
            _exclude_blocked_website_configs=AsyncMock(return_value=website_configs),
            _get_user_website_settings_map_for_configs=AsyncMock(return_value={}),
            _apply_website_block_user_triggers=AsyncMock(return_value=set()),
            _log_message_skip=lambda message, reason: None,
            handle_keyword_forward=AsyncMock(return_value=None),
            handle_keyword_search=AsyncMock(return_value=True),
            handle_image=AsyncMock(return_value=None),
            _message_preview=lambda message, limit=50: message.content[:limit],
        )
        client._run_message_stage_with_timeout = MethodType(
            DiscordBotClient._run_message_stage_with_timeout,
            client,
        )

        message = SimpleNamespace(
            author=SimpleNamespace(id=222, bot=False),
            webhook_id=None,
            guild=SimpleNamespace(id=1),
            mentions=[],
            reference=None,
            id=123456789,
            channel=SimpleNamespace(id=987654321, name='finds'),
            content='b22 sample',
            attachments=[
                SimpleNamespace(
                    filename='sample.jpg',
                    content_type='image/jpeg',
                )
            ],
        )

        with patch('backend.bot.mark_message_as_processed', return_value=True):
            await DiscordBotClient.on_message(client, message)

        client.handle_keyword_search.assert_awaited_once_with(
            message,
            website_configs_override=website_configs,
            allow_keyword_image_search=False,
        )
        client.handle_image.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
