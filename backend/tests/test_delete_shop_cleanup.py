import os
import sqlite3
import tempfile
import unittest

from backend.database import Database


class DeleteShopCleanupTestCase(unittest.TestCase):
    def test_delete_shop_removes_products_images_cache_and_history_links(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "metadata.db")
            image_path = os.path.join(tmpdir, "product.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(b"image")

            db = Database(db_path)
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO shops (shop_id, name, product_count) VALUES (?, ?, ?)",
                    ("shop-1", "Shop One", 1),
                )
                cursor.execute(
                    "INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                    (7, "owner", "hash", "user"),
                )
                cursor.execute(
                    "INSERT INTO user_shop_permissions (user_id, shop_id) VALUES (?, ?)",
                    (7, "shop-1"),
                )
                cursor.execute(
                    """
                    INSERT INTO products (product_url, title, shop_name)
                    VALUES (?, ?, ?)
                    """,
                    ("https://example.com/item/1", "Product One", "Shop One"),
                )
                product_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO product_images (product_id, image_path, image_index)
                    VALUES (?, ?, ?)
                    """,
                    (product_id, image_path, 0),
                )
                image_db_id = cursor.lastrowid
                cursor.execute(
                    """
                    INSERT INTO product_image_retrieval_cache
                        (image_db_id, strategy_name, embedding_json)
                    VALUES (?, ?, ?)
                    """,
                    (image_db_id, "simple", "[0.1]"),
                )
                cursor.execute(
                    """
                    INSERT INTO search_history
                        (query_image_path, matched_product_id, matched_image_index, similarity, threshold)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("query.jpg", product_id, 0, 0.9, 0.8),
                )
                cursor.execute(
                    """
                    INSERT INTO skipped_image_history
                        (query_image_path, matched_product_id, matched_image_index, similarity, threshold)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("query2.jpg", product_id, 0, 0.7, 0.8),
                )
                conn.commit()

            result = db.delete_shop("shop-1")

            self.assertTrue(result["success"])
            self.assertEqual(result["deleted_products"], 1)
            self.assertEqual(result["deleted_images"], 1)
            self.assertFalse(os.path.exists(image_path))

            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                for table_name in (
                    "shops",
                    "user_shop_permissions",
                    "products",
                    "product_images",
                    "product_image_retrieval_cache",
                ):
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    self.assertEqual(cursor.fetchone()[0], 0, table_name)
                cursor.execute("SELECT matched_product_id FROM search_history")
                self.assertIsNone(cursor.fetchone()[0])
                cursor.execute("SELECT matched_product_id FROM skipped_image_history")
                self.assertIsNone(cursor.fetchone()[0])

    def test_delete_shop_reports_missing_shop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(os.path.join(tmpdir, "metadata.db"))

            result = db.delete_shop("missing")

            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "shop_not_found")


if __name__ == "__main__":
    unittest.main()
