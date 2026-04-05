import json
import sqlite3
from pathlib import Path

from backend.database import Database


def test_database_exposes_strategy_cache_in_searchable_records(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    test_db = Database(db_path=str(db_path))

    product_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1001",
            "title": "Alpha Runner",
            "description": "",
            "english_title": "",
            "cnfans_url": "",
            "acbuy_url": "",
            "shop_name": "shop-a",
            "ruleEnabled": True,
            "item_id": "1001",
        }
    )
    image_db_id = test_db.insert_image_record(product_id, "/tmp/a-1.jpg", 0)

    test_db.upsert_product_image_retrieval_cache(
        image_db_id=image_db_id,
        strategy_name="siglip2_rerank",
        cache_version="siglip2_rerank_v1",
        embedding=[0.1, 0.2, 0.3],
        color_hist=[0.4, 0.5, 0.6, 0.7],
        tokens=["alpha", "runner"],
    )

    rows = test_db.get_searchable_product_image_records(strategy_name="siglip2_rerank")

    assert len(rows) == 1
    assert rows[0]["retrieval_cache_strategy"] == "siglip2_rerank"
    assert rows[0]["retrieval_cache_version"] == "siglip2_rerank_v1"
    assert rows[0]["retrieval_embedding"] == "[0.1, 0.2, 0.3]"
    assert rows[0]["retrieval_color_hist"] == "[0.4, 0.5, 0.6, 0.7]"
    assert rows[0]["retrieval_tokens"] == "[\"alpha\", \"runner\"]"


def test_database_counts_missing_retrieval_cache_rows(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    test_db = Database(db_path=str(db_path))

    first_product_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1001",
            "title": "Alpha Runner",
            "description": "",
            "english_title": "",
            "cnfans_url": "",
            "acbuy_url": "",
            "shop_name": "shop-a",
            "ruleEnabled": True,
            "item_id": "1001",
        }
    )
    second_product_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1002",
            "title": "Beta Runner",
            "description": "",
            "english_title": "",
            "cnfans_url": "",
            "acbuy_url": "",
            "shop_name": "shop-b",
            "ruleEnabled": True,
            "item_id": "1002",
        }
    )

    first_image_id = test_db.insert_image_record(first_product_id, "/tmp/a-1.jpg", 0)
    test_db.insert_image_record(second_product_id, "/tmp/b-1.jpg", 0)

    test_db.upsert_product_image_retrieval_cache(
        image_db_id=first_image_id,
        strategy_name="siglip2_rerank",
        cache_version="siglip2_rerank_v1",
        embedding=[0.1, 0.2, 0.3],
        color_hist=None,
        tokens=["alpha"],
    )

    assert test_db.count_product_image_retrieval_cache("siglip2_rerank") == 1
    assert test_db.count_missing_product_image_retrieval_cache("siglip2_rerank") == 1


def test_database_treats_oversized_legacy_cache_rows_as_missing(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    test_db = Database(db_path=str(db_path))

    product_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1003",
            "title": "Gamma Runner",
            "description": "",
            "english_title": "",
            "cnfans_url": "",
            "acbuy_url": "",
            "shop_name": "shop-c",
            "ruleEnabled": True,
            "item_id": "1003",
        }
    )
    image_id = test_db.insert_image_record(product_id, "/tmp/c-1.jpg", 0)

    oversized_embedding = [0.1] * (768 * 196)
    test_db.upsert_product_image_retrieval_cache(
        image_db_id=image_id,
        strategy_name="siglip2_rerank",
        cache_version="siglip2_rerank_v1",
        embedding=oversized_embedding,
        color_hist=None,
        tokens=["gamma"],
    )

    assert test_db.count_product_image_retrieval_cache("siglip2_rerank") == 0
    assert test_db.count_missing_product_image_retrieval_cache("siglip2_rerank") == 1
    assert test_db.get_searchable_product_image_records(
        strategy_name="siglip2_rerank",
        require_cache=True,
    ) == []


