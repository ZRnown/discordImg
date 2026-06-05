import tempfile
import unittest
from pathlib import Path

from backend.database import Database


class SkippedImageHistoryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(str(self.db_path))
        self.product_id = self._create_product()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_product(self) -> int:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO products (
                    product_url,
                    title,
                    english_title,
                    shop_name
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    "https://weidian.com/item.html?itemID=1234567890",
                    "测试商品",
                    "Test Product",
                    "test-shop",
                ),
            )
            product_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO product_images (product_id, image_index, image_path)
                VALUES (?, ?, ?)
                """,
                (product_id, 0, "/tmp/test-product-0.jpg"),
            )
            conn.commit()
            return product_id

    def test_skipped_image_history_round_trip(self):
        history_id = self.db.add_skipped_image_history(
            query_image_path="/tmp/query-1.jpg",
            similarity=0.42,
            threshold=0.6,
            discord_message_id="1001",
            discord_channel_id="2002",
            discord_channel_name="鞋服群",
            discord_author_id="3003",
            discord_author_name="buyer",
            message_content="帮我看看这双鞋",
            matched_product_id=self.product_id,
            matched_image_index=0,
        )

        self.assertIsInstance(history_id, int)

        result = self.db.get_skipped_image_history(limit=10, offset=0)
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["history"]), 1)

        row = result["history"][0]
        self.assertEqual(row["query_image_path"], "/tmp/query-1.jpg")
        self.assertEqual(row["similarity"], 0.42)
        self.assertEqual(row["threshold"], 0.6)
        self.assertEqual(row["discord_message_id"], "1001")
        self.assertEqual(row["discord_channel_name"], "鞋服群")
        self.assertEqual(row["discord_author_name"], "buyer")
        self.assertEqual(row["message_content"], "帮我看看这双鞋")
        self.assertEqual(row["matched_product_id"], self.product_id)
        self.assertEqual(row["matched_image_index"], 0)
        self.assertEqual(row["title"], "测试商品")

    def test_clear_skipped_image_history_removes_rows(self):
        self.db.add_skipped_image_history(
            query_image_path="/tmp/query-2.jpg",
            similarity=0.12,
            threshold=0.6,
            discord_message_id="m-1",
            discord_channel_id="c-1",
            discord_channel_name="test",
            discord_author_id="u-1",
            discord_author_name="buyer",
            message_content="",
            matched_product_id=None,
            matched_image_index=None,
        )

        self.assertTrue(self.db.clear_skipped_image_history())
        result = self.db.get_skipped_image_history(limit=10, offset=0)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["history"], [])

    def test_search_history_returns_all_rows_for_page_limit_in_desc_order(self):
        for index, similarity in enumerate((0.31, 0.42, 0.53), start=1):
            self.db.add_search_history(
                query_image_path=f"/tmp/search-{index}.jpg",
                matched_product_id=self.product_id,
                matched_image_index=0,
                similarity=similarity,
                threshold=0.6,
            )

        result = self.db.get_search_history(limit=10, offset=0)

        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["history"]), 3)
        self.assertEqual(
            [item["query_image_path"] for item in result["history"]],
            ["/tmp/search-3.jpg", "/tmp/search-2.jpg", "/tmp/search-1.jpg"],
        )

    def test_cleanup_search_query_images_removes_expired_files_and_clears_paths(self):
        expired_search_path = Path(self.temp_dir.name) / "expired-search.jpg"
        expired_search_path.write_bytes(b"expired-search")
        fresh_search_path = Path(self.temp_dir.name) / "fresh-search.jpg"
        fresh_search_path.write_bytes(b"fresh-search")
        expired_skipped_path = Path(self.temp_dir.name) / "expired-skipped.jpg"
        expired_skipped_path.write_bytes(b"expired-skipped")

        self.db.add_search_history(
            query_image_path=str(expired_search_path),
            matched_product_id=None,
            matched_image_index=None,
            similarity=0.5,
            threshold=0.6,
        )
        self.db.add_search_history(
            query_image_path=str(fresh_search_path),
            matched_product_id=None,
            matched_image_index=None,
            similarity=0.7,
            threshold=0.6,
        )
        self.db.add_skipped_image_history(
            query_image_path=str(expired_skipped_path),
            similarity=0.3,
            threshold=0.6,
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE search_history SET search_time = datetime('now', '-2 day') WHERE query_image_path = ?",
                (str(expired_search_path),),
            )
            cursor.execute(
                "UPDATE skipped_image_history SET created_at = datetime('now', '-2 day') WHERE query_image_path = ?",
                (str(expired_skipped_path),),
            )
            conn.commit()

        summary = self.db.cleanup_search_query_images(max_age_days=1)

        self.assertEqual(summary["deleted_files"], 2)
        self.assertEqual(summary["cleared_search_history"], 1)
        self.assertEqual(summary["cleared_skipped_image_history"], 1)
        self.assertFalse(expired_search_path.exists())
        self.assertFalse(expired_skipped_path.exists())
        self.assertTrue(fresh_search_path.exists())

        history = self.db.get_search_history(limit=10, offset=0)["history"]
        cleared_row = next(item for item in history if item["similarity"] == 0.5)
        fresh_row = next(item for item in history if item["similarity"] == 0.7)
        self.assertEqual(cleared_row["query_image_path"], "")
        self.assertEqual(fresh_row["query_image_path"], str(fresh_search_path))

        skipped_history = self.db.get_skipped_image_history(limit=10, offset=0)["history"]
        self.assertEqual(skipped_history[0]["query_image_path"], "")


if __name__ == "__main__":
    unittest.main()
