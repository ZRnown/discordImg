import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.database import Database


class ShopPermissionsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        db_path = Path(self._tmpdir.name) / "metadata.db"
        self.test_db = Database(db_path=str(db_path))
        self._seed_user(2, "user-two")
        self._seed_user(3, "user-three")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _seed_user(self, user_id: int, username: str) -> None:
        with self.test_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO users (id, username, password_hash, role, is_active)
                VALUES (?, ?, ?, 'user', 1)
                ''',
                (user_id, username, f"hashed-{username}"),
            )
            conn.commit()

    def test_add_shop_auto_assigns_owner_permission(self):
        self.assertTrue(self.test_db.add_shop("1713062461", "测试店铺", owner_user_id=2))
        self.assertEqual(self.test_db.get_user_shops(2), ["1713062461"])

    def test_delete_shop_cleans_user_permissions(self):
        self.assertTrue(self.test_db.add_shop("1713062461", "测试店铺", owner_user_id=2))
        self.assertTrue(self.test_db.add_user_shop_permission(3, "1713062461"))

        self.assertEqual(sorted(self.test_db.get_user_ids_by_shop("1713062461")), [2, 3])
        self.assertTrue(self.test_db.delete_shop("1713062461"))
        self.assertEqual(self.test_db.get_user_ids_by_shop("1713062461"), [])
        self.assertEqual(self.test_db.get_user_shops(2), [])
        self.assertEqual(self.test_db.get_user_shops(3), [])


if __name__ == "__main__":
    unittest.main()