def test_database_drops_oversized_optional_retrieval_payloads_from_searchable_records(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    test_db = Database(db_path=str(db_path))

    product_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1004",
            "title": "Delta Runner",
            "description": "",
            "english_title": "",
            "cnfans_url": "",
            "acbuy_url": "",
            "shop_name": "shop-d",
            "ruleEnabled": True,
            "item_id": "1004",
        }
    )
    image_id = test_db.insert_image_record(product_id, "/tmp/d-1.jpg", 0)

    test_db.upsert_product_image_retrieval_cache(
        image_db_id=image_id,
        strategy_name="siglip2_rerank",
        cache_version="siglip2_rerank_v1",
        embedding=[0.1, 0.2, 0.3],
        color_hist=[0.1, 0.2],
        tokens=["delta"],
    )

    oversized_hist = json.dumps([0.1] * 10000)
    oversized_tokens = json.dumps(["delta-runner"] * 5000)
    with test_db.get_connection() as conn:
        conn.execute(
            """
            UPDATE product_image_retrieval_cache
            SET color_hist_json = ?, tokens_json = ?
            WHERE image_db_id = ? AND strategy_name = ?
            """,
            (oversized_hist, oversized_tokens, image_id, "siglip2_rerank"),
        )
        conn.commit()

    rows = test_db.get_searchable_product_image_records(
        strategy_name="siglip2_rerank",
        require_cache=True,
    )

    assert len(rows) == 1
    assert rows[0]["retrieval_embedding"] == "[0.1, 0.2, 0.3]"
    assert rows[0]["retrieval_color_hist"] is None
    assert rows[0]["retrieval_tokens"] is None


def test_database_migrates_legacy_product_images_schema(tmp_path: Path):
    db_path = tmp_path / "legacy-metadata.db"

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_url TEXT UNIQUE NOT NULL,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cursor.execute(
            '''
            CREATE TABLE product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                image_index INTEGER NOT NULL,
                features TEXT,
                milvus_id INTEGER UNIQUE,
                FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
                UNIQUE(product_id, image_index)
            )
            '''
        )
        cursor.execute(
            "INSERT INTO products (id, product_url, title) VALUES (?, ?, ?)",
            (1, "https://weidian.com/item.html?itemID=1001", "Alpha Runner"),
        )
        cursor.execute(
            '''
            INSERT INTO product_images (id, product_id, image_path, image_index, features, milvus_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (7, 1, "/tmp/a-1.jpg", 0, "[0.1, 0.2, 0.3]", 123),
        )
        conn.commit()

    test_db = Database(db_path=str(db_path))

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(product_images)")
        columns = [row[1] for row in cursor.fetchall()]
        assert columns == ["id", "product_id", "image_path", "image_index"]

        cursor.execute("SELECT id, product_id, image_path, image_index FROM product_images")
        rows = cursor.fetchall()
        assert rows == [(7, 1, "/tmp/a-1.jpg", 0)]

    product_images = test_db.get_product_images(1)
    assert product_images == [{"id": 7, "image_path": "/tmp/a-1.jpg", "image_index": 0}]


def test_insert_product_persists_item_id_and_updates_existing_row(tmp_path: Path):
    db_path = tmp_path / "metadata.db"
    test_db = Database(db_path=str(db_path))

    first_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1001",
            "title": "Alpha Runner",
            "description": "v1",
            "english_title": "",
            "cnfans_url": "",
            "acbuy_url": "",
            "shop_name": "shop-a",
            "ruleEnabled": True,
            "item_id": "1001",
        }
    )

    second_id = test_db.insert_product(
        {
            "product_url": "https://weidian.com/item.html?itemID=1001",
            "title": "Alpha Runner Updated",
            "description": "v2",
            "english_title": "Updated",
            "cnfans_url": "https://cnfans.com/product?id=1001&platform=WEIDIAN",
            "acbuy_url": "",
            "shop_name": "shop-b",
            "ruleEnabled": False,
            "item_id": "1001",
        }
    )

    assert second_id == first_id

    product = test_db.get_product_by_item_id("1001")
    assert product is not None
    assert product["id"] == first_id
    assert product["title"] == "Alpha Runner Updated"
    assert product["description"] == "v2"
    assert product["english_title"] == "Updated"
    assert product["shop_name"] == "shop-b"
