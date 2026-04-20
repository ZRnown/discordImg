import base64
import io
import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from types import ModuleType, SimpleNamespace
import sys

@contextmanager
def _noop_context():
    yield

if "torch" not in sys.modules:
    torch_stub = ModuleType("torch")
    torch_stub.float32 = "float32"
    torch_stub.device = lambda value: value
    torch_stub.no_grad = _noop_context
    torch_stub.backends = SimpleNamespace(nnpack=SimpleNamespace(enabled=False))
    sys.modules["torch"] = torch_stub

if "cv2" not in sys.modules:
    sys.modules["cv2"] = ModuleType("cv2")

if "PIL" not in sys.modules:
    pil_stub = ModuleType("PIL")
    pil_image_stub = ModuleType("PIL.Image")
    pil_filter_stub = ModuleType("PIL.ImageFilter")
    pil_image_stub.Image = type("Image", (), {})
    pil_stub.Image = pil_image_stub
    pil_stub.ImageFilter = pil_filter_stub
    sys.modules["PIL"] = pil_stub
    sys.modules["PIL.Image"] = pil_image_stub
    sys.modules["PIL.ImageFilter"] = pil_filter_stub

if "transformers" not in sys.modules:
    transformers_stub = ModuleType("transformers")
    transformers_stub.AutoImageProcessor = object
    transformers_stub.AutoModel = object
    sys.modules["transformers"] = transformers_stub

if "ultralytics" not in sys.modules:
    ultralytics_stub = ModuleType("ultralytics")
    ultralytics_stub.YOLO = object
    sys.modules["ultralytics"] = ultralytics_stub

from backend import app as app_module
from backend import feature_extractor as feature_extractor_module
from backend import live_retrieval as live_retrieval_module

sys.modules.setdefault("feature_extractor", feature_extractor_module)
sys.modules.setdefault("live_retrieval", live_retrieval_module)


