import os
import sys
import tempfile
import types
import unittest

if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: False
    sys.modules["dotenv"] = dotenv_stub

from backend.database import Database


class DiscordAccountAutostartTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "metadata.db")
        self.db = Database(self.db_path)

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, role, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (7, "user-seven", "hashed_pw", "user", 1),
            )
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, role, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (8, "user-eight", "hashed_pw", "user", 1),
            )
            conn.executemany(
                """
                INSERT INTO discord_accounts (username, token, user_id)
                VALUES (?, ?, ?)
                """,
                [
                    ("alpha", "token-alpha", 7),
                    ("beta", "token-beta", 7),
                    ("gamma", "token-gamma", 8),
                ],
            )
            conn.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_discord_accounts_do_not_autostart_by_default(self):
        self.assertEqual(self.db.get_discord_accounts_marked_for_autostart(), [])

    def test_set_discord_accounts_autostart_by_user_marks_only_target_users_accounts(self):
        updated_count = self.db.set_discord_accounts_autostart_by_user(7, True)

        self.assertEqual(updated_count, 2)
        autostart_accounts = self.db.get_discord_accounts_marked_for_autostart()
        self.assertEqual(
            {account["username"] for account in autostart_accounts},
            {"alpha", "beta"},
        )

    def test_disabling_autostart_clears_user_accounts(self):
        self.db.set_discord_accounts_autostart_by_user(7, True)

        updated_count = self.db.set_discord_accounts_autostart_by_user(7, False)

        self.assertEqual(updated_count, 2)
        self.assertEqual(self.db.get_discord_accounts_marked_for_autostart(), [])


if __name__ == "__main__":
    unittest.main()
