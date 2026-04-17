import os
import tempfile
import unittest
import uuid

from backend.database import Database


class TestDatabase(Database):
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_sqlite_database()


class WebsiteBlockedUsersTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "metadata.db")
        self.db = TestDatabase(self.db_path)
        self.user_id = self._create_user()

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
            user_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO website_configs
                (name, display_name, url_template, id_pattern, badge_color, reply_template, reply_language)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"site_{uuid.uuid4().hex[:6]}",
                    "Test Site",
                    "https://example.com/{id}",
                    "{id}",
                    "blue",
                    "{url}",
                    '["en"]',
                ),
            )
            conn.commit()
            self.website_id = cursor.lastrowid
            return int(user_id)

    def test_upsert_and_get_website_blocked_users(self):
        self.db.upsert_website_blocked_user(
            user_id=self.user_id,
            website_id=self.website_id,
            discord_user_id="778899",
            discord_username="buyer_one",
            trigger_keyword="stop replying",
        )

        rows = self.db.get_website_blocked_users(self.user_id, self.website_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["discord_user_id"], "778899")
        self.assertEqual(rows[0]["discord_username"], "buyer_one")
        self.assertEqual(rows[0]["trigger_keyword"], "stop replying")

    def test_upsert_updates_username_without_duplicate_rows(self):
        self.db.upsert_website_blocked_user(
            user_id=self.user_id,
            website_id=self.website_id,
            discord_user_id="778899",
            discord_username="old_name",
            trigger_keyword="bye",
        )
        self.db.upsert_website_blocked_user(
            user_id=self.user_id,
            website_id=self.website_id,
            discord_user_id="778899",
            discord_username="new_name",
            trigger_keyword="bye",
        )

        rows = self.db.get_website_blocked_users(self.user_id, self.website_id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["discord_username"], "new_name")

    def test_delete_website_blocked_user_removes_entry(self):
        self.db.upsert_website_blocked_user(
            user_id=self.user_id,
            website_id=self.website_id,
            discord_user_id="778899",
            discord_username="buyer_one",
            trigger_keyword="bye",
        )

        deleted = self.db.delete_website_blocked_user(
            self.user_id,
            self.website_id,
            "778899",
        )

        self.assertTrue(deleted)
        self.assertEqual(self.db.get_website_blocked_users(self.user_id, self.website_id), [])

    def test_get_blocked_website_ids_for_discord_user_filters_by_candidate_websites(self):
        other_website_name = f"site_{uuid.uuid4().hex[:6]}"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO website_configs
                (name, display_name, url_template, id_pattern, badge_color, reply_template, reply_language)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    other_website_name,
                    "Other Site",
                    "https://example.com/{id}",
                    "{id}",
                    "green",
                    "{url}",
                    '["en"]',
                ),
            )
            conn.commit()
            other_website_id = cursor.lastrowid

        self.db.upsert_website_blocked_user(
            user_id=self.user_id,
            website_id=self.website_id,
            discord_user_id="778899",
            discord_username="buyer_one",
            trigger_keyword="bye",
        )
        self.db.upsert_website_blocked_user(
            user_id=self.user_id,
            website_id=other_website_id,
            discord_user_id="778899",
            discord_username="buyer_one",
            trigger_keyword="stop",
        )

        blocked_ids = self.db.get_blocked_website_ids_for_discord_user(
            user_id=self.user_id,
            discord_user_id="778899",
            candidate_website_ids=[self.website_id],
        )

        self.assertEqual(blocked_ids, {self.website_id})
