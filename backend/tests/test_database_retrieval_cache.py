import sqlite3

from backend.database import Database


def test_count_missing_product_image_retrieval_cache_ignores_orphan_images(tmp_path):
    db_path = tmp_path / "metadata.db"
    db = Database(str(db_path))

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO products (
                id, product_url, title, english_title, shop_name, ruleEnabled, reply_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "https://example.com/p/1", "Alpha", "Alpha", "shop-a", 1, "all"),
        )
        cursor.execute(
            """
            INSERT INTO products (
                id, product_url, title, english_title, shop_name, ruleEnabled, reply_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (2, "https://example.com/p/2", "Beta", "Beta", "shop-b", 1, "all"),
        )
        cursor.execute(
            """
            INSERT INTO product_images (id, product_id, image_path, image_index)
            VALUES (?, ?, ?, ?)
            """,
            (11, 1, "/tmp/alpha.jpg", 0),
        )
        cursor.execute(
            """
            INSERT INTO product_images (id, product_id, image_path, image_index)
            VALUES (?, ?, ?, ?)
            """,
            (12, 2, "/tmp/beta.jpg", 0),
        )
        cursor.execute(
            """
            INSERT INTO product_image_retrieval_cache (
                image_db_id, strategy_name, cache_version, embedding_json
            ) VALUES (?, ?, ?, ?)
            """,
            (11, "siglip2_rerank", "siglip2_rerank_v1", "[0.1, 0.2, 0.3]"),
        )
        conn.commit()

    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            """
            INSERT INTO product_images (id, product_id, image_path, image_index)
            VALUES (?, ?, ?, ?)
            """,
            (13, 9999, "/tmp/orphan.jpg", 0),
        )
        conn.commit()

    assert db.count_missing_product_image_retrieval_cache("siglip2_rerank") == 1
    assert (
        db.count_searchable_product_image_records(
            strategy_name="siglip2_rerank",
            require_cache=False,
            only_missing_cache=True,
        )
        == 1
    )

    rows = db.get_searchable_product_image_records(
        strategy_name="siglip2_rerank",
        require_cache=False,
        only_missing_cache=True,
    )
    assert [row["image_db_id"] for row in rows] == [12]