def _make_jpeg_bytes():
    # Tiny valid JPEG so the test does not depend on Pillow.
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxISEhUTEhIVFhUVFxUXFhUVFxUVFhUVFRUXFhUVFRUYHSggGBolGxUVITEhJSkrLi4uFx8zODMtNygtLisBCgoKDg0OFw8QFS0dFR0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBIgACEQEDEQH/xAAbAAEAAgMBAQAAAAAAAAAAAAAABQYDBEcCAf/EADYQAAEDAgQDBgQFBQAAAAAAAAEAAgMEEQUSITFBBhMiUWFxgZEUMkKhsdEHFSNCYnKCwdH/xAAYAQEBAQEBAAAAAAAAAAAAAAAAAQIDBP/EAB8RAAICAgEFAAAAAAAAAAAAAAABAhEDIRIxQVFhcf/aAAwDAQACEQMRAD8A9+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//2Q=="
    )


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
                partition_match_enabled BOOLEAN DEFAULT 0,
                partition_match_rules TEXT,
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
            INSERT INTO products (
                id, product_url, title, english_title, title_translations, description,
                ruleEnabled, min_delay, max_delay, created_at, cnfans_url, shop_name,
                custom_reply_text, custom_reply_images, custom_image_urls, image_source,
                reply_scope, per_website_reply_settings, uploaded_reply_images, item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                3,
                "https://weidian.com/item.html?itemID=1407314815541575732",
                "spider sweater knitwear",
                "spider sweater knitwear",
                json.dumps({"en": "spider sweater knitwear"}),
                "demo spider product",
                1,
                1,
                3,
                "2026-04-06 00:00:00",
                None,
                "Store  No.1",
                None,
                None,
                None,
                "product",
                "all",
                None,
                None,
                "1407314815541575732",
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
        self.conn.execute(
            """
            INSERT INTO product_images (id, product_id, image_path, image_index)
            VALUES (?, ?, ?, ?)
            """,
            (3, 3, "/tmp/spider-0.jpg", 0),
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

    def test_search_similar_skips_query_feature_extraction_without_any_filter_images(self):
        class DummyRetriever:
            def search(self, image_path, query_text="", top_k=5, threshold=0.0, user_shops=None):
                return {
                    "strategy": "dummy",
                    "catalog_size": 0,
                    "ranked_products": [],
                    "top1_score": 0.0,
                    "top1_margin": 0.0,
                }

        with patch.object(
            app_module,
            "extract_features",
            side_effect=AssertionError(
                "extract_features should be skipped when there are no filter images"
            ),
        ), patch.object(
            app_module,
            "get_current_user",
            return_value=None,
        ), patch.object(
            app_module,
            "build_user_shop_scope",
            return_value=["Vibeo"],
        ), patch.object(
            app_module.db,
            "has_global_image_filter_images",
            return_value=False,
            create=True,
        ), patch.object(
            app_module.db,
            "has_user_website_filter_images",
            return_value=False,
            create=True,
        ), patch.object(
            app_module.db,
            "get_total_indexed_images",
            return_value=0,
        ), patch(
            "live_retrieval.get_live_image_retriever",
            return_value=DummyRetriever(),
        ), patch(
            "live_retrieval.warm_live_image_retriever",
            return_value={"catalog_size": 0},
        ):
            response = self.client.post(
                "/search_similar",
                data={
                    "threshold": "0.2",
                    "limit": "5",
                    "user_id": "123",
                    "image": (io.BytesIO(b"fake-image-bytes"), "query.jpg"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)

    def test_ai_status_does_not_initialize_feature_extractor(self):
        with (
            patch.object(
                app_module,
                "get_global_feature_extractor",
                side_effect=AssertionError("ai-status should not initialize the model"),
            ),
            patch.object(app_module.db, "get_connection", self._fake_get_connection),
            patch.object(app_module.db, "count_product_image_retrieval_cache", return_value=7),
        ):
            response = self.client.get("/api/system/ai-status")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["ai_model_status"]["initialized"])
        self.assertFalse(data["ai_model_status"]["yolo_available"])
        self.assertEqual(data["retrieval_cache_status"]["total_images"], 3)
        self.assertEqual(data["retrieval_cache_status"]["cached_images"], 7)

    def test_initialize_feature_extractor_reuses_feature_extractor_singleton(self):
        dummy_extractor = object()
        call_state = {"count": 0}

        def fake_extractor_ctor(*args, **kwargs):
            call_state["count"] += 1
            if call_state["count"] == 1:
                return dummy_extractor
            raise AssertionError("feature_extractor singleton should be reused")

        with (
            patch.object(app_module, "feature_extractor_instance", None),
            patch.object(app_module, "feature_extractor_failed_at", 0.0),
            patch.object(feature_extractor_module, "_global_extractor", None),
            patch.object(
                feature_extractor_module,
                "DINOv2FeatureExtractor",
                side_effect=fake_extractor_ctor,
            ),
        ):
            created = app_module.initialize_feature_extractor()
            shared = feature_extractor_module.get_feature_extractor()

        self.assertIs(created, dummy_extractor)
        self.assertIs(shared, dummy_extractor)
        self.assertEqual(call_state["count"], 1)

    def test_search_similar_returns_retryable_when_catalog_is_warming_up(self):
        import live_retrieval as live_retrieval_module

        class WarmableRetriever:
            def __init__(self):
                self.calls = 0

            def search(self, image_path, query_text="", top_k=5, threshold=0.0, user_shops=None):
                self.calls += 1
                raise live_retrieval_module.LiveCatalogPreparingError(
                    "live catalog is warming up"
                )

        warmable_retriever = WarmableRetriever()

        with patch.object(app_module.db, "get_connection", self._fake_get_connection), patch.object(
            app_module,
            "get_current_user",
            return_value=None,
        ), patch.object(
            app_module,
            "build_user_shop_scope",
            return_value=["Store  No.1"],
        ), patch.object(
            app_module.db,
            "has_global_image_filter_images",
            return_value=False,
            create=True,
        ), patch.object(
            app_module.db,
            "has_user_website_filter_images",
            return_value=False,
            create=True,
        ), patch.object(
            app_module.db,
            "get_total_indexed_images",
            return_value=0,
        ), patch.object(
            app_module.db,
            "generate_website_urls",
            return_value=[],
            create=True,
        ), patch.object(
            app_module.db,
            "add_search_history",
            return_value=1,
            create=True,
        ), patch(
            "live_retrieval.get_live_image_retriever",
            return_value=warmable_retriever,
        ) as mock_get_retriever, patch(
            "live_retrieval.warm_live_image_retriever",
            return_value={"catalog_size": 1},
        ) as mock_warm:
            response = self.client.post(
                "/search_similar",
                data={
                    "threshold": "0.2",
                    "limit": "5",
                    "user_id": "123",
                    "image": (io.BytesIO(_make_jpeg_bytes()), "query.jpg"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 503)
        data = response.get_json()
        self.assertTrue(data["retryable"])
        self.assertEqual(data["error"], "search warming up")
        self.assertEqual(warmable_retriever.calls, 1)
        mock_get_retriever.assert_called_once()
        mock_warm.assert_not_called()

    def test_text_search_preserves_shop_name_whitespace_in_scope_filter(self):
        with patch.object(app_module.db, "get_connection", self._fake_get_connection), patch.object(
            app_module,
            "build_user_shop_scope",
            return_value=["1773175595", "Store  No.1"],
        ):
            response = self.client.post(
                "/api/search_similar_text",
                json={
                    "query": "spider sweater knitwear",
                    "limit": 5,
                    "user_id": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["products"][0]["id"], 3)


if __name__ == "__main__":
    unittest.main()
