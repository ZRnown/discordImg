import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from backend import app as app_module


class SearchSimilarTextApiTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._create_schema()
        self._seed_product()
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.conn.close()

    def _create_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                product_url TEXT,
                title TEXT,
                english_title TEXT,
                title_translations TEXT,
                description TEXT,
                ruleEnabled BOOLEAN,
                min_delay INTEGER,
                max_delay INTEGER,
                created_at TEXT,
                cnfans_url TEXT,
                shop_name TEXT,
                custom_reply_text TEXT,
                custom_reply_images TEXT,
                custom_image_urls TEXT,
                image_source TEXT,
                reply_scope TEXT,
                per_website_reply_settings TEXT,
                uploaded_reply_images TEXT,
                item_id TEXT
            );
            CREATE TABLE product_images (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                image_index INTEGER NOT NULL
            );
            """
        )

    def _seed_product(self):
        self.conn.execute(
            """
            INSERT INTO products (
                id, product_url, title, english_title, title_translations, description,
                ruleEnabled, min_delay, max_delay, created_at, cnfans_url, shop_name,
                custom_reply_text, custom_reply_images, custom_image_urls, image_source,
                reply_scope, per_website_reply_settings, uploaded_reply_images, item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "https://weidian.com/item.html?itemID=7724464447",
                "pur牛仔短裤top",
                "pur denim shorts top",
                json.dumps({"en": "pur denim shorts top"}),
                "demo product",
                1,
                1,
                3,
                "2026-04-04 00:00:00",
                None,
                "demo shop",
                None,
                None,
                None,
                "product",
                "all",
                None,
                None,
                "7724464447",
            ),
        )
        self.conn.execute(
            """
            INSERT INTO products (
                id, product_url, title, english_title, title_translations, description,
                ruleEnabled, min_delay, max_delay, created_at, cnfans_url, shop_name,
                custom_reply_text, custom_reply_images, custom_image_urls, image_source,
                reply_scope, per_website_reply_settings, uploaded_reply_images, item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                2,
                "https://weidian.com/item.html?itemID=5277",
                "鲨.鱼卫裤系列",
                "Shark-Fish Sweatpants Collection",
                json.dumps({"en": "Shark-Fish Sweatpants Collection"}),
                "demo shark product",
                1,
                1,
                3,
                "2026-04-05 00:00:00",
                None,
                "vibeo",
                None,
                None,
                None,
                "product",
                "all",
                None,
                None,
                None,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO product_images (id, product_id, image_path, image_index)
            VALUES (?, ?, ?, ?)
            """,
            (1, 1, "/tmp/pur-0.jpg", 0),
        )
        self.conn.execute(
            """
            INSERT INTO product_images (id, product_id, image_path, image_index)
            VALUES (?, ?, ?, ?)
            """,
            (2, 2, "/tmp/shark-0.jpg", 0),
        )
        self.conn.commit()

    @contextmanager
    def _fake_get_connection(self):
        yield self.conn

    def test_marketplace_link_query_returns_direct_item_match(self):
        payload = {
            "query": "https://www.acbuy.com/product?id=7724464447&source=WD&u=XNX5L3",
            "limit": 5,
        }

        with patch.object(app_module.db, "get_connection", self._fake_get_connection):
            response = self.client.post("/api/search_similar_text", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(
            data["products"][0]["product_url"],
            "https://weidian.com/item.html?itemID=7724464447",
        )
        self.assertEqual(data["products"][0]["title"], "pur牛仔短裤top")

    def test_four_word_hyphenated_english_title_returns_match(self):
        payload = {
            "query": "Shark-Fish Sweatpants Collection",
            "limit": 5,
        }

        with patch.object(app_module.db, "get_connection", self._fake_get_connection):
            response = self.client.post("/api/search_similar_text", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["products"][0]["id"], 2)


if __name__ == "__main__":
    unittest.main()
