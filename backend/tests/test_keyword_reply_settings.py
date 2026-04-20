import os
import tempfile
import unittest
import uuid
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.database import Database
from backend.bot import DiscordBotClient
from backend import bot as bot_module
from backend.rotation_settings import resolve_rotation_settings_update


class TestDatabase(Database):
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_sqlite_database()


class KeywordReplySettingsTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "metadata.db")
        self.db = TestDatabase(self.db_path)
        self.user_id = self._create_user()
        self.website_id = self._create_website()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_user(self) -> int:
        username = f"test_user_{uuid.uuid4().hex[:10]}"
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

    def _create_website(self) -> int:
        name = f"site_{uuid.uuid4().hex[:8]}"
        success = self.db.add_website_config(
            name=name,
            display_name="Test Site",
            url_template="https://example.com/{id}",
            id_pattern=r"\\d+",
        )
        self.assertTrue(success)
        websites = self.db.get_website_configs()
        website = next((item for item in websites if item["name"] == name), None)
        self.assertIsNotNone(website)
        return website["id"]

    def test_get_user_website_settings_contains_keyword_batch_default(self):
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)

        self.assertIn("reply_mode", settings)
        self.assertEqual(settings["reply_mode"], "rotation")
        self.assertIn("keyword_reply_batch_size", settings)
        self.assertEqual(settings["keyword_reply_batch_size"], 0)
        self.assertIn("keyword_reply_interval", settings)
        self.assertEqual(settings["keyword_reply_interval"], 180)
        self.assertIn("keyword_batch_dispatch_mode", settings)
        self.assertEqual(settings["keyword_batch_dispatch_mode"], "immediate")
        self.assertIn("thread_reply_enabled", settings)
        self.assertEqual(settings["thread_reply_enabled"], 0)
        self.assertIn("forum_post_reply_enabled", settings)
        self.assertEqual(settings["forum_post_reply_enabled"], 0)

    def test_user_settings_persist_keyword_best_match_image_toggle(self):
        ok = self.db.update_user_settings(
            user_id=self.user_id,
            keyword_reply_send_best_match_image=1,
        )

        self.assertTrue(ok)
        settings = self.db.get_user_settings(self.user_id)
        self.assertEqual(settings["keyword_reply_send_best_match_image"], 1)

    def test_user_settings_persist_review_bark_fields(self):
        ok = self.db.update_user_settings(
            user_id=self.user_id,
            bark_server_url="https://api.day.app",
            bark_device_key="device-key",
            review_bark_enabled=1,
            review_bark_mode="interval",
            review_bark_count_threshold=8,
            review_bark_interval_minutes=45,
            review_bark_last_notified_at="2026-04-20T10:00:00+08:00",
            review_bark_last_pending_count=3,
        )

        self.assertTrue(ok)
        settings = self.db.get_user_settings(self.user_id)
        self.assertEqual(settings["review_bark_enabled"], 1)
        self.assertEqual(settings["review_bark_mode"], "interval")
        self.assertEqual(settings["review_bark_count_threshold"], 8)
        self.assertEqual(settings["review_bark_interval_minutes"], 45)
        self.assertEqual(settings["review_bark_last_notified_at"], "2026-04-20T10:00:00+08:00")
        self.assertEqual(settings["review_bark_last_pending_count"], 3)

    def test_count_pending_review_items_only_counts_pending_status(self):
        first_id = self.db.add_keyword_reply_review_item({
            "user_id": self.user_id,
            "website_id": self.website_id,
            "channel_id": "100",
            "guild_id": "200",
            "guild_name": "Guild",
            "channel_name": "channel",
            "account_ids": [1],
            "account_names": ["sender-1"],
            "sender_id": "300",
            "sender_name": "sender",
            "content": "content-1",
            "source_content": "source-1",
            "message_id": "400",
            "reply_mode": "keyword",
            "status": "pending",
            "payload": {},
        })
        second_id = self.db.add_keyword_reply_review_item({
            "user_id": self.user_id,
            "website_id": self.website_id,
            "channel_id": "101",
            "guild_id": "201",
            "guild_name": "Guild",
            "channel_name": "channel",
            "account_ids": [2],
            "account_names": ["sender-2"],
            "sender_id": "301",
            "sender_name": "sender",
            "content": "content-2",
            "source_content": "source-2",
            "message_id": "401",
            "reply_mode": "keyword",
            "status": "pending",
            "payload": {},
        })

        self.assertGreater(first_id, 0)
        self.assertGreater(second_id, 0)
        self.assertEqual(self.db.count_pending_keyword_reply_review_items(self.user_id), 2)

        self.assertTrue(self.db.update_keyword_reply_review_item_status(first_id, "approved"))
        self.assertEqual(self.db.count_pending_keyword_reply_review_items(self.user_id), 1)

    def test_review_bark_count_mode_only_triggers_on_new_threshold_bucket(self):
        self.assertTrue(
            bot_module._should_send_review_queue_bark_count_notification(
                pending_count=5,
                threshold=5,
                last_pending_count=4,
            )
        )
        self.assertFalse(
            bot_module._should_send_review_queue_bark_count_notification(
                pending_count=6,
                threshold=5,
                last_pending_count=5,
            )
        )
        self.assertTrue(
            bot_module._should_send_review_queue_bark_count_notification(
                pending_count=10,
                threshold=5,
                last_pending_count=6,
            )
        )

    def test_review_bark_interval_mode_checks_elapsed_time(self):
        self.assertFalse(
            bot_module._should_send_review_queue_bark_interval_notification(
                pending_count=3,
                interval_minutes=60,
                last_notified_at=None,
                now=datetime.fromisoformat("2026-04-20T12:00:00+08:00"),
            )
        )
        self.assertFalse(
            bot_module._should_send_review_queue_bark_interval_notification(
                pending_count=0,
                interval_minutes=60,
                last_notified_at=None,
                now=datetime.fromisoformat("2026-04-20T12:00:00+08:00"),
            )
        )
        self.assertFalse(
            bot_module._should_send_review_queue_bark_interval_notification(
                pending_count=3,
                interval_minutes=60,
                last_notified_at="2026-04-20T11:30:00+08:00",
                now=datetime.fromisoformat("2026-04-20T12:00:00+08:00"),
            )
        )
        self.assertTrue(
            bot_module._should_send_review_queue_bark_interval_notification(
                pending_count=3,
                interval_minutes=60,
                last_notified_at="2026-04-20T10:30:00+08:00",
                now=datetime.fromisoformat("2026-04-20T12:00:00+08:00"),
            )
        )

    def test_update_user_website_rotation_persists_keyword_batch_size(self):
        try:
            success = self.db.update_user_website_rotation(
                self.user_id,
                self.website_id,
                rotation_interval=300,
                rotation_enabled=1,
                reply_mode="keyword",
                keyword_reply_interval=45,
                keyword_reply_batch_size=2,
                keyword_batch_dispatch_mode="window_end",
            )
        except TypeError as exc:
            self.fail(f"keyword reply settings update support is missing: {exc}")

        self.assertTrue(success)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["rotation_interval"], 300)
        self.assertEqual(settings["rotation_enabled"], 0)
        self.assertEqual(settings["reply_mode"], "keyword")
        self.assertEqual(settings["keyword_reply_interval"], 45)
        self.assertEqual(settings["keyword_reply_batch_size"], 2)
        self.assertEqual(settings["keyword_batch_dispatch_mode"], "window_end")

    def test_keyword_window_settings_use_keyword_reply_interval_instead_of_rotation_interval(self):
        client = SimpleNamespace(
            user_id=self.user_id,
            _get_user_website_settings_safe=AsyncMock(return_value={
                "reply_mode": "keyword",
                "rotation_interval": 300,
                "keyword_reply_interval": 45,
                "keyword_reply_batch_size": 3,
            }),
        )

        interval_seconds, batch_size, rotation_enabled, reply_mode, dispatch_mode = asyncio.run(
            DiscordBotClient._get_keyword_window_settings(
                client,
                {
                    "id": self.website_id,
                    "reply_mode": "rotation",
                    "rotation_interval": 180,
                    "keyword_reply_interval": 60,
                    "keyword_reply_batch_size": 2,
                    "keyword_batch_dispatch_mode": "immediate",
                },
                sender_count=1,
            )
        )

        self.assertEqual(interval_seconds, 45)
        self.assertEqual(batch_size, 3)
        self.assertEqual(rotation_enabled, 0)
        self.assertEqual(reply_mode, "keyword")
        self.assertEqual(dispatch_mode, "immediate")

    def test_rotation_mode_keeps_rotation_enabled_for_single_sender(self):
        effective = resolve_rotation_settings_update(
            current_settings={
                "reply_mode": "rotation",
                "rotation_interval": 180,
                "rotation_enabled": 1,
                "keyword_reply_interval": 180,
                "keyword_reply_batch_size": 0,
                "keyword_batch_dispatch_mode": "immediate",
            },
            sender_count=1,
            reply_mode="rotation",
            keyword_reply_interval=30,
            keyword_reply_batch_size=2,
            keyword_batch_dispatch_mode="window_end",
        )

        self.assertEqual(effective["rotation_interval"], 180)
        self.assertEqual(effective["rotation_enabled"], 1)
        self.assertEqual(effective["reply_mode"], "rotation")
        self.assertEqual(effective["keyword_reply_interval"], 30)
        self.assertEqual(effective["keyword_reply_batch_size"], 2)
        self.assertEqual(effective["keyword_batch_dispatch_mode"], "window_end")

    def test_keyword_mode_rejected_for_multiple_senders(self):
        with self.assertRaisesRegex(ValueError, "仅绑定1个发送账号时可切换到关键词模式"):
            resolve_rotation_settings_update(
                current_settings={
                "reply_mode": "rotation",
                "rotation_interval": 180,
                "rotation_enabled": 1,
                "keyword_reply_interval": 180,
                "keyword_reply_batch_size": 0,
                "keyword_batch_dispatch_mode": "immediate",
            },
            sender_count=2,
            reply_mode="keyword",
        )

    def test_keyword_dispatch_mode_rejected_for_multiple_senders(self):
        with self.assertRaisesRegex(ValueError, "仅绑定1个发送账号时可设置单轮关键词时间和上限"):
            resolve_rotation_settings_update(
                current_settings={
                    "reply_mode": "rotation",
                    "rotation_interval": 180,
                    "rotation_enabled": 1,
                    "keyword_reply_interval": 180,
                    "keyword_reply_batch_size": 0,
                    "keyword_batch_dispatch_mode": "immediate",
                },
                sender_count=2,
                keyword_batch_dispatch_mode="window_end",
            )

    def test_default_mode_is_persisted_and_disables_rotation(self):
        effective = resolve_rotation_settings_update(
            current_settings={
                "reply_mode": "rotation",
                "rotation_interval": 180,
                "rotation_enabled": 1,
                "keyword_reply_interval": 45,
                "keyword_reply_batch_size": 2,
                "keyword_batch_dispatch_mode": "window_end",
            },
            sender_count=3,
            reply_mode="default",
        )

        self.assertEqual(effective["reply_mode"], "default")
        self.assertEqual(effective["rotation_enabled"], 0)
        self.assertEqual(effective["rotation_interval"], 180)
        self.assertEqual(effective["keyword_reply_interval"], 45)
        self.assertEqual(effective["keyword_reply_batch_size"], 2)
        self.assertEqual(effective["keyword_batch_dispatch_mode"], "window_end")

        success = self.db.update_user_website_rotation(
            self.user_id,
            self.website_id,
            rotation_interval=180,
            rotation_enabled=0,
            reply_mode="default",
            keyword_reply_interval=45,
            keyword_reply_batch_size=2,
            keyword_batch_dispatch_mode="window_end",
        )

        self.assertTrue(success)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["reply_mode"], "default")
        self.assertEqual(settings["rotation_enabled"], 0)
        self.assertEqual(settings["keyword_batch_dispatch_mode"], "window_end")

    def test_default_mode_disables_rotation_without_using_keyword_window(self):
        effective = resolve_rotation_settings_update(
            current_settings={
                "reply_mode": "rotation",
                "rotation_interval": 180,
                "rotation_enabled": 1,
                "keyword_reply_interval": 45,
                "keyword_reply_batch_size": 3,
                "keyword_batch_dispatch_mode": "window_end",
            },
            sender_count=2,
            reply_mode="default",
        )

        self.assertEqual(effective["reply_mode"], "default")
        self.assertEqual(effective["rotation_enabled"], 0)
        self.assertEqual(effective["rotation_interval"], 180)
        self.assertEqual(effective["keyword_reply_interval"], 45)
        self.assertEqual(effective["keyword_reply_batch_size"], 3)
        self.assertEqual(effective["keyword_batch_dispatch_mode"], "window_end")

    def test_database_persists_default_mode(self):
        success = self.db.update_user_website_rotation(
            self.user_id,
            self.website_id,
            rotation_interval=180,
            rotation_enabled=0,
            reply_mode="default",
            keyword_reply_interval=45,
            keyword_reply_batch_size=2,
            keyword_batch_dispatch_mode="window_end",
        )

        self.assertTrue(success)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["reply_mode"], "default")
        self.assertEqual(settings["rotation_enabled"], 0)
        self.assertEqual(settings["keyword_reply_interval"], 45)
        self.assertEqual(settings["keyword_reply_batch_size"], 2)
        self.assertEqual(settings["keyword_batch_dispatch_mode"], "window_end")

    def test_database_persists_all_mode_with_zero_interval(self):
        success = self.db.update_user_website_rotation(
            self.user_id,
            self.website_id,
            rotation_interval=0,
            rotation_enabled=0,
            reply_mode="all",
        )

        self.assertTrue(success)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["reply_mode"], "all")
        self.assertEqual(settings["rotation_enabled"], 0)
        self.assertEqual(settings["rotation_interval"], 0)

    def test_database_persists_thread_reply_toggle(self):
        success = self.db.update_user_website_rotation(
            self.user_id,
            self.website_id,
            thread_reply_enabled=1,
        )

        self.assertTrue(success)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["thread_reply_enabled"], 1)

    def test_database_persists_forum_post_reply_toggle(self):
        success = self.db.update_user_website_rotation(
            self.user_id,
            self.website_id,
            forum_post_reply_enabled=1,
        )

        self.assertTrue(success)
        settings = self.db.get_user_website_settings(self.user_id, self.website_id)
        self.assertEqual(settings["forum_post_reply_enabled"], 1)


if __name__ == "__main__":
    unittest.main()
